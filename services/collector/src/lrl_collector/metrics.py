"""Prometheus metrics for the collector."""

from collections.abc import Callable

from prometheus_client import CollectorRegistry, Counter, Gauge
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily
from prometheus_client.registry import Collector

from .rithmic.source import RithmicSource


class FeedCollector(Collector):
    """Reads source state at scrape time, so values are never stale."""

    def __init__(self, source: RithmicSource) -> None:
        self._source = source

    def collect(self):
        stats = self._source.stats
        age = GaugeMetricFamily("lrl_collector_feed_age_seconds", "Seconds since the last market data event")
        age.add_metric([], min(stats.feed_age_seconds(), 1e9))
        yield age
        yield GaugeMetricFamily("lrl_collector_connected", "1 when logged in to Rithmic", value=int(stats.connected))
        yield GaugeMetricFamily(
            "lrl_collector_queue_depth", "Events waiting to publish", value=self._source.queue_depth()
        )
        yield CounterMetricFamily("lrl_collector_reconnects", "Successful reconnects", value=stats.reconnects)
        yield CounterMetricFamily("lrl_collector_rejects", "Reject or forced logout messages", value=stats.rejects)
        yield CounterMetricFamily(
            "lrl_collector_dropped_events", "Events dropped by a full buffer", value=self._source.dropped
        )
        messages = CounterMetricFamily("lrl_collector_messages", "Market data events received", labels=["type"])
        for kind, count in sorted(stats.messages.items()):
            messages.add_metric([kind], count)
        yield messages


def build_registry(source: RithmicSource) -> tuple[CollectorRegistry, Counter, Callable[[], None]]:
    registry = CollectorRegistry()
    registry.register(FeedCollector(source))
    published = Counter("lrl_collector_published", "Events published to Redpanda", registry=registry)
    publish_errors = Gauge("lrl_collector_publish_errors", "Publish failures since start", registry=registry)
    return registry, published, publish_errors.inc
