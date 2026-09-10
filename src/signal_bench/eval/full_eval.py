# SPDX-License-Identifier: Apache-2.0
"""Full KWS/AD MCU evaluation over a streamed-sample serial protocol.

The P3 MCU firmware uses ``RUN <task> <iterations>`` and cycles over samples
compiled into ``input_data.h``. That protocol is sufficient for energy matrix
runs, but it cannot evaluate a full test corpus. This module implements the
host side of the A01 protocol extension:

``EVAL <task_id> <sample_index> <base64-int8-input>``

Expected device responses are:

``PRED <sample_index> <duration_us> <class_id>`` for KWS.
``SCORE <sample_index> <duration_us> <reconstruction_error>`` for AD.
``ERR <code> <message>`` for device-side failures.

Old ``RUN``-only firmware answers the ``EVAL`` command with an ``ERR EINVAL``
frame; that is surfaced as ``FullEvalProtocolError`` so a subset run cannot be
mistaken for full evaluation.
"""

from __future__ import annotations

import asyncio
import base64
import csv
import datetime as dt
import hashlib
import importlib
import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self, cast

import numpy as np
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session, sessionmaker

from signal_bench import __version__
from signal_bench.ids import new_id
from signal_bench.schema import Failure, Result, Run, Target, Task

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

EVAL_TASKS = ("kws", "ad")
RESPONSE_FIELD_COUNT = 3


class FullEvalProtocolError(RuntimeError):
    """Raised when the attached MCU firmware does not implement full eval."""


@dataclass(frozen=True, slots=True)
class EvalRunConfig:
    """Configuration for one full evaluation run."""

    db_path: Path
    task: str
    target: str
    corpus: str
    data_path: Path
    serial_port: str | None = None
    baud_rate: int = 115_200
    runs_dir: Path = Path("runs")
    timeout_s: float = 5.0
    max_consecutive_failures: int = 20
    max_sample_retries: int = 3
    serial_chunk_bytes: int = 32
    serial_chunk_delay_s: float = 0.003


@dataclass(frozen=True, slots=True)
class SampleResult:
    """One streamed sample response from the MCU."""

    sample_index: int
    label: int
    duration_us: int
    prediction: int | None = None
    score: float | None = None
    source: str | None = None
    error: str | None = None
    retry_count: int = 0


