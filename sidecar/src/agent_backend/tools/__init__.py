"""Tool package — importing it populates the registry (Appendix B §B.2).

Each module runs its `register(...)` call at import time. Adding a new tool =
add one module + one name here. Nothing else changes anywhere (PRD Decision #15).
"""

from . import calculator, datetime_tool, files, web_search  # noqa: F401
