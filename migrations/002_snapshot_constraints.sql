-- A SQL CHECK accepts NULL. Require TRUE so absent/null JSON fields fail.
-- Replace the original unnamed checks as well as these stable names, making
-- this migration safe to reapply to both existing and newly created tables.
ALTER TABLE catalog_offers
  DROP CONSTRAINT IF EXISTS catalog_offers_check,
  DROP CONSTRAINT IF EXISTS catalog_offers_check1,
  DROP CONSTRAINT IF EXISTS catalog_offers_snapshot_id_matches,
  DROP CONSTRAINT IF EXISTS catalog_offers_snapshot_revision_matches;

ALTER TABLE catalog_offers
  ADD CONSTRAINT catalog_offers_snapshot_id_matches
    CHECK ((snapshot ->> 'id' = offer_id) IS TRUE),
  ADD CONSTRAINT catalog_offers_snapshot_revision_matches
    CHECK (((snapshot ->> 'revision')::integer = revision) IS TRUE);
