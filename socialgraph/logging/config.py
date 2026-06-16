"""Structured logging configuration for social-graph.

Sets up structlog with two outputs:
- Console: human-readable colored output (level controlled by SG_LOG_LEVEL)
- File:    JSON-lines at .socialgraph/logs/socialgraph.log (rotating, 10 MB × 5 files)

Usage:
    from socialgraph.logging import configure_logging
    configure_logging(settings)   # call once at CLI startup

All modules get loggers via:
    import structlog
    logger = structlog.get_logger(__name__)
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path


def get_log_path(workspace_dir: Path) -> Path:
    log_dir = workspace_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "socialgraph.log"


def configure_logging(settings: object) -> None:
    """Configure structlog + stdlib logging from settings.

    Must be called before any loggers are used (i.e. at CLI entry point).
    """
    import structlog

    log_level_name: str = getattr(settings, "log_level", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    workspace_dir: Path = getattr(settings, "workspace_dir", Path(".socialgraph"))
    log_path = get_log_path(workspace_dir)

    # ── stdlib root logger ───────────────────────────────────────────────
    root = logging.getLogger()
    root.setLevel(log_level)
    root.handlers.clear()

    # Console handler — human readable
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(console_handler)

    # Rotating file handler — JSON lines, survives restarts
    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,  # 10 MB per file
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)  # file always captures everything
    file_handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(file_handler)

    # Silence noisy third-party libs
    for noisy in ("httpx", "httpcore", "playwright", "asyncio", "hpack"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # ── structlog configuration ──────────────────────────────────────────
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=False),
        structlog.processors.StackInfoRenderer(),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Console formatter — pretty coloured output
    console_formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()),
        foreign_pre_chain=shared_processors,
    )
    console_handler.setFormatter(console_formatter)

    # File formatter — JSON lines (machine-readable, greppable)
    file_formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )
    file_handler.setFormatter(file_formatter)

    structlog.get_logger("socialgraph.logging").info(
        "logging.configured",
        level=log_level_name,
        log_file=str(log_path),
    )
