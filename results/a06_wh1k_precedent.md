# A06 Wh/1000 Literature Precedent

Generated: 2026-06-30

## Finding

`Wh/1000 inferences` was not found as a verbatim standard metric in the checked
MLPerf Tiny material. The closest established metric is energy per inference,
usually reported as `uJ/inf`, `mJ/inf`, or `Energy/Inf`.

The Post 1 metric should therefore be framed as a derived presentation unit: it
is the same energy-per-inference quantity multiplied by 1000 and expressed in
watt-hours for readability alongside board-level power measurements.

## Evidence

MLCommons describes MLPerf Tiny as measuring task performance for tiny systems
and lists the standard Tiny tasks and quality targets. The public results
repositories report performance, accuracy, and, for power submissions, energy
per inference.

Examples from MLPerf Tiny v1.0 checked locally:

- STMicroelectronics NUCLEO-L4R5ZI KWS energy result:
  `Median energy cost is 3371.738 uJ/inf`.
- STMicroelectronics NUCLEO-L4R5ZI AD energy result:
  `Median energy cost is 322.977 uJ/inf`.

The MLPerf Power paper and MLCommons summary describe energy efficiency as a
first-class benchmark concern and emphasize physical power measurement across
scales from microwatts to megawatts. That supports the energy-normalized
framing, but it does not make `Wh/1000` itself a formal MLPerf Tiny unit.

TinyML Summit 2021 includes the keynote "miliJoules for 1000 Inferences:
Machine Learning Systems on Chip 'on the Cheap'", which is close in spirit and
scale: energy normalized to 1000 inferences. This supports using a
per-1000-inference presentation unit for reader comprehension, while still
anchoring the method in conventional energy-per-inference practice.

## Recommended Post Framing

Use this framing:

> Wh/1000 is a derived presentation unit: the underlying measurement is
> window-level energy divided by completed inference count, equivalent to the
> established energy-per-inference metric used in MLPerf Tiny-style reporting,
> then scaled to 1000 inferences and converted to watt-hours for readability.

Avoid calling `Wh/1000` an MLPerf Tiny standard unit.
