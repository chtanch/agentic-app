"""The agent turn / tool-calling loop (Appendix A §A.3.2).

This is what `POST /agents/{id}/messages` executes. It is implemented close to
the §A.3.2 pseudocode: persist-as-you-go, rebuild the provider messages array by
replaying `message_json` VERBATIM (reasoning included, in original order), and a
`while` loop with a max-iterations guard.

**Phase 2 scope:** single agent, non-streaming chat, *no tools*. The tool
registry + the Appendix B §B.5 call site land in Phase 3; this phase serializes
no tools, so the loop resolves in a single round to a final assistant message.
The multi-round structure is already here so Phase 3 is a pure addition.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from . import db, keys, llm
from .errors import ApiError

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
    # Phase 2 serializes none — tool handlers + registry arrive in Phase 3.
    tool_defs = None

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

        # --- Phase 3 (Appendix B §B.5): for each call, validate arguments,
        #     dispatch registry[name].handler, persist a `tool` row, append the
        #     result to `messages`, then `continue`. No tools are serialized in
        #     Phase 2, so a well-behaved model never reaches here.
        log.warning(
            "agent %s requested tool_calls but tools are not enabled yet (Phase 3)",
            agent_id,
        )
        raise ApiError(
            "model_error",
            "This agent requested a tool, but tools aren't enabled yet.",
        )
