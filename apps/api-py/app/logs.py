"""Structured logging: one JSON object per line, with the request id on every line.

`configure_logging()` routes both structlog loggers and the standard `logging` loggers the
rest of the code already uses through the same pipeline, so existing `logger.info(...)` calls
gain the request id and JSON output without being rewritten.
"""

import logging
import sys
from typing import IO

import structlog
from structlog.typing import Processor


def configure_logging(
    level: str = "INFO", fmt: str = "json", stream: IO[str] | None = None
) -> None:
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,  # adds request_id (and anything else bound)
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
    final: list[Processor]
    if fmt == "json":
        final = [structlog.processors.format_exc_info, structlog.processors.JSONRenderer()]
    else:
        final = [structlog.dev.ConsoleRenderer()]
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, *final],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # httpx logs every outgoing request URL at INFO, and the Google embeddings call carries its
    # API key in the URL (?key=...). Keep these libraries quiet so a secret can never reach the logs.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    # uvicorn installs its own handlers; send its messages through ours instead. The access log
    # is left alone on purpose: it is switched off (--no-access-log) because RequestIdMiddleware
    # logs one line per request, with the request id.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
