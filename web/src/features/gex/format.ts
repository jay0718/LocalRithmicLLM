/** Dollar gamma per 1% move, compact: $1.24B, -$350M, $12K. */
export function formatGex(value: number, digits = 2): string {
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(value);
  const [scale, unit] = abs >= 1e9 ? [1e9, "B"] : abs >= 1e6 ? [1e6, "M"] : abs >= 1e3 ? [1e3, "K"] : [1, ""];
  const scaled = abs / scale;
  const fixed = unit ? scaled.toFixed(scaled >= 100 ? 0 : digits) : scaled.toFixed(0);
  // Drop trailing zeros after a decimal point only: 2.50 -> 2.5, but 500 stays 500.
  const trimmed = fixed.includes(".") ? fixed.replace(/\.?0+$/, "") : fixed;
  return `${sign}$${trimmed}${unit}`;
}

const priceFormat = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const strikeFormat = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

export const formatPrice = (value: number) => priceFormat.format(value);
export const formatStrike = (value: number) => strikeFormat.format(value);

/** Evenly spaced round ticks covering -limit..limit, symmetric around zero. */
export function symmetricTicks(maxAbs: number, target = 2): { limit: number; ticks: number[] } {
  if (!(maxAbs > 0)) return { limit: 1, ticks: [-1, 0, 1] };
  const rough = maxAbs / target;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const step = ([1, 2, 2.5, 5, 10].find((m) => m * magnitude >= rough) ?? 10) * magnitude;
  const count = Math.ceil(maxAbs / step);
  const ticks = Array.from({ length: count * 2 + 1 }, (_, index) => (index - count) * step);
  return { limit: count * step, ticks };
}
