"""Encode requests and decode market data frames. Frames are plain protobuf, no length prefix."""

from dataclasses import dataclass

from lrl_common.events import OpenInterest, Quote, SequenceCounter, Settlement, Trade
from lrl_common.rithmic import binding

from ..quotes import QuoteBook

LOGIN = 10
LOGIN_RESPONSE = 11
LOGOUT = 12
HEARTBEAT = 18
HEARTBEAT_RESPONSE = 19
REJECT = 75
FORCED_LOGOUT = 77
MARKET_DATA_UPDATE = 100
MARKET_DATA_UPDATE_RESPONSE = 101
SEARCH_SYMBOLS = 109
SEARCH_SYMBOLS_RESPONSE = 110
TIME_BAR_REPLAY = 202
TIME_BAR_REPLAY_RESPONSE = 203
LAST_TRADE = 150
BEST_BID_OFFER = 151
END_OF_DAY_PRICES = 155
OPEN_INTEREST = 158

# The only templates this app may ever send: session upkeep and read-only market
# data, symbol search and bar history. Order, PnL and admin templates are absent,
# so a coding mistake cannot place or change an order.
ALLOWED_OUTBOUND = frozenset({LOGIN, LOGOUT, HEARTBEAT, MARKET_DATA_UPDATE, SEARCH_SYMBOLS, TIME_BAR_REPLAY})

UPDATE_LAST_TRADE = 1
UPDATE_BBO = 2
UPDATE_SETTLEMENT = 512
UPDATE_OPEN_INTEREST = 2048
EOD_SETTLEMENT = 2
SUBSCRIBE = 1
UNSUBSCRIBE = 2
TICKER_PLANT = 1
HISTORY_PLANT = 3
SOURCE = "rithmic"


class ForbiddenTemplate(Exception):
    """Raised before any non-market-data message could be sent."""


class LoginRejected(Exception):
    def __init__(self, codes: list[str]) -> None:
        super().__init__(f"Rithmic rejected the login: {codes}")
        self.codes = codes


def encode(message) -> bytes:
    """The single path for outbound bytes. Refuses anything outside the market data allowlist."""
    if message.template_id not in ALLOWED_OUTBOUND:
        raise ForbiddenTemplate(f"Template {message.template_id} is not a market data request")
    return message.SerializeToString()


def template_id(frame: bytes) -> int:
    base = binding("base_pb2").Base()
    base.ParseFromString(frame)
    return base.template_id


@dataclass(frozen=True)
class Credentials:
    user: str
    password: str
    system_name: str
    app_name: str
    app_version: str

    def __repr__(self) -> str:
        return f"Credentials(user={self.user!r}, system_name={self.system_name!r}, app_name={self.app_name!r})"


def login_request(credentials: Credentials, plant: int = TICKER_PLANT) -> bytes:
    module = binding("request_login_pb2")
    request = module.RequestLogin()
    request.template_id = LOGIN
    request.template_version = "3.9"
    request.user = credentials.user
    request.password = credentials.password
    request.app_name = credentials.app_name
    request.app_version = credentials.app_version
    request.system_name = credentials.system_name
    request.infra_type = plant
    return encode(request)


def parse_login_response(frame: bytes) -> float:
    """Return the heartbeat interval in seconds, or raise LoginRejected."""
    response = binding("response_login_pb2").ResponseLogin()
    response.ParseFromString(frame)
    codes = list(response.rp_code)
    if response.template_id != LOGIN_RESPONSE or codes[:1] != ["0"]:
        raise LoginRejected(codes)
    return response.heartbeat_interval or 60.0


def heartbeat_request() -> bytes:
    request = binding("request_heartbeat_pb2").RequestHeartbeat()
    request.template_id = HEARTBEAT
    return encode(request)


def logout_request() -> bytes:
    request = binding("request_logout_pb2").RequestLogout()
    request.template_id = LOGOUT
    return encode(request)


def market_data_request(symbol: str, exchange: str, subscribe: bool = True) -> bytes:
    request = binding("request_market_data_update_pb2").RequestMarketDataUpdate()
    request.template_id = MARKET_DATA_UPDATE
    request.user_msg.append(symbol)
    request.symbol = symbol
    request.exchange = exchange
    request.request = SUBSCRIBE if subscribe else UNSUBSCRIBE
    request.update_bits = UPDATE_LAST_TRADE | UPDATE_BBO | UPDATE_SETTLEMENT | UPDATE_OPEN_INTEREST
    return encode(request)