async def run_full_eval(config: EvalRunConfig) -> dict[str, Any]:
    """Run a full streamed-sample evaluation and persist its summary."""
    if config.task not in EVAL_TASKS:
        msg = f"full MCU eval supports {', '.join(EVAL_TASKS)}, got {config.task!r}"
        raise ValueError(msg)

    inputs, labels, sources, metadata = load_eval_archive(config.data_path)
    serial_port = config.serial_port or _serial_port_from_db(config.db_path, config.target)
    if serial_port is None:
        msg = f"no serial port supplied and target {config.target!r} has no DB serial_port"
        raise ValueError(msg)

    session_factory = _session_factory(config.db_path)
    target, task = _ensure_target_task(session_factory, config.target, config.task)
    run_id = new_id()
    started_at = dt.datetime.now(dt.UTC)
    _create_eval_run(
        session_factory,
        run_id,
        target,
        task,
        config,
        started_at,
        metadata,
    )
    results_dir = config.runs_dir / run_id
    results_dir.mkdir(parents=True, exist_ok=True)

    client = StreamingMCUEvalClient(
        serial_port,
        config.baud_rate,
        config.timeout_s,
        config.serial_chunk_bytes,
        config.serial_chunk_delay_s,
    )
    rows: list[SampleResult] = []
    try:
        await client.open()
        consecutive_failures = 0
        for index, sample in enumerate(inputs):
            retry_count = 0
            try:
                while True:
                    try:
                        response = await client.evaluate(config.task, index, sample)
                        break
                    except FullEvalProtocolError as exc:
                        if retry_count < config.max_sample_retries and _is_retriable_sample_error(
                            exc
                        ):
                            retry_count += 1
                            continue
                        raise
            except (TimeoutError, FullEvalProtocolError, OSError) as exc:
                consecutive_failures += 1
                rows.append(
                    SampleResult(
                        sample_index=index,
                        label=int(labels[index]),
                        duration_us=0,
                        source=str(sources[index]) if sources is not None else None,
                        error=str(exc),
                        retry_count=retry_count,
                    ),
                )
                if consecutive_failures >= config.max_consecutive_failures:
                    msg = (
                        "aborting full eval after "
                        f"{consecutive_failures} consecutive sample failures"
                    )
                    raise FullEvalProtocolError(msg) from exc
                continue
            consecutive_failures = 0
            rows.append(
                SampleResult(
                    sample_index=index,
                    label=int(labels[index]),
                    duration_us=response["duration_us"],
                    prediction=response.get("prediction"),
                    score=response.get("score"),
                    source=str(sources[index]) if sources is not None else None,
                    retry_count=retry_count,
                ),
            )
    except Exception as exc:
        _mark_eval_failed(session_factory, run_id, str(exc))
        _write_failure(session_factory, target, task, config, str(exc), metadata)
        raise
    finally:
        await client.close()

    per_sample_csv = results_dir / "predictions.csv"
    _write_per_sample_csv(per_sample_csv, rows, config.task)
    metric_name, metric_value, detail = _compute_metric(config.task, rows)
    successful_rows = [row for row in rows if row.error is None]
    duration_ms = (
        statistics.fmean(row.duration_us for row in successful_rows) / 1000.0
        if successful_rows
        else 0.0
    )
    _write_eval_result(
        session_factory,
        run_id,
        metric_name,
        metric_value,
        duration_ms,
        len(successful_rows),
        per_sample_csv,
        detail,
        len(rows) - len(successful_rows),
    )
    _finish_eval_run(
        session_factory,
        run_id,
        len(rows),
        len(successful_rows),
        metric_name,
        metric_value,
    )
    return {
        "run_id": run_id,
        "target": config.target,
        "task": config.task,
        "corpus": config.corpus,
        "metric": metric_name,
        "value": metric_value,
        "n_samples": len(rows),
        "n_successful": len(successful_rows),
        "n_failed": len(rows) - len(successful_rows),
        "per_sample_csv": str(per_sample_csv),
        "metadata": metadata,
    }


def load_eval_archive(
    path: Path,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None, dict[str, Any]]:
    """Load a preprocessed full-eval ``.npz`` archive."""
    archive = np.load(path, allow_pickle=False)
    inputs = archive["inputs"]
    labels = archive["labels"].astype(np.int64, copy=False)
    sources = archive["sources"].astype(str, copy=False) if "sources" in archive.files else None
    raw_metadata = archive["metadata_json"].item() if "metadata_json" in archive.files else "{}"
    metadata = json.loads(str(raw_metadata))
    if inputs.dtype != np.int8:
        msg = f"{path} inputs must be int8 for MCU streaming, got {inputs.dtype}"
        raise ValueError(msg)
    if len(inputs) != len(labels):
        msg = f"{path} inputs/labels length mismatch: {len(inputs)} vs {len(labels)}"
        raise ValueError(msg)
    if sources is not None and len(sources) != len(inputs):
        msg = f"{path} sources length mismatch: {len(sources)} vs {len(inputs)}"
        raise ValueError(msg)
    return inputs, labels, sources, metadata


def compute_kws_top1(labels: list[int], predictions: list[int]) -> tuple[float, dict[str, float]]:
    """Return overall top-1 accuracy and per-class top-1 accuracy."""
    if len(labels) != len(predictions):
        msg = "labels and predictions must have the same length"
        raise ValueError(msg)
    if not labels:
        return float("nan"), {}

    correct = sum(
        int(label == prediction) for label, prediction in zip(labels, predictions, strict=True)
    )
    by_class: dict[int, list[int]] = {}
    for label, prediction in zip(labels, predictions, strict=True):
        by_class.setdefault(label, []).append(int(label == prediction))
    per_class = {str(label): statistics.fmean(values) for label, values in sorted(by_class.items())}
    return correct / len(labels), per_class


