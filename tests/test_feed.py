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
MIN_PRODUCTS = 80


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
    assert status["Q106629718-128GB"] == {"available": True, "status": "limited_stock"}
    assert status["Q108044294-512GB"] == {"available": False, "status": "out_of_stock"}
    assert {item["status"] for item in status.values()} == {
        "in_stock",
        "limited_stock",
        "out_of_stock",
    }
    assert all(offer.pricing.currency == "cop" for offer in fresh_p0_offers())


def test_feed_groups_configurations_of_one_product_under_shared_metadata() -> None:
    _, products = build_feed(fresh_p0_offers(), base_url=ORIGIN)
    grouped = next(product for product in products if product["id"] == "prod-q104772244")
    variants = cast(list[dict[str, Any]], grouped["variants"])
    assert [variant["id"] for variant in variants] == [
        "Q104772244-128GB",
        "Q104772244-256GB",
        "Q104772244-512GB",
    ]
    # Cada variante publica su configuración como opciones; es lo que el agente filtra.
    options = {
        variant["id"]: {option["name"]: option["value"] for option in variant["variant_options"]}
        for variant in variants
    }
    assert options["Q104772244-128GB"]["Almacenamiento"] == "128 GB"
    assert options["Q104772244-512GB"]["Almacenamiento"] == "512 GB"
    # El nivel producto es común a todas las variantes.
    assert len({variant["title"].rsplit(" ", 1)[0] for variant in variants}) == 1


def test_feed_publishes_brand_in_its_own_taxonomy() -> None:
    _, products = build_feed(fresh_p0_offers(), base_url=ORIGIN)
    for product in products:
        for variant in cast(list[dict[str, Any]], product["variants"]):
            rows = cast(list[dict[str, str]], variant["categories"])
            taxonomies = {row["taxonomy"]: row["value"] for row in rows}
            # El esquema ACP no tiene campo de marca; viaja como categoría con taxonomía propia.
            assert taxonomies["merchant"] == "smartphones"
            assert taxonomies["brand"]


def test_every_product_has_an_image_served_by_the_merchant() -> None:
    _, products = build_feed(fresh_p0_offers(), base_url=ORIGIN)
    # Una tarjeta sin foto se ve peor que un catálogo más corto: el fixture descarta los
    # productos cuya imagen no se pudo descargar, así que aquí no debe faltar ninguna.
    for product in products:
        media = cast(list[dict[str, Any]], product["media"])
        url = str(media[0]["url"])
        assert url.startswith(f"{ORIGIN}/assets/products/")
        # La ruta derivada del id es el respaldo; ningún producto debe caer en ella.
        assert not url.endswith(f"/assets/products/{product['id']}.jpg")
