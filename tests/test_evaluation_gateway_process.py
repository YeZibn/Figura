from __future__ import annotations

import json
from pathlib import Path
from urllib.request import Request, urlopen

from chartagent.evaluation.gateway_process import ManagedGateway


def test_managed_gateway_uses_private_data_root_and_shuts_down(tmp_path):
    data_dir = tmp_path / "evaluation"
    gateway = ManagedGateway(data_dir, startup_timeout=10)

    base_url = gateway.start()
    try:
        request = Request(f"{base_url}/health", headers={"Accept": "application/json"})
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["status"] == "ok"
        assert gateway.process is not None
        assert gateway.process.poll() is None
        assert gateway.data_dir == data_dir.resolve()
        assert (data_dir / "sessions.db").is_file()
    finally:
        gateway.close()

    assert gateway.process is None