def compute_ad_clip_auroc(
    labels: list[int],
    scores: list[float],
    sources: list[str],
) -> float:
    """Return clip-level AUROC using mean patch score per source clip."""
    if not (len(labels) == len(scores) == len(sources)):
        msg = "labels, scores, and sources must have the same length"
        raise ValueError(msg)
    grouped_scores: dict[str, list[float]] = {}
    grouped_labels: dict[str, int] = {}
    for label, score, source in zip(labels, scores, sources, strict=True):
        grouped_scores.setdefault(source, []).append(score)
        grouped_labels.setdefault(source, label)
    ordered_sources = sorted(grouped_scores)
    clip_labels = [grouped_labels[source] for source in ordered_sources]
    clip_scores = [statistics.fmean(grouped_scores[source]) for source in ordered_sources]
    return _binary_auc(clip_labels, clip_scores)


class StreamingMCUEvalClient:
    """Async serial client for the A01 streamed-sample MCU eval protocol."""

    def __init__(
        self: Self,
        serial_port: str,
        baud_rate: int,
        timeout_s: float,
        chunk_bytes: int,
        chunk_delay_s: float,
    ) -> None:
        """Create the client with serial connection settings."""
        self._serial_port = serial_port
        self._baud_rate = baud_rate
        self._timeout_s = timeout_s
        self._chunk_bytes = chunk_bytes
        self._chunk_delay_s = chunk_delay_s
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def open(self: Self) -> None:
        """Open the USB-CDC serial connection."""
        serial_asyncio = importlib.import_module("serial_asyncio")
        open_serial_connection = cast(
            "Callable[..., Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]]",
            serial_asyncio.open_serial_connection,
        )
        self._reader, self._writer = await open_serial_connection(
            url=self._serial_port,
            baudrate=self._baud_rate,
        )

    async def evaluate(
        self: Self,
        task: str,
        sample_index: int,
        sample: np.ndarray,
    ) -> dict[str, Any]:
        """Send one sample and parse the device response."""
        writer = self._require_writer()
        payload = base64.b64encode(
            np.ascontiguousarray(sample).reshape(-1).tobytes(),
        ).decode("ascii")
        command = f"EVAL {task} {sample_index} {payload}\n".encode("ascii")
        chunk_bytes = max(1, self._chunk_bytes)
        for offset in range(0, len(command), chunk_bytes):
            writer.write(command[offset : offset + chunk_bytes])
            await asyncio.wait_for(writer.drain(), timeout=self._timeout_s)
            if self._chunk_delay_s > 0:
                await asyncio.sleep(self._chunk_delay_s)
        line = await self._read_line()
        tag, *fields = line.split(maxsplit=3)
        if tag == "ERR":
            message = fields[1] if len(fields) > 1 else ""
            raise FullEvalProtocolError(
                "MCU full-eval protocol rejected EVAL command. "
                f"Device returned ERR {fields[0] if fields else ''} {message}".strip(),
            )
        if task == "kws" and tag == "PRED" and len(fields) == RESPONSE_FIELD_COUNT:
            return {
                "sample_index": _expect_index(fields[0], sample_index),
                "duration_us": int(fields[1]),
                "prediction": int(fields[2]),
            }
        if task == "ad" and tag == "SCORE" and len(fields) == RESPONSE_FIELD_COUNT:
            return {
                "sample_index": _expect_index(fields[0], sample_index),
                "duration_us": int(fields[1]),
                "score": float(fields[2]),
            }
        msg = f"unexpected MCU eval response for {task}: {line}"
        raise FullEvalProtocolError(msg)

    async def close(self: Self) -> None:
        """Close the serial connection if open."""
        writer = self._writer
        self._reader = None
        self._writer = None
        if writer is not None:
            writer.close()
            await writer.wait_closed()

    async def _read_line(self: Self) -> str:
        reader = self._require_reader()
        line = await asyncio.wait_for(reader.readline(), timeout=self._timeout_s)
        if not line:
            msg = "MCU serial connection dropped during full eval"
            raise FullEvalProtocolError(msg)
        return line.decode("ascii").strip()

    def _require_reader(self: Self) -> asyncio.StreamReader:
        if self._reader is None:
            msg = "MCU eval serial reader is not open"
            raise FullEvalProtocolError(msg)
        return self._reader

    def _require_writer(self: Self) -> asyncio.StreamWriter:
        if self._writer is None:
            msg = "MCU eval serial writer is not open"
            raise FullEvalProtocolError(msg)
        return self._writer


