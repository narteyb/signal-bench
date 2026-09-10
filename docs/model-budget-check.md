# Post 1 Model Budget Check

## Executive Matrix

T2.5 verifies whether the three Post 1 TinyML models can be attempted on the
three Tier 1 MCU targets. The result is better than the early risk framing:
all nine MCU cells are static-budget `FITS`. The important correction is that
the `.tflite` model bytes are compiled as `const` data and live in Flash, while
SRAM is consumed by the TFLM tensor arena, stack, heap, and framework state.

| Task | F401RE 96KB SRAM / 512KB Flash | Nano 33 256KB SRAM / 960KB Flash | ESP32-S3 320KB internal SRAM / 1MB app Flash |
|---|---:|---:|---:|
| KWS | FITS: 36KB arena, 54KB SRAM estimate, 153KB Flash estimate | FITS: 96KB SRAM, 215KB Flash | FITS: 77KB SRAM, 450KB Flash |
| IC | FITS: 56KB arena, 75KB SRAM estimate, 198KB Flash estimate | FITS: 116KB SRAM, 260KB Flash | FITS: 97KB SRAM, 494KB Flash |
| AD | FITS: 12KB arena, 30KB SRAM estimate, 376KB Flash estimate | FITS: 71KB SRAM, 438KB Flash | FITS: 52KB SRAM, 673KB Flash |

The IC/F401RE cell remains the closest SRAM case at 74,884 bytes, leaving
23,420 bytes of SRAM margin before runtime jitter, USB buffers, and Phase 5
task glue. It is not marked `WORKAROUND` because it stays below the 80% warning
threshold, but Phase 5 should verify it first on real firmware.

## Methodology

`tools/estimate_tflm_arena.py` loads each reference `.tflite` model through
LiteRT, allocates tensors, and inspects tensor metadata. LiteRT does not expose
TFLM's exact `RecordingMicroAllocator` arena-used value from Python, so the
script uses a conservative static heuristic:

1. exclude constant weights and biases from SRAM accounting;
2. identify input, output, and intermediate runtime tensors;
3. estimate the arena as the larger of three copies of the largest runtime
   tensor plus 8KB scratch, or one third of all runtime tensor bytes plus 8KB;
4. round the result up to the next 4KB boundary.

This matches the TFLM memory model at planning level: the tensor arena holds
inputs, outputs, intermediate activations, scratch buffers, and allocator
metadata, while model FlatBuffer bytes are application-owned constant data. The
exact Phase 5 firmware should replace these estimates with the
`RecordingMicroAllocator` byte count after `AllocateTensors()`.

For target totals, the analysis adds the measured scaffold static RAM from T1
plus the estimated arena plus a 16KB runtime reserve for stack, heap, serial
buffers, and task glue. Flash totals add measured scaffold Flash, model bytes,
and an 80KB TFLM runtime estimate. The Flash estimate is intentionally
conservative; optimized op resolvers and CMSIS-NN builds may reduce it.

## Target Budgets

The target budgets are taken from the compile-tested firmware scaffolds:

- F401RE: 98,304 bytes SRAM, 524,288 bytes Flash; scaffold 1,156 bytes RAM and
  17,452 bytes Flash.
- Nano 33 BLE Sense Rev2: 262,144 bytes SRAM, 983,040 bytes Flash; scaffold
  42,464 bytes RAM and 79,180 bytes Flash.
- ESP32-S3: conservative no-external-PSRAM budget of 327,680 bytes internal
  SRAM and 1,048,576 bytes app-partition Flash; scaffold 23,468 bytes RAM and
  313,921 bytes Flash. The board has more physical Flash, and some variants add
  PSRAM, but Post 1 should not depend on external RAM for Tier 1 comparability.

## Per-Task Findings

KWS is the safest all-target task. The model is 53,936 bytes in Flash and the
arena estimate is 36,864 bytes. Even on F401RE, total estimated SRAM is 54,404
bytes, or about 55% of available SRAM. This leaves enough margin for Phase 5's
input fixture loader and protocol plumbing.

IC is the meaningful crunch point. The model is only 98,496 bytes in Flash, but
its ResNet-style activations drive the largest arena estimate: 57,344 bytes.
F401RE total SRAM is estimated at 74,884 bytes, about 76% of SRAM. This is a
valid `FITS` cell, but Phase 5 should keep the op resolver narrow, avoid extra
image buffers, and confirm the actual TFLM arena before running the full
100-inference measurement batch.

AD reverses the early risk assumption. The model is large on disk and in Flash
at 276,976 bytes, but its dense-autoencoder activations are small. The SRAM
arena estimate is only 12,288 bytes. F401RE Flash reaches 376,348 bytes, or
about 72% of Flash, so Flash is the tighter AD constraint but still has roughly
148KB of margin before the 512KB limit.

## Workarounds

No cell is currently marked `WORKAROUND` or `WONT_FIT`. If Phase 5's exact
allocator measurements exceed this static estimate, the first workaround is a
narrow `MicroMutableOpResolver` plus optimized kernels, especially CMSIS-NN on
Cortex-M4 targets. If IC/F401RE crosses 90% SRAM in real firmware, reduce
runtime buffers before changing model variants.

## Post 1 Narrative

T2.5 does not produce a "too large to fit" headline. Instead, the useful Post 1
finding is subtler: model byte size alone is a poor proxy for MCU feasibility.
AD looks impossible if the 277KB model is treated as SRAM, but it is plausible
once Flash and arena memory are separated. IC is the actual SRAM pressure case.
That distinction is worth carrying into the Signal Report because it teaches
readers how TinyML memory limits really fail.

## Phase 5 Handoff

Phase 5 should treat the manifest `targets` blocks as the attempt matrix, not
as final hardware proof. Every cell starts as `FITS`, but the firmware must log
actual tensor arena bytes after `AllocateTensors()`, final firmware Flash/RAM
from the linker report, and any target-specific resolver or kernel choices.
If real allocation differs by more than 20% from this estimate, update this
document and the manifest before publishing Post 1.

## References

- TensorFlow Lite Micro memory management:
  https://android.googlesource.com/platform/external/tensorflow/+/a444526fa7a096ead6096b7e36c8da4371d6380b/tensorflow/lite/micro/docs/memory_management.md
- MLCommons MLPerf Inference: Tiny benchmark summary:
  https://mlcommons.org/benchmarks/inference-tiny/
