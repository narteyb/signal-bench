# Chart Vocabulary

The visual + theme-application contract between signal-bench's chart producer
(`src/signal_bench/synth/chart_data.py`, T3.5) and its rendering consumers —
primarily a downstream Signal Reports renderer, but implementation-agnostic by
design.

This doc is the visual complement to [`chart-data-spec.md`](chart-data-spec.md).
That spec covers the *algorithmic* contract (median-of-runs aggregation,
target-capability ordering, file output conventions). This doc covers the
*visual* contract (colors, fonts, axis treatments, theme application).

The two are independent. Algorithmic decisions are stable when colors change;
visual decisions hold even if the aggregator is rewritten. Cross-reference them
together when implementing either side.

## 1. Purpose & scope

**In scope.**

- The JSON contract between signal-bench's chart producer and any consumer that
  renders Chart.js v4 from that JSON.
- The visual vocabulary that a downstream blog renderer applies on top of that
  JSON — color roles, typography, axis conventions, legend + tooltip
  treatments, annotation conventions.
- The boundary between "what the producer emits" (structural) and "what the
  consumer applies" (theme).

**Out of scope.**

- Specific Post 1 chart specs (which charts go where, what each one shows).
  That's T4.5.
- Verification rendering of Post 1 charts in the blog mockup. That's T4.7.
- Chart.js plugin selection (annotation, datalabels, etc.). The consumer
  picks plugins; the producer stays plugin-agnostic where possible.
- Accuracy charts. Out of scope until Phase 5 produces accuracy data
  (per [chart-data-spec.md](chart-data-spec.md)).

## 2. Producer contract

The producer is `src/signal_bench/synth/chart_data.py::write_chart_json_files()`,
which writes three JSON files under `data/charts/` per the matrix export:

- `data/charts/hardware-curve.json` — line chart, target capability vs median
  latency (log y-axis)
- `data/charts/wh-comparison.json` — grouped bar chart, target vs mWh/1000
  inferences (log y-axis)
- `data/charts/variance-illustration.json` — bar chart, per-run latency spread
  (defaults to KWS on Pi 5)

### 2.1. Top-level shape

Each file is a single JSON object of the form:

```json
{
  "type": "line" | "bar" | "scatter",
  "data": {
    "labels": ["F401RE", "Nano 33", ...],
    "datasets": [
      {
        "label": "Series name",
        "data": [1.2, 3.4, null, ...]
        // OPTIONAL per-series fields — see §2.2
      }
    ]
  },
  "options": {
    "scales": { ... },
    "plugins": { ... }
  }
}
```

This matches Chart.js v4's expected config shape. A consumer that does
`new Chart(ctx, JSON.parse(fileContents))` gets a working chart with
Chart.js defaults; the theme application in §3 + §4 layers on top.

### 2.2. What the producer DOES emit

