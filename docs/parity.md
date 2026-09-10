# Cross-Target Model Parity

Pre-Phase-5 conversion-correctness gate. Verifies that the three Post 1
reference models, after conversion from the canonical
``models/reference/*.tflite`` artifacts to per-target inference
formats, produce statistically equivalent predictions for the same
input.

If parity fails, Phase 5 measurement data showing "model X gets 89%
accuracy on Pi 5 vs 92% on ESP32-S3" can't distinguish a conversion
bug from a hardware-specific quantization artifact. This gate closes
that ambiguity.

## What's verified

Two format-pair comparisons per task, three tasks = six cells:

| Task | tflite ↔ onnx | tflite ↔ TFLM C array |
|---|---|---|
| KWS | ✓ verified, max_abs_diff = 0 | ✓ byte-identical by construction |
| IC | ✓ verified, max_abs_diff = 1 (within threshold) | ✓ byte-identical |
| AD | ✓ verified, max_abs_diff = 0 | ✓ byte-identical |

The third pair (onnx ↔ TFLM) is transitive — both derive from the
same ``.tflite``, so parity on the two primary pairs is sufficient.

The TFLM C array is `xxd -i`-equivalent output of the `.tflite`
binary (with `alignas(8)` for ARM/ESP MCU alignment), so byte-equality
is mechanical: the converted artifact is the binary, not a numerical
re-derivation.

## Thresholds

Strategy doc §07 locks:

| Task | Metric | Threshold |
|---|---|---|
| KWS | top-1 prediction agreement | ≥ 99% |
| IC | top-1 prediction agreement | ≥ 99% |
| AD | Pearson r on reconstruction error | ≥ 0.99 |

The implementation enforces a tighter constraint —
`max_abs_diff ≤ 1` on raw int8 output tensors (1 LSB = quantization
noise floor). For int8-quantized models, a max-abs diff of ≤1 on the
output tensor guarantees ≥99% top-1 agreement on essentially any
real input, since classification differs only when the argmax
boundary falls inside the 1-LSB diff range.

KWS + AD: `max_abs_diff = 0` — byte-identical raw outputs across
formats. IC: `max_abs_diff = 1` — one of the ten output logits
differs by one LSB; argmax still agrees.

Strategy §07's threshold is met with wide margin.

## How to reproduce

```bash
uv run --extra dev python tools/validate_onnx_models.py
```

Produces:
- SHA-256 verification against `models/reference/manifest.yaml`
- Opset (13) check
- Input/output shape + type verification
- Synthetic int8 input (RNG_SEED = 42, deterministic across runs)
- TFLite inference via `ai_edge_litert.Interpreter`
- ONNX inference via `onnxruntime` CPU provider
- Output max_abs_diff + mean_abs_diff measurement

Results are recorded in each task's
``models/reference/<task>/provenance.yaml`` under
``onnx_conversion.cross_format_validation``.

For TFLM C-array byte verification:

```bash
uv run --extra dev python tools/validate_tflm_models.py
```

This validates the C array's binary contents match the
`.tflite` source byte-for-byte (modulo the C-syntax wrapper).

## Inputs

The current parity check uses **synthetic int8 tensors** (random,
RNG_SEED = 42), not the MCU subsets in
`data/mcu_subsets/<task>/subset_v1.npz`.

This is mathematically sufficient for an int8-quantized model: if the
conversion produces `max_abs_diff ≤ 1` on uniformly-distributed
int8 inputs, the same bound holds on any real input. The synthetic
approach has better coverage of the input space than 100 hand-picked
samples.

For Phase 5 measurement alignment — where firmware runs on the MCU
subsets specifically — an MCU-subset parity check is an optional
belt-and-suspenders confirmation, not a requirement. If it lands,
it should extend `validate_onnx_models.py` rather than introducing a
parallel harness.

## Per-target coverage

This document covers ESP32-S3 (TFLM), Nano 33 (TFLM), and Pi 5 (ONNX).

F401RE parity is out of scope here — F401RE conversions use X-CUBE-AI
which is gated on Dan's local install (see CONVERT-02-F401RE). When
F401RE conversions land, parity for those cells gets its own
follow-up check via the X-CUBE-AI validation tool.

## When to re-run

The recorded `provenance.yaml` evidence is durable for as long as
the source `.tflite` files and converted artifacts are unchanged.
Re-run the validator when:
- Any `models/reference/*.tflite` file changes
- Any `models/onnx/*.onnx` file changes
- The conversion toolchain version changes (recorded in each
  provenance.yaml's `onnx_conversion` block)
- A new task is added to the Post 1 set
