# SPDX-License-Identifier: Apache-2.0
"""Structured JSON-line logging for telemetry components."""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import sys
from pathlib import Path

TELEMETRY_LOGGER_NAME = "signal_bench.telemetry"
LOG_LEVEL_ENV = "SIGNAL_BENCH_LOG_LEVEL"
LOG_DEST_ENV = "SIGNAL_BENCH_LOG_DEST"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_DEST = "stderr"
_HANDLER_MARKER = "_signal_bench_telemetry_json_handler"


class TelemetryJsonFormatter(logging.Formatter):
    """Format telemetry log records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        """Return a JSON-line representation of a structured telemetry event."""
        context = getattr(record, "context", {})
        if not isinstance(context, dict):
            context = {"value": str(context)}
        safe_context = _json_safe(context)
        if not isinstance(safe_context, dict):
            safe_context = {"value": safe_context}

        payload: dict[str, object] = {
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", record.getMessage()),
            "source": getattr(record, "source", "orchestrator"),
            "run_id": getattr(record, "run_id", None),
            "at_ts": _record_timestamp(record),
            "context": safe_context,
        }
        if record.exc_info is not None:
            safe_context["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def get_logger(name: str) -> logging.Logger:
    """Return a telemetry logger after installing the default JSON handler."""
    configure_logging()
    return logging.getLogger(name)


def emit_event(  # noqa: PLR0913 - structured event fields are intentionally explicit.
    logger: logging.Logger,
    level: int,
    event: str,
    *,
    source: str,
    run_id: str | None,
    context: dict[str, object] | None = None,
    exc_info: object | None = None,
) -> None:
    """Emit one structured telemetry event."""
    logger.log(
        level,
        event,
        extra={
            "event": event,
            "source": source,
            "run_id": run_id,
            "context": context or {},
        },
        exc_info=exc_info,  # type: ignore[arg-type]
    )


def configure_logging() -> None:
    """Configure the telemetry logger from environment variables once."""
    telemetry_logger = logging.getLogger(TELEMETRY_LOGGER_NAME)
    _enable_telemetry_loggers()
    telemetry_logger.setLevel(_env_level())
    if any(getattr(handler, _HANDLER_MARKER, False) for handler in telemetry_logger.handlers):
        return

    handler = _build_handler()
    setattr(handler, _HANDLER_MARKER, True)
    handler.setFormatter(TelemetryJsonFormatter())
    telemetry_logger.addHandler(handler)
    telemetry_logger.propagate = True


def _build_handler() -> logging.Handler:
    destination = os.environ.get(LOG_DEST_ENV, DEFAULT_LOG_DEST).strip() or DEFAULT_LOG_DEST
    if destination == "stderr":
        return logging.StreamHandler(sys.stderr)
    return logging.FileHandler(Path(destination))


def _enable_telemetry_loggers() -> None:
    logging.getLogger(TELEMETRY_LOGGER_NAME).disabled = False
    for name, logger_obj in logging.Logger.manager.loggerDict.items():
        if (
            name == TELEMETRY_LOGGER_NAME or name.startswith(f"{TELEMETRY_LOGGER_NAME}.")
        ) and isinstance(logger_obj, logging.Logger):
            logger_obj.disabled = False


def _env_level() -> int:
    raw_level = os.environ.get(LOG_LEVEL_ENV, DEFAULT_LOG_LEVEL).upper()
    level = logging.getLevelName(raw_level)
    if isinstance(level, int):
        return level
    return logging.INFO


def _record_timestamp(record: logging.LogRecord) -> str:
    return (
        dt.datetime.fromtimestamp(record.created, tz=dt.UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _json_safe(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
