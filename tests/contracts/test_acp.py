import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry, Resource

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
    assert total["amount"] == 74_000_000
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
