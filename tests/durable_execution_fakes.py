from __future__ import annotations

from types import SimpleNamespace
from typing import Any


class FakeDurableExecutionPort:
    def __init__(self) -> None:
        self.staged: list[tuple[Any, Any]] = []
        self.verifications: list[Any] = []
        self.promotions: list[tuple[Any, str]] = []
        self.commits: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        self.execution_results: dict[str, Any] = {}
        self.staged_charts: dict[str, Any] = {}
        self.staged_work: dict[str, Any] = {}
        self.published_artifact_ids: list[str] = []

    def stage_chart(self, image, manifest):
        self.staged.append((image, manifest))
        staged_ref = manifest.staged_ref
        self.staged_charts[staged_ref] = {
            "manifest": manifest,
            "content": image.content,
            "mediaType": image.media_type,
        }
        self.staged_work[manifest.work_key] = self.staged_charts[staged_ref]
        return {"stagedRef": staged_ref}

    def record_verification(self, result):
        self.verifications.append(result)
        return {"verificationRef": result.verification_ref}

    def promote_chart(self, manifest, verification_ref):
        self.promotions.append((manifest, verification_ref))
        artifact_id = (
            self.published_artifact_ids.pop(0)
            if self.published_artifact_ids
            else f"artifact_fake_{len(self.promotions):08d}"
        )
        return {"artifactId": artifact_id}

    def resolve_execution_result(self, work_key):
        return self.execution_results.get(work_key)

    def resolve_staged_chart(self, staged_ref):
        return self.staged_charts.get(staged_ref)

    def resolve_staged_work(self, work_key):
        return self.staged_work.get(work_key)

    def commit_execution_entry(self, kind, payload, **kwargs):
        self.commits.append((kind, payload, kwargs))
        sequence = len(self.commits)
        return SimpleNamespace(entry_id=f"exe_fake_{sequence:08d}", sequence=sequence)
