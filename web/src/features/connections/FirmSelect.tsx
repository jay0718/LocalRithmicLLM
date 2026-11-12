import { useId, useMemo, useState, type KeyboardEvent } from "react";

export type Firm = { name: string; is_test: boolean };

/** A searchable combobox for Rithmic systems, following the WAI-ARIA combobox pattern. */
export function FirmSelect({
  firms,
  value,
  onChange,
  showTest,
  inputProps,
}: {
  firms: Firm[];
  value: string;
  onChange: (name: string) => void;
  showTest: boolean;
  inputProps: { id: string; "aria-invalid": boolean; "aria-describedby": string | undefined };
}) {
  const listId = useId();
  const [query, setQuery] = useState(value);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);

  const options = useMemo(() => {
    const term = query.trim().toLowerCase();
    return firms.filter(
      (firm) =>
        (showTest || !firm.is_test || firm.name === value) &&
        (!term || firm.name.toLowerCase().includes(term)),
    );
  }, [firms, query, showTest, value]);

  function choose(name: string) {
    onChange(name);
    setQuery(name);
    setOpen(false);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((index) => (options.length ? (index + step + options.length) % options.length : 0));
    } else if (event.key === "Enter" && open) {
      event.preventDefault();
      const option = options[active];
      if (option) choose(option.name);
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  }

  const activeId = open && options[active] ? `${listId}-${active}` : undefined;
  return (
    <div className="combobox">
      <input
        {...inputProps}
        className="input"
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={activeId}
        autoComplete="off"
        placeholder="Search firms"
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
          setActive(0);
          setOpen(true);
          if (event.target.value !== value) onChange("");
        }}
        onClick={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={onKeyDown}
      />
      {open && (
        <ul id={listId} role="listbox" className="combobox-list">
          {options.length === 0 && <li className="combobox-empty">No firms match “{query}”</li>}
          {options.map((firm, index) => (
            <li
              key={firm.name}
              id={`${listId}-${index}`}
              role="option"
              aria-selected={firm.name === value}
              data-active={index === active}
              onMouseDown={(event) => {
                event.preventDefault();
                choose(firm.name);
              }}
            >
              {firm.name}
              {firm.is_test && <span className="badge">Test</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
