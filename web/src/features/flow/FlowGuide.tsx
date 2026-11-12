/** A short guide to reading the flow nodes chart, shown above it on request. */
export function FlowGuide({ onClose }: { onClose: () => void }) {
  return (
    <section className="flow-guide" aria-label="How to read flow nodes">
      <header className="flow-guide-head">
        <h2>How to read flow nodes</h2>
        <button type="button" className="fib-close" aria-label="Close the guide" onClick={onClose}>
          <svg viewBox="0 0 20 20" aria-hidden="true">
            <path d="M5 5l10 10M15 5L5 15" />
          </svg>
        </button>
      </header>
      <div className="flow-guide-grid">
        <div>
          <h3>What a node is</h3>
          <p>
            Each dot is the estimated dealer gamma at one QQQ strike, from today&apos;s 0DTE option trades.
            Dots sit at the matching NQ price. The value is roughly how many dollars of QQQ dealers trade to
            hedge a $1 move.
          </p>
        </div>
        <div>
          <h3>
            <span className="guide-swatch guide-positive" /> Blue: dealers long gamma
          </h3>
          <p>
            Dealers sell into rallies and buy dips there, which damps moves. Price tends to slow, stall or pin
            near strong blue nodes.
          </p>
        </div>
        <div>
          <h3>
            <span className="guide-swatch guide-negative" /> Red: dealers short gamma
          </h3>
          <p>
            Dealers buy rallies and sell dips there, which adds to moves. Price tends to speed up through
            strong red nodes, and they often act as turning or breaking points.
          </p>
        </div>
        <div>
          <h3>Size, king and 2nd</h3>
          <p>
            Bigger, brighter dots are stronger relative to the strongest node at that moment. The king (solid
            ring, ★ in the table) is the strongest; the second (dashed ring) is next. A new king, or a node
            closing in on it, is worth watching.
          </p>
        </div>
        <div>
          <h3>Walls and flip</h3>
          <p>
            Call wall: the strongest blue node. Put wall: the strongest red node. Gamma flip: the price where
            total dealer gamma changes sign; above it moves tend to be calmer, below it faster.
          </p>
        </div>
        <div>
          <h3>Reading the values</h3>
          <p>
            0DTE gamma grows as 4 PM nears, so values climb through the day (hundreds of millions near the
            close is normal). Compare nodes with each other (% king) rather than across hours. Before the
            open, the stripes are the board frozen at the previous 4:15 PM close.
          </p>
        </div>
        <div>
          <h3>On the chart</h3>
          <p>
            Hover a minute for its table. Drag to move, wheel to zoom, drag the price axis to stretch,
            double-click to fit. Per minute or Streaming (a frame every 10 s) under the mode menu; trade
            filters under Filters.
          </p>
        </div>
        <div>
          <h3>Keep in mind</h3>
          <p>
            These are estimates from public trade data, not dealers&apos; actual books. Use them as a map of
            where hedging flows may concentrate, not as signals on their own.
          </p>
        </div>
      </div>
    </section>
  );
}
