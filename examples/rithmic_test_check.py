"""Check what a Rithmic login can see. Read-only: this script never sends orders.

Setup:
    cp .env.example .env            # then fill in your values
    set -a; source .env; set +a
    ./scripts/gen_rithmic_bindings.sh

Run:
    uv run --no-project --env-file .env --with websockets --with protobuf \
        python examples/rithmic_test_check.py --seconds 60

R|Protocol frames are plain protobuf. Do not add a 4-byte length prefix: a
prefixed login is rejected with rp_code 13, "permission denied".
"""

import argparse
import asyncio
import collections
import os
import ssl
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "rithmic_kit" / "gen"))

import base_pb2  # noqa: E402
import best_bid_offer_pb2  # noqa: E402
import open_interest_pb2  # noqa: E402
import request_login_pb2  # noqa: E402
import request_logout_pb2  # noqa: E402
import request_market_data_update_by_underlying_pb2 as sub_request  # noqa: E402
import request_market_data_update_pb2  # noqa: E402
import request_search_symbols_pb2  # noqa: E402
import response_login_pb2  # noqa: E402
import response_market_data_update_by_underlying_pb2 as sub_response  # noqa: E402
import response_search_symbols_pb2  # noqa: E402
import websockets  # noqa: E402

LOGIN_RESPONSE = 11
SEARCH_RESPONSE = 110
SUBSCRIBE_RESPONSE = 106
BEST_BID_OFFER = 151
OPEN_INTEREST = 158

UPDATE_BBO = 2
UPDATE_OPEN_INTEREST = 2048
PATTERN_CONTAINS = 2
INSTRUMENT_FUTURE_OPTION = 2
SUBSCRIBE = 1


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if not value:
        raise SystemExit(f"Set {name} in .env")
    return value


def template_id(frame: bytes) -> int:
    message = base_pb2.Base()
    message.ParseFromString(frame)
    return message.template_id


async def next_frame(ws, deadline: float) -> bytes | None:
    try:
        return await asyncio.wait_for(ws.recv(), max(0.1, deadline - time.time()))
    except TimeoutError:
        return None


async def login(ws) -> None:
    request = request_login_pb2.RequestLogin()
    request.template_id = 10
    request.template_version = "3.9"
    request.user = env("RITHMIC_USER")
    request.password = env("RITHMIC_PASSWORD")
    request.app_name = env("RITHMIC_APP_NAME")
    request.app_version = env("RITHMIC_APP_VERSION", "0.1.0")
    request.system_name = env("RITHMIC_SYSTEM_NAME")
    request.infra_type = request_login_pb2.RequestLogin.SysInfraType.TICKER_PLANT
    await ws.send(request.SerializeToString())

    response = response_login_pb2.ResponseLogin()
    response.ParseFromString(await asyncio.wait_for(ws.recv(), 10))
    if response.template_id != LOGIN_RESPONSE or list(response.rp_code)[:1] != ["0"]:
        raise SystemExit(f"Login rejected: {list(response.rp_code)}")
    print(f"login: ok, fcm={response.fcm_id} ib={response.ib_id}")


async def search_options(ws, product: str, exchange: str) -> list[tuple[str, str]]:
    request = request_search_symbols_pb2.RequestSearchSymbols()
    request.template_id = 109
    request.search_text = product
    request.exchange = exchange
    request.instrument_type = INSTRUMENT_FUTURE_OPTION
    request.pattern = PATTERN_CONTAINS
    await ws.send(request.SerializeToString())

    found = []
    deadline = time.time() + 20
    while (frame := await next_frame(ws, deadline)) is not None:
        if template_id(frame) != SEARCH_RESPONSE:
            continue
        message = response_search_symbols_pb2.ResponseSearchSymbols()
        message.ParseFromString(frame)
        if list(message.rp_code):
            return found
        if message.product_code == product:
            found.append((message.symbol, message.expiration_date))
    raise SystemExit("Timed out waiting for symbol search")


async def subscribe_expiry(ws, underlying: str, exchange: str, expiry: str) -> None:
    request = sub_request.RequestMarketDataUpdateByUnderlying()
    request.template_id = 105
    request.underlying_symbol = underlying
    request.exchange = exchange
    request.expiration_date = expiry
    request.request = SUBSCRIBE
    request.update_bits = UPDATE_BBO | UPDATE_OPEN_INTEREST
    await ws.send(request.SerializeToString())


