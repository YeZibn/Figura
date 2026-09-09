"""Tests for the CLI agent REPL and `--agent` dispatch (no real LLM)."""

import builtins
from io import StringIO

from chartagent import cli as cli_mod
from chartagent.trace import TraceEvent


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


def test_cli_trace_options_forwarded_to_agent_repl(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli_mod, "run_agent_repl", lambda **k: seen.update(k) or 0)

    assert cli_mod.cli(
        ["--agent", "--trace", "--trace-reasoning", "--trace-format", "jsonl"]
    ) == 0
    assert seen == {
        "model": None,
        "trace": True,
        "trace_reasoning": True,
        "trace_format": "jsonl",
    }


def test_cli_rejects_trace_without_agent(capsys):
    assert cli_mod.cli(["--trace"]) == 2
    assert "require --agent" in capsys.readouterr().err


def test_cli_rejects_reasoning_without_trace(capsys):
    assert cli_mod.cli(["--agent", "--trace-reasoning"]) == 2
    assert "requires --trace" in capsys.readouterr().err


def test_cli_rejects_non_text_format_without_trace(capsys):
    assert cli_mod.cli(["--agent", "--trace-format", "jsonl"]) == 2
    assert "--trace-format requires --trace" in capsys.readouterr().err


def test_agent_repl_trace_sink_is_jsonl_and_final_answer_stays_stdout(monkeypatch, capsys):
    captured = {}

    class _CapturingAgent:
        def __init__(self, _client, _registry, **kwargs):
            captured.update(kwargs)

        def run(self, _turn):
            return "answer"

    monkeypatch.setattr(cli_mod, "load_environment", lambda: None)
    monkeypatch.setattr(cli_mod, "LLMClient", lambda: object())
    monkeypatch.setattr(cli_mod, "ToolRegistry", lambda: object())
    monkeypatch.setattr(cli_mod, "register_builtins", lambda _registry: None)
    monkeypatch.setattr(cli_mod, "register_chart_tools", lambda _registry: None)
    monkeypatch.setattr(cli_mod, "Agent", _CapturingAgent)
    trace_stream = StringIO()
    lines = iter(["hello", ""])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(lines))

    assert cli_mod.run_agent_repl(
        trace=True,
        trace_reasoning=True,
        trace_format="jsonl",
        trace_stream=trace_stream,
    ) == 0
    captured["trace"](TraceEvent("final_answer", run_id="r", turn=1, payload={"answer": "answer"}))
    assert '"kind":"final_answer"' in trace_stream.getvalue()
    assert "answer" in capsys.readouterr().out
    assert captured["trace_reasoning"] is True


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


def test_plain_text_preserves_internal_whitespace(monkeypatch):
    agent = _FakeAgent()
    _patch_constructors(monkeypatch, agent=agent)
    lines = iter(["  keep   my spacing  ", ""])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(lines))

    cli_mod.run_agent_repl()

    assert agent.seen == ["keep   my spacing"]


def test_extract_image_refs_supports_quoted_and_mixed_paths():
    text, paths = cli_mod.extract_image_refs(
        'compare @"/tmp/chart one.png" with @/tmp/two.png'
    )

    assert text == "compare with"
    assert paths == ["/tmp/chart one.png", "/tmp/two.png"]


def test_extract_image_refs_leaves_unterminated_quote_as_text():
    line = 'inspect @"/tmp/chart one.png'

    assert cli_mod.extract_image_refs(line) == (line, [])


def test_single_at_path_registers_opaque_attachment(monkeypatch, tmp_path):
    agent = _FakeAgent()
    _patch_constructors(monkeypatch, agent=agent)
    img = tmp_path / "chart.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 12)
    lines = iter([f"read this chart @{img}", ""])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(lines))
    cli_mod.run_agent_repl()
    turn = agent.seen[0]
    assert isinstance(turn, str)
    assert "Registered image attachments" in turn
    assert "attachment_id=att_" in turn
    assert str(img) not in turn
    assert "data:image" not in turn


def test_mixed_quoted_and_unquoted_paths_register_in_order(monkeypatch, tmp_path):
    agent = _FakeAgent()
    _patch_constructors(monkeypatch, agent=agent)
    first = tmp_path / "chart one.png"
    second = tmp_path / "two.png"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    lines = iter([f'compare @"{first}"   with @{second}', ""])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(lines))

    cli_mod.run_agent_repl()

    turn = agent.seen[0]
    assert isinstance(turn, str)
    assert turn.startswith("compare with\n\nRegistered image attachments")
    assert turn.index("filename=chart one.png") < turn.index("filename=two.png")
    assert str(first) not in turn
    assert str(second) not in turn
    assert "data:image" not in turn


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
        "load_image",
    }


def test_agent_repl_uses_advisory_chart_default(monkeypatch):
    captured = {}

    class _CapturingAgent:
        def __init__(self, _client, _registry, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(cli_mod, "load_environment", lambda: None)
    monkeypatch.setattr(cli_mod, "LLMClient", lambda: object())
    monkeypatch.setattr(cli_mod, "ToolRegistry", lambda: object())
    monkeypatch.setattr(cli_mod, "register_builtins", lambda _registry: None)
    monkeypatch.setattr(cli_mod, "register_chart_tools", lambda _registry: None)
    monkeypatch.setattr(cli_mod, "Agent", _CapturingAgent)
    monkeypatch.setattr(builtins, "input", lambda prompt="": "")

    assert cli_mod.run_agent_repl() == 0
    assert captured["system"] == cli_mod.AGENT_SYSTEM_PROMPT
    for capability in (
        "extract_text",
        "measure_bars",
        "assemble_spec",
        "validate_spec",
    ):
        assert capability in captured["system"]
    assert "Decide freely" in captured["system"]
    assert "ChartSpec is optional" in captured["system"]


def test_agent_repl_accepts_explicit_system_override(monkeypatch):
    captured = {}

    class _CapturingAgent:
        def __init__(self, _client, _registry, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(cli_mod, "load_environment", lambda: None)
    monkeypatch.setattr(cli_mod, "LLMClient", lambda: object())
    monkeypatch.setattr(cli_mod, "ToolRegistry", lambda: object())
    monkeypatch.setattr(cli_mod, "register_builtins", lambda _registry: None)
    monkeypatch.setattr(cli_mod, "register_chart_tools", lambda _registry: None)
    monkeypatch.setattr(cli_mod, "Agent", _CapturingAgent)
    monkeypatch.setattr(builtins, "input", lambda prompt="": "")

    assert cli_mod.run_agent_repl(system="custom agent") == 0
    assert captured["system"] == "custom agent"


def test_conversation_repl_keeps_general_default(monkeypatch):
    captured = {}

    class _CapturingConversation:
        def __init__(self, _client, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(cli_mod, "load_environment", lambda: None)
    monkeypatch.setattr(cli_mod, "LLMClient", lambda: object())
    monkeypatch.setattr(cli_mod, "Conversation", _CapturingConversation)
    monkeypatch.setattr(builtins, "input", lambda prompt="": "")

    assert cli_mod.run_repl() == 0
    assert captured["system"] == "You are a helpful assistant."
