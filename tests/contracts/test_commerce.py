import pytest
from pydantic import ValidationError

from commerce_lab.contracts import (
    MAX_SAFE_INTEGER,
    CatalogSearchInput,
    Checkout,
    CheckoutPrepareInput,
    ExecutionContext,
    Money,
    Offer,
    Pricing,
    ScenarioClock,
    is_expired,
    sum_minor_amounts,
)
from commerce_lab.fixtures import (
    FIXTURE_DELIVERY_CONTEXT,
    FIXTURE_EXPIRES_AT,
    FIXTURE_NOW,
    P0_OFFERS,
    fresh_p0_offers,
)


def checkout_payload() -> dict[str, object]:
    return {
        "id": "checkout-001",
        "revision": 1,
        "status": "prepared",
        "offer_id": "SON-01",
        "offer_revision": 1,
        "quantity": 1,
        "pricing": P0_OFFERS[3].pricing.model_dump(),
        "delivery_context": FIXTURE_DELIVERY_CONTEXT.model_dump(),
        "delivery_days": 3,
        "created_at": FIXTURE_NOW,
        "updated_at": FIXTURE_NOW,
        "expires_at": FIXTURE_EXPIRES_AT,
    }


def test_cop_uses_integer_minor_units_and_shipping_once() -> None:
    # COP tiene exponente 2, así que 8.999.000 pesos son 899.900.000 centavos enteros.
    assert Money(currency="cop", amount_minor=8_999_000_00).amount_minor == 899_900_000
    assert sum_minor_amounts(899_000_00, 25_000_00) == 924_000_00
    # El envío se suma exactamente una vez en cada oferta del catálogo.
    for offer in P0_OFFERS:
        assert offer.pricing.total_minor == (
            offer.pricing.items_total_minor + offer.pricing.shipping_total_minor
        )
        assert offer.pricing.tax_included is True
    keychron = next(offer for offer in P0_OFFERS if offer.id == "KEY-Q3MAX-RED")
    assert keychron.pricing.items_total_minor == 899_000_00
    assert keychron.pricing.shipping_total_minor == 25_000_00
    assert keychron.pricing.total_minor == 924_000_00
    with pytest.raises(ValidationError):
        Pricing.model_validate({**P0_OFFERS[0].pricing.model_dump(), "total_minor": 1})


def test_money_rejects_fractional_foreign_and_overflow_values() -> None:
    with pytest.raises(ValidationError):
        Money(currency="cop", amount_minor=0.1)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Money(currency="COP", amount_minor=100)
    with pytest.raises(ValueError, match="safe integer"):
        sum_minor_amounts(MAX_SAFE_INTEGER, 1)


def test_tool_input_cannot_claim_authority_or_price() -> None:
    payload = {
        "offer_id": "SON-01",
        "expected_offer_revision": 1,
        "quantity": 1,
        "delivery_context": FIXTURE_DELIVERY_CONTEXT.model_dump(),
        "idempotency_key": "checkout-create-001",
    }
    CheckoutPrepareInput.model_validate(payload)
    for injection in (
        {"actor_id": "admin"},
        {"run_id": "other-run"},
        {"approved": True},
        {"total_minor": 1},
    ):
        with pytest.raises(ValidationError):
            CheckoutPrepareInput.model_validate({**payload, **injection})
    context = ExecutionContext(
        actor_id="buyer-fixture",
        run_id="run-001",
        request_id="req-001",
        received_at=FIXTURE_NOW,
    )
    assert context.actor_id == "buyer-fixture"


def test_contract_requires_one_unit_revision_and_bounded_idempotency() -> None:
    base = {
        "offer_id": "SON-01",
        "expected_offer_revision": 1,
        "quantity": 1,
        "delivery_context": FIXTURE_DELIVERY_CONTEXT.model_dump(),
        "idempotency_key": "checkout-create-001",
    }
    for changed in (
        {"quantity": 2},
        {"expected_offer_revision": 0},
        {"idempotency_key": ""},
        {"idempotency_key": "a" * 256},
    ):
        with pytest.raises(ValidationError):
            CheckoutPrepareInput.model_validate({**base, **changed})
    search = CatalogSearchInput(category="headphones")
    assert search.offset == 0 and search.limit == 20


