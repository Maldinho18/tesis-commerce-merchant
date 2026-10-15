-- Existing rows remain NULL: their original ACP response cannot be reconstructed.
ALTER TABLE checkout_sessions
  ADD COLUMN acp_create_fingerprint text,
  ADD COLUMN acp_create_response jsonb;

ALTER TABLE checkout_sessions ADD CONSTRAINT checkout_sessions_acp_creation_pair CHECK (
  (acp_create_fingerprint IS NULL AND acp_create_response IS NULL)
  OR (
    acp_create_fingerprint IS NOT NULL AND acp_create_response IS NOT NULL
    AND acp_create_fingerprint ~ '^[0-9a-f]{64}$'
    AND jsonb_typeof(acp_create_response) = 'object'
    AND ((acp_create_response ->> 'id') = checkout_id) IS TRUE
    AND ((acp_create_response -> 'protocol' ->> 'version') = '2026-04-17') IS TRUE
  )
);

CREATE FUNCTION preserve_checkout_creation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.run_id IS DISTINCT FROM OLD.run_id
     OR NEW.actor_id IS DISTINCT FROM OLD.actor_id
     OR NEW.checkout_id IS DISTINCT FROM OLD.checkout_id
     OR NEW.idempotency_sha256 IS DISTINCT FROM OLD.idempotency_sha256
     OR NEW.request_fingerprint IS DISTINCT FROM OLD.request_fingerprint
     OR NEW.create_snapshot IS DISTINCT FROM OLD.create_snapshot
     OR (OLD.acp_create_fingerprint IS NOT NULL AND (
       NEW.acp_create_fingerprint IS DISTINCT FROM OLD.acp_create_fingerprint
       OR NEW.acp_create_response IS DISTINCT FROM OLD.acp_create_response
     )) THEN
    RAISE EXCEPTION 'checkout creation identity is immutable';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER checkout_creation_immutable BEFORE UPDATE ON checkout_sessions
FOR EACH ROW EXECUTE FUNCTION preserve_checkout_creation();
