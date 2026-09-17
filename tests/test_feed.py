import json
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from commerce_lab.feed import build_feed, export_feed
from commerce_lab.fixtures import fresh_p0_offers

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = json.loads((ROOT / "vendor/acp/2026-04-17/schema.feed.json").read_text(encoding="utf-8"))
REGISTRY = Registry().with_resource(str(BUNDLE["$id"]), Resource.from_contents(BUNDLE))


def validate(definition: str, value: object) -> None:
    Draft202012Validator(
        {"$ref": f"{BUNDLE['$id']}#/$defs/{definition}"},
        registry=REGISTRY,
        format_checker=FormatChecker(),
    ).validate(value)


def test_feed_export_is_deterministic_schema_valid_and_has_unique_stable_ids(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr("commerce_lab.feed._read_offers", lambda run_id: fresh_p0_offers())
    first = tmp_path / "first"
    second = tmp_path / "second"
    summary = export_feed(first)
    export_feed(second)
    assert summary["product_count"] == summary["variant_count"] == 10
    for name in ("metadata.json", "products.jsonl"):
        assert (first / name).read_bytes() == (second / name).read_bytes()
    metadata = json.loads((first / "metadata.json").read_text(encoding="utf-8"))
    validate("FeedMetadata", metadata)
    assert metadata == {
        "id": "feed_p0_headphones",
        "target_country": "CO",
        "updated_at": "2026-09-10T14:00:00Z",
    }
    lines = (first / "products.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 10
    products = [json.loads(line) for line in lines]
    assert [product["id"] for product in products] == sorted(product["id"] for product in products)
    assert len({product["id"] for product in products}) == 10
    variants = [variant for product in products for variant in product["variants"]]
    assert len(variants) == len({variant["id"] for variant in variants}) == 10
    assert {variant["id"] for variant in variants} == {offer.id for offer in fresh_p0_offers()}
    for product in products:
        validate("Product", product)
        assert product["title"] and product["description"]["plain"] and product["url"]
        assert len(product["variants"]) == 1
        variant = product["variants"][0]
        for definition, value in (
            ("Variant", variant),
            ("Price", variant["price"]),
            ("Availability", variant["availability"]),
        ):
            validate(definition, value)
        assert variant["price"]["currency"] == "USD"
        assert variant["price"]["amount"] >= 0
        assert "run_id" not in json.dumps(product)
        assert "token" not in json.dumps(product).lower()
    status = {variant["id"]: variant["availability"] for variant in variants}
    assert status["SON-03"] == {"available": True, "status": "limited_stock"}
    assert status["SON-07"] == {"available": False, "status": "out_of_stock"}
    assert {item["status"] for item in status.values()} == {
        "in_stock",
        "limited_stock",
        "out_of_stock",
    }
    assert all(offer.pricing.currency == "usd" for offer in fresh_p0_offers())


def test_feed_price_is_item_only_and_checkout_must_add_shipping() -> None:
    _, products = build_feed(fresh_p0_offers())
    sonora = next(product for product in products if product["id"] == "prod-son-01")
    variant = cast(list[dict[str, Any]], sonora["variants"])[0]
    assert variant["price"] == {"amount": 72_000, "currency": "USD"}
    offer = next(offer for offer in fresh_p0_offers() if offer.id == "SON-01")
    assert offer.pricing.shipping_total_minor == 2_000
    assert offer.pricing.total_minor == 74_000
