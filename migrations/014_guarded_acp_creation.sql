CREATE TABLE guarded_checkout_creations (
  run_id uuid NOT NULL,
  actor_id text NOT NULL,
  idempotency_sha256 text NOT NULL CHECK (idempotency_sha256 ~ '^[0-9a-f]{64}$'),
  checkout_id text NOT NULL,
  guard_fingerprint text NOT NULL CHECK (guard_fingerprint ~ '^[0-9a-f]{64}$'),
  proof jsonb NOT NULL CHECK (jsonb_typeof(proof) = 'object'),
  proof_sha256 text NOT NULL CHECK (proof_sha256 ~ '^[0-9a-f]{64}$'),
  PRIMARY KEY (run_id, actor_id, idempotency_sha256),
  UNIQUE (run_id, checkout_id),
  FOREIGN KEY (run_id, checkout_id) REFERENCES checkout_sessions(run_id, checkout_id),
  CHECK ((proof ->> 'schema_version' = 'merchant-guarded-acp-proof/1') IS TRUE),
  CHECK ((proof ->> 'guard_fingerprint' = guard_fingerprint) IS TRUE),
  CHECK ((proof -> 'creation' ->> 'run_id' = run_id::text) IS TRUE),
  CHECK ((proof -> 'creation' ->> 'actor_id' = actor_id) IS TRUE),
  CHECK ((proof -> 'creation' ->> 'checkout_id' = checkout_id) IS TRUE),
  CHECK ((proof -> 'creation' ->> 'idempotency_key_sha256' = idempotency_sha256) IS TRUE)
);

CREATE FUNCTION preserve_guarded_creation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'guarded creation proof is immutable';
END;
$$;
CREATE TRIGGER guarded_creation_immutable BEFORE UPDATE OR DELETE ON guarded_checkout_creations
FOR EACH ROW EXECUTE FUNCTION preserve_guarded_creation();

CREATE FUNCTION bind_guarded_creation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM checkout_sessions c
    WHERE c.run_id = NEW.run_id AND c.actor_id = NEW.actor_id
      AND c.checkout_id = NEW.checkout_id AND c.idempotency_sha256 = NEW.idempotency_sha256
      AND (NEW.proof -> 'creation' ->> 'acp_create_fingerprint') = c.acp_create_fingerprint
      AND (NEW.proof -> 'creation' -> 'original_response') = c.acp_create_response
      AND (NEW.proof ->> 'offer_id') = (c.create_snapshot ->> 'offer_id')
      AND (NEW.proof ->> 'accepted_offer_revision')::bigint =
          (c.create_snapshot ->> 'offer_revision')::bigint
  ) OR EXISTS (
    SELECT 1 FROM rejected_guarded_checkout_attempts r
    WHERE r.run_id=NEW.run_id AND r.actor_id=NEW.actor_id
      AND r.idempotency_sha256=NEW.idempotency_sha256
  ) THEN
    RAISE EXCEPTION 'guarded creation must bind original ACP creation';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guarded_creation_binding BEFORE INSERT ON guarded_checkout_creations
FOR EACH ROW EXECUTE FUNCTION bind_guarded_creation();

-- Known semantic rejections also fix conditional attempt identity, without an effect.
CREATE TABLE rejected_guarded_checkout_attempts (
  run_id uuid NOT NULL,
  actor_id text NOT NULL,
  idempotency_sha256 text NOT NULL CHECK (idempotency_sha256 ~ '^[0-9a-f]{64}$'),
  guard_fingerprint text NOT NULL CHECK (guard_fingerprint ~ '^[0-9a-f]{64}$'),
  record jsonb NOT NULL CHECK (jsonb_typeof(record)='object'),
  record_sha256 text NOT NULL CHECK (record_sha256 ~ '^[0-9a-f]{64}$'),
  PRIMARY KEY (run_id,actor_id,idempotency_sha256),
  FOREIGN KEY (run_id,actor_id) REFERENCES experiment_runs(run_id,actor_id),
  CHECK ((record ->> 'schema_version' = 'merchant-guarded-acp-rejection/1') IS TRUE),
  CHECK ((record ->> 'run_id' = run_id::text) IS TRUE),
  CHECK ((record ->> 'actor_id' = actor_id) IS TRUE),
  CHECK ((record ->> 'idempotency_sha256' = idempotency_sha256) IS TRUE),
  CHECK ((record ->> 'guard_fingerprint' = guard_fingerprint) IS TRUE)
);
CREATE TRIGGER guarded_rejection_immutable BEFORE UPDATE OR DELETE ON rejected_guarded_checkout_attempts
FOR EACH ROW EXECUTE FUNCTION preserve_guarded_creation();
CREATE FUNCTION bind_guarded_rejection() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM guarded_checkout_creations c
    WHERE c.run_id=NEW.run_id AND c.actor_id=NEW.actor_id
      AND c.idempotency_sha256=NEW.idempotency_sha256
  ) THEN
    RAISE EXCEPTION 'accepted creation cannot become a rejected attempt';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guarded_rejection_binding BEFORE INSERT ON rejected_guarded_checkout_attempts
FOR EACH ROW EXECUTE FUNCTION bind_guarded_rejection();