def test_checkout_is_not_a_payment_and_rejects_inconsistent_time() -> None:
    checkout = Checkout.model_validate(checkout_payload())
    assert checkout.status == "prepared"
    with pytest.raises(ValidationError):
        Checkout.model_validate({**checkout_payload(), "status": "paid"})
    with pytest.raises(ValidationError):
        Checkout.model_validate({**checkout_payload(), "updated_at": "2026-09-10T13:00:00Z"})


def test_each_scenario_starts_from_independent_fixture_state() -> None:
    changed = fresh_p0_offers()
    changed[0] = Offer.model_validate(
        {
            **changed[0].model_dump(),
            "availability": "out_of_stock",
            "available_quantity": 0,
            "revision": 2,
        }
    )
    assert changed[0].revision == 2
    assert fresh_p0_offers()[0].availability == "in_stock"
    assert fresh_p0_offers()[0].revision == 1


def test_legacy_offer_snapshot_derives_new_non_authoritative_fields() -> None:
    snapshot = P0_OFFERS[0].model_dump(mode="json")
    snapshot.pop("sku")
    snapshot.pop("attributes")

    offer = Offer.model_validate(snapshot)

    assert offer.sku == offer.id
    assert offer.attributes == {}


def test_fixture_has_exactly_two_admissible_asus_configurations() -> None:
    admissible = [
        offer.id
        for offer in P0_OFFERS
        if offer.brand == "ASUS"
        and offer.condition == "new"
        and offer.pricing.total_minor <= 12_000_000_00
        and offer.delivery_days <= 5
        and offer.available_quantity > 0
    ]
    assert admissible == ["ASUS-G16-16-5060-1TB", "ASUS-G16-32-5070-1TB"]
    assert all(offer.sku == offer.id for offer in P0_OFFERS)


def test_variant_attributes_carry_the_configuration_that_distinguishes_siblings() -> None:
    zephyrus = [offer for offer in P0_OFFERS if offer.product_id == "prod-asus-rog-zephyrus-g16"]
    assert len(zephyrus) == 4
    # Las variantes del mismo producto comparten los campos de nivel producto...
    assert len({offer.product_title for offer in zephyrus}) == 1
    assert len({offer.product_description for offer in zephyrus}) == 1
    assert len({offer.brand for offer in zephyrus}) == 1
    # ...y se distinguen por sus atributos, que son los que el agente filtra.
    assert {offer.attributes["gpu"] for offer in zephyrus} == {
        "RTX 5060",
        "RTX 5070",
        "RTX 5070 Ti",
        "RTX 5080",
    }
    assert all("ram" in offer.attributes and "storage" in offer.attributes for offer in zephyrus)


def test_every_p0_product_has_explicit_valid_internal_status() -> None:
    assert len(P0_OFFERS) == 34
    assert len({offer.product_id for offer in P0_OFFERS}) == 14
    assert len({offer.id for offer in P0_OFFERS}) == len(P0_OFFERS)
    assert {offer.product_status for offer in P0_OFFERS} == {"active"}
    assert all("product_status" in offer.model_dump() for offer in P0_OFFERS)
    with pytest.raises(ValidationError):
        Offer.model_validate({**P0_OFFERS[0].model_dump(), "product_status": "archived"})


def test_expiration_uses_injected_clock_at_exact_boundary() -> None:
    clock = ScenarioClock(FIXTURE_NOW)
    clock.advance_seconds(899)
    assert not is_expired(FIXTURE_EXPIRES_AT, clock)
    clock.advance_seconds(1)
    assert is_expired(FIXTURE_EXPIRES_AT, clock)
    with pytest.raises(ValueError):
        clock.advance_seconds(-1)
    assert ScenarioClock(FIXTURE_NOW).now() == FIXTURE_NOW
