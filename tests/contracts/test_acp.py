import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from pydantic import ValidationError as ModelValidationError
from referencing import Registry, Resource

from commerce_lab.acp import ACPCheckoutCreateRequest

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / "vendor" / "acp"
FIXTURES = ROOT / "src" / "commerce" / "fixtures" / "acp"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


BUNDLE = read_json(VENDOR / "2026-04-17" / "schema.agentic_checkout.json")
PROVENANCE = read_json(VENDOR / "provenance.json")
CREATE_REQUEST = read_json(FIXTURES / "create-request.json")
CREATE_RESPONSE = read_json(FIXTURES / "create-response.json")
GET_REQUEST = read_json(FIXTURES / "get-request.json")
GET_RESPONSE = read_json(FIXTURES / "get-response.json")
REGISTRY = Registry().with_resource(str(BUNDLE["$id"]), Resource.from_contents(BUNDLE))


def validator(definition: str) -> Draft202012Validator:
    return Draft202012Validator({"$ref": f"{BUNDLE['$id']}#/$defs/{definition}"}, registry=REGISTRY)


def test_upstream_acp_sources_match_recorded_hashes() -> None:
    feed_paths = {
        source["upstream_path"] for source in PROVENANCE["files"] if "feed" in source["path"]
    }
    assert feed_paths == {
        "spec/2026-04-17/json-schema/schema.feed.json",
        "spec/2026-04-17/openapi/openapi.feed.yaml",
    }
    assert PROVENANCE["commit"] == "7fdd78df677a94dce04c770644b0fbbb1401272b"
    for source in PROVENANCE["files"]:
        path = VENDOR / source["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == source["sha256"]
        assert source["modified"] is False


def test_acp_create_and_get_examples_validate_against_frozen_bundle() -> None:
    validator("CheckoutSessionCreateRequest").validate(CREATE_REQUEST["body"])
    checkout_validator = validator("CheckoutSession")
    checkout_validator.validate(CREATE_RESPONSE["body"])
    checkout_validator.validate(GET_RESPONSE["body"])
    assert CREATE_RESPONSE["status"] == 201
    assert GET_RESPONSE["status"] == 200
    assert GET_REQUEST["path"] == f"/checkout_sessions/{CREATE_RESPONSE['body']['id']}"
    assert GET_RESPONSE["body"] == CREATE_RESPONSE["body"]


def test_acp_create_accepts_empty_capabilities_and_strict_legacy_payment() -> None:
    minimum = {
        "currency": "usd",
        "line_items": [{"id": "SON-01"}],
        "capabilities": {},
    }
    validator("CheckoutSessionCreateRequest").validate(minimum)
    ACPCheckoutCreateRequest.model_validate(minimum)
    ACPCheckoutCreateRequest.model_validate(
        {**minimum, "capabilities": {"payment": {"handlers": []}}}
    )
    for capabilities in (
        {"invented": True},
        {"payment": {"handlers": [{"type": "unimplemented"}]}},
        {"payment": {}},
        {"payment": None},
    ):
        with pytest.raises(ModelValidationError):
            ACPCheckoutCreateRequest.model_validate({**minimum, "capabilities": capabilities})


def test_acp_http_fixture_uses_version_authentication_and_idempotency() -> None:
    assert CREATE_REQUEST["headers"]["API-Version"] == "2026-04-17"
    assert GET_REQUEST["headers"]["API-Version"] == "2026-04-17"
    assert CREATE_REQUEST["headers"]["Authorization"].startswith("Bearer ")
    assert (
        CREATE_REQUEST["headers"]["Idempotency-Key"]
        == CREATE_RESPONSE["headers"]["Idempotency-Key"]
    )
    assert "body" not in GET_REQUEST


def test_acp_rejects_missing_capabilities_and_internal_revision() -> None:
    create_validator = validator("CheckoutSessionCreateRequest")
    checkout_validator = validator("CheckoutSession")
    missing = copy.deepcopy(CREATE_REQUEST["body"])
    del missing["capabilities"]
    with pytest.raises(ValidationError):
        create_validator.validate(missing)
    with pytest.raises(ValidationError):
        create_validator.validate({**CREATE_REQUEST["body"], "revision": 1})
    with pytest.raises(ValidationError):
        checkout_validator.validate({**GET_RESPONSE["body"], "revision": 1})


def test_acp_checkout_fixture_is_not_a_purchase() -> None:
    body = GET_RESPONSE["body"]
    assert body["status"] == "not_ready_for_payment"
    assert body["capabilities"]["payment"]["handlers"] == []
    total = next(item for item in body["totals"] if item["type"] == "total")
    assert total["amount"] == 74_000
    assert body["line_items"][0]["quantity"] == 1
    assert "order" not in body


def test_lifecycle_requests_and_states_follow_frozen_bundle() -> None:
    update = {
        "selected_fulfillment_options": [
            {"type": "shipping", "option_id": "ship_chk_001", "item_ids": ["li_chk_001"]}
        ]
    }
    validator("CheckoutSessionUpdateRequest").validate(update)
    validator("CancelSessionRequest").validate({})
    with pytest.raises(ValidationError):
        validator("CheckoutSessionUpdateRequest").validate({**update, "revision": 2})
    checkout = copy.deepcopy(GET_RESPONSE["body"])
    for state in ("not_ready_for_payment", "expired", "canceled"):
        checkout["status"] = state
        validator("CheckoutSession").validate(checkout)
    checkout["status"] = "prepared"
    with pytest.raises(ValidationError):
        validator("CheckoutSession").validate(checkout)


def test_p0_buyer_fulfillment_and_update_requests_validate_against_schema() -> None:
    buyer = {"email": "buyer.p0@example.test", "first_name": "Buyer", "last_name": "P0"}
    fulfillment = {
        "name": "Buyer P0",
        "email": "buyer.p0@example.test",
        "phone_number": "+573000000000",
        "address": {
            "name": "Buyer P0",
            "line_one": "Calle 100 # 10-20",
            "city": "Bogota",
            "state": "DC",
            "country": "CO",
            "postal_code": "110111",
        },
    }
    selection = [{"type": "shipping", "option_id": "ship_chk_001", "item_ids": ["li_chk_001"]}]

    validator("Buyer").validate(buyer)
    validator("FulfillmentDetails").validate(fulfillment)

    update_validator = validator("CheckoutSessionUpdateRequest")
    update_validator.validate({"buyer": buyer})
    update_validator.validate({"fulfillment_details": fulfillment})
    update_validator.validate({"selected_fulfillment_options": selection})
    update_validator.validate(
        {
            "buyer": buyer,
            "fulfillment_details": fulfillment,
            "selected_fulfillment_options": selection,
        }
    )

    checkout = copy.deepcopy(GET_RESPONSE["body"])
    checkout["buyer"] = buyer
    checkout["fulfillment_details"] = fulfillment
    checkout["selected_fulfillment_options"] = selection
    validator("CheckoutSession").validate(checkout)


def fmt_validator(definition: str) -> Draft202012Validator:
    """Validator with FormatChecker enabled — mirrors _UPDATE_VALIDATOR in acp.py."""
    return Draft202012Validator(
        {"$ref": f"{BUNDLE['$id']}#/$defs/{definition}"},
        registry=REGISTRY,
        format_checker=FormatChecker(),
    )


def test_email_format_validation_accepts_valid_buyer_email() -> None:
    buyer = {"email": "buyer.valid@example.test", "first_name": "Buyer", "last_name": "Valid"}
    fmt_validator("Buyer").validate(buyer)  # must not raise


def test_email_format_validation_rejects_invalid_buyer_email() -> None:
    buyer = {"email": "not-an-email", "first_name": "Buyer", "last_name": "Bad"}
    with pytest.raises(ValidationError, match="not-an-email"):
        fmt_validator("Buyer").validate(buyer)


def test_email_format_validation_accepts_valid_fulfillment_email() -> None:
    fulfillment = {
        "name": "Dest Valid",
        "email": "dest.valid@example.test",
        "phone_number": "+573000000000",
        "address": {
            "name": "Dest Valid",
            "line_one": "Calle 100 # 10-20",
            "city": "Bogota",
            "state": "DC",
            "country": "CO",
            "postal_code": "110111",
        },
    }
    fmt_validator("FulfillmentDetails").validate(fulfillment)  # must not raise


def test_email_format_validation_rejects_invalid_fulfillment_email() -> None:
    fulfillment = {
        "name": "Dest Bad",
        "email": "not-an-email",
        "phone_number": "+573000000000",
        "address": {
            "name": "Dest Bad",
            "line_one": "Calle 100 # 10-20",
            "city": "Bogota",
            "state": "DC",
            "country": "CO",
            "postal_code": "110111",
        },
    }
    with pytest.raises(ValidationError, match="not-an-email"):
        fmt_validator("FulfillmentDetails").validate(fulfillment)
