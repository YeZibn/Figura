"""Tests for the CLI agent REPL and `--agent` dispatch (no real LLM)."""

import builtins

from chartagent import cli as cli_mod


class _FakeAgent:
    def __init__(self, *a, **k):
        self.seen = []
        self.model = k.get("model")

    def run(self, line):
        self.seen.append(line)
        return f"replied:{line}"


def _patch_constructors(monkeypatch, agent=None):
    """Patch the REPL's construction points so no real LLM/registry is used.

    ``load_environment`` is also disabled: it would read ``.env`` into
    ``os.environ`` and leak the API key into later tests.
    """
    monkeypatch.setattr(cli_mod, "load_environment", lambda *a, **k: None)
    monkeypatch.setattr(cli_mod, "LLMClient", lambda *a, **k: object())
    monkeypatch.setattr(cli_mod, "ToolRegistry", lambda: object())
    monkeypatch.setattr(cli_mod, "Agent", lambda *a, **k: agent or _FakeAgent())
    monkeypatch.setattr(cli_mod, "register_builtins", lambda reg: None)
    monkeypatch.setattr(cli_mod, "register_chart_tools", lambda reg: None)


def test_cli_default_uses_conversation(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli_mod, "run_repl",
                        lambda **k: captured.update(path="chat") or 0)
    monkeypatch.setattr(cli_mod, "run_agent_repl",
                        lambda **k: captured.update(path="agent") or 0)
    rc = cli_mod.cli([])
    assert rc == 0
    assert captured["path"] == "chat"


def test_cli_agent_flag_selects_agent(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli_mod, "run_repl",
                        lambda **k: captured.update(path="chat") or 0)
    monkeypatch.setattr(cli_mod, "run_agent_repl",
                        lambda **k: captured.update(path="agent") or 0)
    cli_mod.cli(["--agent"])
    assert captured["path"] == "agent"


def test_cli_agent_model_forwarded(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli_mod, "run_agent_repl", lambda **k: seen.update(k) or 0)
    cli_mod.cli(["--agent", "--model", "qwen-3"])
    assert seen["model"] == "qwen-3"


def test_run_agent_repl_empty_line_exits(monkeypatch):
    _patch_constructors(monkeypatch)
    monkeypatch.setattr(builtins, "input", lambda prompt="": "")
    assert cli_mod.run_agent_repl() == 0


def test_run_agent_repl_runs_line(monkeypatch, capsys):
    agent = _FakeAgent()
    _patch_constructors(monkeypatch, agent=agent)
    lines = iter(["hello", ""])  # one real line, then blank to exit
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(lines))
    assert cli_mod.run_agent_repl() == 0
    assert agent.seen == ["hello"]
    out = capsys.readouterr().out
    assert "replied:hello" in out


def test_plain_text_without_at_unchanged(monkeypatch):
    """No @ token -> the agent gets the original stripped string, not a list."""
    agent = _FakeAgent()
    _patch_constructors(monkeypatch, agent=agent)
    lines = iter(["just a question", ""])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(lines))
    cli_mod.run_agent_repl()
    assert agent.seen == ["just a question"]


def test_single_at_path_attaches_image_part(monkeypatch, tmp_path):
    agent = _FakeAgent()
    _patch_constructors(monkeypatch, agent=agent)
    img = tmp_path / "chart.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 12)
    lines = iter([f"read this chart @{img}", ""])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(lines))
    cli_mod.run_agent_repl()
    turn = agent.seen[0]
    assert isinstance(turn, list)
    assert turn[0] == {"type": "text", "text": "read this chart"}
    assert turn[1]["type"] == "image_url"
    assert turn[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_nonexistent_at_path_errors_without_calling_agent(monkeypatch, capsys):
    class _ExplodingAgent:
        def __init__(self, *a, **k):
            pass

        def run(self, _turn):
            raise AssertionError("agent must not be called on bad @path")

    monkeypatch.setattr(cli_mod, "load_environment", lambda *a, **k: None)
    monkeypatch.setattr(cli_mod, "LLMClient", lambda *a, **k: object())
    monkeypatch.setattr(cli_mod, "ToolRegistry", lambda: object())
    monkeypatch.setattr(cli_mod, "Agent", _ExplodingAgent)
    monkeypatch.setattr(cli_mod, "register_builtins", lambda reg: None)
    monkeypatch.setattr(cli_mod, "register_chart_tools", lambda reg: None)
    lines = iter(["look @/definitely/missing/xyz.png", ""])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(lines))
    assert cli_mod.run_agent_repl() == 0  # session survives, exits on blank
    out = capsys.readouterr().out
    assert "[error]" in out


def test_agent_repl_registers_builtin_and_chart_tools(monkeypatch):
    captured = {}

    class _CapturingAgent:
        def __init__(self, _client, registry, **_kwargs):
            captured["names"] = [tool.name for tool in registry.list()]

        def run(self, _turn):
            raise AssertionError("blank input must exit before running the agent")

    monkeypatch.setattr(cli_mod, "load_environment", lambda *a, **k: None)
    monkeypatch.setattr(cli_mod, "LLMClient", lambda *a, **k: object())
    monkeypatch.setattr(cli_mod, "Agent", _CapturingAgent)
    monkeypatch.setattr(builtins, "input", lambda prompt="": "")

    assert cli_mod.run_agent_repl() == 0
    assert set(captured["names"]) == {
        "read_file",
        "list_dir",
        "parse_json",
        "read_json_file",
        "extract_text",
        "measure_bars",
        "assemble_spec",
        "validate_spec",
    }
