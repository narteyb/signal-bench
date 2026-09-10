# MCU Subsets

These files are compact benchmark-input subsets used by MCU firmware and
hardware reproduction scripts. They are third-party benchmark inputs, not
signal-bench measurement telemetry.

See `docs/third-party-data.md` for the license inventory and regeneration
instructions.

Current status:

- `kws/subset_v1.npz` remains redistributed under Google Speech Commands'
  CC BY 4.0 license with attribution.
- IC is not committed; regenerate it from the official CIFAR-10 source with
  `uv run python scripts/datasets/prepare_ic.py`.
- AD is not committed; regenerate it from DCASE 2020 Task 2 with
  `uv run python scripts/datasets/stage_dcase.py` followed by
  `uv run python scripts/datasets/prepare_ad.py`.
