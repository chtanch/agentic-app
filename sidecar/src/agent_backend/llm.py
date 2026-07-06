"""OpenAI-compatible chat-completions client — one non-streaming call (A §A.3.2).

`call_openai_compatible` performs a single request→response round-trip (PRD
Decision: non-streaming) against any provider exposing the OpenAI
`/chat/completions` shape (OpenRouter here, but the code assumes nothing
OpenRouter-specific beyond the base_url the caller passes). It returns the
provider's raw `message` object **unmodified**, so the turn loop can store it
verbatim (`message_json`, §5.5) and replay it.

Failures are mapped to the three turn-aborting envelope kinds (A.2.7):
  - can't reach the provider          -> `offline`
  - 401/403 (key rejected/missing)    -> `bad_api_key`
  - any other non-2xx / bad payload   -> `model_error`
The API key is never logged.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import requests

from .errors import ApiError

log = logging.getLogger(__name__)

# OpenRouter mirrors the OpenAI chat-completions shape.
_TIMEOUT_SECONDS = 120


def call_openai_compatible(
    *,
    base_url: str,
    model: str,
    api_key: str,
    system: str,
    messages: list[dict[str, Any]],
    tools: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Run one completion and return `choices[0].message` verbatim (a dict).

    `system` (the agent's description, A.3.2) is injected as a leading system
    message only when non-empty; it is never stored as a DB row.
    """
    url = base_url.rstrip("/") + "/chat/completions"

    payload_messages: list[dict[str, Any]] = []
    if system:
        payload_messages.append({"role": "system", "content": system})
    payload_messages.extend(messages)

    payload: dict[str, Any] = {"model": model, "messages": payload_messages}
    if tools:
        payload["tools"] = tools

    headers = {
        "Authorization": f"Bearer {api_key}",  # value never logged
        "Content-Type": "application/json",
    }

    log.debug(
        "llm -> model=%s messages=%d tools=%d",
        model, len(payload_messages), len(tools or []),
    )

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=_TIMEOUT_SECONDS)
    except requests.exceptions.RequestException as e:
        # DNS failure, connection refused, timeout -> we're effectively offline.
        log.warning("llm unreachable: %s", e)
        raise ApiError(
            "offline",
            "Couldn't reach the model provider. Check your internet connection.",
        )

    if resp.status_code in (401, 403):
        log.warning("llm rejected the API key (HTTP %s)", resp.status_code)
        raise ApiError(
            "bad_api_key",
            "The OpenRouter API key was rejected. Check it in Settings.",
        )

    if resp.status_code >= 400:
        # Body may carry a provider error message; safe to log (no secrets).
        log.warning("llm error HTTP %s: %s", resp.status_code, resp.text[:500])
        raise ApiError(
            "model_error",
            "The model provider returned an error.",
            detail=f"HTTP {resp.status_code}",
        )

    try:
        data = resp.json()
    except ValueError:
        log.warning("llm returned non-JSON: %s", resp.text[:500])
        raise ApiError("model_error", "The model provider returned an invalid response.")

    choices = data.get("choices")
    if not choices:
        # OpenRouter can return 200 with an `error` object and no choices.
        err = data.get("error") or {}
        log.warning("llm returned no completion: %s", str(data)[:500])
        raise ApiError(
            "model_error",
            "The model provider returned no completion.",
            detail=str(err.get("message")) if err.get("message") else None,
        )

    return choices[0]["message"]
