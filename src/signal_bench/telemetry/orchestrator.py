# SPDX-License-Identifier: Apache-2.0
"""Async telemetry capture orchestrator."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging as stdlib_logging
import math
import os
import time
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Self, cast

from sqlalchemy import insert, update

from signal_bench.schema import Run
from signal_bench.schema import TelemetrySample as TelemetrySampleRow
from signal_bench.telemetry.base import OrchestratorConfig, TelemetrySample, TelemetrySource
from signal_bench.telemetry.exceptions import (
    OrchestratorError,
    SourceDataError,
    SourceDisconnectError,
    SourceStartError,
    TelemetryError,
)
from signal_bench.telemetry.logging import configure_logging, emit_event, get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from sqlalchemy.orm import Session
    from sqlalchemy.sql.schema import Table

log = get_logger(__name__)

RATE_WINDOW_S = 5.0
RATE_LOW_THRESHOLD_FRACTION = 0.5
RATE_LOW_DURATION_S = 3.0
SOURCE_DISCONNECTED_DURATION_S = 2.0
RATE_MONITOR_INTERVAL_S = 1.0
WRITE_LAG_QUEUE_FRACTION = 0.8
STALE_SAMPLE_THRESHOLD_S = 60.0
FUTURE_SAMPLE_THRESHOLD_S = 10.0
CLOCK_SKEW_THRESHOLD_S = 5.0
PARTIAL_COVERAGE_THRESHOLD_FRAC = 0.90
PARTIAL_COVERAGE_THRESHOLD_ENV = "SIGNAL_BENCH_PARTIAL_COVERAGE_THRESHOLD"
PARTIAL_EXPECTED_SAMPLE_GRACE = 2
PARTIAL_SAMPLE_GRACE_MIN_EXPECTED = 20


@dataclass(frozen=True, slots=True)
class PartialDecision:
    """Run-end telemetry partial decision."""

    partial: bool
    sources: list[str]
    reasons: list[str]
    per_source_coverage: dict[str, float]
    expected_samples: dict[str, int]
    received_samples: dict[str, int]


@dataclass(slots=True)
class OrchestratorState:
    """Observable state accumulated during one telemetry run."""

    samples_written: int = 0
    rows_written: int = 0
    samples_per_source: dict[str, int] = field(default_factory=dict)
    rows_per_source: dict[str, int] = field(default_factory=dict)
    failed_sources: list[str] = field(default_factory=list)
    partial_reasons: list[str] = field(default_factory=list)
    partial: bool = False


class TelemetryOrchestrator:
    """Run async telemetry sources and persist samples for one active run.

    The caller owns run-row creation and final run status. The orchestrator only
    writes scalar rows to ``telemetry_samples`` and updates telemetry partial
    fields on the existing ``runs`` row.
    """

    def __init__(
        self: Self,
        session_factory: Callable[[], Session],
        config: OrchestratorConfig | None = None,
    ) -> None:
        """Create an orchestrator.

        Args:
        ----
            session_factory: Callable returning a synchronous SQLAlchemy
                ``Session``. Sync DB work is isolated in the writer path.
            config: Runtime queue, batching, and shutdown knobs.

        """
        self._session_factory = session_factory
        self._config = config or OrchestratorConfig()
        self._queue: asyncio.Queue[TelemetrySample] = asyncio.Queue(
            maxsize=self._config.queue_maxsize,
        )
        self._stop_event = asyncio.Event()
        self._source_tasks: list[asyncio.Task[None]] = []
        self._writer_task: asyncio.Task[None] | None = None
        self._rate_monitor_task: asyncio.Task[None] | None = None
        self._sources: list[TelemetrySource] = []
        self._run_id: str | None = None
        self._failed_sources: set[str] = set()
        self._fatal_error: OrchestratorError | None = None
        self._state = OrchestratorState()
        self._running = False
        self._run_started_monotonic = 0.0
        self._run_stopping_monotonic: float | None = None
        self._sample_windows: dict[str, deque[float]] = {}
        self._last_sample_monotonic: dict[str, float] = {}
        self._rate_low_started_at: dict[str, float] = {}
        self._rate_low_emitted: set[str] = set()
        self._disconnect_emitted: set[str] = set()
        self._write_lag_emitted = False
        self._latest_sample_timestamps: dict[str, float] = {}
        self._clock_skew_emitted = False
        self._writer_failure_reason: str | None = None

    @property
    def state(self: Self) -> OrchestratorState:
        """Return the current run state."""
        return self._state

    async def start_run(self: Self, run_id: str, sources: Iterable[TelemetrySource]) -> None:
        """Start telemetry capture for an existing run row.

        Sources are started concurrently. Source startup failures mark the run
        partial; healthy sources continue. A non-empty source list is still
        required so configuration mistakes fail clearly.
        """
        configure_logging()
        if self._running:
            msg = "telemetry orchestrator already has an active run"
            emit_event(
                log,
                stdlib_logging.ERROR,
                "run_start_rejected",
                source="orchestrator",
                run_id=self._run_id,
                context={"reason": msg},
            )
            raise OrchestratorError(msg)

        self._sources = list(sources)
        if not self._sources:
            msg = "telemetry orchestrator requires at least one source"
            emit_event(
                log,
                stdlib_logging.ERROR,
                "source_start_failed",
                source="orchestrator",
                run_id=run_id,
                context={"reason": msg},
            )
            raise SourceStartError(msg)

        self._run_id = run_id
        self._queue = asyncio.Queue(maxsize=self._config.queue_maxsize)
        self._stop_event = asyncio.Event()
        self._source_tasks = []
        self._writer_task = None
        self._rate_monitor_task = None
        self._failed_sources = set()
        self._fatal_error = None
        self._state = OrchestratorState()
        self._run_started_monotonic = time.monotonic()
        self._run_stopping_monotonic = None
        self._sample_windows = {source.name: deque() for source in self._sources}
        self._last_sample_monotonic = {}
        self._rate_low_started_at = {}
        self._rate_low_emitted = set()
        self._disconnect_emitted = set()
        self._write_lag_emitted = False
        self._latest_sample_timestamps = {}
        self._clock_skew_emitted = False
        self._writer_failure_reason = None

        emit_event(
            log,
            stdlib_logging.INFO,
            "run_started",
            source="orchestrator",
            run_id=run_id,
            context={
                "source_count": len(self._sources),
                "sources": [source.name for source in self._sources],
                "queue_maxsize": self._config.queue_maxsize,
                "batch_size": self._config.batch_size,
            },
        )
        started_sources = await self._start_sources(self._sources)
        self._writer_task = asyncio.create_task(
            self._writer_loop(),
            name="telemetry-orchestrator-writer",
        )
        self._run_started_monotonic = time.monotonic()
        self._rate_monitor_task = asyncio.create_task(
            self._rate_monitor_loop(),
            name="telemetry-orchestrator-rate-monitor",
        )
        self._source_tasks = [
            asyncio.create_task(
                self._source_pump(source),
                name=f"telemetry-orchestrator-{source.name}",
            )
            for source in started_sources
        ]
        self._running = True

    async def stop_run(self: Self) -> OrchestratorState:
        """Stop telemetry capture, drain pending samples, and return state.

        Calling this method when the orchestrator is idle is harmless.
        """
        if not self._running and self._writer_task is None:
            return self._state

        emit_event(
            log,
            stdlib_logging.INFO,
            "run_stopping",
            source="orchestrator",
            run_id=self._run_id,
            context={},
        )
        self._run_stopping_monotonic = time.monotonic()
        self._stop_event.set()
        await self._cancel_rate_monitor_task()
        await self._cancel_source_tasks()
        await self._stop_sources()
        writer_failed = (
            self._fatal_error is not None
            and self._writer_task is not None
            and self._writer_task.done()
        )
        if writer_failed:
            self._drain_queue_after_writer_failure()
        await self._queue.join()

        if self._writer_task is not None:
            await self._writer_task

        decision = self._decide_telemetry_partial()
        await self._update_run_partial(decision)
        self._state.failed_sources = sorted(self._failed_sources)
        self._state.partial_reasons = decision.reasons
        self._state.partial = decision.partial
        self._running = False

        emit_event(
            log,
            stdlib_logging.INFO,
            "telemetry_partial_decided",
            source="orchestrator",
            run_id=self._run_id,
            context={
                "partial": decision.partial,
                "criterion": "coverage_below_threshold",
                "threshold_frac": get_partial_coverage_threshold(),
                "per_source_coverage": decision.per_source_coverage,
                "expected_samples": decision.expected_samples,
                "received_samples": decision.received_samples,
                "reasons": decision.reasons,
            },
        )
        if self._fatal_error is not None:
            emit_event(
                log,
                stdlib_logging.ERROR,
                "run_failed",
                source="orchestrator",
                run_id=self._run_id,
                context={
                    "samples_written": self._state.samples_written,
                    "rows_written": self._state.rows_written,
                    "failed_sources": self._state.failed_sources,
                    "error_class": type(self._fatal_error).__name__,
                    "message": str(self._fatal_error),
                },
            )
            raise self._fatal_error
        emit_event(
            log,
            stdlib_logging.INFO,
            "run_completed",
            source="orchestrator",
            run_id=self._run_id,
            context={
                "samples_written": self._state.samples_written,
                "rows_written": self._state.rows_written,
                "failed_sources": self._state.failed_sources,
                "partial": self._state.partial,
            },
        )
        return self._state

    async def _start_sources(
        self: Self,
        sources: list[TelemetrySource],
    ) -> list[TelemetrySource]:
        results = await asyncio.gather(
            *(source.start() for source in sources),
            return_exceptions=True,
        )
        failed = [
            (source, result)
            for source, result in zip(sources, results, strict=True)
            if isinstance(result, Exception)
        ]
        if not failed:
            for source in sources:
                emit_event(
                    log,
                    stdlib_logging.INFO,
                    "source_started",
                    source=source.name,
                    run_id=self._run_id,
                    context={"sample_rate_hz": source.sample_rate_hz},
                )
            return sources

        succeeded = [
            source
            for source, result in zip(sources, results, strict=True)
            if not isinstance(result, Exception)
        ]

        failed_names = ", ".join(source.name for source, _result in failed)
        for source in succeeded:
            emit_event(
                log,
                stdlib_logging.INFO,
                "source_started",
                source=source.name,
                run_id=self._run_id,
                context={"sample_rate_hz": source.sample_rate_hz},
            )
        for source, result in failed:
            self._failed_sources.add(source.name)
            emit_event(
                log,
                stdlib_logging.ERROR,
                "source_start_failed",
                source=source.name,
                run_id=self._run_id,
                context={
                    "error_class": type(result).__name__,
                    "message": str(result),
                    "failed_sources": [failed_source.name for failed_source, _ in failed],
                },
                exc_info=result,
            )
        decision = self._decide_telemetry_partial()
        await self._update_run_partial(decision)
        self._state.failed_sources = decision.sources
        self._state.partial_reasons = decision.reasons
        self._state.partial = decision.partial
        emit_event(
            log,
            stdlib_logging.WARNING,
            "telemetry_start_degraded",
            source="orchestrator",
            run_id=self._run_id,
            context={
                "failed_sources": sorted(self._failed_sources),
                "started_sources": [source.name for source in succeeded],
                "message": f"telemetry source startup failed: {failed_names}",
            },
        )
        return succeeded

    async def _source_pump(self: Self, source: TelemetrySource) -> None:
        try:
            async for sample in source.samples():
                if self._stop_event.is_set():
                    break
                self._record_sample_health(sample.source_name)
                self._check_sample_timestamp(sample)
                await self._queue.put(sample)
                self._maybe_log_write_lag()
                if log.isEnabledFor(stdlib_logging.DEBUG):
                    emit_event(
                        log,
                        stdlib_logging.DEBUG,
                        "sample_received",
                        source=sample.source_name,
                        run_id=self._run_id,
                        context={
                            "metric_count": len(sample.values),
                            "queue_size": self._queue.qsize(),
                        },
                    )
            if not self._stop_event.is_set():
                emit_event(
                    log,
                    stdlib_logging.WARNING,
                    "source_stopped_unexpectedly",
                    source=source.name,
                    run_id=self._run_id,
                    context={},
                )
                self._record_source_failure(source.name)
        except asyncio.CancelledError:
            raise
        except (SourceDisconnectError, SourceDataError) as exc:
            event = (
                "source_disconnected"
                if isinstance(exc, SourceDisconnectError)
                else "source_data_error"
            )
            emit_event(
                log,
                stdlib_logging.ERROR,
                event,
                source=source.name,
                run_id=self._run_id,
                context={"error_class": type(exc).__name__, "message": str(exc)},
                exc_info=exc,
            )
            self._record_source_failure(source.name)
        except TelemetryError as exc:
            emit_event(
                log,
                stdlib_logging.ERROR,
                "source_telemetry_error",
                source=source.name,
                run_id=self._run_id,
                context={"error_class": type(exc).__name__, "message": str(exc)},
                exc_info=exc,
            )
            self._record_source_failure(source.name)
        except Exception as exc:  # noqa: BLE001 - source failures mark the run partial.
            emit_event(
                log,
                stdlib_logging.ERROR,
                "source_unhandled_exception",
                source=source.name,
                run_id=self._run_id,
                context={"error_class": type(exc).__name__, "message": str(exc)},
                exc_info=exc,
            )
            self._record_source_failure(source.name)

    def _record_source_failure(self: Self, source_name: str) -> None:
        already_failed = source_name in self._failed_sources
        self._failed_sources.add(source_name)
        self._state.failed_sources = sorted(self._failed_sources)
        if not already_failed:
            emit_event(
                log,
                stdlib_logging.WARNING,
                "partial_data_threshold_crossed",
                source=source_name,
                run_id=self._run_id,
                context={
                    "failed_sources": sorted(self._failed_sources),
                    "source_count": len(self._sources),
                },
            )
        if len(self._failed_sources) >= len(self._sources):
            emit_event(
                log,
                stdlib_logging.ERROR,
                "all_sources_failed",
                source="orchestrator",
                run_id=self._run_id,
                context={"failed_sources": sorted(self._failed_sources)},
            )

    async def _cancel_rate_monitor_task(self: Self) -> None:
        task = self._rate_monitor_task
        if task is None:
            return
        if not task.done():
            task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        self._rate_monitor_task = None

    async def _cancel_source_tasks(self: Self) -> None:
        for task in self._source_tasks:
            if not task.done():
                task.cancel()

        if not self._source_tasks:
            return

        done, pending = await asyncio.wait(
            self._source_tasks,
            timeout=self._config.shutdown_timeout_s,
        )
        for task in done:
            with suppress(asyncio.CancelledError):
                task.result()
        for task in pending:
            emit_event(
                log,
                stdlib_logging.WARNING,
                "source_task_stop_timeout",
                source="orchestrator",
                run_id=self._run_id,
                context={"task_name": task.get_name()},
            )

    async def _stop_sources(self: Self, sources: Iterable[TelemetrySource] | None = None) -> None:
        source_list = list(self._sources if sources is None else sources)
        if not source_list:
            return

        async def _stop_one(source: TelemetrySource) -> None:
            try:
                await asyncio.wait_for(source.stop(), timeout=self._config.shutdown_timeout_s)
                emit_event(
                    log,
                    stdlib_logging.INFO,
                    "source_stopped",
                    source=source.name,
                    run_id=self._run_id,
                    context={},
                )
            except TimeoutError:
                emit_event(
                    log,
                    stdlib_logging.ERROR,
                    "orchestrator_teardown_failed",
                    source=source.name,
                    run_id=self._run_id,
                    context={"reason": "source_stop_timeout"},
                )
            except Exception as exc:  # noqa: BLE001 - teardown must not mask run results.
                emit_event(
                    log,
                    stdlib_logging.ERROR,
                    "orchestrator_teardown_failed",
                    source=source.name,
                    run_id=self._run_id,
                    context={
                        "reason": "source_stop_failed",
                        "error_class": type(exc).__name__,
                        "message": str(exc),
                    },
                    exc_info=exc,
                )

        await asyncio.gather(*(_stop_one(source) for source in source_list))

    async def _writer_loop(self: Self) -> None:  # noqa: C901
        batch: list[TelemetrySample] = []
        last_flush = time.monotonic()
        while not (self._stop_event.is_set() and self._queue.empty()):
            try:
                sample = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=self._config.flush_interval_s,
                )
                batch.append(sample)
            except TimeoutError:
                pass

            now = time.monotonic()
            should_flush = (
                len(batch) >= self._config.batch_size
                or (batch and now - last_flush >= self._config.flush_interval_s)
                or (self._stop_event.is_set() and batch and self._queue.empty())
            )
            if should_flush:
                try:
                    await self._flush_batch(batch)
                except Exception as exc:  # noqa: BLE001 - any DB failure loses telemetry.
                    self._handle_writer_failure(batch, exc)
                    return
                else:
                    for _sample in batch:
                        self._queue.task_done()
                    batch = []
                    last_flush = now

        if batch:
            try:
                await self._flush_batch(batch)
            except Exception as exc:  # noqa: BLE001 - any DB failure loses telemetry.
                self._handle_writer_failure(batch, exc)
                return
            else:
                for _sample in batch:
                    self._queue.task_done()

    async def _flush_batch(self: Self, batch: list[TelemetrySample]) -> None:
        rows = self._rows_from_samples(batch)
        if not rows:
            return

        await asyncio.to_thread(self._insert_rows, rows)
        emit_event(
            log,
            stdlib_logging.DEBUG,
            "db_batch_written",
            source="orchestrator",
            run_id=self._run_id,
            context={"sample_count": len(batch), "row_count": len(rows)},
        )
        self._state.samples_written += len(batch)
        self._state.rows_written += len(rows)
        for sample in batch:
            self._state.samples_per_source[sample.source_name] = (
                self._state.samples_per_source.get(sample.source_name, 0) + 1
            )
            self._state.rows_per_source[sample.source_name] = self._state.rows_per_source.get(
                sample.source_name, 0
            ) + len(sample.values)

    def _rows_from_samples(
        self: Self, samples: Iterable[TelemetrySample]
    ) -> list[dict[str, object]]:
        if self._run_id is None:
            msg = "telemetry orchestrator has no active run_id"
            raise OrchestratorError(msg)

        rows: list[dict[str, object]] = []
        for sample in samples:
            for metric, value in dict.items(sample.values):
                rows.append(
                    {
                        "run_id": self._run_id,
                        "timestamp": sample.timestamp,
                        "source": sample.source_name,
                        "metric": metric,
                        "value": value,
                    },
                )
        return rows

    def _insert_rows(self: Self, rows: list[dict[str, object]]) -> None:
        sample_table = cast("Table", TelemetrySampleRow.__table__)
        with self._session_factory() as session:
            session.execute(insert(sample_table), rows)
            session.commit()

    async def _update_run_partial(self: Self, decision: PartialDecision) -> None:
        if self._run_id is None:
            return

        await asyncio.to_thread(self._update_run_partial_sync, decision=decision)

    def _update_run_partial_sync(self: Self, *, decision: PartialDecision) -> None:
        if self._run_id is None:
            return

        with self._session_factory() as session:
            session.execute(
                update(Run)
                .where(Run.run_id == self._run_id)
                .values(
                    telemetry_partial=decision.partial,
                    telemetry_partial_sources=decision.sources if decision.partial else None,
                    partial_reasons=decision.reasons if decision.partial else None,
                ),
            )
            session.commit()

    def _decide_telemetry_partial(self: Self) -> PartialDecision:
        stop_at = self._run_stopping_monotonic or time.monotonic()
        run_duration_s = max(0.0, stop_at - self._run_started_monotonic)
        reasons: list[str] = []
        partial_sources: set[str] = set()
        per_source_coverage: dict[str, float] = {}
        expected_samples: dict[str, int] = {}
        received_samples: dict[str, int] = {}

        for source in self._sources:
            threshold = _source_partial_threshold(source)
            expected = max(1, math.floor(source.sample_rate_hz * run_duration_s))
            received = self._state.samples_per_source.get(source.name, 0)
            coverage = min(1.0, received / expected)
            per_source_coverage[source.name] = round(coverage, 4)
            expected_samples[source.name] = expected
            received_samples[source.name] = received
            if _coverage_below_threshold(
                received=received,
                expected=expected,
                threshold=threshold,
            ):
                partial_sources.add(source.name)
                reasons.append(
                    _coverage_reason(
                        source=source.name,
                        coverage=coverage,
                        threshold=threshold,
                        received=received,
                        expected=expected,
                    ),
                )

        if self._writer_failure_reason is not None:
            partial_sources.add("db_writer")
            reasons.append(self._writer_failure_reason)

        return PartialDecision(
            partial=bool(reasons),
            sources=sorted(partial_sources),
            reasons=reasons,
            per_source_coverage=per_source_coverage,
            expected_samples=expected_samples,
            received_samples=received_samples,
        )

    async def _rate_monitor_loop(self: Self) -> None:
        while not self._stop_event.is_set():
            await asyncio.sleep(RATE_MONITOR_INTERVAL_S)
            if self._stop_event.is_set():
                return
            self._check_source_rates(time.monotonic())

    def _record_sample_health(self: Self, source_name: str) -> None:
        now = time.monotonic()
        window = self._sample_windows.setdefault(source_name, deque())
        window.append(now)
        self._last_sample_monotonic[source_name] = now
        cutoff = now - RATE_WINDOW_S
        while window and window[0] < cutoff:
            window.popleft()

    def _check_sample_timestamp(self: Self, sample: TelemetrySample) -> None:
        timestamp = sample.timestamp
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            emit_event(
                log,
                stdlib_logging.WARNING,
                "sample_timestamp_invalid",
                source=sample.source_name,
                run_id=self._run_id,
                context={"reason": "naive_datetime", "timestamp": timestamp.isoformat()},
            )
            return

        sample_epoch = timestamp.timestamp()
        self._latest_sample_timestamps[sample.source_name] = sample_epoch
        now_epoch = dt.datetime.now(dt.UTC).timestamp()
        age_s = now_epoch - sample_epoch
        if age_s > STALE_SAMPLE_THRESHOLD_S:
            emit_event(
                log,
                stdlib_logging.WARNING,
                "sample_timestamp_stale",
                source=sample.source_name,
                run_id=self._run_id,
                context={
                    "age_s": round(age_s, 3),
                    "threshold_s": STALE_SAMPLE_THRESHOLD_S,
                    "timestamp": timestamp.isoformat(),
                },
            )
        elif age_s < -FUTURE_SAMPLE_THRESHOLD_S:
            emit_event(
                log,
                stdlib_logging.WARNING,
                "sample_timestamp_invalid",
                source=sample.source_name,
                run_id=self._run_id,
                context={
                    "reason": "future_datetime",
                    "age_s": round(age_s, 3),
                    "threshold_s": FUTURE_SAMPLE_THRESHOLD_S,
                    "timestamp": timestamp.isoformat(),
                },
            )

        min_sources_for_skew = 2
        if len(self._latest_sample_timestamps) < min_sources_for_skew or self._clock_skew_emitted:
            return
        earliest = min(self._latest_sample_timestamps.values())
        latest = max(self._latest_sample_timestamps.values())
        skew_s = latest - earliest
        if skew_s <= CLOCK_SKEW_THRESHOLD_S:
            return
        self._clock_skew_emitted = True
        emit_event(
            log,
            stdlib_logging.WARNING,
            "clock_skew_detected",
            source="orchestrator",
            run_id=self._run_id,
            context={
                "skew_s": round(skew_s, 3),
                "threshold_s": CLOCK_SKEW_THRESHOLD_S,
                "sources": sorted(self._latest_sample_timestamps),
            },
        )

    def _check_source_rates(self: Self, now: float) -> None:
        for source in self._sources:
            if source.name in self._failed_sources:
                continue
            elapsed_s = max(0.0, now - self._run_started_monotonic)
            last_sample_at = self._last_sample_monotonic.get(source.name)
            if (
                elapsed_s >= SOURCE_DISCONNECTED_DURATION_S
                and last_sample_at is None
                and source.name not in self._disconnect_emitted
            ):
                self._disconnect_emitted.add(source.name)
                emit_event(
                    log,
                    stdlib_logging.ERROR,
                    "source_disconnected",
                    source=source.name,
                    run_id=self._run_id,
                    context={
                        "reason": "no_samples_seen",
                        "elapsed_s": round(elapsed_s, 3),
                        "threshold_s": SOURCE_DISCONNECTED_DURATION_S,
                    },
                )
                self._record_source_failure(source.name)
                continue

            if (
                last_sample_at is not None
                and now - last_sample_at >= SOURCE_DISCONNECTED_DURATION_S
                and source.name not in self._disconnect_emitted
            ):
                self._disconnect_emitted.add(source.name)
                emit_event(
                    log,
                    stdlib_logging.ERROR,
                    "source_disconnected",
                    source=source.name,
                    run_id=self._run_id,
                    context={
                        "reason": "no_recent_samples",
                        "silence_s": round(now - last_sample_at, 3),
                        "threshold_s": SOURCE_DISCONNECTED_DURATION_S,
                    },
                )
                self._record_source_failure(source.name)
                continue

            expected_rate_hz = source.sample_rate_hz
            if expected_rate_hz <= 0:
                continue
            observed_rate_hz = self._observed_rate_hz(source.name, now)
            threshold_hz = expected_rate_hz * RATE_LOW_THRESHOLD_FRACTION
            if elapsed_s < RATE_LOW_DURATION_S:
                continue
            if observed_rate_hz < threshold_hz:
                low_started_at = self._rate_low_started_at.setdefault(source.name, now)
                if (
                    now - low_started_at >= RATE_LOW_DURATION_S
                    and source.name not in self._rate_low_emitted
                ):
                    self._rate_low_emitted.add(source.name)
                    emit_event(
                        log,
                        stdlib_logging.WARNING,
                        "sample_rate_below_threshold",
                        source=source.name,
                        run_id=self._run_id,
                        context={
                            "expected_hz": expected_rate_hz,
                            "observed_hz": round(observed_rate_hz, 3),
                            "threshold_hz": round(threshold_hz, 3),
                            "window_s": RATE_WINDOW_S,
                            "duration_s": RATE_LOW_DURATION_S,
                        },
                    )
            else:
                self._rate_low_started_at.pop(source.name, None)

    def _observed_rate_hz(self: Self, source_name: str, now: float) -> float:
        window = self._sample_windows.setdefault(source_name, deque())
        cutoff = now - RATE_WINDOW_S
        while window and window[0] < cutoff:
            window.popleft()
        elapsed = min(RATE_WINDOW_S, max(1.0, now - self._run_started_monotonic))
        return len(window) / elapsed

    def _maybe_log_write_lag(self: Self) -> None:
        if self._write_lag_emitted or self._queue.maxsize <= 0:
            return
        queue_size = self._queue.qsize()
        queue_fraction = queue_size / self._queue.maxsize
        if queue_fraction < WRITE_LAG_QUEUE_FRACTION:
            return
        self._write_lag_emitted = True
        emit_event(
            log,
            stdlib_logging.WARNING,
            "db_write_lagging",
            source="orchestrator",
            run_id=self._run_id,
            context={
                "queue_size": queue_size,
                "queue_maxsize": self._queue.maxsize,
                "queue_fraction": round(queue_fraction, 3),
                "threshold_fraction": WRITE_LAG_QUEUE_FRACTION,
            },
        )

    def _handle_writer_failure(self: Self, batch: list[TelemetrySample], exc: Exception) -> None:
        emit_event(
            log,
            stdlib_logging.ERROR,
            "db_write_failed",
            source="orchestrator",
            run_id=self._run_id,
            context={
                "error_class": type(exc).__name__,
                "message": str(exc),
                "batch_size": len(batch),
                "queue_size": self._queue.qsize(),
            },
            exc_info=exc,
        )
        self._writer_failure_reason = f"db_writer: write failed ({type(exc).__name__}: {exc})"
        for _sample in batch:
            self._queue.task_done()
        drained = self._drain_queue_after_writer_failure()
        self._fatal_error = OrchestratorError("telemetry database write failed")
        self._stop_event.set()
        if drained:
            emit_event(
                log,
                stdlib_logging.WARNING,
                "queue_drained_after_writer_failure",
                source="orchestrator",
                run_id=self._run_id,
                context={"drained_samples": drained},
            )

    def _drain_queue_after_writer_failure(self: Self) -> int:
        drained = 0
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            self._queue.task_done()
            drained += 1
        return drained


def get_partial_coverage_threshold() -> float:
    """Return the configured global partial coverage threshold."""
    raw_threshold = os.environ.get(
        PARTIAL_COVERAGE_THRESHOLD_ENV,
        str(PARTIAL_COVERAGE_THRESHOLD_FRAC),
    )
    try:
        threshold = float(raw_threshold)
    except ValueError as exc:
        msg = (
            f"{PARTIAL_COVERAGE_THRESHOLD_ENV} must be a float in the range "
            f"0.0 < threshold <= 1.0, got {raw_threshold!r}"
        )
        raise ValueError(msg) from exc
    if not 0.0 < threshold <= 1.0:
        msg = (
            f"{PARTIAL_COVERAGE_THRESHOLD_ENV} must be in the range "
            f"0.0 < threshold <= 1.0, got {threshold}"
        )
        raise ValueError(msg)
    return threshold


def _source_partial_threshold(source: TelemetrySource) -> float:
    override = getattr(source, "partial_coverage_threshold", None)
    if override is None:
        return get_partial_coverage_threshold()
    threshold = float(override)
    if not 0.0 < threshold <= 1.0:
        msg = f"{source.name} partial_coverage_threshold must be 0.0 < threshold <= 1.0"
        raise ValueError(msg)
    return threshold


def _coverage_below_threshold(*, received: int, expected: int, threshold: float) -> bool:
    grace = PARTIAL_EXPECTED_SAMPLE_GRACE if expected >= PARTIAL_SAMPLE_GRACE_MIN_EXPECTED else 0
    return (received + grace) < (threshold * expected)


def _coverage_reason(
    *,
    source: str,
    coverage: float,
    threshold: float,
    received: int,
    expected: int,
) -> str:
    coverage_pct = round(coverage * 100)
    threshold_pct = round(threshold * 100)
    return (
        f"{source}: coverage={coverage_pct}%, threshold={threshold_pct}%, "
        f"samples={received}/{expected}"
    )
