# SPDX-License-Identifier: Apache-2.0
"""Measurement dataclasses and host-side sampling helpers."""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class InferenceMeasurement:
    """One LLM inference measurement ready to persist as a Result row."""

    started_at: datetime
    duration_ms: float
    first_token_ms: float
    tokens_in: int
    tokens_out: int
    throughput_value: float
    completion: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ThermalSnapshot:
    """One thermal-state observation captured during a sustained run."""

    timestamp: datetime
    thermal_state: int | None
    raw: str | None


class ThermalSampler:
    """Capture macOS thermal-state readings at a fixed cadence."""

    def __init__(self, interval_s: float = 10.0) -> None:
        self._interval_s = interval_s
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.samples: list[ThermalSnapshot] = []

    def start(self) -> None:
        """Start thermal sampling in a background thread."""
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="e01-thermal-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> list[ThermalSnapshot]:
        """Stop sampling and return captured snapshots."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._interval_s + 1.0)
        return self.samples

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.samples.append(read_macos_thermal_state())
            self._stop_event.wait(timeout=self._interval_s)


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(tz=UTC)


def read_macos_thermal_state() -> ThermalSnapshot:
    """Read macOS CPU thermal state, returning None if unavailable on this host."""
    try:
        result = subprocess.run(
            ["sysctl", "-n", "machdep.xcpm.cpu_thermal_state"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ThermalSnapshot(timestamp=utc_now(), thermal_state=None, raw=str(exc))

    raw = result.stdout.strip() or result.stderr.strip()
    try:
        thermal_state = int(raw)
    except ValueError:
        thermal_state = None
    return ThermalSnapshot(timestamp=utc_now(), thermal_state=thermal_state, raw=raw or None)


def monotonic_ms_since(start_s: float) -> float:
    """Return elapsed monotonic milliseconds."""
    return (time.perf_counter() - start_s) * 1000.0
