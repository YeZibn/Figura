"""Tool adapter for the generated-chart review service."""

from __future__ import annotations

from typing import Any

from ...review import ChartReviewManager, MAX_REVIEW_EVIDENCE, MAX_REVIEW_TEXT
from ..core.definition import Tool


def review_generated_chart_tool(manager: ChartReviewManager) -> Tool:
    """Build the model-facing review transition tool for one manager."""
    def review_generated_chart(
        candidate_id: str,
        review_id: str,
        decision: dict | None = None,
    ) -> dict[str, Any]:
        candidate = manager.get(candidate_id, review_id)
        if candidate is None:
            return {"error": "candidate or review context is not authorized"}
        result = manager.process(candidate, decision=decision)
        return {
            "candidate": result.safe_metadata(),
            "review": result.review.to_dict() if result.review else None,
        }

    return Tool(
        "review_generated_chart",
        "Complete the mandatory review for one generated chart candidate. Use the exact candidate_id and review_id from the pending render result, and submit decision only when the review status requires a bounded model decision; do not call this for ordinary source-image analysis or invent identifiers. The result contains candidate, review checks, evidence, publication status, and rejection or warning details. Tool completion means the review transition was processed, not that publication succeeded: claim the chart as published only when publication_status is published or published_with_warning.",
        {
            "type": "object",
            "properties": {
                "candidate_id": {"type": "string", "minLength": 1, "maxLength": 120, "description": "Exact candidateId returned by render_chart or an earlier review result."},
                "review_id": {"type": "string", "minLength": 1, "maxLength": 120, "description": "Exact reviewId paired with candidate_id in the pending result."},
                "decision": {
                    "type": "object",
                    "properties": {
                        "accepted": {"type": "boolean", "description": "Whether the candidate passes the requested semantic review."},
                        "reason": {"type": "string", "maxLength": MAX_REVIEW_TEXT, "description": "Short bounded reason for accepting or rejecting the candidate."},
                        "evidence_refs": {"type": "array", "items": {"type": "string", "maxLength": 120, "description": "Reference to supplied review evidence, such as a check or overlay."}, "maxItems": MAX_REVIEW_EVIDENCE, "description": "Evidence references required when accepting a semantically reviewed candidate."},
                    },
                    "required": ["accepted"],
                    "additionalProperties": False,
                },
            },
            "required": ["candidate_id", "review_id"],
            "additionalProperties": False,
        },
        review_generated_chart,
        group="chart-review",
    )


__all__ = ["review_generated_chart_tool"]
