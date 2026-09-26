"""Durable, serial dispatch of persisted tool-call intents."""

from __future__ import annotations

import hashlib

from figura.json_schema import canonical_json_dumps
from figura.tools import (
    ReplayEffect,
    ToolContext,
    ToolExecutionResult,
    ToolInvocation,
    ToolRegistry,
    ToolRuntime,
)

from .errors import RunError, RunErrorCode
from .models import (
    ActionKind,
    RunState,
    RunStatus,
    ToolAttemptStartedFact,
    ToolCallFact,
    ToolExecutionFact,
    ToolFactKind,
)
from ._run_lock import PerRunExecutionLock, RunExecutionLockUnavailable
from .store import FiguraRunStore


class DurableToolExecutor:
    """Execute the persisted next tool call and advance in provider order."""

    __slots__ = ("_store", "_registry", "_runtime", "_lock")

    def __init__(
        self,
        store: FiguraRunStore,
        registry: ToolRegistry,
        runtime: ToolRuntime | None = None,
        *,
        execution_lock: PerRunExecutionLock | None = None,
    ) -> None:
        if not isinstance(store, FiguraRunStore):
            raise TypeError("store must be a FiguraRunStore")
        if not isinstance(registry, ToolRegistry):
            raise TypeError("registry must be a ToolRegistry")
        selected_runtime = runtime or ToolRuntime(registry)
        if not isinstance(selected_runtime, ToolRuntime) or selected_runtime.registry is not registry:
            raise TypeError("runtime must use the selected ToolRegistry")
        object.__setattr__(self, "_store", store)
        object.__setattr__(self, "_registry", registry)
        object.__setattr__(self, "_runtime", selected_runtime)
        object.__setattr__(self, "_lock", execution_lock or PerRunExecutionLock(store.data_root))

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("DurableToolExecutor is immutable")

    def execute_pending(self, session_id: str, run_id: str) -> RunState:
        """Run all consecutive pending calls; unknown attempts require recovery."""
        try:
            with self._lock.acquire(run_id):
                return self._execute_pending_locked(session_id, run_id)
        except RunExecutionLockUnavailable:
            raise RunError(RunErrorCode.INVALID_TRANSITION) from None

    def _execute_pending_locked(self, session_id: str, run_id: str) -> RunState:
        state = self._store.read_run_state(session_id, run_id)
        return self._execute_from_state_locked(state)

    def recover_unknown_attempt(self, session_id: str, run_id: str) -> RunState:
        """Recover an orphaned attempt only after acquiring its Run process lock."""
        try:
            with self._lock.acquire(run_id):
                state = self._store.read_run_state(session_id, run_id)
                action = state.checkpoint.next_action
                if action is None or action.action_kind is not ActionKind.TOOL_ATTEMPT:
                    return self._execute_from_state_locked(state)

                call_fact = _call_fact_at(state, action.tool_call_sequence)
                call = call_fact.payload
                attempt_fact = _attempt_fact_for(state, action.attempt_id)
                attempt = attempt_fact.payload
                if (
                    not isinstance(attempt, ToolAttemptStartedFact)
                    or attempt.tool_call_sequence != call_fact.tool_sequence
                    or attempt.registry_version != self._registry.version
                    or call.registry_version != self._registry.version
                ):
                    raise RunError(RunErrorCode.INVALID_TRANSITION)
                definition = self._registry.get(call.tool_name)
                if definition is None or definition.replay_effect is not attempt.replay_effect:
                    raise RunError(RunErrorCode.INVALID_TRANSITION)
                if attempt.replay_effect is ReplayEffect.RECONCILE_REQUIRED:
                    return state

                replay_start = self._store.begin_tool_replay_attempt(
                    session_id=session_id,
                    run_id=run_id,
                    expected_revision=state.checkpoint.revision,
                    tool_call_sequence=call_fact.tool_sequence,
                    previous_attempt_id=attempt.attempt_id,
                    registry_version=self._registry.version,
                )
                resumed = self._invoke_and_commit(
                    state,
                    call_fact,
                    replay_start,
                    expected_revision=state.checkpoint.revision + 1,
                    replay_effect=attempt.replay_effect,
                )
                return self._execute_from_state_locked(resumed)
        except RunExecutionLockUnavailable:
            raise RunError(RunErrorCode.INVALID_TRANSITION) from None

    def reconcile_unknown_attempt(
        self,
        session_id: str,
        run_id: str,
        result: ToolExecutionResult,
    ) -> RunState:
        """Commit a trusted observation for a reconcile_required attempt without dispatch."""
        try:
            with self._lock.acquire(run_id):
                state = self._store.read_run_state(session_id, run_id)
                action = state.checkpoint.next_action
                if action is None or action.action_kind is not ActionKind.TOOL_ATTEMPT:
                    raise RunError(RunErrorCode.INVALID_TRANSITION)
                call_fact = _call_fact_at(state, action.tool_call_sequence)
                attempt_fact = _attempt_fact_for(state, action.attempt_id)
                attempt = attempt_fact.payload
                if (
                    not isinstance(attempt, ToolAttemptStartedFact)
                    or attempt.replay_effect is not ReplayEffect.RECONCILE_REQUIRED
                    or attempt.registry_version != self._registry.version
                    or call_fact.payload.registry_version != self._registry.version
                ):
                    raise RunError(RunErrorCode.INVALID_TRANSITION)
                definition = self._registry.get(call_fact.payload.tool_name)
                if definition is None or definition.replay_effect is not ReplayEffect.RECONCILE_REQUIRED:
                    raise RunError(RunErrorCode.INVALID_TRANSITION)
                self._store.commit_tool_result(
                    session_id=session_id,
                    run_id=run_id,
                    expected_revision=state.checkpoint.revision,
                    attempt_id=attempt.attempt_id,
                    result=result,
                )
                return self._store.read_run_state(session_id, run_id)
        except RunExecutionLockUnavailable:
            raise RunError(RunErrorCode.INVALID_TRANSITION) from None

    def _execute_from_state_locked(self, state: RunState) -> RunState:
        session_id, run_id = state.run.session_id, state.run.run_id
        while (
            state.run.status is RunStatus.RUNNING
            and state.checkpoint.next_action is not None
            and state.checkpoint.next_action.action_kind is ActionKind.TOOL_EXECUTION
        ):
            action = state.checkpoint.next_action
            call_fact = _call_fact_at(state, action.tool_call_sequence)
            call = call_fact.payload
            definition = self._registry.get(call.tool_name)
            if (
                call.registry_version != self._registry.version
                or definition is None
            ):
                raise RunError(RunErrorCode.INVALID_TRANSITION)

            attempt_start = self._store.begin_tool_attempt(
                session_id=session_id,
                run_id=run_id,
                expected_revision=state.checkpoint.revision,
                tool_call_sequence=call_fact.tool_sequence,
                registry_version=self._registry.version,
                replay_effect=definition.replay_effect,
            )
            state = self._invoke_and_commit(
                state,
                call_fact,
                attempt_start,
                expected_revision=state.checkpoint.revision + 1,
                replay_effect=definition.replay_effect,
            )
        return state

    def _invoke_and_commit(
        self,
        state: RunState,
        call_fact: ToolExecutionFact,
        attempt_start: ToolExecutionFact,
        *,
        expected_revision: int,
        replay_effect: ReplayEffect,
    ) -> RunState:
        call = call_fact.payload
        attempt = attempt_start.payload
        if not isinstance(call, ToolCallFact):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        idempotency_key = (
            _idempotency_key(state.run.run_id, call.call_id)
            if replay_effect is ReplayEffect.IDEMPOTENT_LOCAL_WRITE
            else None
        )
        result = self._runtime.invoke(
            ToolInvocation(call.call_id, call.tool_name, call.arguments_json),
            ToolContext(
                run_id=state.run.run_id,
                session_id=state.run.session_id,
                call_id=call.call_id,
                idempotency_key=idempotency_key,
            ),
        )
        self._store.commit_tool_result(
            session_id=state.run.session_id,
            run_id=state.run.run_id,
            expected_revision=expected_revision,
            attempt_id=attempt.attempt_id,
            result=result,
        )
        return self._store.read_run_state(state.run.session_id, state.run.run_id)


def _call_fact_at(state: RunState, tool_sequence: int | None) -> ToolExecutionFact:
    if type(tool_sequence) is not int or tool_sequence < 1:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    fact = next(
        (item for item in state.tool_facts if item.tool_sequence == tool_sequence),
        None,
    )
    if (
        fact is None
        or fact.fact_kind is not ToolFactKind.TOOL_CALL
        or not isinstance(fact.payload, ToolCallFact)
    ):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    return fact


def _attempt_fact_for(state: RunState, attempt_id: str | None) -> ToolExecutionFact:
    if not isinstance(attempt_id, str) or not attempt_id:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    fact = next(
        (
            item
            for item in state.tool_facts
            if item.fact_kind is ToolFactKind.TOOL_ATTEMPT_STARTED
            and isinstance(item.payload, ToolAttemptStartedFact)
            and item.payload.attempt_id == attempt_id
        ),
        None,
    )
    if fact is None:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    return fact


def _idempotency_key(run_id: str, call_id: str) -> str:
    encoded = canonical_json_dumps([run_id, call_id]).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
