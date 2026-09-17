CREATE TABLE IF NOT EXISTS experiment_runs (
  run_id uuid PRIMARY KEY,
  scenario_id text NOT NULL,
  variant text NOT NULL CHECK (variant IN ('preparation', 'B0', 'B1', 'B2')),
  fixture_version text NOT NULL,
  clock_at timestamptz NOT NULL,
  manifest jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS catalog_offers (
  run_id uuid NOT NULL REFERENCES experiment_runs(run_id),
  offer_id text NOT NULL,
  revision integer NOT NULL CHECK (revision > 0),
  snapshot jsonb NOT NULL,
  PRIMARY KEY (run_id, offer_id),
  CONSTRAINT catalog_offers_snapshot_id_matches CHECK ((snapshot ->> 'id' = offer_id) IS TRUE),
  CONSTRAINT catalog_offers_snapshot_revision_matches CHECK (((snapshot ->> 'revision')::integer = revision) IS TRUE)
);

CREATE TABLE IF NOT EXISTS run_events (
  event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id uuid NOT NULL REFERENCES experiment_runs(run_id),
  event_type text NOT NULL,
  producer text NOT NULL,
  scenario_at timestamptz NOT NULL,
  payload jsonb NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS run_events_run_id ON run_events(run_id, event_id);
