"""Phase 3: the 6 tools, the registry/isolation, and the tool-calling loop.

Handlers are exercised directly (unit) and end-to-end through the turn loop with
a mocked LLM that drives one or more tool rounds (Appendix A §A.3.2, Appendix B).
No network: web_search is covered by monkeypatching `requests.post`.
"""

from __future__ import annotations

import json

import pytest

from agent_backend import db, turn_loop
from agent_backend.tools import registry
from agent_backend.tools.base import ExecutionContext
from agent_backend.tools import calculator, datetime_tool, files, web_search


def _ctx(workspace=None, agent_id=1) -> ExecutionContext:
    return ExecutionContext(workspace_folder=workspace, agent_id=agent_id)


# --- registry / isolation (B.2, B.4, G4) ---------------------------------

def test_registry_has_exactly_the_six_canonical_tools():
    from agent_backend.tool_names import TOOL_NAMES

    assert set(registry.all_tools()) == set(TOOL_NAMES)


def test_serialize_tools_only_emits_assigned_registered_tools():
    out = registry.serialize_tools(["calculator", "bogus_tool", "file_read"])
    names = [t["function"]["name"] for t in out]
    # Isolation: unknown assigned name is skipped; assigned ones pass through.
    assert names == ["calculator", "file_read"]
    # Shape is OpenRouter's function-tool envelope with the derived schema.
    assert out[0]["type"] == "function"
    assert "expression" in out[0]["function"]["parameters"]["properties"]


def test_serialize_tools_empty_is_empty_list():
    assert registry.serialize_tools([]) == []


# --- calculator (B.3.1) --------------------------------------------------

@pytest.mark.parametrize("expr,expected", [
    ("2 * (3 + 4)", "14"),
    ("-5 + 2", "-3"),
    ("10 / 4", "2.5"),
    ("2 ** 8", "256"),
])
def test_calculator_evaluates(expr, expected):
    assert calculator.calculator(calculator.CalculatorArgs(expression=expr), _ctx()) == expected


def test_calculator_division_by_zero_is_error_string():
    assert calculator.calculator(calculator.CalculatorArgs(expression="1/0"), _ctx()) == \
        "Error: division by zero"


def test_calculator_rejects_names_and_calls():
    assert calculator.calculator(calculator.CalculatorArgs(expression="__import__('os')"), _ctx()) \
        .startswith("Error:")


def test_calculator_pow_guard_blocks_dos_expression():
    # A tiny expression that would otherwise build a giant int — must be refused
    # as a recoverable error, not hang or crash.
    assert calculator.calculator(
        calculator.CalculatorArgs(expression="2 ** (10 ** 9)"), _ctx()
    ).startswith("Error:")


# --- current_datetime (B.3.2 + settled ValueError widening) ---------------

def test_datetime_named_timezone_is_iso():
    out = datetime_tool.current_datetime(datetime_tool.DateTimeArgs(timezone="America/New_York"), _ctx())
    # ISO 8601 with a UTC offset (proves tzdata resolved the zone).
    assert "T" in out and ("-05:00" in out or "-04:00" in out)


def test_datetime_default_local_is_iso():
    out = datetime_tool.current_datetime(datetime_tool.DateTimeArgs(), _ctx())
    assert "T" in out


def test_datetime_unknown_zone_is_error_string():
    out = datetime_tool.current_datetime(datetime_tool.DateTimeArgs(timezone="Mars/Olympus"), _ctx())
    assert out.startswith("Error: unknown timezone")


def test_datetime_malformed_zone_valueerror_is_recovered():
    # ZoneInfo raises ValueError (not ZoneInfoNotFoundError) for path-like keys;
    # the widened except (settled decision (b)) makes this a clean error string.
    out = datetime_tool.current_datetime(datetime_tool.DateTimeArgs(timezone="../etc/passwd"), _ctx())
    assert out.startswith("Error: unknown timezone")


# --- file tools + sandbox (B.3.4, A.3.3 §6) -------------------------------

def test_file_edit_then_read_roundtrip(tmp_path):
    ctx = _ctx(workspace=str(tmp_path))
    wrote = files.file_edit(files.FileEditArgs(path="notes/a.txt", content="hello"), ctx)
    assert wrote.startswith("Wrote 5 chars")
    assert (tmp_path / "notes" / "a.txt").read_text(encoding="utf-8") == "hello"
    assert files.file_read(files.FileReadArgs(path="notes/a.txt"), ctx) == "hello"


