import { useCallback, useEffect, useState } from "react";

/** A point in data terms, so drawings stay put through scrolling, zooming and reloads. */
export type Point = { ns: number; price: number };

export type TwoPointKind = "trend" | "ray" | "rect" | "fib" | "measure";
/** One Fibonacci level: its ratio (0 at the second point, 1 at the first), colour and visibility. */
export type FibLevel = { value: number; color: string; visible: boolean };
/** Fibonacci settings: the levels and whether the bands between them are shaded. */
export type FibStyle = { levels: FibLevel[]; fill: boolean };
export type Drawing =
  | { id: string; kind: TwoPointKind; a: Point; b: Point; fib?: FibStyle }
  | { id: string; kind: "hline"; price: number }
  | { id: string; kind: "vline"; ns: number };

export type Tool = "cursor" | TwoPointKind | "hline" | "vline";

/** Swatches offered for drawing colours; each reads on both the light and the dark surface. */
export const SWATCHES = [
  "#ffffff",
  "#8a8f98",
  "#e5484d",
  "#f76b15",
  "#ffd60a",
  "#30a46c",
  "#12a594",
  "#0090ff",
  "#8e4ec6",
  "#d6409f",
];

const WHITE = "#ffffff";
const YELLOW = "#ffd60a";
const RED = "#e5484d";
const GREEN = "#30a46c";

/** The user's standard levels: 0, 1 and 2 red; 0.5 green; 0.618 and 1.618 yellow; the rest white. */
export const DEFAULT_FIB: FibStyle = {
  levels: [
    { value: 0, color: RED, visible: true },
    { value: 0.114, color: WHITE, visible: true },
    { value: 0.236, color: WHITE, visible: true },
    { value: 0.382, color: WHITE, visible: true },
    { value: 0.5, color: GREEN, visible: true },
    { value: 0.618, color: YELLOW, visible: true },
    { value: 0.786, color: WHITE, visible: true },
    { value: 0.886, color: WHITE, visible: true },
    { value: 1, color: RED, visible: true },
    { value: 1.382, color: WHITE, visible: true },
    { value: 1.618, color: YELLOW, visible: true },
    { value: 2, color: RED, visible: true },
    { value: 2.618, color: WHITE, visible: true },
  ],
  fill: false,
};

/** Ratios offered by "Add level", in order, skipping ones the drawing already has. */
const EXTRA_LEVELS = [1.272, 1.414, 3.618, 4.236, -0.272, -0.618];

export function nextLevel(style: FibStyle): FibLevel {
  const taken = new Set(style.levels.map((level) => level.value));
  const value = EXTRA_LEVELS.find((candidate) => !taken.has(candidate)) ?? Math.max(...taken, 0) + 1;
  return { value, color: WHITE, visible: true };
}

/** A Fibonacci level's price: 0 sits at the second point, 1 at the first. */
export function fibPrice(a: Point, b: Point, value: number): number {
  return b.price + (a.price - b.price) * value;
}

/** Visible levels sorted by ratio, from the drawing's own settings or the defaults. */
export function visibleLevels(style: FibStyle | undefined): FibLevel[] {
  return (style ?? DEFAULT_FIB).levels.filter((level) => level.visible).sort((x, y) => x.value - y.value);
}

/** Screen mapping for hit testing: content x for a time, y for a price, and the plot's right edge. */
export type Projection = { x: (ns: number) => number; y: (price: number) => number; right: number };

function distanceToSegment(px: number, py: number, ax: number, ay: number, bx: number, by: number): number {
  const dx = bx - ax;
  const dy = by - ay;
  const length = dx * dx + dy * dy;
  const t = length ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / length)) : 0;
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

/** Where a ray from a through b leaves the plot on the right (or the left, if it points back). */
export function rayEnd(
  ax: number,
  ay: number,
  bx: number,
  by: number,
  right: number,
  left = 0,
): [number, number] {
  if (bx === ax) return [bx, by];
  const edge = bx > ax ? right : left;
  return [edge, ay + ((by - ay) * (edge - ax)) / (bx - ax)];
}

