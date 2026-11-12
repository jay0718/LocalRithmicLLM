"""Download Databento OPRA trades for one option expiry and build its flow history.

What is needed, and why:
  - Dataset OPRA.PILLAR (all US options exchanges), schema ``tcbbo``: every trade with the
    consolidated best bid and offer just before it. The quote is what decides whether a trade was a
    customer buy (at or through the ask) or sell (at or through the bid).
  - Symbols: each call and put of the expiry in a strike range, by OSI raw symbol, e.g.
    ``QQQ   261110C00674000``.
  - Two time ranges: every earlier session since the expiry listed (positions accumulate from
    listing), and the replayed session itself through the 4:15 PM ET close.

Databento publishes OPRA history in a daily batch, so a session is available the next day.

    # 1. Download (checks the cost first and stops above --max-cost)
    uv run --with databento --env-file .env.live python -m lrl_gex.flow_dbn download \\
        QQQ 20261110 2026-11-10 data/flow-raw --strikes 640:710
    # 2. Build the minute-by-minute history the Flow nodes page reads
    uv run --with databento python -m lrl_gex.flow_dbn build QQQ 20261110 2026-11-10 data/flow \\
        data/flow-raw/2026-11-10/qqq_1110_*.dbn.zst

databento is a tool dependency, installed on demand with ``uv run --with databento``, so the
service itself does not need it. The key is read from DATABENTO_API_KEY.
"""

import argparse
import os
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .flow import ALL_RULES
from .flow_history import FlowStore, FlowTrade, build_history

NY = ZoneInfo("America/New_York")
DATASET = "OPRA.PILLAR"
SCHEMA = "tcbbo"
# Weekly and daily options list well within this window before they expire.
LISTING_LOOKBACK = timedelta(days=35)


@dataclass(frozen=True)
class Request:
    """One Databento timeseries request and the file it is saved to."""

    name: str
    start: datetime
    end: datetime
    path: Path


def osi_symbols(root: str, expiry: str, low: int, high: int) -> list[str]:
    """OSI raw symbols for every call and put from low to high strike, inclusive."""
    return [f"{root:<6}{expiry[2:]}{cp}{strike * 1000:08d}" for strike in range(low, high + 1) for cp in "CP"]


def plan(root: str, expiry: str, session: date, out: Path) -> list[Request]:
    """The earlier sessions since listing, then the session itself through the 4:15 PM close."""
    open_ = datetime.combine(session, time(9, 30), NY).astimezone(UTC)
    close = datetime.combine(session, time(16, 15), NY).astimezone(UTC)
    folder = out / session.isoformat()
    stem = f"{root.lower()}_{expiry[4:]}"
    return [
        Request("earlier sessions", open_ - LISTING_LOOKBACK, open_, folder / f"{stem}_prior.dbn.zst"),
        Request("session", open_, close, folder / f"{stem}_session.dbn.zst"),
    ]


def download(root: str, expiry: str, session: date, out: Path, strikes: tuple[int, int], max_cost: float) -> None:
    import databento as db

    client = db.Historical(os.environ["DATABENTO_API_KEY"])
    symbols = osi_symbols(root, expiry, *strikes)
    requests = plan(root, expiry, session, out)
    args = {"dataset": DATASET, "schema": SCHEMA, "stype_in": "raw_symbol", "symbols": symbols}
    costs = [client.metadata.get_cost(**args, start=r.start, end=r.end) for r in requests]
    print(
        f"{len(symbols)} contracts; cost "
        + ", ".join(f"{r.name} ${c:.2f}" for r, c in zip(requests, costs, strict=True))
    )
    if sum(costs) > max_cost:
        sys.exit(f"Total ${sum(costs):.2f} is above --max-cost ${max_cost:.2f}; nothing downloaded.")
    for request in requests:
        if request.path.exists():
            print(f"have {request.path}")
            continue
        request.path.parent.mkdir(parents=True, exist_ok=True)
        fetch(client, args, request)
        print(f"saved {request.path}")


def fetch(client, args: dict, request: Request, attempts: int = 4, wait: float = 20.0, sleep=None) -> None:
    """Download one range to a temporary file, renamed into place only once complete, retrying
    Databento server errors (such as a 504 gateway timeout) a few times."""
    import time as clock

    from databento.common.error import BentoServerError

    part = request.path.with_name(request.path.name + ".part")
    for attempt in range(1, attempts + 1):
        try:
            client.timeseries.get_range(**args, start=request.start, end=request.end, path=str(part))
            part.replace(request.path)
            return
        except BentoServerError as error:
            part.unlink(missing_ok=True)
            if attempt == attempts:
                raise
            print(f"{request.name}: {error}; retrying in {wait:.0f}s ({attempt}/{attempts})")
            (sleep or clock.sleep)(wait)


def read_trades(paths: list[Path]) -> Iterator[FlowTrade]:
    import databento as db

    return trades_from_store(*(db.DBNStore.from_file(path) for path in paths))


def trades_from_store(*stores) -> Iterator[FlowTrade]:
    """Trades in time order from one or more Databento tcbbo stores (files or API responses)."""
    import pandas as pd

    frames = [store.to_df() for store in stores]
    if not frames or all(frame.empty for frame in frames):
        return
    df = pd.concat(frames).sort_values("ts_event", kind="stable")
    for ts, symbol, price, size, bid, ask in zip(
        df["ts_event"].astype("int64"),
        df["symbol"],
        df["price"],
        df["size"],
        df["bid_px_00"],
        df["ask_px_00"],
        strict=True,
    ):
        yield FlowTrade(int(ts), symbol.replace(" ", ""), float(price), int(size), float(bid), float(ask))


def build(root: str, expiry: str, session: str, out: str, files: list[str]) -> None:
    """One history per combination of trade filters, so the page can switch between them."""
    trades = list(read_trades([Path(f) for f in files]))
    for rules in ALL_RULES:
        history = build_history(iter(trades), root, expiry, date.fromisoformat(session), rules=rules)
        path = FlowStore(Path(out)).save(history, rules)
        print(f"{len(history.frames)} frames for {root} {expiry} on {session} ({rules.key or 'default'}) -> {path}")


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="python -m lrl_gex.flow_dbn")
    commands = parser.add_subparsers(dest="command", required=True)
    get = commands.add_parser("download", help="download one expiry's trades for one session")
    get.add_argument("root", help="option root, e.g. QQQ")
    get.add_argument("expiry", help="YYYYMMDD")
    get.add_argument("session", help="YYYY-MM-DD, the session to replay")
    get.add_argument("out", help="folder for the raw files, e.g. data/flow-raw")
    get.add_argument("--strikes", required=True, help="LOW:HIGH whole-dollar strikes, e.g. 640:710")
    get.add_argument("--max-cost", type=float, default=15.0, help="stop if the total exceeds this (USD)")
    make = commands.add_parser("build", help="build the flow history from downloaded files")
    make.add_argument("root")
    make.add_argument("expiry")
    make.add_argument("session")
    make.add_argument("out", help="folder the service reads, e.g. data/flow")
    make.add_argument("files", nargs="+")
    args = parser.parse_args(argv)
    if args.command == "download":
        low, high = (int(part) for part in args.strikes.split(":"))
        download(args.root, args.expiry, date.fromisoformat(args.session), Path(args.out), (low, high), args.max_cost)
    else:
        build(args.root, args.expiry, args.session, args.out, args.files)


if __name__ == "__main__":
    main(sys.argv[1:])
