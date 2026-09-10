# AD MCU Subset Regeneration

`subset_v1.npz` is not committed because it is derived from DCASE 2020 Task 2 /
ToyADMOS ToyCar, whose upstream Zenodo record is licensed CC BY-NC-SA 4.0. That
license is not compatible with redistributing the derived feature subset as part
of this Apache-2.0 repository.

Regenerate the deterministic 100-vector feature subset from the upstream source:

```bash
uv sync --extra dev --extra ad-prep
uv run python scripts/datasets/stage_dcase.py
uv run python scripts/datasets/prepare_ad.py
```

The staging script downloads the ToyCar archive from Zenodo record `3678171`,
verifies Zenodo's checksum, and extracts it outside the repository under
`~/data/dcase-2020-task2/` by default. The prepare script writes
`data/mcu_subsets/ad/subset_v1.npz` and does not publish to Hugging Face.
Maintainer publishing requires the explicit `--publish` flag.
