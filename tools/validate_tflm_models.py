# SPDX-License-Identifier: Apache-2.0
"""Validate MLPerf Tiny TFLite models and generate embeddable C arrays."""

from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

try:
    from ai_edge_litert.interpreter import Interpreter as LiteInterpreter
except ModuleNotFoundError:  # pragma: no cover - exercised only without LiteRT.
    try:
        from tensorflow.lite import Interpreter as LiteInterpreter
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency failure path.
        msg = (
            "No TFLite interpreter is installed. Install the dev extra with "
            "`uv sync --extra dev`."
        )
        raise SystemExit(msg) from exc


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_ROOT = ROOT / "models" / "reference"
TFLM_ROOT = ROOT / "models" / "tflm"
MANIFEST_PATH = REFERENCE_ROOT / "manifest.yaml"
BYTES_PER_LINE = 12
RNG_SEED = 42


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """Local validation and C-array settings for one reference model."""

    task: str
    reference_path: Path
    c_array_path: Path
    variable_name: str
    expected_input_shape: tuple[int, ...]
    expected_output_shape: tuple[int, ...]


MODEL_SPECS = (
    ModelSpec(
        task="kws",
        reference_path=REFERENCE_ROOT / "kws" / "kws_ref_model.tflite",
        c_array_path=TFLM_ROOT / "kws_int8.cc",
        variable_name="g_kws_int8_model_data",
        expected_input_shape=(1, 49, 10, 1),
        expected_output_shape=(1, 12),
    ),
    ModelSpec(
        task="ic",
        reference_path=REFERENCE_ROOT / "ic" / "pretrainedResnet_quant.tflite",
        c_array_path=TFLM_ROOT / "ic_int8.cc",
        variable_name="g_ic_int8_model_data",
        expected_input_shape=(1, 32, 32, 3),
        expected_output_shape=(1, 10),
    ),
    ModelSpec(
        task="ad",
        reference_path=REFERENCE_ROOT / "ad" / "ad01_int8.tflite",
        c_array_path=TFLM_ROOT / "ad_int8.cc",
        variable_name="g_ad_int8_model_data",
        expected_input_shape=(1, 640),
        expected_output_shape=(1, 640),
    ),
)


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Validated model metadata used by reports and CLI output."""

    task: str
    path: Path
    bytes_size: int
    sha256: str
    input_name: str
    input_shape: tuple[int, ...]
    input_dtype: str
    input_quantization: tuple[float, int]
    output_name: str
    output_shape: tuple[int, ...]
    output_dtype: str
    output_quantization: tuple[float, int]
    output_preview: tuple[float, ...]


def main() -> None:
    """Run validation and optionally regenerate C arrays."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--regen-c-arrays",
        action="store_true",
        help="Regenerate models/tflm/*.cc from the reference .tflite files.",
    )
    args = parser.parse_args()

    manifest = _load_manifest()
    results = [_validate_model(spec, manifest) for spec in MODEL_SPECS]

    if args.regen_c_arrays:
        for spec in MODEL_SPECS:
            _tflite_to_cc(spec.reference_path, spec.variable_name, spec.c_array_path)
    else:
        _check_c_arrays_current()

    _print_report(results)


def _load_manifest() -> dict[str, object]:
    with MANIFEST_PATH.open("r", encoding="utf-8") as handle:
        manifest = yaml.safe_load(handle)
    if not isinstance(manifest, dict):
        msg = f"{MANIFEST_PATH} did not parse to a mapping"
        raise TypeError(msg)
    return manifest