def test_file_search_lists_matches(tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "b.md").write_text("y", encoding="utf-8")
    ctx = _ctx(workspace=str(tmp_path))
    assert files.file_search(files.FileSearchArgs(pattern="*.txt"), ctx) == "a.txt"


def test_file_read_missing_is_error_string(tmp_path):
    ctx = _ctx(workspace=str(tmp_path))
    assert files.file_read(files.FileReadArgs(path="nope.txt"), ctx) == "Error: no such file: nope.txt"


def test_file_tools_require_a_workspace():
    ctx = _ctx(workspace=None)  # A.3.3 §6: null workspace -> error string, no default
    assert files.file_read(files.FileReadArgs(path="x"), ctx).startswith("Error: no workspace")
    assert files.file_edit(files.FileEditArgs(path="x", content="y"), ctx).startswith("Error: no workspace")


def test_file_path_escape_is_blocked(tmp_path):
    ctx = _ctx(workspace=str(tmp_path))
    out = files.file_read(files.FileReadArgs(path="../secret.txt"), ctx)
    assert out.startswith("Error: path escapes")


def test_file_edit_escape_does_not_write_outside(tmp_path):
    ctx = _ctx(workspace=str(tmp_path / "ws"))
    (tmp_path / "ws").mkdir()
    files.file_edit(files.FileEditArgs(path="../escaped.txt", content="pwn"), ctx)
    assert not (tmp_path / "escaped.txt").exists()


# --- web_search (B.3.3) --------------------------------------------------

def test_web_search_no_key_is_recoverable_string(monkeypatch):
    monkeypatch.setattr(web_search, "get_key", lambda p: None)
    out = web_search.web_search(web_search.WebSearchArgs(query="anything"), _ctx())
    assert out.startswith("Error: web search is unavailable")


def test_web_search_formats_results(monkeypatch):
    monkeypatch.setattr(web_search, "get_key", lambda p: "tvly-key")

    class FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return {"results": [
                {"title": "T1", "url": "http://a", "content": "C1"},
                {"title": "T2", "url": "http://b", "content": "C2"},
            ]}

    monkeypatch.setattr(web_search.requests, "post", lambda *a, **k: FakeResp())
    out = web_search.web_search(web_search.WebSearchArgs(query="q"), _ctx())
    assert "T1" in out and "http://a" in out and "C2" in out


def test_web_search_timeout_is_recoverable_string(monkeypatch):
    import requests
    monkeypatch.setattr(web_search, "get_key", lambda p: "tvly-key")

    def boom(*a, **k):
        raise requests.exceptions.Timeout()

    monkeypatch.setattr(web_search.requests, "post", boom)
    assert web_search.web_search(web_search.WebSearchArgs(query="q"), _ctx()) == \
        "Error: web search timed out"


# --- turn loop: multi-round tool calling (A.3.2, B.5) ---------------------

def _tool_call(call_id, name, arguments):
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)}}


def _make_agent_with_tools(client, tools, workspace=None):
    body = {
        "name": "Toolbot", "description": "Use tools.",
        "model_id": "poolside/laguna-m.1:free",
        "tools": tools, "workspace_folder": workspace,
    }
    return client.post("/agents", json=body).get_json()["agent"]


def test_turn_loop_executes_a_tool_then_answers(client, monkeypatch):
    agent = _make_agent_with_tools(client, ["calculator"])
    client.put("/keys", json={"openrouter": "sk-test"})

    # Scripted 2-round conversation: call calculator, then answer with the result.
    scripted = iter([
        {"role": "assistant", "content": None,
         "tool_calls": [_tool_call("c1", "calculator", {"expression": "6*7"})]},
        {"role": "assistant", "content": "It's 42."},
    ])
    monkeypatch.setattr(turn_loop.llm, "call_openai_compatible", lambda **k: next(scripted))

    msgs = client.post(f"/agents/{agent['id']}/messages", json={"content": "6*7?"}).get_json()["messages"]

    # A.2.4 delta: user, assistant-with-tool-call, tool result, final assistant.
    assert [m["role"] for m in msgs] == ["user", "assistant", "tool", "assistant"]
    tool_row = msgs[2]
    assert tool_row["content"] == "42"
    assert tool_row["tool_call_id"] == "c1"
    assert msgs[1]["tool_calls"][0]["function"]["name"] == "calculator"
    assert msgs[3]["content"] == "It's 42."


