"""Checkpoint-driven ReAct scheduling for one durable Figura Run."""

from __future__ import annotations

from contextlib import nullcontext
from collections.abc import Mapping
from dataclasses import replace
import time
import uuid
import logging
from datetime import datetime, timezone
from threading import Event, Thread
from types import MappingProxyType
from figura.providers.models import ProviderOptions, ProviderStreamEventKind
from figura.shared.payloads import PayloadError, payload_scope, encode_json

from figura.runtime.models import PREPARATION_MESSAGES
from figura.providers import ProviderFactory, ProviderId, ProviderResponse
from figura.providers.errors import ProviderCallError, ProviderFailureCode
from figura.runtime.coordinator import RunCoordinator
from figura.runtime.errors import RunError, RunErrorCode
from figura.runtime.persistence.controls import RunStopRequested
from figura.runtime.models import ActionKind, RunStatus, TerminalCode, ToolFactKind
from figura.runtime.records import (
    ModelResponseFact,
    RunState,
    ProviderRequestRecord,
    SessionContextCheckpoint,
    ToolAttemptStartedFact,
    ToolCallFact,
)
from .context_compaction import (
    SummaryValidationError,
    calculate_context_history_budgets,
    estimate_protected_raw_history_tokens,
    legacy_input_reconciliation_selection,
    select_compaction_coverage,
    selection_for_coverage,
    validate_summary_response,
)
from figura.runtime.tool_execution import DurableToolExecutor
from figura.runtime.run_lock import PerRunExecutionLock, RunExecutionOwnership, RunExecutionLockUnavailable

from .request import AgentRequestBuilder
from .context_accounting import account_request_context
from figura.tools.contracts import ToolOutcomeUnknown


_LOGGER = logging.getLogger(__name__)


