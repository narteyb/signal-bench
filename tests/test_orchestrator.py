# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import asyncio
import datetime as dt
import json
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from signal_bench.adapters import Adapter, AdapterConfig, InferenceResult, OSInfo, ThermalReading
from signal_bench.orchestrator import (
    CellSpec,
    Orchestrator,
    OrchestratorConfig,
    ProtocolGateRejected,
)
from signal_bench.schema import Failure, Run

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from pathlib import Path

    from signal_bench.adapters.mcu.task import TaskSpec


class SleepRecorder:
    """Record requested sleeps without waiting."""

    def __init__(self) -> None:
        """Create an empty sleep recorder."""
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        """Record one requested sleep duration."""
        self.calls.append(seconds)


class ThermalAdapter(Adapter):
    """Adapter with programmable thermal availability for protocol-gate tests."""

    def __init__(self, *, available: bool = True, temperature_c: float = 40.0) -> None:
        """Create a test adapter with fixed device-temperature behavior."""
        super().__init__(AdapterConfig(target_id="mock"))
        self.available = available
        self.temperature_c = temperature_c
        self.prepared = False

    async def prepare(self, run_id: str) -> None:
        """Mark the synthetic target prepared."""
        _ = run_id
        self.prepared = True

    async def warmup(self) -> None:
        """No-op warmup."""

    async def measure(self, task: TaskSpec, iterations: int) -> AsyncIterator[InferenceResult]:
        """Yield deterministic inference results."""
        for iter_id in range(iterations):
            yield InferenceResult(
                iter_id=iter_id,
                output={"task": task.task_id, "iter": iter_id},
                duration_us=1000,
                timestamp=dt.datetime.now(dt.UTC),
            )

    async def read_thermal(self) -> ThermalReading:
        """Return the configured thermal reading."""
        return ThermalReading(
            available=self.available,
            temperature_c=self.temperature_c if self.available else None,
            sensor="test-soc" if self.available else None,
            timestamp=dt.datetime.now(dt.UTC),
        )

    async def os_info(self) -> OSInfo:
        """Return synthetic OS metadata."""
        return OSInfo(target_name="mock", firmware_version="test")

    async def teardown(self) -> None:
        """Mark the synthetic target torn down."""
        self.prepared = False


def _sequenced_ambient(values: list[float | None]) -> Callable[[], float | None]:
    def _read() -> float | None:
        if len(values) == 1:
            return values[0]
        return values.pop(0)

    return _read


def _sequenced_thermal(values: list[float]) -> Callable[[str], ThermalReading]:
    def _read(target_name: str) -> ThermalReading:
        value = values[0] if len(values) == 1 else values.pop(0)
        return ThermalReading(
            available=True,
            temperature_c=value,
            sensor=f"{target_name}-soc",
            timestamp=dt.datetime.now(dt.UTC),
        )

    return _read


def _thermal_adapter_factory(
    *,
    available: bool = True,
    temperature_c: float = 40.0,
) -> Callable[[str], ThermalAdapter]:
    def _build(target_name: str) -> ThermalAdapter:
        _ = target_name
        return ThermalAdapter(available=available, temperature_c=temperature_c)

    return _build


def _lineage(tmp_path: Path, *, delta_pp: float = -1.0, sparsity: float | None = None) -> Path:
    payload = {
        "derived_from": "tinyml-kws-ds-cnn-ref-v1",
        "prep_method": "quantization-aware-training",
        "prep_params": {"target_dtype": "int8"},
        "accuracy_retention": {
            "metric": "top1",
            "canonical": 0.943,
            "variant": 0.943 + (delta_pp / 100),
            "delta_pp": delta_pp,
        },
        "prep_pipeline_uri": "variant-pipeline://model-prep/v1/kws",
    }
    if sparsity is not None:
        payload["prep_params"]["sparsity"] = sparsity
    path = tmp_path / f"lineage-{delta_pp}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _runs(db_path: Path) -> list[Run]:
    engine = create_engine(f"sqlite:///{db_path}")
    session_factory = sessionmaker(bind=engine)
    try:
        with session_factory() as session:
            return session.scalars(select(Run).order_by(Run.started_at)).all()
    finally:
        engine.dispose()


