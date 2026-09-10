# SPDX-License-Identifier: Apache-2.0
"""Export P4 X-corpus float TFLite inputs for Hailo DFC compilation.

The exported models and calibration arrays are proprietary/local build inputs.
They are written out-of-tree by default and must not be committed.
"""


from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import numpy as np
import tensorflow as tf

VARIANT_ROOT = Path("<local-path>")
DEFAULT_OUTPUT = Path("<local-path>")
SUBSET_ROOT = Path("<local-path>")

REGENERATE_SUBSET_COMMANDS = {
    "ic": "uv run python scripts/datasets/prepare_ic.py",
    "ad": (
        "uv run python scripts/datasets/stage_dcase.py && "
        "uv run python scripts/datasets/prepare_ad.py"
    ),
}


def main() -> int:
    """Export float models and calibration tensors."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "ic": _export_ic(output_dir / "ic"),
        "kws": _export_kws(output_dir / "kws"),
        "ad": _export_ad(output_dir / "ad"),
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


def _export_ic(output_dir: Path) -> dict[str, Any]:
    variant = VARIANT_ROOT / "ic-resnet-prune-40"
    common = _load_module("p4_ic_common", variant / "common.py")
    model = common.build_resnet8()
    checkpoint = variant / "checkpoints/ic-resnet-prune-40.weights.h5"
    model.load_weights(checkpoint)
    return _write_float_tflite_and_calib(
        task="ic",
        output_dir=output_dir,
        model=model,
        subset_path=SUBSET_ROOT / "ic/subset_v1.npz",
        lineage_path=variant / "artifacts/lineage.json",
        checkpoint=checkpoint,
        calib_cast=np.float32,
    )


def _export_kws(output_dir: Path) -> dict[str, Any]:
    try:
        import tensorflow_model_optimization as tfmot
    except ModuleNotFoundError as exc:
        msg = "tensorflow_model_optimization is required to load the KWS QAT SavedModel"
        raise RuntimeError(msg) from exc

    variant = VARIANT_ROOT / "kws-qat-int8"
    checkpoint = variant / "checkpoints/kws-qat-int8"
    canonical_checkpoint = variant / "checkpoints/kws-ds-cnn-canonical"
    model = tf.keras.models.load_model(canonical_checkpoint, compile=False)
    with tfmot.quantization.keras.quantize_scope():
        qat_model = tf.keras.models.load_model(checkpoint, compile=False)
    _transfer_qat_inner_weights(qat_model, model)
    inputs, labels, indices = _load_kws_reference_subset(variant, SUBSET_ROOT / "kws/subset_v1.npz")
    return _write_float_tflite_and_calib(
        task="kws",
        output_dir=output_dir,
        model=model,
        inputs=inputs,
        labels=labels,
        indices=indices,
        lineage_path=variant / "artifacts/lineage.json",
        checkpoint=checkpoint,
        calib_cast=np.float32,
    )


def _export_ad(output_dir: Path) -> dict[str, Any]:
    variant = VARIANT_ROOT / "ad-distill-50"
    common = _load_module("p4_ad_common", variant / "common.py")
    config = common.get_student_config("b07-d07-a05")
    model = common.build_student(config)
    checkpoint = variant / "checkpoints/b07-d07-a05.weights.h5"
    model.load_weights(checkpoint)
    manifest = _write_float_tflite_and_calib(
        task="ad",
        output_dir=output_dir,
        model=model,
        subset_path=SUBSET_ROOT / "ad/subset_v1.npz",
        lineage_path=variant / "artifacts/lineage.json",
        checkpoint=checkpoint,
        calib_cast=np.float32,
    )
    manifest["clip_eval_subset_path"] = str(_write_ad_clip_eval_subset(common, output_dir))
    return manifest


def _write_float_tflite_and_calib(
    *,
    task: str,
    output_dir: Path,
    model: tf.keras.Model,
    lineage_path: Path,
    checkpoint: Path,
    calib_cast: Any,
    subset_path: Path | None = None,
    inputs: np.ndarray | None = None,
    labels: np.ndarray | None = None,
    indices: np.ndarray | None = None,
) -> dict[str, Any]:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    if inputs is None:
        if subset_path is None:
            msg = "Either subset_path or inputs must be provided"
            raise ValueError(msg)
        if not subset_path.exists():
            command = REGENERATE_SUBSET_COMMANDS.get(task)
            if command:
                msg = (
                    f"missing regenerated {task.upper()} subset: {subset_path}. "
                    f"Run `{command}` from the repo root first."
                )
                raise FileNotFoundError(msg)
        archive = np.load(subset_path, allow_pickle=False)
        inputs = archive["inputs"]
        labels = archive.get("labels", labels)
        indices = archive.get("indices", indices)
    inputs = inputs.astype(calib_cast)
    calib_path = output_dir / "calib.npy"
    np.save(calib_path, inputs)
    eval_subset_path = output_dir / "eval_subset.npz"
    eval_payload: dict[str, Any] = {"inputs": inputs}
    if labels is not None:
        eval_payload["labels"] = labels
    if indices is not None:
        eval_payload["indices"] = indices
    np.savez_compressed(eval_subset_path, **eval_payload)

    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    tflite = converter.convert()
    model_path = output_dir / f"{task}_float.tflite"
    model_path.write_bytes(tflite)
    lineage_copy = output_dir / "lineage.json"
    shutil.copyfile(lineage_path, lineage_copy)

    return {
        "task": task,
        "model_path": str(model_path),
        "model_format": "float32-tflite",
        "calib_path": str(calib_path),
        "eval_subset_path": str(eval_subset_path),
        "calib_shape": list(inputs.shape),
        "calib_dtype": str(inputs.dtype),
        "lineage_path": str(lineage_copy),
        "checkpoint": str(checkpoint),
        "source_lineage": str(lineage_path),
        "size_bytes": model_path.stat().st_size,
    }


def _load_kws_reference_subset(
    variant: Path,
    subset_path: Path,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return the KWS subset through the MLPerf Tiny reference preprocessing."""
    existing = np.load(subset_path, allow_pickle=False)
    wanted_indices = existing["indices"].astype(np.int64)
    max_index = int(wanted_indices.max())

    common = _load_module("p4_kws_common", variant / "common.py")
    modules = common.load_mlperf_kws_modules(common.DEFAULT_MLPERF_TINY_ROOT)
    bg_path = common.default_bg_path(common.DEFAULT_MLPERF_TINY_ROOT)
    (_ds_train, ds_test, _ds_val), _flags = common.load_datasets(
        modules,
        data_dir=common.DEFAULT_DATA_DIR,
        bg_path=bg_path,
        batch_size=100,
        learning_rate=1e-4,
        epochs=40,
        num_test_samples=max_index + 1,
    )

    features: list[np.ndarray] = []
    labels: list[np.ndarray] = []
    for batch_inputs, batch_labels in ds_test:
        features.append(batch_inputs.numpy().astype(np.float32))
        labels.append(batch_labels.numpy().astype(np.int64))
    all_inputs = np.concatenate(features, axis=0)
    all_labels = np.concatenate(labels, axis=0)
    selected_inputs = all_inputs[wanted_indices]
    selected_labels = all_labels[wanted_indices]
    return selected_inputs, selected_labels, wanted_indices