def _validate_model(spec: ModelSpec, manifest: dict[str, object]) -> ValidationResult:
    if not spec.reference_path.exists():
        msg = f"Missing reference model: {spec.reference_path}"
        raise FileNotFoundError(msg)

    sha256 = hashlib.sha256(spec.reference_path.read_bytes()).hexdigest()
    expected_sha256 = _manifest_sha256(manifest, spec.task)
    if sha256 != expected_sha256:
        msg = f"{spec.task}: SHA-256 mismatch, expected {expected_sha256}, got {sha256}"
        raise ValueError(msg)

    interpreter = LiteInterpreter(model_path=str(spec.reference_path))
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()
    if len(input_details) != 1 or len(output_details) != 1:
        msg = f"{spec.task}: expected one input and one output tensor"
        raise ValueError(msg)

    input_detail = input_details[0]
    output_detail = output_details[0]
    input_shape = _shape_tuple(input_detail["shape"])
    output_shape = _shape_tuple(output_detail["shape"])
    if input_shape != spec.expected_input_shape:
        msg = f"{spec.task}: expected input shape {spec.expected_input_shape}, got {input_shape}"
        raise ValueError(msg)
    if output_shape != spec.expected_output_shape:
        msg = f"{spec.task}: expected output shape {spec.expected_output_shape}, got {output_shape}"
        raise ValueError(msg)

    synthetic_input = _synthetic_input(input_shape, input_detail["dtype"])
    interpreter.set_tensor(input_detail["index"], synthetic_input)
    interpreter.invoke()
    output = interpreter.get_tensor(output_detail["index"])
    if output.shape != output_shape:
        msg = f"{spec.task}: output tensor shape drifted after invoke: {output.shape}"
        raise ValueError(msg)
    if np.issubdtype(output.dtype, np.floating) and not np.isfinite(output).all():
        msg = f"{spec.task}: output contains non-finite values"
        raise ValueError(msg)
    if np.all(output == 0):
        msg = f"{spec.task}: output was all zeros for synthetic input"
        raise ValueError(msg)

    return ValidationResult(
        task=spec.task,
        path=spec.reference_path.relative_to(ROOT),
        bytes_size=spec.reference_path.stat().st_size,
        sha256=sha256,
        input_name=str(input_detail["name"]),
        input_shape=input_shape,
        input_dtype=_dtype_name(input_detail["dtype"]),
        input_quantization=_quantization_tuple(input_detail),
        output_name=str(output_detail["name"]),
        output_shape=output_shape,
        output_dtype=_dtype_name(output_detail["dtype"]),
        output_quantization=_quantization_tuple(output_detail),
        output_preview=tuple(float(value) for value in output.reshape(-1)[:5]),
    )


def _manifest_sha256(manifest: dict[str, object], task: str) -> str:
    tasks = manifest["tasks"]
    if not isinstance(tasks, dict):
        msg = f"{MANIFEST_PATH} tasks entry did not parse to a mapping"
        raise TypeError(msg)
    manifest_info = tasks[task]
    if not isinstance(manifest_info, dict):
        msg = f"{task}: manifest task entry did not parse to a mapping"
        raise TypeError(msg)
    sha256 = manifest_info["sha256"]
    if not isinstance(sha256, str):
        msg = f"{task}: manifest sha256 entry is not a string"
        raise TypeError(msg)
    return sha256


def _shape_tuple(shape: object) -> tuple[int, ...]:
    return tuple(int(part) for part in shape)


def _dtype_name(dtype: object) -> str:
    return np.dtype(dtype).name


def _quantization_tuple(detail: dict[str, object]) -> tuple[float, int]:
    scale, zero_point = detail["quantization"]
    return float(scale), int(zero_point)


def _synthetic_input(shape: tuple[int, ...], dtype: object) -> np.ndarray:
    np_dtype = np.dtype(dtype)
    rng = np.random.default_rng(RNG_SEED)
    if np.issubdtype(np_dtype, np.integer):
        limits = np.iinfo(np_dtype)
        return rng.integers(limits.min, limits.max + 1, size=shape, dtype=np_dtype)
    return rng.random(shape, dtype=np.float32).astype(np_dtype)


def _tflite_to_cc(tflite_path: Path, variable_name: str, output_path: Path) -> None:
    data = tflite_path.read_bytes()
    lines = [
        "#include <cstdint>",
        "",
        f"alignas(8) const unsigned char {variable_name}[] = {{",
    ]
    for offset in range(0, len(data), BYTES_PER_LINE):
        chunk = data[offset : offset + BYTES_PER_LINE]
        lines.append("  " + ", ".join(f"0x{byte:02x}" for byte in chunk) + ",")
    lines.extend(
        [
            "};",
            f"const unsigned int {variable_name}_len = {len(data)};",
            "",
        ],
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def _check_c_arrays_current() -> None:
    for spec in MODEL_SPECS:
        if not spec.c_array_path.exists():
            msg = f"Missing C array: {spec.c_array_path}; run with --regen-c-arrays"
            raise FileNotFoundError(msg)
        expected_len = spec.reference_path.stat().st_size
        text = spec.c_array_path.read_text(encoding="utf-8")
        expected = f"const unsigned int {spec.variable_name}_len = {expected_len};"
        if "alignas(8)" not in text or expected not in text:
            msg = f"{spec.task}: C array is stale; run with --regen-c-arrays"
            raise ValueError(msg)


def _print_report(results: list[ValidationResult]) -> None:
    for result in results:
        print(f"{result.task}: {result.path}")
        print(f"  bytes: {result.bytes_size}")
        print(f"  sha256: {result.sha256}")
        print(
            "  input: "
            f"{result.input_name} {result.input_shape} {result.input_dtype} "
            f"quant={result.input_quantization}",
        )
        print(
            "  output: "
            f"{result.output_name} {result.output_shape} {result.output_dtype} "
            f"quant={result.output_quantization}",
        )
        print(f"  sanity output preview: {result.output_preview}")


if __name__ == "__main__":
    main()