def test_block_randomization_seed_and_cross_corpus_cooldown_recorded(tmp_path: Path) -> None:
    db_path = tmp_path / "batch.db"
    sleeper = SleepRecorder()
    orchestrator = Orchestrator(
        OrchestratorConfig(
            db_path=db_path,
            archive_root=tmp_path / "archives",
            cooldown_delta_c=2,
            cooldown_max_wait_s=20,
            cooldown_poll_interval_s=5,
            sleep=sleeper,
            adapter_factory=_thermal_adapter_factory(temperature_c=40.0),
            device_thermal_reader=_sequenced_thermal([43.0, 42.0]),
        ),
    )
    try:
        summaries = asyncio.run(
            orchestrator.run_batch(
                [
                    CellSpec("kws", "mock", 1, "X"),
                    CellSpec("kws", "mock", 1, "N4"),
                ],
                seed=123,
            ),
        )
    finally:
        orchestrator.close()

    assert len(summaries) == 2
    runs = _runs(db_path)
    assert {run.extra["batch_seed"] for run in runs if run.extra is not None} == {123}
    cooldown_runs = [run for run in runs if run.extra.get("cooldown")]
    assert len(cooldown_runs) == 1
    assert cooldown_runs[0].extra["cooldown"]["mode"] == "device_temp"
    assert cooldown_runs[0].extra["cooldown"]["status"] == "cooled"
    assert cooldown_runs[0].extra["crosscorpus_cooldown_seconds"] == 5
    assert 5 in sleeper.calls


def test_cooldown_timeout_proceeds_and_flags_row(tmp_path: Path) -> None:
    db_path = tmp_path / "cool-timeout.db"
    sleeper = SleepRecorder()
    orchestrator = Orchestrator(
        OrchestratorConfig(
            db_path=db_path,
            archive_root=tmp_path / "archives",
            cooldown_delta_c=2,
            cooldown_max_wait_s=10,
            cooldown_poll_interval_s=5,
            sleep=sleeper,
            adapter_factory=_thermal_adapter_factory(temperature_c=40.0),
            device_thermal_reader=_sequenced_thermal([45.0]),
        ),
    )
    try:
        asyncio.run(
            orchestrator.run_batch(
                [
                    CellSpec("kws", "mock", 1, "X"),
                    CellSpec("kws", "mock", 1, "N4"),
                ],
                seed=123,
            ),
        )
    finally:
        orchestrator.close()

    [run] = [run for run in _runs(db_path) if run.extra.get("cooldown")]
    assert run.extra["cooldown"]["status"] == "timeout"
    assert run.extra["thermal_gate_flags"] == ["cooldown_timeout"]
    assert sleeper.calls == [5, 5]


