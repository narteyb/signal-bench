# IC MCU Subset Regeneration

`subset_v1.npz` is not committed because CIFAR-10's official source requests
citation but does not provide an explicit redistribution license suitable for
carrying the pixels in this Apache-2.0 repository.

Regenerate the deterministic 100-image subset from the official CIFAR-10 source:

```bash
uv sync --extra dev
uv run python scripts/datasets/prepare_ic.py
```

The script downloads:

`https://www.cs.toronto.edu/~kriz/cifar-10-python.tar.gz`

Citation requested by the source:

Krizhevsky, Alex. "Learning Multiple Layers of Features from Tiny Images."
Technical Report, University of Toronto, 2009.

The normal regeneration command writes `data/mcu_subsets/ic/subset_v1.npz` and
does not publish to Hugging Face. Maintainer publishing requires the explicit
`--publish` flag.
