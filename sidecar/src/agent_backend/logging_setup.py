"""Logging setup (PRD §6.1).

A fresh, timestamped log file per sidecar start (no cleanup), hardcoded at
DEBUG (no toggle). Keys are never logged anywhere in the app; that is a
discipline at every log call site, not a filter here.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from .config import logs_dir

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging() -> Path:
    """Configure root logging and return the path of this run's log file.

    Called once at startup. A new file `app_YYYYMMDD_HHMMSS.log` is created each
    run so files sort chronologically and each run is self-contained.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = logs_dir() / f"app_{ts}.log"

    formatter = logging.Formatter(_FORMAT)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # hardcoded DEBUG (PRD §6.1, Decision #16)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    logging.getLogger(__name__).info("logging started; writing to %s", log_file)
    return log_file
