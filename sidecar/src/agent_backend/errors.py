"""Uniform error envelope (Appendix A §A.2.7).

Every non-2xx response, from any endpoint, returns the same shape so the
frontend has exactly one error path. Five kinds only:
  - bad_api_key | model_error | offline   (turn-aborting runtime failures)
  - not_found | bad_request               (protocol-level HTTP errors)

Tool execution failure is deliberately NOT a kind — it never aborts a turn
(Appendix A §A.2.7, Appendix B §B.5).

`message` must always be safe to show the user (no secrets, no stack traces —
those go to the DEBUG log per §6.1).
"""

from __future__ import annotations

from typing import Any, Optional

# kind -> default HTTP status
_STATUS = {
    "bad_api_key": 401,
    "model_error": 502,
    "offline": 503,
    "not_found": 404,
    "bad_request": 400,
}


class ApiError(Exception):
    """Raised anywhere in a request to short-circuit to the error envelope."""

    def __init__(
        self,
        kind: str,
        message: str,
        detail: Optional[str] = None,
        http_status: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.detail = detail
        self.http_status = http_status or _STATUS.get(kind, 500)

    def envelope(self) -> dict[str, Any]:
        return {
            "error": {
                "kind": self.kind,
                "message": self.message,
                "detail": self.detail,
            }
        }


def not_found(message: str = "not found") -> ApiError:
    return ApiError("not_found", message)


def bad_request(message: str, detail: Optional[str] = None) -> ApiError:
    return ApiError("bad_request", message, detail)
