// SPDX-License-Identifier: Apache-2.0
/* global Chart, jsyaml */

const CHART_SLOTS = [
  { id: "hardware_curve_tier1", sourceKeys: ["hardware_curve_tier1", "hardware_curve"] },
  { id: "energy_comparison_tier1", sourceKeys: ["energy_comparison_tier1"] },
  { id: "variance_strip_tier1", sourceKeys: ["variance_strip_tier1", "variance_illustration"] },
];

const DATA_FILES = {
  synthetic: "/content/signal-reports/_synthetic-smoke-data.yml",
  production: "/content/signal-reports/2026-05-28-tinyml-reality-check-data.yml",
};

const TASK_COLORS = {
  kws: "var(--signal-green)",
  ic: "var(--amber)",
  ad: "var(--coral)",
};

const TASK_FOR_CELL_INDEX = ["kws", "kws", "kws", "ic", "ic", "ic", "ad", "ad", "ad"];

const annotationPlugin = window.ChartAnnotation || window["chartjs-plugin-annotation"];
if (annotationPlugin) Chart.register(annotationPlugin);

document.addEventListener("DOMContentLoaded", () => {
  renderSmokeHarness().catch((error) => {
    showError(error);
  });
});

async function renderSmokeHarness() {
  const dataMode = new URLSearchParams(window.location.search).get("data") || "synthetic";
  const dataPath = DATA_FILES[dataMode] || DATA_FILES.synthetic;
  const response = await fetch(dataPath, { cache: "no-store" });

  if (!response.ok) {
    throw new Error(
      `Unable to load ${dataPath}. Serve this repo over HTTP, for example: python3 -m http.server 8765`,
    );
  }

  const reportData = jsyaml.load(await response.text());
  CHART_SLOTS.forEach(({ id, sourceKeys }) => {
    const chartData = sourceKeys.map((key) => reportData[key]).find(Boolean);
    if (!chartData) {
      markEmpty(id, `Missing ${sourceKeys.join(" or ")} in loaded YAML.`);
      return;
    }
    setCaption(id, chartData.caption_template || chartData.caption);
    renderChart(id, chartData);
  });
}

function renderChart(chartId, chartData) {
  if (isChartEmpty(chartData)) {
    markEmpty(chartId, "Awaiting Phase 5 data.");
    renderEmptyShell(chartId, chartData);
    return;
  }

  if (chartData.chart_type === "line") {
    renderLineChart(chartId, chartData);
  } else if (chartData.chart_type === "bar") {
    renderBarChart(chartId, chartData);
  } else if (chartData.chart_type === "scatter_strip") {
    renderStripPlot(chartId, chartData);
  } else {
    markEmpty(chartId, `Unsupported chart_type: ${chartData.chart_type}`);
  }
}

function renderLineChart(chartId, chartData) {
  const labels = chartData.x_axis.values;
  const futureTargets = chartData.future_tiers?.labels || [];
  const firstFutureTarget = futureTargets[0] || labels[labels.length - 1];
  const datasets = chartData.series.map((series) => ({
    label: series.label,
    data: normalizeLineSeries(series.data, labels),
    borderColor: cssColor(series.color),
    backgroundColor: transparent(cssColor(series.color), 0.16),
    borderWidth: 2,
    pointRadius: 4,
    pointHoverRadius: 6,
    tension: 0.25,
  }));

  new Chart(canvasContext(chartId), {
    type: "line",
    data: { labels, datasets },
    options: baseOptions({
      title: chartData.title,
      yTitle: "Latency (ms)",
      yScale: "logarithmic",
      annotations: extensionAnnotation(firstFutureTarget),
      futureTargets,
    }),
  });
}

function renderBarChart(chartId, chartData) {
  const labels = chartData.x_axis.values;
  const datasets = chartData.series.map((series) => ({
    label: series.label,
    data: series.data,
    backgroundColor: transparent(cssColor(series.color), 0.76),
    borderColor: cssColor(series.color),
    borderWidth: 1,
  }));

  new Chart(canvasContext(chartId), {
    type: "bar",
    data: { labels, datasets },
    options: baseOptions({
      title: chartData.title,
      yTitle: "Wh per 1000 inferences",
      yScale: chartData.y_axis.scale === "log" ? "logarithmic" : "linear",
    }),
  });
}

