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


def test_usd_uses_integer_minor_units_and_shipping_once() -> None:
    assert Money(currency="usd", amount_minor=72_000).amount_minor == 72_000
    assert sum_minor_amounts(72_000, 2_000) == 74_000
    assert [offer.pricing.total_minor for offer in P0_OFFERS] == [
        62_000,
        67_500,
        71_500,
        74_000,
        78_000,
        82_000,
        66_000,
        98_000,
        73_000,
        73_000,
    ]
    with pytest.raises(ValidationError):
        Pricing.model_validate({**P0_OFFERS[0].pricing.model_dump(), "total_minor": 1})


def test_money_rejects_fractional_foreign_and_overflow_values() -> None:
    with pytest.raises(ValidationError):
        Money(currency="usd", amount_minor=0.1)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Money(currency="USD", amount_minor=100)
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


def test_fixture_has_exactly_two_admissible_sonora_offers() -> None:
    admissible = [
        offer.id
        for offer in P0_OFFERS
        if offer.brand == "Sonora"
        and offer.condition == "new"
        and offer.pricing.total_minor <= 80_000
        and offer.delivery_days <= 5
        and offer.available_quantity > 0
    ]
    assert admissible == ["SON-01", "SON-02"]
    assert all(offer.sku == offer.id for offer in P0_OFFERS)
    assert all(offer.attributes == {"color": offer.color} for offer in P0_OFFERS)


def test_all_ten_p0_products_have_explicit_valid_internal_status() -> None:
    assert len(P0_OFFERS) == len({offer.product_id for offer in P0_OFFERS}) == 10
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
