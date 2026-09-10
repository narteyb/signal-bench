# Third-Party Data and Model Inventory

This repository is Apache-2.0, but not every third-party component referenced by
the launch-tier benchmarks is Apache-2.0. This inventory separates signal-bench
code from redistributed data and model artifacts.

## Summary

| Component | Repo surface | Hugging Face surface | Upstream | License | Status |
|---|---|---|---|---|---|
| KWS MCU subset | fetched local file, not committed | `narteybrown/signal-bench-support-artifacts-v1` | Google Speech Commands v0.02 | CC BY 4.0 | Retrieved on demand with attribution |
| IC MCU subset | generated local file, not committed | `narteybrown/signal-bench-ic-v1` | CIFAR-10, University of Toronto | Terms not explicit enough for repo redistribution | Regenerate from upstream |
| AD MCU subset | generated local file, not committed | `narteybrown/signal-bench-ad-v1` | DCASE 2020 Task 2 / ToyADMOS ToyCar | CC BY-NC-SA 4.0 | Regenerate from upstream |
| Full-eval KWS/AD archives | fetched local files, not committed | `narteybrown/signal-bench-support-artifacts-v1` | Google Speech Commands v0.02 / DCASE 2020 Task 2 | CC BY 4.0 / CC BY-NC-SA 4.0 | Retrieved on demand |
| Reference models | `models/reference/**` | none | MLCommons Tiny commit `5dae3296bd899ed58a65311a8e6fd91d83f664ab` | Apache-2.0 | Redistributed with NOTICE |

Tier A no-hardware verification does not depend on the KWS, IC, or AD input
datasets. It fetches `narteybrown/signal-bench-post1-telemetry-v1`, which is
Dan Brown's own Apache-2.0 measurement telemetry.

## KWS: Google Speech Commands

The KWS subset is derived from Google Speech Commands v0.02, published by Pete
Warden, filtered to the MLPerf Tiny KWS class set, and converted to 49 x 10 x 1
MFCC features with the MLPerf Tiny reference preprocessing parameters.

License: Creative Commons Attribution 4.0 International (CC BY 4.0). The KWS
subset is not covered by signal-bench's Apache-2.0 license.

Attribution:

- Upstream dataset: Google Speech Commands v0.02.
- Author: Pete Warden.
- Source: <https://www.tensorflow.org/datasets/catalog/speech_commands>
- Paper: Warden, Pete. "Speech Commands: A Dataset for Limited-Vocabulary
  Speech Recognition." arXiv:1804.03209, 2018.
- License: <https://creativecommons.org/licenses/by/4.0/>

Change notice: signal-bench uses the test split, relies on TensorFlow Datasets
for Speech Commands partitioning and `_silence_` / `_unknown_` synthesis, filters
to the MLPerf Tiny 12-class target set, extracts MFCC features, and stores a
deterministic 100-sample MCU subset.

Fetch the pinned support artifact or regenerate it:

```bash
uv run python scripts/fetch_support_artifacts.py data/mcu_subsets/kws/subset_v1.npz
```

```bash
uv sync --extra dev --extra kws-prep
uv run python scripts/datasets/prepare_kws.py
```

## Full-Eval Support Archives

The full-eval archives under `data/eval/**` are preprocessed input archives for
hardware-facing evaluation runs. They are not working databases and are not
committed to Git. Fetch the pinned copies from Hugging Face when needed:

```bash
uv run python scripts/fetch_support_artifacts.py \
  data/eval/kws/mlperftiny-kws-test.npz \
  data/eval/ad/mlperftiny-ad-test.npz
```

The `signal-bench eval` command also fetches its default archive automatically
when the default local path is missing.

## IC: CIFAR-10

The IC subset is a deterministic 100-image stratified subset from the CIFAR-10
official test batch.

Upstream:

- Source: <https://www.cs.toronto.edu/~kriz/cifar.html>
- Download: <https://www.cs.toronto.edu/~kriz/cifar-10-python.tar.gz>
- Citation requested by source: Krizhevsky, Alex. "Learning Multiple Layers of
  Features from Tiny Images." Technical Report, University of Toronto, 2009.

License position: the official source requests citation but does not provide an
explicit redistribution license suitable for carrying the pixels in this
Apache-2.0 repository. The repo does not commit the subset. Reproducers should
obtain CIFAR-10 from the official University of Toronto source and regenerate
the local subset.

Regenerate:

```bash
uv sync --extra dev
uv run python scripts/datasets/prepare_ic.py
```

That command downloads `cifar-10-python.tar.gz`, extracts the official test
batch, writes `data/mcu_subsets/ic/subset_v1.npz`, and does not publish to
Hugging Face. Maintainer publishing, if ever needed, requires the explicit
`--publish` flag.

## AD: DCASE 2020 Task 2 / ToyADMOS ToyCar

The AD subset is a deterministic class-balanced set of 100 log-mel feature
vectors derived from the ToyCar test partition of the DCASE 2020 Task 2
development dataset.

Upstream:

- Source: <https://zenodo.org/records/3678171>
- Dataset: DCASE 2020 Challenge Task 2 Development Dataset.
- Machine type used by signal-bench: ToyCar.
- License: Creative Commons Attribution-NonCommercial-ShareAlike 4.0
  International (CC BY-NC-SA 4.0).
- Citation requested by source includes the ToyADMOS paper and the DCASE 2020
  Task 2 description paper.

License position: CC BY-NC-SA 4.0 is not compatible with redistributing derived
feature data as part of this Apache-2.0 repository. The repo does not commit the
subset. Reproducers should obtain DCASE 2020 Task 2 from Zenodo and regenerate
the local feature subset.

Regenerate:

```bash
uv sync --extra dev --extra ad-prep
uv run python scripts/datasets/stage_dcase.py
uv run python scripts/datasets/prepare_ad.py
```

The staging command downloads `dev_data_ToyCar.zip` from Zenodo, verifies the
published checksum, and extracts outside the repository under
`~/data/dcase-2020-task2/` by default. The prepare command extracts the MLPerf
Tiny-compatible log-mel features, writes `data/mcu_subsets/ad/subset_v1.npz`,
and does not publish to Hugging Face. Maintainer publishing, if ever needed,
requires the explicit `--publish` flag.

## Reference Models

The reference TFLite models under `models/reference/**` are unmodified MLCommons
Tiny artifacts pinned to commit `5dae3296bd899ed58a65311a8e6fd91d83f664ab`.
Each task directory has a `provenance.yaml` recording the source URL, SHA-256,
byte count, and Apache-2.0 license URL. The root `NOTICE` preserves the MLPerf
Tiny attribution required for Apache-2.0 redistribution.

Verify local bytes:

```bash
uv run python - <<'PY'
import hashlib
import pathlib
import yaml

manifest = yaml.safe_load(open("models/reference/manifest.yaml"))
for task, info in manifest["tasks"].items():
    path = pathlib.Path("models/reference") / info["directory"] / info["canonical_file"]
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual == info["sha256"], task
    print(f"{task}: OK")
PY
```
