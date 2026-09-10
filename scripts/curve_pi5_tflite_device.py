# SPDX-License-Identifier: Apache-2.0
"""Pi-side LiteRT inference loop for Curve Fan-Out Brief A."""


from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.metadata
import json
import platform
import time
from pathlib import Path
from typing import Any

import numpy as np
from ai_edge_litert.interpreter import Interpreter


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--input-data", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument(
        "--task-family",
        choices=["classification", "keyword_spotting", "anomaly_detection"],
        required=True,
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--duration-s", type=float, default=35.0)
    parser.add_argument("--warmup", type=int, default=8)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--results-jsonl", type=Path, required=True)
    args = parser.parse_args()

    archive = np.load(args.input_data, allow_pickle=False)
    inputs = archive["inputs"].astype(np.float32, copy=False)
    labels = archive["labels"].astype(np.int64, copy=False) if "labels" in archive else None
    sources = archive["sources"].astype(str, copy=False) if "sources" in archive else None

    interpreter = Interpreter(model_path=str(args.model), num_threads=args.threads)
    interpreter.allocate_tensors()
    input_detail = interpreter.get_input_details()[0]
    output_detail = interpreter.get_output_details()[0]
    interpreter.resize_tensor_input(input_detail["index"], [1, *inputs.shape[1:]], strict=False)
    interpreter.allocate_tensors()
    input_detail = interpreter.get_input_details()[0]
    output_detail = interpreter.get_output_details()[0]

    for index in range(min(args.warmup, len(inputs))):
        interpreter.set_tensor(input_detail["index"], inputs[index : index + 1])
        interpreter.invoke()

    metadata = {
        "run_id": args.run_id,
        "task_id": args.task_id,
        "task_family": args.task_family,
        "runtime_name": "ai-edge-litert",
        "runtime_version": importlib.metadata.version("ai-edge-litert"),
        "execution_provider": "CPU/XNNPACK",
        "python": platform.python_version(),
        "kernel": platform.release(),
        "machine": platform.machine(),
        "threads": args.threads,
        "batch_size": 1,
        "model": str(args.model),
        "model_sha256": _sha256(args.model),
        "input_data": str(args.input_data),
        "input_shape": list(inputs.shape[1:]),
        "input_count": int(inputs.shape[0]),
        "input_dtype": str(inputs.dtype),
        "tflite_input": _tensor_detail(input_detail),
        "tflite_output": _tensor_detail(output_detail),
    }
    print(json.dumps({"type": "metadata", "metadata": metadata}), flush=True)

    args.results_jsonl.parent.mkdir(parents=True, exist_ok=True)
    measurement_start = time.perf_counter()
    next_heartbeat = measurement_start + 5.0
    sequence = 0
    with args.results_jsonl.open("w", encoding="utf-8") as handle:
        while time.perf_counter() - measurement_start < args.duration_s:
            data_index = sequence % len(inputs)
            sample = inputs[data_index : data_index + 1]
            timestamp = dt.datetime.now(dt.UTC).isoformat()
            error = None
            output: dict[str, Any]
            try:
                t0 = time.perf_counter_ns()
                interpreter.set_tensor(input_detail["index"], sample)
                interpreter.invoke()
                raw_output = interpreter.get_tensor(output_detail["index"])
                duration_us = int((time.perf_counter_ns() - t0) / 1000)
                output = _summarize_output(
                    raw_output,
                    sample,
                    family=args.task_family,
                    label=int(labels[data_index]) if labels is not None else None,
                    source=str(sources[data_index]) if sources is not None else None,
                )
            except Exception as exc:
                duration_us = 0
                output = {}
                error = str(exc)
            handle.write(
                json.dumps(
                    {
                        "iter_id": sequence,
                        "data_index": data_index,
                        "timestamp": timestamp,
                        "duration_us": duration_us,
                        "output": output,
                        "error": error,
                    },
                    sort_keys=True,
                )
                + "\n",
            )
            sequence += 1
            now = time.perf_counter()
            if now >= next_heartbeat:
                print(
                    json.dumps(
                        {
                            "type": "heartbeat",
                            "iterations": sequence,
                            "elapsed_s": now - measurement_start,
                        },
                    ),
                    flush=True,
                )
                next_heartbeat = now + 5.0

    print(json.dumps({"type": "measurement_complete", "iterations": sequence}), flush=True)
    return 0


def _summarize_output(
    raw_output: np.ndarray,
    sample: np.ndarray,
    *,
    family: str,
    label: int | None,
    source: str | None,
) -> dict[str, Any]:
    values = raw_output.reshape(-1).astype(np.float32)
    if family in {"classification", "keyword_spotting"}:
        argmax = int(np.argmax(values))
        return {
            "argmax": argmax,
            "confidence": float(values[argmax]),
            "label": label,
            "unique_argmax_key": argmax,
        }
    sample_values = sample.reshape(-1).astype(np.float32)
    score = float(np.mean((values - sample_values) ** 2))
    return {"score": score, "label": label, "source": source}


def _tensor_detail(detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(detail.get("name")),
        "shape": np.asarray(detail.get("shape")).astype(int).tolist(),
        "shape_signature": np.asarray(detail.get("shape_signature")).astype(int).tolist(),
        "dtype": getattr(detail.get("dtype"), "__name__", str(detail.get("dtype"))),
        "quantization": list(detail.get("quantization", (0.0, 0))),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