- **`type`**: `"line"`, `"bar"`, or `"scatter"`. Locked per chart per T3.5
  (D26-A through D26-I in T3.5's session report).
- **`data.labels`**: ordered category strings. For the matrix charts, target
  IDs in capability-ascending order: `F401RE → Nano 33 → ESP32-S3 → Pi 5 →
  Jetson Orin Nano → M1 Max → Modal A10G`. Locked per
  [chart-data-spec.md §"Hardware Curve"](chart-data-spec.md).
- **`data.datasets[].label`**: short human-readable series name (KWS, IC, AD).
- **`data.datasets[].data`**: numerical values. Cells with no usable runs
  emit `null`, which Chart.js renders as gaps.
- **`data.datasets[].tension`** (line only): 0.25 for hardware-curve. Soft
  smoothing without overshoot.
- **`data.datasets[].spanGaps`** (line only): `false`. Gaps in data stay
  gaps; the line doesn't bridge missing cells.
- **`options.scales.y.type`**: `"logarithmic"` for hardware-curve + wh-comparison
  per [chart-data-spec.md](chart-data-spec.md) (orders-of-magnitude spread
  between MCU and cloud targets).
- **`options.scales.y.title.text`**: axis label string (e.g., `"Median
  latency (us, log scale)"`).
- **`options.plugins.legend.position`**: `"top"`.
- **`options.responsive`**: `true`.
- For variance-illustration, a per-chart `meta` field carrying run-count +
  partial-inference details. Consumed by the consumer's tooltip/sidecar
  rendering; ignored by Chart.js itself.

### 2.3. What the producer DOES NOT emit

The producer is **structurally complete and visually neutral**. It does not
emit:

- **Colors** — no `borderColor`, `backgroundColor`, `pointBorderColor`, etc.
  per [chart-data-spec.md](chart-data-spec.md): *"T3.5 deliberately does not
  hardcode a color palette; the blog can apply brand styling at render time."*
- **Fonts** — no `font.family`, `font.size` anywhere in `options`.
- **Padding/margin** — no `layout.padding`, `plugins.title.padding`, etc.
- **Plugin instances** — no `plugins: { annotation: {...} }` or similar.
  The consumer wires plugins.
- **Per-dataset visual config** — `pointRadius`, `pointHoverRadius`,
  `borderWidth`, etc. are theme decisions, not producer decisions.

This separation means the producer's JSON can render in any Chart.js v4
consumer (light theme, dark theme, embedded notebook, plain HTML demo) and
look correct-by-default. Theme application is an additive merge, not a
replacement.

### 2.4. Backward-compat versioning

Breaking changes to the JSON shape require:

1. Bump a version marker (the producer doesn't currently emit one; introducing
   `_meta.version` is the recommended path — see §6 "Future evolution").
2. Coordinate both producer (`chart_data.py`) and consumer
   (`_signal_report_data.html.erb`) on the new shape.
3. Note the change in this doc's revision history (start that history when
   the first break happens).

Additive changes (new optional fields the consumer can ignore) don't need
version bumps.

## 3. Consumer contract

The consumer (a downstream blog renderer, or any future renderer) is responsible
for **theme application** — merging the producer's structural JSON with a
visual theme to produce the final Chart.js config.

### 3.1. Theme application algorithm

The consumer:

1. Loads `data/charts/<name>.json` (or whatever per-page chart payload).
2. Constructs a theme object holding colors, fonts, and visual defaults
   per §4.
3. Merges theme into the loaded config — typically a deep-merge where the
   producer's structural fields win and the theme fills in unset visual
   fields.
4. Per-dataset, assigns colors from the palette in §4.1 in dataset-index
   order (dataset 0 → primary, dataset 1 → secondary, fallback to a small
   cycling palette for 3+).
5. Calls `new Chart(ctx, mergedConfig)`.

The merge is one-way: theme augments, never overrides. If the producer
emitted `options.scales.y.type === "logarithmic"`, the theme respects that.
If the producer didn't emit a `font.family`, the theme provides one.

### 3.2. CSS variables vs hex values

Colors flow through **CSS variables**, not baked hex values, so dark/light
mode and any future theme adjustments propagate without re-running the
producer.

Example consumer-side pattern (idiomatic Chart.js v4):

```javascript
const styles = getComputedStyle(document.documentElement);
const theme = {
  signal: styles.getPropertyValue('--color-signal').trim(),
  amber: styles.getPropertyValue('--color-amber').trim(),
  heading: styles.getPropertyValue('--text-heading').trim(),
  secondary: styles.getPropertyValue('--text-secondary').trim(),
  dim: styles.getPropertyValue('--text-dim').trim(),
  border: styles.getPropertyValue('--border').trim(),
  bg: styles.getPropertyValue('--bg-surface').trim(),
};
// then merge theme into the loaded chart config
```

Theme switching (dark ↔ light) re-reads the CSS variables and re-applies the
theme to existing charts (Chart.js v4 supports config updates without
re-instantiation).

