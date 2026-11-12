"""A local stand-in for Rithmic's ticker plant, for tests that have the kit bindings."""

import asyncio
from dataclasses import dataclass, field

import websockets
from lrl_common.rithmic import binding


def frame(module: str, cls: str, **fields) -> bytes:
    message = getattr(binding(module), cls)()
    for name, value in fields.items():
        if isinstance(value, list):
            getattr(message, name).extend(value)
        else:
            setattr(message, name, value)
    return message.SerializeToString()


def bbo(symbol: str, ssboe: int, **fields) -> bytes:
    return frame(
        "best_bid_offer_pb2", "BestBidOffer", template_id=151, symbol=symbol, exchange="CME", ssboe=ssboe, **fields
    )


def trade(symbol: str, price: float, size: int, **fields) -> bytes:
    return frame(
        "last_trade_pb2",
        "LastTrade",
        template_id=150,
        symbol=symbol,
        exchange="CME",
        presence_bits=1,
        trade_price=price,
        trade_size=size,
        **fields,
    )


def open_interest(symbol: str, value: int, ssboe: int) -> bytes:
    return frame(
        "open_interest_pb2",
        "OpenInterest",
        template_id=158,
        symbol=symbol,
        exchange="CME",
        open_interest=value,
        ssboe=ssboe,
    )


@dataclass
class FakeRithmic:
    """Accepts logins, records every inbound template and pushes scripted frames per session."""

    heartbeat_interval: float = 60
    login_codes: list[list[str]] = field(default_factory=list)
    sessions: list[list[bytes]] = field(default_factory=list)
    close_after_script: bool = False
    received: list[tuple[int, int]] = field(default_factory=list)
    subscribed: list[list[str]] = field(default_factory=list)
    session_count: int = 0

    async def handler(self, ws) -> None:
        session = self.session_count
        self.session_count += 1
        self.subscribed.append([])
        codes = self.login_codes[session] if session < len(self.login_codes) else ["0"]
        script = self.sessions[session] if session < len(self.sessions) else []
        base = binding("base_pb2")
        sent_script = False
        async for raw in ws:
            message = base.Base()
            message.ParseFromString(raw)
            self.received.append((session, message.template_id))
            if message.template_id == 10:
                await ws.send(
                    frame(
                        "response_login_pb2",
                        "ResponseLogin",
                        template_id=11,
                        rp_code=codes,
                        heartbeat_interval=self.heartbeat_interval,
                    )
                )
                if codes[:1] != ["0"]:
                    return
            elif message.template_id == 100:
                request = binding("request_market_data_update_pb2").RequestMarketDataUpdate()
                request.ParseFromString(raw)
                self.subscribed[session].append(request.symbol)
                await ws.send(
                    frame(
                        "response_market_data_update_pb2",
                        "ResponseMarketDataUpdate",
                        template_id=101,
                        rp_code=["0"],
                        user_msg=[request.symbol],
                    )
                )
                if not sent_script:
                    sent_script = True
                    for item in script:
                        await ws.send(item)
                    if self.close_after_script and script:
                        await asyncio.sleep(0.05)
                        await ws.close()
                        return
            elif message.template_id == 12:
                return

    def templates(self) -> set[int]:
        return {template for _, template in self.received}


async def serve(fake: FakeRithmic):
    server = await websockets.serve(fake.handler, "127.0.0.1", 0)
    return server, f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"


def end_of_day(symbol: str, settlement: float, day: str, ssboe: int = 1_800_000_000) -> bytes:
    return frame(
        "end_of_day_prices_pb2",
        "EndOfDayPrices",
        template_id=155,
        symbol=symbol,
        exchange="CME",
        presence_bits=2,
        settlement_price=settlement,
        settlement_date=day,
        ssboe=ssboe,
    )
