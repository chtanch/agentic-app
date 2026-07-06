"""The agent turn / tool-calling loop (Appendix A §A.3.2).

This is what `POST /agents/{id}/messages` executes. It is implemented close to
the §A.3.2 pseudocode: persist-as-you-go, rebuild the provider messages array by
replaying `message_json` VERBATIM (reasoning included, in original order), and a
`while` loop with a max-iterations guard.

**Phase 3 scope:** the multi-round tool-calling loop is now live. Each round's
assigned tools are serialized (isolation, G4); tool calls are validated against
their pydantic model, dispatched through the registry, and their results
persisted as `tool` rows + replayed verbatim (Appendix B §B.5). Tool failures
are data (error strings fed back to the model), never turn-aborting envelopes.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError

from . import db, keys, llm
from .errors import ApiError
from .tools import registry
from .tools.base import ExecutionContext

log = logging.getLogger(__name__)

# Runaway-loop guard (settled decision: ~5). Exceeding it persists whatever
# partial rows were produced, then aborts the turn with a `model_error` envelope.
MAX_ITERATIONS = 5


def load_conversation(agent_id: int) -> list[dict[str, Any]]:
    """Rebuild the provider-shaped messages array from the DB (A.3.2).

    `user` rows emit `{role, content}`; assistant/tool rows replay their full
    `message_json` VERBATIM (never cherry-picked or reordered) so reasoning
    blocks survive the round-trip — reasoning models require this to continue.
    """
    messages: list[dict[str, Any]] = []
    for row in db.get_message_rows(agent_id):
        if row["role"] == "user":
            messages.append({"role": "user", "content": row["content"]})
        else:
            messages.append(json.loads(row["message_json"]))
    return messages


def handle_turn(agent: dict[str, Any], user_text: str) -> list[dict[str, Any]]:
    """Run a full turn for `agent` given new user text; return the NEW rows.

    `agent` is the internal `db.load_agent` view (carries the parsed
    `model_config`). Turn-aborting failures (`bad_api_key`/`model_error`/
    `offline`) raise `ApiError` -> A.2.7 envelope; a tool failing would NOT
    abort a turn (Phase 3).
    """
    agent_id = agent["id"]
    model_config = agent["model_config"]

    # Precondition: resolve the OpenRouter key early (A.3.1).
    api_key = keys.get_key(model_config["api_key_provider"])
    if not api_key:
        raise ApiError(
            "bad_api_key",
            "No OpenRouter API key is configured. Add one in Settings or config.toml.",
        )

    # Persist the user message, then rebuild the replay array (includes it).
    # The persisted user row is the first of the "new rows" this turn returns
    # (A.2.4: user msg, any tool msgs, final assistant msg) — the frontend gets
    # its canonical id/created_at rather than faking the bubble.
    user_row = db.add_message(agent_id, role="user", content=user_text)
    messages = load_conversation(agent_id)

    # ISOLATION (A.3.1 / G4): only an agent's assigned tools are serialized.
    # `serialize_tools([])` -> [], which llm.call_openai_compatible treats as
    # "no tools" (falsy), so a tool-less agent still resolves in one round.
    tool_defs = registry.serialize_tools(agent["tools"])
    # Per-agent sandbox root + correlation id, threaded into every handler (B.5).
    ctx = ExecutionContext(workspace_folder=agent["workspace_folder"], agent_id=agent_id)

    new_rows: list[dict[str, Any]] = [user_row]
    iterations = 0

    while True:
        iterations += 1
        if iterations > MAX_ITERATIONS:
            # Partial rows are already persisted (persist-as-you-go); abort here.
            log.warning("agent %s exceeded max iterations (%d)", agent_id, MAX_ITERATIONS)
            raise ApiError(
                "model_error",
                "The agent exceeded the maximum number of tool-call rounds.",
            )

        assistant_msg = llm.call_openai_compatible(
            base_url=model_config["base_url"],
            model=model_config["model_id"],
            api_key=api_key,
            system=agent["description"],   # system prompt (A.3.2)
            messages=messages,
            tools=tool_defs,
        )

        # Persist the WHOLE raw message verbatim; denormalize content for the UI.
        row = db.add_message(
            agent_id,
            role="assistant",
            content=assistant_msg.get("content"),
            message_json=assistant_msg,
        )
        new_rows.append(row)

        tool_calls = assistant_msg.get("tool_calls")
        if not tool_calls:
            # No tool calls -> final assistant answer. Return the turn's new rows.
            return new_rows

        # Append the raw assistant message to the replay array so the next round
        # sees its reasoning + tool_calls unmodified, then execute the tools.
        messages.append(assistant_msg)

        # --- Tool execution (Appendix B §B.5) -------------------------------
        # For each call: validate arguments, dispatch the handler, persist a
        # `tool` row, append the result to the replay array. Every path yields a
        # str fed back to the model — a tool failure is NEVER a turn-aborting
        # envelope (A.3.3 §2). After the calls, `continue` re-enters the loop so
        # the model sees the results and may call again (multi-round default).
        for call in tool_calls:
            fn = call.get("function") or {}
            name = fn.get("name")
            result = _run_tool_call(agent, ctx, name, fn.get("arguments"))

            # A.3.2: the tool result message pairs back to the call via id.
            tool_msg = {"role": "tool", "tool_call_id": call.get("id"), "content": result}
            row = db.add_message(agent_id, role="tool", content=result, message_json=tool_msg)
            new_rows.append(row)
            messages.append(tool_msg)

        continue  # model sees the tool results, may call again or answer


def _run_tool_call(
    agent: dict[str, Any],
    ctx: ExecutionContext,
    name: str | None,
    arguments: Any,
) -> str:
    """Validate + dispatch one tool call, returning the result string (B.5).

    Never raises: a recoverable handler failure comes back as an error string;
    an unexpected handler raise is caught, logged as a crash (full traceback +
    correlation context), and replaced with a safe generic string so the turn
    survives. The raw exception text never reaches the model, only the log.
    """
    # ISOLATION defense-in-depth (A.3.3 §3): even though only assigned tools are
    # serialized, guard against the model hallucinating an unassigned tool name.
    if name not in agent["tools"]:
        return "Error: tool not assigned to this agent"
    tool = registry.get(name)
    if tool is None:                                 # assigned but unregistered
        return "Error: tool not assigned to this agent"
    try:
        # OpenRouter/OpenAI deliver function.arguments as a JSON-encoded STRING
        # (or "" / null for zero-arg tools) — parse+validate in one step against
        # the same model that produced input_schema, so schema == validation.
        args = tool.args_model.model_validate_json(arguments or "{}")
        return tool.handler(args, ctx)               # recoverable failures -> strings
    except ValidationError:
        return "Error: invalid tool arguments"
    except Exception:                                # unrecoverable: a genuine bug
        log.exception("tool crashed", extra={"agent_id": agent["id"], "tool": name})
        return "Error: the tool failed unexpectedly"