## 4. Visual vocabulary

These values define the Signal Reports chart theme as of 2026-05-15. Where
this doc needs a value the theme token set does not define, the doc names the
closest existing variable and flags the substitution.

### 4.1. Color palette

| Role | CSS variable | Dark theme | Light theme |
|---|---|---|---|
| Primary data series | `--color-signal` | `#00D4AA` | `#00D4AA` |
| Primary data series (deeper variant for hover / emphasis) | `--color-signal-dark` | `#009A7A` | `#009A7A` |
| Secondary data series / highlight | `--color-amber` | `#F0C674` | `#F0C674` |
| Tertiary data series (3-series qualitative palette) | `--color-violet` | `#A78BFA` | `#A78BFA` |
| Heading text (axis titles, chart titles) | `--text-heading` | `#F0F6FC` | `#0D1117` |
| Body text (axis labels, legend) | `--text-secondary` | `#8B949E` | `#57606A` |
| Dim text (sub-labels, ticks, annotations, caption text) | `--text-dim` | `#484F58` | `#687078` |
| Grid lines, chart borders | `--border` | `rgba(139, 148, 158, 0.15)` | `#D0D7DE` |
| Chart background | `--bg-surface` | `#1C2128` | `#FFFFFF` |

**Dataset-index color assignment:**
- Dataset 0: `--color-signal` (primary)
- Dataset 1: `--color-amber` (secondary)
- Dataset 2: `--color-violet` (tertiary). Locked per D67-G; see note below.
- Dataset 3+: cycling palette to be defined when a 4+ series chart enters
  scope.

**D67-G (2026-05-16):** Third categorical data series token resolved as
`--color-violet`. Prior placeholder `--color-signal-dark` rejected on two
grounds: (1) role-collision — it is reserved per the row above as the
primary-series hover/emphasis state; (2) perceptual — lightness variation
of the primary hue reads as a sequential scale, not as a categorical peer.
Coral was considered and rejected on proximity-to-amber grounds (~30–60° on
the color wheel; confusability at small sizes and for colorblind readers).
The teal–orange–violet trio aligns with ColorBrewer Set2 / Dark2 and
Tableau Color Blind 10 qualitative palettes. The pillar/chart dual-role
pattern matches the established `--color-amber` precedent (P3 pillar
accent + chart secondary series); `--color-violet` joins under the same
pattern (P4 pillar accent + chart tertiary series). Source: Signal Reports
theme token set, defined within the Tailwind v4 `@theme {}` block.

### 4.2. Typography

The Signal Reports theme exposes three font families:

| Use | CSS variable | Family |
|---|---|---|
| Display headings | `--font-display` | `"Outfit", sans-serif` |
| Body text | `--font-body` | `"IBM Plex Sans", sans-serif` |
| Mono / numeric | `--font-mono` | `"JetBrains Mono", monospace` |

**Chart-specific typography assignment:**

| Surface | Font | Size | Color |
|---|---|---|---|
| Axis tick labels (numbers, target names) | `--font-mono` | 11px | `--text-secondary` |
| Axis title text | `--font-mono` | 10px | `--text-dim` |
| Chart title (if rendered) | `--font-body` | 12-13px | `--text-heading` |
| Legend labels | `--font-mono` | 11px | `--text-secondary` |
| Tooltip title | `--font-mono` | 11px | `--text-heading` |
| Tooltip body | `--font-body` | 12px | `--text-secondary` |
| Annotation text | `--font-mono` | 10px italic | `--text-dim` |
| Caption beneath chart | `--font-mono` | 10.5px | `--text-dim`, right-aligned, letter-spacing 0.04em |

Rationale: numbers + technical labels use mono to signal "engineering
surface" (matches the broader signal-bench / Signal Reports brand grammar).
Prose (chart titles, tooltip body) uses Plex Sans for legibility.

