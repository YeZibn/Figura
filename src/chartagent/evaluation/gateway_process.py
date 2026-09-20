"""Lifecycle management for an evaluation-local Gateway subprocess."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..storage import project_root


class ManagedGatewayError(RuntimeError):
    """Raised when the evaluation Gateway cannot be started or stopped safely."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message[:500]


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


class ManagedGateway:
    """Start the public Gateway API with a private evaluation data root."""

    def __init__(
        self,
        data_dir: str | Path,
        *,
        startup_timeout: float = 30.0,
        request_timeout: float = 0.5,
    ) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.startup_timeout = max(1.0, float(startup_timeout))
        self.request_timeout = min(5.0, max(0.1, float(request_timeout)))
        self.port: int | None = None
        self.process: subprocess.Popen[bytes] | None = None

    @property
    def base_url(self) -> str:
        if self.port is None:
            raise ManagedGatewayError("gateway_not_started", "评测 Gateway 尚未启动")
        return f"http://127.0.0.1:{self.port}/api/v1"

    def start(self) -> str:
        if self.process is not None:
            return self.base_url
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.port = _free_loopback_port()
        command = [
            sys.executable,
            "-m",
            "chartagent.gateway",
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
            "--data-dir",
            str(self.data_dir),
        ]
        try:
            self.process = subprocess.Popen(
                command,
                cwd=str(project_root()),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=(os.name == "posix"),
            )
        except OSError as exc:
            self.process = None
            raise ManagedGatewayError("gateway_start_failed", "无法启动评测 Gateway") from exc

        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                code = self.process.returncode
                self.close()
                raise ManagedGatewayError(
                    "gateway_start_failed",
                    f"评测 Gateway 启动失败（退出码 {code}）",
                )
            if self._health_available():
                return self.base_url
            time.sleep(0.1)
        self.close()
        raise ManagedGatewayError("gateway_start_timeout", "评测 Gateway 未在限定时间内就绪")

    def _health_available(self) -> bool:
        try:
            request = Request(f"{self.base_url}/health", headers={"Accept": "application/json"})
            with urlopen(request, timeout=self.request_timeout) as response:
                if int(getattr(response, "status", 200)) != 200:
                    return False
                raw = response.read(64 * 1024)
            payload: Any = json.loads(raw.decode("utf-8"))
            return isinstance(payload, dict) and payload.get("status") == "ok"
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
            return False

    def close(self) -> None:
        process = self.process
        self.process = None
        if process is None:
            return
        if process.poll() is not None:
            return
        try:
            if os.name == "posix" and process.pid:
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
        except (ProcessLookupError, OSError):
            return
        try:
            process.wait(timeout=5.0)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            if os.name == "posix" and process.pid:
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait(timeout=2.0)
        except (ProcessLookupError, OSError, subprocess.TimeoutExpired):
            return

    def __enter__(self) -> "ManagedGateway":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()


__all__ = ["ManagedGateway", "ManagedGatewayError"]
