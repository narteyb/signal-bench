# SPDX-License-Identifier: Apache-2.0
import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from click.testing import CliRunner
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import signal_bench_cli.commands.telemetry as telemetry_command
from signal_bench.schema import Run, TelemetrySample
from signal_bench.telemetry import TelemetrySample as TelemetrySampleValue
from signal_bench.telemetry import TelemetrySource
from signal_bench_cli.__main__ import main


def test_telemetry_test_mocks_only_command_writes_samples(tmp_path: Path) -> None:
    db_path = tmp_path / "telemetry.db"

    result = CliRunner().invoke(
        main,
        ["telemetry", "test", "--duration", "1", "--no-fnb58", "--db", str(db_path)],
    )

    assert result.exit_code == 0, result.output
    assert "Telemetry Test Summary" in result.output
    assert "mock_ina219_main" in result.output
    assert "mock_bme280_lab" in result.output
    engine = create_engine(f"sqlite:///{db_path}")
    session_factory = sessionmaker(bind=engine)
    try:
        with session_factory() as session:
            run = session.scalar(select(Run).order_by(Run.started_at.desc()))
            assert run is not None
            assert run.status == "completed"
            assert run.extra is not None
            assert run.extra["kind"] == "telemetry_test"
            assert run.extra["skipped_sources"] == ["fnb58"]
            assert run.telemetry_partial is False
            sample_count = session.scalar(
                select(func.count())
                .select_from(TelemetrySample)
                .where(TelemetrySample.run_id == run.run_id),
            )
            assert sample_count is not None
            assert sample_count >= 45
            sources = set(
                session.scalars(
                    select(TelemetrySample.source).where(TelemetrySample.run_id == run.run_id),
                ),
            )
            assert sources == {"mock_ina219_main", "mock_bme280_lab"}
    finally:
        engine.dispose()


def test_telemetry_test_duration_is_required(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        main,
        ["telemetry", "test", "--no-fnb58", "--db", str(tmp_path / "telemetry.db")],
    )

    assert result.exit_code == 3
    assert "--duration must be a positive integer" in result.output


def test_telemetry_test_json_output_is_structured(tmp_path: Path) -> None:
    db_path = tmp_path / "telemetry.db"

    result = CliRunner().invoke(
        main,
        [
            "telemetry",
            "test",
            "--duration",
            "1",
            "--no-fnb58",
            "--quiet",
            "--output",
            "json",
            "--db",
            str(db_path),
        ],
    )

    assert result.exit_code == 0, result.output
    summary = json.loads(result.output.splitlines()[-1])
    assert summary["telemetry_partial"] is False
    assert summary["skipped_sources"] == ["fnb58"]
    assert {source["source"] for source in summary["sources"]} == {
        "mock_ina219_main",
        "mock_bme280_lab",
    }


def test_telemetry_test_csv_output_is_structured(tmp_path: Path) -> None:
    db_path = tmp_path / "telemetry.db"

    result = CliRunner().invoke(
        main,
        [
            "telemetry",
            "test",
            "--duration",
            "1",
            "--no-fnb58",
            "--quiet",
            "--output",
            "csv",
            "--db",
            str(db_path),
        ],
    )

    assert result.exit_code == 0, result.output
    lines = [line for line in result.output.splitlines() if line.startswith(("run_id,", "019"))]
    assert lines[0] == "run_id,source,samples,rows,rate_hz,status"
    assert any("mock_ina219_main" in line for line in lines)
    assert any("mock_bme280_lab" in line for line in lines)


def test_telemetry_test_quiet_table_suppresses_start_banner(tmp_path: Path) -> None:
    db_path = tmp_path / "telemetry.db"

    result = CliRunner().invoke(
        main,
        [
            "telemetry",
            "test",
            "--duration",
            "1",
            "--no-fnb58",
            "--quiet",
            "--db",
            str(db_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Running 1s telemetry test" not in result.output
    assert "Telemetry Test Summary" in result.output


class _FakeFnirsiSource(TelemetrySource):
    source_name = "fnb58"
    sample_rate_hz = 10.0

    def __init__(self, config) -> None:
        self.config = config

    @property
    def name(self) -> str:
        return "fnb58"

    async def start(self) -> None:
        return None

    async def samples(self) -> AsyncIterator[TelemetrySampleValue]:
        if False:
            yield None

    async def stop(self) -> None:
        return None


def test_stage1_sources_use_flag_over_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FNB58_ADDRESS", "env-address")
    monkeypatch.setattr(telemetry_command, "FnirsiSource", _FakeFnirsiSource)

    sources, skipped = telemetry_command._build_stage1_sources(
        fnb58_address="flag-address",
        no_fnb58=False,
        output_format="json",
        quiet=True,
    )

    assert skipped == []
    assert sources[0].name == "fnb58"
    assert sources[0].config.address == "flag-address"


def test_stage1_sources_skip_fnb58_without_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FNB58_ADDRESS", raising=False)

    sources, skipped = telemetry_command._build_stage1_sources(
        fnb58_address=None,
        no_fnb58=False,
        output_format="json",
        quiet=True,
    )

    assert skipped == ["fnb58"]
    assert [source.name for source in sources] == ["mock_ina219_main", "mock_bme280_lab"]


def test_stage1_sources_can_use_real_i2c_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGNAL_BENCH_REAL_I2C", "1")
    monkeypatch.setenv("INA219_ADDRESS", "0x40")
    monkeypatch.setenv("BME280_ADDRESS", "0x76")
    monkeypatch.delenv("FNB58_ADDRESS", raising=False)

    sources, skipped = telemetry_command._build_stage1_sources(
        fnb58_address=None,
        no_fnb58=False,
        output_format="json",
        quiet=True,
    )

    assert skipped == ["fnb58"]
    assert [source.name for source in sources] == ["ina219", "bme280"]
    assert sources[0]._config.address == 0x40
    assert sources[1]._config.address == 0x76


def test_telemetry_sources_lists_mock(tmp_path: Path) -> None:
    db_path = tmp_path / "telemetry.db"
    result = CliRunner().invoke(main, ["telemetry", "sources", "--db", str(db_path)])

    assert result.exit_code == 0, result.output
    assert "mock" in result.output
    assert "available" in result.output
