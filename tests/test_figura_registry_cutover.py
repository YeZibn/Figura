from __future__ import annotations

import pytest

from figura.bootstrap import create_application
from figura.providers import FinishReason, MODEL_IDS, ProviderId, ProviderResponse, ProviderToolCall
from figura.runtime.models import RunCreateRequest, RunStatus


def _leave_v8_run(tmp_path, *, terminal: bool):
    application = create_application(tmp_path)
    coordinator = application.coordinator
    session = coordinator.create_session()
    run = coordinator.create_run(
        RunCreateRequest(
            session_id=session.session_id,
            text="continue an old execution",
            provider_id=ProviderId.QWEN.value,
            model_id=MODEL_IDS[ProviderId.QWEN],
            idempotency_key="old-registry-run",
        )
    )
    state = coordinator.read_run_state(session.session_id, run.run_id)
    attempt = coordinator.begin_provider_attempt(session.session_id, run.run_id, state.checkpoint.revision)
    claimed = coordinator.read_run_state(session.session_id, run.run_id)
    coordinator.commit_model_response(
        session.session_id,
        run.run_id,
        claimed.checkpoint.revision,
        ProviderResponse(
            ProviderId.QWEN,
            MODEL_IDS[ProviderId.QWEN],
            "old tool call",
            (ProviderToolCall("old-call", "measure_bars", "{}"),),
            FinishReason.TOOL_CALLS,
        ),
        provider_attempt_id=attempt.attempt_id,
        registry_version="figura-web-v8",
    )
    if terminal:
        state = coordinator.read_run_state(session.session_id, run.run_id)
        coordinator.interrupt_run(session.session_id, run.run_id, state.checkpoint.revision)
        assert coordinator.read_run_state(session.session_id, run.run_id).run.status is RunStatus.INTERRUPTED
    application.close()


def test_registry_v9_startup_blocks_active_v8_runs(tmp_path) -> None:
    _leave_v8_run(tmp_path, terminal=False)

    with pytest.raises(RuntimeError, match="Run bound to v8 is still active"):
        create_application(tmp_path)


def test_registry_v9_startup_allows_terminal_v8_history(tmp_path) -> None:
    _leave_v8_run(tmp_path, terminal=True)

    application = create_application(tmp_path)
    try:
        assert application.dispatcher._executor._tools.registry.version == "figura-web-v9"
    finally:
        application.close()
