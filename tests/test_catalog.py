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
    result = reader().search({"category": "smartphones"})
    identifiers = [offer.id for offer in result.data.offers]
    # La búsqueda pagina; devuelve el tope de la página en orden estable.
    assert identifiers == sorted(identifiers)
    assert len(identifiers) == len(set(identifiers))
    assert result.data.next_offset is not None


def test_catalog_exposes_every_configuration_of_one_product() -> None:
    offers = [offer for offer in fresh_p0_offers() if offer.product_id == "prod-q104772244"]
    assert [offer.id for offer in offers] == [
        "Q104772244-128GB",
        "Q104772244-256GB",
        "Q104772244-512GB",
    ]
    assert {offer.product_id for offer in offers} == {"prod-q104772244"}
    # Las variantes del mismo producto se distinguen por su configuración.
    assert [offer.attributes["storage"] for offer in offers] == ["128 GB", "256 GB", "512 GB"]


def test_catalog_rejects_invented_identity_or_approval_fields() -> None:
    catalog = reader()
    with pytest.raises(ValidationError):
        catalog.search({"category": "smartphones", "actor_id": "admin"})
    with pytest.raises(ValidationError):
        catalog.get(
            {
                "offer_id": "Q104772244-128GB",
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
            "offer_id": "Q104772244-128GB",
            "delivery_context": FIXTURE_DELIVERY_CONTEXT.model_dump(),
        }
    )
    assert isinstance(result, Failure)
    assert result.error.code == "OFFER_EXPIRED"


def test_catalog_paginates_stably_and_isolates_caller_mutation() -> None:
    catalog = reader()
    first = catalog.search({"category": "smartphones", "limit": 2})
    assert first.data.next_offset == 2
    first.data.offers[0].pricing.total_minor = 1
    original = catalog.get(
        {
            "offer_id": "BBGooglePixel7a-128GB",
            "delivery_context": FIXTURE_DELIVERY_CONTEXT.model_dump(),
        }
    )
    assert isinstance(original, Success)
    assert original.data.pricing.total_minor == 1_775_000_00
    second = catalog.search({"category": "smartphones", "limit": 2, "offset": 2})
    assert [offer.id for offer in second.data.offers] == [
        "BBGooglePixel8-256GB",
        "BBGooglePixel8Pro-128GB",
    ]


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
