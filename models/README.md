# Reproducing the reference models

The publishable repository contains the model provenance and the generated
TFLM C arrays, but intentionally does not publish compiled `.tflite` or `.onnx`
model binaries. The binary paths are ignored by the repository. Recreate the
files below from the pinned MLCommons Tiny source and verify their bytes before
using them in a benchmark.

## 1. Download the pinned TFLite references

The source is the public `mlcommons/tiny` repository at commit
`5dae3296bd899ed58a65311a8e6fd91d83f664ab` (the v1.3 benchmark definitions;
the public repository does not expose a matching tag). The retrieval timestamp
recorded for these artifacts is `2026-05-10T04:03:03Z`.

```bash
set -eu
mkdir -p models/reference/{kws,ic,ad}
base=https://raw.githubusercontent.com/mlcommons/tiny/5dae3296bd899ed58a65311a8e6fd91d83f664ab/benchmark/training
curl -fsSL "$base/keyword_spotting/trained_models/kws_ref_model.tflite" \
  -o models/reference/kws/kws_ref_model.tflite
curl -fsSL "$base/image_classification/trained_models/pretrainedResnet_quant.tflite" \
  -o models/reference/ic/pretrainedResnet_quant.tflite
curl -fsSL "$base/anomaly_detection/trained_models/ad01_int8.tflite" \
  -o models/reference/ad/ad01_int8.tflite
```

Expected TFLite files:

| Task | Path | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| KWS | `models/reference/kws/kws_ref_model.tflite` | 53,936 | `aeea436800704fce17b17292e4412630ad856e9d777c044c64ef748a880bd0ae` |
| IC | `models/reference/ic/pretrainedResnet_quant.tflite` | 98,496 | `3c002613d1b2475eb51dd78dfb85a546c8ae658dee71cf6ade43b022fe205415` |
| AD | `models/reference/ad/ad01_int8.tflite` | 276,976 | `87cf24194ef93d1d9b11a591d805526b98008e351655d29883c825c9c106ba24` |

Check the downloads with `shasum -a 256` (or `sha256sum`) and compare both
the digest and byte count with this table and
`models/reference/manifest.yaml`.

## 2. Convert TFLite to ONNX

The conversion environment is CPython `3.12.3` with uv `0.10.7`, TensorFlow
`2.21.0`, `tf2onnx` `1.17.0`, ONNX `1.21.0`, and ONNX Runtime `1.25.1`, using
opset `13`. The complete environment, including the serializer and runtime
dependencies that affect the bytes, is pinned in
`models/onnx-conversion-requirements.txt`.

```bash
uv --version  # expected: 0.10.7
uv venv --python 3.12.3 /tmp/signal-bench-models
uv pip install --python /tmp/signal-bench-models/bin/python \
  -r models/onnx-conversion-requirements.txt
```

Activate that environment, then run:

```bash
python -m tf2onnx.convert --tflite models/reference/kws/kws_ref_model.tflite \
  --output models/onnx/kws_int8.onnx --opset 13
python -m tf2onnx.convert --tflite models/reference/ic/pretrainedResnet_quant.tflite \
  --output models/onnx/ic_int8.onnx --opset 13
python -m tf2onnx.convert --tflite models/reference/ad/ad01_int8.tflite \
  --output models/onnx/ad_int8.onnx --opset 13
python tools/canonicalize_onnx.py --in-place models/onnx/kws_int8.onnx
python tools/canonicalize_onnx.py --in-place models/onnx/ic_int8.onnx
python tools/canonicalize_onnx.py --in-place models/onnx/ad_int8.onnx
```

Expected ONNX outputs:

| Task | Path | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| KWS | `models/onnx/kws_int8.onnx` | 38,178 | `c3c8900765c752402579a7eb199f380ef74e087bd0f2bac29899f0035a2975e0` |
| IC | `models/onnx/ic_int8.onnx` | 91,671 | `f180650819ce87f83472d03ca5f44689d0c925be034e612e791c463d0e87d66b` |
| AD | `models/onnx/ad_int8.onnx` | 278,240 | `6131f5b7b2428c83fc5417dcba98adc5fa99bfc10db7b7c6af689459ab44bbb1` |

The canonicalization step removes generated names and normalizes protobuf
serialization so repeated conversions in the pinned environment have stable
bytes. These byte-level checksums are still specific to the pinned environment
and canonicalization tool. A different Python, protobuf, ONNX, or related
serializer version can produce a semantically equivalent ONNX graph with
different bytes; treat a mismatch as unverified until the pinned environment
and canonicalization step are used. The ONNX files are generic opset-13
outputs, not provider-specific optimized artifacts. Validate the TFLite/ONNX
pair and regenerate the tracked TFLM C arrays with:

```bash
uv run --extra dev python tools/validate_onnx_models.py
uv run --extra dev python tools/validate_tflm_models.py --regen-c-arrays
```

The per-task provenance files record the source paths, all expected checksums,
the conversion versions, and the cross-format validation results.
