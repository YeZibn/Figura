from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import sqlite3
import time
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from figura.agent.executor import AgentExecutor
from figura.providers import FinishReason, MODEL_IDS, ProviderFactory, ProviderId, ProviderToolCall
from figura.runtime.coordinator import RunCoordinator
from figura.runtime.models import ActionKind, RunStatus
from figura.runtime.records import (
    FinalAnswerFact,
    ModelResponseFact,
    ToolAttemptStartedFact,
    ToolCallFact,
    ToolResultFact,
)
from figura.runtime.store import FiguraRunStore
from figura.shared.media import ResourceImage
from figura.shared.resource_refs import ToolResourceRef
from figura.tools import (
    ReplayEffect,
    ToolDefinition,
    ToolImageOutput,
    ToolOutput,
    ToolRegistry,
)
from figura.tools.implementations.extract_text import EXTRACT_TEXT_RESULT_SCHEMA
from figura.tools.implementations.measurement_schema import SOURCE_PARAMETERS

from figura.bootstrap import recover_running_runs
from figura.gateway.dispatcher import RunDispatcher

from tests.figura_sources_support import make_attachment_service, make_durable_tool_executor
from tests.test_figura_agent_executor import (
    _FakeClient,
    _agent,
    _app,
    _commit_tool_response,
    _response,
    _app_with_image,
)


RECOVERY_REPEATS = 3
CONCURRENCY_REPEATS = 5
FAULT_CASES = (
    ("before_recovery_scan", "replay_safe", "tool_flow", "recoverable"),
    ("provider_attempt_before_send", "replay_safe", "tool_flow", "recoverable"),
    ("provider_after_send_before_response", "replay_safe", "tool_flow", "recoverable"),
    ("provider_response_before_commit", "replay_safe", "tool_flow", "recoverable"),
    ("provider_response_after_commit", "replay_safe", "tool_flow", "recoverable"),
    ("tool_attempt_after_claim", "replay_safe", "seeded_tool", "recoverable"),
    ("replay_safe_after_handler", "replay_safe", "seeded_tool", "recoverable"),
    ("idempotent_effect_before_result", "idempotent_local_write", "seeded_tool", "recoverable"),
    ("reconcile_after_attempt_claim", "reconcile_required", "seeded_tool", "fail_closed"),
    ("media_installed_before_result", "idempotent_local_write", "media_tool", "recoverable"),
    ("tool_result_after_commit", "replay_safe", "seeded_tool", "recoverable"),
    ("final_response_after_commit", "replay_safe", "plain_final", "recoverable"),
)


def _pause(control, point: str, details: dict[str, object] | None = None) -> None:
    if control is None:
        return
    control.send({"event": "fault_point", "point": point, **(details or {})})
    control.recv()


def _append_json_line(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _effect_ledger(root: Path, key: str) -> None:
    database = root / "external-effect-ledger.sqlite3"
    with sqlite3.connect(database, timeout=5) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS effects (idempotency_key TEXT PRIMARY KEY, apply_count INTEGER NOT NULL)"
        )
        connection.execute(
            "INSERT INTO effects(idempotency_key, apply_count) VALUES (?, 1) "
            "ON CONFLICT(idempotency_key) DO NOTHING",
            (key,),
        )


def _tiny_png(color: tuple[int, int, int] = (40, 100, 180), size: tuple[int, int] = (2, 2)) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, color=color).save(output, format="PNG")
    return output.getvalue()


