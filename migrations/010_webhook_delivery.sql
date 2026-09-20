CREATE TABLE IF NOT EXISTS webhook_deliveries (
  delivery_id text PRIMARY KEY,
  run_id uuid NOT NULL,
  actor_id text NOT NULL,
  event_type text NOT NULL CHECK (event_type IN ('order_create', 'order_update')),
  order_id text NOT NULL,
  payload jsonb NOT NULL,
  payload_sha256 text NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
  attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0 AND attempt_count <= 5),
  next_attempt_at timestamptz NOT NULL,
  delivered_at timestamptz,
  last_http_status integer,
  last_error text,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  UNIQUE (run_id, event_type, order_id, payload_sha256),
  FOREIGN KEY (run_id, actor_id)
    REFERENCES experiment_runs(run_id, actor_id)
    ON DELETE CASCADE,
  FOREIGN KEY (order_id)
    REFERENCES orders(order_id)
    ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS webhook_delivery_attempts (
  delivery_id text NOT NULL,
  attempt_no integer NOT NULL CHECK (attempt_no >= 1 AND attempt_no <= 5),
  attempted_at timestamptz NOT NULL,
  finished_at timestamptz,
  http_status integer,
  outcome text NOT NULL,
  latency_ms integer CHECK (latency_ms >= 0),
  error_code text,
  PRIMARY KEY (delivery_id, attempt_no),
  FOREIGN KEY (delivery_id)
    REFERENCES webhook_deliveries(delivery_id)
    ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS webhook_deliveries_due_idx
  ON webhook_deliveries (next_attempt_at, created_at)
  WHERE delivered_at IS NULL;