def parse_subscription_response(frame: bytes) -> tuple[str, list[str]]:
    response = binding("response_market_data_update_pb2").ResponseMarketDataUpdate()
    response.ParseFromString(frame)
    return (response.user_msg[0] if response.user_msg else ""), list(response.rp_code)


def _ts_ns(seconds: int, micros: int = 0, nanos: int | None = None) -> int:
    fraction = nanos if nanos else micros * 1000
    return seconds * 1_000_000_000 + fraction


class Decoder:
    """Turns market data frames into normalized events. Returns None for frames that carry no event."""

    def __init__(self, sequence: SequenceCounter, quotes: QuoteBook) -> None:
        self._sequence = sequence
        self._quotes = quotes

    def _common(self, symbol: str, exchange: str, ts_ns: int) -> dict:
        return {
            "source": SOURCE,
            "symbol": symbol,
            "exchange": exchange,
            "exchange_ts_ns": ts_ns,
            "seq": self._sequence.next(symbol),
        }

    def decode(self, kind: int, frame: bytes) -> Trade | Quote | OpenInterest | Settlement | None:
        if kind == BEST_BID_OFFER:
            message = binding("best_bid_offer_pb2").BestBidOffer()
            message.ParseFromString(frame)
            bid, bid_size, ask, ask_size = self._quotes.apply(
                message.symbol,
                message.presence_bits,
                message.clear_bits,
                message.bid_price,
                message.bid_size,
                message.ask_price,
                message.ask_size,
            )
            ts = _ts_ns(message.ssboe, message.usecs)
            # Rithmic reports an empty side as price 0, which is not a real quote.
            if not bid:
                bid, bid_size = None, None
            if not ask:
                ask, ask_size = None, None
            return Quote(
                **self._common(message.symbol, message.exchange, ts),
                bid_price=bid,
                bid_size=bid_size,
                ask_price=ask,
                ask_size=ask_size,
            )
        if kind == LAST_TRADE:
            message = binding("last_trade_pb2").LastTrade()
            message.ParseFromString(frame)
            if not message.presence_bits & UPDATE_LAST_TRADE:
                return None
            if message.source_ssboe:
                ts = _ts_ns(message.source_ssboe, message.source_usecs, message.source_nsecs)
            else:
                ts = _ts_ns(message.ssboe, message.usecs)
            return Trade(
                **self._common(message.symbol, message.exchange, ts),
                price=message.trade_price,
                size=message.trade_size,
            )
        if kind == END_OF_DAY_PRICES:
            message = binding("end_of_day_prices_pb2").EndOfDayPrices()
            message.ParseFromString(frame)
            if not message.presence_bits & EOD_SETTLEMENT or message.settlement_price <= 0:
                return None
            if len(message.settlement_date) != 8:
                return None
            ts = _ts_ns(message.ssboe, message.usecs)
            return Settlement(
                **self._common(message.symbol, message.exchange, ts),
                price=message.settlement_price,
                settlement_date=message.settlement_date,
            )
        if kind == OPEN_INTEREST:
            message = binding("open_interest_pb2").OpenInterest()
            message.ParseFromString(frame)
            if message.should_clear:
                return None
            ts = _ts_ns(message.ssboe, message.usecs)
            return OpenInterest(
                **self._common(message.symbol, message.exchange, ts), open_interest=message.open_interest
            )
        return None


INSTRUMENT_FUTURE_OPTION = 2
PATTERN_CONTAINS = 2
MINUTE_BAR = 2
BACKWARDS = 2
OLDEST_FIRST = 1


def search_options_request(text: str, exchange: str) -> bytes:
    request = binding("request_search_symbols_pb2").RequestSearchSymbols()
    request.template_id = SEARCH_SYMBOLS
    request.search_text = text
    request.exchange = exchange
    request.instrument_type = INSTRUMENT_FUTURE_OPTION
    request.pattern = PATTERN_CONTAINS
    return encode(request)


def minute_bars_request(symbol: str, exchange: str, start_s: int, end_s: int) -> bytes:
    request = binding("request_time_bar_replay_pb2").RequestTimeBarReplay()
    request.template_id = TIME_BAR_REPLAY
    request.user_msg.append(symbol)
    request.symbol = symbol
    request.exchange = exchange
    request.bar_type = MINUTE_BAR
    request.bar_type_period = 1
    request.start_index = start_s
    request.finish_index = end_s
    request.direction = BACKWARDS
    request.time_order = OLDEST_FIRST
    return encode(request)
