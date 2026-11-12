import type { Tool } from "./drawings";

/** One-colour glyphs on a 20px grid; each shows the shape the tool draws. */
const ICONS: Record<Tool | "hide" | "show" | "clear", string> = {
  cursor: "M5 3l10 6-4.5 1.2L9 15z",
  trend:
    "M5.2 14.8L14.8 5.2M2.4 16a1.6 1.6 0 1 0 3.2 0a1.6 1.6 0 1 0-3.2 0M14.4 4a1.6 1.6 0 1 0 3.2 0a1.6 1.6 0 1 0-3.2 0",
  ray: "M5.3 14.1L18 5M2.4 15a1.6 1.6 0 1 0 3.2 0a1.6 1.6 0 1 0-3.2 0",
  hline: "M2 10h6.4M11.6 10H18M8.4 10a1.6 1.6 0 1 0 3.2 0a1.6 1.6 0 1 0-3.2 0",
  vline: "M10 2v6.4M10 11.6V18M8.4 10a1.6 1.6 0 1 0 3.2 0a1.6 1.6 0 1 0-3.2 0",
  rect: "M4 6h12v8H4z",
  fib: "M3 4h14M3 8h14M3 12h14M3 16h14",
  measure: "M10 3v14M7 6l3-3 3 3M7 14l3 3 3-3",
  hide: "M2 10s3-5 8-5 8 5 8 5-3 5-8 5-8-5-8-5zM10 12a2 2 0 100-4 2 2 0 000 4zM3 17L17 3",
  show: "M2 10s3-5 8-5 8 5 8 5-3 5-8 5-8-5-8-5zM10 12a2 2 0 100-4 2 2 0 000 4z",
  clear: "M4 6h12M8 6V4h4v2M6 6l1 10h6l1-10",
};

const TOOLS: { tool: Tool; label: string; key?: string }[] = [
  { tool: "cursor", label: "Cursor", key: "Esc" },
  { tool: "trend", label: "Trend line" },
  { tool: "ray", label: "Ray" },
  { tool: "hline", label: "Horizontal line" },
  { tool: "vline", label: "Vertical line" },
  { tool: "rect", label: "Rectangle" },
  { tool: "fib", label: "Fib retracement" },
  { tool: "measure", label: "Measure" },
];

function Glyph({ path }: { path: string }) {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d={path} />
    </svg>
  );
}

export function DrawingToolbar({
  tool,
  onTool,
  hidden,
  onToggleHidden,
  onClear,
  count,
}: {
  tool: Tool;
  onTool: (tool: Tool) => void;
  hidden: boolean;
  onToggleHidden: () => void;
  onClear: () => void;
  count: number;
}) {
  return (
    <div className="draw-toolbar" role="toolbar" aria-label="Drawing tools" aria-orientation="vertical">
      {TOOLS.map((item) => (
        <button
          key={item.tool}
          type="button"
          className="draw-tool"
          aria-label={item.label}
          aria-pressed={tool === item.tool}
          title={item.key ? `${item.label} (${item.key})` : item.label}
          onClick={() => onTool(item.tool)}
        >
          <Glyph path={ICONS[item.tool]} />
        </button>
      ))}
      <span className="draw-separator" />
      <button
        type="button"
        className="draw-tool"
        aria-label={hidden ? "Show drawings" : "Hide drawings"}
        aria-pressed={hidden}
        title={hidden ? "Show drawings" : "Hide drawings"}
        onClick={onToggleHidden}
      >
        <Glyph path={ICONS[hidden ? "hide" : "show"]} />
      </button>
      <button
        type="button"
        className="draw-tool"
        aria-label="Remove all drawings"
        title="Remove all drawings"
        disabled={!count}
        onClick={onClear}
      >
        <Glyph path={ICONS.clear} />
      </button>
    </div>
  );
}
