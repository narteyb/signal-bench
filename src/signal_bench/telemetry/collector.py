# SPDX-License-Identifier: Apache-2.0
"""Concurrent telemetry capture orchestrator."""

from __future__ import annotations

import logging
import queue
import threading
import time
from contextlib import suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Self, cast

from sqlalchemy import insert, update

from signal_bench.schema import Run
from signal_bench.schema import TelemetrySample as TelemetrySampleRow

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session
    from sqlalchemy.sql.schema import Table

    from signal_bench.telemetry.base import TelemetrySample, TelemetrySource

log = logging.getLogger(__name__)


@dataclass
class CollectorResult:
    """Outcome returned after telemetry capture stops."""

    samples_written: int = 0
    samples_per_source: dict[str, int] = field(default_factory=dict)
    failed_sources: list[str] = field(default_factory=list)
    partial: bool = False


class TelemetryCollector:
    """Runs multiple telemetry sources concurrently against a single run_id."""

    BATCH_SIZE = 200
    BATCH_INTERVAL_S = 0.5
    SHUTDOWN_TIMEOUT_S = 5.0

    def __init__(
        self: Self,
        sources: list[TelemetrySource],
        session_factory: Callable[[], Session],
    ) -> None:
        """Create a collector for a set of telemetry sources."""
        self._sources = sources
        self._session_factory = session_factory
        self._queue: queue.Queue[TelemetrySample] = queue.Queue()
        self._stop_event = threading.Event()
        self._source_threads: list[threading.Thread] = []
        self._writer_thread: threading.Thread | None = None
        self._failed_sources: set[str] = set()
        self._failed_lock = threading.Lock()
        self._result = CollectorResult()
        self._run_id: str | None = None

    def start(self: Self, run_id: str) -> None:
        """Begin sampling. Returns immediately."""
        self._run_id = run_id
        self._queue = queue.Queue()
        self._stop_event.clear()
        self._source_threads = []
        self._writer_thread = None
        self._failed_sources.clear()
        self._result = CollectorResult()

        for source in self._sources:
            try:
                source.open()
            except Exception:
                log.exception("source %s failed to open", source.source_name)
                with self._failed_lock:
                    self._failed_sources.add(source.source_name)

        for source in self._sources:
            if source.source_name in self._failed_sources:
                continue
            thread = threading.Thread(
                target=self._source_loop,
                args=(source,),
                name=f"telemetry-{source.source_name}",
                daemon=True,
            )
            thread.start()
            self._source_threads.append(thread)

        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name="telemetry-writer",
            daemon=True,
        )
        self._writer_thread.start()

    def stop(self: Self) -> CollectorResult:
        """Stop sampling, drain pending writes, update the run row, and return outcome."""
        self._stop_event.set()

        deadline = time.monotonic() + self.SHUTDOWN_TIMEOUT_S
        for thread in self._source_threads:
            remaining = max(0.0, deadline - time.monotonic())
            thread.join(timeout=remaining)
            if thread.is_alive():
                log.warning("source thread %s did not exit within timeout", thread.name)

        for source in self._sources:
            try:
                source.close()
            except Exception:
                log.exception("source %s failed to close", source.source_name)

        if self._writer_thread is not None:
            self._writer_thread.join(timeout=self.SHUTDOWN_TIMEOUT_S)
            if self._writer_thread.is_alive():
                log.warning("writer thread did not exit within timeout")

        with self._failed_lock:
            failed = sorted(self._failed_sources)

        partial = bool(failed)
        if self._run_id is not None:
            with self._session_factory() as session:
                session.execute(
                    update(Run)
                    .where(Run.run_id == self._run_id)
                    .values(
                        telemetry_partial=partial,
                        telemetry_partial_sources=failed if partial else None,
                    ),
                )
                session.commit()

        self._result.failed_sources = failed
        self._result.partial = partial
        return self._result

    def _source_loop(self: Self, source: TelemetrySource) -> None:
        interval = 1.0 / source.sample_rate_hz
        next_tick = time.monotonic()

        while not self._stop_event.is_set():
            try:
                for sample in source.sample():
                    self._queue.put(sample)
            except Exception:
                log.exception("source %s raised, marking partial", source.source_name)
                with self._failed_lock:
                    self._failed_sources.add(source.source_name)
                return

            next_tick += interval
            sleep_for = max(0.0, next_tick - time.monotonic())
            if sleep_for > 0:
                self._stop_event.wait(timeout=sleep_for)
            else:
                next_tick = time.monotonic()

    def _writer_loop(self: Self) -> None:
        batch: list[TelemetrySample] = []
        last_flush = time.monotonic()

        while not (self._stop_event.is_set() and self._queue.empty()):
            with suppress(queue.Empty):
                batch.append(self._queue.get(timeout=0.1))

            now = time.monotonic()
            should_flush = (
                len(batch) >= self.BATCH_SIZE
                or (batch and now - last_flush >= self.BATCH_INTERVAL_S)
                or (self._stop_event.is_set() and batch and self._queue.empty())
            )
            if should_flush:
                self._flush_batch(batch)
                self._result.samples_written += len(batch)
                for sample in batch:
                    self._result.samples_per_source[sample.source] = (
                        self._result.samples_per_source.get(sample.source, 0) + 1
                    )
                batch = []
                last_flush = now

    def _flush_batch(self: Self, batch: list[TelemetrySample]) -> None:
        if self._run_id is None:
            msg = "collector has no active run_id"
            raise RuntimeError(msg)

        rows = [
            {
                "run_id": self._run_id,
                "timestamp": sample.timestamp,
                "source": sample.source,
                "metric": sample.metric,
                "value": sample.value,
            }
            for sample in batch
        ]
        sample_table = cast("Table", TelemetrySampleRow.__table__)
        with self._session_factory() as session:
            session.execute(insert(sample_table), rows)
            session.commit()
