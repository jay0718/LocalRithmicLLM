-- One table for all event types, partitioned by day on exchange time.
CREATE TABLE md_events (
    ts               timestamptz NOT NULL,
    event_key        uuid        NOT NULL,
    type             text        NOT NULL CHECK (type IN ('trade', 'quote', 'open_interest')),
    source           text        NOT NULL,
    symbol           text        NOT NULL,
    exchange         text        NOT NULL,
    exchange_ts_ns   bigint      NOT NULL,
    seq              bigint      NOT NULL,
    price            double precision,
    size             bigint,
    bid_price        double precision,
    bid_size         bigint,
    ask_price        double precision,
    ask_size         bigint,
    open_interest    bigint,
    ingested_at      timestamptz NOT NULL DEFAULT now(),
    -- Partitioned tables require the partition column in unique constraints.
    -- ts is derived from the key's exchange_ts_ns, so this is still unique per event.
    PRIMARY KEY (event_key, ts)
) PARTITION BY RANGE (ts);

CREATE TABLE md_events_default PARTITION OF md_events DEFAULT;

CREATE INDEX md_events_symbol_ts ON md_events (symbol, ts);
