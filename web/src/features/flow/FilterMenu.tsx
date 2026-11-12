import { useEffect, useRef, useState } from "react";

export type FilterOption = {
  key: string;
  label: string;
  hint: string;
  checked: boolean;
  /** The value it starts with; the button is marked when any option differs. */
  initial: boolean;
  onChange: (checked: boolean) => void;
};

/** A "Filters" button that opens a short list of switches. */
export function FilterMenu({ options }: { options: FilterOption[] }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    function onDown(event: PointerEvent) {
      if (!box.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);
  const changed = options.filter((option) => option.checked !== option.initial).length;
  return (
    <div className="filter-menu" ref={box}>
      <button
        type="button"
        className="filter-button"
        aria-expanded={open}
        aria-haspopup="true"
        onClick={() => setOpen((value) => !value)}
      >
        Filters{changed ? ` · ${changed} changed` : ""}
      </button>
      {open && (
        <div className="filter-panel" role="group" aria-label="Filters">
          {options.map((option) => (
            <label key={option.key} className="filter-option">
              <input
                type="checkbox"
                checked={option.checked}
                onChange={(event) => option.onChange(event.target.checked)}
              />
              <span>
                <span className="filter-label">{option.label}</span>
                <span className="filter-hint">{option.hint}</span>
              </span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
