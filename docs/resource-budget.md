# Raspberry Pi resource budget

The Pi 5 has 8 GB of RAM and already runs about 21 containers for other apps. On 2026-11-09, `free` reported about 5.8 GB available. This project reserves **2.5 GB** for infrastructure and keeps the rest as headroom for its own services and the other apps.

## Infrastructure (`compose.yaml`)

| Service | Memory limit | CPU limit | Why this size |
|---|---|---|---|
| Redpanda | 896 MiB | 1.0 | `--memory=640M` for the broker plus overhead; one core with `--smp=1` |
| Postgres | 512 MiB | 1.0 | `shared_buffers=128MB`, 40 connections |
| Prometheus | 384 MiB | 0.5 | 15-second scrapes, retention capped at 15 days or 2 GB |
| Grafana | 256 MiB | 0.5 | |
| Redis | 128 MiB | 0.5 | `maxmemory 96mb`, no persistence |
| redpanda-init | 128 MiB | 0.5 | Runs once to create topics, then exits |
| **Total** | **2,304 MiB** | | Under the 2,560 MiB budget, checked by `tests/test_compose.py` |

Measured on a Mac with the stack idle, Redpanda used 185 MiB, Grafana 100 MiB and the rest under 30 MiB each. Pi measurements under load are still to come.

## Planned application services

| Service | Planned limit |
|---|---|
| Collector | 256 MiB |
| Pipeline writer | 256 MiB |
| GEX engine | 512 MiB |
| Gateway | 256 MiB |
| Console | 128 MiB |
| **Total** | **1,408 MiB** |

With infrastructure, that is about 3.6 GB of the 5.8 GB available.

## The Pi LLM fallback does not fit comfortably

A small Qwen model on the Pi needs roughly 1.5 to 2.5 GB, which would leave little or no headroom. Options, in order of preference:

1. Run the model only when the Mac is unreachable, and unload it after an idle timeout.
2. Use the smallest Qwen model and cap context length.
3. Skip the Pi fallback and fail over to the mock provider with a clear error.

This is decided under #10.

## Disk

| Data | Cap |
|---|---|
| Redpanda | 15 GiB market data plus 1 GiB DLQ, by retention settings |
| Prometheus | 2 GB |
| Container logs | 30 MB per service |

The root partition has about 53 GB free. Moving volumes to the unused SSD space is tracked in #48 and #49.
