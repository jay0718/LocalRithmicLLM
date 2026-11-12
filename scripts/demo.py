#!/usr/bin/env python3
"""Replay a synthetic ES session and print its GEX. Needs no credentials or Rithmic files."""

import argparse
import asyncio

from lrl_collector.replay import ALL_SYMBOLS, ReplaySource
from lrl_collector.synthetic import MarketConfig, SyntheticMarket
from lrl_gex.chain import ChainState
from lrl_gex.engine import EngineConfig, GexSnapshot, compute_snapshot

BAR_WIDTH = 30
ROWS_EACH_SIDE = 8


def render(snapshot: GexSnapshot) -> str:
    flip = "none" if snapshot.flip_level is None else f"{snapshot.flip_level:,.2f}"
    lines = [
        "ES options GEX (synthetic data; open interest is daily; excludes SPX)",
        f"Spot {snapshot.spot:,.2f}   Total GEX ${snapshot.total_gex / 1e9:,.2f}B per 1%",
        f"Flip {flip}   Call wall {snapshot.call_wall:,.0f}   Put wall {snapshot.put_wall:,.0f}",
        f"Used {snapshot.contracts_used}/{snapshot.contracts_total} contracts   Dealer: {snapshot.convention.value}",
        "",
    ]
    center = min(range(len(snapshot.strikes)), key=lambda i: abs(snapshot.strikes[i].strike - snapshot.spot))
    rows = snapshot.strikes[max(center - ROWS_EACH_SIDE, 0) : center + ROWS_EACH_SIDE + 1]
    largest = max(abs(row.net_gex) for row in rows) or 1
    for row in reversed(rows):
        size = round(abs(row.net_gex) / largest * BAR_WIDTH)
        left = ("#" * size if row.net_gex < 0 else "").rjust(BAR_WIDTH)
        right = "#" * size if row.net_gex > 0 else ""
        lines.append(f"{row.strike:>8,.0f} {left}|{right}")
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--ticks", type=int, default=3000)
    args = parser.parse_args()

    market = SyntheticMarket(MarketConfig(seed=args.seed))
    chain = ChainState(market.config.underlying, market.contracts)
    source = ReplaySource(market.events(args.ticks))
    await source.connect()
    await source.subscribe([ALL_SYMBOLS])
    async for event in source.stream():
        chain.apply(event)
    await source.close()
    print(render(compute_snapshot(chain, EngineConfig())))


if __name__ == "__main__":
    asyncio.run(main())
