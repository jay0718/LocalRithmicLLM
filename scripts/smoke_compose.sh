#!/usr/bin/env bash
# Verify the running Compose stack end to end.
set -euo pipefail
cd "$(dirname "$0")/.."

dc() { docker compose "$@"; }
pass() { printf 'ok    %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1" >&2; exit 1; }

topics=$(dc exec -T redpanda rpk topic list)
for topic in md.events.v1 md.events.dlq.v1; do
  grep -q "^$topic " <<<"$topics" || fail "topic $topic exists"
done
pass "topics exist"

dc exec -T redpanda rpk topic describe md.events.v1 -c | grep -q 'retention.bytes *5368709120' || fail "retention set"
pass "retention configured"

marker="smoke-$(date +%s)-$RANDOM"
echo "$marker" | dc exec -T redpanda rpk topic produce md.events.dlq.v1 -k smoke >/dev/null
dc exec -T redpanda rpk topic consume md.events.dlq.v1 -o -1 -n 1 -f '%v\n' | grep -q "$marker" || fail "produce and consume"
pass "produce and consume"

[[ $(dc exec -T postgres psql -U lrl -d lrl -tAc 'select 1') == 1 ]] || fail "postgres query"
pass "postgres query"

[[ $(dc exec -T redis redis-cli ping) == PONG ]] || fail "redis ping"
[[ $(dc exec -T redis redis-cli config get maxmemory-policy | tail -1) == volatile-lru ]] || fail "redis eviction policy"
pass "redis ping and eviction policy"

for _ in $(seq 1 20); do
  targets=$(dc exec -T prometheus wget -qO- http://localhost:9090/api/v1/targets)
  [[ $(grep -o '"health":"up"' <<<"$targets" | wc -l) -ge 2 ]] && break
  sleep 3
done
[[ $(grep -o '"health":"up"' <<<"$targets" | wc -l) -ge 2 ]] || fail "prometheus targets up"
pass "prometheus scrapes prometheus and redpanda"

dc exec -T grafana wget -qO- http://localhost:3000/api/health | grep -q '"database": *"ok"' || fail "grafana health"
dc exec -T grafana sh -c 'wget -qO- --header "Authorization: Basic $(printf "%s:%s" "$GF_SECURITY_ADMIN_USER" "$GF_SECURITY_ADMIN_PASSWORD" | base64)" http://localhost:3000/api/datasources/uid/prometheus' \
  | grep -q '"url":"http://prometheus:9090"' || fail "grafana datasource"
pass "grafana health and provisioned datasource"

over=$(docker stats --no-stream --format '{{.Name}} {{.MemPerc}}' $(dc ps -q) | awk '{gsub("%","",$2); if ($2+0 > 90) print}')
[[ -z "$over" ]] || fail "memory under 90% of limits: $over"
pass "every service under 90% of its memory limit"
