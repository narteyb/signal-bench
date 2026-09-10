# SPDX-License-Identifier: Apache-2.0
"""macOS powermetrics telemetry source."""

from __future__ import annotations

import asyncio
import datetime as dt
import os
import re
import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Self, cast

from signal_bench.telemetry.base import TelemetrySample, TelemetrySource
from signal_bench.telemetry.exceptions import SourceDataError, SourceStartError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

POWERMETRICS_POWER_RE = re.compile(
    r"(?i)\b(?:package|cpu)\s+power\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)\s*(m?W)\b",
)
POWERMETRICS_UNIT_HINTS = {"power": "W"}


@dataclass(frozen=True, slots=True)
class PowermetricsConfig:
    """Configuration for macOS package-power sampling."""

    name: str = "powermetrics"
    sample_rate_hz: float = 10.0
    interval_ms: int = 100
    sampler: str = "cpu_power"
    warmup_samples: int = 2
    command: str = "powermetrics"


class PowermetricsSource(TelemetrySource):
    """Async telemetry source for macOS ``powermetrics`` package power."""

    source_name = "powermetrics"
    sample_rate_hz = 10.0
    partial_coverage_threshold = 0.75

    def __init__(
        self: Self,
        config: PowermetricsConfig | None = None,
        *,
        process_factory: Callable[..., asyncio.subprocess.Process] | None = None,
    ) -> None:
        """Create a powermetrics source."""
        self._config = config or PowermetricsConfig()
        self.source_name = self._config.name
        self.sample_rate_hz = self._config.sample_rate_hz
        self._process_factory = cast("Any", process_factory or asyncio.create_subprocess_exec)
        self._process: asyncio.subprocess.Process | None = None
        self._started = False
        self._stopping = True
        self._discard_remaining = self._config.warmup_samples

    @property
    def name(self: Self) -> str:
        """Return the source name."""
        return self._config.name

    async def start(self: Self) -> None:
        """Start powermetrics sampling."""
        if self._started:
            return
        if shutil.which(self._config.command) is None:
            msg = f"{self._config.command} not found on PATH"
            raise SourceStartError(msg)

        command = _powermetrics_command(self._config)
        try:
            self._process = await self._process_factory(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            msg = f"failed to start powermetrics: {exc}"
            raise SourceStartError(msg) from exc

        await asyncio.sleep(0)
        if self._process.returncode is not None and self._process.returncode != 0:
            stderr = await _read_stream(self._process.stderr)
            msg = _powermetrics_permission_message(stderr)
            raise SourceStartError(msg)

        self._started = True
        self._stopping = False
        self._discard_remaining = self._config.warmup_samples

    async def stop(self: Self) -> None:
        """Stop powermetrics sampling."""
        self._stopping = True
        process = self._process
        self._process = None
        self._started = False
        if process is None or process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=2.0)
        except TimeoutError:
            process.kill()
            await process.wait()

    async def samples(self: Self) -> AsyncIterator[TelemetrySample]:
        """Yield package-power samples."""
        if not self._started or self._process is None or self._process.stdout is None:
            msg = "PowermetricsSource must be started before samples() is consumed"
            raise SourceStartError(msg)

        while not self._stopping:
            line = await self._process.stdout.readline()
            if not line:
                stderr = await _read_stream(self._process.stderr)
                msg = _powermetrics_permission_message(stderr)
                raise SourceDataError(msg)
            power_w = parse_powermetrics_power(line.decode("utf-8", errors="replace"))
            if power_w is None:
                continue
            if self._discard_remaining > 0:
                self._discard_remaining -= 1
                continue
            yield TelemetrySample(
                timestamp=dt.datetime.now(dt.UTC),
                source_name=self._config.name,
                values={"power": power_w},
                unit_hints=POWERMETRICS_UNIT_HINTS,
            )


def parse_powermetrics_power(line: str) -> float | None:
    """Parse one powermetrics package-power line into watts."""
    match = POWERMETRICS_POWER_RE.search(line)
    if match is None:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    return value / 1000.0 if unit == "mw" else value


def _powermetrics_command(config: PowermetricsConfig) -> list[str]:
    base = [
        config.command,
        "--samplers",
        config.sampler,
        "-i",
        str(config.interval_ms),
    ]
    if os.geteuid() == 0:
        return base
    if os.environ.get("SUDO_ASKPASS"):
        return ["sudo", "-A", *base]
    return ["sudo", "-n", *base]


async def _read_stream(stream: asyncio.StreamReader | None) -> str:
    if stream is None:
        return ""
    data = await stream.read()
    return data.decode("utf-8", errors="replace")


def _powermetrics_permission_message(stderr: str) -> str:
    detail = stderr.strip()
    return (
        "powermetrics requires sudo. Configure passwordless sudo for the exact "
        "powermetrics command, for example: "
        "<your-username> ALL=(root) NOPASSWD: /usr/bin/powermetrics --samplers cpu_power *; "
        "or provide SUDO_ASKPASS for sudo -A." + (f" stderr: {detail}" if detail else "")
    )
