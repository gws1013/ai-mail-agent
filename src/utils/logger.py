"""Logging utilities for AI Mail Agent.

Provides structured logging with Rich console output and rotating file handlers.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from rich.logging import RichHandler

# ---------------------------------------------------------------------------
# Internal registry – avoids creating duplicate handlers on repeated calls
# ---------------------------------------------------------------------------
_loggers: dict[str, logging.Logger] = {}

_DEFAULT_LOG_DIR = Path(__file__).parent.parent.parent / "logs"
_DEFAULT_LOG_LEVEL = logging.INFO

# Log format used by both the file handler and (as a fallback) the console.
_FILE_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# RotatingFileHandler parameters
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_BACKUP_COUNT = 5


def setup_logger(
    name: str,
    log_dir: Optional[str | Path] = None,
    log_level: int | str = logging.INFO,
) -> logging.Logger:
    """Create and configure a named logger with Rich console + rotating file output.

    Args:
        name: Logger name (typically ``__name__`` of the calling module).
        log_dir: Directory where log files are written.  Created automatically
            if it does not exist.  Defaults to ``<project_root>/logs``.
        log_level: Logging level for *both* handlers.  Accepts ``int``
            constants (e.g. ``logging.DEBUG``) or string names
            (e.g. ``"DEBUG"``).

    Returns:
        A fully configured :class:`logging.Logger` instance.

    Example::

        logger = setup_logger("classifier", log_dir="/var/log/mail-agent", log_level="DEBUG")
        logger.info("Classifier started")
    """
    # Resolve log level early so we can validate it
    if isinstance(log_level, str):
        numeric_level = getattr(logging, log_level.upper(), None)
        if not isinstance(numeric_level, int):
            raise ValueError(f"Invalid log level: {log_level!r}")
        log_level = numeric_level

    # Return cached logger if already configured to prevent duplicate handlers
    if name in _loggers:
        logger = _loggers[name]
        logger.setLevel(log_level)
        return logger

    # Resolve log directory
    resolved_dir = Path(log_dir) if log_dir is not None else _DEFAULT_LOG_DIR
    resolved_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(log_level)
    # Prevent log records from propagating to the root logger to avoid
    # duplicate output when multiple loggers are active.
    logger.propagate = False

    # ------------------------------------------------------------------
    # Console handler – Rich renders coloured, structured output
    # ------------------------------------------------------------------
    rich_handler = RichHandler(
        level=log_level,
        rich_tracebacks=True,
        tracebacks_show_locals=False,
        show_time=True,
        show_level=True,
        show_path=True,
        markup=True,
    )
    # Rich already formats the timestamp; keep the format minimal here.
    rich_handler.setFormatter(logging.Formatter("%(message)s", datefmt="[%X]"))
    logger.addHandler(rich_handler)

    # ------------------------------------------------------------------
    # Rotating file handler – plain text, machine-parseable
    # ------------------------------------------------------------------
    log_file = resolved_dir / f"{name}.log"
    file_handler = RotatingFileHandler(
        filename=log_file,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(logging.Formatter(_FILE_FORMAT, datefmt=_DATE_FORMAT))
    logger.addHandler(file_handler)

    _loggers[name] = logger
    return logger


def get_logger(name: str) -> logging.Logger:
    """Return (or create) a logger using project-wide defaults from env/config.

    This is the preferred entry point for module-level loggers.  It reads
    ``LOG_LEVEL`` from the environment and uses the project's default log
    directory so callers do not need to repeat configuration.

    Args:
        name: Logger name – use ``__name__`` of the calling module.

    Returns:
        A configured :class:`logging.Logger` instance.

    Example::

        from src.utils.logger import get_logger
        logger = get_logger(__name__)
        logger.debug("Processing email id=%s", email_id)
    """
    if name in _loggers:
        return _loggers[name]

    env_level = os.environ.get("LOG_LEVEL", "INFO")
    return setup_logger(name=name, log_dir=_DEFAULT_LOG_DIR, log_level=env_level)
