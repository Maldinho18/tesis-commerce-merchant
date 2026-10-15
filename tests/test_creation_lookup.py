import hashlib
from copy import deepcopy
from typing import Any

import pytest
from jsonschema import ValidationError as SchemaError
from pydantic import TypeAdapter, ValidationError

from commerce_lab.contracts.creation_lookup import (
    LOOKUP_SCHEMA,
    CreationFound,
    CreationLookupError,
    CreationLookupInput,
    CreationLookupResult,
    canonical_original_response,
    original_response_sha256,
)


def original() -> dict[str, Any]:
    return {
        "id": "chk_lookup",
        "protocol": {"version": "2026-04-17"},
        "status": "not_ready_for_payment",
        "currency": "cop",
        "capabilities": {},
        "line_items": [
            {
                "id": "li_lookup",
                "item": {"id": "offer_lookup"},
                "quantity": 1,
                "totals": [{"type": "total", "display_text": "Total", "amount": 10}],
            }
        ],
        "totals": [{"type": "total", "display_text": "Total", "amount": 10}],
        "fulfillment_options": [],
        "messages": [],
        "links": [],
    }


def found() -> dict[str, Any]:
    response = original()
    return {
        "schema_version": LOOKUP_SCHEMA,
        "result": "found",
        "run_id": "run_test",
        "actor_id": "actor_test",
        "request_id": "request_test",
        "idempotency_key_sha256": "1" * 64,
        "acp_api_version": "2026-04-17",
        "acp_create_fingerprint": "2" * 64,
        "checkout_id": "chk_lookup",
        "original_response": response,
        "original_response_profile": "merchant-acp-original-response/1",
        "original_response_sha256": original_response_sha256(response),
    }


def test_canonical_vector_key_order_unicode_sequences_and_domain():
    value = {"z": [2, 1], "a": "café"}
    expected = b'{"a":"caf\xc3\xa9","z":[2,1]}'
    assert canonical_original_response(value) == expected
    assert (
        original_response_sha256(value)
        == hashlib.sha256(b"merchant-acp-original-response/v1\0" + expected).hexdigest()
    )
    assert original_response_sha256(
        dict(reversed(list(value.items())))
    ) == original_response_sha256(value)
    assert original_response_sha256({**value, "z": [1, 2]}) != original_response_sha256(value)
    assert original_response_sha256({"a": "é"}) != original_response_sha256({"a": "e\u0301"})
    assert original_response_sha256(value) != hashlib.sha256(expected).hexdigest()


@pytest.mark.parametrize(
    "value",
    [1.0, float("nan"), float("inf"), 2**53, {1: "value"}, (1, 2), "\ud800", {"token": "secret"}],
)
def test_canonical_profile_rejects_unsupported_values(value):
    with pytest.raises((ValueError, UnicodeError)):
        canonical_original_response(value)


@pytest.mark.parametrize(
    "digest", ["A" * 64, "a" * 63, "a" * 65, "g" * 64, "a" * 63 + "\n", 123, None]
)
def test_request_digest_is_exact_lowercase_hex(digest):
    with pytest.raises(ValidationError):
        CreationLookupInput.model_validate(
            {"schema_version": LOOKUP_SCHEMA, "idempotency_key_sha256": digest}
        )


@pytest.mark.parametrize(
    "field", ["run_id", "actor_id", "checkout_id", "bearer_token", "idempotency_key", "trusted"]
)
def test_request_rejects_authority_and_secret_substitutes(field):
    with pytest.raises(ValidationError):
        CreationLookupInput.model_validate(
            {
                "schema_version": LOOKUP_SCHEMA,
                "idempotency_key_sha256": "1" * 64,
                field: "do-not-echo",
            }
        )


def test_discriminated_response_and_versions_are_closed():
    adapter = TypeAdapter(CreationLookupResult)
    assert isinstance(adapter.validate_python(found()), CreationFound)
    for result in ("not_found", "unrecoverable"):
        value = {
            key: found()[key]
            for key in (
                "schema_version",
                "run_id",
                "actor_id",
                "idempotency_key_sha256",
                "request_id",
            )
        }
        value["result"] = result
        assert adapter.validate_python(value).result == result
        with pytest.raises(ValidationError):
            adapter.validate_python({**value, "checkout_id": "forbidden"})
    for change in ({"result": "allow"}, {"schema_version": "unknown"}, {"trusted": True}):
        with pytest.raises(ValidationError):
            adapter.validate_python({**found(), **change})
    with pytest.raises(ValidationError):
        CreationLookupError.model_validate(
            {
                "schema_version": LOOKUP_SCHEMA,
                "result": "error",
                "code": "not_found",
                "request_id": "request_test",
            }
        )


@pytest.mark.parametrize(
    "change", ["id", "protocol", "schema", "digest", "fingerprint", "credential"]
)
def test_found_rejects_inconsistent_or_unsafe_evidence(change):
    value = deepcopy(found())
    if change == "digest":
        value["original_response_sha256"] = "0" * 64
    elif change == "fingerprint":
        value["acp_create_fingerprint"] = "bad"
    else:
        response = value["original_response"]
        if change == "id":
            response["id"] = "foreign"
        elif change == "protocol":
            response["protocol"]["version"] = "unknown"
        elif change == "schema":
            del response["currency"]
        else:
            response["bearer_token"] = "do-not-expose"
        if change != "credential":
            value["original_response_sha256"] = original_response_sha256(response)
    with pytest.raises((ValidationError, SchemaError)):
        CreationFound.model_validate(value)
