import hashlib
from copy import deepcopy

import pytest
from pydantic import ValidationError

from commerce_lab.contracts import Offer
from commerce_lab.contracts.creation_lookup import canonical_original_response
from commerce_lab.contracts.guarded_creation import GuardedInput, offer_snapshot_sha256
from commerce_lab.fixtures import fresh_p0_offers


def body():
    offer = fresh_p0_offers()[0]
    return {
        "schema_version": "merchant-guarded-acp-create/1",
        "acp_request": {"line_items": [{"id": offer.id}], "currency": "cop", "capabilities": {}},
        "offer_id": offer.id,
        "expected_offer_revision": offer.revision,
        "offer_snapshot_profile": "merchant-offer-snapshot/1",
        "offer_snapshot_sha256": offer_snapshot_sha256(offer),
    }


@pytest.mark.parametrize(
    "field", ["run_id", "actor_id", "approved", "policy_decision", "authorization"]
)
def test_authority_fields_never_accepted(field):
    with pytest.raises(ValidationError):
        GuardedInput.model_validate({**body(), field: "untrusted"})


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": "other/1"},
        {"expected_offer_revision": True},
        {"expected_offer_revision": "1"},
        {"expected_offer_revision": 1.0},
        {"offer_id": "different"},
        {"offer_snapshot_sha256": "x" * 64},
        {"offer_snapshot_profile": "unknown/1"},
    ],
)
def test_strict_versions_identity_revision_digest(change):
    with pytest.raises(ValidationError):
        GuardedInput.model_validate({**body(), **change})


def test_full_snapshot_digest_vector_and_changed_content():
    offer = fresh_p0_offers()[0]
    normalized = offer.model_dump(mode="json")
    assert (
        offer_snapshot_sha256(offer)
        == hashlib.sha256(
            b"merchant-offer-snapshot/v1\0" + canonical_original_response(normalized)
        ).hexdigest()
    )
    assert offer_snapshot_sha256(
        Offer.model_validate(dict(reversed(list(normalized.items()))))
    ) == (offer_snapshot_sha256(offer))
    for field, value in [
        ("revision", offer.revision + 1),
        ("name", offer.name + " changed"),
        ("product_status", "inactive"),
        ("delivery_days", offer.delivery_days + 1),
    ]:
        changed = {**normalized, field: value}
        assert offer_snapshot_sha256(Offer.model_validate(changed)) != offer_snapshot_sha256(offer)


def test_guard_identity_preserves_presence_and_condition():
    value = body()
    first = GuardedInput.model_validate(value)
    changed = deepcopy(value)
    changed["acp_request"]["capabilities"] = {"payment": {"handlers": []}}
    second = GuardedInput.model_validate(changed)
    assert first.acp_request.model_dump() == second.acp_request.model_dump()
    assert first.acp_fingerprint() != second.acp_fingerprint()
    assert first.fingerprint() != second.fingerprint()
    changed = deepcopy(value)
    changed["expected_offer_revision"] += 1
    assert GuardedInput.model_validate(changed).fingerprint() != first.fingerprint()
