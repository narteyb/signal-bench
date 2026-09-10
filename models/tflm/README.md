# TFLM C Arrays

This directory contains deterministic C++ arrays generated from the Post 1
reference `.tflite` models in `models/reference/`. The arrays are intended for
direct firmware inclusion when Phase 5 replaces the current canned MCU stubs
with real TFLM inference.

Variable names follow `g_<task>_int8_model_data` with a matching
`_len` constant. Each array is emitted with `alignas(8)` so Cortex-M and
ESP32-S3 TFLM interpreters can read model data safely.

Regenerate and validate with:

```bash
uv run --extra dev python tools/validate_tflm_models.py --regen-c-arrays
```

Future quantization variants should use the same convention, for example
`kws_int4.cc` with `g_kws_int4_model_data`.
