ALTER TABLE experiment_runs DROP CONSTRAINT IF EXISTS experiment_runs_variant_check;
ALTER TABLE experiment_runs ADD CONSTRAINT experiment_runs_variant_check
  CHECK (variant IN ('preparation', 'B0', 'B1', 'B2', 'merchant'));

CREATE UNIQUE INDEX IF NOT EXISTS one_managed_merchant_catalog
  ON experiment_runs (variant) WHERE variant = 'merchant';

ALTER TABLE catalog_offers
  ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

CREATE OR REPLACE FUNCTION touch_catalog_offer_updated_at()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS catalog_offer_updated_at ON catalog_offers;
CREATE TRIGGER catalog_offer_updated_at
BEFORE UPDATE ON catalog_offers
FOR EACH ROW EXECUTE FUNCTION touch_catalog_offer_updated_at();