def _compute_metric(task: str, rows: list[SampleResult]) -> tuple[str, float, dict[str, Any]]:
    valid_rows = [row for row in rows if row.error is None]
    labels = [row.label for row in valid_rows]
    if task == "kws":
        predictions = [int(row.prediction) for row in valid_rows if row.prediction is not None]
        value, per_class = compute_kws_top1(labels, predictions)
        return (
            "top1_accuracy",
            value,
            {
                "per_class_top1": per_class,
                "failed_samples": len(rows) - len(valid_rows),
                "retried_samples": sum(1 for row in rows if row.retry_count > 0),
            },
        )
    scores = [float(row.score) for row in valid_rows if row.score is not None]
    sources = [row.source or str(row.sample_index) for row in valid_rows]
    value = compute_ad_clip_auroc(labels, scores, sources)
    return (
        "clip_auroc",
        value,
        {
            "aggregation": "mean_patch_score_per_clip",
            "failed_samples": len(rows) - len(valid_rows),
            "retried_samples": sum(1 for row in rows if row.retry_count > 0),
        },
    )


def _is_retriable_sample_error(exc: FullEvalProtocolError) -> bool:
    """Return true for protocol errors caused by a truncated serial frame."""
    message = str(exc)
    return "ERR EBADLEN" in message or "decoded tensor length mismatch" in message


def _binary_auc(labels: list[int], scores: list[float]) -> float:
    positives = [score for label, score in zip(labels, scores, strict=True) if label == 1]
    negatives = [score for label, score in zip(labels, scores, strict=True) if label == 0]
    if not positives or not negatives:
        return float("nan")
    wins = 0.0
    for positive in positives:
        for negative in negatives:
            if positive > negative:
                wins += 1.0
            elif positive == negative:
                wins += 0.5
    return wins / (len(positives) * len(negatives))


