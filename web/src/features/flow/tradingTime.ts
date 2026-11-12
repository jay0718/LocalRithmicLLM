/**
 * A time axis without the hours the futures market is shut: the daily close from 5 PM to 6 PM ET
 * (Monday to Thursday) and the weekend from Friday 5 PM to Sunday 6 PM ET. compress() maps a time
 * to "trading time" (closed hours removed), so the chart draws Friday's close right next to
 * Sunday's open; expand() goes back.
 */

const HOUR_MS = 3_600_000;
const DAY_MS = 24 * HOUR_MS;
const NS_PER_MS = 1_000_000;

const offsetFormat = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  timeZoneName: "shortOffset",
});
const dayFormat = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" });

/** New York's offset from UTC at an instant, in milliseconds (e.g. -5 h in winter). */
function nyOffsetMs(ms: number): number {
  const name = offsetFormat.formatToParts(ms).find((part) => part.type === "timeZoneName")?.value ?? "GMT-5";
  const match = /GMT([+-]\d+)(?::(\d+))?/.exec(name);
  if (!match) return 0;
  const hours = Number(match[1]);
  const minutes = Number(match[2] ?? 0) * Math.sign(hours || 1);
  return (hours * 60 + minutes) * 60_000;
}

/** The instant (ms) of a New York wall-clock hour on a given calendar day (UTC midnight of it). */
function nyWall(dayUtcMs: number, hour: number): number {
  const wall = dayUtcMs + hour * HOUR_MS;
  // The offset five hours later is New York's at that wall time, away from any 2 AM switch.
  return wall - nyOffsetMs(wall + 5 * HOUR_MS);
}

export type Closure = [number, number];

/** Closed spans (ns) overlapping [fromNs, toNs], in order. */
export function closures(fromNs: number, toNs: number): Closure[] {
  const out: Closure[] = [];
  const first = Date.parse(dayFormat.format(fromNs / NS_PER_MS - 3 * DAY_MS));
  const last = toNs / NS_PER_MS + DAY_MS;
  for (let day = first; day <= last; day += DAY_MS) {
    const weekday = new Date(day).getUTCDay(); // 0 Sunday … 6 Saturday
    if (weekday >= 1 && weekday <= 4) out.push([nyWall(day, 17), nyWall(day, 18)]);
    else if (weekday === 5) out.push([nyWall(day, 17), nyWall(day + 2 * DAY_MS, 18)]);
  }
  return out
    .map(([a, b]): Closure => [a * NS_PER_MS, b * NS_PER_MS])
    .filter(([a, b]) => b > fromNs && a < toNs);
}

export type TradingTime = {
  compress: (ns: number) => number;
  expand: (trading: number) => number;
  /** Whether the market is shut at this time. */
  closed: (ns: number) => boolean;
};

/** A trading-time mapping valid over [fromNs, toNs] (and linear beyond it). */
export function tradingTime(fromNs: number, toNs: number): TradingTime {
  const spans = closures(fromNs, toNs);
  // Closed time before each span starts, so compress is a sum over earlier spans.
  const before: number[] = [];
  let total = 0;
  for (const [a, b] of spans) {
    before.push(total);
    total += b - a;
  }
  const compress = (ns: number) => {
    let removed = 0;
    for (let i = 0; i < spans.length; i++) {
      const [a, b] = spans[i] as Closure;
      if (ns <= a) break;
      removed = (before[i] ?? 0) + Math.min(ns, b) - a;
    }
    return ns - removed;
  };
  const expand = (trading: number) => {
    let removed = 0;
    for (let i = 0; i < spans.length; i++) {
      const [a, b] = spans[i] as Closure;
      // The span starts at trading time a - closed time before it.
      if (trading < a - (before[i] ?? 0)) break;
      removed = (before[i] ?? 0) + (b - a);
    }
    return trading + removed;
  };
  const closed = (ns: number) => spans.some(([a, b]) => ns > a && ns < b);
  return { compress, expand, closed };
}
