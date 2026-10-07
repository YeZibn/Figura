"""Offline measurement regression through authorized production tools.

No network request is made. Reference values are used only after measurement.
Run with conda run -n agent python scripts/evaluate_figura_measurements.py.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import platform
import subprocess
import tempfile
import re

import numpy as np
from figura.agent.execution_state import RunExecutionStateService
from figura.agent.execution_images import RunExecutionImageReader
from figura.providers import FinishReason, MODEL_IDS, ProviderFactory, ProviderId, ProviderResponse, ProviderToolCall
from figura.runtime.coordinator import RunCoordinator
from figura.runtime.models import RunCreateRequest
from figura.runtime.store import FiguraRunStore
from figura.runtime.tool_execution import DurableToolExecutor
from figura.sources.attachments import FiguraAttachmentService
from figura.sources.panels import FiguraPanelService
from figura.sources.repository import SourcesRepository
from figura.tools import ToolRegistry
from figura.tools.implementations.image import image_tool_definitions
from figura.tools.implementations.measure_chart import measure_chart_definition
from figura.tools.measurements.family_adapters import current_chart_family_adapters
from figura.tools.measurements.contracts import MEASUREMENT_RESULT_SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/figura_measurement"


def _commit_call(coordinator, session, run, registry, executor, name, args, index):
    state = coordinator.read_run_state(session, run)
    attempt = coordinator.begin_provider_attempt(session, run, state.checkpoint.revision)
    claimed = coordinator.read_run_state(session, run)
    # Synthetic model response records a tool intent, never invokes a model.
    coordinator.commit_model_response(session, run, claimed.checkpoint.revision,
        ProviderResponse(ProviderId.QWEN, MODEL_IDS[ProviderId.QWEN], "离线测量回归。",
            (ProviderToolCall(f"offline-{index}", name, json.dumps(args)),), FinishReason.TOOL_CALLS),
        provider_attempt_id=attempt.attempt_id, registry_version=registry.version)
    completed = executor.execute_pending(session, run)
    fact = completed.tool_facts[-1]
    payload = fact.payload
    return {"outcome": payload.outcome.value, "result": payload.result,
            "error": {"code": payload.error.code, "message": payload.error.message} if payload.error else None}


def _position(item):
    point = item.get("position_px") or item.get("center_px") or item.get("median_px")
    if point is not None:
        return list(point)
    rect = item.get("bounds_px")
    if rect is not None:
        return [rect["x"] + rect["width"]/2, rect["y"] + rect["height"]/2]
    return None


def flatten(result):
    o = result["observations"]
    kind = result["chart_type"]
    rows = []
    if kind in {"line", "scatter", "radar"}:
        for series in o["series"]:
            for point in series["vertices" if kind == "radar" else "points"]:
                label = point.get("category_label")
                if kind == "radar":
                    label = next((s["label"] for s in o["spokes"] if s["dimension_id"] == point["dimension_id"]), None)
                rows.append({**point, "position_px":_position(point), "series_label":series["label"], "label":label})
    elif kind == "area":
        for series in o["series"]:
            for segment in series["segments"]:
                for sample in segment.get("samples", []):
                    rows.append({**sample, "position_px":sample.get("upper_position_px") or sample.get("position_px"), "series_label":series["label"], "label":sample.get("category_label")})
    elif kind == "pie":
        for sector in o["sectors"]:
            angle = np.radians(sector["start_angle_deg"] + sector["sweep_angle_deg"]/2)
            center = o["center_px"]
            radius = .7 * o["outer_radius_px"]
            rows.append({**sector,"position_px":[center[0]+radius*np.sin(angle),center[1]-radius*np.cos(angle)]})
    else:
        collection = {"bar":"bars", "histogram":"bins", "box_plot":"groups", "heatmap":"cells", "treemap":"nodes"}[kind]
        for item in o[collection]:
            series_label = next((s["label"] for s in o.get("series",[]) if s["id"] == item.get("series_id")), None)
            label = item.get("category_label") or item.get("label")
            row_label = None
            if kind == "heatmap":
                def lookup(key, labels, prefix):
                    identity = item.get(key)
                    if not identity or not identity.startswith(prefix):
                        return None
                    index = int(identity[len(prefix):])-1
                    return labels[index] if 0 <= index < len(labels) else None
                label = lookup("column_id",o["column_labels"],"column_")
                row_label = lookup("row_id",o["row_labels"],"row_")
            rows.append({**item,"position_px":_position(item),"series_label":series_label,"label":label,"row_label":row_label})
    return rows


def normalize_label(value):
    if value is None:
        return None
    import unicodedata
    text = unicodedata.normalize("NFKC",value).strip()
    # Chinese labels conventionally omit presentation spacing before A/B/1.
    # Preserve English inter-word spaces and all substantive characters.
    return re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[A-Za-z0-9])","",text)


def reference_position(target):
    if target.get("role") == "group":
        bounds = target.get("bounds_px")
        if bounds is None:
            return None  # Root title has no independently visible rectangle.
        if isinstance(bounds, list):
            x,y,w,h = bounds
        else:
            x,y,w,h = (bounds[k] for k in ("x","y","width","height"))
        return [x+w/2,y+h/2]
    return target["position_px"]


def compare(reference, result, offset=(0,0)):
    expected = reference["targets"]
    actual = flatten(result)
    pairs = []
    for i,t in enumerate(expected):
        expected_position = reference_position(t)
        for j,p in enumerate(actual):
            if expected_position is None:
                if t.get("role") == "group" and p.get("role") == "group" and p.get("parent_id") is None and normalize_label(t.get("label")) == normalize_label(p.get("label")):
                    pairs.append((0.,i,j))
                continue
            if p["position_px"] is None:
                continue
            delta = np.asarray(p["position_px"]) + offset - expected_position
            distance = float(np.linalg.norm(delta))
            # Box centers versus reference medians require per-family geometry.
            if distance <= max(12, min(reference["plot_area_px"][2:])*.08):
                pairs.append((distance,i,j))
    used_t, used_p, matches = set(),set(),[]
    for distance,i,j in sorted(pairs):
        if i not in used_t and j not in used_p:
            used_t.add(i); used_p.add(j); matches.append((i,j))
    missing = len(expected)-len(matches)
    extra = len(actual)-len(matches)
    association_errors = []
    geometry_errors = []
    numeric_missing, numeric_errors = [],[]
    for i,j in matches:
        t,p = expected[i],actual[j]
        expected_position = reference_position(t)
        actual_position = np.asarray(p["position_px"]) + offset
        distance = float(np.linalg.norm(actual_position - expected_position)) if expected_position is not None else 0.
        if distance > reference["geometry_tolerance_px"]:
            geometry_errors.append({"target": t["id"], "expected_position_px": list(map(float, expected_position)),
                                    "actual_position_px": actual_position.tolist(), "distance_px": distance})
        if "role" in t and t["role"] != p.get("role"):
            association_errors.append({"target":t["id"],"field":"role","expected":t["role"],"actual":p.get("role")})
        if "parent_label" in t:
            parent = next((n for n in result["observations"]["nodes"] if n["id"]==p.get("parent_id")),None)
            actual_parent = parent["label"] if parent else None
            if normalize_label(t["parent_label"]) != normalize_label(actual_parent):
                association_errors.append({"target":t["id"],"field":"parent_label","expected":t["parent_label"],"actual":actual_parent})
        for key in ("series_label","label","row_label"):
            # OCR percent labels include the printed ratio; compare semantic text.
            actual_label = p.get(key)
            if reference["chart_type"] == "pie" and key == "label" and actual_label:
                actual_label = re.sub(r"[\d.%\s]+", "", actual_label)
            if t.get(key) is not None and normalize_label(t[key]) != normalize_label(actual_label):
                association_errors.append({"target":t["id"],"field":key,"expected":t[key],"actual":p.get(key)})
        for key,value in t["values"].items():
            prediction = p.get(key)
            if prediction is None:
                numeric_missing.append({"target":t["id"],"field":key})
                continue
            scale = "ratio" if key=="ratio" else "x" if key in {"x_value","interval_start","interval_end"} else "radial" if reference["chart_type"]=="radar" else "color" if reference["chart_type"]=="heatmap" else "y"
            tolerance = reference["numeric_tolerance"].get(scale,0)
            if abs(prediction-value)>tolerance:
                numeric_errors.append({"target":t["id"],"field":key,"expected":value,"actual":prediction,
                                       "error":abs(prediction-value),"tolerance":tolerance})
    return {"expected_objects":len(expected),"observed_objects":len(actual),"matched_objects":len(matches),
            "missing_objects":missing,"spurious_objects":extra,"association_errors":association_errors,
            "geometry_errors":geometry_errors,
            "numeric_missing":numeric_missing,"numeric_errors":numeric_errors,
            "provenance_validation":"not_available_in_contract_2" if result["schema_version"]<3 else "validated_by_tool",
            "calibration_support": [{"id":item["id"], "kind":item["kind"], "axis_role":item["axis_role"],
                "support_domain":item["support_domain"], "residual_value":item["residual_value"],
                "parameters":{key:value for key,value in item["parameters"].items() if key in {"slope","intercept"}}}
                for item in result.get("calibrations", [])],
            "passed": not(missing or extra or geometry_errors or association_errors or numeric_missing or numeric_errors)}


def evaluate(output: Path):
    manifest = json.loads((FIXTURES/"manifest.json").read_text())
    records = []
    with tempfile.TemporaryDirectory(prefix="figura-measurement-regression-") as temp:
        store = FiguraRunStore(Path(temp))
        repository = SourcesRepository(store.database)
        attachments = FiguraAttachmentService(repository,store.data_root)
        panels = FiguraPanelService(repository,store.data_root,attachments)
        # Dummy config enables local Run construction only; transport is never used.
        factory = ProviderFactory.from_env({"FIGURA_QWEN_API_KEY":"offline-placeholder","FIGURA_QWEN_BASE_URL":"https://offline.invalid/v1"},transport_factory=lambda _:None)
        coordinator = RunCoordinator(store,factory)
        inventory = RunExecutionStateService(coordinator,panels)
        reader = RunExecutionImageReader(attachments,panels)
        registry = ToolRegistry("offline-measurement-regression",(*image_tool_definitions(inventory.for_run,reader,panels),measure_chart_definition(inventory.for_run,reader,current_chart_family_adapters())))
        executor = DurableToolExecutor(store,registry)
        for case in manifest["cases"]:
            content = (FIXTURES/"images"/case["image"]).read_bytes()
            if sha256(content).hexdigest()!=case["sha256"]:
                raise ValueError(f'fixture hash mismatch: {case["case_id"]}')
            session = coordinator.create_session()
            attachment = attachments.upload(session.session_id,"chart.png",content)
            run = coordinator.create_run(RunCreateRequest(session_id=session.session_id,text="离线测量回归",attachment_ids=(attachment.attachment_id,),provider_id=ProviderId.QWEN.value,model_id=MODEL_IDS[ProviderId.QWEN],idempotency_key=case["case_id"]))
            panel_refs = []
            if len(case["charts"])>1:
                envelope = _commit_call(coordinator,session.session_id,run.run_id,registry,executor,"decompose_chart_image",{"attachment_id":attachment.attachment_id,"panels":[{"name":c["chart_id"],"points":[{"x":x,"y":y} for x,y in c["panel_polygon"]]} for c in case["charts"]]},0)
                panel_refs = envelope["result"]["panels"]
            for index,reference in enumerate(case["charts"],1):
                source = {"source_kind":"panel" if panel_refs else "attachment","source_id":panel_refs[index-1]["panel_id"] if panel_refs else attachment.attachment_id,"chart_type":reference["chart_type"]}
                envelope = _commit_call(coordinator,session.session_id,run.run_id,registry,executor,"measure_chart",source,index)
                row = {"case_id":case["case_id"],"chart_type":reference["chart_type"],"sha256":case["sha256"],"ocr_mode":"real_rapidocr"}
                if envelope["outcome"]!="succeeded":
                    row.update({"passed":False,"tool_error":envelope["error"]})
                else:
                    offset = (0,0)
                    if panel_refs:
                        polygon=reference["panel_polygon"]
                        offset=(round(min(p[0] for p in polygon)*case["image_size"][0]/1000),round(min(p[1] for p in polygon)*case["image_size"][1]/1000))
                    row.update(compare(reference,envelope["result"],offset))
                    row["measurement_status"]=envelope["result"]["status"]
                records.append(row)
                print(f'{case["case_id"]}/{reference["chart_type"]}: {"PASS" if row["passed"] else "FAIL"}',flush=True)
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()
    digest = sha256()
    for source in sorted((ROOT / "src/figura/tools/measurements").glob("*.py")):
        digest.update(source.name.encode())
        digest.update(source.read_bytes())
    report={"scope":"synthetic offline measurement regression; not Agent completion or external benchmark accuracy", "python":platform.python_version(),
            "git_revision":revision,"measurement_source_sha256":digest.hexdigest(),
            "manifest_sha256":sha256((FIXTURES/"manifest.json").read_bytes()).hexdigest(),
            "contract_version":MEASUREMENT_RESULT_SCHEMA_VERSION,"cases":records}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=ROOT/".figura/evaluation/measurement-regression.json")
    args=parser.parse_args()
    report=evaluate(args.output)
    print(f'{sum(c["passed"] for c in report["cases"])}/{len(report["cases"])} chart instances passed; report: {args.output}')