def strike_of(symbol: str) -> float | None:
    try:
        return float(symbol.rsplit(" ", 1)[1][1:])
    except (IndexError, ValueError):
        return None


def nearest_contracts(chain: set[str], around: float, count: int) -> list[str]:
    priced = [(abs(strike - around), symbol) for symbol in chain if (strike := strike_of(symbol)) is not None]
    return [symbol for _, symbol in sorted(priced)[:count]]


async def subscribe_symbols(ws, symbols: list[str], exchange: str) -> None:
    for symbol in symbols:
        request = request_market_data_update_pb2.RequestMarketDataUpdate()
        request.template_id = 100
        request.symbol = symbol
        request.exchange = exchange
        request.request = SUBSCRIBE
        request.update_bits = UPDATE_BBO | UPDATE_OPEN_INTEREST
        await ws.send(request.SerializeToString())


async def watch(ws, seconds: int, chain: set[str]) -> None:
    counts = collections.Counter()
    quoted = set()
    open_interest = {}
    deadline = time.time() + seconds
    while (frame := await next_frame(ws, deadline)) is not None:
        kind = template_id(frame)
        counts[kind] += 1
        if kind == SUBSCRIBE_RESPONSE:
            message = sub_response.ResponseMarketDataUpdateByUnderlying()
            message.ParseFromString(frame)
            print(f"subscribe: rp_code={list(message.rp_code)}")
        elif kind == BEST_BID_OFFER:
            message = best_bid_offer_pb2.BestBidOffer()
            message.ParseFromString(frame)
            quoted.add(message.symbol)
        elif kind == OPEN_INTEREST:
            message = open_interest_pb2.OpenInterest()
            message.ParseFromString(frame)
            open_interest[message.symbol] = message.open_interest

    in_chain = quoted & chain
    print(f"messages by template: {dict(counts)}")
    print(f"quotes: {len(in_chain)} of {len(chain)} chain symbols, {len(quoted - chain)} other symbols")
    print(f"sample quoted: {sorted(in_chain)[:4]}")
    nonzero = sum(1 for value in open_interest.values() if value)
    print(f"open interest: {len(open_interest)} symbols, {nonzero} nonzero")
    print(f"sample open interest: {sorted(open_interest.items())[:4]}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--product", default="ES")
    parser.add_argument("--underlying", default="ESZ6")
    parser.add_argument("--exchange", default="CME")
    parser.add_argument("--expiry", help="YYYYMMDD; defaults to the expiry with the most contracts")
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--mode", choices=["underlying", "symbols"], default="symbols")
    parser.add_argument("--around", type=float, default=7600, help="center strike for --mode symbols")
    parser.add_argument("--count", type=int, default=20, help="contracts to subscribe in --mode symbols")
    args = parser.parse_args()

    kit = Path(env("RITHMIC_KIT_DIR"))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(kit / "etc" / "rithmic_ssl_cert_auth_params")
    context.check_hostname = False

    async with websockets.connect(env("RITHMIC_URI"), ssl=context, open_timeout=10, max_size=None) as ws:
        await login(ws)
        options = await search_options(ws, args.product, args.exchange)
        today = date.today().strftime("%Y%m%d")
        by_expiry = collections.Counter(expiry for _, expiry in options if expiry >= today)
        print(f"option chain: {len(options)} {args.product} contracts, {len(by_expiry)} current expiries")
        print(f"expiries: {sorted(by_expiry.items())[:12]}")
        if not by_expiry:
            raise SystemExit("No current expiries found")

        expiry = args.expiry or by_expiry.most_common(1)[0][0]
        chain = {symbol for symbol, item_expiry in options if item_expiry == expiry}
        if args.mode == "underlying":
            print(f"subscribing by underlying: {args.underlying} {expiry}, {len(chain)} contracts")
            await subscribe_expiry(ws, args.underlying, args.exchange, expiry)
        else:
            picks = nearest_contracts(chain, args.around, args.count)
            print(f"subscribing per symbol: {len(picks)} contracts of {expiry}, sample {picks[:2]}")
            await subscribe_symbols(ws, picks, args.exchange)
            chain = set(picks)
        await watch(ws, args.seconds, chain)

        logout = request_logout_pb2.RequestLogout()
        logout.template_id = 12
        await ws.send(logout.SerializeToString())
        print("logged out")


if __name__ == "__main__":
    asyncio.run(main())
