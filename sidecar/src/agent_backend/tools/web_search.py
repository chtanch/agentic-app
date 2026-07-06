"""Web Search tool — Tavily (Appendix B §B.3.3).

DEVIATION from the B.3.3 code sample: uses `requests` (already a project dep,
already bundled + verified in the PyInstaller build) instead of `httpx`, to
avoid adding a second HTTP client to the packaged sidecar. The error semantics
are identical — timeout / HTTP-status / generic-failure all map to short,
recoverable error strings (Tavily down is data, not an exception).

Key resolution is the sidecar's job: the handler reads the already-resolved key
from `keys.get_key('tavily')` (§5.6 precedence) rather than the DB directly, so
tools stay ignorant of persistence. A missing Tavily key is a recoverable
failure returned as a string — NOT the turn-aborting `bad_api_key` envelope,
which is reserved for the agent's own model key (A.3.1 / A.3.3 §2).
"""

import requests
from pydantic import BaseModel, Field

from .base import ExecutionContext, Tool
from .registry import register
from ..keys import get_key            # resolves 'tavily' per §5.6 precedence (file > DB)

_TAVILY_URL = "https://api.tavily.com/search"
_TIMEOUT = 15.0


class WebSearchArgs(BaseModel):
    query: str = Field(description="The search query.")
    max_results: int = Field(
        default=5, ge=1, le=10,
        description="How many results to return (1-10).",
    )


def web_search(args: WebSearchArgs, ctx: ExecutionContext) -> str:
    key = get_key("tavily")
    if not key:
        # A missing tool key is a recoverable/explainable failure returned as a
        # string, NOT the turn-aborting bad_api_key envelope — that one is
        # reserved for the agent's own model key (A.3.1 / A.3.3 §2).
        return "Error: web search is unavailable: no Tavily API key configured"
    try:
        resp = requests.post(
            _TAVILY_URL,
            headers={"Authorization": f"Bearer {key}"},   # Tavily auth is a Bearer header
            json={
                "query": args.query,
                "max_results": args.max_results,
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout:
        return "Error: web search timed out"
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        return f"Error: web search request failed (HTTP {status})"
    except (requests.exceptions.RequestException, ValueError):
        # ValueError covers a 200 with a non-JSON body (requests' JSONDecodeError).
        return "Error: web search request failed"

    results = data.get("results", [])
    if not results:
        return "No results found."

    lines = [
        f"- {r.get('title', '(untitled)')}\n  {r.get('url', '')}\n  {r.get('content', '')}"
        for r in results
    ]
    return "\n".join(lines)


register(Tool(
    name="web_search",
    description="Search the web and return summarized, linked results.",
    args_model=WebSearchArgs,
    handler=web_search,
))
