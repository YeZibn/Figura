from types import SimpleNamespace

from chartagent.gateway.durable_execution import GatewayDurableExecutionPort


def test_gateway_durable_execution_port_delegates_with_bound_run_and_session():
    calls = []
    staged = {"stagedRef": "stg_bound_12345678"}
    verification = {"verificationRef": "ver_bound_12345678"}
    promotion = {"artifactId": "artifact_bound_12345678"}
    cached_result = {"verification": {"status": "pass"}}
    staged_chart = {"manifest": object(), "content": b"chart"}
    staged_work = {"manifest": object(), "content": b"work"}
    committed_entry = SimpleNamespace(entry_id="exe_bound_12345678", sequence=4)

    class History:
        def stage_chart(self, run_id, session_id, image, manifest):
            calls.append(("stage", run_id, session_id, image, manifest))
            return staged

        def record_verification(self, result):
            calls.append(("verification", result))
            return verification

        def promote_staged_chart(self, run_id, session_id, staged_ref, verification_ref):
            calls.append(("promote", run_id, session_id, staged_ref, verification_ref))
            return promotion

        def get_execution_entry_by_work_key_in_lineage(self, run_id, work_key):
            calls.append(("execution_result", run_id, work_key))
            return SimpleNamespace(payload=cached_result)

        def get_staged_chart_by_reference(self, session_id, staged_ref):
            calls.append(("staged_chart", session_id, staged_ref))
            return staged_chart

        def get_staged_chart_by_work_key(self, session_id, work_key):
            calls.append(("staged_work", session_id, work_key))
            return staged_work

    class Run:
        run_id = "run_bound_12345678"

        def commit_execution_entry(self, kind, payload, **kwargs):
            calls.append(("commit", kind, payload, kwargs))
            return committed_entry

    port = GatewayDurableExecutionPort(
        run=Run(),
        session_id="session_bound_12345678",
        history_store=History(),
    )
    image = object()
    manifest = SimpleNamespace(
        run_id="run_bound_12345678",
        session_id="session_bound_12345678",
    )
    recovered_manifest = SimpleNamespace(
        run_id="run_parent_12345678",
        session_id="session_bound_12345678",
        staged_ref="stg_bound_12345678",
    )
    result = object()

    assert port.stage_chart(image, manifest) is staged
    assert port.stage_chart(image, SimpleNamespace(run_id="other_run", session_id=manifest.session_id)) is None
    assert port.stage_chart(image, SimpleNamespace(run_id=manifest.run_id, session_id="other_session")) is None
    assert port.record_verification(result) is verification
    assert port.promote_chart(recovered_manifest, "ver_bound_12345678") is promotion
    assert port.promote_chart(
        SimpleNamespace(
            run_id="run_parent_12345678",
            session_id="other_session",
            staged_ref="stg_bound_12345678",
        ),
        "ver_bound_12345678",
    ) is None
    assert port.resolve_execution_result("verify:bound-work") is cached_result
    assert port.resolve_staged_chart("stg_bound_12345678") is staged_chart
    assert port.resolve_staged_work("stage:bound-work") is staged_work
    assert port.commit_execution_entry(
        "tool_result",
        {"ok": True},
        turn=2,
        next_action_kind="model",
        work_key="tool:bound-work",
        event_kind="tool_result_committed",
        event_payload={"call_id": "call-bound"},
    ) is committed_entry

    assert calls == [
        ("stage", "run_bound_12345678", "session_bound_12345678", image, manifest),
        ("verification", result),
        ("promote", "run_parent_12345678", "session_bound_12345678", "stg_bound_12345678", "ver_bound_12345678"),
        ("execution_result", "run_bound_12345678", "verify:bound-work"),
        ("staged_chart", "session_bound_12345678", "stg_bound_12345678"),
        ("staged_work", "session_bound_12345678", "stage:bound-work"),
        (
            "commit",
            "tool_result",
            {"ok": True},
            {
                "turn": 2,
                "next_action_kind": "model",
                "work_key": "tool:bound-work",
                "call_id": None,
                "message_entry_id": None,
                "staged_ref": None,
                "verification_ref": None,
                "event_kind": "tool_result_committed",
                "event_payload": {"call_id": "call-bound"},
            },
        ),
    ]
