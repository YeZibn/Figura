"""Guard final chart claims against committed verification and publication facts."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

_ARTIFACT_ID = re.compile(r"\bartifact_[A-Za-z0-9_-]{8,128}\b")
_PUBLISH_CLAIM = re.compile(r"已发布|发布成功|可下载|下载链接|正式图表|已保存为")
_VERIFIED_CLAIM = re.compile(r"验证通过|检查通过|确认无误")
_NEGATIVE_STATUS = re.compile(r"未通过|未发布|仅预览|无法确认|暂不可用|失败")


def _records(records: Sequence[Any]) -> tuple[dict[tuple[str, str], str], set[str]]:
    verified: dict[tuple[str, str], str] = {}
    promotions: list[Mapping[str, Any]] = []
    for record in records:
        kind = getattr(record, "kind", None)
        payload = getattr(record, "payload", None)
        if not isinstance(payload, Mapping):
            continue
        staged_ref = payload.get("stagedRef")
        verification_ref = payload.get("verificationRef")
        if kind == "verification_result" and isinstance(staged_ref, str) and isinstance(verification_ref, str):
            status = payload.get("status")
            if isinstance(status, str):
                verified[(staged_ref, verification_ref)] = status
        elif kind == "promotion_result":
            promotions.append(payload)
    committed_artifacts = {
        artifact_id
        for payload in promotions
        if isinstance(payload.get("artifactId"), str)
        and isinstance(payload.get("stagedRef"), str)
        and isinstance(payload.get("verificationRef"), str)
        and verified.get((payload["stagedRef"], payload["verificationRef"])) in {"pass", "pass_with_warning"}
        for artifact_id in (payload["artifactId"],)
    }
    return verified, committed_artifacts


def guard_final_answer(answer: str, records: Sequence[Any]) -> str:
    """Keep final claims consistent with immutable verification and promotion records."""
    verified, committed_artifacts = _records(records)
    artifact_references = set(_ARTIFACT_ID.findall(answer))
    invalid_references = artifact_references - committed_artifacts
    if invalid_references:
        return "本次没有可确认的已发布图表；生成结果只能依据当前验证状态查看。"

    statuses = set(verified.values())
    if _PUBLISH_CLAIM.search(answer) and not committed_artifacts:
        if statuses & {"fail", "unavailable"}:
            return "本次生成图表未通过验证或无法确认，目前仅可预览，尚未发布。"
        if statuses & {"pass", "pass_with_warning"}:
            return "图表验证已完成，但发布尚未确认，目前仅可预览，尚未发布。"
        return "本次没有已提交的图表发布结果，不能确认图表已发布。"

    if _VERIFIED_CLAIM.search(answer) and statuses and not statuses.issubset({"pass", "pass_with_warning"}):
        return "本次生成图表未通过验证或无法确认；我不能报告验证通过。"
    if statuses & {"fail", "unavailable"} and not _NEGATIVE_STATUS.search(answer):
        return f"{answer.rstrip()}\n\n本次生成图表未通过验证或无法确认，目前仅可预览，尚未发布。"
    return answer


__all__ = ["guard_final_answer"]
