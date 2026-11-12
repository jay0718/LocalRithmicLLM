-- Settlement prices from the exchange. The price reuses the price column.
ALTER TABLE md_events DROP CONSTRAINT md_events_type_check;
ALTER TABLE md_events ADD CONSTRAINT md_events_type_check
    CHECK (type IN ('trade', 'quote', 'open_interest', 'settlement'));
ALTER TABLE md_events ADD COLUMN settlement_date date;
