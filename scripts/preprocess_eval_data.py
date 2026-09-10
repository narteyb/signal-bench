# SPDX-License-Identifier: Apache-2.0
"""Preprocess full KWS/AD eval data for streamed MCU evaluation.

The output archive is intentionally simple:
``inputs`` int8 tensors, ``labels`` int64 labels, optional ``sources`` strings,
and ``metadata_json``. The MCU receives the flattened int8 input payload over
the A01 streamed-sample serial protocol implemented by ``signal-bench eval``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
VARIANT_ROOT = Path("<local-path>")
DEFAULT_KWS_FULL = Path("<local-path>")
DEFAULT_AD_GROUPS = VARIANT_ROOT / "ad-distill-50" / "cache" / "test_feature_groups.npz"
MODEL_PATHS = {
    "kws": VARIANT_ROOT / "kws-qat-int8" / "artifacts" / "model.tflite",
    "ad": VARIANT_ROOT / "ad-distill-50" / "artifacts" / "model.tflite",
}
DEFAULT_CORPUS = {
    "kws": "mlperftiny-kws-test",
    "ad": "mlperftiny-ad-test",
}


def main() -> int:
    """Run the preprocessing CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=["kws", "ad"], required=True)
    parser.add_argument("--input-npz", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--corpus", help="Corpus tag used in the output filename/metadata.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    task = args.task
    model = args.model or MODEL_PATHS[task]
    corpus = args.corpus or DEFAULT_CORPUS[task]
    output = args.output or ROOT / "data" / "eval" / task / f"{corpus}.npz"

    if task == "kws":
        inputs, labels, sources, provenance = _load_kws(args.input_npz or DEFAULT_KWS_FULL)
    else:
        inputs, labels, sources, provenance = _load_ad(args.input_npz or DEFAULT_AD_GROUPS)

    quantized, quantization = _quantize_inputs(inputs, model)
    metadata = {
        "generated": dt.datetime.now(dt.UTC).isoformat(),
        "task": task,
        "corpus": corpus,
        "source": provenance,
        "model_path": str(model),
        "model_sha256": _sha256(model),
        "quantization": quantization,
        "input_shape": list(quantized.shape[1:]),
        "n_samples": len(quantized),
        "label_distribution": _label_distribution(labels),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "inputs": quantized,
        "labels": labels.astype(np.int64, copy=False),
        "metadata_json": np.asarray(json.dumps(metadata, sort_keys=True)),
    }
    if sources is not None:
        payload["sources"] = sources.astype(str, copy=False)
    np.savez_compressed(output, **payload)
    output.with_suffix(".metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(output), "metadata": metadata}, indent=2, sort_keys=True))
    return 0


def _load_kws(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray | None, dict[str, Any]]:
    if not path.exists():
        raise SystemExit(
            f"KWS full eval archive not found at {path}. "
            "Run scripts/datasets/prepare_kws.py or pass --input-npz."
        )
    archive = np.load(path, allow_pickle=False)
    return (
        archive["inputs"].astype(np.float32, copy=False),
        archive["labels"].astype(np.int64, copy=False),
        None,
        {"path": str(path), "kind": "full MLPerf Tiny reference-preprocessed KWS"},
    )


def _load_ad(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    if not path.exists():
        raise SystemExit(
            f"AD test feature groups not found at {path}. "
            "Run scripts/datasets/stage_dcase.py and scripts/datasets/prepare_ad.py, "
            "or pass --input-npz."
        )
    archive = np.load(path, allow_pickle=True)
    if "inputs" in archive.files and "labels" in archive.files:
        sources = archive["sources"].astype(str, copy=False) if "sources" in archive.files else None
        if sources is None:
            sources = np.asarray([f"clip_{index}" for index in range(len(archive["inputs"]))])
        return (
            archive["inputs"].astype(np.float32, copy=False),
            archive["labels"].astype(np.int64, copy=False),
            sources,
            {"path": str(path), "kind": "pre-flattened AD eval archive"},
        )

    groups = archive["groups"].item()
    inputs: list[np.ndarray] = []
    labels: list[int] = []
    sources: list[str] = []
    for group_name, clips in sorted(groups.items()):
        for clip_index, item in enumerate(clips):
            features, label = item
            for vector in np.asarray(features, dtype=np.float32):
                inputs.append(vector)
                labels.append(int(label))
                sources.append(f"{group_name}:{clip_index}")
    return (
        np.stack(inputs, axis=0).astype(np.float32),
        np.asarray(labels, dtype=np.int64),
        np.asarray(sources),
        {
            "path": str(path),
            "kind": "AD per-clip feature groups flattened to frame patches",
            "clip_count": len(set(sources)),
        },
    )


def _quantize_inputs(inputs: np.ndarray, model_path: Path) -> tuple[np.ndarray, dict[str, Any]]:
    try:
        from ai_edge_litert.interpreter import Interpreter
    except ModuleNotFoundError:
        from tensorflow.lite.python.interpreter import Interpreter  # type: ignore[no-redef]

    interpreter = Interpreter(model_path=str(model_path))
    interpreter.allocate_tensors()
    detail = interpreter.get_input_details()[0]
    scale, zero_point = detail["quantization"]
    if not scale:
        raise SystemExit(f"model input is not quantized: {model_path}")
    quantized = np.rint(inputs.astype(np.float32) / float(scale) + int(zero_point))
    quantized = np.clip(quantized, -128, 127).astype(np.int8)
    return quantized, {
        "input_scale": float(scale),
        "input_zero_point": int(zero_point),
        "input_dtype": str(detail["dtype"]),
    }


def _label_distribution(labels: np.ndarray) -> dict[str, int]:
    values, counts = np.unique(labels, return_counts=True)
    return {str(int(value)): int(count) for value, count in zip(values, counts, strict=True)}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
