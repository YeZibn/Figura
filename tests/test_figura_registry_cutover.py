from __future__ import annotations

import pytest

from figura.bootstrap import create_application
from figura.providers import FinishReason, MODEL_IDS, ProviderId, ProviderResponse, ProviderToolCall
from figura.runtime.models import RunCreateRequest, RunStatus


def _leave_older_registry_run(tmp_path, *, registry_version: str, terminal: bool):
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
        registry_version=registry_version,
    )
    if terminal:
        state = coordinator.read_run_state(session.session_id, run.run_id)
        coordinator.interrupt_run(session.session_id, run.run_id, state.checkpoint.revision)
        assert coordinator.read_run_state(session.session_id, run.run_id).run.status is RunStatus.INTERRUPTED
    application.close()


@pytest.mark.parametrize("old_version", ["figura-web-v8", "figura-web-v9"])
def test_registry_v10_startup_blocks_active_older_registry_runs(tmp_path, old_version) -> None:
    _leave_older_registry_run(tmp_path, registry_version=old_version, terminal=False)

    with pytest.raises(RuntimeError, match="older bound Run is still active"):
        create_application(tmp_path)


@pytest.mark.parametrize("old_version", ["figura-web-v8", "figura-web-v9"])
def test_registry_v10_startup_allows_terminal_older_registry_history(tmp_path, old_version) -> None:
    _leave_older_registry_run(tmp_path, registry_version=old_version, terminal=True)

    application = create_application(tmp_path)
    try:
        assert application.dispatcher._executor._tools.registry.version == "figura-web-v10"
    finally:
        application.close()
