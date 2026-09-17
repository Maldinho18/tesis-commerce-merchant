ALTER TABLE experiment_runs
  ADD COLUMN IF NOT EXISTS actor_id text;

UPDATE experiment_runs
SET actor_id = 'preparation-fixture'
WHERE actor_id IS NULL;

ALTER TABLE experiment_runs
  ALTER COLUMN actor_id SET NOT NULL;

ALTER TABLE experiment_runs
  DROP CONSTRAINT IF EXISTS experiment_runs_actor_id_format;

ALTER TABLE experiment_runs
  ADD CONSTRAINT experiment_runs_actor_id_format
    CHECK (actor_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$');

CREATE UNIQUE INDEX IF NOT EXISTS experiment_runs_run_actor
  ON experiment_runs(run_id, actor_id);

CREATE TABLE IF NOT EXISTS lab_sessions (
  session_sha256 text PRIMARY KEY,
  run_id uuid NOT NULL,
  actor_id text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  CONSTRAINT lab_sessions_hash_format CHECK (session_sha256 ~ '^[0-9a-f]{64}$'),
  CONSTRAINT lab_sessions_expiration CHECK (expires_at > created_at),
  CONSTRAINT lab_sessions_run_actor_fk
    FOREIGN KEY (run_id, actor_id)
    REFERENCES experiment_runs(run_id, actor_id)
    ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS lab_sessions_active_lookup
  ON lab_sessions(session_sha256, expires_at)
  WHERE revoked_at IS NULL;
