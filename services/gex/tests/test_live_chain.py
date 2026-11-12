from datetime import UTC, date, datetime

from lrl_gex.live import LIVE_PRODUCTS, OptionListing, choose_chain, futures_expiry, parse_option

NOW = datetime(2026, 11, 11, 23, 30, tzinfo=UTC)  # 6:30pm New York, after today's 4pm expiries


def listing(symbol: str, product: str, expiry: str, name: str) -> OptionListing:
    return OptionListing(symbol, product, expiry, name)


LISTINGS = [
    listing("E2CX6 C7600", "E2C", "20261111", "E-mini S&P 500 Wednesday Weekly Options 2"),  # expired at 4pm
    listing("E2DX6 C7600", "E2D", "20261112", "E-mini S&P 500 Thursday Weekly Options 2"),
    listing("E2DX6 P7600", "E2D", "20261112", "E-mini S&P 500 Thursday Weekly Options 2"),
    listing("EW2X6 C7600", "EW2", "20261113", "CME End of Month Options on Emini S&P500 Week 2"),
    listing("EX3X6 C7600", "EX3", "20261113", "Friday Weekly Micro E-mini S&P 500 Options"),
    listing("E3AX6 C9000", "E3A", "20261116", "E-mini S&P 500 Monday Weekly Options 3"),  # too far from spot
    listing("E3AX6 C7625", "E3A", "20261116", "E-mini S&P 500 Monday Weekly Options 3"),
    listing("ESZ6 C7600", "ES", "20261218", "E-Mini S&P 500"),
    listing("ESH7 C7600", "ES", "20270319", "E-Mini S&P 500"),  # settles into March, not December
    listing("ECESX6 C7600", "ECES", "20261113", "E-mini S&P 500 Futures Event Options Contracts"),
]


def test_chain_takes_nearest_unexpired_expiries_of_the_right_products() -> None:
    chain = choose_chain(LISTINGS, LIVE_PRODUCTS["ES"], "ESZ6", futures_expiry("ESZ6"), 7615, NOW, 3, 0.025)
    assert sorted(c.symbol for c in chain) == ["E2DX6 C7600", "E2DX6 P7600", "E3AX6 C7625", "EW2X6 C7600"]
    assert {c.expiry for c in chain} == {"20261112", "20261113", "20261116"}


def test_quarterly_included_when_within_expiry_count() -> None:
    chain = choose_chain(LISTINGS, LIVE_PRODUCTS["ES"], "ESZ6", date(2026, 12, 18), 7615, NOW, 10, 0.025)
    assert "ESZ6 C7600" in {c.symbol for c in chain}
    assert "ESH7 C7600" not in {c.symbol for c in chain}


def test_product_allowlist() -> None:
    chain = choose_chain(LISTINGS, LIVE_PRODUCTS["ES"], "ESZ6", date(2026, 12, 18), 7615, NOW, 10, 0.025, ("ES",))
    assert [c.symbol for c in chain] == ["ESZ6 C7600"]


def test_parse_option_and_futures_expiry() -> None:
    contract = parse_option(listing("QN3X6 P27200", "QN3", "20261120", "x"), "NQZ6")
    assert (contract.strike, contract.is_call, contract.underlying) == (27200, False, "NQZ6")
    assert parse_option(listing("ESZ6", "ES", "20261218", "x"), "ESZ6") is None
    assert futures_expiry("ESZ6") == date(2026, 12, 18)
    assert futures_expiry("NQH7") == date(2027, 3, 19)
