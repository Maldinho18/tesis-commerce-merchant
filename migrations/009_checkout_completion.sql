ALTER TABLE checkout_sessions DROP CONSTRAINT IF EXISTS checkout_sessions_status_check;
ALTER TABLE checkout_sessions
  ADD CONSTRAINT checkout_sessions_status_check
  CHECK (status IN ('prepared', 'ready_for_payment', 'completed', 'expired', 'canceled'));

CREATE TABLE IF NOT EXISTS orders (
  order_id text PRIMARY KEY,
  run_id uuid NOT NULL,
  actor_id text NOT NULL,
  checkout_id text NOT NULL,
  snapshot jsonb NOT NULL,
  created_at timestamptz NOT NULL,
  UNIQUE (run_id, checkout_id),
  FOREIGN KEY (run_id, actor_id)
    REFERENCES experiment_runs(run_id, actor_id)
    ON DELETE CASCADE,
  FOREIGN KEY (run_id, checkout_id)
    REFERENCES checkout_sessions(run_id, checkout_id)
    ON DELETE CASCADE,
  CONSTRAINT orders_snapshot_id_matches
    CHECK ((snapshot ->> 'id' = order_id) IS TRUE),
  CONSTRAINT orders_snapshot_checkout_matches
    CHECK ((snapshot ->> 'checkout_session_id' = checkout_id) IS TRUE)
);

CREATE TABLE IF NOT EXISTS checkout_completion_attempts (
  run_id uuid NOT NULL,
  actor_id text NOT NULL,
  checkout_id text NOT NULL,
  idempotency_sha256 text NOT NULL CHECK (idempotency_sha256 ~ '^[0-9a-f]{64}$'),
  request_fingerprint text NOT NULL CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
  result_snapshot jsonb NOT NULL,
  created_at timestamptz NOT NULL,
  PRIMARY KEY (run_id, actor_id, checkout_id, idempotency_sha256),
  FOREIGN KEY (run_id, actor_id)
    REFERENCES experiment_runs(run_id, actor_id)
    ON DELETE CASCADE,
  FOREIGN KEY (run_id, checkout_id)
    REFERENCES checkout_sessions(run_id, checkout_id)
    ON DELETE CASCADE
);
