"""Checkpoint-driven ReAct scheduling for one durable Figura Run."""

from __future__ import annotations

from contextlib import nullcontext
from collections.abc import Mapping
from dataclasses import replace
import time
import uuid
from datetime import datetime, timezone
from figura.providers.models import ProviderOptions
from figura.shared.payloads import payload_scope, encode_json

from figura.runtime.models import PREPARATION_MESSAGES
from figura.providers import ProviderFactory, ProviderResponse
from figura.providers.errors import ProviderCallError, ProviderFailureCode
from figura.providers.retries import retry_deadline
from figura.runtime.coordinator import RunCoordinator
from figura.runtime.errors import RunError, RunErrorCode
from figura.runtime.persistence.controls import RunStopRequested
from figura.runtime.models import ActionKind, RunStatus, TerminalCode, ToolFactKind
from figura.runtime.records import (
    ModelResponseFact,
    RunState,
    ProviderRequestBinding,
    SessionContextCheckpoint,
    ToolAttemptStartedFact,
    ToolCallFact,
)
from .context_compaction import eligible_compaction_runs, validate_summary_response
from figura.runtime.tool_execution import DurableToolExecutor
from figura.runtime.run_lock import PerRunExecutionLock, RunExecutionOwnership, RunExecutionLockUnavailable

from .request import AgentRequestBuilder
from figura.tools.contracts import ToolOutcomeUnknown


