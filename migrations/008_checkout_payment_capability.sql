ALTER TABLE checkout_sessions DROP CONSTRAINT IF EXISTS checkout_sessions_status_check;
ALTER TABLE checkout_sessions
  ADD CONSTRAINT checkout_sessions_status_check
  CHECK (status IN ('prepared', 'ready_for_payment', 'expired', 'canceled'));
