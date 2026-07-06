"""Current Date & Time tool (Appendix B §B.3.2).

DEVIATION (settled build decision (b)): the `except` is widened to also catch
`ValueError`, because `ZoneInfo` raises `ValueError` — not `ZoneInfoNotFoundError`
— for malformed keys (absolute paths, '..' components). Both are recoverable bad
input → an error string the model sees, never a raised crash. The IANA tz db is
shipped via the bundled `tzdata` package (Windows has no system tz db).
"""

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field

from .base import ExecutionContext, Tool
from .registry import register


class DateTimeArgs(BaseModel):
    timezone: str | None = Field(
        default=None,
        description="Optional IANA timezone name, e.g. 'America/New_York' or "
                    "'Europe/London'. If omitted, the system local timezone is used.",
    )


def current_datetime(args: DateTimeArgs, ctx: ExecutionContext) -> str:
    try:
        tz = ZoneInfo(args.timezone) if args.timezone else datetime.now().astimezone().tzinfo
    except (ZoneInfoNotFoundError, ValueError):
        return f"Error: unknown timezone: {args.timezone!r}"
    now = datetime.now(tz)
    return now.isoformat()


register(Tool(
    name="current_datetime",
    description="Return the current date and time, timezone-aware (ISO 8601).",
    args_model=DateTimeArgs,
    handler=current_datetime,
))
