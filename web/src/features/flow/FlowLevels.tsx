import { formatGex, formatPrice, formatStrike } from "../gex/format";
import type { NodeFrame } from "./useFlowHistory";

/** The selected minute's call wall, put wall, gamma flip and net dealer gamma, in ETF and futures prices. */
export function FlowLevels({ frame, ratio, etf }: { frame: NodeFrame; ratio: number; etf: string }) {
  const level = (value: number | null | undefined, strike = true) =>
    value == null
      ? "None"
      : `${strike ? formatStrike(value) : value.toFixed(2)} · ${formatPrice(value * ratio)}`;
  return (
    <dl className="flow-levels-list">
      <div>
        <dt>
          <span className="swatch-line flow-swatch-call" /> Call wall
        </dt>
        <dd className="num">{level(frame.call_wall)}</dd>
      </div>
      <div>
        <dt>
          <span className="swatch-line flow-swatch-put" /> Put wall
        </dt>
        <dd className="num">{level(frame.put_wall)}</dd>
      </div>
      <div>
        <dt>
          <span className="swatch-line flow-swatch-flip" /> Gamma flip
        </dt>
        <dd className="num">{level(frame.flip, false)}</dd>
      </div>
      <div>
        <dt>Net dealer gamma</dt>
        <dd className="num">
          {formatGex(frame.total ?? 0, 1)} per $1 {etf}
        </dd>
      </div>
    </dl>
  );
}
