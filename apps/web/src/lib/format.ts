/** Presentation-only helpers. These do not compute science. */

export function formatNumber(value: number | null | undefined, digits = 6): string {
  if (value === null || value === undefined) return "—";
  if (Number.isNaN(value)) return "NaN";
  if (value === Infinity) return "∞";
  if (value === -Infinity) return "-∞";
  if (value === 0) return "0";
  const rounded = Number(value.toPrecision(digits));
  return rounded.toString();
}

export function formatScalar(value: number | boolean | string | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return formatNumber(value);
  return String(value);
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 1) return `${(seconds * 1000).toFixed(0)} ms`;
  return `${seconds.toFixed(2)} s`;
}

export function shortHash(hash: string | null | undefined, length = 12): string {
  if (!hash) return "—";
  return hash.slice(0, length);
}
