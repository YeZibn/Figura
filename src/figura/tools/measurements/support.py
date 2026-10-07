"""Build and validate local numeric support from actual sensor observations."""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy

from figura.shared.payloads import PayloadTooLarge, current_payload_limits, encode_json

from .contracts import measurement_counts, MAX_MEASUREMENT_SUPPORT

_NUMERIC_FIELDS = frozenset({"value", "x_value", "y_value", "baseline_value", "ratio", "area_ratio",
    "interval_start", "interval_end", "lower_whisker", "q1", "median", "q3", "upper_whisker",
    "upper_value", "lower_value", "series_value"})


def semantic_values(observations: Mapping) -> dict[str, float]:
    found = {}
    def walk(value, path, key=None):
        if isinstance(value, Mapping):
            for name, item in value.items():
                if name == "axes":
                    continue  # ticks/calibration support are not output chart readings
                walk(item, f"{path}/{name}", name)
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                walk(item, f"{path}/{index}", key)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            if key in _NUMERIC_FIELDS or key in {"upper_values", "lower_values"}:
                found[path] = float(value)
    walk(observations, "/observations")
    return found


def resolve_pointer(value, path):
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("invalid pointer")
    for token in path[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not token.isdecimal() or str(int(token)) != token:
                raise ValueError("invalid array pointer")
            value = value[int(token)]
        else:
            value = value[token]
    return value


def _set_pointer(value, path, replacement):
    head, tail = path.rsplit("/", 1)
    parent = resolve_pointer(value, head)
    if isinstance(parent, list):
        parent[int(tail)] = replacement
    else:
        parent[tail] = replacement


def validate_support(result):
    """Return a bounded (code,path,message) issue, without inspecting private pixels."""
    evidence = {item["id"]: item for item in result["evidence"]}
    calibrations = {item["id"]: item for item in result["calibrations"]}
    if len(evidence) != len(result["evidence"]) or len(calibrations) != len(result["calibrations"]):
        return "duplicate_support_id", "/evidence", "测量依据 ID 必须唯一。"
    if set(evidence) & set(calibrations):
        return "duplicate_support_id", "/calibrations", "校准与证据 ID 不得冲突。"
    coverage = result["coverage"]
    if coverage["detected_counts"] != measurement_counts(result["chart_type"], result["observations"]):
        return "coverage_count_mismatch", "/coverage/detected_counts", "检测数量必须与实际观察一致。"
    scope = coverage["requested_scope"]
    if (coverage["scope_kind"] == "scoped") != (scope is not None):
        return "scope_coverage_mismatch", "/coverage", "观察范围与覆盖说明不一致。"
    if scope is not None and not scope:
        return "invalid_scope", "/coverage/requested_scope", "局部观察范围不能为空。"
    for index, issue in enumerate(result["issues"]):
        if any(identity not in evidence for identity in issue["evidence_ids"]):
            return "dangling_evidence", f"/issues/{index}", "问题引用的证据不存在。"
        try:
            resolve_pointer(result, issue["field_path"])
        except (KeyError, IndexError, TypeError, ValueError):
            return "invalid_issue_path", f"/issues/{index}/field_path", "问题字段路径不存在。"
    for index, item in enumerate(result["calibrations"]):
        refs = item["support_evidence_ids"]
        if any(identity not in evidence for identity in refs):
            return "dangling_evidence", f"/calibrations/{index}", "校准引用的证据不存在。"
        from .cartesian import parse_numeric_text
        support_values = {parse_numeric_text(evidence[e]["text"]) for e in refs if evidence[e]["kind"] == "ocr"}
        support_values.discard(None)
        if item["supported"] and (len(set(refs)) < 2 or len(support_values)<2 or item["support_domain"][0] >= item["support_domain"][1]):
            return "invalid_calibration_support", f"/calibrations/{index}", "校准缺少非退化支持。"
        role = item["axis_role"]
        if ((item["kind"] == "axis" and role not in {"x","y"}) or
            (item["kind"] == "radial" and role != "radial") or
            (item["kind"] == "color_scale" and role != "color")):
            return "calibration_role_mismatch", f"/calibrations/{index}", "校准角色与类型不一致。"
    observations = result["observations"]
    for role, axis in observations.get("axes", {}).items():
        calibration = axis.get("calibration")
        if not calibration or not calibration.get("calibrated") or "support_tick_ids" not in calibration:
            continue
        selected = calibration["support_tick_ids"]
        tick_ids = {tick["id"] for tick in axis["ticks"] if tick["value"] is not None}
        if (len(selected) != calibration["support_count"] or len(selected) != len(set(selected))
                or any(identity not in tick_ids for identity in selected)):
            return "invalid_calibration_support", f"/observations/axes/{role}/calibration/support_tick_ids", "轴校准支持必须唯一对应可读刻度。"
    series_ids = [item["id"] for item in observations.get("series", [])]
    if len(series_ids) != len(set(series_ids)):
        return "duplicate_series_id", "/observations/series", "系列 ID 必须唯一。"
    if result["chart_type"] == "bar" and any(b["series_id"] not in series_ids for b in observations["bars"]):
        return "dangling_series", "/observations/bars", "柱引用的系列不存在。"
    if result["chart_type"] == "treemap":
        nodes = {n["id"]: n for n in observations["nodes"]}
        if len(nodes) != len(observations["nodes"]):
            return "duplicate_node_id", "/observations/nodes", "树图节点 ID 必须唯一。"
        for node in nodes.values():
            parent_id = node["parent_id"]
            if parent_id is not None and (parent_id not in nodes or nodes[parent_id]["role"] != "group"):
                return "invalid_parent", "/observations/nodes", "树图父节点不存在或不是分组。"
            if (node["area_ratio_basis"] == "parent_plot") != (node["area_ratio_parent_id"] is not None):
                return "invalid_ratio_basis", "/observations/nodes", "面积分母与父节点引用不一致。"
            if node["area_ratio_parent_id"] != parent_id:
                return "invalid_ratio_basis", "/observations/nodes", "面积比例必须引用实际父节点。"
            seen = {node["id"]}
            while parent_id is not None:
                if parent_id in seen:
                    return "cyclic_hierarchy", "/observations/nodes", "树图层级不能成环。"
                seen.add(parent_id)
                parent_id = nodes[parent_id]["parent_id"]
    values = semantic_values(result["observations"])
    provenance = {}
    for index, item in enumerate(result["value_provenance"]):
        path = item["field_path"]
        if path not in values or path in provenance:
            return "invalid_value_path", f"/value_provenance/{index}/field_path", "数值来源必须指向唯一非空语义数值。"
        refs = item["evidence_ids"]
        c_refs = item["calibration_ids"]
        if any(identity not in evidence for identity in refs) or any(identity not in calibrations for identity in c_refs):
            return "dangling_support", f"/value_provenance/{index}", "数值引用的支持不存在。"
        method = item["method"]
        if method in {"axis_calibration", "radial_calibration", "color_scale_calibration"}:
            kind = {"axis_calibration":"axis", "radial_calibration":"radial", "color_scale_calibration":"color_scale"}[method]
            if not any(evidence[e]["kind"] == "geometry" for e in refs) or not c_refs or any(not calibrations[c]["supported"] or calibrations[c]["kind"] != kind for c in c_refs):
                return "unsupported_value", f"/value_provenance/{index}", "数值缺少可用校准或对象几何。"
        elif method == "direct_text":
            from .cartesian import parse_numeric_text
            if not any(evidence[e]["kind"] == "ocr" and parse_numeric_text(evidence[e]["text"]) is not None and
                       abs(parse_numeric_text(evidence[e]["text"])-values[path]) < 1e-6 for e in refs):
                return "unsupported_value", f"/value_provenance/{index}", "直接读数缺少文字证据。"
        elif method == "geometry_ratio":
            geometry = [evidence[e] for e in refs if evidence[e]["kind"] == "geometry"]
            if not any(item["ratio_denominator"] is not None for item in geometry):
                return "unsupported_value", f"/value_provenance/{index}", "几何比例缺少明确分母。"
            field = path.rsplit("/", 1)[-1]
            if field == "ratio" and result["chart_type"] == "pie":
                sector = resolve_pointer(result, path.rsplit("/", 1)[0])
                center = observations.get("center_px")
                if (not center or abs(values[path] - sector["sweep_angle_deg"] / 360.0) > 1e-6
                        or not any(item["ratio_denominator"] == 360.0 and center in item["points_px"] for item in geometry)):
                    return "unsupported_value", f"/value_provenance/{index}", "扇区比例必须由角度与一周分母直接支持。"
            elif field == "area_ratio" and result["chart_type"] == "treemap":
                node = resolve_pointer(result, path.rsplit("/", 1)[0])
                bounds = node["bounds_px"]
                if node["parent_id"] is None:
                    denominator_rect = result["plot_area_px"]
                else:
                    parent = next((item for item in observations["nodes"] if item["id"] == node["parent_id"]), None)
                    denominator_rect = parent["bounds_px"] if parent else None
                numerator = bounds["width"] * bounds["height"] if bounds else 0
                denominator = (denominator_rect["width"] * denominator_rect["height"]
                               if denominator_rect else 0)
                if (not numerator or not denominator or abs(values[path] - numerator / denominator) > 1e-6
                        or not any(item["bounds_px"] == bounds and item["ratio_denominator"] == denominator for item in geometry)):
                    return "unsupported_value", f"/value_provenance/{index}", "树图面积比例必须由节点与其声明分母的像素面积支持。"
            else:
                return "unsupported_value", f"/value_provenance/{index}", "当前图表类型不支持该几何比例读数。"
        elif method == "derived":
            if not item["input_paths"] or any(p not in values for p in item["input_paths"]):
                return "unsupported_value", f"/value_provenance/{index}", "衍生数值缺少输入。"
        if method != "derived" and item["input_paths"]:
            return "invalid_derived_inputs", f"/value_provenance/{index}", "非衍生数值不能引用衍生输入。"
        provenance[path] = item
    if set(values) != set(provenance):
        return "missing_value_provenance", "/value_provenance", "每个非空语义数值必须保留依据。"
    visiting, visited = set(), set()
    def visit(path):
        if path in visiting:
            return False
        if path in visited:
            return True
        visiting.add(path)
        if not all(visit(p) for p in provenance[path]["input_paths"]):
            return False
        visiting.remove(path); visited.add(path)
        return True
    if not all(visit(p) for p in provenance):
        return "cyclic_value_support", "/value_provenance", "衍生数值支持不能形成环。"
    return None


def _retain_support_closure(result, evidence, calibrations, provenance, issues):
    """Drop support that is no longer reachable from retained values/issues."""
    changed = True
    while changed:
        changed = False
        available = semantic_values(result["observations"])
        for item in list(provenance):
            if item["method"] == "derived" and any(path not in available for path in item["input_paths"]):
                _set_pointer(result, item["field_path"], None)
                provenance.remove(item)
                changed = True
                result["status"] = "partial"
                result["truncated"] = True

    used_calibrations = {identity for item in provenance for identity in item["calibration_ids"]}
    calibrations = [item for item in calibrations if item["id"] in used_calibrations]
    used_evidence = {identity for item in provenance for identity in item["evidence_ids"]}
    used_evidence.update(identity for item in calibrations for identity in item["support_evidence_ids"])
    used_evidence.update(identity for item in issues for identity in item["evidence_ids"])
    evidence = [item for item in evidence if item["id"] in used_evidence]
    result.update(evidence=evidence, calibrations=calibrations,
                  value_provenance=provenance, issues=issues)


def build_axis_support(
    result,
    scope=None,
    *,
    support_limit=MAX_MEASUREMENT_SUPPORT,
    payload_limit=None,
):
    """Use retained tick/geometry evidence, never synthesize missing calibrations.

    Family-specific text/radial/color support can be supplied by a sensor later.
    This builder provides common Cartesian and observed-ratio support only.
    """
    result = deepcopy(result)
    observations = result["observations"]
    evidence = list(result.get("evidence", []))
    calibrations = list(result.get("calibrations", []))
    provenance = list(result.get("value_provenance", []))
    issues = list(result.get("issues", []))
    if not 0 <= support_limit <= MAX_MEASUREMENT_SUPPORT:
        raise ValueError("invalid support limit")
    if payload_limit is None:
        payload_limit = current_payload_limits().max_json_bytes
    if type(payload_limit) is not int or payload_limit <= 0:
        raise ValueError("invalid payload limit")
    axis_ids = {c["axis_role"]: c["id"] for c in calibrations
                if c["kind"] == "axis" and c["supported"]}
    for role, axis in observations.get("axes", {}).items():
        if role in axis_ids:
            continue
        calibration = axis.get("calibration")
        if not calibration or not calibration["calibrated"] or not axis["points_px"]:
            continue
        selected_ticks = calibration.get("support_tick_ids")
        ticks = [t for t in axis["ticks"] if t["value"] is not None and
                 (not selected_ticks or t["id"] in selected_ticks)]
        if len(ticks) < 2:
            continue
        if len(evidence) + len(ticks) > support_limit or len(calibrations) >= support_limit:
            result["truncated"] = True
            result["status"] = "partial"
            continue
        refs, positions = [], []
        for i, tick in enumerate(ticks):
            identity = f"axis_{role}_tick_{i}"
            x,y,w,h = tick["bbox_px"]
            evidence.append({"id":identity,"kind":"ocr","bounds_px":{"x":x,"y":y,"width":w,"height":h},"text":tick["text"],"confidence":tick["confidence"]})
            refs.append(identity)
            from .cartesian import axis_scalar
            positions.append(axis_scalar(tick["point_px"],axis["points_px"]))
        identity = f"axis_{role}_calibration"
        calibrations.append({"id":identity,"kind":"axis","axis_role":role,"supported":True,
            "support_evidence_ids":refs,"parameters":{"slope":calibration["slope"],"intercept":calibration["intercept"],"points_px":axis["points_px"]},
            "residual_value":calibration["residual_value"],"support_domain":[min(positions),max(positions)]})
        axis_ids[role] = identity
    existing = {item["field_path"] for item in provenance}
    for path,value in semantic_values(observations).items():
        if path in existing:
            continue
        # Find the nearest parent carrying the measured object's geometry.
        parent_path = path.rsplit("/",1)[0]
        parent = resolve_pointer(result,parent_path)
        points, bounds = [], None
        if isinstance(parent, Mapping):
            geometry_key = {"lower_value":"lower_position_px", "upper_value":"position_px",
                "median":"median_px", "q1":"q1_px", "q3":"q3_px", "lower_whisker":"lower_whisker_px", "upper_whisker":"upper_whisker_px"}.get(path.rsplit("/",1)[-1])
            bounds = parent.get("bounds_px")
            if geometry_key and parent.get(geometry_key) is not None:
                points.append(parent[geometry_key])
            for key in (() if points else ("position_px","center_px","median_px","q1_px","q3_px","lower_whisker_px","upper_whisker_px")):
                if parent.get(key) is not None:
                    points.append(parent[key])
        if not points and not bounds:
            # Area arrays have per-entry point geometry.
            if "/upper_values/" in path or "/lower_values/" in path:
                stem,index = path.rsplit("/",1)
                segment_path = stem.rsplit("/",1)[0]
                segment = resolve_pointer(result,segment_path)
                key = "upper_boundary_px" if "/upper_values/" in path else "lower_boundary_px"
                boundary = segment.get(key)
                if boundary and int(index)<len(boundary):
                    points.append(boundary[int(index)])
        field = path.split("/")[-1]
        ratio = field in {"ratio","area_ratio"}
        denominator = None
        if ratio and field == "ratio" and observations.get("center_px") is not None:
            points = [observations["center_px"]]
            denominator = 360.0
        elif ratio and bounds is not None:
            if parent.get("parent_id"):
                ancestor = next((n for n in observations["nodes"] if n["id"] == parent["parent_id"]),None)
                rect = ancestor["bounds_px"] if ancestor else None
            else:
                rect = result.get("plot_area_px")
            if rect:
                denominator = rect["width"]*rect["height"]
        role = "x" if field in {"x_value","interval_start","interval_end"} else "y"
        if observations.get("orientation") == "horizontal" and result["chart_type"] in {"bar","box_plot"}:
            role = "x"
        supported = bool(points or bounds) and (denominator is not None if ratio else role in axis_ids)
        if not supported or len(evidence)>=support_limit or len(provenance)>=support_limit:
            if supported:
                result["truncated"] = True
            _set_pointer(result,path,None)
            if len(issues)<32:
                issues.append({"code":"numeric_support_missing","field_path":path,"evidence_ids":[],"message":"读数缺少保留的几何或校准支持，保持未知。"})
            if result["status"]=="measured":result["status"]="partial"
            continue
        identity=f"value_geometry_{len(provenance)}"
        evidence.append({"id":identity,"kind":"geometry","bounds_px":bounds,"points_px":points,"ratio_denominator":denominator})
        provenance.append({"field_path":path,"method":"geometry_ratio" if ratio else "axis_calibration",
            "evidence_ids":[identity],"calibration_ids":[] if ratio else [axis_ids[role]],"input_paths":[],
            "error_bound":None if ratio else 2*abs(next(c for c in calibrations if c["id"]==axis_ids[role])["parameters"]["slope"])})
    result["coverage"]={"scope_kind":"scoped" if scope is not None else "full_source","requested_scope":scope,
        "structure_status":"established" if result["status"]=="measured" else "unknown" if result["status"] in {"no_evidence","unsupported"} else "partial",
        "detected_counts":measurement_counts(result["chart_type"],observations)}
    _retain_support_closure(result, evidence, calibrations, provenance, issues)

    # The result body must leave room for the durable ToolResultFact envelope.
    # This follows the configured Runtime payload budget, not a separate
    # cumulative Run quota. If support data alone exhausts that budget, clear
    # complete readings (and their derived dependents) until the closure fits.
    result_budget = max(0, payload_limit - min(1024, max(128, payload_limit // 100)))
    while True:
        try:
            encode_json(result, maximum=result_budget)
            break
        except PayloadTooLarge:
            if not provenance:
                raise
            dropped = provenance.pop()
            _set_pointer(result, dropped["field_path"], None)
            result["status"] = "partial"
            result["truncated"] = True
            if not any(issue["code"] == "support_budget_truncated" for issue in issues):
                if len(issues) < 32:
                    issues.append({"code": "support_budget_truncated", "field_path": "/observations",
                                   "evidence_ids": [], "message": "Runtime payload 预算不足以保留全部数值依据，未保留的读数已置为未知。"})
                warnings = result.setdefault("warnings", [])
                warning = "Runtime payload 预算不足以保留全部数值依据，部分读数已置为未知。"
                if warning not in warnings and len(warnings) < 32:
                    warnings.append(warning)
            _retain_support_closure(result, evidence, calibrations, provenance, issues)
            result["coverage"]["structure_status"] = "partial"
    return result
