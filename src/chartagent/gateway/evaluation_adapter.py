"""Read-only Gateway boundary for the Evaluation workbench.

The HTTP Gateway exposes evaluation data, but it does not own bundle parsing,
SQLite inspection, or redaction rules.  This adapter is the single bridge
between the two packages and translates Evaluation-specific failures into a
Gateway-owned error shape.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ..evaluation.reader import EvaluationReader, EvaluationReaderError


class EvaluationGatewayError(RuntimeError):
    """Safe error contract consumed by :class:`GatewayService`."""

    def __init__(self, code: str, status: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message[:240]


class EvaluationReaderAdapter:
    """Expose only read-only workbench operations to the Gateway service."""

    def __init__(self, data_root: str | Path) -> None:
        self._reader = EvaluationReader(data_root)

    def list_summaries(self) -> list[dict[str, Any]]:
        return self._call(self._reader.list_summaries)

    def get_evaluation(self, evaluation_id: str) -> dict[str, Any]:
        return self._call(self._reader.get_evaluation, evaluation_id)

    def get_case(self, evaluation_id: str, case_id: str) -> dict[str, Any]:
        return self._call(self._reader.get_case, evaluation_id, case_id)

    def get_history(
        self,
        evaluation_id: str,
        case_id: str,
        *,
        after_sequence: int = 0,
    ) -> dict[str, Any]:
        return self._call(
            self._reader.get_history,
            evaluation_id,
            case_id,
            after_sequence=after_sequence,
        )

    def get_history_details(
        self,
        evaluation_id: str,
        case_id: str,
        *,
        after_record_sequence: int = 0,
    ) -> dict[str, Any]:
        return self._call(
            self._reader.get_history_details,
            evaluation_id,
            case_id,
            after_record_sequence=after_record_sequence,
        )

    def get_resource(
        self,
        evaluation_id: str,
        resource_id: str,
        *,
        case_id: str | None = None,
    ) -> tuple[bytes, str]:
        return self._call(
            self._reader.get_resource,
            evaluation_id,
            resource_id,
            case_id=case_id,
        )

    @staticmethod
    def _call(operation: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        try:
            return operation(*args, **kwargs)
        except EvaluationReaderError as exc:
            raise EvaluationGatewayError(exc.code, exc.status, exc.message) from exc


__all__ = ["EvaluationGatewayError", "EvaluationReaderAdapter"]
