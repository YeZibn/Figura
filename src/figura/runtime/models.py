"""Core values for Figura Sessions and durable Runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class RecordKind(str, Enum):
    INPUT = "input"
    MODEL_RESPONSE = "model_response"
    FINAL_ANSWER = "final_answer"


class ActionKind(str, Enum):
    MODEL = "model"
    PROVIDER_ATTEMPT = "provider_attempt"
    TOOL_EXECUTION = "tool_execution"
    TOOL_ATTEMPT = "tool_attempt"
    FINAL = "final"


class ProviderAttemptStatus(str, Enum):
    STARTED = "started"
    RESPONSE_COMMITTED = "response_committed"
    KNOWN_FAILURE = "known_failure"
    OUTCOME_UNKNOWN = "outcome_unknown"


class ToolFactKind(str, Enum):
    TOOL_CALL = "tool_call"
    TOOL_ATTEMPT_STARTED = "tool_attempt_started"
    TOOL_RESULT = "tool_result"


class EventKind(str, Enum):
    RUN_CREATED = "run_created"
    RUN_PROGRESS = "run_progress"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_INTERRUPTED = "run_interrupted"


class TerminalCode(str, Enum):
    EXECUTION_FAILED = "execution_failed"
    INVALID_RESPONSE = "invalid_response"
    STORAGE_ERROR = "storage_error"
    INTERRUPTED = "interrupted"
    PROVIDER_OUTCOME_UNKNOWN = "provider_outcome_unknown"
    TOOL_OUTCOME_UNKNOWN = "tool_outcome_unknown"
    TOOL_RECOVERY_UNAVAILABLE = "tool_recovery_unavailable"
    TOOL_RECOVERY_EXHAUSTED = "tool_recovery_exhausted"


TERMINAL_MESSAGES: Mapping[TerminalCode, str] = MappingProxyType(
    {
        TerminalCode.TOOL_OUTCOME_UNKNOWN: "工具执行结果状态未知，当前 Run 已停止。",
        TerminalCode.TOOL_RECOVERY_UNAVAILABLE: "原工具版本或恢复条件不可用，当前 Run 已停止。",
        TerminalCode.TOOL_RECOVERY_EXHAUSTED: "工具自动恢复次数已达上限，当前 Run 已停止。",
        TerminalCode.EXECUTION_FAILED: "Run 执行未能完成。",
        TerminalCode.INVALID_RESPONSE: "Run 收到无法接受的模型结果。",
        TerminalCode.STORAGE_ERROR: "Run 执行结果未能保存。",
        TerminalCode.INTERRUPTED: "Run 已中断。",
        TerminalCode.PROVIDER_OUTCOME_UNKNOWN: "模型服务商的结果状态未知，当前 Run 已停止。",
    }
)


PREPARATION_MESSAGES: Mapping[str, str] = MappingProxyType({
    "missing_deepseek_continuation": "DeepSeek 工具历史缺少必要的 reasoning continuation，无法继续请求。",
    "invalid_request": "模型请求未通过本地校验，无法继续执行。",
    "unsupported_capability": "当前服务商不支持该请求能力。",
    "invalid_configuration": "当前模型配置无效，无法准备请求。",
    "configuration_missing": "当前模型配置不完整，无法准备请求。",
})


@dataclass(frozen=True)
class Session:
    session_id: str
    name: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class SessionListEntry:
    session: Session
    run_count: int
    latest_activity: str


@dataclass(frozen=True)
class Run:
    run_id: str
    session_id: str
    ordinal: int
    input_record_id: str
    status: RunStatus
    provider: str
    model: str
    created_at: str
    started_at: str
    finished_at: str | None = None
    terminal_code: str | None = None
    terminal_message: str | None = None
    final_record_id: str | None = None

    def to_public_dict(self) -> dict[str, object]:
        """Return the bounded Run summary without input or execution payloads."""
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "ordinal": self.ordinal,
            "status": self.status.value,
            "provider": self.provider,
            "model": self.model,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "terminal_code": self.terminal_code,
            "terminal_message": self.terminal_message,
            "final_record_id": self.final_record_id,
        }


@dataclass(frozen=True)
class NextAction:
    action_kind: ActionKind
    response_record_id: str | None = None
    tool_call_sequence: int | None = None
    attempt_id: str | None = None


@dataclass(frozen=True)
class ExecutionCheckpoint:
    run_id: str
    revision: int
    last_committed_record_sequence: int
    last_committed_tool_sequence: int
    next_action: NextAction | None
    schema_version: int
    updated_at: str


@dataclass(frozen=True)
class RunCreateRequest:
    session_id: str
    text: str = field(repr=False)
    provider_id: str
    model_id: str
    idempotency_key: str = field(repr=False)
    attachment_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunStopRequest:
    run_id: str
    request_id: str
    requested_at: str
    reason: str
