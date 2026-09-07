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