"""Run the Figura local web Gateway on loopback."""

from __future__ import annotations

import os
import signal
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

from .application import create_application, recover_running_runs
from .server import FiguraHTTPServer


def main() -> None:
    project_root = Path(__file__).resolve().parents[3]
    load_dotenv(project_root / ".env", override=False)
    port = _read_port(os.environ.get("FIGURA_GATEWAY_PORT", "8766"))
    origins = _read_origins(
        os.environ.get(
            "FIGURA_WEB_ORIGINS",
            "http://127.0.0.1:1421,http://localhost:1421,http://[::1]:1421",
        )
    )
    data_dir = os.environ.get("FIGURA_DATA_DIR")
    application = create_application(
        project_root,
        data_dir=data_dir,
        allowed_origins=origins,
    )
    try:
        server = FiguraHTTPServer(("127.0.0.1", port), application)
        recover_running_runs(application)
    except Exception:
        application.close()
        raise

    def stop_on_signal(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    previous_sigterm = signal.signal(signal.SIGTERM, stop_on_signal)
    print(f"Figura Gateway ready at http://127.0.0.1:{port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        server.server_close()
        application.close()


def _read_port(value: str) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise SystemExit("FIGURA_GATEWAY_PORT must be an integer between 1 and 65535") from None
    if not 1 <= port <= 65535:
        raise SystemExit("FIGURA_GATEWAY_PORT must be an integer between 1 and 65535")
    return port


def _read_origins(value: str) -> tuple[str, ...]:
    origins = tuple(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))
    if not origins:
        raise SystemExit("FIGURA_WEB_ORIGINS must contain at least one local Origin")
    for origin in origins:
        try:
            parsed = urlsplit(origin)
            local_host = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            valid = (
                parsed.scheme == "http"
                and local_host
                and parsed.port is not None
                and parsed.username is None
                and parsed.password is None
                and parsed.path in {"", "/"}
                and not parsed.query
                and not parsed.fragment
            )
        except ValueError:
            valid = False
        if not valid:
            raise SystemExit("FIGURA_WEB_ORIGINS accepts only explicit loopback HTTP Origins")
    return origins


if __name__ == "__main__":
    main()
