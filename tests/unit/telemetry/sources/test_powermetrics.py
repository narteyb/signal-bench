# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import asyncio

import pytest

from signal_bench.telemetry.exceptions import SourceDataError, SourceStartError
from signal_bench.telemetry.sources.powermetrics import (
    PowermetricsConfig,
    PowermetricsSource,
    parse_powermetrics_power,
)


class _FakeStream:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    async def readline(self) -> bytes:
        if not self._lines:
            await asyncio.sleep(0)
            return b""
        return self._lines.pop(0)

    async def read(self) -> bytes:
        return b""


class _FakeProcess:
    returncode = None

    def __init__(self, lines: list[bytes]) -> None:
        self.stdout = _FakeStream(lines)
        self.stderr = _FakeStream([])
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    async def wait(self) -> int:
        return 0


def test_parse_powermetrics_power_accepts_watts_and_milliwatts() -> None:
    assert parse_powermetrics_power("Package power: 4.25 W") == pytest.approx(4.25)
    assert parse_powermetrics_power("CPU Power: 4250 mW") == pytest.approx(4.25)
    assert parse_powermetrics_power("not power") is None


@pytest.mark.asyncio
async def test_powermetrics_source_discards_warmup_and_yields_power(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/powermetrics")

    process = _FakeProcess(
        [
            b"Package power: 1.0 W\n",
            b"Package power: 2.0 W\n",
            b"Package power: 3.0 W\n",
        ],
    )

    async def _factory(*_args: object, **_kwargs: object) -> _FakeProcess:
        return process

    source = PowermetricsSource(
        PowermetricsConfig(warmup_samples=2),
        process_factory=_factory,
    )
    await source.start()
    sample = await anext(source.samples())
    await source.stop()

    assert sample.source_name == "powermetrics"
    assert object.__getattribute__(sample, "values") == {"power": pytest.approx(3.0)}
    assert process.terminated is True


@pytest.mark.asyncio
async def test_powermetrics_source_requires_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: None)
    source = PowermetricsSource()

    with pytest.raises(SourceStartError, match="not found"):
        await source.start()


@pytest.mark.asyncio
async def test_powermetrics_source_empty_stream_is_data_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/powermetrics")

    async def _factory(*_args: object, **_kwargs: object) -> _FakeProcess:
        return _FakeProcess([])

    source = PowermetricsSource(PowermetricsConfig(warmup_samples=0), process_factory=_factory)
    await source.start()
    with pytest.raises(SourceDataError):
        await anext(source.samples())
