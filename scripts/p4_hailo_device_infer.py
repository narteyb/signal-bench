# SPDX-License-Identifier: Apache-2.0
"""Run a local HailoAdapter first-light loop on the Pi and emit JSON lines."""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from signal_bench.adapters.hailo import HailoAdapter, HailoAdapterConfig
from signal_bench.adapters.mcu.task import TaskSpec

if TYPE_CHECKING:
    from signal_bench.adapters.base import InferenceResult


async def _run(args: argparse.Namespace) -> int:
    adapter = HailoAdapter(
        HailoAdapterConfig(
            target_id=args.target_id,
            hef_path=args.hef,
            batch_size=args.batch_size,
            input_format_type=args.input_format_type,
            output_format_type=args.output_format_type,
            timeout_ms=args.timeout_ms,
            warmup_iterations=args.warmup_iterations,
        ),
    )
    task = TaskSpec(
        task_id=args.task_id,
        model_path=args.hef,
        input_data_path=args.input_data,
        metadata={
            "family": args.task_family,
            "quantization": args.quantization,
            "model_hash": args.hef.name,
        },
    )
    try:
        await adapter.prepare(args.run_id)
        metadata = adapter.metadata()
        metadata["hef_source"] = args.hef_source
        print(json.dumps({"type": "metadata", "metadata": metadata}), flush=True)
        await adapter.warmup()
        results = [
            _result_payload(result) async for result in adapter.measure(task, args.iterations)
        ]
        print(
            json.dumps(
                {
                    "type": "measurement_complete",
                    "results": len(results),
                    "timestamp": dt.datetime.now(tz=dt.UTC).isoformat(),
                },
            ),
            flush=True,
        )
        if args.results_jsonl is not None:
            args.results_jsonl.parent.mkdir(parents=True, exist_ok=True)
            with args.results_jsonl.open("w", encoding="utf-8") as handle:
                for result in results:
                    handle.write(json.dumps(result) + "\n")
        else:
            for result in results:
                print(json.dumps(result), flush=True)
    finally:
        await adapter.teardown()
    return 0


def _result_payload(result: InferenceResult) -> dict[str, object]:
    return {
        "type": "result",
        "iter_id": result.iter_id,
        "duration_us": result.duration_us,
        "timestamp": result.timestamp.isoformat(),
        "output": result.output,
        "error": result.error,
    }


def main() -> int:
    """Parse arguments and run the device-side inference loop."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hef", type=Path, required=True)
    parser.add_argument("--hef-source", required=True)
    parser.add_argument("--input-data", type=Path, default=Path("/dev/null"))
    parser.add_argument("--task-id", default="hailo-prebuilt-classification")
    parser.add_argument("--task-family", default="classification")
    parser.add_argument("--quantization", default="prebuilt-hef")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--target-id", default="pi5-hailo10h")
    parser.add_argument("--iterations", type=int, default=200)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--input-format-type", default="FLOAT32")
    parser.add_argument("--output-format-type", default="UINT8")
    parser.add_argument("--timeout-ms", type=int, default=10_000)
    parser.add_argument("--warmup-iterations", type=int, default=1)
    parser.add_argument("--results-jsonl", type=Path)
    args = parser.parse_args()
    try:
        return asyncio.run(_run(args))
    except Exception as exc:
        print(json.dumps({"type": "error", "message": str(exc)}), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
