"""Merchant-owned catalog lifecycle; experimental episodes remain test fixtures."""

import argparse
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from commerce_lab.contracts import Offer
from commerce_lab.db import database_url
from commerce_lab.fixtures import fresh_p0_offers

MANAGED_CATALOG_VERSION = "merchant-catalog-v1"
MANAGED_ACTOR_ID = "merchant-agent"
OFFER_LIFETIME = timedelta(days=365)


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def managed_catalog_context() -> tuple[UUID, str] | None:
    with psycopg.connect(database_url()) as connection:
        row = connection.execute(
            "SELECT run_id, actor_id FROM experiment_runs WHERE variant = 'merchant'"
        ).fetchone()
    return (row[0], row[1]) if row is not None else None


def import_current_catalog() -> dict[str, object]:
    """Import the curated assortment once; restarts never regenerate price or inventory."""
    with psycopg.connect(database_url()) as connection, connection.transaction():
        connection.execute("SELECT pg_advisory_xact_lock(hashtext('merchant-catalog-import'))")
        existing = connection.execute(
            "SELECT run_id FROM experiment_runs WHERE variant = 'merchant'"
        ).fetchone()
        if existing is not None:
            return {"status": "already_imported", "run_id": str(existing[0])}
        now = datetime.now(UTC)
        offers = fresh_p0_offers()
        run_id = uuid4()
        manifest = {"source": "curated-assortment", "offer_count": len(offers)}
        connection.execute(
            """
            INSERT INTO experiment_runs
              (run_id, scenario_id, variant, fixture_version, clock_at, manifest, actor_id)
            VALUES (%s, %s, 'merchant', %s, %s, %s, %s)
            """,
            (
                run_id,
                "MERCHANT-01",
                MANAGED_CATALOG_VERSION,
                now,
                Jsonb(manifest),
                MANAGED_ACTOR_ID,
            ),
        )
        for offer in offers:
            snapshot = offer.model_dump(mode="json")
            snapshot["observed_at"] = _timestamp(now)
            snapshot["expires_at"] = _timestamp(now + OFFER_LIFETIME)
            imported = Offer.model_validate(snapshot)
            connection.execute(
                """
                INSERT INTO catalog_offers (run_id, offer_id, revision, snapshot)
                VALUES (%s, %s, %s, %s)
                """,
                (run_id, imported.id, imported.revision, Jsonb(imported.model_dump(mode="json"))),
            )
    return {"status": "imported", "run_id": str(run_id), "offer_count": len(offers)}


def changed_offer(
    offer: Offer,
    now: datetime,
    *,
    price_minor: int | None = None,
    stock: int | None = None,
) -> Offer:
    if price_minor is None and stock is None:
        raise ValueError("Specify a price or stock change")
    if price_minor is not None and price_minor < 0:
        raise ValueError("Price must be nonnegative")
    if stock is not None and stock < 0:
        raise ValueError("Stock must be nonnegative")
    snapshot = offer.model_dump(mode="json")
    snapshot["revision"] = offer.revision + 1
    snapshot["observed_at"] = _timestamp(now)
    snapshot["expires_at"] = _timestamp(now + OFFER_LIFETIME)
    if price_minor is not None:
        pricing = snapshot["pricing"]
        pricing["items_total_minor"] = price_minor
        pricing["total_minor"] = price_minor + pricing["shipping_total_minor"]
    if stock is not None:
        snapshot["available_quantity"] = stock
        snapshot["availability"] = "in_stock" if stock > 0 else "out_of_stock"
    return Offer.model_validate(snapshot)


def update_offer(
    offer_id: str, *, price_minor: int | None = None, stock: int | None = None
) -> Offer:
    """Edit an authoritative variant; pending checkouts must revalidate its revision."""
    now = datetime.now(UTC)
    with psycopg.connect(database_url()) as connection, connection.transaction():
        row = connection.execute(
            """
            SELECT offers.run_id, offers.revision, offers.snapshot
            FROM catalog_offers AS offers
            JOIN experiment_runs AS run ON run.run_id = offers.run_id
            WHERE run.variant = 'merchant' AND offers.offer_id = %s
            FOR UPDATE OF offers
            """,
            (offer_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Offer does not exist in the managed catalog")
        run_id, revision, raw = row
        original = Offer.model_validate(raw)
        if original.revision != revision:
            raise ValueError("Catalog revision does not match its snapshot")
        updated = changed_offer(original, now, price_minor=price_minor, stock=stock)
        connection.execute(
            """
            UPDATE catalog_offers SET revision = %s, snapshot = %s
            WHERE run_id = %s AND offer_id = %s
            """,
            (updated.revision, Jsonb(updated.model_dump(mode="json")), run_id, offer_id),
        )
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description="Administer the merchant's persistent catalog")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("import-current")
    change = commands.add_parser("update-offer")
    change.add_argument("offer_id")
    change.add_argument("--price-minor", type=int)
    change.add_argument("--stock", type=int)
    arguments = parser.parse_args()
    if arguments.command == "import-current":
        result = import_current_catalog()
    else:
        offer = update_offer(
            arguments.offer_id, price_minor=arguments.price_minor, stock=arguments.stock
        )
        result = {
            "offer_id": offer.id,
            "revision": offer.revision,
            "price_minor": offer.pricing.items_total_minor,
            "stock": offer.available_quantity,
        }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
