# SPDX-License-Identifier: Apache-2.0
"""Library-level benchmark orchestration with Phase 5 protocol gates."""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import inspect
import json
import random
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from signal_bench import __version__
from signal_bench.adapters import Adapter, InferenceResult, MockAdapter, ThermalReading
from signal_bench.adapters.exceptions import AdapterError
from signal_bench.archive import (
    DEFAULT_ARCHIVE_ROOT,
    copy_lineage_file,
    create_archive_dir,
    write_toolchain_manifest,
)
from signal_bench.ids import new_id
from signal_bench.protocols import load_n3_floors
from signal_bench.schema import (
    ACTIVE_CORPUS_TAGS,
    FAILURE_MODES,
    Failure,
    Result,
    Run,
    Target,
    Task,
)
from signal_bench.tasks import get_task
from signal_bench.telemetry.exceptions import SourceDataError, SourceStartError
from signal_bench.telemetry.sources.bme280 import Bme280Source

if TYPE_CHECKING:
    from pathlib import Path

    from signal_bench.adapters.mcu.task import TaskSpec

SleepFn = Callable[[float], Awaitable[None]]
AdapterFactory = Callable[[str], Adapter]
AmbientReader = Callable[[], float | None | Awaitable[float | None]]
DeviceThermalReader = Callable[[str], ThermalReading | Awaitable[ThermalReading]]

EXIT_GATE_REJECTED = 3
DEFAULT_THERMAL_POLL_INTERVAL_S = 5.0


class ProtocolError(ValueError):
    """Raised when protocol configuration is invalid."""


class ProtocolGateRejected(RuntimeError):  # noqa: N818 - public protocol wording.
    """Raised when a protocol gate rejects a cell before measurement."""


