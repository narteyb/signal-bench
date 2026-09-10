# TFLM Reference Model Validation

## Summary

T2.3 validated the three Post 1 MLPerf Tiny reference `.tflite` files from
`models/reference/` with the LiteRT TFLite interpreter. Validation checks the
manifest SHA-256 hash, loads the model, allocates tensors, verifies the expected
input and output shapes, runs one deterministic synthetic inference, and
regenerates embeddable C arrays in `models/tflm/`. This is a format and runtime
smoke check only. It does not validate MLPerf accuracy, real input pipelines,
or target memory budgets.

The validator lives at `tools/validate_tflm_models.py`. It uses
`ai-edge-litert` as the default interpreter package because the full TensorFlow
wheel is a large dev-time dependency and was slow to fetch reliably on the M1
Max. The script still falls back to `tensorflow.lite.Interpreter` when LiteRT is
not installed. C arrays are generated in Python rather than through `xxd` so
the output is deterministic across platforms and always includes the `alignas(8)`
directive required by TFLM on MCU targets.

## KWS

`models/reference/kws/kws_ref_model.tflite` is 53,936 bytes with SHA-256
`aeea436800704fce17b17292e4412630ad856e9d777c044c64ef748a880bd0ae`. The model
loads with one `int8` input tensor named `input_1` shaped `(1, 49, 10, 1)` and
quantized with scale `0.5847029089927673`, zero point `83`. It produces one
`int8` output tensor named `Identity` shaped `(1, 12)` with scale `0.00390625`,
zero point `-128`. Synthetic inference completed successfully. The generated
C array is `models/tflm/kws_int8.cc` with variable
`g_kws_int8_model_data`. The synthetic input is random-but-valid quantized
MFCC-shaped data, so the output is not semantically meaningful; the check only
proves the interpreter accepts the model and produces a correctly shaped tensor.

## IC

`models/reference/ic/pretrainedResnet_quant.tflite` is 98,496 bytes with
SHA-256 `3c002613d1b2475eb51dd78dfb85a546c8ae658dee71cf6ade43b022fe205415`.
The model loads with one `int8` input tensor named `input_1_int8` shaped
`(1, 32, 32, 3)` and quantized with scale `1.0`, zero point `-128`. It produces
one `int8` output tensor named `Identity_int8` shaped `(1, 10)` with scale
`0.00390625`, zero point `-128`. Synthetic inference completed successfully.
The generated C array is `models/tflm/ic_int8.cc` with variable
`g_ic_int8_model_data`. The input tensor matches CIFAR-10 image dimensions, but
the validation input is synthetic int8 data. Phase 5 owns image preprocessing
and accuracy checks against real CIFAR-derived fixtures.

## AD

`models/reference/ad/ad01_int8.tflite` is 276,976 bytes with SHA-256
`87cf24194ef93d1d9b11a591d805526b98008e351655d29883c825c9c106ba24`. The model
loads with one `int8` input tensor named `input_1` shaped `(1, 640)` and
quantized with scale `0.3910152316093445`, zero point `89`. It produces one
`int8` output tensor named `Identity` shaped `(1, 640)` with scale
`0.36449846625328064`, zero point `96`. Synthetic inference completed
successfully. The generated C array is `models/tflm/ad_int8.cc` with variable
`g_ad_int8_model_data`. The output shape mirrors the input shape, as expected
for an autoencoder reconstruction task. T2.3 does not compute anomaly scores or
AUC; that requires the MLPerf evaluation data and belongs to Phase 5.

## Notes

All three models matched the tensor shapes now recorded in per-task provenance.
The AD artifact remains the budget risk for F401RE: T2.3 proves it is a valid
TFLite model, but T2.5 must decide whether any F401RE deployment is possible.
The generated `.cc` files are committed even though they are derived artifacts.
That keeps future firmware builds mechanical: they can include model arrays
without first running a generation step. Regeneration remains available through
`uv run --extra dev python tools/validate_tflm_models.py --regen-c-arrays`, and
the script checks stale or missing arrays during its normal validation path.
