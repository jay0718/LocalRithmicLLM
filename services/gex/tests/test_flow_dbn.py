from datetime import date, datetime
from pathlib import Path

import pytest
from lrl_gex.flow_dbn import NY, main, osi_symbols, plan


def test_osi_symbols_cover_calls_and_puts_in_the_range() -> None:
    assert osi_symbols("QQQ", "20261110", 674, 675) == [
        "QQQ   261110C00674000",
        "QQQ   261110P00674000",
        "QQQ   261110C00675000",
        "QQQ   261110P00675000",
    ]


def test_plan_covers_listing_to_the_close() -> None:
    earlier, session = plan("QQQ", "20261110", date(2026, 11, 10), Path("raw"))
    open_ = datetime(2026, 11, 10, 9, 30, tzinfo=NY)
    assert earlier.end == session.start == open_
    assert (open_ - earlier.start).days == 35
    assert session.end == datetime(2026, 11, 10, 16, 15, tzinfo=NY)
    assert session.path == Path("raw/2026-11-10/qqq_1110_session.dbn.zst")
    assert earlier.path.name == "qqq_1110_prior.dbn.zst"


def test_download_needs_a_strike_range() -> None:
    with pytest.raises(SystemExit):
        main(["download", "QQQ", "20261110", "2026-11-10", "raw"])


def test_fetch_retries_server_errors_and_never_leaves_a_partial_file(monkeypatch, tmp_path: Path) -> None:
    import sys
    import types

    from lrl_gex.flow_dbn import Request, fetch

    class BentoServerError(Exception):
        pass

    error_module = types.ModuleType("databento.common.error")
    error_module.BentoServerError = BentoServerError
    for name in ("databento", "databento.common"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "databento.common.error", error_module)

    outcomes = [BentoServerError("504 The remote gateway timed out."), None]

    class Timeseries:
        def get_range(self, path: str, **_: object) -> None:
            Path(path).write_bytes(b"partial")
            outcome = outcomes.pop(0)
            if outcome:
                raise outcome
            Path(path).write_bytes(b"complete")

    client = types.SimpleNamespace(timeseries=Timeseries())
    target = tmp_path / "qqq_1105_session.dbn.zst"
    request = Request("session", datetime(2026, 11, 5, 14, 30), datetime(2026, 11, 5, 21, 15), target)
    waits: list[float] = []
    fetch(client, {}, request, wait=1, sleep=waits.append)
    assert target.read_bytes() == b"complete"
    assert waits == [1]
    assert not list(tmp_path.glob("*.part"))
