import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { DEFAULT_FIB, nextLevel, SWATCHES, type FibLevel, type FibStyle } from "./drawings";

const PALETTE = { width: 142, height: 112, gap: 6 };

/** Where the palette goes: under the swatch, or above it when the window has no room below. */
function placePalette(swatch: DOMRect): { top: number; left: number } {
  const below = swatch.bottom + PALETTE.gap;
  const top =
    below + PALETTE.height <= window.innerHeight
      ? below
      : Math.max(8, swatch.top - PALETTE.gap - PALETTE.height);
  const left = Math.min(Math.max(8, swatch.right - PALETTE.width), window.innerWidth - PALETTE.width - 8);
  return { top, left };
}

/**
 * A colour button that opens a small palette of swatches and a custom colour input. The palette
 * is drawn at the page level, so a scrolling list or panel around the button cannot clip it.
 */
export function ColorPicker({
  color,
  label,
  onChange,
}: {
  color: string;
  label: string;
  onChange: (color: string) => void;
}) {
  const [place, setPlace] = useState<{ top: number; left: number } | null>(null);
  const open = place !== null;
  const box = useRef<HTMLSpanElement>(null);
  const palette = useRef<HTMLSpanElement>(null);
  const setOpen = (next: boolean | ((value: boolean) => boolean)) => {
    const value = typeof next === "function" ? next(open) : next;
    const rect = box.current?.getBoundingClientRect();
    setPlace(value && rect ? placePalette(rect) : null);
  };
  useEffect(() => {
    if (!open) return;
    function onDown(event: PointerEvent) {
      const target = event.target as Node;
      if (!box.current?.contains(target) && !palette.current?.contains(target)) setPlace(null);
    }
    // The palette is fixed to the window, so it closes when anything under it scrolls or resizes.
    function onMove(event: Event) {
      if (!palette.current?.contains(event.target as Node)) setPlace(null);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.stopPropagation();
        setPlace(null);
      }
    }
    document.addEventListener("pointerdown", onDown);
    window.addEventListener("keydown", onKey, true);
    window.addEventListener("scroll", onMove, true);
    window.addEventListener("resize", onMove);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      window.removeEventListener("keydown", onKey, true);
      window.removeEventListener("scroll", onMove, true);
      window.removeEventListener("resize", onMove);
    };
  }, [open]);
  return (
    <span className="color-picker" ref={box}>
      <button
        type="button"
        className="color-swatch"
        aria-label={label}
        aria-expanded={open}
        style={{ background: color }}
        onClick={() => setOpen((value) => !value)}
      />
      {place &&
        createPortal(
          <span
            ref={palette}
            className="color-palette"
            role="group"
            aria-label={`${label} options`}
            style={{ top: place.top, left: place.left, width: PALETTE.width }}
          >
            {SWATCHES.map((swatch) => (
              <button
                key={swatch}
                type="button"
                className="color-swatch"
                aria-label={swatch}
                aria-pressed={swatch.toLowerCase() === color.toLowerCase()}
                style={{ background: swatch }}
                onClick={() => {
                  onChange(swatch);
                  setOpen(false);
                }}
              />
            ))}
            <label className="color-custom">
              Custom
              <input type="color" value={color} onChange={(event) => onChange(event.target.value)} />
            </label>
          </span>,
          document.body,
        )}
    </span>
  );
}

/**
 * Settings for one Fibonacci drawing: each level's ratio, colour and visibility, extra levels, and
 * shading between levels. Changes apply as they are made; "Save as default" keeps them for new
 * drawings.
 */
export function FibSettings({
  style,
  onChange,
  onSaveDefault,
  onClose,
}: {
  style: FibStyle;
  onChange: (style: FibStyle) => void;
  onSaveDefault: () => void;
  onClose: () => void;
}) {
  // Bumped when levels are replaced wholesale, so the ratio inputs pick up the new values.
  const [version, setVersion] = useState(0);
  const update = (index: number, change: Partial<FibLevel>) =>
    onChange({
      ...style,
      levels: style.levels.map((level, at) => (at === index ? { ...level, ...change } : level)),
    });
  return (
    <section className="fib-settings" aria-label="Fib retracement settings">
      <header className="fib-settings-head">
        <h3>Fib retracement</h3>
        <button type="button" className="fib-close" aria-label="Close settings" onClick={onClose}>
          <svg viewBox="0 0 20 20" aria-hidden="true">
            <path d="M5 5l10 10M15 5L5 15" />
          </svg>
        </button>
      </header>
      <div className="fib-levels">
        {style.levels.map((level, index) => (
          <div className="fib-level" key={`${version}-${index}`}>
            <input
              type="checkbox"
              aria-label={`Show level ${level.value}`}
              checked={level.visible}
              onChange={(event) => update(index, { visible: event.target.checked })}
            />
            <input
              type="number"
              step="0.001"
              className="fib-value"
              aria-label={`Level ${index + 1} ratio`}
              defaultValue={level.value}
              onChange={(event) => {
                const value = event.target.valueAsNumber;
                if (Number.isFinite(value)) update(index, { value });
              }}
            />
            <ColorPicker
              color={level.color}
              label={`Level ${index + 1} colour`}
              onChange={(color) => update(index, { color })}
            />
            <button
              type="button"
              className="fib-remove"
              aria-label={`Remove level ${level.value}`}
              onClick={() => {
                onChange({ ...style, levels: style.levels.filter((_, at) => at !== index) });
                setVersion((value) => value + 1);
              }}
            >
              <svg viewBox="0 0 20 20" aria-hidden="true">
                <path d="M6 10h8" />
              </svg>
            </button>
          </div>
        ))}
      </div>
      <div className="fib-row">
        <button
          type="button"
          className="fib-text-button"
          onClick={() => onChange({ ...style, levels: [...style.levels, nextLevel(style)] })}
        >
          Add level
        </button>
        <label className="fib-check">
          <input
            type="checkbox"
            checked={style.fill}
            onChange={(event) => onChange({ ...style, fill: event.target.checked })}
          />
          Background
        </label>
      </div>
      <div className="fib-row">
        <button
          type="button"
          className="fib-text-button"
          onClick={() => {
            onChange(DEFAULT_FIB);
            setVersion((value) => value + 1);
          }}
        >
          Reset
        </button>
        <button type="button" className="fib-text-button fib-primary" onClick={onSaveDefault}>
          Save as default
        </button>
      </div>
    </section>
  );
}
