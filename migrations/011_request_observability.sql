CREATE TABLE IF NOT EXISTS request_observations (
  request_id text PRIMARY KEY,
  run_id uuid,
  actor_id text,
  operation text NOT NULL
    CHECK (operation IN ('create', 'get', 'update', 'complete', 'cancel')),
  result text NOT NULL CHECK (result IN ('success', 'error')),
  http_status integer NOT NULL,
  latency_ms integer NOT NULL CHECK (latency_ms >= 0),
  checkout_id text,
  order_id text,
  idempotency_sha256 text
    CHECK (idempotency_sha256 IS NULL OR idempotency_sha256 ~ '^[0-9a-f]{64}$'),
  error_code text,
  recorded_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS request_observations_run_recorded_idx
  ON request_observations (run_id, recorded_at);
