# ONNX Models

This directory contains generic ONNX Runtime models for the Post 1 SBC,
desktop, and cloud tier. The files are converted from the pinned INT8 TFLite
reference artifacts in `models/reference/` with `tf2onnx` at opset 13. They are
not pre-optimized for CoreML, CUDA, TensorRT, or any other execution provider;
Phase 5 owns provider-specific tuning.

Validate the models with:

```bash
uv run --extra dev python tools/validate_onnx_models.py
```

Regenerate from the TFLite references with `tf2onnx --tflite --opset 13`; the
exact tool versions and hashes are recorded in each task's provenance file.
