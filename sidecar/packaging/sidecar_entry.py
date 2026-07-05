"""PyInstaller entry point.

PyInstaller freezes a *script*, not a `-m` module, and `agent_backend`'s modules
use package-relative imports — so we bootstrap through the installed package's
`main()` rather than pointing PyInstaller at `__main__.py` directly.
"""

from agent_backend.__main__ import main

if __name__ == "__main__":
    main()
