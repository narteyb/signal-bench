# SPDX-License-Identifier: Apache-2.0
import io
import json
import logging

from signal_bench.telemetry import logging as telemetry_logging
from signal_bench.telemetry.logging import TelemetryJsonFormatter, emit_event, get_logger


def _remove_telemetry_handlers() -> None:
    logger = logging.getLogger(telemetry_logging.TELEMETRY_LOGGER_NAME)
    for handler in list(logger.handlers):
        if getattr(handler, telemetry_logging._HANDLER_MARKER, False):
            logger.removeHandler(handler)
            handler.close()


def test_json_formatter_emits_structured_event() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(TelemetryJsonFormatter())
    logger = logging.getLogger("signal_bench.telemetry.test_json_formatter")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    emit_event(
        logger,
        logging.INFO,
        "source_started",
        source="mock_ina219",
        run_id="run-123",
        context={"sample_rate_hz": 50.0},
    )

    payload = json.loads(stream.getvalue())
    assert payload["event"] == "source_started"
    assert payload["source"] == "mock_ina219"
    assert payload["run_id"] == "run-123"
    assert payload["context"] == {"sample_rate_hz": 50.0}
    assert payload["level"] == "INFO"
    assert payload["at_ts"].endswith("Z")


def test_get_logger_uses_env_log_level(monkeypatch) -> None:
    _remove_telemetry_handlers()
    monkeypatch.setenv("SIGNAL_BENCH_LOG_LEVEL", "DEBUG")

    logger = get_logger("signal_bench.telemetry.test_env_level")

    assert logging.getLogger("signal_bench.telemetry").level == logging.DEBUG
    assert logger.isEnabledFor(logging.DEBUG)


def test_get_logger_writes_json_lines_to_env_destination(tmp_path, monkeypatch) -> None:
    _remove_telemetry_handlers()
    log_path = tmp_path / "telemetry.jsonl"
    monkeypatch.setenv("SIGNAL_BENCH_LOG_DEST", str(log_path))
    monkeypatch.setenv("SIGNAL_BENCH_LOG_LEVEL", "INFO")

    logger = get_logger("signal_bench.telemetry.file_dest")
    emit_event(
        logger,
        logging.WARNING,
        "db_write_lagging",
        source="orchestrator",
        run_id="run-456",
        context={"queue_fraction": 0.9},
    )
    for handler in logging.getLogger("signal_bench.telemetry").handlers:
        handler.flush()

    payload = json.loads(log_path.read_text())
    assert payload["event"] == "db_write_lagging"
    assert payload["context"]["queue_fraction"] == 0.9

    _remove_telemetry_handlers()