def test_turn_loop_passes_serialized_tools_to_the_model(client, monkeypatch):
    agent = _make_agent_with_tools(client, ["calculator", "current_datetime"])
    client.put("/keys", json={"openrouter": "sk-test"})

    seen = {}

    def capture(**kwargs):
        seen["tools"] = kwargs.get("tools")
        return {"role": "assistant", "content": "done"}

    monkeypatch.setattr(turn_loop.llm, "call_openai_compatible", capture)
    client.post(f"/agents/{agent['id']}/messages", json={"content": "hi"})

    names = {t["function"]["name"] for t in seen["tools"]}
    assert names == {"calculator", "current_datetime"}


def test_turn_loop_isolation_rejects_unassigned_tool(client, monkeypatch):
    # Agent has only calculator; model hallucinates a file_read call. The
    # defense-in-depth guard (A.3.3 §3) returns an error string, turn survives.
    agent = _make_agent_with_tools(client, ["calculator"])
    client.put("/keys", json={"openrouter": "sk-test"})

    scripted = iter([
        {"role": "assistant", "content": None,
         "tool_calls": [_tool_call("c1", "file_read", {"path": "secret"})]},
        {"role": "assistant", "content": "ok"},
    ])
    monkeypatch.setattr(turn_loop.llm, "call_openai_compatible", lambda **k: next(scripted))

    msgs = client.post(f"/agents/{agent['id']}/messages", json={"content": "read it"}).get_json()["messages"]
    assert msgs[2]["role"] == "tool"
    assert msgs[2]["content"] == "Error: tool not assigned to this agent"


def test_turn_loop_invalid_tool_arguments_is_error_string(client, monkeypatch):
    agent = _make_agent_with_tools(client, ["calculator"])
    client.put("/keys", json={"openrouter": "sk-test"})

    # arguments is malformed JSON -> ValidationError -> recoverable error string.
    bad_call = {"id": "c1", "type": "function",
                "function": {"name": "calculator", "arguments": "{not json"}}
    scripted = iter([
        {"role": "assistant", "content": None, "tool_calls": [bad_call]},
        {"role": "assistant", "content": "handled"},
    ])
    monkeypatch.setattr(turn_loop.llm, "call_openai_compatible", lambda **k: next(scripted))

    msgs = client.post(f"/agents/{agent['id']}/messages", json={"content": "go"}).get_json()["messages"]
    assert msgs[2]["content"] == "Error: invalid tool arguments"


def test_turn_loop_handler_crash_is_caught_and_turn_survives(client, monkeypatch):
    agent = _make_agent_with_tools(client, ["calculator"])
    client.put("/keys", json={"openrouter": "sk-test"})

    # Force the handler to raise a genuine bug; B.5 catches it, logs a crash,
    # and substitutes a safe string — the turn is NOT aborted. (Tool is frozen,
    # so swap what registry.get returns rather than mutating the handler field.)
    from agent_backend.tools.base import Tool

    def crash(args, ctx):
        raise RuntimeError("boom")

    crashing = Tool(name="calculator", description="d",
                    args_model=calculator.CalculatorArgs, handler=crash)
    monkeypatch.setattr(turn_loop.registry, "get", lambda name: crashing)
    scripted = iter([
        {"role": "assistant", "content": None,
         "tool_calls": [_tool_call("c1", "calculator", {"expression": "1+1"})]},
        {"role": "assistant", "content": "recovered"},
    ])
    monkeypatch.setattr(turn_loop.llm, "call_openai_compatible", lambda **k: next(scripted))

    msgs = client.post(f"/agents/{agent['id']}/messages", json={"content": "go"}).get_json()["messages"]
    assert msgs[2]["content"] == "Error: the tool failed unexpectedly"
    assert msgs[3]["content"] == "recovered"


def test_turn_loop_max_iterations_guard_trips_on_runaway_tools(client, monkeypatch):
    agent = _make_agent_with_tools(client, ["calculator"])
    client.put("/keys", json={"openrouter": "sk-test"})

    # Model calls a tool forever; the guard must abort with a model_error envelope
    # after MAX_ITERATIONS, with partial rows already persisted (persist-as-you-go).
    def always_calls(**kwargs):
        return {"role": "assistant", "content": None,
                "tool_calls": [_tool_call("c", "calculator", {"expression": "1+1"})]}

    monkeypatch.setattr(turn_loop.llm, "call_openai_compatible", always_calls)
    resp = client.post(f"/agents/{agent['id']}/messages", json={"content": "loop"})
    assert resp.status_code == 502
    assert resp.get_json()["error"]["kind"] == "model_error"
    # Partial history survived the abort.
    history = client.get(f"/agents/{agent['id']}/messages").get_json()["messages"]
    assert len(history) > 1