def _write_ad_clip_eval_subset(common: Any, output_dir: Path) -> Path:
    """Write a deterministic balanced clip-level AD eval subset."""
    groups = common.load_test_feature_groups(
        Path.home() / "data" / "dcase-2020-task2" / "ToyCar",
        cache_dir=VARIANT_ROOT / "ad-distill-50" / "cache",
    )
    rng = np.random.default_rng(0)
    frames: list[np.ndarray] = []
    labels: list[np.ndarray] = []
    frame_sources: list[np.ndarray] = []
    for machine_id, records in sorted(groups.items()):
        by_label = {
            0: [(index, features) for index, (features, label) in enumerate(records) if label == 0],
            1: [(index, features) for index, (features, label) in enumerate(records) if label == 1],
        }
        for label in (0, 1):
            chosen = rng.choice(len(by_label[label]), size=20, replace=False)
            for chosen_index in sorted(chosen.tolist()):
                record_index, clip_frames = by_label[label][chosen_index]
                source = f"{machine_id}_{record_index:04d}_label{label}"
                clip_frames = clip_frames.astype(np.float32)
                frames.append(clip_frames)
                labels.append(np.full(clip_frames.shape[0], label, dtype=np.int64))
                frame_sources.append(np.full(clip_frames.shape[0], source))
    eval_path = output_dir / "eval_clip_frames.npz"
    np.savez_compressed(
        eval_path,
        inputs=np.concatenate(frames, axis=0),
        labels=np.concatenate(labels, axis=0),
        sources=np.concatenate(frame_sources, axis=0),
    )
    return eval_path


def _transfer_qat_inner_weights(qat_model: tf.keras.Model, float_model: tf.keras.Model) -> None:
    """Copy trained inner-layer weights from a TFMOT QAT graph to a float graph."""
    transferred = 0
    for wrapper in qat_model.layers:
        inner = getattr(wrapper, "layer", None)
        if inner is None or not inner.weights:
            continue
        try:
            target = float_model.get_layer(inner.name)
        except ValueError:
            continue
        inner_weights = inner.get_weights()
        target_weights = target.get_weights()
        if len(inner_weights) != len(target_weights):
            continue
        if any(
            source.shape != dest.shape
            for source, dest in zip(inner_weights, target_weights, strict=True)
        ):
            continue
        target.set_weights(inner_weights)
        transferred += 1
    if transferred == 0:
        msg = "No KWS QAT inner-layer weights were transferred to the float graph"
        raise RuntimeError(msg)


def _load_module(name: str, path: Path) -> Any:
    module_dir = str(path.parent)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        msg = f"Unable to load module from {path}"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    raise SystemExit(main())
