"""Deterministic full-replacement Product Feed export from merchant DB snapshots."""

import argparse
import json
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from commerce_lab.contracts import Offer
from commerce_lab.db import database_url
from commerce_lab.db.core import FIXTURE_VERSION

_BUNDLE: dict[str, Any] = json.loads(
    (Path(__file__).resolve().parents[2] / "vendor/acp/2026-04-17/schema.feed.json").read_text(
        encoding="utf-8"
    )
)
_REGISTRY = Registry().with_resource(str(_BUNDLE["$id"]), Resource.from_contents(_BUNDLE))
_CHECKER = FormatChecker()
_METADATA_VALIDATOR = Draft202012Validator(
    {"$ref": f"{_BUNDLE['$id']}#/$defs/FeedMetadata"},
    registry=_REGISTRY,
    format_checker=_CHECKER,
)
_PRODUCT_VALIDATOR = Draft202012Validator(
    {"$ref": f"{_BUNDLE['$id']}#/$defs/Product"},
    registry=_REGISTRY,
    format_checker=_CHECKER,
)


def _json_line(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def build_feed(offers: list[Offer]) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Project one authoritative Offer snapshot to one Product with one Variant."""
    if not offers:
        raise ValueError("P0 feed requires merchant offers")
    if len({offer.id for offer in offers}) != len(offers):
        raise ValueError("P0 feed requires unique variant IDs")
    if len({offer.product_id for offer in offers}) != len(offers):
        raise ValueError("P0 feed requires one variant per product")
    if any(offer.pricing.currency != "usd" for offer in offers):
        raise ValueError("P0 feed requires USD merchant snapshots")
    if len({offer.delivery_context.country for offer in offers}) != 1:
        raise ValueError("P0 feed requires one target country")

    metadata: dict[str, object] = {
        "id": "feed_p0_headphones",
        "target_country": offers[0].delivery_context.country,
        "updated_at": max(offer.observed_at for offer in offers),
    }
    products: list[dict[str, object]] = []
    for offer in sorted(offers, key=lambda item: item.product_id):
        availability_status = (
            "out_of_stock"
            if offer.available_quantity == 0
            else "limited_stock"
            if offer.available_quantity == 1
            else "in_stock"
        )
        url = f"https://merchant.example.test/products/{offer.product_id}"
        variant: dict[str, object] = {
            "id": offer.id,
            "title": offer.name,
            "url": f"{url}?variant={offer.id}",
            # Checkout/discovery use lowercase usd; feed Price requires ISO 4217 uppercase.
            "price": {"amount": offer.pricing.items_total_minor, "currency": "USD"},
            "availability": {
                "available": offer.available_quantity > 0,
                "status": availability_status,
            },
            "categories": [{"value": offer.category, "taxonomy": "merchant"}],
            "condition": [offer.condition],
            "variant_options": ([{"name": "Color", "value": offer.color}] if offer.color else []),
            "seller": {"name": "Synthetic Commerce Merchant"},
        }
        product: dict[str, object] = {
            "id": offer.product_id,
            "title": offer.name,
            "description": {"plain": f"Synthetic {offer.brand} headphones, {offer.condition}."},
            "url": url,
            "media": [
                {
                    "type": "image",
                    "url": f"https://merchant.example.test/assets/products/{offer.product_id}.jpg",
                    "alt_text": offer.name,
                }
            ],
            "variants": [variant],
        }
        _PRODUCT_VALIDATOR.validate(product)
        products.append(product)
    _METADATA_VALIDATOR.validate(metadata)
    return metadata, products


def _read_offers(run_id: str | None) -> list[Offer]:
    with psycopg.connect(database_url()) as connection, connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        if run_id is None:
            selected = connection.execute(
                """SELECT run_id FROM experiment_runs
                   WHERE fixture_version = %s
                   ORDER BY created_at DESC, run_id DESC LIMIT 1""",
                (FIXTURE_VERSION,),
            ).fetchone()
        else:
            selected = connection.execute(
                "SELECT run_id FROM experiment_runs WHERE run_id = %s AND fixture_version = %s",
                (UUID(run_id), FIXTURE_VERSION),
            ).fetchone()
        if selected is None:
            raise ValueError("Seed a P0 merchant episode before exporting the feed")
        rows = connection.execute(
            "SELECT snapshot FROM catalog_offers WHERE run_id = %s ORDER BY offer_id",
            (selected[0],),
        ).fetchall()
    return [Offer.model_validate(row[0]) for row in rows]


def export_feed(output_dir: Path, *, run_id: str | None = None) -> dict[str, object]:
    metadata, products = build_feed(_read_offers(run_id))
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "metadata.json").write_text(_json_line(metadata), encoding="utf-8")
    (output_dir / "products.jsonl").write_text(
        "".join(_json_line(product) for product in products), encoding="utf-8"
    )
    return {
        "metadata": str(output_dir / "metadata.json"),
        "products": str(output_dir / "products.jsonl"),
        "product_count": len(products),
        "variant_count": len(products),
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m commerce_lab.feed")
    parser.add_argument("command", choices=["export"])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-id")
    arguments = parser.parse_args()
    try:
        result = export_feed(arguments.output_dir, run_id=arguments.run_id)
    except Exception:
        parser.exit(1, "P0 feed export failed. Check merchant database and snapshots.\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
