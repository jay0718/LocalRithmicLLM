import { useStoredState } from "../../lib/useStoredState";
import { formatGex, formatPrice, formatStrike } from "../gex/format";
import { topNodes, type NodeFrame } from "./useFlowHistory";

/** A column: rank, ETF strike, futures price, share of the king, or value. */
type Column = "rank" | "strike" | "futures" | "king" | "value";
type Sort = { key: Column; direction: "ascending" | "descending" };
/** What each column sorts on: several columns order rows the same way, but only the clicked one is marked. */
const FIELD: Record<Column, "rank" | "strike" | "value"> = {
  rank: "rank",
  strike: "strike",
  futures: "strike",
  king: "rank",
  value: "value",
};

/** Each column's first click: strongest first, prices high to low (as on a price ladder), value high to low. */
const FIRST: Record<Column, Sort["direction"]> = {
  rank: "ascending",
  strike: "descending",
  futures: "descending",
  king: "ascending",
  value: "descending",
};

/**
 * The selected minute's top nodes: rank, strike, futures price, share of the king, value. Click a
 * column heading to sort by it, again to reverse; the choice is remembered in this browser. The #
 * column always shows the node's strength rank, whatever the order.
 */
export function NodeTable({
  frame,
  ratio,
  count,
  etf,
}: {
  frame: NodeFrame;
  ratio: number;
  count: number;
  etf: string;
}) {
  const [sort, setSort] = useStoredState<Sort>("lrl.flow.tableSort", { key: "rank", direction: "ascending" });
  const ranked = topNodes(frame, count).map((node, rank) => ({ ...node, rank }));
  const king = Math.abs(ranked[0]?.value ?? 0) || 1;
  const sign = sort.direction === "ascending" ? 1 : -1;
  // A sort saved by an older version may name a column that no longer exists.
  const field = FIELD[sort.key] ?? "rank";
  const rows = [...ranked].sort((a, b) => sign * (a[field] - b[field]));

  function heading(key: Column, label: string) {
    const active = sort.key === key;
    return (
      <th scope="col" aria-sort={active ? sort.direction : "none"}>
        <button
          type="button"
          className="sort-button"
          onClick={() =>
            setSort(
              active
                ? { key, direction: sort.direction === "ascending" ? "descending" : "ascending" }
                : { key, direction: FIRST[key] },
            )
          }
        >
          {label}
          <span className="sort-mark" aria-hidden="true">
            {active ? (sort.direction === "ascending" ? "↑" : "↓") : ""}
          </span>
        </button>
      </th>
    );
  }

  return (
    <table className="node-table">
      <caption className="visually-hidden">{etf} flow nodes</caption>
      <thead>
        <tr>
          {heading("rank", "#")}
          {heading("strike", etf)}
          {heading("futures", "Futures")}
          <th scope="col">
            <span className="visually-hidden">Strength</span>
          </th>
          {heading("king", "% king")}
          {heading("value", "Value")}
        </tr>
      </thead>
      <tbody>
        {rows.map((node) => {
          const share = Math.abs(node.value) / king;
          const positive = node.value >= 0;
          return (
            <tr key={node.strike} data-king={node.rank === 0}>
              <td className="num">{node.rank === 0 ? "★" : node.rank + 1}</td>
              <td className="num">{formatStrike(node.strike)}</td>
              <td className="num">{formatPrice(node.strike * ratio)}</td>
              <td className="node-bar-cell">
                <span
                  className={positive ? "node-bar node-bar-positive" : "node-bar node-bar-negative"}
                  style={{ width: `${Math.max(share * 100, 2)}%` }}
                />
              </td>
              <td className="num">{(share * 100).toFixed(1)}%</td>
              <td className="num">{formatGex(node.value, 1)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