def _session_factory(db_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{db_path}")
    return sessionmaker(bind=engine, expire_on_commit=False)


def _serial_port_from_db(db_path: Path, target_name: str) -> str | None:
    if not db_path.exists():
        return None
    session_factory = _session_factory(db_path)
    with session_factory() as session:
        target = session.scalar(
            select(Target).where(Target.name == target_name, Target.kind == "mcu")
        )
        if target is None or not target.extra:
            return None
        value = target.extra.get("serial_port")
        return str(value) if value else None


def _ensure_target_task(
    session_factory: sessionmaker[Session],
    target_name: str,
    task_name: str,
) -> tuple[Target, Task]:
    with session_factory() as session:
        target = session.scalar(
            select(Target).where(Target.name == target_name, Target.kind == "mcu")
        )
        if target is None:
            target = Target(target_id=new_id(), name=target_name, kind="mcu", cpu=target_name)
            session.add(target)
        task = session.scalar(
            select(Task).where(Task.name == task_name, Task.version == "full-eval-v1")
        )
        if task is None:
            task = Task(
                task_id=new_id(),
                name=task_name,
                version="full-eval-v1",
                family="keyword_spotting" if task_name == "kws" else "anomaly_detection",
            )
            session.add(task)
        session.commit()
        session.refresh(target)
        session.refresh(task)
        return target, task


def _create_eval_run(
    session_factory: sessionmaker[Session],
    run_id: str,
    target: Target,
    task: Task,
    config: EvalRunConfig,
    started_at: dt.datetime,
    metadata: dict[str, Any],
) -> None:
    with session_factory() as session:
        session.add(
            Run(
                run_id=run_id,
                target_id=target.target_id,
                task_id=task.task_id,
                started_at=started_at,
                status="running",
                corpus_tag="N3",
                warmup_count=0,
                measurement_count=0,
                signal_bench_version=__version__,
                runtime_name="TFLM",
                runtime_version="Chirale_TensorFLowLite-2.0.0",
                model_name=task.name,
                model_hash=str(metadata.get("model_sha256", "")) or None,
                quantization=str(metadata.get("quantization", "int8")),
                telemetry_partial=False,
                extra={
                    "action": "A01",
                    "eval_protocol": "streamed-sample-v1",
                    "corpus": config.corpus,
                    "data_path": str(config.data_path),
                    "metadata": metadata,
                },
            )
        )
        session.commit()


def _write_eval_result(
    session_factory: sessionmaker[Session],
    run_id: str,
    metric_name: str,
    metric_value: float,
    duration_ms: float,
    n_samples: int,
    per_sample_csv: Path,
    detail: dict[str, Any],
    failed_samples: int,
) -> None:
    with session_factory() as session:
        session.add(
            Result(
                result_id=new_id(),
                run_id=run_id,
                sequence=0,
                started_at=dt.datetime.now(dt.UTC),
                duration_ms=duration_ms,
                accuracy_value=metric_value,
                throughput_unit="samples",
                throughput_value=float(n_samples),
                extra={
                    "metric": metric_name,
                    "value": metric_value,
                    "n_samples": n_samples,
                    "failed_samples": failed_samples,
                    "per_sample_csv": str(per_sample_csv),
                    **detail,
                },
            )
        )
        session.commit()


def _finish_eval_run(
    session_factory: sessionmaker[Session],
    run_id: str,
    n_samples: int,
    n_successful: int,
    metric_name: str,
    metric_value: float,
) -> None:
    with session_factory() as session:
        run = session.get(Run, run_id)
        extra = dict(run.extra or {}) if run else {}
        extra["metric"] = metric_name
        extra["value"] = metric_value
        extra["n_samples"] = n_samples
        extra["n_successful"] = n_successful
        extra["n_failed"] = n_samples - n_successful
        session.execute(
            update(Run)
            .where(Run.run_id == run_id)
            .values(
                finished_at=dt.datetime.now(dt.UTC),
                status="completed",
                measurement_count=n_samples,
                extra=extra,
            )
        )
        session.commit()


def _mark_eval_failed(session_factory: sessionmaker[Session], run_id: str, error: str) -> None:
    with session_factory() as session:
        run = session.get(Run, run_id)
        extra = dict(run.extra or {}) if run else {}
        extra["error"] = error
        session.execute(
            update(Run)
            .where(Run.run_id == run_id)
            .values(finished_at=dt.datetime.now(dt.UTC), status="failed", extra=extra)
        )
        session.commit()


def _write_failure(
    session_factory: sessionmaker[Session],
    target: Target,
    task: Task,
    config: EvalRunConfig,
    signature: str,
    metadata: dict[str, Any],
) -> None:
    with session_factory() as session:
        session.add(
            Failure(
                failure_id=new_id(),
                target_id=target.target_id,
                task_id=task.task_id,
                model_name=config.task,
                model_version=str(metadata.get("model_sha256", "unknown")),
                corpus_tag="N3",
                failure_mode="toolchain_version_skew",
                diagnostic_signature=signature[-1000:],
                toolchain_versions={"signal_bench": __version__},
                context={
                    "action": "A01",
                    "eval_protocol": "streamed-sample-v1",
                    "data_path": str(config.data_path),
                },
            )
        )
        session.commit()


def _write_per_sample_csv(path: Path, rows: list[SampleResult], task: str) -> None:
    fieldnames = ["sample_index", "label", "duration_us", "source", "retry_count", "error"]
    fieldnames.append("prediction" if task == "kws" else "score")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            payload = {
                "sample_index": row.sample_index,
                "label": row.label,
                "duration_us": row.duration_us,
                "source": row.source or "",
                "retry_count": row.retry_count,
                "error": row.error or "",
            }
            if task == "kws":
                payload["prediction"] = row.prediction
            else:
                payload["score"] = row.score
            writer.writerow(payload)


def _expect_index(raw: str, expected: int) -> int:
    value = int(raw)
    if value != expected:
        msg = f"MCU response sample index {value} did not match requested {expected}"
        raise FullEvalProtocolError(msg)
    return value


def sha256_file(path: Path) -> str:
    """Return the SHA256 digest for ``path``."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
