"""Checkpoint-driven ReAct scheduling for one durable Figura Run."""

from __future__ import annotations

from contextlib import nullcontext

from figura.runtime.models import PREPARATION_MESSAGES
from figura.providers import ProviderFactory, ProviderResponse
from figura.providers.errors import ProviderCallError, ProviderFailureCode
from figura.runtime.coordinator import RunCoordinator
from figura.runtime.errors import RunError, RunErrorCode
from figura.runtime.persistence.controls import RunStopRequested
from figura.runtime.models import ActionKind, RunStatus, TerminalCode, ToolFactKind
from figura.runtime.records import (
    ModelResponseFact,
    RunState,
    ToolAttemptStartedFact,
    ToolCallFact,
)
from figura.runtime.tool_execution import DurableToolExecutor
from figura.runtime.run_lock import PerRunExecutionLock, RunExecutionOwnership, RunExecutionLockUnavailable

from .request import AgentRequestBuilder


_MAX_PROVIDER_ATTEMPTS = 8
_MAX_STARTED_TOOL_CALLS = 32


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

    def execute(self, session_id: str, run_id: str) -> RunState:
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
        while state.run.status is RunStatus.RUNNING:
            state = self._coordinator.read_run_state(session_id, run_id)
            if state.stop_request is not None:
                return self._stop_owned(state)
            if state.run.status is not RunStatus.RUNNING:
                return state
            action = state.checkpoint.next_action
            if action is None:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            if action.action_kind is ActionKind.MODEL:
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
            state = next_state
        return state

    def _execute_model_action(self, state: RunState) -> RunState:
        session_id, run_id = state.run.session_id, state.run.run_id
        if len(state.provider_attempts) >= _MAX_PROVIDER_ATTEMPTS:
            return self._fail_run(state)
        try:
            prior_run_states = self._coordinator.read_prior_run_states(session_id, run_id)
            request = self._requests.build(
                state, self._tools.registry, prior_run_states
            )
        except RunError:
            return self._fail_run(state)

        try:
            client = self._provider_factory.create(state.run.provider, state.run.model)
        except Exception:
            return self._fail_run(state)

        try:
            try:
                prepared = client.prepare(request)
            except ProviderCallError as error:
                return self._fail_run(state, terminal_message=_preparation_failure_message(error))
            except Exception:
                return self._fail_run(state)

            with self._lock.acquire(run_id):
                current = self._coordinator.read_run_state(session_id, run_id)
                if (
                    current.run.status is not RunStatus.RUNNING
                    or current.checkpoint.revision != state.checkpoint.revision
                    or current.checkpoint.next_action != state.checkpoint.next_action
                ):
                    return current

                attempt = self._coordinator.begin_provider_attempt(
                    session_id, run_id, current.checkpoint.revision
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

        started_calls = {
            fact.payload.tool_call_sequence
            for fact in state.tool_facts
            if fact.fact_kind is ToolFactKind.TOOL_ATTEMPT_STARTED
            and isinstance(fact.payload, ToolAttemptStartedFact)
        }
        remaining = _MAX_STARTED_TOOL_CALLS - len(started_calls)
        if remaining <= 0:
            return self._fail_run(state)
        try:
            progressed = self._tools.execute_owned_pending(
                state.run.session_id,
                state.run.run_id,
                max_calls=min(remaining, 1),
            )
        except RunStopRequested:
            raise
        except RunError as error:
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

        if (
            progressed.checkpoint.next_action is not None
            and progressed.checkpoint.next_action.action_kind is ActionKind.TOOL_EXECUTION
            and len(
                {
                    fact.payload.tool_call_sequence
                    for fact in progressed.tool_facts
                    if fact.fact_kind is ToolFactKind.TOOL_ATTEMPT_STARTED
                    and isinstance(fact.payload, ToolAttemptStartedFact)
                }
            ) >= _MAX_STARTED_TOOL_CALLS
        ):
            return self._fail_run(progressed)
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
