"""Evaluation workbench application boundary for the Gateway."""

from __future__ import annotations

from typing import Any

from .evaluation_adapter import EvaluationGatewayError
from .protocol import GatewayFault, success


class EvaluationWorkbenchMixin:
    """Expose read-only evaluation operations without bundle internals."""

    def list_evaluations(self) -> dict[str, Any]:
        return success({"evaluations": self._evaluation_reader.list_summaries()})

    def get_evaluation(self, evaluation_id: object) -> dict[str, Any]:
        return success(self._evaluation_call(lambda: self._evaluation_reader.get_evaluation(self._evaluation_id(evaluation_id))))

    def get_evaluation_case(self, evaluation_id: object, case_id: object) -> dict[str, Any]:
        return success(self._evaluation_call(
            lambda: self._evaluation_reader.get_case(
                self._evaluation_id(evaluation_id),
                self._case_id(case_id),
            )
        ))

    def get_evaluation_history(
        self,
        evaluation_id: object,
        case_id: object,
        after_sequence: int = 0,
    ) -> dict[str, Any]:
        return success(self._evaluation_call(
            lambda: self._evaluation_reader.get_history(
                self._evaluation_id(evaluation_id),
                self._case_id(case_id),
                after_sequence=max(0, int(after_sequence)),
            )
        ))

    def get_evaluation_history_details(
        self,
        evaluation_id: object,
        case_id: object,
        after_record_sequence: int = 0,
    ) -> dict[str, Any]:
        return success(self._evaluation_call(
            lambda: self._evaluation_reader.get_history_details(
                self._evaluation_id(evaluation_id),
                self._case_id(case_id),
                after_record_sequence=max(0, int(after_record_sequence)),
            )
        ))

    def get_evaluation_resource(
        self,
        evaluation_id: object,
        resource_id: object,
        *,
        case_id: object | None = None,
    ) -> tuple[bytes, str]:
        result = self._evaluation_call(
            lambda: self._evaluation_reader.get_resource(
                self._evaluation_id(evaluation_id),
                self._resource_id(resource_id),
                case_id=self._case_id(case_id) if case_id is not None else None,
            )
        )
        return result

    @staticmethod
    def _evaluation_id(value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise GatewayFault("evaluation_not_found", 404, "评测批次不存在")
        return value.strip()

    @staticmethod
    def _case_id(value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise GatewayFault("evaluation_case_not_found", 404, "评测 case 不存在")
        return value.strip()

    @staticmethod
    def _resource_id(value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise GatewayFault("evaluation_resource_not_found", 404, "评测资源不存在")
        return value.strip()

    @staticmethod
    def _evaluation_call(operation):
        try:
            return operation()
        except EvaluationGatewayError as exc:
            raise GatewayFault(exc.code, exc.status, exc.message) from exc


__all__ = ["EvaluationWorkbenchMixin"]