function renderStripPlot(chartId, chartData) {
  const labels = chartData.x_axis.values;
  const runSeries = chartData.series.find((series) => series.label === "Individual runs");
  const meanSeries = chartData.series.find((series) => series.label === "Cell mean");
  const bandSeries = chartData.series.find((series) => series.label === "±1 stddev band");

  const normalizedRunPoints = (runSeries.data || []).map((entry, index) => {
    const point = normalizeRunPoint(entry);
    return {
      x: point.cellIndex + jitter(labels[point.cellIndex], index),
      y: point.value,
      cellIndex: point.cellIndex,
      partial: point.partial,
      partialReasons: point.partialReasons,
      partialInferenceWarnings: point.partialInferenceWarnings,
    };
  });
  const runPoints = normalizedRunPoints.filter((point) => point.y !== null && point.y !== undefined);

  const datasets = [
    {
      label: "Individual runs",
      type: "scatter",
      data: runPoints,
      pointRadius: (context) => (context.raw?.partial ? 5 : 3),
      pointHoverRadius: (context) => (context.raw?.partial ? 7 : 5),
      pointStyle: (context) => (context.raw?.partial ? "triangle" : "circle"),
      pointBackgroundColor: (context) =>
        context.raw?.partial
          ? transparent(cssColor("var(--coral)"), 0.82)
          : transparent(cssColor(runSeries.color), 0.52),
      pointBorderColor: (context) =>
        context.raw?.partial
          ? cssColor("var(--coral)")
          : transparent(cssColor(runSeries.color), 0.78),
    },
  ];

  (meanSeries.data || []).forEach((mean, cellIndex) => {
    if (mean === null || mean === undefined) return;
    const task = TASK_FOR_CELL_INDEX[cellIndex];
    const color = cssColor(TASK_COLORS[task]);
    datasets.push({
      label: cellIndex === 0 ? "Cell mean" : "",
      type: "line",
      data: [
        { x: cellIndex - 0.28, y: mean },
        { x: cellIndex + 0.28, y: mean },
      ],
      borderColor: color,
      borderWidth: 3,
      pointRadius: 0,
      showLine: true,
      tension: 0,
    });
  });

  const annotations = {};
  (bandSeries.data || []).forEach((band, cellIndex) => {
    if (!band || band[0] === null || band[1] === null) return;
    const [low, high] = band;
    const task = TASK_FOR_CELL_INDEX[cellIndex];
    const color = cssColor(TASK_COLORS[task]);
    annotations[`stddev-${cellIndex}`] = {
      type: "box",
      xMin: cellIndex - 0.34,
      xMax: cellIndex + 0.34,
      yMin: low,
      yMax: high,
      backgroundColor: transparent(color, 0.15),
      borderColor: transparent(color, 0.28),
      borderWidth: 1,
    };
  });
  allGapCells(normalizedRunPoints, labels.length).forEach(({ cellIndex, count }) => {
    annotations[`all-gaps-${cellIndex}`] = {
      type: "label",
      xValue: cellIndex,
      yValue: 18,
      backgroundColor: transparent(cssColor("var(--midnight)"), 0.9),
      borderColor: transparent(cssColor("var(--coral)"), 0.8),
      borderRadius: 3,
      borderWidth: 1,
      color: cssColor("var(--coral)"),
      content: [`${count} telemetry`, "gaps"],
      font: { size: 11, weight: "700" },
      padding: 6,
    };
  });

  new Chart(canvasContext(chartId), {
    type: "scatter",
    data: { datasets },
    options: baseOptions({
      title: chartData.title,
      yTitle: "Latency (ms)",
      yScale: "logarithmic",
      annotations,
      xScale: {
        type: "linear",
        min: -0.5,
        max: labels.length - 0.5,
        grid: { color: transparent(cssColor("var(--slate)"), 0.08) },
        ticks: {
          color: cssColor("var(--smoke)"),
          stepSize: 1,
          callback: (value) => labels[value] || "",
          maxRotation: 45,
          minRotation: 30,
        },
        title: {
          color: cssColor("var(--slate)"),
          display: true,
          text: "Cell",
        },
      },
    }),
  });
}