def _registry(root: Path, effect: str, scenario: str, control, coordinator, session_id, run_id,
              *, media_tool: bool = False):
    replay_effect = ReplayEffect(effect)
    schema = {
        "type": "object",
        "properties": {"value": {"type": "integer"}},
        "required": ["value"],
        "additionalProperties": False,
    }
    result_schema = EXTRACT_TEXT_RESULT_SCHEMA if media_tool else schema

    def handler(context, arguments):
        state = coordinator.read_run_state(session_id, run_id)
        started = [
            fact.payload for fact in state.tool_facts
            if isinstance(fact.payload, ToolAttemptStartedFact)
        ]
        latest_attempt = started[-1] if started else None
        _append_json_line(root / "handler-invocations.jsonl", {
            "call_id": context.call_id,
            "attempt_id": latest_attempt.attempt_id if latest_attempt else None,
            "attempt_number": latest_attempt.attempt_number if latest_attempt else None,
            "replay_effect": replay_effect.value,
            "idempotency_key": context.idempotency_key,
        })

        if replay_effect is ReplayEffect.IDEMPOTENT_LOCAL_WRITE:
            if context.idempotency_key is None:
                raise AssertionError("idempotent handler did not receive its stable key")
            _effect_ledger(root, context.idempotency_key)
            if scenario == "idempotent_effect_before_result":
                _pause(control, scenario, {"call_id": context.call_id})

        if scenario == "replay_safe_after_handler":
            _pause(control, scenario, {"call_id": context.call_id})

        if media_tool:
            result = {
                "source_kind": arguments["source_kind"],
                "source_id": arguments["source_id"],
                "image_size": {"width": 2, "height": 2},
                "coordinate_system": "attachment_px",
                "available": False,
                "truncated": False,
                "snippets": [],
            }
            png = _tiny_png()
            image = ResourceImage.from_bytes(png)
            ref = ToolResourceRef("ocr", context.run_id, context.call_id)
            return ToolOutput(
                result,
                (ToolImageOutput(ref, "ocr_annotation", image),),
            )
        result = {"value": arguments["value"]}
        return ToolOutput(result)

    return ToolRegistry(
        "process-fault-v1",
        (
            ToolDefinition(
                name="extract_text" if media_tool else "fault_probe",
                description="Deterministic local recovery fixture.",
                parameters_schema=SOURCE_PARAMETERS if media_tool else schema,
                result_schema=result_schema,
                replay_effect=replay_effect,
                handler=handler,
                produces_images=media_tool,
            ),
        ),
    )


class _ControlledClient(_FakeClient):
    def __init__(self, *, root: Path, coordinator, session_id: str, run_id: str,
                 scenario: str, mode: str, control):
        super().__init__([])
        self.root = root
        self.coordinator = coordinator
        self.session_id = session_id
        self.run_id = run_id
        self.scenario = scenario
        self.mode = mode
        self.control = control

    def dispatch(self, prepared, *, on_stream_event=None):
        from figura.providers.models import ProviderStreamEvent, ProviderStreamEventKind

        self.requests.append(prepared.request)
        state = self.coordinator.read_run_state(self.session_id, self.run_id)
        attempt = state.provider_attempts[-1]
        request = state.provider_requests[-1]
        entry = {
            "attempt_id": attempt.attempt_id,
            "request_id": request.request_id,
            "request_fingerprint": request.request_fingerprint,
        }

        if self.scenario == "provider_attempt_before_send":
            _pause(self.control, self.scenario, entry)

        _append_json_line(self.root / "provider-dispatches.jsonl", entry)
        if self.scenario == "provider_after_send_before_response":
            _pause(self.control, self.scenario, entry)

        state = self.coordinator.read_run_state(self.session_id, self.run_id)
        has_tool_intent = any(isinstance(fact.payload, ToolCallFact) for fact in state.tool_facts)
        if self.mode == "plain_final":
            outcome = _response(content="恢复评测完成。")
        elif not has_tool_intent:
            outcome = _response(
                content="",
                reason=FinishReason.TOOL_CALLS,
                calls=(ProviderToolCall("fault-call-1", "fault_probe", '{"value":1}'),),
            )
        else:
            outcome = _response(content="恢复评测完成。")

        if on_stream_event is not None:
            on_stream_event(ProviderStreamEvent(ProviderStreamEventKind.RESPONSE_STARTED))
            if outcome.assistant_content:
                on_stream_event(ProviderStreamEvent(
                    ProviderStreamEventKind.TEXT_DELTA,
                    text=outcome.assistant_content,
                ))
            on_stream_event(ProviderStreamEvent(
                ProviderStreamEventKind.COMPLETED,
                usage=outcome.usage,
            ))
        return outcome


class _ControlledFactory:
    def __init__(self, client: _ControlledClient):
        self.client = client
        self.selections = []
        self.payload_limits = client.payload_limits

    def create(self, provider_id, model_id):
        self.selections.append((provider_id, model_id))
        self.client.provider_id = ProviderId(provider_id)
        self.client.model_id = model_id
        return self.client


