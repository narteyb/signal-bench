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

The recorded conversion environment is TensorFlow `2.21.0`, `tf2onnx`
`1.17.0`, ONNX `1.21.0`, and ONNX Runtime `1.25.1`, using opset `13`.
For example, create an isolated Python 3.12 environment and install those
exact versions:

```bash
uv venv --python 3.12 /tmp/signal-bench-models
uv pip install --python /tmp/signal-bench-models/bin/python \
  "tensorflow==2.21.0" "tf2onnx==1.17.0" "onnx==1.21.0" \
  "onnxruntime==1.25.1"
```

Activate that environment, then run:

```bash
python -m tf2onnx.convert --tflite models/reference/kws/kws_ref_model.tflite \
  --output models/onnx/kws_int8.onnx --opset 13
python -m tf2onnx.convert --tflite models/reference/ic/pretrainedResnet_quant.tflite \
  --output models/onnx/ic_int8.onnx --opset 13
python -m tf2onnx.convert --tflite models/reference/ad/ad01_int8.tflite \
  --output models/onnx/ad_int8.onnx --opset 13
```

Expected ONNX outputs:

| Task | Path | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| KWS | `models/onnx/kws_int8.onnx` | 73,802 | `d7eb060290aa1da24fe2d713d2d68007529531ab661ff55965fe66775181f1da` |
| IC | `models/onnx/ic_int8.onnx` | 112,387 | `6ce9e5fab1590a8365ced31e467796e98bf92c0b29c732164f086053f75e5029` |
| AD | `models/onnx/ad_int8.onnx` | 285,111 | `7de136c8c472be09b00cb1047ea7dcb4e85b5d41f586b2e02721b46d2bac0f60` |

The ONNX files are generic opset-13 outputs, not provider-specific optimized
artifacts. Validate the TFLite/ONNX pair and regenerate the tracked TFLM C
arrays with:

```bash
uv run --extra dev python tools/validate_onnx_models.py
uv run --extra dev python tools/validate_tflm_models.py --regen-c-arrays
```

The per-task provenance files record the source paths, all expected checksums,
the conversion versions, and the cross-format validation results.