function renderEmptyShell(chartId, chartData) {
  const labels = chartData.x_axis?.values || [];
  const datasets = (chartData.series || []).map((series) => ({
    label: series.label,
    data: [],
    borderColor: cssColor(series.color || "var(--smoke)"),
    backgroundColor: transparent(cssColor(series.color || "var(--smoke)"), 0.16),
  }));

  new Chart(canvasContext(chartId), {
    type: chartData.chart_type === "bar" ? "bar" : "line",
    data: { labels, datasets },
    options: baseOptions({
      title: chartData.title,
      yTitle: chartData.y_axis?.label || "Value",
      yScale: chartData.y_axis?.scale === "log" ? "logarithmic" : "linear",
    }),
  });
}

function baseOptions({
  title,
  yTitle,
  yScale,
  annotations = {},
  xScale = null,
  futureTargets = [],
}) {
  return {
    maintainAspectRatio: false,
    responsive: true,
    animation: false,
    interaction: { intersect: false, mode: "nearest" },
    plugins: {
      legend: {
        labels: {
          color: cssColor("var(--slate)"),
          filter: (item) => item.text !== "",
        },
        position: "top",
      },
      title: {
        color: cssColor("var(--bone)"),
        display: true,
        font: { size: 18, weight: "700" },
        padding: { bottom: 16 },
        text: title,
      },
      annotation: { annotations },
      tooltip: {
        callbacks: {
          label: (context) => {
            const label = `${context.dataset.label || "value"}: ${formatNumber(context.parsed.y)}`;
            if (context.raw?.partial) return `${label} (partial)`;
            return label;
          },
          afterLabel: (context) => {
            const lines = [
              ...formatLineMetadata(context.raw),
              ...(context.raw?.partialReasons || []),
              ...formatInferenceWarnings(context.raw?.partialInferenceWarnings || []),
            ];
            return lines;
          },
        },
      },
    },
    scales: {
      x:
        xScale ||
        {
          grid: { color: transparent(cssColor("var(--slate)"), 0.08) },
          ticks: {
            color: (context) => {
              const label = context.tick?.label;
              if (futureTargets.includes(label)) return transparent(cssColor("var(--slate)"), 0.58);
              return cssColor("var(--smoke)");
            },
          },
          title: { color: cssColor("var(--slate)"), display: true, text: "Target" },
        },
      y: {
        type: yScale,
        beginAtZero: yScale !== "logarithmic",
        grid: { color: transparent(cssColor("var(--slate)"), 0.1) },
        ticks: {
          color: cssColor("var(--smoke)"),
          callback: (value) => formatNumber(value),
        },
        title: { color: cssColor("var(--slate)"), display: true, text: yTitle },
      },
    },
  };
}

function extensionAnnotation(lastLabel) {
  return {
    postsExtension: {
      type: "line",
      xMin: lastLabel,
      xMax: lastLabel,
      borderColor: transparent(cssColor("var(--slate)"), 0.4),
      borderDash: [6, 4],
      borderWidth: 2,
      label: {
        backgroundColor: transparent(cssColor("var(--midnight)"), 0.85),
        color: cssColor("var(--smoke)"),
        content: "Future tiers →",
        display: true,
        font: { size: 12, weight: "600" },
        position: "end",
      },
    },
  };
}

function normalizeLineSeries(data, labels) {
  return (data || []).map((point, index) => {
    if (point === null || point === undefined) return null;
    if (typeof point === "number") return { x: labels[index], y: point };
    return { x: point.x || labels[index], ...point };
  });
}