### 4.3. Chart container conventions

The downstream blog renderer wraps every Chart.js canvas in a `.chart-wrap` div.
The wrap provides:

- `background: var(--bg-surface)`
- `border: 1px solid var(--border)`
- `border-radius: 12px`
- `padding: 28px 28px 22px`
- Inner `canvas { max-height: 360px; }` — caps vertical height so a chart
  doesn't dominate the page when rendered at wide-screen widths

A `<figcaption class="chart-caption">` beneath the canvas provides the
caption per §4.2's "Caption beneath chart" row.

Consumers other than the downstream blog renderer can replicate this wrap or substitute
their own — the producer's JSON doesn't care.

### 4.4. Tooltip treatment

```javascript
plugins.tooltip = {
  backgroundColor: 'var(--bg-surface)',
  borderColor: 'var(--border)',
  borderWidth: 1,
  titleFont: { family: 'var(--font-mono)', size: 11 },
  titleColor: 'var(--text-heading)',
  bodyFont: { family: 'var(--font-body)', size: 12 },
  bodyColor: 'var(--text-secondary)',
  padding: 12,
  // For variance-illustration: bodyCallback emits runId + min/max
  // from the producer's per-chart `meta` field.
};
```

Note: Chart.js v4 expects literal color/font values in config — wrap the
`getComputedStyle().getPropertyValue()` reads from §3.2 before passing.

### 4.5. Legend treatment

```javascript
plugins.legend = {
  position: 'top',                          // producer emits this
  labels: {
    font: { family: 'var(--font-mono)', size: 11 },
    color: 'var(--text-secondary)',
    padding: 18,
    boxWidth: 14,
  },
};
```

## 5. Chart-type conventions

These apply across every chart the producer emits.

### 5.1. Axis types

- **Linear y-axis**: percentage data, agreement scores, normalized values
  (range bounded, near-zero matters as much as near-max).
- **Logarithmic y-axis**: any data spanning >2 orders of magnitude. Locked
  per [chart-data-spec.md](chart-data-spec.md) for hardware-curve +
  wh-comparison; the producer emits `type: "logarithmic"` and the consumer
  preserves it. Linear scale would compress F401RE-vs-Modal-A10G data into
  unreadable noise.
- **Categorical x-axis**: target-capability ordering as locked in §2.2.

### 5.2. Grid

- **y-axis**: grid lines at tick positions, color `--border`, no axis-line
  border (`grid.drawBorder: false` in Chart.js v4).
- **x-axis**: no grid (`grid.display: false`). Categorical x doesn't need
  vertical guides; the spacing carries the information.

### 5.3. Tick density

Chart.js v4 default automatic-tick computation. Bias toward fewer ticks for
readability — the consumer may set `ticks.maxTicksLimit` per chart if
default density is too noisy. Producer doesn't constrain.

### 5.4. Series markers (line charts)

- **Point radius**: 4px default, 6px on hover
- **Line width**: 2px
- **Line tension**: 0.25 (already in producer JSON for hardware-curve)

### 5.5. Bar charts

- **Border**: none (flat fills)
- **Bar thickness**: Chart.js v4 auto by default; consumer doesn't override
  unless a specific chart's narrative needs thicker/thinner bars
- **Grouped bars**: dataset-index color assignment from §4.1; bars within a
  group share the dataset's color

### 5.6. Annotation conventions

When a chart needs annotations (truncation markers, threshold lines, or axis
callouts):

- Lives in the consumer-side config under `options.plugins.annotation`
  (requires `chartjs-plugin-annotation`).
- The producer **may** emit a hint in its per-chart `meta` field (e.g.,
  `meta.annotations: [{type: "line", value: 0.85, label: "threshold"}]`)
  but the consumer is the source of truth for actual Chart.js annotation
  syntax.
- Text: `--font-mono` 10px italic, color `--text-dim`.
- Position: right-aligned for end-of-axis annotations; top-right for
  chart-level annotations.

