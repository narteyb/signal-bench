# KWS MCU Subset

`subset_v1.npz` is a deterministic 100-sample subset derived from Google Speech
Commands v0.02 and converted to MLPerf Tiny-compatible MFCC features.

License: CC BY 4.0. This data is not covered by the repository's Apache-2.0
license. Attribution and change notice are documented in
`docs/third-party-data.md`.

Regenerate:

```bash
uv sync --extra dev --extra kws-prep
uv run python scripts/datasets/prepare_kws.py
```
