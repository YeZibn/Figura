"""Guard final chart claims against committed verification and publication facts."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

_ARTIFACT_ID = re.compile(r"\bartifact_[A-Za-z0-9_-]{8,128}\b")
_PUBLISH_CLAIM = re.compile(r"已发布|发布成功|可下载|下载链接|正式图表|已保存为")
_VERIFIED_CLAIM = re.compile(r"验证通过|检查通过|确认无误")
_NEGATIVE_STATUS = re.compile(r"未通过|未发布|仅预览|无法确认|暂不可用|失败")
_PASS_STATUSES = {"pass", "pass_with_warning"}


def _committed_facts(
    records: Sequence[Mapping[str, Any]],
) -> tuple[dict[tuple[str, str], str], dict[str, tuple[str, str]]]:
    verified: dict[tuple[str, str], str] = {}
    promotions: list[Mapping[str, Any]] = []
    for record in records:
        kind = record.get("kind")
        payload = record.get("payload")
        if not isinstance(payload, Mapping):
            continue
        staged_ref = payload.get("stagedRef")
        verification_ref = payload.get("verificationRef")
        if kind == "verification_result":
            if isinstance(staged_ref, str) and isinstance(verification_ref, str):
                status = payload.get("status")
                if isinstance(status, str):
                    verified[(staged_ref, verification_ref)] = status
        elif kind == "promotion_result":
            promotions.append(payload)

    published: dict[str, tuple[str, str]] = {}
    for payload in promotions:
        artifact_id = payload.get("artifactId")
        staged_ref = payload.get("stagedRef")
        verification_ref = payload.get("verificationRef")
        if (
            isinstance(artifact_id, str)
            and isinstance(staged_ref, str)
            and isinstance(verification_ref, str)
            and verified.get((staged_ref, verification_ref)) in _PASS_STATUSES
        ):
            published[artifact_id] = (staged_ref, verification_ref)
    return verified, published


def _current_output_statuses(
    artifacts: Sequence[Mapping[str, Any]],
    verified: Mapping[tuple[str, str], str],
) -> dict[tuple[str, str], str]:
    statuses: dict[tuple[str, str], str] = {}
    unresolved_index = 0
    for artifact in artifacts:
        if artifact.get("kind") != "generated_chart":
            continue
        staged_ref = artifact.get("staged_ref")
        verification = artifact.get("verification")
        verification_ref = verification.get("verificationRef") if isinstance(verification, Mapping) else None
        if isinstance(staged_ref, str) and isinstance(verification_ref, str):
            key = (staged_ref, verification_ref)
            statuses[key] = verified.get((staged_ref, verification_ref), "unavailable")
        else:
            statuses[("unresolved", str(unresolved_index))] = "unavailable"
            unresolved_index += 1
    return statuses


def guard_final_answer(
    answer: str,
    records: Sequence[Mapping[str, Any]],
    current_output_artifacts: Sequence[Mapping[str, Any]],
) -> str:
    """Keep final claims consistent with exact facts for the current chart output."""
    verified, published = _committed_facts(records)
    output_statuses = _current_output_statuses(current_output_artifacts, verified)
    artifact_references = set(_ARTIFACT_ID.findall(answer))
    if artifact_references - published.keys():
        return "本次没有可确认的已发布图表；生成结果只能依据当前验证状态查看。"

    output_keys = set(output_statuses)
    successful_outputs = {
        key for key, status in output_statuses.items()
        if status in _PASS_STATUSES
    }
    published_outputs = {
        (staged_ref, verification_ref)
        for staged_ref, verification_ref in published.values()
    }
    all_outputs_verified = bool(output_statuses) and len(successful_outputs) == len(output_statuses)
    all_outputs_published = (
        bool(output_statuses)
        and all_outputs_verified
        and output_keys.issubset(published_outputs)
    )

    if _PUBLISH_CLAIM.search(answer) and not all_outputs_published:
        statuses = set(output_statuses.values())
        if statuses & {"fail", "unavailable"}:
            return "本次生成图表未通过验证或无法确认，目前仅可预览，尚未发布。"
        if output_statuses:
            return "图表验证已完成，但当前输出的发布尚未全部确认，目前仅可预览，尚未发布。"
        if artifact_references:
            return answer
        return "本次没有当前图表发布结果，不能确认图表已发布。"

    if _VERIFIED_CLAIM.search(answer) and not all_outputs_verified:
        if output_statuses:
            return "本次当前输出中有图表未通过验证或无法确认；我不能报告验证通过。"
        return "本次没有当前图表验证结果；我不能报告验证通过。"

    if (
        output_statuses
        and set(output_statuses.values()) & {"fail", "unavailable"}
        and not _NEGATIVE_STATUS.search(answer)
    ):
        return f"{answer.rstrip()}\n\n本次生成图表未通过验证或无法确认，目前仅可预览，尚未发布。"
    return answer


__all__ = ["guard_final_answer"]