class AgentExecutor:
    """Advance the action currently named by a Run's durable checkpoint."""

    __slots__ = ("_coordinator", "_provider_factory", "_tools", "_lock", "_requests", "_owner", "_stream_sink")

    def __init__(
        self,
        coordinator: RunCoordinator,
        provider_factory: ProviderFactory,
        tools: DurableToolExecutor,
        execution_lock: PerRunExecutionLock,
        request_builder: AgentRequestBuilder,
        stream_sink=None,
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
        object.__setattr__(self, "_stream_sink", stream_sink)

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
        logical_request = None
        pending_compaction = None
        request_context_projection = None
        try:
            prior_run_states = self._coordinator.read_prior_run_states(session_id, run_id)
            retrying = state.checkpoint.next_action.action_kind is ActionKind.PROVIDER_RETRY
            if retrying:
                previous_attempt = state.provider_attempts[-1]
                logical_request = next(
                    (item for item in state.provider_requests if item.request_id == previous_attempt.request_id),
                    None,
                )
                if logical_request is None or logical_request.purpose != "agent_turn":
                    return self._fail_run(state)
                context_checkpoint = self._checkpoint_for_request(logical_request, session_id)
                stored_policy_version = logical_request.asset_manifest.get(
                    "context_policy_version", 1
                )
                stored_directory_budget = logical_request.asset_manifest.get(
                    "directory_budget_tokens"
                )
                request, request_context_projection = self._requests.build_with_projection(
                    state, self._tools.registry, prior_run_states,
                    context_checkpoint=context_checkpoint,
                    directory_budget_tokens=stored_directory_budget,
                    context_policy_version=stored_policy_version,
                )
                request = replace(request, options=ProviderOptions(
                    max_completion_tokens=logical_request.options["max_completion_tokens"],
                    thinking_mode=logical_request.options["thinking_mode"],
                    reasoning_effort=logical_request.options["reasoning_effort"],
                    schema_version=2,
                ))
                context_projection = logical_request.context_projection
                context_checkpoint_revision = logical_request.context_checkpoint_revision
                context_compaction_operation_id = logical_request.context_checkpoint_operation_id
            else:
                context_checkpoint = self._coordinator.read_session_context_checkpoint(session_id)
                pending_compaction = self._coordinator.find_context_compaction_operation(
                    session_id, run_id,
                    state.checkpoint.last_committed_record_sequence,
                    state.checkpoint.last_committed_tool_sequence,
                )
                request, request_context_projection = self._requests.build_with_projection(
                    state, self._tools.registry, prior_run_states,
                    context_checkpoint=context_checkpoint,
                    context_policy_version=2,
                )
                context_projection = "checkpoint" if context_checkpoint is not None else "full"
                context_checkpoint_revision = context_checkpoint.revision if context_checkpoint else None
                context_compaction_operation_id = context_checkpoint.compaction_operation_id if context_checkpoint else None
        except RunError:
            return self._fail_run(state)

        try:
            client = self._provider_factory.create(state.run.provider, state.run.model)
        except Exception:
            return self._fail_run(state)

        try:
            try:
                if logical_request is not None:
                    timeout_policy = {
                        key: logical_request.options[key]
                        for key in ("connect_timeout_seconds", "write_timeout_seconds")
                    }
                    prepared = client.prepare(
                        request, frozen_options=True,
                        frozen_timeout_policy=timeout_policy,
                        estimate_context=False,
                    )
                    if not _request_matches_prepared(logical_request, prepared.descriptor):
                        return self._fail_run(state)
                else:
                    prepared = client.prepare(request)
                    estimate = prepared.context_estimate
                    should_resume_compaction = pending_compaction is not None and pending_compaction.status == "preparing"
                    accounting = account_request_context(
                        request, request_context_projection, estimate
                    )
                    _log_context_accounting(accounting)
                    directory_budget_tokens = None
                    mandatory_directory_tokens = None
                    protected_raw_tokens = None
                    triggered = _context_pressure_reached(estimate)
                    if triggered and not should_resume_compaction:
                        mandatory_directory_tokens = self._requests.mandatory_directory_tokens(
                            state, prior_run_states, context_checkpoint
                        )
                        protected_raw_tokens = estimate_protected_raw_history_tokens(
                            prior_run_states, state, context_checkpoint
                        )
                        if (
                            mandatory_directory_tokens is not None
                            and protected_raw_tokens is not None
                        ):
                            budgets = calculate_context_history_budgets(
                                estimate.context_window_tokens,
                                accounting=accounting,
                                mandatory_directory_tokens=mandatory_directory_tokens,
                                protected_raw_tokens=protected_raw_tokens,
                            )
                            if budgets is not None and budgets.directory_tokens is not None:
                                directory_budget_tokens = budgets.directory_tokens
                                request, request_context_projection = self._requests.build_with_projection(
                                    state,
                                    self._tools.registry,
                                    prior_run_states,
                                    context_checkpoint=context_checkpoint,
                                    directory_budget_tokens=directory_budget_tokens,
                                    context_policy_version=2,
                                )
                                prepared = client.prepare(request)
                                estimate = prepared.context_estimate
                                accounting = account_request_context(
                                    request, request_context_projection, estimate
                                )
                                _log_context_accounting(accounting)
                                triggered = _context_pressure_reached(estimate)

                    if should_resume_compaction or triggered:
                        if mandatory_directory_tokens is None:
                            mandatory_directory_tokens = self._requests.mandatory_directory_tokens(
                                state, prior_run_states, context_checkpoint
                            )
                        if protected_raw_tokens is None:
                            protected_raw_tokens = estimate_protected_raw_history_tokens(
                                prior_run_states, state, context_checkpoint
                            )
                        (
                            context_checkpoint,
                            context_projection,
                            context_compaction_operation_id,
                        ) = self._compact_context_if_possible(
                            client, state, prior_run_states, context_checkpoint,
                            context_capacity_tokens=(
                                estimate.context_window_tokens if estimate is not None else None
                            ),
                            accounting=accounting,
                            mandatory_directory_tokens=mandatory_directory_tokens,
                            protected_raw_tokens=protected_raw_tokens,
                            existing_operation=pending_compaction,
                        )
                        context_checkpoint_revision = (
                            context_checkpoint.revision
                            if context_projection == "checkpoint" and context_checkpoint is not None
                            else None
                        )
                        if should_resume_compaction:
                            operation = self._coordinator.read_context_compaction_operation(
                                context_compaction_operation_id
                            ) if context_compaction_operation_id else None
                            frozen_directory_budget = (
                                operation.selection_plan.get("directory_budget_tokens")
                                if operation is not None
                                and operation.selection_plan.get("selection_plan_version") == 2
                                else None
                            )
                            directory_budget_tokens = frozen_directory_budget
                        request, request_context_projection = self._requests.build_with_projection(
                            state, self._tools.registry, prior_run_states,
                            context_checkpoint=context_checkpoint if context_projection == "checkpoint" else None,
                            directory_budget_tokens=directory_budget_tokens,
                            context_policy_version=2,
                        )
                        prepared = client.prepare(request)
                        estimate = prepared.context_estimate
                        accounting = account_request_context(
                            request, request_context_projection, estimate
                        )
                        _log_context_accounting(accounting)
                        if (
                            context_projection == "checkpoint"
                            and context_checkpoint is not None
                            and estimate is not None
                            and estimate.context_window_tokens is not None
                        ):
                            final_mandatory = self._requests.mandatory_directory_tokens(
                                state, prior_run_states, context_checkpoint
                            )
                            final_protected = estimate_protected_raw_history_tokens(
                                prior_run_states, state, context_checkpoint
                            )
                            final_budgets = (
                                calculate_context_history_budgets(
                                    estimate.context_window_tokens,
                                    accounting=accounting,
                                    mandatory_directory_tokens=final_mandatory,
                                    protected_raw_tokens=final_protected,
                                )
                                if final_mandatory is not None and final_protected is not None
                                else None
                            )
                            final_directory_budget = (
                                final_budgets.directory_tokens
                                if final_budgets is not None
                                else directory_budget_tokens
                            )
                            if final_directory_budget != directory_budget_tokens:
                                directory_budget_tokens = final_directory_budget
                                request, request_context_projection = self._requests.build_with_projection(
                                    state,
                                    self._tools.registry,
                                    prior_run_states,
                                    context_checkpoint=context_checkpoint,
                                    directory_budget_tokens=directory_budget_tokens,
                                    context_policy_version=2,
                                )
                                prepared = client.prepare(request)
                                accounting = account_request_context(
                                    request, request_context_projection,
                                    prepared.context_estimate,
                                )
                                _log_context_accounting(accounting)
                    logical_request = _provider_request_record(
                        prepared, run_id=run_id,
                        base_record_sequence=state.checkpoint.last_committed_record_sequence,
                        base_tool_sequence=state.checkpoint.last_committed_tool_sequence,
                        purpose="agent_turn", context_projection=context_projection,
                        context_checkpoint_revision=context_checkpoint_revision,
                        context_checkpoint_operation_id=context_compaction_operation_id,
                    )
            except ProviderCallError as error:
                return self._fail_run(state, terminal_message=_preparation_failure_message(error))
            except RunStopRequested:
                raise
            except Exception:
                return self._fail_run(state)

            with self._lock.acquire(run_id):
                current = self._coordinator.read_run_state(session_id, run_id)
                if current.stop_request is not None:
                    self._coordinator._interrupt_owned_run(session_id, run_id, current.checkpoint.revision)
                    return self._coordinator.read_run_state(session_id, run_id)
                if (
                    current.run.status is not RunStatus.RUNNING
                    or current.checkpoint.revision != state.checkpoint.revision
                    or current.checkpoint.next_action != state.checkpoint.next_action
                ):
                    return current

                attempt = self._coordinator.begin_provider_attempt(
                    session_id, run_id, current.checkpoint.revision,
                    request=logical_request, request_bytes=prepared.request_bytes,
                )
                claimed = self._coordinator.read_run_state(session_id, run_id)
                current_phase = "connecting"
                delta_sequence = 0

                def on_stream_event(event):
                    nonlocal current_phase, delta_sequence
                    if event.kind is ProviderStreamEventKind.RESPONSE_STARTED:
                        current_phase = "awaiting_response"
                        self._coordinator.update_provider_attempt_phase(
                            session_id=session_id, run_id=run_id, attempt_id=attempt.attempt_id,
                            phase=current_phase, provider_request_id=event.provider_request_id,
                            http_status=event.http_status,
                            response_bytes=event.response_bytes,
                        )
                    elif event.kind is ProviderStreamEventKind.HEARTBEAT:
                        self._coordinator.update_provider_attempt_phase(
                            session_id=session_id, run_id=run_id, attempt_id=attempt.attempt_id,
                            phase=current_phase, activity=True,
                            response_bytes=event.response_bytes,
                        )
                    elif event.kind in {
                        ProviderStreamEventKind.TEXT_DELTA,
                        ProviderStreamEventKind.REASONING_DELTA,
                        ProviderStreamEventKind.TOOL_CALL_DELTA,
                        ProviderStreamEventKind.USAGE,
                        ProviderStreamEventKind.COMPLETED,
                    }:
                        current_phase = "streaming"
                        self._coordinator.update_provider_attempt_phase(
                            session_id=session_id, run_id=run_id, attempt_id=attempt.attempt_id,
                            phase=current_phase, activity=True, usage=event.usage,
                            first_event=True,
                            response_bytes=event.response_bytes,
                        )
                        if event.kind is ProviderStreamEventKind.TEXT_DELTA and event.text and self._stream_sink is not None:
                            delta_sequence += 1
                            self._stream_sink(session_id, run_id, attempt.attempt_id, delta_sequence, event.text)

                try:
                    self._coordinator.update_provider_attempt_phase(
                        session_id=session_id, run_id=run_id, attempt_id=attempt.attempt_id,
                        phase="sending",
                    )
                    response = self._dispatch_with_stop_monitor(
                        client, prepared, on_stream_event, session_id, run_id
                    )
                except ProviderCallError as error:
                    latest = self._coordinator.read_run_state(session_id, run_id)
                    stopped = latest.stop_request is not None
                    self._coordinator.fail_provider_attempt(
                        session_id, run_id, claimed.checkpoint.revision, attempt.attempt_id,
                        outcome_unknown=not error.failure.outcome_known,
                        failure_code=error.failure.failure_code.value,
                        transient=error.failure.transient,
                        http_status=error.failure.http_status,
                        retry_after_seconds=error.failure.retry_after_seconds,
                        failure_category=error.failure.category,
                        cancelled=stopped,
                    )
                    return self._coordinator.read_run_state(session_id, run_id)
                except Exception:
                    latest = self._coordinator.read_run_state(session_id, run_id)
                    stopped = latest.stop_request is not None
                    self._coordinator.fail_provider_attempt(
                        session_id, run_id, claimed.checkpoint.revision, attempt.attempt_id,
                        outcome_unknown=True, failure_code=None,
                        transient=True, failure_category="temporary_unknown",
                        cancelled=stopped,
                    )
                    return self._coordinator.read_run_state(session_id, run_id)

                try:
                    self._coordinator.commit_model_response(
                        session_id, run_id, claimed.checkpoint.revision, response,
                        provider_attempt_id=attempt.attempt_id,
                        registry_version=self._tools.registry.version,
                    )
                except RunError as error:
                    if error.code not in {RunErrorCode.UNSUPPORTED_PAYLOAD, RunErrorCode.UNSUPPORTED_VERSION}:
                        raise
                    self._coordinator.fail_provider_attempt(
                        session_id, run_id, claimed.checkpoint.revision, attempt.attempt_id,
                        outcome_unknown=False,
                        failure_code=ProviderFailureCode.INVALID_PROVIDER_RESPONSE.value,
                        failure_category="invalid_response",
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

    def _checkpoint_for_request(
        self, request_record: ProviderRequestRecord, session_id: str
    ) -> SessionContextCheckpoint | None:
        if request_record.context_projection in {"full", "fallback"}:
            if request_record.context_projection == "fallback":
                operation = self._coordinator.read_context_compaction_operation(
                    request_record.context_checkpoint_operation_id or ""
                )
                if operation.status != "fallback":
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
            return None
        checkpoint = self._coordinator.read_session_context_checkpoint(session_id)
        if checkpoint is None or checkpoint.revision != request_record.context_checkpoint_revision:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if checkpoint.compaction_operation_id != request_record.context_checkpoint_operation_id:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        return checkpoint

    def _dispatch_with_stop_monitor(
        self, client, prepared, on_stream_event, session_id: str, run_id: str
    ):
        """Close an active HTTP stream promptly after a durable user stop request."""
        finished = Event()

        def watch_stop() -> None:
            while not finished.wait(0.2):
                try:
                    state = self._coordinator.read_run_state(session_id, run_id)
                except RunError:
                    continue
                if state.stop_request is not None:
                    interrupt = getattr(client, "interrupt", None)
                    if callable(interrupt):
                        interrupt()
                    else:
                        close = getattr(client, "close", None)
                        if callable(close):
                            close()
                    return

        watcher = Thread(
            target=watch_stop,
            name=f"figura-provider-stop-{run_id[:8]}",
            daemon=True,
        )
        watcher.start()
        try:
            return client.dispatch(prepared, on_stream_event=on_stream_event)
        finally:
            finished.set()
            watcher.join(timeout=0.5)

    def _compact_context_if_possible(
        self,
        client,
        state: RunState,
        prior_run_states: tuple[RunState, ...],
        previous_checkpoint: SessionContextCheckpoint | None,
        *,
        context_capacity_tokens: int | None,
        accounting=None,
        mandatory_directory_tokens: int | None = None,
        protected_raw_tokens: int | None = None,
        existing_operation=None,
    ) -> tuple[SessionContextCheckpoint | None, str, str | None]:
        if existing_operation is None:
            if accounting is not None and (
                mandatory_directory_tokens is None or protected_raw_tokens is None
            ):
                return (
                    previous_checkpoint,
                    "checkpoint" if previous_checkpoint is not None else "full",
                    previous_checkpoint.compaction_operation_id if previous_checkpoint else None,
                )
            budgets = calculate_context_history_budgets(
                context_capacity_tokens,
                accounting=accounting,
                mandatory_directory_tokens=(mandatory_directory_tokens or 0),
                protected_raw_tokens=(protected_raw_tokens or 0),
            )
            if budgets is None:
                return (
                    previous_checkpoint,
                    "checkpoint" if previous_checkpoint is not None else "full",
                    previous_checkpoint.compaction_operation_id if previous_checkpoint else None,
                )
            reconciliation = (
                previous_checkpoint is not None
                and previous_checkpoint.summary_contract_version < 3
            )
            candidate = (
                legacy_input_reconciliation_selection(
                    prior_run_states, state, previous_checkpoint
                )
                if reconciliation
                else select_compaction_coverage(
                    prior_run_states,
                    previous_checkpoint,
                    budgets.raw_history_tokens,
                    active_run_state=state,
                )
            )
            if candidate is None:
                _log_context_accounting(
                    accounting, pressure_reason="no_new_coverage"
                )
                return (
                    previous_checkpoint,
                    "checkpoint" if previous_checkpoint is not None else "full",
                    previous_checkpoint.compaction_operation_id if previous_checkpoint else None,
                )
            if budgets.summary_tokens <= 0:
                _log_context_accounting(
                    accounting, pressure_reason="protected_content"
                )
                return (
                    previous_checkpoint,
                    "checkpoint" if previous_checkpoint is not None else "full",
                    previous_checkpoint.compaction_operation_id if previous_checkpoint else None,
                )
            if budgets.accounting_version == 2:
                plan = {
                    "selection_plan_version": 2,
                    "context_capacity_tokens": budgets.context_capacity_tokens,
                    "raw_history_budget_tokens": budgets.raw_history_tokens,
                    "summary_budget_tokens": budgets.summary_tokens,
                    "protected_raw_tokens": budgets.protected_raw_tokens,
                    "mandatory_directory_tokens": budgets.mandatory_directory_tokens,
                    "directory_budget_tokens": (
                        budgets.directory_tokens
                        if budgets.directory_tokens is not None
                        else budgets.mandatory_directory_tokens
                    ),
                    "accounting_basis": {
                        "policy_tools_state_tokens": getattr(
                            accounting, "policy_tools_state_tokens", 0
                        ),
                        "current_input_tokens": getattr(
                            accounting, "current_input_tokens", 0
                        ),
                    },
                    "coverage_version": 2,
                    "input_projection_version": 2,
                    "directory_projection_version": 2,
                    "accounting_version": 1,
                    "summary_contract_version": 3,
                    "reconciliation": reconciliation,
                }
            else:
                # Compatibility path for operation creation without usable
                # component accounting. Existing operation readers still know v1.
                plan = {
                    "context_capacity_tokens": budgets.context_capacity_tokens,
                    "raw_history_budget_tokens": budgets.raw_history_tokens,
                    "summary_budget_tokens": budgets.summary_tokens,
                    "coverage_version": 1,
                }
            operation = self._coordinator.get_or_create_context_compaction_operation(
                session_id=state.run.session_id,
                target_run_id=state.run.run_id,
                base_record_sequence=state.checkpoint.last_committed_record_sequence,
                base_tool_sequence=state.checkpoint.last_committed_tool_sequence,
                input_checkpoint_revision=(previous_checkpoint.revision if previous_checkpoint else 0),
                covered_run_id=candidate.covered_run_id,
                covered_run_ordinal=candidate.covered_run_ordinal,
                covered_record_sequence=candidate.covered_record_sequence,
                covered_tool_sequence=candidate.covered_tool_sequence,
                selection_plan=plan,
            )
        else:
            operation = existing_operation

        def fallback_operation(failure_code: str) -> None:
            # A resumed summary may still have a started physical attempt when
            # its frozen request can no longer be reconstructed. Close that
            # attempt as outcome-unknown without scheduling another send before
            # allowing the Agent request to proceed.
            request_id = operation.provider_request_id
            if request_id is not None:
                latest = self._coordinator.read_run_state(
                    state.run.session_id, state.run.run_id
                )
                active = [
                    item for item in latest.provider_attempts
                    if item.request_id == request_id and item.status.value == "started"
                ]
                for item in active:
                    self._coordinator.fail_provider_attempt(
                        state.run.session_id,
                        state.run.run_id,
                        latest.checkpoint.revision,
                        item.attempt_id,
                        outcome_unknown=True,
                        failure_code=None,
                        transient=False,
                        failure_category="internal_error",
                    )
                    latest = self._coordinator.read_run_state(
                        state.run.session_id, state.run.run_id
                    )
            self._coordinator.fallback_context_compaction_operation(
                operation.operation_id, failure_code
            )

        if operation.status == "completed":
            _log_context_accounting(
                accounting, pressure_reason="no_new_coverage"
            )
            checkpoint = self._coordinator.read_session_context_checkpoint(state.run.session_id)
            if (
                checkpoint is None
                or checkpoint.compaction_operation_id != operation.operation_id
                or checkpoint.revision != operation.result_checkpoint_revision
            ):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            return checkpoint, "checkpoint", operation.operation_id
        if operation.status == "fallback":
            _log_context_accounting(
                accounting, pressure_reason="no_new_coverage"
            )
            fallback_operation(operation.failure_code or "summary_fallback")
            return None, "fallback", operation.operation_id
        if operation.status != "preparing":
            raise RunError(RunErrorCode.INTEGRITY_ERROR)

        plan = _validated_compaction_plan(operation.selection_plan)
        if plan is None:
            fallback_operation("summary_plan_missing")
            return None, "fallback", operation.operation_id
        selection = selection_for_coverage(
            prior_run_states,
            previous_checkpoint,
            operation,
            active_run_state=state,
        )
        if selection is None:
            fallback_operation("summary_coverage_unavailable")
            return None, "fallback", operation.operation_id
        selected_runs = selection.selected_run_states
        if not any(item.run.run_id == operation.covered_run_id for item in selected_runs):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)

        try:
            summary_request, allowed_refs = self._requests.build_summary_request(
                state,
                selected_runs,
                previous_checkpoint,
                coverage=selection,
                context_capacity_tokens=plan["context_capacity_tokens"],
                summary_budget_tokens=plan["summary_budget_tokens"],
                summary_contract_version=plan["summary_contract_version"],
                reconcile_inputs_only=plan.get("reconciliation", False),
            )
            request_record = None
            if operation.provider_request_id is not None:
                latest_state = self._coordinator.read_run_state(
                    state.run.session_id, state.run.run_id
                )
                request_record = next(
                    (item for item in latest_state.provider_requests
                     if item.request_id == operation.provider_request_id),
                    None,
                )
                if request_record is None or request_record.purpose != "context_compaction":
                    raise ValueError("saved summary request is unavailable")
                options = request_record.options
                frozen_request = replace(
                    summary_request,
                    options=ProviderOptions(
                        max_completion_tokens=options["max_completion_tokens"],
                        thinking_mode=options["thinking_mode"],
                        reasoning_effort=options["reasoning_effort"],
                    ),
                )
                prepared = client.prepare(
                    frozen_request,
                    frozen_options=True,
                    frozen_timeout_policy={
                        key: options[key]
                        for key in ("connect_timeout_seconds", "write_timeout_seconds")
                    },
                    estimate_context=True,
                )
                if not _request_matches_prepared(request_record, prepared.descriptor):
                    raise ValueError("summary request identity changed")
            else:
                prepared = client.prepare(summary_request)
                if not _summary_request_fits_capacity(prepared, plan):
                    fallback_operation("summary_request_exceeds_capacity")
                    return None, "fallback", operation.operation_id
                request_record = _provider_request_record(
                    prepared,
                    run_id=state.run.run_id,
                    base_record_sequence=state.checkpoint.last_committed_record_sequence,
                    base_tool_sequence=state.checkpoint.last_committed_tool_sequence,
                    purpose="context_compaction",
                    compaction_operation_id=operation.operation_id,
                    # Some legacy checkpoints predate compaction operation IDs.
                    # The summary request fingerprint already freezes their
                    # projected summary and sources, so bind them as a full
                    # auxiliary request instead of creating an invalid partial
                    # checkpoint binding with no operation identity.
                    context_projection=(
                        "checkpoint"
                        if previous_checkpoint is not None
                        and previous_checkpoint.compaction_operation_id is not None
                        else "full"
                    ),
                    context_checkpoint_revision=(
                        previous_checkpoint.revision
                        if previous_checkpoint is not None
                        and previous_checkpoint.compaction_operation_id is not None
                        else None
                    ),
                    context_checkpoint_operation_id=(
                        previous_checkpoint.compaction_operation_id
                        if previous_checkpoint is not None
                        else None
                    ),
                )
        except ProviderCallError as error:
            fallback_operation(error.failure.failure_code.value)
            return None, "fallback", operation.operation_id
        except (RunError, TypeError, ValueError, KeyError) as error:
            fallback_operation(
                "invalid_summary_input" if isinstance(error, RunError)
                else "summary_request_invalid"
            )
            return None, "fallback", operation.operation_id

        assert request_record is not None
        while True:
            latest = self._coordinator.read_run_state(state.run.session_id, state.run.run_id)
            if latest.stop_request is not None:
                raise RunStopRequested()
            operation = self._coordinator.read_context_compaction_operation(operation.operation_id)
            attempts = [
                item for item in latest.provider_attempts
                if item.request_id == request_record.request_id
            ]
            previous_attempt = attempts[-1] if attempts else None
            if previous_attempt is not None and previous_attempt.status.value == "started":
                # The prior process may have sent this summary and lost its result.
                # Preserve the uncertainty and let the shared retry policy decide
                # whether another generation-only attempt is eligible.
                self._coordinator.fail_provider_attempt(
                    state.run.session_id,
                    state.run.run_id,
                    latest.checkpoint.revision,
                    previous_attempt.attempt_id,
                    outcome_unknown=True,
                    failure_code=None,
                    transient=True,
                    failure_category="temporary_unknown",
                )
                continue
            if previous_attempt is not None and previous_attempt.next_eligible_at is not None:
                due = datetime.fromisoformat(
                    previous_attempt.next_eligible_at.replace("Z", "+00:00")
                )
                while datetime.now(timezone.utc) < due:
                    latest = self._coordinator.read_run_state(
                        state.run.session_id, state.run.run_id
                    )
                    if latest.stop_request is not None:
                        raise RunStopRequested()
                    time.sleep(min(
                        0.1,
                        max(0.0, (due - datetime.now(timezone.utc)).total_seconds()),
                    ))
            if previous_attempt is not None and (
                previous_attempt.status.value not in {"known_failure", "outcome_unknown"}
                or previous_attempt.request_attempt_number >= request_record.max_attempts
                or previous_attempt.next_eligible_at is None
            ):
                fallback_operation(
                    previous_attempt.failure_code or "summary_attempts_exhausted"
                )
                return None, "fallback", operation.operation_id

            attempt = self._coordinator.begin_provider_attempt(
                state.run.session_id,
                state.run.run_id,
                latest.checkpoint.revision,
                request=request_record,
                auxiliary=True,
                request_bytes=prepared.request_bytes,
            )
            phase = "connecting"

            def on_summary_event(event):
                nonlocal phase
                if event.kind is ProviderStreamEventKind.RESPONSE_STARTED:
                    phase = "awaiting_response"
                elif event.kind in {
                    ProviderStreamEventKind.TEXT_DELTA,
                    ProviderStreamEventKind.REASONING_DELTA,
                    ProviderStreamEventKind.TOOL_CALL_DELTA,
                    ProviderStreamEventKind.USAGE,
                    ProviderStreamEventKind.COMPLETED,
                }:
                    phase = "streaming"
                self._coordinator.update_provider_attempt_phase(
                    session_id=state.run.session_id,
                    run_id=state.run.run_id,
                    attempt_id=attempt.attempt_id,
                    phase=phase,
                    provider_request_id=event.provider_request_id,
                    http_status=event.http_status,
                    activity=event.kind in {
                        ProviderStreamEventKind.HEARTBEAT,
                        ProviderStreamEventKind.TEXT_DELTA,
                        ProviderStreamEventKind.REASONING_DELTA,
                        ProviderStreamEventKind.TOOL_CALL_DELTA,
                        ProviderStreamEventKind.USAGE,
                        ProviderStreamEventKind.COMPLETED,
                    },
                    first_event=event.kind in {
                        ProviderStreamEventKind.TEXT_DELTA,
                        ProviderStreamEventKind.REASONING_DELTA,
                        ProviderStreamEventKind.TOOL_CALL_DELTA,
                        ProviderStreamEventKind.USAGE,
                        ProviderStreamEventKind.COMPLETED,
                    },
                    usage=event.usage,
                    response_bytes=event.response_bytes,
                )

            try:
                self._coordinator.update_provider_attempt_phase(
                    session_id=state.run.session_id,
                    run_id=state.run.run_id,
                    attempt_id=attempt.attempt_id,
                    phase="sending",
                )
                response = self._dispatch_with_stop_monitor(
                    client,
                    prepared,
                    on_summary_event,
                    state.run.session_id,
                    state.run.run_id,
                )
            except ProviderCallError as error:
                latest = self._coordinator.read_run_state(
                    state.run.session_id, state.run.run_id
                )
                stopped = latest.stop_request is not None
                self._coordinator.fail_provider_attempt(
                    state.run.session_id,
                    state.run.run_id,
                    latest.checkpoint.revision,
                    attempt.attempt_id,
                    outcome_unknown=not error.failure.outcome_known,
                    failure_code=error.failure.failure_code.value,
                    transient=error.failure.transient,
                    http_status=error.failure.http_status,
                    retry_after_seconds=error.failure.retry_after_seconds,
                    failure_category=error.failure.category,
                    cancelled=stopped,
                )
                if stopped:
                    raise RunStopRequested()
                latest = self._coordinator.read_run_state(
                    state.run.session_id, state.run.run_id
                )
                failed_attempt = next(
                    item for item in latest.provider_attempts
                    if item.attempt_id == attempt.attempt_id
                )
                if failed_attempt.next_eligible_at is not None:
                    continue
                fallback_operation(error.failure.failure_code.value)
                return None, "fallback", operation.operation_id
            except RunStopRequested:
                raise
            except Exception:
                latest = self._coordinator.read_run_state(
                    state.run.session_id, state.run.run_id
                )
                stopped = latest.stop_request is not None
                self._coordinator.fail_provider_attempt(
                    state.run.session_id,
                    state.run.run_id,
                    latest.checkpoint.revision,
                    attempt.attempt_id,
                    outcome_unknown=True,
                    failure_code=None,
                    transient=True,
                    failure_category="temporary_unknown",
                    cancelled=stopped,
                )
                if stopped:
                    raise RunStopRequested()
                fallback_operation("summary_transport_error")
                return None, "fallback", operation.operation_id

            try:
                summary, summary_refs = validate_summary_response(
                    response,
                    provider_id=state.run.provider,
                    model_id=state.run.model,
                    allowed_refs=allowed_refs,
                    selected_runs=selected_runs,
                )
            except (SummaryValidationError, TypeError, ValueError) as error:
                latest = self._coordinator.read_run_state(
                    state.run.session_id, state.run.run_id
                )
                self._coordinator.fail_provider_attempt(
                    state.run.session_id,
                    state.run.run_id,
                    latest.checkpoint.revision,
                    attempt.attempt_id,
                    outcome_unknown=False,
                    failure_code=ProviderFailureCode.INVALID_PROVIDER_RESPONSE.value,
                    transient=False,
                    failure_category="invalid_response",
                )
                failure_code = (
                    error.failure_code if isinstance(error, SummaryValidationError)
                    else "invalid_summary_response"
                )
                fallback_operation(failure_code)
                return None, "fallback", operation.operation_id

            if previous_checkpoint is not None:
                prior_outcomes = previous_checkpoint.summary.get("run_outcomes", ())
                if isinstance(prior_outcomes, (tuple, list)):
                    summary["run_outcomes"] = _merge_run_outcomes(
                        prior_outcomes, summary["run_outcomes"]
                    )

            source_refs = tuple(dict.fromkeys((
                *(previous_checkpoint.source_refs if previous_checkpoint else ()),
                *summary_refs,
            )))
            checkpoint = SessionContextCheckpoint(
                session_id=state.run.session_id,
                revision=(previous_checkpoint.revision + 1 if previous_checkpoint else 1),
                covered_run_id=selection.covered_run_id,
                covered_run_ordinal=selection.covered_run_ordinal,
                covered_record_sequence=selection.covered_record_sequence,
                covered_tool_sequence=selection.covered_tool_sequence,
                summary_contract_version=plan["summary_contract_version"],
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
                    provider_attempt_id=attempt.attempt_id,
                )
            except RunError as error:
                if error.code is RunErrorCode.UNSUPPORTED_PAYLOAD:
                    fallback_operation("invalid_summary_checkpoint")
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


def _provider_request_record(
    prepared,
    *,
    run_id: str,
    base_record_sequence: int,
    base_tool_sequence: int,
    purpose: str,
    compaction_operation_id: str | None = None,
    context_projection: str = "full",
    context_checkpoint_revision: int | None = None,
    context_checkpoint_operation_id: str | None = None,
) -> ProviderRequestRecord:
    descriptor = prepared.descriptor
    options = descriptor["options"]
    manifest = descriptor["asset_manifest"]
    return ProviderRequestRecord(
        request_id=uuid.uuid4().hex,
        run_id=run_id,
        purpose=purpose,
        compaction_operation_id=compaction_operation_id,
        base_record_sequence=base_record_sequence,
        base_tool_sequence=base_tool_sequence,
        provider_id=descriptor["provider_id"],
        model_id=descriptor["model_id"],
        request_fingerprint=descriptor["request_fingerprint"],
        endpoint_identity=descriptor["endpoint_identity"],
        prompt_digest=manifest["prompt_digest"],
        tool_registry_digest=manifest["registry_digest"],
        options=MappingProxyType(dict(options)),
        asset_manifest=MappingProxyType(dict(manifest)),
        created_at=datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
        generation_only=True,
        max_attempts=4,
        context_estimate=prepared.context_estimate,
        context_projection=context_projection,
        context_checkpoint_revision=context_checkpoint_revision,
        context_checkpoint_operation_id=context_checkpoint_operation_id,
    )


def _request_matches_prepared(
    request: ProviderRequestRecord, descriptor: Mapping[str, object]
) -> bool:
    try:
        manifest = descriptor["asset_manifest"]
        options = descriptor["options"]
        return (
            request.provider_id == descriptor["provider_id"]
            and request.model_id == descriptor["model_id"]
            and request.request_fingerprint == descriptor["request_fingerprint"]
            and request.endpoint_identity == descriptor["endpoint_identity"]
            and isinstance(manifest, Mapping)
            and isinstance(options, Mapping)
            and encode_json(dict(request.asset_manifest)) == encode_json(dict(manifest))
            and encode_json(dict(request.options)) == encode_json(dict(options))
        )
    except (KeyError, PayloadError, TypeError, ValueError):
        return False


def _preparation_failure_message(error: ProviderCallError) -> str | None:
    failure = error.failure
    key = failure.failure_code.value
    if key == "invalid_request" and failure.safe_message == (
        "DeepSeek thinking 模式的工具历史必须包含 reasoning continuation。"
    ):
        key = "missing_deepseek_continuation"
    return PREPARATION_MESSAGES.get(key)


def _validated_compaction_plan(plan: Mapping[str, object] | None) -> dict[str, object] | None:
    if not isinstance(plan, Mapping):
        return None
    legacy_fields = {
        "context_capacity_tokens",
        "raw_history_budget_tokens",
        "summary_budget_tokens",
        "coverage_version",
    }
    if set(plan) == legacy_fields:
        capacity = plan.get("context_capacity_tokens")
        raw_budget = plan.get("raw_history_budget_tokens")
        summary_budget = plan.get("summary_budget_tokens")
        version = plan.get("coverage_version")
        if (
            type(capacity) is not int or capacity <= 0
            or raw_budget != capacity // 10
            or summary_budget != capacity // 10
            or type(raw_budget) is not int
            or type(summary_budget) is not int
            or type(version) is not int or version != 1
        ):
            return None
        return {
            "context_capacity_tokens": capacity,
            "raw_history_budget_tokens": raw_budget,
            "summary_budget_tokens": summary_budget,
            "coverage_version": 1,
            "summary_contract_version": 2,
            "reconciliation": False,
        }
    expected_v2_fields = {
        "selection_plan_version", "context_capacity_tokens",
        "raw_history_budget_tokens", "summary_budget_tokens",
        "protected_raw_tokens", "mandatory_directory_tokens",
        "directory_budget_tokens", "accounting_basis", "coverage_version",
        "input_projection_version", "directory_projection_version",
        "accounting_version", "summary_contract_version", "reconciliation",
    }
    if set(plan) != expected_v2_fields:
        return None
    capacity = plan.get("context_capacity_tokens")
    raw_budget = plan.get("raw_history_budget_tokens")
    summary_budget = plan.get("summary_budget_tokens")
    protected = plan.get("protected_raw_tokens")
    mandatory_directory = plan.get("mandatory_directory_tokens")
    directory_budget = plan.get("directory_budget_tokens")
    basis = plan.get("accounting_basis")
    if (
        type(plan.get("selection_plan_version")) is not int
        or plan["selection_plan_version"] != 2
        or type(capacity) is not int or capacity <= 0
        or type(raw_budget) is not int or raw_budget < 0
        or type(summary_budget) is not int or summary_budget < 0
        or summary_budget > capacity // 10
        or type(protected) is not int or protected < 0 or protected > raw_budget
        or type(mandatory_directory) is not int or mandatory_directory < 0
        or type(directory_budget) is not int or directory_budget < mandatory_directory
        or not isinstance(basis, Mapping)
        or set(basis) != {"policy_tools_state_tokens", "current_input_tokens"}
        or any(type(value) is not int or value < 0 for value in basis.values())
        or plan.get("coverage_version") != 2
        or plan.get("input_projection_version") != 2
        or plan.get("directory_projection_version") != 2
        or plan.get("accounting_version") != 1
        or plan.get("summary_contract_version") != 3
        or type(plan.get("reconciliation")) is not bool
    ):
        return None
    return {
        "selection_plan_version": 2,
        "context_capacity_tokens": capacity,
        "raw_history_budget_tokens": raw_budget,
        "summary_budget_tokens": summary_budget,
        "protected_raw_tokens": protected,
        "mandatory_directory_tokens": mandatory_directory,
        "directory_budget_tokens": directory_budget,
        "accounting_basis": dict(basis),
        "coverage_version": 2,
        "input_projection_version": 2,
        "directory_projection_version": 2,
        "accounting_version": 1,
        "summary_contract_version": 3,
        "reconciliation": plan["reconciliation"],
    }


def _context_pressure_reached(estimate) -> bool:
    input_tokens = getattr(estimate, "input_tokens", None)
    capacity = getattr(estimate, "context_window_tokens", None)
    return (
        type(input_tokens) is int
        and type(capacity) is int
        and capacity > 0
        and input_tokens / capacity >= 0.8
    )


def _log_context_accounting(accounting, *, pressure_reason: str | None = None) -> None:
    diagnostic = getattr(accounting, "safe_diagnostic", None)
    if not callable(diagnostic):
        return
    try:
        values = diagnostic()
        if pressure_reason is not None:
            values["pressure_reason"] = pressure_reason
        _LOGGER.debug("Figura request context accounting: %s", encode_json(values))
    except (PayloadError, TypeError, ValueError):
        _LOGGER.debug("Figura request context accounting: unavailable")


def _summary_request_fits_capacity(prepared, plan: Mapping[str, int]) -> bool:
    estimate = getattr(prepared, "context_estimate", None)
    request = getattr(prepared, "request", None)
    options = getattr(request, "options", None)
    input_tokens = getattr(estimate, "input_tokens", None)
    completion_tokens = getattr(options, "max_completion_tokens", None)
    capacity = plan.get("context_capacity_tokens")
    if (
        type(input_tokens) is not int or input_tokens < 0
        or type(capacity) is not int or capacity <= 0
        or (completion_tokens is not None and (
            type(completion_tokens) is not int or completion_tokens < 0
        ))
    ):
        return False
    return input_tokens + (completion_tokens or 0) <= capacity


def _merge_run_outcomes(previous: object, current: object) -> list[object]:
    merged: dict[str, object] = {}
    for value in (*tuple(previous), *tuple(current)):
        if isinstance(value, Mapping) and isinstance(value.get("run_id"), str):
            merged[value["run_id"]] = value
    return sorted(
        merged.values(),
        key=lambda value: value.get("run_ordinal", 0) if isinstance(value, Mapping) else 0,
    )
