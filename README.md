# LocalRithmicLLM

A self-hosted market data platform that runs on a Raspberry Pi 5. It ingests live futures and options data from Rithmic, computes gamma exposure (GEX) in real time, and serves local LLMs to internal callers through a multi-tenant gateway.

The goal is production-style engineering at small scale: idempotent processing, failure testing, observability, and measured results.

## Components

```
Rithmic / Replay -> collector -> Redpanda -> writer -> Postgres -> query API
                                    |
                                    +-> GEX engine -> WebSocket UI

gex-insights, ops-summarizer, eval-runner -> LLM gateway -> Qwen on Mac / Qwen on Pi / mock
```

| Component | Purpose |
|---|---|
| Console | Pick a prop firm, store Rithmic credentials encrypted, discover accounts |
| Collector | Pluggable `MarketDataSource`: Rithmic for live data, Replay for tests and demos |
| Pipeline | Redpanda, idempotent Postgres writer, dead-letter queue, gap detection |
| GEX engine | Black-76 gamma on live quotes with daily open interest |
| LLM gateway | OpenAI-compatible API with tenant keys, quotas, failover and tracing |
| Observability | Prometheus, Grafana, OpenTelemetry |

## GEX limitations

- Open interest is published daily. Only gamma and price update live.
- Coverage is ES options only and excludes SPX.
- Dealer positioning is an assumption, exposed as a setting.

## Licensing and secrets

- Rithmic's kit is not redistributable. `.proto` files, generated `_pb2.py` files and the SSL certificate stay out of this repo and are generated from a local path.
- Captured CME data stays out of this repo. Public demos use synthetic replay data.
- Rithmic production access requires passing Rithmic's conformance process under this app's own `app_name`.

## Status

Early development. Work is tracked in GitHub Issues.

## Running locally

```bash
cp .env.example .env     # set POSTGRES_PASSWORD and GRAFANA_ADMIN_PASSWORD
make dev                 # install Python packages
make demo                # GEX from synthetic data, no credentials needed
make up                  # Redpanda, Postgres, Redis, Prometheus, Grafana
make smoke               # check the running stack
make test-integration    # tests against the running stack

# Live data: Rithmic -> Redpanda -> Postgres
uv run python -m lrl_collector.main --symbols ESZ6 "ESZ6 C7600"
DATABASE_URL=postgresql://lrl:$POSTGRES_PASSWORD@localhost:15432/lrl uv run python -m lrl_pipeline.main
```

Grafana is at http://localhost:13000 and Prometheus at http://localhost:19090. See [docs/resource-budget.md](docs/resource-budget.md) for memory limits.