class AgentExecutor:
    """Advance the action currently named by a Run's durable checkpoint."""

    __slots__ = ("_coordinator", "_provider_factory", "_tools", "_lock", "_requests", "_owner")

    def __init__(
        self,
        coordinator: RunCoordinator,
        provider_factory: ProviderFactory,
        tools: DurableToolExecutor,
        execution_lock: PerRunExecutionLock,
        request_builder: AgentRequestBuilder,
    ) -> None:
        if not isinstance(coordinator, RunCoordinator):
            raise TypeError("coordinator must be a RunCoordinator")
        if not isinstance(tools, DurableToolExecutor):
            raise TypeError("tools must be a DurableToolExecutor")
        if not isinstance(execution_lock, PerRunExecutionLock):
            raise TypeError("execution_lock must be a PerRunExecutionLock")
        if not isinstance(request_builder, AgentRequestBuilder):
            raise TypeError("request_builder must be an AgentRequestBuilder")
        object.__setattr__(self, "_coordinator", coordinator)
        object.__setattr__(self, "_provider_factory", provider_factory)
        object.__setattr__(self, "_tools", tools)
        object.__setattr__(self, "_lock", execution_lock)
        object.__setattr__(self, "_requests", request_builder)
        object.__setattr__(self, "_owner", RunExecutionOwnership(coordinator.data_root))

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("AgentExecutor is immutable")

    @property
    def coordinator(self) -> RunCoordinator:
        return self._coordinator

    @property
    def payload_limits(self):
        return self._coordinator.payload_limits

    def execute(self, session_id: str, run_id: str) -> RunState:
        """Synchronous driver waits outside ownership and never holds a worker during backoff."""
        while True:
            before = self._coordinator.read_run_state(session_id, run_id)
            state = self.execute_slice(session_id, run_id)
            if state.run.status is not RunStatus.RUNNING:
                return state
            action = state.checkpoint.next_action
            if state.checkpoint.revision == before.checkpoint.revision and self.is_ready(state):
                return state
            if action and action.action_kind is ActionKind.PROVIDER_RETRY:
                if state.stop_request is None and not self.is_ready(state):
                    time.sleep(min(0.1, self.retry_delay(state)))
                continue
            if state.checkpoint.revision == before.checkpoint.revision:
                return state

    @staticmethod
    def retry_delay(state: RunState) -> float:
        if not state.provider_attempts or state.provider_attempts[-1].next_eligible_at is None:
            return 0.0
        due = datetime.fromisoformat(state.provider_attempts[-1].next_eligible_at.replace("Z", "+00:00"))
        return max(0.0, (due - datetime.now(timezone.utc)).total_seconds())

    @classmethod
    def is_ready(cls, state: RunState) -> bool:
        return state.stop_request is not None or cls.retry_delay(state) == 0

    @payload_scope
    def execute_slice(self, session_id: str, run_id: str) -> RunState:
        try:
            with self._owner.acquire(run_id):
                try:
                    return self._execute_owned(session_id, run_id)
                except RunStopRequested:
                    return self._stop_owned(self._coordinator.read_run_state(session_id, run_id))
                except RunError as error:
                    if error.code in {RunErrorCode.STALE_CHECKPOINT, RunErrorCode.INVALID_TRANSITION}:
                        return self._coordinator.read_run_state(session_id, run_id)
                    if error.code in {RunErrorCode.INTEGRITY_ERROR, RunErrorCode.STORAGE_ERROR,
                                      RunErrorCode.UNSUPPORTED_VERSION, RunErrorCode.RUN_NOT_FOUND}:
                        raise
                    return self._close_unexpected(session_id, run_id)
                except ToolOutcomeUnknown:
                    return self._coordinator.read_run_state(session_id, run_id)
                except Exception:
                    return self._close_unexpected(session_id, run_id)
        except RunExecutionLockUnavailable:
            return self._coordinator.read_run_state(session_id, run_id)

    def _close_unexpected(self, session_id: str, run_id: str) -> RunState:
        state = self._coordinator.read_run_state(session_id, run_id)
        if state.run.status is not RunStatus.RUNNING:
            return state
        if state.stop_request is not None:
            return self._stop_owned(state)
        action = state.checkpoint.next_action
        if action.action_kind is ActionKind.PROVIDER_ATTEMPT:
            return self._resolve_provider_attempt(state)
        if action.action_kind is ActionKind.TOOL_ATTEMPT:
            return self._recover_tool_attempt(state)
        return self._fail_run(state)

    def _stop_owned(self, state: RunState) -> RunState:
        if state.run.status is RunStatus.RUNNING:
            with self._lock.acquire(state.run.run_id):
                state = self._coordinator.read_run_state(state.run.session_id, state.run.run_id)
                if state.run.status is RunStatus.RUNNING:
                    self._coordinator._interrupt_owned_run(
                        state.run.session_id, state.run.run_id, state.checkpoint.revision,
                    )
        return self._coordinator.read_run_state(state.run.session_id, state.run.run_id)

    def _recover_tool_attempt(self, state: RunState) -> RunState:
        action = state.checkpoint.next_action
        attempt = next((fact.payload for fact in state.tool_facts
                        if isinstance(fact.payload, ToolAttemptStartedFact)
                        and fact.payload.attempt_id == action.attempt_id), None)
        call = next((fact.payload for fact in state.tool_facts
                     if isinstance(fact.payload, ToolCallFact)
                     and fact.tool_sequence == action.tool_call_sequence), None)
        definition = self._tools.registry.get(call.tool_name) if call is not None else None
        if attempt is None or definition is None or attempt.registry_version != self._tools.registry.version:
            return self._fail_run(state, TerminalCode.TOOL_RECOVERY_UNAVAILABLE)
        if definition.replay_effect != attempt.replay_effect:
            return self._fail_run(state, TerminalCode.TOOL_RECOVERY_UNAVAILABLE)
        if attempt.replay_effect.value == "reconcile_required":
            return self._fail_run(state, TerminalCode.TOOL_OUTCOME_UNKNOWN)
        if attempt.attempt_number >= 3:
            return self._fail_run(state, TerminalCode.TOOL_RECOVERY_EXHAUSTED)
        return self._tools.recover_owned_attempt(state.run.session_id, state.run.run_id)

    def _execute_owned(self, session_id: str, run_id: str) -> RunState:
        """Advance until terminal, externally unresolved, or another owner holds the Run."""
        state = self._coordinator.read_run_state(session_id, run_id)
        if state.run.status is RunStatus.RUNNING:
            state = self._coordinator.read_run_state(session_id, run_id)
            if state.stop_request is not None:
                return self._stop_owned(state)
            if state.run.status is not RunStatus.RUNNING:
                return state
            action = state.checkpoint.next_action
            if action is None:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            if action.action_kind in {ActionKind.MODEL, ActionKind.PROVIDER_RETRY}:
                next_state = self._execute_model_action(state)
            elif action.action_kind is ActionKind.TOOL_EXECUTION:
                next_state = self._execute_tool_action(state)
            elif action.action_kind is ActionKind.TOOL_ATTEMPT:
                next_state = self._recover_tool_attempt(state)
            elif action.action_kind is ActionKind.PROVIDER_ATTEMPT:
                next_state = self._resolve_provider_attempt(state)
            elif action.action_kind is ActionKind.FINAL:
                next_state = self._finalize(state)
            else:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)

            if (
                next_state.run.status is RunStatus.RUNNING
                and next_state.checkpoint.revision == state.checkpoint.revision
                and next_state.checkpoint.next_action == state.checkpoint.next_action
            ):
                return next_state
            return next_state
        return state

    def _execute_model_action(self, state: RunState) -> RunState:
        session_id, run_id = state.run.session_id, state.run.run_id
        if not self.is_ready(state):
            return state
        binding = None
        if state.checkpoint.next_action.action_kind is ActionKind.PROVIDER_RETRY:
            last = state.provider_attempts[-1]
            binding = next((item for item in state.provider_request_bindings if item.operation_id == last.operation_id), None)
            if binding is None:
                return self._fail_run(state)
        try:
            prior_run_states = self._coordinator.read_prior_run_states(session_id, run_id)
            context_projection = "full"
            context_checkpoint_revision = None
            context_compaction_operation_id = None
            if binding is not None:
                context_checkpoint = self._checkpoint_for_binding(binding, session_id)
                request = self._requests.build(
                    state,
                    self._tools.registry,
                    prior_run_states,
                    context_checkpoint=context_checkpoint,
                )
                request = replace(
                    request,
                    options=ProviderOptions(**{
                        key: value for key, value in binding.options.items()
                        if key != "timeout_seconds"
                    }),
                )
                context_projection = binding.context_projection
                context_checkpoint_revision = binding.context_checkpoint_revision
                context_compaction_operation_id = binding.context_compaction_operation_id
            else:
                context_checkpoint = self._coordinator.read_session_context_checkpoint(session_id)
                request = self._requests.build(
                    state,
                    self._tools.registry,
                    prior_run_states,
                    context_checkpoint=context_checkpoint,
                )
                if context_checkpoint is not None:
                    context_projection = "checkpoint"
                    context_checkpoint_revision = context_checkpoint.revision
                    context_compaction_operation_id = context_checkpoint.compaction_operation_id
        except RunError:
            return self._fail_run(state)

        try:
            client = self._provider_factory.create(state.run.provider, state.run.model)
        except Exception:
            return self._fail_run(state)

        try:
            try:
                if binding is not None:
                    prepared = client.prepare(
                        request,
                        frozen_options=True,
                        frozen_timeout_seconds=binding.options["timeout_seconds"],
                        estimate_context=False,
                    )
                else:
                    prepared = client.prepare(request)
                    estimate = getattr(prepared, "context_estimate", None)
                    if (
                        estimate is not None
                        and estimate.context_window_tokens is not None
                        and estimate.input_tokens / estimate.context_window_tokens >= 0.8
                    ):
                        (
                            context_checkpoint,
                            context_projection,
                            context_compaction_operation_id,
                        ) = self._compact_context_if_possible(
                            client,
                            state,
                            prior_run_states,
                            context_checkpoint,
                        )
                        context_checkpoint_revision = (
                            context_checkpoint.revision
                            if context_projection == "checkpoint" and context_checkpoint is not None
                            else None
                        )
                        request = self._requests.build(
                            state,
                            self._tools.registry,
                            prior_run_states,
                            context_checkpoint=(
                                context_checkpoint
                                if context_projection == "checkpoint"
                                else None
                            ),
                        )
                        prepared = client.prepare(request)
                        if context_projection == "checkpoint":
                            context_checkpoint_revision = context_checkpoint.revision
                descriptor = prepared.descriptor
                if binding:
                    if any(descriptor[key] != getattr(binding, key) for key in ("provider_id", "model_id", "endpoint_binding", "request_fingerprint")) or descriptor["asset_manifest"] != binding.asset_manifest:
                        return self._fail_run(state)
                else:
                    binding = ProviderRequestBinding(operation_id=uuid.uuid4().hex, run_id=run_id,
                        base_record_sequence=state.checkpoint.last_committed_record_sequence,
                        base_tool_sequence=state.checkpoint.last_committed_tool_sequence,
                        schema_version=3, context_estimate=getattr(prepared, "context_estimate", None),
                        context_projection=context_projection,
                        context_checkpoint_revision=context_checkpoint_revision,
                        context_compaction_operation_id=context_compaction_operation_id,
                        created_at=datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"), **descriptor)
            except ProviderCallError as error:
                return self._fail_run(state, terminal_message=_preparation_failure_message(error))
            except RunStopRequested:
                raise
            except Exception:
                return self._fail_run(state)

            with self._lock.acquire(run_id):
                current = self._coordinator.read_run_state(session_id, run_id)
                if current.stop_request is not None:
                    self._coordinator._interrupt_owned_run(
                        session_id, run_id, current.checkpoint.revision,
                    )
                    return self._coordinator.read_run_state(session_id, run_id)
                if (
                    current.run.status is not RunStatus.RUNNING
                    or current.checkpoint.revision != state.checkpoint.revision
                    or current.checkpoint.next_action != state.checkpoint.next_action
                ):
                    return current

                attempt = self._coordinator.begin_provider_attempt(
                    session_id, run_id, current.checkpoint.revision, binding=binding
                )
                claimed = self._coordinator.read_run_state(session_id, run_id)
                try:
                    response = client.dispatch(prepared)
                except ProviderCallError as error:
                    self._coordinator.fail_provider_attempt(
                        session_id,
                        run_id,
                        claimed.checkpoint.revision,
                        attempt.attempt_id,
                        outcome_unknown=not error.failure.outcome_known,
                        failure_code=error.failure.failure_code.value,
                        transient=error.failure.transient and not request.options.stream,
                        http_status=error.failure.http_status, retry_after_seconds=error.failure.retry_after_seconds,
                        failure_category=error.failure.category,
                    )
                    return self._coordinator.read_run_state(session_id, run_id)
                except Exception:
                    self._coordinator.fail_provider_attempt(
                        session_id,
                        run_id,
                        claimed.checkpoint.revision,
                        attempt.attempt_id,
                        outcome_unknown=True,
                        failure_code=None,
                    )
                    return self._coordinator.read_run_state(session_id, run_id)

                try:
                    self._coordinator.commit_model_response(
                        session_id,
                        run_id,
                        claimed.checkpoint.revision,
                        response,
                        provider_attempt_id=attempt.attempt_id,
                        registry_version=self._tools.registry.version,
                    )
                except RunError as error:
                    if error.code not in {
                        RunErrorCode.UNSUPPORTED_PAYLOAD,
                        RunErrorCode.UNSUPPORTED_VERSION,
                    }:
                        raise
                    self._coordinator.fail_provider_attempt(
                        session_id,
                        run_id,
                        claimed.checkpoint.revision,
                        attempt.attempt_id,
                        outcome_unknown=False,
                        failure_code=ProviderFailureCode.INVALID_PROVIDER_RESPONSE.value,
                    )
                    return self._coordinator.read_run_state(session_id, run_id)

                committed = self._coordinator.read_run_state(session_id, run_id)
                if not _accepted_provider_response(response):
                    return self._fail_run(committed, TerminalCode.INVALID_RESPONSE, action_owned=True)
                return committed
        except RunExecutionLockUnavailable:
            return self._coordinator.read_run_state(session_id, run_id)
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

    def _checkpoint_for_binding(
        self, binding: ProviderRequestBinding, session_id: str
    ) -> SessionContextCheckpoint | None:
        if binding.schema_version < 3 or binding.context_projection in {"full", "fallback"}:
            if binding.context_projection == "fallback":
                operation = self._coordinator.read_context_compaction_operation(
                    binding.context_compaction_operation_id
                )
                if operation.status != "fallback":
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
            return None
        if binding.context_projection != "checkpoint":
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        checkpoint = self._coordinator.read_session_context_checkpoint(session_id)
        if (
            checkpoint is None
            or checkpoint.revision != binding.context_checkpoint_revision
            or checkpoint.compaction_operation_id != binding.context_compaction_operation_id
        ):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        operation = self._coordinator.read_context_compaction_operation(
            binding.context_compaction_operation_id
        )
        if (
            operation.status != "completed"
            or operation.result_checkpoint_revision != checkpoint.revision
        ):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        return checkpoint

    def _compact_context_if_possible(
        self,
        client,
        state: RunState,
        prior_run_states: tuple[RunState, ...],
        previous_checkpoint: SessionContextCheckpoint | None,
    ) -> tuple[SessionContextCheckpoint | None, str, str | None]:
        checkpoint_ordinal = (
            previous_checkpoint.covered_run_ordinal if previous_checkpoint else 0
        )
        selected_runs = eligible_compaction_runs(prior_run_states, checkpoint_ordinal)
        if not selected_runs:
            return (
                previous_checkpoint,
                "checkpoint" if previous_checkpoint is not None else "full",
                previous_checkpoint.compaction_operation_id if previous_checkpoint else None,
            )

        covered = selected_runs[-1]
        operation = self._coordinator.get_or_create_context_compaction_operation(
            session_id=state.run.session_id,
            target_run_id=state.run.run_id,
            base_record_sequence=state.checkpoint.last_committed_record_sequence,
            base_tool_sequence=state.checkpoint.last_committed_tool_sequence,
            input_checkpoint_revision=(previous_checkpoint.revision if previous_checkpoint else 0),
            covered_run_id=covered.run.run_id,
            covered_run_ordinal=covered.run.ordinal,
            covered_record_sequence=covered.checkpoint.last_committed_record_sequence,
            covered_tool_sequence=covered.checkpoint.last_committed_tool_sequence,
        )
        if operation.status == "completed":
            checkpoint = self._coordinator.read_session_context_checkpoint(state.run.session_id)
            if (
                checkpoint is None
                or checkpoint.compaction_operation_id != operation.operation_id
                or checkpoint.revision != operation.result_checkpoint_revision
            ):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            return checkpoint, "checkpoint", operation.operation_id
        if operation.status == "fallback":
            return None, "fallback", operation.operation_id
        if operation.status != "preparing":
            raise RunError(RunErrorCode.INTEGRITY_ERROR)

        try:
            summary_request, allowed_refs = self._requests.build_summary_request(
                state, selected_runs, previous_checkpoint
            )
        except (TypeError, ValueError):
            self._coordinator.fallback_context_compaction_operation(
                operation.operation_id, "invalid_summary_input"
            )
            return None, "fallback", operation.operation_id

        request_binding = operation.request_binding
        try:
            if request_binding is None:
                prepared = client.prepare(summary_request)
                descriptor = prepared.descriptor
                request_binding = {
                    "descriptor": dict(descriptor),
                    "summary_contract_version": 2,
                }
                operation = self._coordinator.bind_context_compaction_request(
                    operation.operation_id, request_binding
                )
            else:
                if request_binding.get("summary_contract_version") != 2:
                    raise ValueError("saved summary contract version changed")
                descriptor = request_binding.get("descriptor")
                if not isinstance(descriptor, Mapping):
                    raise ValueError("invalid saved summary request binding")
                options = descriptor.get("options")
                if not isinstance(options, Mapping):
                    raise ValueError("invalid saved summary options")
                frozen_request = replace(
                    summary_request,
                    options=ProviderOptions(**{
                        key: value for key, value in options.items()
                        if key != "timeout_seconds"
                    }),
                )
                prepared = client.prepare(
                    frozen_request,
                    frozen_options=True,
                    frozen_timeout_seconds=options["timeout_seconds"],
                    estimate_context=False,
                )
                if encode_json(prepared.descriptor) != encode_json(descriptor):
                    raise ValueError("summary request identity changed")
        except ProviderCallError as error:
            self._coordinator.fallback_context_compaction_operation(
                operation.operation_id, error.failure.failure_code.value
            )
            return None, "fallback", operation.operation_id
        except (TypeError, ValueError, KeyError):
            self._coordinator.fallback_context_compaction_operation(
                operation.operation_id, "summary_binding_mismatch"
            )
            return None, "fallback", operation.operation_id

        while True:
            latest = self._coordinator.read_run_state(
                state.run.session_id, state.run.run_id
            )
            if latest.stop_request is not None:
                raise RunStopRequested()
            operation = self._coordinator.read_context_compaction_operation(
                operation.operation_id
            )
            if operation.attempt_count >= 4:
                self._coordinator.fallback_context_compaction_operation(
                    operation.operation_id, "summary_attempts_exhausted"
                )
                return None, "fallback", operation.operation_id
            attempt_number = self._coordinator.begin_context_compaction_attempt(
                operation.operation_id
            )
            try:
                response = client.dispatch(prepared)
            except ProviderCallError as error:
                if error.failure.transient and attempt_number < 4:
                    due = datetime.fromisoformat(
                        retry_deadline(attempt_number, error.failure.retry_after_seconds).replace(
                            "Z", "+00:00"
                        )
                    )
                    while datetime.now(timezone.utc) < due:
                        latest = self._coordinator.read_run_state(
                            state.run.session_id, state.run.run_id
                        )
                        if latest.stop_request is not None:
                            raise RunStopRequested()
                        time.sleep(min(0.1, max(0.0, (due - datetime.now(timezone.utc)).total_seconds())))
                    continue
                self._coordinator.fallback_context_compaction_operation(
                    operation.operation_id, error.failure.failure_code.value
                )
                return None, "fallback", operation.operation_id
            except Exception:
                self._coordinator.fallback_context_compaction_operation(
                    operation.operation_id, "summary_transport_error"
                )
                return None, "fallback", operation.operation_id

            try:
                summary, summary_refs = validate_summary_response(
                    response,
                    provider_id=state.run.provider,
                    model_id=state.run.model,
                    allowed_refs=allowed_refs,
                    selected_runs=selected_runs,
                )
            except (TypeError, ValueError):
                self._coordinator.fallback_context_compaction_operation(
                    operation.operation_id, "invalid_summary_response"
                )
                return None, "fallback", operation.operation_id

            if previous_checkpoint is not None:
                prior_outcomes = previous_checkpoint.summary.get("run_outcomes", ())
                if isinstance(prior_outcomes, (tuple, list)):
                    summary["run_outcomes"] = [*prior_outcomes, *summary["run_outcomes"]]

            source_refs = tuple(dict.fromkeys((
                *(previous_checkpoint.source_refs if previous_checkpoint else ()),
                *summary_refs,
            )))
            checkpoint = SessionContextCheckpoint(
                session_id=state.run.session_id,
                revision=(previous_checkpoint.revision + 1 if previous_checkpoint else 1),
                covered_run_id=covered.run.run_id,
                covered_run_ordinal=covered.run.ordinal,
                covered_record_sequence=covered.checkpoint.last_committed_record_sequence,
                covered_tool_sequence=covered.checkpoint.last_committed_tool_sequence,
                summary_contract_version=2,
                summary=summary,
                source_refs=source_refs,
                compaction_operation_id=operation.operation_id,
            )
            latest = self._coordinator.read_run_state(
                state.run.session_id, state.run.run_id
            )
            if latest.stop_request is not None:
                raise RunStopRequested()
            try:
                checkpoint = self._coordinator.replace_session_context_checkpoint(
                    checkpoint,
                    expected_revision=(previous_checkpoint.revision if previous_checkpoint else 0),
                )
            except RunError as error:
                if error.code is RunErrorCode.UNSUPPORTED_PAYLOAD:
                    self._coordinator.fallback_context_compaction_operation(
                        operation.operation_id, "invalid_summary_checkpoint"
                    )
                    return None, "fallback", operation.operation_id
                raise
            return checkpoint, "checkpoint", operation.operation_id

    def _execute_tool_action(self, state: RunState) -> RunState:
        action = state.checkpoint.next_action
        if action is None or type(action.tool_call_sequence) is not int:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        call = next(
            (
                fact.payload
                for fact in state.tool_facts
                if fact.tool_sequence == action.tool_call_sequence
                and fact.fact_kind is ToolFactKind.TOOL_CALL
                and isinstance(fact.payload, ToolCallFact)
            ),
            None,
        )
        if call is None:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if (
            call.registry_version != self._tools.registry.version
            or self._tools.registry.get(call.tool_name) is None
        ):
            return self._fail_run(state)

        try:
            progressed = self._tools.execute_owned_pending(
                state.run.session_id,
                state.run.run_id,
                max_calls=1,
            )
        except RunStopRequested:
            raise
        except RunError as error:
            if error.code in {
                RunErrorCode.STORAGE_ERROR, RunErrorCode.INTEGRITY_ERROR,
                RunErrorCode.UNSUPPORTED_VERSION, RunErrorCode.RUN_NOT_FOUND,
            }:
                raise
            current = self._coordinator.read_run_state(state.run.session_id, state.run.run_id)
            if (
                current.run.status is not RunStatus.RUNNING
                or current.checkpoint.revision != state.checkpoint.revision
                or current.checkpoint.next_action != state.checkpoint.next_action
                or (
                    current.checkpoint.next_action is not None
                    and current.checkpoint.next_action.action_kind is ActionKind.TOOL_ATTEMPT
                )
            ):
                return current
            if error.code is RunErrorCode.INVALID_TRANSITION:
                return current
            raise
        except Exception:
            current = self._coordinator.read_run_state(state.run.session_id, state.run.run_id)
            if (
                current.checkpoint.next_action is not None
                and current.checkpoint.next_action.action_kind is ActionKind.TOOL_ATTEMPT
            ):
                return current
            raise

        return progressed

    def _resolve_provider_attempt(self, state: RunState) -> RunState:
        try:
            return self._coordinator._resolve_owned_provider_attempt(
                state.run.session_id, state.run.run_id
            )
        except RunStopRequested:
            raise
        except RunError as error:
            current = self._coordinator.read_run_state(state.run.session_id, state.run.run_id)
            if error.code is RunErrorCode.INVALID_TRANSITION:
                return current
            raise

    def _finalize(self, state: RunState) -> RunState:
        action = state.checkpoint.next_action
        response = next(
            (
                record.payload
                for record in state.records
                if record.record_id == (action.response_record_id if action is not None else None)
            ),
            None,
        )
        if (
            not isinstance(response, ModelResponseFact)
            or response.finish_reason != "stop"
            or not response.assistant_content.strip()
        ):
            return self._fail_run(state, TerminalCode.INVALID_RESPONSE)
        try:
            with self._lock.acquire(state.run.run_id):
                self._coordinator._complete_owned_run(
                    state.run.session_id,
                    state.run.run_id,
                    state.checkpoint.revision,
                )
        except RunStopRequested:
            raise
        except RunError as error:
            current = self._coordinator.read_run_state(state.run.session_id, state.run.run_id)
            if current.checkpoint.revision != state.checkpoint.revision:
                return current
            if error.code is RunErrorCode.INVALID_TRANSITION:
                return self._fail_run(current, TerminalCode.INVALID_RESPONSE)
            raise
        return self._coordinator.read_run_state(state.run.session_id, state.run.run_id)

    def _fail_run(
        self,
        state: RunState,
        terminal_code: TerminalCode = TerminalCode.EXECUTION_FAILED,
        *,
        terminal_message: str | None = None,
        action_owned: bool = False,
    ) -> RunState:
        try:
            with nullcontext() if action_owned else self._lock.acquire(state.run.run_id):
                self._coordinator._fail_owned_run(
                    state.run.session_id,
                    state.run.run_id,
                    state.checkpoint.revision,
                    terminal_code,
                    terminal_message=terminal_message,
                )
        except RunExecutionLockUnavailable:
            return self._coordinator.read_run_state(state.run.session_id, state.run.run_id)
        except RunError as error:
            if error.code not in {RunErrorCode.STALE_CHECKPOINT, RunErrorCode.INVALID_TRANSITION}:
                raise
        return self._coordinator.read_run_state(state.run.session_id, state.run.run_id)


def _accepted_provider_response(response: object) -> bool:
    if not isinstance(response, ProviderResponse):
        return False
    if response.finish_reason.value == "tool_calls":
        return bool(response.tool_calls)
    return (
        response.finish_reason.value == "stop"
        and not response.tool_calls
        and bool(response.assistant_content.strip())
    )


def _preparation_failure_message(error: ProviderCallError) -> str | None:
    failure = error.failure
    key = failure.failure_code.value
    if key == "invalid_request" and failure.safe_message == (
        "DeepSeek thinking 模式的工具历史必须包含 reasoning continuation。"
    ):
        key = "missing_deepseek_continuation"
    return PREPARATION_MESSAGES.get(key)
