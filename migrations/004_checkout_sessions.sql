CREATE TABLE IF NOT EXISTS checkout_sessions (
  run_id uuid NOT NULL,
  checkout_id text NOT NULL,
  actor_id text NOT NULL,
  revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
  offer_id text NOT NULL,
  offer_revision integer NOT NULL CHECK (offer_revision > 0),
  quantity integer NOT NULL CHECK (quantity = 1),
  idempotency_sha256 text NOT NULL,
  request_fingerprint text NOT NULL,
  status text NOT NULL CHECK (status IN ('prepared', 'expired', 'canceled')),
  snapshot jsonb NOT NULL,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  PRIMARY KEY (run_id, checkout_id),
  UNIQUE (run_id, actor_id, idempotency_sha256),
  CONSTRAINT checkout_sessions_run_actor_fk
    FOREIGN KEY (run_id, actor_id)
    REFERENCES experiment_runs(run_id, actor_id)
    ON DELETE CASCADE,
  CONSTRAINT checkout_sessions_offer_fk
    FOREIGN KEY (run_id, offer_id)
    REFERENCES catalog_offers(run_id, offer_id),
  CONSTRAINT checkout_sessions_id_format
    CHECK (checkout_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
  CONSTRAINT checkout_sessions_hash_format
    CHECK (idempotency_sha256 ~ '^[0-9a-f]{64}$' AND request_fingerprint ~ '^[0-9a-f]{64}$'),
  CONSTRAINT checkout_sessions_time_order
    CHECK (updated_at >= created_at AND expires_at > created_at),
  CONSTRAINT checkout_sessions_snapshot_id_matches
    CHECK ((snapshot ->> 'id' = checkout_id) IS TRUE),
  CONSTRAINT checkout_sessions_snapshot_revision_matches
    CHECK (((snapshot ->> 'revision')::integer = revision) IS TRUE),
  CONSTRAINT checkout_sessions_snapshot_status_matches
    CHECK ((snapshot ->> 'status' = status) IS TRUE)
);

CREATE INDEX IF NOT EXISTS checkout_sessions_offer_lookup
  ON checkout_sessions(run_id, offer_id);