function formatLineMetadata(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return [];
  const lines = [];
  if (raw.wh_per_1000 !== null && raw.wh_per_1000 !== undefined) {
    lines.push(`Energy: ${formatNumber(raw.wh_per_1000)} Wh/1000`);
  }
  if (raw.accuracy !== null && raw.accuracy !== undefined) {
    lines.push(`Accuracy: ${formatNumber(raw.accuracy * 100)}%`);
  } else if (raw.accuracy_note) {
    lines.push(`Accuracy: ${raw.accuracy_note}`);
  }
  return lines;
}

function isChartEmpty(chartData) {
  if (chartData.chart_type === "scatter_strip") {
    return (chartData.series || []).every((series) => !series.data || series.data.length === 0);
  }
  return (chartData.series || []).every((series) => !series.data || series.data.length === 0);
}

function markEmpty(chartId, message) {
  const card = document.querySelector(`#card-${chartId} .canvas-wrap`);
  const empty = document.querySelector(`#card-${chartId} .empty-state`);
  if (card) card.classList.add("is-empty");
  if (empty) empty.textContent = message;
}

function setCaption(chartId, caption) {
  const captionEl = document.getElementById(`caption-${chartId}`);
  if (captionEl) captionEl.textContent = (caption || "").trim();
}

function showError(error) {
  const errorEl = document.getElementById("error");
  errorEl.textContent = error.message;
  errorEl.classList.add("is-visible");
  console.error(error);
}

function canvasContext(chartId) {
  return document.getElementById(`chart-${chartId}`).getContext("2d");
}

function cssColor(token) {
  if (!token || !token.startsWith("var(")) return token || cssColor("var(--smoke)");
  const name = token.slice(4, -1).trim();
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function normalizeRunPoint(entry) {
  if (Array.isArray(entry)) {
    const meta = entry[2] || {};
    return {
      cellIndex: entry[0],
      value: entry[1],
      partial: Boolean(meta.partial),
      partialReasons: meta.partial_reasons || meta.partialReasons || [],
      partialInferenceWarnings:
        meta.partial_inference_warnings || meta.partialInferenceWarnings || [],
    };
  }
  return {
    cellIndex: entry.cell_index ?? entry.cellIndex,
    value: entry.value,
    partial: Boolean(entry.partial),
    partialReasons: entry.partial_reasons || entry.partialReasons || [],
    partialInferenceWarnings:
      entry.partial_inference_warnings || entry.partialInferenceWarnings || [],
  };
}

function allGapCells(points, labelCount) {
  const counts = Array.from({ length: labelCount }, () => ({ total: 0, nulls: 0 }));
  points.forEach((point) => {
    counts[point.cellIndex].total += 1;
    if (point.y === null || point.y === undefined) counts[point.cellIndex].nulls += 1;
  });
  return counts
    .map((item, cellIndex) => ({ ...item, cellIndex }))
    .filter((item) => item.total > 0 && item.total === item.nulls)
    .map((item) => ({ cellIndex: item.cellIndex, count: item.nulls }));
}

function formatInferenceWarnings(warnings) {
  if (!warnings.length) return [];
  return [`partial inference windows: ${warnings.length}`];
}

function transparent(hex, alpha) {
  const normalized = hex.replace("#", "");
  const bigint = parseInt(normalized, 16);
  const r = (bigint >> 16) & 255;
  const g = (bigint >> 8) & 255;
  const b = bigint & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function jitter(cellLabel, runIndex) {
  let hash = 0;
  const source = `${cellLabel}:${runIndex}`;
  for (let i = 0; i < source.length; i += 1) {
    hash = ((hash << 5) - hash + source.charCodeAt(i)) | 0;
  }
  const normalized = (Math.abs(hash) % 1000) / 1000;
  return (normalized - 0.5) * 0.3;
}

function formatNumber(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return value;
  if (numeric >= 100) return numeric.toFixed(0);
  if (numeric >= 10) return numeric.toFixed(1);
  if (numeric >= 1) return numeric.toFixed(2);
  return numeric.toPrecision(2);
}
