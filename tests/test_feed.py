import json
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from commerce_lab.feed import build_feed, export_feed
from commerce_lab.fixtures import fresh_p0_offers

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = json.loads((ROOT / "vendor/acp/2026-04-17/schema.feed.json").read_text(encoding="utf-8"))
REGISTRY = Registry().with_resource(str(BUNDLE["$id"]), Resource.from_contents(BUNDLE))

# El origen se fija en la prueba para que el export no dependa de ACP_API_BASE_URL del entorno.
ORIGIN = "https://merchant.example.test"
# El catálogo se recolecta de una fuente externa: se afirma escala mínima e invariantes,
# no literales que quedarían obsoletos en cada recolección.
MIN_PRODUCTS = 150


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
    summary = export_feed(first, base_url=ORIGIN)
    export_feed(second, base_url=ORIGIN)
    assert isinstance(summary["product_count"], int)
    assert isinstance(summary["variant_count"], int)
    assert summary["product_count"] >= MIN_PRODUCTS
    assert summary["variant_count"] >= summary["product_count"]
    for name in ("metadata.json", "products.jsonl"):
        assert (first / name).read_bytes() == (second / name).read_bytes()
    metadata = json.loads((first / "metadata.json").read_text(encoding="utf-8"))
    validate("FeedMetadata", metadata)
    assert metadata == {
        "id": "feed_p0_tech",
        "target_country": "CO",
        "updated_at": "2026-09-10T14:00:00Z",
    }
    lines = (first / "products.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == summary["product_count"]
    products = [json.loads(line) for line in lines]
    assert [product["id"] for product in products] == sorted(product["id"] for product in products)
    assert len({product["id"] for product in products}) == len(products)
    variants = [variant for product in products for variant in product["variants"]]
    assert len(variants) == len({variant["id"] for variant in variants})
    assert {variant["id"] for variant in variants} == {offer.id for offer in fresh_p0_offers()}
    # El catálogo P0 agrupa configuraciones bajo un mismo producto; sin esto el filtro de
    # opciones del agente no tendría nada que discriminar.
    assert max(len(product["variants"]) for product in products) > 1
    for product in products:
        validate("Product", product)
        assert product["title"] and product["description"]["plain"] and product["url"]
        assert len(product["media"]) >= 1
        for media in product["media"]:
            validate("Media", media)
            assert media["type"] == "image"
            parsed_url = urlparse(media["url"])
            # La imagen siempre se publica como HTTPS absoluto. La sirve el propio comercio
            # bajo /assets/products, ya sea la foto descargada o la ruta derivada del id.
            assert parsed_url.scheme == "https" and parsed_url.netloc
            if parsed_url.netloc == "merchant.example.test":
                assert parsed_url.path.startswith("/assets/products/")
            assert media["alt_text"].strip()
        assert len(product["variants"]) >= 1
        variant_ids = [variant["id"] for variant in product["variants"]]
        assert variant_ids == sorted(variant_ids)
        for variant in product["variants"]:
            for definition, value in (
                ("Variant", variant),
                ("Price", variant["price"]),
                ("Availability", variant["availability"]),
            ):
                validate(definition, value)
            assert variant["price"]["currency"] == "COP"
            assert variant["price"]["amount"] >= 0
            for option in variant["variant_options"]:
                validate("VariantOption", option)
            names = [option["name"] for option in variant["variant_options"]]
            assert len(names) == len(set(names))
        assert "run_id" not in json.dumps(product)
        assert "token" not in json.dumps(product).lower()
    status = {variant["id"]: variant["availability"] for variant in variants}
    assert status["ASUS-G16-32-5070TI-2TB"] == {"available": True, "status": "limited_stock"}
    assert status["SON-XM6-BLU"] == {"available": False, "status": "out_of_stock"}
    assert {item["status"] for item in status.values()} == {
        "in_stock",
        "limited_stock",
        "out_of_stock",
    }
    assert all(offer.pricing.currency == "cop" for offer in fresh_p0_offers())


def test_feed_groups_configurations_of_one_product_under_shared_metadata() -> None:
    _, products = build_feed(fresh_p0_offers(), base_url=ORIGIN)
    zephyrus = next(
        product for product in products if product["id"] == "prod-asus-rog-zephyrus-g16"
    )
    variants = cast(list[dict[str, Any]], zephyrus["variants"])
    assert len(variants) == 4
    assert zephyrus["title"] == "ASUS ROG Zephyrus G16 (2025)"
    # Cada variante publica su configuración como opciones; es lo que el agente filtra.
    options = {
        variant["id"]: {option["name"]: option["value"] for option in variant["variant_options"]}
        for variant in variants
    }
    assert options["ASUS-G16-32-5070TI-2TB"]["RAM"] == "32 GB"
    assert options["ASUS-G16-32-5070TI-2TB"]["GPU"] == "RTX 5070 Ti"
    assert options["ASUS-G16-32-5070TI-2TB"]["Almacenamiento"] == "2 TB"
    assert options["ASUS-G16-16-5060-1TB"]["GPU"] == "RTX 5060"
    assert {variant["price"]["amount"] for variant in variants} == {
        8_999_000_00,
        11_499_000_00,
        13_999_000_00,
        16_999_000_00,
    }


def test_feed_price_is_item_only_and_checkout_must_add_shipping() -> None:
    _, products = build_feed(fresh_p0_offers(), base_url=ORIGIN)
    keychron = next(product for product in products if product["id"] == "prod-keychron-q3-max")
    variants = cast(list[dict[str, Any]], keychron["variants"])
    variant = next(item for item in variants if item["id"] == "KEY-Q3MAX-RED")
    assert variant["price"] == {"amount": 899_000_00, "currency": "COP"}
    offer = next(offer for offer in fresh_p0_offers() if offer.id == "KEY-Q3MAX-RED")
    assert offer.pricing.shipping_total_minor == 25_000_00
    assert offer.pricing.total_minor == 924_000_00