def test_cooldown_falls_back_to_bounded_fixed_wait_for_sensorless_target(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "cool-fixed.db"
    sleeper = SleepRecorder()
    orchestrator = Orchestrator(
        OrchestratorConfig(
            db_path=db_path,
            archive_root=tmp_path / "archives",
            cooldown_max_wait_s=3,
            sleep=sleeper,
            adapter_factory=_thermal_adapter_factory(available=False),
        ),
    )
    try:
        asyncio.run(
            orchestrator.run_batch(
                [
                    CellSpec("kws", "mock", 1, "X"),
                    CellSpec("kws", "mock", 1, "N4"),
                ],
                seed=123,
            ),
        )
    finally:
        orchestrator.close()

    [run] = [run for run in _runs(db_path) if run.extra.get("cooldown")]
    assert run.extra["cooldown"]["mode"] == "fixed_wait"
    assert run.extra["cooldown"]["flags"] == ["cooldown_fallback_fixed"]
    assert run.extra["thermal_gate_flags"] == [
        "cooldown_fallback_fixed",
        "device_temp_start_unavailable",
        "device_temp_end_unavailable",
    ]
    assert sleeper.calls == [3]


def test_cold_start_equalization_uses_ambient_when_within_tolerance(tmp_path: Path) -> None:
    db_path = tmp_path / "cold.db"
    sleeper = SleepRecorder()
    orchestrator = Orchestrator(
        OrchestratorConfig(
            db_path=db_path,
            archive_root=tmp_path / "archives",
            session_ambient_c=21.5,
            coldstart_ambient_tol_c=1.5,
            ambient_reader=_sequenced_ambient([21.0]),
            sleep=sleeper,
        ),
    )
    try:
        asyncio.run(orchestrator.run_cell(CellSpec("kws", "mock", 1, "N1")))
    finally:
        orchestrator.close()

    [run] = _runs(db_path)
    assert run.extra["coldstart"]["status"] == "within_tolerance"
    assert run.extra["coldstart"]["baseline_c"] == 21.5
    assert run.extra["coldstart"]["final_c"] == 21.0
    assert sleeper.calls == []


def test_cold_start_drift_waits_then_proceeds_and_flags_row(tmp_path: Path) -> None:
    db_path = tmp_path / "cold-drift.db"
    sleeper = SleepRecorder()
    orchestrator = Orchestrator(
        OrchestratorConfig(
            db_path=db_path,
            archive_root=tmp_path / "archives",
            session_ambient_c=21.0,
            coldstart_ambient_tol_c=1.5,
            coldstart_max_wait_s=2,
            coldstart_poll_interval_s=1,
            ambient_reader=_sequenced_ambient([24.0]),
            sleep=sleeper,
        ),
    )
    try:
        asyncio.run(orchestrator.run_cell(CellSpec("kws", "mock", 1, "N1")))
    finally:
        orchestrator.close()

    [run] = _runs(db_path)
    assert run.extra["coldstart"]["status"] == "timeout"
    assert run.extra["coldstart"]["flags"] == ["coldstart_drift"]
    assert run.extra["thermal_gate_flags"] == [
        "coldstart_drift",
        "device_temp_start_unavailable",
        "device_temp_end_unavailable",
    ]
    assert sleeper.calls == [1, 1]


def test_accuracy_gate_happy_path_writes_lineage_to_run(tmp_path: Path) -> None:
    db_path = tmp_path / "n3-pass.db"
    lineage = _lineage(tmp_path, delta_pp=-1.0)
    orchestrator = Orchestrator(OrchestratorConfig(db_path=db_path, archive_root=tmp_path))
    try:
        asyncio.run(orchestrator.run_cell(CellSpec("kws", "mock", 1, "N3", lineage)))
    finally:
        orchestrator.close()

    [run] = _runs(db_path)
    assert run.corpus_tag == "N3"
    assert run.extra["model_lineage"]["accuracy_retention"]["delta_pp"] == -1.0


def test_accuracy_gate_rejection_writes_failure_not_run(tmp_path: Path) -> None:
    db_path = tmp_path / "n3-fail.db"
    lineage = _lineage(tmp_path, delta_pp=-3.0)
    orchestrator = Orchestrator(OrchestratorConfig(db_path=db_path, archive_root=tmp_path))
    try:
        with pytest.raises(ProtocolGateRejected, match="accuracy gate"):
            asyncio.run(orchestrator.run_cell(CellSpec("kws", "mock", 1, "N3", lineage)))
    finally:
        orchestrator.close()

    assert _runs(db_path) == []
    engine = create_engine(f"sqlite:///{db_path}")
    session_factory = sessionmaker(bind=engine)
    try:
        with session_factory() as session:
            [failure] = session.scalars(select(Failure)).all()
            assert failure.failure_mode == "accuracy_gate_rejected"
            assert failure.context["model_lineage"]["accuracy_retention"]["delta_pp"] == -3.0
    finally:
        engine.dispose()


def test_archive_path_populated_on_successful_run(tmp_path: Path) -> None:
    db_path = tmp_path / "archive.db"
    root = tmp_path / "archives"
    orchestrator = Orchestrator(OrchestratorConfig(db_path=db_path, archive_root=root))
    try:
        summary = asyncio.run(orchestrator.run_cell(CellSpec("kws", "mock", 1, "X")))
    finally:
        orchestrator.close()

    [run] = _runs(db_path)
    assert run.extra["archive_path"] == str(root / summary.run_id)
    assert (root / summary.run_id / "toolchain-manifest.json").exists()