class ProtocolFailure(RuntimeError):  # noqa: N818 - public protocol wording.
    """Exception carrying a first-class failure-mode record."""

    def __init__(
        self,
        failure_mode: str,
        diagnostic_signature: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Create a failure carrying a protocol failure mode."""
        super().__init__(diagnostic_signature)
        if failure_mode not in FAILURE_MODES:
            msg = f"Unsupported failure mode: {failure_mode}"
            raise ValueError(msg)
        self.failure_mode = failure_mode
        self.diagnostic_signature = diagnostic_signature
        self.context = context


@dataclass(frozen=True, slots=True)
class CellSpec:
    """One planned benchmark cell."""

    task_name: str
    target_name: str
    iterations: int
    corpus_tag: str
    model_lineage_path: Path | None = None


@dataclass(slots=True)
class OrchestratorConfig:
    """Runtime configuration for benchmark orchestration."""

    db_path: Path
    archive_root: Path = DEFAULT_ARCHIVE_ROOT
    cooldown_delta_c: float = 2.0
    cooldown_max_wait_s: float = 120.0
    coldstart_ambient_tol_c: float = 1.5
    coldstart_max_wait_s: float = 120.0
    cooldown_poll_interval_s: float = DEFAULT_THERMAL_POLL_INTERVAL_S
    coldstart_poll_interval_s: float = DEFAULT_THERMAL_POLL_INTERVAL_S
    sleep: SleepFn = asyncio.sleep
    toolchain_versions: dict[str, Any] = field(
        default_factory=lambda: {"signal_bench": __version__},
    )
    session_ambient_c: float | None = None
    adapter_factory: AdapterFactory | None = None
    ambient_reader: AmbientReader | None = None
    device_thermal_reader: DeviceThermalReader | None = None


@dataclass(frozen=True, slots=True)
class ThermalGateOutcome:
    """Outcome recorded for a thermal protocol gate."""

    mode: str
    status: str
    waited_s: float
    baseline_c: float | None = None
    final_c: float | None = None
    flags: tuple[str, ...] = ()

    def as_extra(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "mode": self.mode,
            "status": self.status,
            "waited_s": self.waited_s,
            "baseline_c": self.baseline_c,
            "final_c": self.final_c,
            "flags": list(self.flags),
        }


@dataclass(frozen=True, slots=True)
class RunSummary:
    """Summary returned to CLI callers after a successful run."""

    run_id: str
    count: int
    total_duration_us: int
    avg_duration_us: float
    output_hash: str
    target_name: str


class Orchestrator:
    """Own benchmark cell lifecycle and Phase 5 protocol enforcement."""

    def __init__(self, config: OrchestratorConfig) -> None:
        """Create an orchestrator bound to one SQLite database."""
        self.config = config
        self._ensure_database(config.db_path)
        self._engine = create_engine(f"sqlite:///{config.db_path}")
        self._session_factory = sessionmaker(bind=self._engine)
        self.last_run_id: str | None = None
        self.last_failure_id: str | None = None
        self._last_device_thermal_start: dict[str, ThermalReading] = {}

    def close(self) -> None:
        """Release database resources."""
        self._engine.dispose()

    async def run_cell(
        self,
        cell: CellSpec,
        *,
        protocol_extra: dict[str, Any] | None = None,
    ) -> RunSummary:
        """Run one benchmark cell and persist a successful run row."""
        self._validate_cell(cell)
        task = get_task(cell.task_name)
        adapter = self._build_adapter(cell.target_name)
        target, task_row = self._ensure_target_task(adapter, task)
        lineage = self._load_lineage(cell)
        extra = self._base_extra(cell, task)
        if protocol_extra is not None:
            extra.update(protocol_extra)

        if cell.corpus_tag == "N3":
            self._apply_n3_gate(cell, task, target, task_row, lineage, extra)

        if cell.corpus_tag == "N1":
            await self._apply_cold_start(extra)

        run_id = new_id()
        archive_path = create_archive_dir(run_id, root=self.config.archive_root)
        extra["archive_path"] = str(archive_path)
        if self.config.session_ambient_c is not None:
            extra["session_ambient_c"] = self.config.session_ambient_c
        write_toolchain_manifest(
            run_id,
            self.config.toolchain_versions,
            root=self.config.archive_root,
        )
        if cell.model_lineage_path is not None:
            copy_lineage_file(run_id, cell.model_lineage_path, root=self.config.archive_root)

        results: list[InferenceResult] = []
        try:
            await adapter.prepare(run_id)
            start_thermal = await self._read_prepared_device_thermal(adapter)
            self._record_device_thermal(extra, "start", start_thermal)
            self._last_device_thermal_start[cell.target_name] = start_thermal
            await adapter.warmup()
            results.extend([result async for result in adapter.measure(task, cell.iterations)])
            end_thermal = await self._read_prepared_device_thermal(adapter)
            self._record_device_thermal(extra, "end", end_thermal)
            run = self._write_successful_run(
                run_id=run_id,
                target=target,
                task=task_row,
                cell=cell,
                results=results,
                task_metadata=task.metadata,
                model_path=str(task.model_path),
                extra=extra,
            )
            self.last_run_id = run.run_id
        except ProtocolFailure as exc:
            failure = self._write_failure(
                target=target,
                task=task_row,
                cell=cell,
                task_model_hash=str(task.metadata["model_hash"]),
                failure_mode=exc.failure_mode,
                diagnostic_signature=exc.diagnostic_signature,
                context=exc.context,
            )
            self.last_failure_id = failure.failure_id
            raise
        except MemoryError as exc:
            failure = self._write_failure(
                target=target,
                task=task_row,
                cell=cell,
                task_model_hash=str(task.metadata["model_hash"]),
                failure_mode="activation_memory_overflow",
                diagnostic_signature=str(exc) or "activation memory overflow",
                context=None,
            )
            self.last_failure_id = failure.failure_id
            failure_mode = "activation_memory_overflow"
            raise ProtocolFailure(failure_mode, failure.diagnostic_signature) from exc
        finally:
            await adapter.teardown()

        return self._summarize_results(run_id, results, adapter.config.target_id)

    async def run_batch(
        self,
        cells: Sequence[CellSpec],
        *,
        seed: int | None = None,
    ) -> list[RunSummary]:
        """Run a block-randomized batch of cells."""
        batch_seed = seed if seed is not None else random.SystemRandom().randrange(2**32)
        randomized = list(cells)
        random.Random(batch_seed).shuffle(randomized)  # noqa: S311 - protocol randomization.

        summaries: list[RunSummary] = []
        previous: CellSpec | None = None
        for cell in randomized:
            cell_extra: dict[str, Any] = {"batch_seed": batch_seed}
            if previous is not None and previous.target_name == cell.target_name:
                cooldown = await self._apply_cooldown(
                    previous,
                    cell,
                )
                cell_extra["crosscorpus_cooldown_seconds"] = cooldown.waited_s
                cell_extra["cooldown"] = cooldown.as_extra()
                _append_thermal_gate_flags(cell_extra, cooldown.flags)
            summary = await self.run_cell(cell, protocol_extra=cell_extra)
            summaries.append(summary)
            previous = cell
        return summaries

    @staticmethod
    def _ensure_database(db_path: Path) -> None:
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
        command.upgrade(cfg, "head")

    def _build_adapter(self, target_name: str) -> Adapter:
        if self.config.adapter_factory is not None:
            return self.config.adapter_factory(target_name)
        if target_name == "mock":
            return MockAdapter()
        msg = f"Unknown target: {target_name}. Available targets: mock"
        raise ProtocolError(msg)

    @staticmethod
    def _validate_cell(cell: CellSpec) -> None:
        if cell.iterations <= 0:
            msg = "--runs must be a positive integer."
            raise ProtocolError(msg)
        if cell.corpus_tag not in ACTIVE_CORPUS_TAGS:
            choices = ", ".join(ACTIVE_CORPUS_TAGS)
            msg = f"--corpus must be one of: {choices}"
            raise ProtocolError(msg)
        if cell.corpus_tag == "N3" and cell.model_lineage_path is None:
            msg = "--model-lineage is required when --corpus N3."
            raise ProtocolError(msg)
        if cell.corpus_tag != "N3" and cell.model_lineage_path is not None:
            msg = "--model-lineage is only valid when --corpus N3."
            raise ProtocolError(msg)

    def _ensure_target_task(self, adapter: Adapter, task: TaskSpec) -> tuple[Target, Task]:
        with self._session_factory() as session:
            target = session.scalar(
                select(Target).where(
                    Target.name == adapter.config.target_id,
                    Target.kind == "mock",
                ),
            )
            if target is None:
                target = Target(target_id=new_id(), name=adapter.config.target_id, kind="mock")
                session.add(target)

            task_row = session.scalar(
                select(Task).where(Task.name == task.task_id, Task.version == "mlperf-tiny-v1.3"),
            )
            if task_row is None:
                task_row = Task(
                    task_id=new_id(),
                    name=task.task_id,
                    version="mlperf-tiny-v1.3",
                    family=str(task.metadata["family"]),
                    yaml_path="models/reference/manifest.yaml",
                    yaml_hash=str(task.metadata["model_hash"]),
                )
                session.add(task_row)
            session.commit()
            session.refresh(target)
            session.refresh(task_row)
            return target, task_row

    @staticmethod
    def _base_extra(cell: CellSpec, task: TaskSpec) -> dict[str, Any]:
        return {
            "kind": "benchmark",
            "target": cell.target_name,
            "task_family": task.metadata["family"],
            "iterations": cell.iterations,
            "model_path": str(task.model_path),
        }

    @staticmethod
    def _load_lineage(cell: CellSpec) -> dict[str, Any] | None:
        if cell.model_lineage_path is None:
            return None
        try:
            payload = json.loads(cell.model_lineage_path.read_text(encoding="utf-8"))
        except OSError as exc:
            msg = f"Could not read --model-lineage file: {exc}"
            raise ProtocolError(msg) from exc
        except json.JSONDecodeError as exc:
            msg = f"Malformed --model-lineage JSON: {exc}"
            raise ProtocolError(msg) from exc
        _validate_lineage_payload(payload)
        return dict(payload)

    @staticmethod
    def _lineage_passes_floor(task_id: str, lineage: dict[str, Any]) -> bool:
        floors = load_n3_floors()
        floor = floors.get(task_id)
        if not isinstance(floor, dict):
            msg = f"No N3 accuracy floor configured for task {task_id}"
            raise ProtocolError(msg)

        retention = lineage["accuracy_retention"]
        metric = retention["metric"]
        if metric != floor["metric"]:
            msg = f"Lineage metric {metric!r} does not match floor metric {floor['metric']!r}"
            raise ProtocolError(msg)

        if "floor_delta_pp" in floor:
            delta_pp = retention.get("delta_pp")
            if not isinstance(delta_pp, int | float):
                msg = "Lineage accuracy_retention.delta_pp must be numeric"
                raise ProtocolError(msg)
            if delta_pp < float(floor["floor_delta_pp"]):
                return False
            floor_sparsity = floor.get("floor_sparsity")
            if floor_sparsity is not None:
                sparsity = lineage.get("prep_params", {}).get("sparsity")
                if not isinstance(sparsity, int | float) or sparsity < float(floor_sparsity):
                    return False
            return True

        ratio = retention.get("ratio")
        if not isinstance(ratio, int | float):
            msg = "Lineage accuracy_retention.ratio must be numeric"
            raise ProtocolError(msg)
        return ratio >= float(floor["floor_ratio"])

    def _apply_n3_gate(  # noqa: PLR0913 - keeps N3 persistence context explicit.
        self,
        cell: CellSpec,
        task: TaskSpec,
        target: Target,
        task_row: Task,
        lineage: dict[str, Any] | None,
        extra: dict[str, Any],
    ) -> None:
        if lineage is None:
            msg = "--model-lineage is required when --corpus N3."
            raise ProtocolError(msg)
        if self._lineage_passes_floor(task.task_id, lineage):
            extra["model_lineage"] = lineage
            return
        failure = self._write_failure(
            target=target,
            task=task_row,
            cell=cell,
            task_model_hash=str(task.metadata["model_hash"]),
            failure_mode="accuracy_gate_rejected",
            diagnostic_signature="accuracy retention below Phase 5 N3 floor",
            context={"model_lineage": lineage},
        )
        self.last_failure_id = failure.failure_id
        msg = f"N3 accuracy gate rejected model lineage for task {task.task_id}"
        raise ProtocolGateRejected(msg)

    async def _apply_cold_start(self, extra: dict[str, Any]) -> None:
        outcome = await self._wait_for_ambient_cold_start()
        extra["coldstart"] = outcome.as_extra()
        extra["cold_start_wait_s"] = outcome.waited_s
        _append_thermal_gate_flags(extra, outcome.flags)

    async def _apply_cooldown(
        self,
        previous: CellSpec,
        current: CellSpec,
    ) -> ThermalGateOutcome:
        if previous.corpus_tag == current.corpus_tag:
            return ThermalGateOutcome(mode="not_required", status="skipped", waited_s=0.0)

        baseline = self._last_device_thermal_start.get(previous.target_name)
        if baseline is not None and baseline.available and baseline.temperature_c is not None:
            return await self._wait_for_device_cooldown(
                target_name=current.target_name,
                baseline_c=baseline.temperature_c,
            )
        return await self._apply_cooldown_fallback()

    async def _read_prepared_device_thermal(self, adapter: Adapter) -> ThermalReading:
        try:
            return await adapter.read_thermal()
        except AdapterError:
            return ThermalReading(available=False)

    @staticmethod
    def _record_device_thermal(
        extra: dict[str, Any],
        position: str,
        reading: ThermalReading,
    ) -> None:
        thermal = extra.setdefault("device_thermal", {})
        if not reading.available or reading.temperature_c is None:
            thermal[position] = {"available": False}
            _append_thermal_gate_flags(extra, f"device_temp_{position}_unavailable")
            return
        thermal[position] = {
            "available": True,
            "temperature_c": reading.temperature_c,
            "sensor": reading.sensor,
            "timestamp": reading.timestamp.isoformat() if reading.timestamp is not None else None,
        }
        extra[f"temp_{position}_c"] = reading.temperature_c

    async def _wait_for_device_cooldown(
        self,
        *,
        target_name: str,
        baseline_c: float,
    ) -> ThermalGateOutcome:
        waited_s = 0.0
        final_c: float | None = None
        while waited_s <= self.config.cooldown_max_wait_s:
            reading = await self._read_device_thermal_for_gate(target_name)
            if reading.available and reading.temperature_c is not None:
                final_c = reading.temperature_c
                if final_c <= baseline_c + self.config.cooldown_delta_c:
                    return ThermalGateOutcome(
                        mode="device_temp",
                        status="cooled",
                        waited_s=waited_s,
                        baseline_c=baseline_c,
                        final_c=final_c,
                    )
            else:
                return await self._apply_cooldown_fallback()

            if waited_s >= self.config.cooldown_max_wait_s:
                break
            sleep_s = min(
                self.config.cooldown_poll_interval_s,
                self.config.cooldown_max_wait_s - waited_s,
            )
            await self.config.sleep(sleep_s)
            waited_s += sleep_s

        return ThermalGateOutcome(
            mode="device_temp",
            status="timeout",
            waited_s=waited_s,
            baseline_c=baseline_c,
            final_c=final_c,
            flags=("cooldown_timeout",),
        )

    async def _read_device_thermal_for_gate(self, target_name: str) -> ThermalReading:
        if self.config.device_thermal_reader is not None:
            reading = self.config.device_thermal_reader(target_name)
            if inspect.isawaitable(reading):
                return await reading
            return reading

        adapter = self._build_adapter(target_name)
        run_id = f"thermal-gate-{new_id()}"
        try:
            await adapter.prepare(run_id)
            return await self._read_prepared_device_thermal(adapter)
        except AdapterError:
            return ThermalReading(available=False)
        finally:
            with suppress(AdapterError):
                await adapter.teardown()

    async def _apply_cooldown_fallback(self) -> ThermalGateOutcome:
        if self.config.session_ambient_c is not None:
            ambient = await self._read_ambient_temperature()
        else:
            ambient = None
        if ambient is not None and self.config.session_ambient_c is not None:
            return await self._wait_for_ambient_cooldown(self.config.session_ambient_c, ambient)

        wait_s = self.config.cooldown_max_wait_s
        await self.config.sleep(wait_s)
        return ThermalGateOutcome(
            mode="fixed_wait",
            status="fallback",
            waited_s=wait_s,
            flags=("cooldown_fallback_fixed",),
        )

    async def _wait_for_ambient_cooldown(
        self,
        baseline_c: float,
        initial_c: float,
    ) -> ThermalGateOutcome:
        waited_s = 0.0
        final_c = initial_c
        while waited_s <= self.config.cooldown_max_wait_s:
            if abs(final_c - baseline_c) <= self.config.cooldown_delta_c:
                return ThermalGateOutcome(
                    mode="ambient_relative",
                    status="cooled",
                    waited_s=waited_s,
                    baseline_c=baseline_c,
                    final_c=final_c,
                    flags=("cooldown_fallback_ambient",),
                )
            if waited_s >= self.config.cooldown_max_wait_s:
                break
            sleep_s = min(
                self.config.cooldown_poll_interval_s,
                self.config.cooldown_max_wait_s - waited_s,
            )
            await self.config.sleep(sleep_s)
            waited_s += sleep_s
            next_ambient = await self._read_ambient_temperature()
            if next_ambient is not None:
                final_c = next_ambient

        return ThermalGateOutcome(
            mode="ambient_relative",
            status="timeout",
            waited_s=waited_s,
            baseline_c=baseline_c,
            final_c=final_c,
            flags=("cooldown_fallback_ambient", "cooldown_timeout"),
        )

    async def _wait_for_ambient_cold_start(self) -> ThermalGateOutcome:
        baseline_c = self.config.session_ambient_c
        initial_c = await self._read_ambient_temperature()
        if initial_c is None:
            return ThermalGateOutcome(
                mode="ambient_bme280",
                status="unavailable",
                waited_s=0.0,
                baseline_c=baseline_c,
                flags=("coldstart_ambient_unavailable",),
            )

        if baseline_c is None:
            return ThermalGateOutcome(
                mode="ambient_bme280",
                status="baseline_established",
                waited_s=0.0,
                baseline_c=initial_c,
                final_c=initial_c,
                flags=("coldstart_baseline_from_first_read",),
            )

        waited_s = 0.0
        final_c = initial_c
        while waited_s <= self.config.coldstart_max_wait_s:
            if abs(final_c - baseline_c) <= self.config.coldstart_ambient_tol_c:
                return ThermalGateOutcome(
                    mode="ambient_bme280",
                    status="within_tolerance",
                    waited_s=waited_s,
                    baseline_c=baseline_c,
                    final_c=final_c,
                )
            if waited_s >= self.config.coldstart_max_wait_s:
                break
            sleep_s = min(
                self.config.coldstart_poll_interval_s,
                self.config.coldstart_max_wait_s - waited_s,
            )
            await self.config.sleep(sleep_s)
            waited_s += sleep_s
            next_ambient = await self._read_ambient_temperature()
            if next_ambient is not None:
                final_c = next_ambient

        return ThermalGateOutcome(
            mode="ambient_bme280",
            status="timeout",
            waited_s=waited_s,
            baseline_c=baseline_c,
            final_c=final_c,
            flags=("coldstart_drift",),
        )

    async def _read_ambient_temperature(self) -> float | None:
        if self.config.ambient_reader is not None:
            value = self.config.ambient_reader()
            if inspect.isawaitable(value):
                resolved = await value
                return float(resolved) if resolved is not None else None
            return float(value) if value is not None else None

        source = Bme280Source()
        try:
            await source.start()
            for sample in source.sample():
                if sample.metric == "temperature":
                    return sample.value
        except (ImportError, OSError, RuntimeError, SourceDataError, SourceStartError, ValueError):
            return None
        finally:
            await source.stop()
        return None

    def _write_successful_run(  # noqa: PLR0913 - explicit persistence boundary.
        self,
        *,
        run_id: str,
        target: Target,
        task: Task,
        cell: CellSpec,
        results: Sequence[InferenceResult],
        task_metadata: dict[str, Any],
        model_path: str,
        extra: dict[str, Any],
    ) -> Run:
        with self._session_factory() as session:
            run = Run(
                run_id=run_id,
                target_id=target.target_id,
                task_id=task.task_id,
                started_at=dt.datetime.now(dt.UTC),
                finished_at=dt.datetime.now(dt.UTC),
                status="completed",
                corpus_tag=cell.corpus_tag,
                warmup_count=0,
                measurement_count=cell.iterations,
                signal_bench_version=__version__,
                runtime_name="signal-bench-cli",
                runtime_version=__version__,
                model_name=cell.task_name,
                model_hash=str(task_metadata["model_hash"]),
                quantization=str(task_metadata["quantization"]),
                extra={**extra, "model_path": model_path},
            )
            session.add(run)
            session.flush()
            for result in results:
                duration_ms = result.duration_us / 1000
                session.add(
                    Result(
                        result_id=new_id(),
                        run_id=run_id,
                        sequence=result.iter_id,
                        started_at=result.timestamp,
                        duration_ms=duration_ms,
                        throughput_unit="inferences/s",
                        throughput_value=1000 / duration_ms if duration_ms > 0 else None,
                        extra={
                            "output": result.output,
                            "error": result.error,
                        },
                    ),
                )
            session.commit()
            session.refresh(run)
            return run

    def _write_failure(  # noqa: PLR0913 - mirrors failures table columns.
        self,
        *,
        target: Target,
        task: Task,
        cell: CellSpec,
        task_model_hash: str,
        failure_mode: str,
        diagnostic_signature: str,
        context: dict[str, Any] | None,
    ) -> Failure:
        if failure_mode not in FAILURE_MODES:
            msg = f"Unsupported failure mode: {failure_mode}"
            raise ProtocolError(msg)
        with self._session_factory() as session:
            failure = Failure(
                failure_id=new_id(),
                attempted_at=dt.datetime.now(dt.UTC),
                target_id=target.target_id,
                task_id=task.task_id,
                model_name=cell.task_name,
                model_version=task_model_hash,
                corpus_tag=cell.corpus_tag,
                failure_mode=failure_mode,
                diagnostic_signature=diagnostic_signature,
                toolchain_versions=self.config.toolchain_versions,
                context=context,
                extra={"target": cell.target_name, "iterations": cell.iterations},
            )
            session.add(failure)
            session.commit()
            session.refresh(failure)
            return failure

    @staticmethod
    def _summarize_results(
        run_id: str,
        results: Sequence[InferenceResult],
        target_name: str,
    ) -> RunSummary:
        total_duration_us = sum(result.duration_us for result in results)
        output_hash = hashlib.sha256(
            json.dumps([result.output for result in results], sort_keys=True).encode(),
        ).hexdigest()[:16]
        return RunSummary(
            run_id=run_id,
            count=len(results),
            total_duration_us=total_duration_us,
            avg_duration_us=total_duration_us / len(results) if results else 0,
            output_hash=output_hash,
            target_name=target_name,
        )


def _append_thermal_gate_flags(extra: dict[str, Any], flags: Sequence[str] | str) -> None:
    if isinstance(flags, str):
        flags = (flags,)
    if not flags:
        return
    existing = extra.setdefault("thermal_gate_flags", [])
    for flag in flags:
        if flag not in existing:
            existing.append(flag)


def _validate_lineage_payload(payload: object) -> None:
    if not isinstance(payload, dict):
        msg = "model lineage payload must be a JSON object"
        raise ProtocolError(msg)
    required = {
        "derived_from",
        "prep_method",
        "prep_params",
        "accuracy_retention",
        "prep_pipeline_uri",
    }
    missing = sorted(required - payload.keys())
    if missing:
        msg = "model lineage payload missing required keys: {}".format(", ".join(missing))
        raise ProtocolError(msg)
    if not isinstance(payload["prep_params"], dict):
        msg = "model lineage prep_params must be an object"
        raise ProtocolError(msg)
    retention = payload["accuracy_retention"]
    if not isinstance(retention, dict):
        msg = "model lineage accuracy_retention must be an object"
        raise ProtocolError(msg)
    if retention.get("metric") not in {"top1", "auroc"}:
        msg = "model lineage accuracy_retention.metric must be top1 or auroc"
        raise ProtocolError(msg)