/** Pixel distance from a content-space point to a drawing; the closest one within reach is picked. */
export function distanceTo(drawing: Drawing, px: number, py: number, p: Projection): number {
  switch (drawing.kind) {
    case "hline":
      return Math.abs(py - p.y(drawing.price));
    case "vline":
      return Math.abs(px - p.x(drawing.ns));
    default: {
      const ax = p.x(drawing.a.ns);
      const ay = p.y(drawing.a.price);
      const bx = p.x(drawing.b.ns);
      const by = p.y(drawing.b.price);
      if (drawing.kind === "trend") return distanceToSegment(px, py, ax, ay, bx, by);
      if (drawing.kind === "ray")
        return distanceToSegment(px, py, ax, ay, ...rayEnd(ax, ay, bx, by, p.right));
      if (drawing.kind === "fib") {
        const ys = [
          ay,
          by,
          ...visibleLevels(drawing.fib).map((level) => p.y(fibPrice(drawing.a, drawing.b, level.value))),
        ];
        return boxDistance(px, py, ax, Math.min(...ys), bx, Math.max(...ys));
      }
      return boxDistance(px, py, ax, ay, bx, by);
    }
  }
}

/** Boxes are picked anywhere inside or near their edge. */
function boxDistance(px: number, py: number, ax: number, ay: number, bx: number, by: number): number {
  const inside =
    px >= Math.min(ax, bx) && px <= Math.max(ax, bx) && py >= Math.min(ay, by) && py <= Math.max(ay, by);
  if (inside) return 0;
  return Math.min(
    distanceToSegment(px, py, ax, ay, bx, ay),
    distanceToSegment(px, py, bx, ay, bx, by),
    distanceToSegment(px, py, bx, by, ax, by),
    distanceToSegment(px, py, ax, by, ax, ay),
  );
}

export function pick(drawings: Drawing[], px: number, py: number, p: Projection, reach = 6): Drawing | null {
  let best: Drawing | null = null;
  let bestDistance = reach;
  for (const drawing of drawings) {
    const distance = distanceTo(drawing, px, py, p);
    if (distance <= bestDistance) {
      best = drawing;
      bestDistance = distance;
    }
  }
  return best;
}

/** Shift a drawing by a time and price offset (dragging it). */
export function moved(drawing: Drawing, dns: number, dprice: number): Drawing {
  switch (drawing.kind) {
    case "hline":
      return { ...drawing, price: drawing.price + dprice };
    case "vline":
      return { ...drawing, ns: drawing.ns + dns };
    default:
      return {
        ...drawing,
        a: { ns: drawing.a.ns + dns, price: drawing.a.price + dprice },
        b: { ns: drawing.b.ns + dns, price: drawing.b.price + dprice },
      };
  }
}

/** The measure tool's readout: price change, percent and the number of one-minute candles. */
export function measure(a: Point, b: Point): { change: number; percent: number; minutes: number } {
  const change = b.price - a.price;
  return {
    change,
    percent: a.price ? (change / a.price) * 100 : 0,
    minutes: Math.round((b.ns - a.ns) / 60e9),
  };
}

function read(key: string): Drawing[] {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as Drawing[]) : [];
  } catch {
    return [];
  }
}

/** Drawings for one chart, kept in this browser per symbol. */
export function useDrawings(storageKey: string) {
  const [drawings, setDrawings] = useState<Drawing[]>(() => read(storageKey));
  const [key, setKey] = useState(storageKey);
  if (key !== storageKey) {
    setKey(storageKey);
    setDrawings(read(storageKey));
  }
  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(drawings));
    } catch {
      // Storage can be unavailable (private windows); drawings then last for the visit only.
    }
  }, [storageKey, drawings]);
  const add = useCallback((drawing: Drawing) => setDrawings((all) => [...all, drawing]), []);
  const replace = useCallback(
    (drawing: Drawing) => setDrawings((all) => all.map((item) => (item.id === drawing.id ? drawing : item))),
    [],
  );
  const remove = useCallback((id: string) => setDrawings((all) => all.filter((item) => item.id !== id)), []);
  const clear = useCallback(() => setDrawings([]), []);
  return { drawings, add, replace, remove, clear };
}

const FIB_DEFAULTS_KEY = "lrl.chart.fib.defaults";

/** The settings new Fibonacci drawings start with; "Save as default" replaces them. */
export function useFibDefaults() {
  const [defaults, setDefaults] = useState<FibStyle>(() => {
    try {
      const raw = localStorage.getItem(FIB_DEFAULTS_KEY);
      return raw ? (JSON.parse(raw) as FibStyle) : DEFAULT_FIB;
    } catch {
      return DEFAULT_FIB;
    }
  });
  const save = useCallback((style: FibStyle) => {
    setDefaults(style);
    try {
      localStorage.setItem(FIB_DEFAULTS_KEY, JSON.stringify(style));
    } catch {
      // Without storage the default lasts for this visit.
    }
  }, []);
  return { defaults, save };
}

let counter = 0;
export function newId(): string {
  counter += 1;
  return `${Date.now().toString(36)}-${counter}`;
}
