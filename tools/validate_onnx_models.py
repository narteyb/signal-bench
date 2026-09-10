# SPDX-License-Identifier: Apache-2.0
"""Validate Post 1 ONNX models against TFLite reference outputs."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import yaml
from ai_edge_litert.interpreter import Interpreter as LiteInterpreter

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_ROOT = ROOT / "models" / "reference"
ONNX_ROOT = ROOT / "models" / "onnx"
MANIFEST_PATH = REFERENCE_ROOT / "manifest.yaml"
RNG_SEED = 42
MAX_ABS_DIFF_THRESHOLD = 1
EXPECTED_ONNX_OPSET = 13


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """Reference and ONNX settings for one model."""

    task: str
    tflite_path: Path
    onnx_path: Path
    expected_input_shape: tuple[int, ...]
    expected_output_shape: tuple[int, ...]
    expected_input_type: str = "tensor(int8)"
    expected_output_type: str = "tensor(int8)"


MODEL_SPECS = (
    ModelSpec(
        task="kws",
        tflite_path=REFERENCE_ROOT / "kws" / "kws_ref_model.tflite",
        onnx_path=ONNX_ROOT / "kws_int8.onnx",
        expected_input_shape=(1, 49, 10, 1),
        expected_output_shape=(1, 12),
    ),
    ModelSpec(
        task="ic",
        tflite_path=REFERENCE_ROOT / "ic" / "pretrainedResnet_quant.tflite",
        onnx_path=ONNX_ROOT / "ic_int8.onnx",
        expected_input_shape=(1, 32, 32, 3),
        expected_output_shape=(1, 10),
    ),
    ModelSpec(
        task="ad",
        tflite_path=REFERENCE_ROOT / "ad" / "ad01_int8.tflite",
        onnx_path=ONNX_ROOT / "ad_int8.onnx",
        expected_input_shape=(1, 640),
        expected_output_shape=(1, 640),
    ),
)


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Validated ONNX model metadata and cross-format diff results."""

    task: str
    path: Path
    bytes_size: int
    sha256: str
    opset: int
    input_name: str
    input_shape: tuple[int, ...]
    input_type: str
    output_name: str
    output_shape: tuple[int, ...]
    output_type: str
    max_abs_diff: int
    mean_abs_diff: float
    output_preview: tuple[float, ...]


def main() -> None:
    """Run ONNX validation for all Post 1 reference models."""
    manifest = _load_manifest()
    results = [_validate_model(spec, manifest) for spec in MODEL_SPECS]
    _print_report(results)


def _load_manifest() -> dict[str, object]:
    with MANIFEST_PATH.open("r", encoding="utf-8") as handle:
        manifest = yaml.safe_load(handle)
    if not isinstance(manifest, dict):
        msg = f"{MANIFEST_PATH} did not parse to a mapping"
        raise TypeError(msg)
    return manifest


def _validate_model(spec: ModelSpec, manifest: dict[str, object]) -> ValidationResult:
    if not spec.onnx_path.exists():
        msg = f"Missing ONNX model: {spec.onnx_path}"
        raise FileNotFoundError(msg)
    sha256 = hashlib.sha256(spec.onnx_path.read_bytes()).hexdigest()
    expected_sha256 = _manifest_onnx_sha256(manifest, spec.task)
    if sha256 != expected_sha256:
        msg = f"{spec.task}: SHA-256 mismatch, expected {expected_sha256}, got {sha256}"
        raise ValueError(msg)

    model = onnx.load(spec.onnx_path)
    onnx.checker.check_model(model)
    opset = _default_opset(model)
    if opset != EXPECTED_ONNX_OPSET:
        msg = f"{spec.task}: expected ONNX opset {EXPECTED_ONNX_OPSET}, got {opset}"
        raise ValueError(msg)

    session = ort.InferenceSession(str(spec.onnx_path), providers=["CPUExecutionProvider"])
    inputs = session.get_inputs()
    outputs = session.get_outputs()
    if len(inputs) != 1 or len(outputs) != 1:
        msg = f"{spec.task}: expected one input and one output"
        raise ValueError(msg)
    input_meta = inputs[0]
    output_meta = outputs[0]
    _assert_tensor_meta(spec, input_meta, output_meta)

    synthetic_input = _synthetic_int8(spec.expected_input_shape)
    onnx_output = session.run(None, {input_meta.name: synthetic_input})[0]
    tflite_output = _run_tflite(spec, synthetic_input)
    max_abs_diff, mean_abs_diff = _diff(tflite_output, onnx_output)
    if max_abs_diff > MAX_ABS_DIFF_THRESHOLD:
        msg = (
            f"{spec.task}: ONNX/TFLite max abs diff {max_abs_diff} exceeds "
            f"{MAX_ABS_DIFF_THRESHOLD}"
        )
        raise ValueError(msg)

    return ValidationResult(
        task=spec.task,
        path=spec.onnx_path.relative_to(ROOT),
        bytes_size=spec.onnx_path.stat().st_size,
        sha256=sha256,
        opset=opset,
        input_name=input_meta.name,
        input_shape=spec.expected_input_shape,
        input_type=input_meta.type,
        output_name=output_meta.name,
        output_shape=spec.expected_output_shape,
        output_type=output_meta.type,
        max_abs_diff=max_abs_diff,
        mean_abs_diff=mean_abs_diff,
        output_preview=tuple(float(value) for value in onnx_output.reshape(-1)[:5]),
    )