def _provider_factory():
    return ProviderFactory.from_env(
        {
            "FIGURA_QWEN_API_KEY": "test-only-key",
            "FIGURA_QWEN_BASE_URL": "https://provider.example.test/v1",
        },
        transport_factory=lambda _profile: None,
    )


def _install_crash_hooks(store, coordinator, scenario: str, control) -> None:
    original_model_commit = coordinator.commit_model_response

    def commit_model_response(*args, **kwargs):
        response = kwargs.get("response")
        if response is None and len(args) >= 4:
            response = args[3]
        is_tool_response = bool(getattr(response, "tool_calls", ()))
        if scenario == "provider_response_before_commit" and is_tool_response:
            _pause(control, scenario)
        result = original_model_commit(*args, **kwargs)
        session_id = kwargs.get("session_id", args[0] if args else None)
        run_id = kwargs.get("run_id", args[1] if len(args) > 1 else None)
        state = coordinator.read_run_state(session_id, run_id)
        action = state.checkpoint.next_action
        if scenario == "provider_response_after_commit" and is_tool_response:
            _pause(control, scenario, {"checkpoint_action": action.action_kind.value if action else None})
        if scenario == "final_response_after_commit" and action is not None and action.action_kind is ActionKind.FINAL:
            _pause(control, scenario, {"checkpoint_action": action.action_kind.value})
        return result

    coordinator.commit_model_response = commit_model_response

    original_begin_tool_attempt = store.begin_tool_attempt

    def begin_tool_attempt(*args, **kwargs):
        result = original_begin_tool_attempt(*args, **kwargs)
        if scenario in {"tool_attempt_after_claim", "reconcile_after_attempt_claim"}:
            _pause(control, scenario)
        return result

    store.begin_tool_attempt = begin_tool_attempt

    original_tool_result = store.commit_tool_result

    def commit_tool_result(*args, **kwargs):
        if scenario == "media_installed_before_result":
            _pause(control, scenario)
        result = original_tool_result(*args, **kwargs)
        if scenario == "tool_result_after_commit":
            _pause(control, scenario)
        return result

    store.commit_tool_result = commit_tool_result


def _worker(root_text: str, session_id: str, run_id: str, effect: str, scenario: str,
            mode: str, control, race_gate: bool = False) -> None:
    root = Path(root_text)
    store = FiguraRunStore(root)
    coordinator = RunCoordinator(store, _provider_factory())
    control_for_actions = control if control is not None else None
    registry = _registry(
        root, effect, scenario, control_for_actions, coordinator, session_id, run_id,
        media_tool=mode == "media_tool",
    )
    client = _ControlledClient(
        root=root,
        coordinator=coordinator,
        session_id=session_id,
        run_id=run_id,
        scenario=scenario,
        mode=mode,
        control=control_for_actions,
    )
    factory = _ControlledFactory(client)
    agent = _agent(store, coordinator, registry, factory)
    _install_crash_hooks(store, coordinator, scenario, control_for_actions)
    dispatcher = RunDispatcher(agent, max_workers=1, max_queued=1, scan_interval=60)
    app = SimpleNamespace(dispatcher=dispatcher, coordinator=coordinator)
    try:
        if scenario == "before_recovery_scan":
            _pause(control, scenario)
        if race_gate:
            if control is None:
                raise AssertionError("race worker needs a control connection")
            control.send({"event": "race_ready"})
            control.recv()
        recover_running_runs(app)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            state = coordinator.read_run_state(session_id, run_id)
            if state.run.status is not RunStatus.RUNNING:
                break
            dispatcher.scan_ready(coordinator)
            time.sleep(0.02)
        state = coordinator.read_run_state(session_id, run_id)
        if control is not None:
            control.send({
                "event": "finished",
                "status": state.run.status.value,
                "terminal_code": state.run.terminal_code,
                "next_action": state.checkpoint.next_action.action_kind.value if state.checkpoint.next_action else None,
            })
    except BaseException as error:
        if control is not None:
            try:
                control.send({"event": "worker_error", "type": type(error).__name__, "message": str(error)[:300]})
            except (BrokenPipeError, EOFError, OSError):
                pass
        raise
    finally:
        dispatcher.close(wait=True)


