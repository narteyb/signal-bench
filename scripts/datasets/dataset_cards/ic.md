---
license: other
task_categories:
  - image-classification
language:
  - en
size_categories:
  - 1K<n<10K
tags:
  - tinyml
  - mlperf-tiny
  - edge-ai
  - benchmarking
  - signal-bench
  - cifar-10
---

# Signal-Bench IC Test Set v1

## What this is

The CIFAR-10 test set, packaged for maintainer-only signal-bench experiments.
The public repository does not redistribute this dataset or its MCU subset
because CIFAR-10's official source does not provide an explicit redistribution
license suitable for an Apache-2.0 repository.

This is **not** a new dataset. It is a packaging of CIFAR-10's standard test
split with no modification for private maintainer use.

## Source attribution

CIFAR-10 was collected by Alex Krizhevsky, Vinod Nair, and Geoffrey Hinton at the University of Toronto. The original dataset is available at https://www.cs.toronto.edu/~kriz/cifar.html.

Citation:
> Krizhevsky, Alex. "Learning multiple layers of features from tiny images." (2009).

## Processing

Passthrough. CIFAR-10 test images are stored as-is at 32×32×3 uint8 (RGB). No normalization, no cropping, no augmentation. The reference MLPerf Tiny image classification model (`pretrainedResnet_quant.tflite`) applies its own normalization internally during inference.

## Subset structure

- **Samples:** 10,000 (full CIFAR-10 test set)
- **Classes:** 10 (airplane, automobile, bird, cat, deer, dog, frog, horse, ship, truck)
- **Class balance:** 1,000 per class
- **Feature shape:** 32×32×3 uint8 RGB

## Intended use

Benchmark evaluation for edge AI image classification. Designed to pair with MLPerf Tiny's reference ResNet-8 model.

The Hugging Face dataset is private. Public reproducers should fetch CIFAR-10
from the official University of Toronto source and run
`uv run python scripts/datasets/prepare_ic.py`.

## MCU subset

A deterministic 100-sample stratified subset (10 samples per class, `seed=42`) is generated at `data/mcu_subsets/ic/subset_v1.npz` for flashing into MCU firmware as C arrays. To regenerate: `uv run python scripts/datasets/prepare_ic.py`.

## Citation

If you use this dataset in published work, cite both the original CIFAR-10 paper and signal-bench:

```bibtex
@misc{signalbench-ic-v1,
  author = {Brown, Daniel},
  title = {Signal-Bench IC Test Set v1},
  year = {2026},
  publisher = {Agoo AI},
  howpublished = {\url{https://huggingface.co/datasets/narteybrown/signal-bench-ic-v1}},
}
```

## Limitations

CIFAR-10 is a small, well-studied dataset with known limitations: low resolution, limited class diversity, no environmental variation. Benchmark results using this set should be understood as a measurement of inference performance on a standard reference workload, not as evaluation against real-world deployment conditions.

The MCU subset (100 samples) is small enough that per-class accuracy estimates have wide confidence intervals; it is intended for latency and energy measurement, not statistical accuracy reporting.

## License

CIFAR-10 is distributed under the terms documented at https://www.cs.toronto.edu/~kriz/cifar.html. That source requests citation but does not provide an explicit redistribution license suitable for public redistribution in this Apache-2.0 repository.