## 6. Cross-references

- [`chart-data-spec.md`](chart-data-spec.md) — algorithmic contract
  (aggregation, output files, per-chart structural decisions).
- [`methodology.md`](methodology.md) — the broader benchmarking
  methodology this charting serves.
- `src/signal_bench/synth/chart_data.py` — the producer implementation.
  Its docstring cross-references this doc.
- Downstream Signal Reports renderer — the consumer implementation should
  reference this doc as the source of truth for theme application.

## 7. Future evolution

### 7.1. Anticipated additions

- **`_meta` provenance field at top level.** Recommended addition by D67-E:
  signal-bench-specific extension carrying source commit, generated_at,
  task, version. Currently the producer doesn't emit `_meta`; adding it
  is additive (consumers ignore unknown top-level keys) and a non-breaking
  change. Worth a follow-up code prompt to wire into `write_chart_json_files()`.
- **Third-series color** resolved by T4.5-AMEND-2-REVISED. See D67-G in
  §4.1 for the lock: `--color-violet` (sourcing to the Signal Reports pillar
  accent palette) serves as the
  categorical third data series. Coral was considered and rejected on
  proximity-to-amber grounds; lightness variation of `--color-signal-dark`
  was rejected on perceptual grounds (categorical peer hues require
  distinct hues per ColorBrewer Set2 conventions, not a sequential scale).
- **Accuracy charts** out of scope until Phase 5 produces accuracy data.
  When they enter scope, the vocabulary here likely covers them
  (categorical x, percentage y on linear scale, same typography). Confirm
  + extend this doc when the data arrives.

### 7.2. Breaking-change protocol

When the JSON contract changes incompatibly:

1. Bump `_meta.version` (`"1.0"` → `"2.0"` for breaks; `"1.0"` → `"1.1"`
   for additive-only).
2. Update both `chart_data.py` (producer) and
   `_signal_report_data.html.erb` (consumer) in the same PR.
3. Update this doc with a "Version history" section noting what changed.

### 7.3. Plugin pinning

Chart.js v4 is the current rendering target. If the consumer ever migrates
to a different chart library (D3, recharts, plain SVG), the producer's
JSON shape is library-agnostic enough that only the consumer migrates.
The structural fields (`type`, `data.labels`, `data.datasets[].data`,
`options.scales.y.type`) carry semantic meaning across libraries; only the
options-level details (legend position, tooltip config) are Chart.js-specific.

### 7.4. Theme variants

This doc locks against the Signal Reports chart theme. If a different rendering
context (a slide deck export, a print-PDF version, a third-party embed)
needs different theme application, the path is: define a second theme
object using the same role names (primary, secondary, heading, etc.) but
different color/font sources. The producer's JSON doesn't change.

## 8. Revision history

- 2026-05-15 · v1 · Initial codification by PQ-2. Locks visual vocabulary
  against the Signal Reports chart theme as of that date. Producer-side
  cross-reference added to `chart_data.py` docstring.
- 2026-05-16 · T4.5-AMEND-2-REVISED · Added `--color-violet` row to §4.1
  dataset-index block as third categorical data series token (D67-G).
  Sourcing convention preserved; no §4 preamble amendment required. Historical
  draft chart notes were updated from `--color-signal-dark` to
  `--color-violet`.
- 2026-05-16 · CHART-BUILDERS-POST1 · No direct vocabulary edits. Logged
  for traceability because the prompt added `build_variance_strip` and
  tier filter capability to `chart_data.py`, which the vocabulary doc
  references indirectly through §4.1's color-role assignments. New chart
  producer surface: six JSON files (3 legacy + 3 tier1 variants).
- 2026-05-16 · CHART-WORKSTREAM-CLEANUP · Closed §7.1 "third-series color"
  bullet by pointing at D67-G; added this revision-history entry and the
  two above for traceability.
