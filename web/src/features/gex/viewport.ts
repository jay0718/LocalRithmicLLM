/** Horizontal zoom (bar spacing), position (bars back from the latest) and an optional manual price range. */
export type Viewport = { slot: number; offset: number; range: { top: number; bottom: number } | null };

export const DEFAULT_SLOT = 9;
export const MIN_SLOT = 2;
export const MAX_SLOT = 40;
export const INITIAL_VIEW: Viewport = { slot: DEFAULT_SLOT, offset: 0, range: null };

/** How far back the view can scroll: until only a fifth of the screen still shows bars. */
export function maxOffsetFor(total: number, capacity: number): number {
  return Math.max(total - Math.min(capacity, total) * 0.2, 0);
}

/** Change bar spacing by factor while keeping the bar under the cursor in place. */
export function zoomAround(
  view: Viewport,
  factor: number,
  pixelsFromRight: number,
  total: number,
  capacityAt: (slot: number) => number,
): Viewport {
  const slot = Math.min(Math.max(view.slot * factor, MIN_SLOT), MAX_SLOT);
  const anchored = view.offset + pixelsFromRight / view.slot - pixelsFromRight / slot;
  return { ...view, slot, offset: Math.min(Math.max(anchored, 0), maxOffsetFor(total, capacityAt(slot))) };
}

export function distance(points: Iterable<{ x: number; y: number }>): number | null {
  const [a, b] = [...points];
  return a && b ? Math.hypot(a.x - b.x, a.y - b.y) : null;
}
