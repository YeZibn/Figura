"""Safe, bounded errors for Figura Run persistence and coordination."""

from __future__ import annotations

from enum import Enum


class RunErrorCode(str, Enum):
    INVALID_REQUEST = "invalid_request"
    SESSION_NOT_FOUND = "session_not_found"
    RUN_NOT_FOUND = "run_not_found"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    STALE_CHECKPOINT = "stale_checkpoint"
    INVALID_TRANSITION = "invalid_transition"
    UNSUPPORTED_PAYLOAD = "unsupported_payload"
    UNSUPPORTED_VERSION = "unsupported_version"
    INTEGRITY_ERROR = "integrity_error"
    STORAGE_ERROR = "storage_error"


_SAFE_MESSAGES = {
    RunErrorCode.INVALID_REQUEST: "Run 请求无效。",
    RunErrorCode.SESSION_NOT_FOUND: "未找到可用的 Session。",
    RunErrorCode.RUN_NOT_FOUND: "未找到可用的 Run。",
    RunErrorCode.PROVIDER_UNAVAILABLE: "所选模型服务当前不可用。",
    RunErrorCode.IDEMPOTENCY_CONFLICT: "幂等键已用于不同的 Run 请求。",
    RunErrorCode.STALE_CHECKPOINT: "Run 执行进度已变化，请重新读取。",
    RunErrorCode.INVALID_TRANSITION: "Run 当前状态不允许此操作。",
    RunErrorCode.UNSUPPORTED_PAYLOAD: "Run 执行记录不受支持或超出范围。",
    RunErrorCode.UNSUPPORTED_VERSION: "Run 数据版本不受支持。",
    RunErrorCode.INTEGRITY_ERROR: "Run 持久数据未通过完整性检查。",
    RunErrorCode.STORAGE_ERROR: "Run 数据暂时无法读取或保存。",
}


class RunError(Exception):
    """An application error whose message never includes raw storage data."""

    def __init__(self, code: RunErrorCode) -> None:
        self.code = code
        self.safe_message = _SAFE_MESSAGES[code]
        super().__init__(self.safe_message)

