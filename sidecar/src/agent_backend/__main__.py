"""Sidecar entrypoint: `python -m agent_backend` (and the PyInstaller target).

Startup order: logging first (so everything after is captured), then the DB
schema, then bind the Flask app to 127.0.0.1:PORT.
"""

from __future__ import annotations

import logging

from . import db
from .config import HOST, PORT
from .logging_setup import setup_logging
from .server import create_app


def main() -> None:
    setup_logging()
    log = logging.getLogger(__name__)

    db.init_db()
    log.info("database ready")

    app = create_app()
    log.info("sidecar listening on http://%s:%d", HOST, PORT)
    # threaded=True: chat turns can be slow; don't block health checks.
    # use_reloader=False: this runs as a bundled sidecar, not a dev server.
    app.run(host=HOST, port=PORT, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