def _manifest_onnx_sha256(manifest: dict[str, object], task: str) -> str:
    tasks = manifest["tasks"]
    if not isinstance(tasks, dict):
        msg = f"{MANIFEST_PATH} tasks entry did not parse to a mapping"
        raise TypeError(msg)
    task_info = tasks[task]
    if not isinstance(task_info, dict):
        msg = f"{task}: manifest task entry did not parse to a mapping"
        raise TypeError(msg)
    formats = task_info["formats"]
    if not isinstance(formats, dict):
        msg = f"{task}: manifest formats entry did not parse to a mapping"
        raise TypeError(msg)
    onnx_info = formats["onnx"]
    if not isinstance(onnx_info, dict):
        msg = f"{task}: manifest onnx entry did not parse to a mapping"
        raise TypeError(msg)
    sha256 = onnx_info["sha256"]
    if not isinstance(sha256, str):
        msg = f"{task}: manifest onnx sha256 entry is not a string"
        raise TypeError(msg)
    return sha256


def _default_opset(model: onnx.ModelProto) -> int:
    for opset in model.opset_import:
        if opset.domain in ("", "ai.onnx"):
            return int(opset.version)
    msg = "ONNX model has no default-domain opset"
    raise ValueError(msg)


def _assert_tensor_meta(
    spec: ModelSpec,
    input_meta: ort.NodeArg,
    output_meta: ort.NodeArg,
) -> None:
    if input_meta.type != spec.expected_input_type:
        msg = f"{spec.task}: expected input type {spec.expected_input_type}, got {input_meta.type}"
        raise ValueError(msg)
    if output_meta.type != spec.expected_output_type:
        msg = (
            f"{spec.task}: expected output type {spec.expected_output_type}, "
            f"got {output_meta.type}"
        )
        raise ValueError(msg)
    if _static_tail(input_meta.shape) != spec.expected_input_shape[1:]:
        msg = f"{spec.task}: unexpected input shape {input_meta.shape}"
        raise ValueError(msg)
    if _static_tail(output_meta.shape) != spec.expected_output_shape[1:]:
        msg = f"{spec.task}: unexpected output shape {output_meta.shape}"
        raise ValueError(msg)


def _static_tail(shape: list[object]) -> tuple[int, ...]:
    return tuple(int(value) for value in shape[1:])


def _synthetic_int8(shape: tuple[int, ...]) -> np.ndarray:
    rng = np.random.default_rng(RNG_SEED)
    limits = np.iinfo(np.int8)
    return rng.integers(limits.min, limits.max + 1, size=shape, dtype=np.int8)


def _run_tflite(spec: ModelSpec, synthetic_input: np.ndarray) -> np.ndarray:
    interpreter = LiteInterpreter(model_path=str(spec.tflite_path))
    interpreter.allocate_tensors()
    input_detail = interpreter.get_input_details()[0]
    output_detail = interpreter.get_output_details()[0]
    interpreter.set_tensor(input_detail["index"], synthetic_input)
    interpreter.invoke()
    return interpreter.get_tensor(output_detail["index"])


def _diff(tflite_output: np.ndarray, onnx_output: np.ndarray) -> tuple[int, float]:
    diff = np.abs(tflite_output.astype(np.int16) - onnx_output.astype(np.int16))
    return int(diff.max()), float(diff.mean())


def _print_report(results: list[ValidationResult]) -> None:
    for result in results:
        print(f"{result.task}: {result.path}")
        print(f"  bytes: {result.bytes_size}")
        print(f"  sha256: {result.sha256}")
        print(f"  opset: {result.opset}")
        print(f"  input: {result.input_name} {result.input_shape} {result.input_type}")
        print(f"  output: {result.output_name} {result.output_shape} {result.output_type}")
        print(
            "  tflite/onnx diff: "
            f"max_abs={result.max_abs_diff} mean_abs={result.mean_abs_diff:.6f}",
        )
        print(f"  sanity output preview: {result.output_preview}")


if __name__ == "__main__":
    main()
