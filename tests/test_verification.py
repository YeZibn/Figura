from __future__ import annotations

import io
from dataclasses import replace

from PIL import Image, ImageDraw

from chartagent.gateway.history import GatewayHistoryStore
from chartagent.memory import SQLiteAgentMemory
from chartagent.spec import (
    ChartCoverage,
    ChartFigure,
    ChartFigureItem,
    ChartMetadata,
    ChartSpec,
    ChartSpecCollection,
    ChartType,
    CoverageBasis,
    CoverageStatus,
    DataPoint,
    FigureLayout,
    FigureSource,
    GenerationContext,
    GenerationCoverage,
    GenerationMode,
    GenerationSourceScope,
    SelectionBasis,
    chart_spec_digest,
)
from chartagent.tools.core import GeneratedImage
from chartagent.verification import (
    ChartManifest,
    GeneratedChartVerificationFlow,
    VerificationIssue,
    VerificationResult,
    content_digest,
    parse_vlm_decision,
    verify_chart_bytes,
)
from chartagent.verification.models import canonical_json


def _png(width: int = 24, height: int = 16) -> bytes:
    output = io.BytesIO()
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((2, 2, max(3, width // 3), height - 2), fill=(40, 120, 200))
    draw.rectangle((width // 2, 4, width - 3, height - 4), fill=(200, 80, 50))
    image.save(output, format="PNG")
    return output.getvalue()


def _spec(**kwargs) -> ChartSpec:
    return ChartSpec(
        metadata=ChartMetadata(ChartType.PIE, title="Sales"),
        dataset=[DataPoint(category="A", value=3), DataPoint(category="B", value=5)],
        **kwargs,
    )


def _manifest(image: bytes, spec: ChartSpec, *, run_id: str = "run_verify", session_id: str = "session_verify", staged_ref: str = "stg_preview_12345678") -> ChartManifest:
    return ChartManifest(
        staged_ref=staged_ref,
        run_id=run_id,
        session_id=session_id,
        work_key="chart:entry:call:0",
        tool_call_id="call_render",
        output_ordinal=0,
        image_sha256=content_digest(image),
        media_type="image/png",
        byte_count=len(image),
        chart_spec=spec.to_dict(),
        chart_spec_digest=chart_spec_digest(spec),
        chart_type=spec.metadata.chart_type.value,
        title="Sales",
        width=24,
        height=16,
    )


def test_deterministic_verification_checks_exact_spec_and_encoded_png():
    image = _png()
    result = verify_chart_bytes(_spec(), image, media_type="image/png", declared_width=24, declared_height=16)
    assert result.blocking is False
    assert result.checks["structure"] == "pass"
    assert result.checks["encoded_artifact"] == "pass"
    assert result.checks["render_fidelity"] == "not_run"

    mismatch = verify_chart_bytes(_spec(), image, media_type="image/png", declared_width=10, declared_height=10)
    assert mismatch.blocking is True
    assert any(issue.code == "dimension_mismatch" for issue in mismatch.issues)


def test_vlm_parser_enforces_exact_four_field_and_six_check_contract():
    payload = {
        "decision": "pass",
        "confidence": 0.9,
        "checks": {name: "pass" for name in ("chart_type", "orientation", "layout", "data_mapping", "labels", "readability")},
        "issues": [],
    }
    parsed = parse_vlm_decision(canonical_json(payload, limit=8000, name="test"))
    assert parsed.decision == "pass"
    assert len(parsed.checks) == 6

    payload["repair_kind"] = "evidence_needed"
    assert parse_vlm_decision(canonical_json(payload, limit=8000, name="test")).decision == "fail"


def test_verification_flow_stages_commits_and_promotes_one_immutable_result():
    spec = _spec()
    image = GeneratedImage(
        _png(),
        "image/png",
        "Sales chart",
        {"kind": "generated_chart", "width": 24, "height": 16, "chart_type": "pie", "title": "Sales"},
    )
    staged = []
    stored = []
    promoted = []
    committed = []

    def stage_sink(_image, manifest):
        staged.append(manifest)
        return {"stagedRef": manifest.staged_ref}

    def verification_sink(result):
        stored.append(result)
        return True

    def promotion_sink(_run_id, _session_id, staged_ref, verification_ref):
        promoted.append((staged_ref, verification_ref))
        return {"artifactId": "artifact_1234567890"}

    flow = GeneratedChartVerificationFlow(
        client=object(),
        chat_kwargs={},
        attachments=None,
        session_id="session_verify",
        stage_sink=stage_sink,
        verification_sink=verification_sink,
        promotion_sink=promotion_sink,
        execution_commit=lambda *args, **kwargs: committed.append((args, kwargs)),
    )
    events = []

    class Emitter:
        run_id = "run_verify"

        def emit(self, kind, **payload):
            events.append((kind, payload))

    outputs, facts = flow.process(
        [image], spec_value=spec.to_dict(), run_id="run_verify", model_entry_id="exe_model_1",
        call_id="call_render", turn=1, emitter=Emitter(),
    )

    assert len(staged) == len(stored) == len(promoted) == 1
    assert events == []
    assert outputs[0].metadata["artifactId"] == "artifact_1234567890"
    assert outputs[0].metadata["verification"]["status"] == "pass"
    assert facts[0]["verification"]["status"] == "pass"
    assert [kwargs["event_kind"] for _, kwargs in committed] == [
        "chart_staged", "chart_verification_result", "chart_promotion_result",
    ]


def test_source_linked_chart_without_authorized_scope_cannot_be_published():
    context = GenerationContext(
        mode=GenerationMode.TRANSFORM,
        source_scope=GenerationSourceScope("att_missing", ("panel_left",), revision=2),
        coverage=GenerationCoverage(),
        selection_basis=SelectionBasis.AGENT_RESOLVED,
        goal_summary="只检查指定 panel",
    )
    spec = _spec(generation_context=context)
    image = GeneratedImage(_png(), "image/png", "Sales chart", {"kind": "generated_chart", "width": 24, "height": 16, "chart_type": "pie", "title": "Sales"})
    published = []
    flow = GeneratedChartVerificationFlow(
        client=object(), chat_kwargs={}, attachments=None, session_id="session_verify",
        stage_sink=lambda _image, manifest: {"stagedRef": manifest.staged_ref},
        verification_sink=lambda _result: True,
        promotion_sink=lambda *_args: published.append(True),
    )
    outputs, _ = flow.process([image], spec_value=spec.to_dict(), run_id="run_verify", model_entry_id="exe_model_1", call_id="call_render", turn=1)
    assert outputs[0].metadata["verification"]["status"] == "fail"
    assert any(issue["code"] == "source_binding_failure" for issue in outputs[0].metadata["verification"]["issues"])
    assert published == []


def test_persistence_promotes_only_matching_pass_and_keeps_failed_preview(tmp_path):
    database = tmp_path / "sessions.db"
    store = GatewayHistoryStore(database, artifact_root=tmp_path / "run-artifacts")
    memory = SQLiteAgentMemory("verification", database=database)
    session_id = memory.session.id
    memory.close()
    store.create_run("run_verify", session_id)
    image = _png()
    manifest = _manifest(image, _spec(), session_id=session_id)
    reference = store.stage_chart(
        "run_verify", session_id,
        GeneratedImage(image, "image/png", "Sales chart", {"kind": "generated_chart", "width": 24, "height": 16}),
        manifest,
    )
    assert reference is not None and reference["stagedRef"] == manifest.staged_ref

    digest = content_digest(canonical_json(manifest.to_dict(), limit=64 * 1024, name="manifest").encode())
    failed = VerificationResult(
        "ver_failed_12345678", manifest.staged_ref, digest, 1, "fail",
        {"structure": "fail"}, (VerificationIssue("bad_chart", "dataset", "values are wrong"),), "fail", 0.0,
    )
    assert store.record_verification(failed) is not None
    assert store.promote_staged_chart("run_verify", session_id, manifest.staged_ref, failed.verification_ref) is None
    preview = store.get_chart_preview(session_id, "run_verify", manifest.staged_ref)
    assert preview == (image, "image/png")
    store.close()


def test_startup_cleanup_removes_orphaned_chart_files_and_preserves_evaluation_details(tmp_path):
    database = tmp_path / "sessions.db"
    artifact_root = tmp_path / "run-artifacts"
    memory = SQLiteAgentMemory("orphan-cleanup", database=database)
    session_id = memory.session.id
    memory.close()

    initial_store = GatewayHistoryStore(database, artifact_root=artifact_root)
    initial_store.create_run("run_orphan_cleanup", session_id)
    image = _png()
    manifest = _manifest(
        image,
        _spec(),
        run_id="run_orphan_cleanup",
        session_id=session_id,
        staged_ref="stg_cleanup_12345678",
    )
    initial_store.stage_chart(
        "run_orphan_cleanup",
        session_id,
        GeneratedImage(image, "image/png", "Sales chart", {"width": 24, "height": 16}),
        manifest,
    )

    retained_chart = artifact_root / session_id / f"{manifest.staged_ref}.bin"
    same_session_orphan = artifact_root / session_id / "uncommitted.bin"
    crashed_temp = artifact_root / session_id / ".stg_crashed.bin.deadbeef.tmp"
    stale_session_orphan = artifact_root / "stale-session" / "uncommitted.bin"
    same_session_orphan.write_bytes(b"orphan")
    crashed_temp.parent.mkdir(parents=True, exist_ok=True)
    crashed_temp.write_bytes(b"partial")
    stale_session_orphan.parent.mkdir(parents=True)
    stale_session_orphan.write_bytes(b"orphan")
    evaluation_detail = artifact_root / "history-details" / "run_eval" / "7.json"
    evaluation_detail.parent.mkdir(parents=True)
    evaluation_detail.write_text('{"detail":"preserve"}', encoding="utf-8")

    # Constructing the store models a Gateway restart after a crash between
    # the artifact rename and its manifest transaction.
    restarted_store = GatewayHistoryStore(database, artifact_root=artifact_root)

    assert retained_chart.is_file()
    assert restarted_store.get_chart_preview(session_id, "run_orphan_cleanup", manifest.staged_ref) == (image, "image/png")
    assert not same_session_orphan.exists()
    assert not crashed_temp.exists()
    assert not stale_session_orphan.parent.exists()
    assert evaluation_detail.read_text(encoding="utf-8") == '{"detail":"preserve"}'
    restarted_store.close()


def test_promote_checkpoint_resumes_from_stored_bytes_and_parent_manifest(tmp_path):
    database = tmp_path / "resume-verification.db"
    artifact_root = tmp_path / "resume-artifacts"
    memory = SQLiteAgentMemory("resume-verification", database=database)
    session_id = memory.session.id
    memory.close()
    store = GatewayHistoryStore(database, artifact_root=artifact_root)
    store.create_run("run_parent", session_id)
    store.create_run("run_child", session_id, parent_run_id="run_parent", root_run_id="run_parent")
    image_bytes = _png()
    image = GeneratedImage(
        image_bytes,
        "image/png",
        "Sales chart",
        {"kind": "generated_chart", "width": 24, "height": 16, "chart_type": "pie", "title": "Sales"},
    )
    work_key = "chart:exe_model_1:call_render:0"
    manifest = replace(
        _manifest(image_bytes, _spec(), run_id="run_parent", session_id=session_id),
        work_key=work_key,
    )
    assert store.stage_chart("run_parent", session_id, image, manifest) is not None
    assert store.get_staged_chart_by_work_key(session_id, work_key)["manifest"] == manifest
    manifest_digest = content_digest(canonical_json(manifest.to_dict(), limit=64 * 1024, name="manifest").encode())
    verification = VerificationResult(
        "ver_resume_12345678",
        manifest.staged_ref,
        manifest_digest,
        1,
        "pass",
        {"structure": "pass"},
        (),
        "pass",
        1.0,
    )
    assert store.record_verification(verification) is not None
    committed = []
    promotions = []
    flow = GeneratedChartVerificationFlow(
        client=object(),
        chat_kwargs={},
        attachments=None,
        session_id=session_id,
        verification_sink=store.record_verification,
        promotion_sink=lambda run_id, session, staged_ref, verification_ref: (
            promotions.append((run_id, session, staged_ref, verification_ref))
            or store.promote_staged_chart(run_id, session, staged_ref, verification_ref)
        ),
        execution_result_resolver=lambda key: (
            {"verification": verification.to_dict()}
            if key == f"verify:{work_key}"
            else None
        ),
        staged_chart_resolver=store.get_staged_chart_by_reference,
        execution_commit=lambda *args, **kwargs: committed.append((args, kwargs)),
    )

    flow.resume_checkpoint(
        action="promote",
        staged_ref=manifest.staged_ref,
        run_id="run_child",
        model_entry_id="exe_model_1",
        call_id="call_render",
        turn=2,
    )

    assert promotions == [("run_parent", session_id, manifest.staged_ref, verification.verification_ref)]
    assert [kwargs["work_key"] for _, kwargs in committed] == [f"verify:{work_key}", f"promote:{work_key}"]
    assert store.get_staged_chart_by_reference(session_id, manifest.staged_ref)["reference"]["artifactId"].startswith("artifact_")
    store.close()


def test_collection_figures_keep_independent_verification_and_promotion(monkeypatch):
    from chartagent.source_scope import SourceScopeResolution
    from chartagent.verification import flow as verification_flow
    from chartagent.verification.vlm import VLMDecision

    def figure(figure_id: str, panel_id: str) -> ChartFigure:
        context = GenerationContext(
            mode=GenerationMode.TRANSFORM,
            source_scope=GenerationSourceScope("att_collection", (panel_id,)),
            coverage=GenerationCoverage(
                basis=CoverageBasis.REQUESTED_SUBSET,
                source_series=("Sales",),
                represented_series=("Sales",),
                status=CoverageStatus.COMPLETE,
            ),
            selection_basis=SelectionBasis.AGENT_RESOLVED,
            goal_summary=f"验证 {panel_id} 图表",
        )
        return ChartFigure(
            figure_id=figure_id,
            source=FigureSource("att_collection", panel_id),
            layout=FigureLayout(columns=1),
            charts=[ChartFigureItem("sales", _spec())],
            coverage=ChartCoverage(["Sales"], ["Sales"], [], "complete"),
            generation_context=context,
        )

    collection = ChartSpecCollection(
        "collection_batch",
        [figure("figure_left", "panel_left"), figure("figure_right", "panel_right")],
    )
    assert collection.validate() == []

    monkeypatch.setattr(
        verification_flow,
        "resolve_generation_scope",
        lambda _attachments, context: SourceScopeResolution(
            status="resolved",
            attachment_id=context.source_scope.attachment_id,
            panel_ids=context.source_scope.panel_ids,
            content=_png(),
        ),
    )

    def vlm(_client, **kwargs):
        passed = kwargs["spec"].figure_id == "figure_left"
        checks = {name: "pass" for name in ("chart_type", "orientation", "layout", "data_mapping", "labels", "readability")}
        issues = () if passed else (VerificationIssue("wrong_values", "charts[0].dataset", "values do not match the authorized source"),)
        if not passed:
            checks["data_mapping"] = "fail"
        return VLMDecision("pass" if passed else "fail", 0.95, checks, issues)

    monkeypatch.setattr(verification_flow, "run_vlm_verification", vlm)

    images = [
        GeneratedImage(_png(), "image/png", "left", {"kind": "generated_chart", "width": 24, "height": 16, "figure_id": "figure_left"}),
        GeneratedImage(_png(), "image/png", "right", {"kind": "generated_chart", "width": 24, "height": 16, "figure_id": "figure_right"}),
    ]
    manifests = []
    promotions = []
    events = []

    class Emitter:
        run_id = "run_collection"

        def emit(self, kind, **payload):
            events.append((kind, payload))

    flow = GeneratedChartVerificationFlow(
        client=object(),
        chat_kwargs={},
        attachments=None,
        session_id="session_collection",
        stage_sink=lambda _image, manifest: manifests.append(manifest) or {"stagedRef": manifest.staged_ref},
        verification_sink=lambda _result: True,
        promotion_sink=lambda _run, _session, staged_ref, verification_ref: (
            promotions.append((staged_ref, verification_ref))
            or {"artifactId": f"artifact_{len(promotions):08d}"}
        ),
    )

    outputs, facts = flow.process(
        images,
        spec_value=collection.to_dict(),
        run_id="run_collection",
        model_entry_id="exe_collection",
        call_id="call_collection",
        turn=1,
        emitter=Emitter(),
    )

    assert [manifest.figure_id for manifest in manifests] == ["figure_left", "figure_right"]
    assert {manifest.collection_id for manifest in manifests} == {"collection_batch"}
    assert [manifest.child_chart_ids for manifest in manifests] == [("sales",), ("sales",)]
    assert [output.metadata["verification"]["status"] for output in outputs] == ["pass", "fail"]
    assert [output.metadata.get("artifactId") for output in outputs] == ["artifact_00000001", None]
    assert [fact["verification"]["status"] for fact in facts] == ["pass", "fail"]
    assert len({fact["stagedRef"] for fact in facts}) == 2
    assert len(promotions) == 1
    staged_events = [payload for kind, payload in events if kind == "chart_staged"]
    assert [event["parent_unit_id"] for event in staged_events] == [
        "generation:collection:collection_batch",
        "generation:collection:collection_batch",
    ]
