import pytest
from pydantic import ValidationError

from commerce_lab.catalog import CatalogReader
from commerce_lab.contracts import Failure, Offer, ScenarioClock, Success
from commerce_lab.fixtures import (
    FIXTURE_DELIVERY_CONTEXT,
    FIXTURE_NOW,
    fresh_sonora_offers,
)


def reader() -> CatalogReader:
    return CatalogReader(fresh_sonora_offers(), ScenarioClock(FIXTURE_NOW))


def test_catalog_exposes_all_five_alternatives() -> None:
    result = reader().search({"category": "headphones"})
    assert [offer.id for offer in result.data.offers] == [
        "ALT-01",
        "SON-01",
        "SON-02",
        "SON-03",
        "SON-04",
    ]


def test_catalog_rejects_invented_identity_or_approval_fields() -> None:
    catalog = reader()
    with pytest.raises(ValidationError):
        catalog.search({"category": "headphones", "actor_id": "admin"})
    with pytest.raises(ValidationError):
        catalog.get(
            {
                "offer_id": "SON-01",
                "delivery_context": FIXTURE_DELIVERY_CONTEXT.model_dump(),
                "approved_by_user": True,
            }
        )


def test_catalog_returns_expired_offer_error_at_boundary() -> None:
    clock = ScenarioClock(FIXTURE_NOW)
    catalog = CatalogReader(fresh_sonora_offers(), clock)
    clock.advance_seconds(15 * 60)
    result = catalog.get(
        {
            "offer_id": "SON-01",
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
            "offer_id": "ALT-01",
            "delivery_context": FIXTURE_DELIVERY_CONTEXT.model_dump(),
        }
    )
    assert isinstance(original, Success)
    assert original.data.pricing.total_minor == 62_000_000
    second = catalog.search({"category": "headphones", "limit": 2, "offset": 2})
    assert [offer.id for offer in second.data.offers] == ["SON-02", "SON-03"]


def test_catalog_accepts_and_searches_a_product_from_an_unrelated_category() -> None:
    payload = fresh_sonora_offers()[0].model_dump(mode="json")
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
