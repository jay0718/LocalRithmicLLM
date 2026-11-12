import time

from lrl_collector.metrics import build_registry
from lrl_collector.rithmic.codec import Credentials
from lrl_collector.rithmic.source import RithmicSource
from prometheus_client import generate_latest


def test_metrics_reflect_source_state() -> None:
    source = RithmicSource("ws://unused", Credentials("u", "p", "s", "a", "v"))
    source.stats.connected = True
    source.stats.reconnects = 2
    source.stats.count("quote")
    source.stats.count("quote")
    source.stats.last_message_monotonic = time.monotonic() - 5
    registry, published, publish_failed = build_registry(source)
    published.inc(3)
    publish_failed()
    text = generate_latest(registry).decode()
    assert "lrl_collector_connected 1.0" in text
    assert "lrl_collector_reconnects_total 2.0" in text
    assert 'lrl_collector_messages_total{type="quote"} 2.0' in text
    assert "lrl_collector_published_total 3.0" in text
    assert "lrl_collector_publish_errors 1.0" in text
    age = float(
        next(line for line in text.splitlines() if line.startswith("lrl_collector_feed_age_seconds")).split()[1]
    )
    assert 5 <= age < 10


def test_feed_age_before_any_message_is_large_not_infinite() -> None:
    source = RithmicSource("ws://unused", Credentials("u", "p", "s", "a", "v"))
    text = generate_latest(build_registry(source)[0]).decode()
    assert "lrl_collector_feed_age_seconds 1e+09" in text
