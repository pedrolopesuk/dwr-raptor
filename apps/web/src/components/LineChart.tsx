"use client";

/**
 * Accessible SVG line chart styled to the Carbon data-visualization guidance:
 * light horizontal gridlines, "nice" tick values, 12px axis labels in the
 * secondary text colour, 2px lines, and a legend below the plot.
 *
 * Presentation only: values come from the Python core. Series are distinguished
 * by colour *and* line style, and each series is named in the legend, so meaning
 * is not carried by colour alone. Non-finite points break the line instead of
 * being drawn misleadingly.
 *
 * Kept as a small custom component rather than a charting library: the data is
 * already aligned by Python and the requirement is a precise, dependency-free
 * scientific plot.
 */

export interface ChartSeries {
  name: string;
  color: string;
  values: number[];
  dashed?: boolean;
}

const WIDTH = 720;
const HEIGHT = 300;
const PAD = { top: 16, right: 24, bottom: 48, left: 72 };
const TARGET_TICKS = 5;

function isFiniteNumber(value: number): boolean {
  return Number.isFinite(value);
}

/** Round to a 1/2/5 x 10^n step so ticks land on human-readable values. */
function niceStep(span: number, target: number): number {
  const raw = span / Math.max(target, 1);
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const fraction = raw / magnitude;
  const nice = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10;
  return nice * magnitude;
}

function niceScale(min: number, max: number): { lo: number; hi: number; ticks: number[] } {
  if (min === max) {
    const pad = Math.abs(min) * 0.1 || 1;
    min -= pad;
    max += pad;
  }
  const step = niceStep(max - min, TARGET_TICKS);
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let value = lo; value <= hi + step / 2; value += step) {
    ticks.push(Number(value.toPrecision(12)));
  }
  return { lo, hi, ticks };
}

function formatTick(value: number): string {
  if (value === 0) return "0";
  const abs = Math.abs(value);
  if (abs >= 1e5 || abs < 1e-3) return value.toExponential(1).replace("e+", "e");
  return Number(value.toPrecision(4)).toString();
}

export function LineChart({
  axis,
  series,
  ariaLabel,
  yLabel,
  xLabel,
}: {
  axis: number[];
  series: ChartSeries[];
  ariaLabel: string;
  yLabel?: string;
  xLabel?: string;
}) {
  const finiteValues = series.flatMap((s) => s.values).filter(isFiniteNumber);
  const finiteAxis = axis.filter(isFiniteNumber);
  if (finiteValues.length === 0 || finiteAxis.length === 0) {
    return <p className="drw-muted">No finite data to plot.</p>;
  }

  const x = niceScale(Math.min(...finiteAxis), Math.max(...finiteAxis));
  const y = niceScale(Math.min(...finiteValues), Math.max(...finiteValues));
  const plotW = WIDTH - PAD.left - PAD.right;
  const plotH = HEIGHT - PAD.top - PAD.bottom;

  const toX = (value: number) => PAD.left + ((value - x.lo) / (x.hi - x.lo)) * plotW;
  const toY = (value: number) => PAD.top + (1 - (value - y.lo) / (y.hi - y.lo)) * plotH;

  const paths = series.map((s) => {
    const segments: string[] = [];
    let current: string[] = [];
    s.values.forEach((value, index) => {
      const at = axis[index];
      if (at === undefined || !isFiniteNumber(value) || !isFiniteNumber(at)) {
        if (current.length > 1) segments.push(current.join(" "));
        current = [];
        return;
      }
      current.push(
        `${current.length === 0 ? "M" : "L"} ${toX(at).toFixed(2)} ${toY(value).toFixed(2)}`,
      );
    });
    if (current.length > 1) segments.push(current.join(" "));
    return { ...s, d: segments.join(" ") };
  });

  const zeroVisible = y.lo < 0 && y.hi > 0;

  return (
    <figure className="drw-figure">
      <svg className="drw-chart" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={ariaLabel}>
        {y.ticks.map((tick) => (
          <g key={`y-${tick}`}>
            <line
              x1={PAD.left}
              x2={WIDTH - PAD.right}
              y1={toY(tick)}
              y2={toY(tick)}
              stroke="var(--cds-border-subtle-01)"
            />
            <text
              x={PAD.left - 8}
              y={toY(tick)}
              textAnchor="end"
              dominantBaseline="middle"
              fill="var(--cds-text-secondary)"
              fontSize="12"
            >
              {formatTick(tick)}
            </text>
          </g>
        ))}
        {x.ticks.map((tick) => (
          <g key={`x-${tick}`}>
            <line
              x1={toX(tick)}
              x2={toX(tick)}
              y1={HEIGHT - PAD.bottom}
              y2={HEIGHT - PAD.bottom + 4}
              stroke="var(--cds-border-strong-01)"
            />
            <text
              x={toX(tick)}
              y={HEIGHT - PAD.bottom + 18}
              textAnchor="middle"
              fill="var(--cds-text-secondary)"
              fontSize="12"
            >
              {formatTick(tick)}
            </text>
          </g>
        ))}

        {zeroVisible ? (
          <line
            x1={PAD.left}
            x2={WIDTH - PAD.right}
            y1={toY(0)}
            y2={toY(0)}
            stroke="var(--cds-border-strong-01)"
            strokeDasharray="2 2"
          />
        ) : null}
        <line
          x1={PAD.left}
          x2={WIDTH - PAD.right}
          y1={HEIGHT - PAD.bottom}
          y2={HEIGHT - PAD.bottom}
          stroke="var(--cds-border-strong-01)"
        />

        {yLabel ? (
          <text
            transform={`translate(14 ${PAD.top + plotH / 2}) rotate(-90)`}
            textAnchor="middle"
            fill="var(--cds-text-primary)"
            fontSize="12"
          >
            {yLabel}
          </text>
        ) : null}
        {xLabel ? (
          <text
            x={PAD.left + plotW / 2}
            y={HEIGHT - 8}
            textAnchor="middle"
            fill="var(--cds-text-primary)"
            fontSize="12"
          >
            {xLabel}
          </text>
        ) : null}

        {paths.map((path) =>
          path.d ? (
            <path
              key={path.name}
              d={path.d}
              fill="none"
              stroke={path.color}
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
              strokeDasharray={path.dashed ? "6 4" : undefined}
            />
          ) : null,
        )}
      </svg>
      <figcaption className="drw-legend">
        {series.map((s) => (
          <span key={s.name} className="drw-legend-item">
            <span
              className={`drw-swatch${s.dashed ? " dashed" : ""}`}
              style={{ color: s.color }}
              aria-hidden="true"
            />
            {s.name}
            {s.dashed ? " (dashed)" : ""}
          </span>
        ))}
      </figcaption>
    </figure>
  );
}
