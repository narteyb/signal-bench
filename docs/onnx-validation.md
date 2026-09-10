# ONNX Reference Model Validation

## Summary

T2.4 converted the three Post 1 INT8 TFLite reference models into generic ONNX
models for Pi 5, Jetson Orin Nano, M1 Max, and Modal A10G execution. Conversion
used `tf2onnx` 1.17.0 with TensorFlow 2.21.0 and opset 13. The failed fallback
path was `tflite2onnx` 0.4.1, which could not convert the KWS model because its
quantized convolution uses per-channel quantization while that converter only
supports per-tensor quantization for the relevant tensor path.

Validation lives in `tools/validate_onnx_models.py`. It loads each ONNX model
with ONNX Runtime 1.25.1, verifies the manifest SHA-256 hash, checks that the
default ONNX opset is 13, confirms the input and output tensor surfaces remain
`int8`, runs deterministic synthetic inference, and compares the ONNX output to
the original TFLite output for the same input. The accepted cross-format
tolerance is max absolute difference <= 1 in int8 output space.

## KWS

`models/onnx/kws_int8.onnx` is 73,802 bytes with SHA-256
`d7eb060290aa1da24fe2d713d2d68007529531ab661ff55965fe66775181f1da`. The ONNX
model exposes input `input_1` with shape `(1, 49, 10, 1)` and type
`tensor(int8)`, and output `Identity` with shape `(1, 12)` and type
`tensor(int8)`. ONNX Runtime inference succeeded. The cross-format check against
LiteRT/TFLite produced max abs diff `0`, mean abs diff `0.0`.

## IC

`models/onnx/ic_int8.onnx` is 112,387 bytes with SHA-256
`6ce9e5fab1590a8365ced31e467796e98bf92c0b29c732164f086053f75e5029`. The ONNX
model exposes input `input_1_int8` with shape `(1, 32, 32, 3)` and type
`tensor(int8)`, and output `Identity_int8` with shape `(1, 10)` and type
`tensor(int8)`. ONNX Runtime inference succeeded. The cross-format check
produced max abs diff `1`, mean abs diff `0.2`, which is within the accepted
int8 tolerance and should be treated as normal runtime rounding variance.

## AD

`models/onnx/ad_int8.onnx` is 285,111 bytes with SHA-256
`7de136c8c472be09b00cb1047ea7dcb4e85b5d41f586b2e02721b46d2bac0f60`. The ONNX
model exposes input `input_1` with shape `(1, 640)` and type `tensor(int8)`, and
output `Identity` with shape `(1, 640)` and type `tensor(int8)`. ONNX Runtime
inference succeeded. The cross-format check against LiteRT/TFLite produced max
abs diff `0`, mean abs diff `0.0`.

## Notes

All three ONNX models preserve INT8 input and output tensors and use generic
opset 13 graphs. No execution-provider-specific optimization was applied.
T2.4 does not validate MLPerf accuracy and does not make any memory-budget
decision; T2.5 remains responsible for the F401RE fit analysis, and Phase 5
owns accuracy runs against real benchmark fixtures.

The ONNX files are intentionally generic. They were not optimized for CoreML on
M1 Max, CUDA on Modal A10G, TensorRT on Jetson, or any Pi-specific execution
provider. That keeps the model registry stable: all non-MCU targets begin from
the same canonical ONNX bytes, and Phase 5 can measure provider-specific
optimization as an explicit runtime choice rather than as hidden model drift.

The validation script accepts ONNX Runtime's symbolic batch dimension names
(`unk__...`) but requires the static non-batch dimensions to match the TFLite
registry. This preserves flexibility for batch size while still catching task
shape drift. All sanity inputs are deterministic `int8` arrays generated with
seed `42`, so the cross-format diff values are repeatable across validation
runs. The IC model's max diff of `1` is the only non-zero delta observed and
stays exactly at the accepted tolerance.