def _json_lines(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _state_metrics(root: Path, session_id: str, run_id: str) -> dict[str, object]:
    store = FiguraRunStore(root)
    state = store.read_run_state(session_id, run_id)
    facts = [fact.payload for fact in state.tool_facts]
    attempts = [item for item in facts if isinstance(item, ToolAttemptStartedFact)]
    calls = [item for item in facts if isinstance(item, ToolCallFact)]
    results = [item for item in facts if isinstance(item, ToolResultFact)]
    final_answers = [record.payload for record in state.records if isinstance(record.payload, FinalAnswerFact)]
    model_responses = [record.payload for record in state.records if isinstance(record.payload, ModelResponseFact)]
    terminal_events = [event for event in state.events if event.event_kind.value in {
        "run_completed", "run_failed", "run_interrupted",
    }]
    with sqlite3.connect(root / "figura.sqlite3") as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    dispatches = _json_lines(root / "provider-dispatches.jsonl")
    handler_invocations = _json_lines(root / "handler-invocations.jsonl")
    attempt_ids = [item.get("attempt_id") for item in dispatches]
    repeated_attempt_ids = len(attempt_ids) - len(set(attempt_ids))
    invocations_by_call: dict[str, int] = {}
    for invocation in handler_invocations:
        call_id = str(invocation.get("call_id"))
        invocations_by_call[call_id] = invocations_by_call.get(call_id, 0) + 1
    repeated_handler_invocations = sum(max(0, count - 1) for count in invocations_by_call.values())
    with sqlite3.connect(root / "external-effect-ledger.sqlite3") as connection:
        try:
            effect_rows = connection.execute("SELECT idempotency_key, apply_count FROM effects").fetchall()
        except sqlite3.OperationalError:
            effect_rows = []
    png_files = list((root / "tool-media").rglob("*.png")) if (root / "tool-media").exists() else []
    committed_media_count = sum(len(item.attachments) for item in results)
    return {
        "run_status": state.run.status.value,
        "terminal_code": state.run.terminal_code,
        "checkpoint_action": state.checkpoint.next_action.action_kind.value if state.checkpoint.next_action else None,
        "record_count": len(state.records),
        "tool_call_count": len(calls),
        "tool_attempt_count": len(attempts),
        "tool_result_count": len(results),
        "model_response_count": len(model_responses),
        "final_answer_count": len(final_answers),
        "terminal_event_count": len(terminal_events),
        "provider_dispatch_count": len(dispatches),
        "provider_attempt_count": len(state.provider_attempts),
        "provider_retry_count": sum(item.retry_of_attempt_id is not None for item in state.provider_attempts),
        "provider_attempt_ids_reused": repeated_attempt_ids,
        "handler_invocation_count": len(handler_invocations),
        "repeated_handler_invocation_count": repeated_handler_invocations,
        "logical_tool_call_count": len(invocations_by_call),
        "effect_row_count": len(effect_rows),
        "effect_apply_counts": [row[1] for row in effect_rows],
        "stored_png_count": len(png_files),
        "published_media_attachment_count": committed_media_count,
        "state_consistent": True,
        "sqlite_integrity": integrity,
        "foreign_key_errors": len(foreign_keys),
    }


def _persist_case_report(root: Path, report: dict[str, object]) -> None:
    if not os.environ.get("FIGURA_RECOVERY_FAULT_RUN_DIR"):
        return
    target = root.parent / "case-report.json"
    temporary = target.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(target)


def _case_dir(request, tmp_path: Path) -> Path:
    root_text = os.environ.get("FIGURA_RECOVERY_FAULT_RUN_DIR")
    if not root_text:
        root = tmp_path / "case"
    else:
        slug = hashlib.sha256(request.node.nodeid.encode("utf-8")).hexdigest()[:16]
        root = Path(root_text) / "cases" / slug / "data"
    root.mkdir(parents=True, exist_ok=False)
    return root


def _create_case(root: Path, effect: str, mode: str):
    if mode == "media_tool":
        store, coordinator, session, run, _attachments, _panels, _images = _app_with_image(root)
    else:
        store, coordinator, session, run = _app(root)
    if mode in {"seeded_tool", "media_tool"}:
        if mode == "media_tool":
            attachment = make_attachment_service(store).list(session.session_id)[0]
            arguments = json.dumps({
                "source_kind": "attachment",
                "source_id": attachment.attachment_id,
            }, sort_keys=True)
        else:
            arguments = '{"value":1}'
        registry = _registry(
            root, effect, "seeded", None, coordinator, session.session_id, run.run_id,
            media_tool=mode == "media_tool",
        )
        _commit_tool_response(
            coordinator,
            session.session_id,
            run.run_id,
            registry,
            _response(
                content="",
                calls=(ProviderToolCall("fault-call-1", "extract_text" if mode == "media_tool" else "fault_probe", arguments),),
                reason=FinishReason.TOOL_CALLS,
            ),
        )
    return session.session_id, run.run_id


def _spawn_worker(ctx, root, session_id, run_id, effect, scenario, mode, *, wait_for_fault=True, race_gate=False):
    parent, child = ctx.Pipe(duplex=True)
    process = ctx.Process(
        target=_worker,
        args=(str(root), session_id, run_id, effect, scenario, mode, child, race_gate),
    )
    process.start()
    child.close()
    return process, parent


def _wait_for_message(connection, process, timeout: float = 15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if connection.poll(0.05):
            return connection.recv()
        if not process.is_alive():
            raise AssertionError(f"worker exited before signaling; exitcode={process.exitcode}")
    raise AssertionError("worker did not reach the expected recovery boundary")


def _kill_at_fault(ctx, root, session_id, run_id, effect, scenario, mode):
    process, connection = _spawn_worker(ctx, root, session_id, run_id, effect, scenario, mode)
    try:
        message = _wait_for_message(connection, process)
        assert message["event"] == "fault_point", message
        assert message["point"] == scenario, message
        process.kill()
        process.join(10)
        assert not process.is_alive()
        assert process.exitcode is not None and process.exitcode != 0
        return message
    finally:
        connection.close()
        if process.is_alive():
            process.kill()
            process.join(5)


def _resume_case(ctx, root, session_id, run_id, effect, mode):
    process, connection = _spawn_worker(ctx, root, session_id, run_id, effect, "", mode)
    try:
        message = _wait_for_message(connection, process, timeout=30)
        while message["event"] != "finished":
            if message["event"] == "worker_error":
                raise AssertionError(f"recovery worker failed: {message}")
            message = _wait_for_message(connection, process, timeout=30)
        process.join(10)
        assert not process.is_alive()
        assert process.exitcode == 0
        return message
    finally:
        connection.close()
        if process.is_alive():
            process.kill()
            process.join(5)


@pytest.mark.parametrize(
    "scenario,effect,mode,case_class,repetition",
    [(*case, repetition) for case in FAULT_CASES for repetition in range(RECOVERY_REPEATS)],
)
def test_sigkill_at_run_checkpoint_boundaries(
    tmp_path, request, record_property, scenario, effect, mode, case_class, repetition,
):
    root = _case_dir(request, tmp_path)
    session_id, run_id = _create_case(root, effect, mode)
    ctx = multiprocessing.get_context("spawn")
    _kill_at_fault(ctx, root, session_id, run_id, effect, scenario, mode)
    before_recovery = _state_metrics(root, session_id, run_id)
    recovered = _resume_case(ctx, root, session_id, run_id, effect, mode)
    after_recovery = _state_metrics(root, session_id, run_id)

    expected_status = "failed" if case_class == "fail_closed" else "completed"
    expected_terminal = "tool_outcome_unknown" if case_class == "fail_closed" else None
    policy_correct = (
        after_recovery["run_status"] == expected_status
        and after_recovery["terminal_code"] == expected_terminal
    )
    duplicate_side_effects = sum(max(0, value - 1) for value in after_recovery["effect_apply_counts"])
    expected_tool_calls = 0 if mode == "plain_final" else 1
    state_consistent = (
        after_recovery["sqlite_integrity"] == "ok"
        and after_recovery["foreign_key_errors"] == 0
        and after_recovery["provider_attempt_ids_reused"] == 0
        and after_recovery["terminal_event_count"] == 1
        and after_recovery["final_answer_count"] == (1 if expected_status == "completed" else 0)
        and after_recovery["tool_call_count"] == expected_tool_calls
        and after_recovery["tool_result_count"] == (expected_tool_calls if expected_status == "completed" else 0)
    )
    if scenario == "media_installed_before_result":
        assert before_recovery["tool_result_count"] == 0
        assert before_recovery["stored_png_count"] == 1
        assert before_recovery["published_media_attachment_count"] == 0
        assert after_recovery["stored_png_count"] == 1
        assert after_recovery["published_media_attachment_count"] == 1
    if case_class == "fail_closed":
        assert after_recovery["handler_invocation_count"] == 0
        assert after_recovery["tool_result_count"] == 0

    report = {
        "scenario": scenario,
        "repetition": repetition + 1,
        "case_class": case_class,
        "recovery_success": after_recovery["run_status"] == "completed",
        "policy_correct": policy_correct,
        "duplicate_side_effects": duplicate_side_effects,
        "repeated_handler_invocations": after_recovery["repeated_handler_invocation_count"],
        "state_consistent": state_consistent,
        "before_recovery": before_recovery,
        "after_recovery": after_recovery,
    }
    _persist_case_report(root, report)

    for key, value in report.items():
        if key not in {"before_recovery", "after_recovery"}:
            record_property(key, str(value))
    record_property("interrupted_status", str(before_recovery["run_status"]))
    record_property("provider_attempt_count", str(after_recovery["provider_attempt_count"]))
    record_property("provider_dispatch_count", str(after_recovery["provider_dispatch_count"]))
    record_property("tool_attempt_count", str(after_recovery["tool_attempt_count"]))
    record_property("handler_invocation_count", str(after_recovery["handler_invocation_count"]))
    record_property("stored_png_count", str(after_recovery["stored_png_count"]))
    record_property("published_media_attachment_count", str(after_recovery["published_media_attachment_count"]))

    assert recovered["event"] == "finished"
    assert policy_correct
    assert duplicate_side_effects == 0
    assert state_consistent


@pytest.mark.parametrize("repetition", range(CONCURRENCY_REPEATS))
def test_two_gateway_processes_compete_for_one_recovery_owner(tmp_path, request, record_property, repetition):
    root = _case_dir(request, tmp_path)
    session_id, run_id = _create_case(root, "replay_safe", "tool_flow")
    ctx = multiprocessing.get_context("spawn")
    workers = [_spawn_worker(ctx, root, session_id, run_id, "replay_safe", "", "tool_flow", race_gate=True)
               for _ in range(2)]
    try:
        ready = [_wait_for_message(connection, process) for process, connection in workers]
        assert all(message["event"] == "race_ready" for message in ready), ready
        for _process, connection in workers:
            connection.send({"go": True})
        finished = []
        for process, connection in workers:
            while True:
                message = _wait_for_message(connection, process, timeout=30)
                if message["event"] == "worker_error":
                    raise AssertionError(f"race worker failed: {message}")
                if message["event"] == "finished":
                    finished.append(message)
                    break
            process.join(10)
            assert not process.is_alive() and process.exitcode == 0
    finally:
        for process, connection in workers:
            connection.close()
            if process.is_alive():
                process.kill()
                process.join(5)

    metrics = _state_metrics(root, session_id, run_id)
    policy_correct = metrics["run_status"] == "completed"
    no_duplicate_dispatches = metrics["provider_attempt_ids_reused"] == 0
    state_consistent = (
        metrics["sqlite_integrity"] == "ok"
        and metrics["foreign_key_errors"] == 0
        and metrics["final_answer_count"] == 1
        and metrics["terminal_event_count"] == 1
        and metrics["tool_call_count"] == 1
        and metrics["tool_result_count"] == 1
    )
    report = {
        "scenario": "two_gateway_processes_compete",
        "repetition": repetition + 1,
        "case_class": "concurrency",
        "recovery_success": policy_correct,
        "policy_correct": policy_correct and no_duplicate_dispatches,
        "duplicate_side_effects": 0,
        "repeated_handler_invocations": metrics["repeated_handler_invocation_count"],
        "state_consistent": state_consistent,
        "after_recovery": metrics,
    }
    _persist_case_report(root, report)
    for key, value in report.items():
        if key != "after_recovery":
            record_property(key, str(value))
    record_property("provider_attempt_count", str(metrics["provider_attempt_count"]))
    record_property("provider_dispatch_count", str(metrics["provider_dispatch_count"]))
    record_property("tool_attempt_count", str(metrics["tool_attempt_count"]))
    record_property("handler_invocation_count", str(metrics["handler_invocation_count"]))
    assert len(finished) == 2
    assert policy_correct and no_duplicate_dispatches and state_consistent

