# Post 1 Chart.js Smoke Harness

This directory is a self-contained Chart.js smoke harness for Post 1's three Signal Report charts. It is also the reference implementation for a downstream Signal Reports renderer: same data keys, same chart types, same task color mapping, and the same synthetic YAML used for visual verification.

The harness does not render the final blog post. It proves that the T4.6 Signal Report data shape can produce the three Post 1 charts before hardware data exists.

## How To Run

Serve the repository root, not this directory, so the harness can fetch the YAML files under `content/signal-reports/`:

```bash
python3 -m http.server 8765
```

Then open:

```text
http://localhost:8765/docs/post-1/smoke-harness/index.html
```

The default view loads `content/signal-reports/_synthetic-smoke-data.yml`. To verify the production Post 1 data path, open:

```text
http://localhost:8765/docs/post-1/smoke-harness/index.html?data=production
```

Opening `index.html` with `file://` will not work in modern browsers because `fetch()` cannot read local YAML files from disk. The local HTTP server is required.

## What It Shows

The first chart, `hardware_curve_tier1`, is a line chart of median latency across the Tier 1 MCU floor. It uses a logarithmic y-axis, three task-colored series, and a dashed `Future tiers ->` annotation at the first future-tier label. Pi 5, Hailo, Jetson, and M1 Max appear as axis labels only; no future-tier values are plotted.

The second chart, `energy_comparison_tier1`, is a grouped bar chart of Wh per 1000 inferences. It renders 9 bars total: three tasks across three MCU targets. The synthetic data spans roughly 9x from the smallest to largest Wh/1000 values, so the harness keeps the log y-axis specified in T4.5.

The third chart, `variance_strip_tier1`, is a scatter strip plot across all 9 cells. Individual non-partial runs are smoke-colored points; partial runs render as larger coral triangles with their `partial_reasons` in the tooltip. Cell means are task-colored horizontal line segments, standard-deviation bands are translucent task-colored boxes, and the jitter is deterministic so screenshots are reproducible across reloads.

## Data Files Consumed

The harness consumes two YAML files produced by T4.6:

```text
content/signal-reports/_synthetic-smoke-data.yml
content/signal-reports/2026-05-28-tinyml-reality-check-data.yml
```

The synthetic file is populated with fake values for local UI smoke testing. The production file carries the real Post 1 Tier 1 values and uses null future-tier points for tiers without data.

For T8.1, the variance run data may include partial markers in either object form (`{value, partial, partial_reasons}`) or the compact harness form (`[cell_index, value, {partial, partial_reasons}]`). The renderer normalizes both shapes before drawing, so the eventual server-side renderer can choose the clearer JSON shape while this static YAML stays compact.

For T8.2, a run value may be `null` when every relevant inference window fell
inside a telemetry gap. The strip plot does not draw those null points as zero;
when every run in a cell is null, it adds a small "telemetry gaps" annotation
over that cell. Partial-but-computable runs still render as coral triangles.

## How To Port To A Blog Renderer

Move the logic in `chart-config.js` into a browser-side module in the publishing application. Keep the three chart ids as the switching surface: `hardware_curve_tier1`, `energy_comparison_tier1`, and `variance_strip_tier1`.

Replace the harness's client-side `fetch()` plus `js-yaml` parse with server-side YAML loading. The server-rendered view should pass the already-parsed chart payload into a `data-chart` attribute or equivalent JSON script tag. Do not make the browser fetch YAML in production unless the publishing application explicitly chooses that architecture.

Replace the harness CSS variables with the site's existing CSS variables or theme tokens. The required color mapping is stable: KWS uses Signal Green, IC uses Amber, AD uses Coral, individual variance dots use Smoke, and axes use Slate.

Keep Chart.js version compatibility in mind when porting. This harness pins Chart.js 4.4.0 and chartjs-plugin-annotation 3.0.1. If the publishing application uses newer versions, verify the annotation API and log-scale tick formatting before shipping.

Wire the markdown chart markers from `content/posts/2026-05-28-tinyml-reality-check.md` to the renderer:

```text
<!-- chart: hardware_curve_tier1 -->
<!-- chart: energy_comparison_tier1 -->
<!-- chart: variance_strip_tier1 -->
```

The renderer should replace each marker with the correct chart container and caption, keyed by chart id.

## Dependencies And Versions

The harness uses CDN-pinned dependencies:

```text
Chart.js 4.4.0
chartjs-plugin-annotation 3.0.1
js-yaml 4.1.0
```

No package manager, bundler, application layer, or server-side renderer is required. The only server is Python's local static file server for development.

## Known Limitations

The screenshots are manual artifacts captured from the local harness. They are not CI assertions.

The production YAML uses the historical Signal Report chart keys where needed; the harness maps them to the three post-facing chart ids.

The strip plot uses a Chart.js scatter chart with numeric x positions and category labels generated by tick callbacks. This is more reliable than relying on categorical scatter behavior across Chart.js versions.

The future-tier marker uses chartjs-plugin-annotation. If the publishing application does not want that dependency, it can replace the annotation with a small local Chart.js plugin, but the visual behavior should stay the same.

## Screenshots

The expected screenshot artifacts are:

```text
screenshots/chart-1-hardware-curve.png
screenshots/chart-2-energy-comparison.png
screenshots/chart-3-variance-strip.png
screenshots/full-page.png
```

Use them as visual references when porting the harness into the publishing application. The published output does not need to be pixel-identical, but the chart structure, ordering, colors, axes, captions, and forward annotation should match.
