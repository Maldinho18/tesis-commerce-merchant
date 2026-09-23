import pytest
from pydantic import ValidationError

from commerce_lab.catalog import CatalogReader
from commerce_lab.contracts import Failure, Offer, ScenarioClock, Success
from commerce_lab.fixtures import (
    FIXTURE_DELIVERY_CONTEXT,
    FIXTURE_NOW,
    fresh_p0_offers,
)


def reader() -> CatalogReader:
    return CatalogReader(fresh_p0_offers(), ScenarioClock(FIXTURE_NOW))


def test_catalog_exposes_every_variant_of_a_category() -> None:
    result = reader().search({"category": "headphones"})
    # Incluye la variante agotada: la disponibilidad se comunica, no se oculta del catálogo.
    assert [offer.id for offer in result.data.offers] == [
        "APL-APP3",
        "SEN-MOM4-BLK",
        "SEN-MOM4-WHT",
        "SON-XM6-BLK",
        "SON-XM6-BLU",
        "SON-XM6-PLT",
    ]


def test_catalog_exposes_every_configuration_of_one_product() -> None:
    # La búsqueda pagina; el producto curado se aísla por product_id.
    offers = [
        offer for offer in fresh_p0_offers() if offer.product_id == "prod-asus-rog-zephyrus-g16"
    ]
    assert [offer.id for offer in offers] == [
        "ASUS-G16-16-5060-1TB",
        "ASUS-G16-32-5070-1TB",
        "ASUS-G16-32-5070TI-2TB",
        "ASUS-G16-32-5080-2TB",
    ]
    assert {offer.product_id for offer in offers} == {"prod-asus-rog-zephyrus-g16"}
    assert [offer.attributes["gpu"] for offer in offers] == [
        "RTX 5060",
        "RTX 5070",
        "RTX 5070 Ti",
        "RTX 5080",
    ]


def test_catalog_rejects_invented_identity_or_approval_fields() -> None:
    catalog = reader()
    with pytest.raises(ValidationError):
        catalog.search({"category": "headphones", "actor_id": "admin"})
    with pytest.raises(ValidationError):
        catalog.get(
            {
                "offer_id": "SON-XM6-BLK",
                "delivery_context": FIXTURE_DELIVERY_CONTEXT.model_dump(),
                "approved_by_user": True,
            }
        )


def test_catalog_returns_expired_offer_error_at_boundary() -> None:
    clock = ScenarioClock(FIXTURE_NOW)
    catalog = CatalogReader(fresh_p0_offers(), clock)
    clock.advance_seconds(15 * 60)
    result = catalog.get(
        {
            "offer_id": "SON-XM6-BLK",
            "delivery_context": FIXTURE_DELIVERY_CONTEXT.model_dump(),
        }
    )
    assert isinstance(result, Failure)
    assert result.error.code == "OFFER_EXPIRED"


def test_catalog_paginates_stably_and_isolates_caller_mutation() -> None:
    catalog = reader()
    first = catalog.search({"category": "headphones", "limit": 2})
    assert first.data.next_offset == 2
    first.data.offers[0].pricing.total_minor = 1
    original = catalog.get(
        {
            "offer_id": "APL-APP3",
            "delivery_context": FIXTURE_DELIVERY_CONTEXT.model_dump(),
        }
    )
    assert isinstance(original, Success)
    assert original.data.pricing.total_minor == 1_124_000_00
    second = catalog.search({"category": "headphones", "limit": 2, "offset": 2})
    assert [offer.id for offer in second.data.offers] == ["SEN-MOM4-WHT", "SON-XM6-BLK"]


def test_catalog_accepts_and_searches_a_product_from_an_unrelated_category() -> None:
    payload = fresh_p0_offers()[0].model_dump(mode="json")
    payload.update(
        {
            "id": "KEY-01",
            "product_id": "keyboard-01",
            "sku": "keyboard-01-brown",
            "category": "keyboard",
            "name": "Teclado mecanico de prueba",
            "brand": "Keyworks",
            "attributes": {"switch_type": "brown", "wireless": True},
        }
    )
    payload.pop("color")
    keyboard = Offer.model_validate(payload)
    catalog = CatalogReader([keyboard], ScenarioClock(FIXTURE_NOW))

    result = catalog.search({"category": "keyboard", "brand": "Keyworks"})

    assert [offer.id for offer in result.data.offers] == ["KEY-01"]
    assert result.data.offers[0].color is None
    assert result.data.offers[0].sku == "keyboard-01-brown"
    assert result.data.offers[0].attributes == {"switch_type": "brown", "wireless": True}
