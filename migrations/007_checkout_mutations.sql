ALTER TABLE checkout_sessions ADD COLUMN IF NOT EXISTS create_snapshot jsonb;
UPDATE checkout_sessions SET create_snapshot = snapshot WHERE create_snapshot IS NULL;
ALTER TABLE checkout_sessions ALTER COLUMN create_snapshot SET NOT NULL;

CREATE TABLE IF NOT EXISTS checkout_mutations (
  run_id uuid NOT NULL,
  actor_id text NOT NULL,
  checkout_id text NOT NULL,
  operation text NOT NULL CHECK (operation IN ('update', 'cancel')),
  idempotency_sha256 text NOT NULL CHECK (idempotency_sha256 ~ '^[0-9a-f]{64}$'),
  request_fingerprint text NOT NULL CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
  response_snapshot jsonb NOT NULL,
  PRIMARY KEY (run_id, actor_id, checkout_id, operation, idempotency_sha256),
  FOREIGN KEY (run_id, checkout_id) REFERENCES checkout_sessions(run_id, checkout_id)
    ON DELETE CASCADE,
  FOREIGN KEY (run_id, actor_id) REFERENCES experiment_runs(run_id, actor_id)
    ON DELETE CASCADE,
  CONSTRAINT checkout_mutations_snapshot_id_matches
    CHECK ((response_snapshot ->> 'id' = checkout_id) IS TRUE)
);
