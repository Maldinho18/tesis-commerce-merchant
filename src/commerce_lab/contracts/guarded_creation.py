"""Private conditional creation v1, independent from frozen ACP and lookup schemas."""

import hashlib
from typing import Literal

from pydantic import ConfigDict, model_validator

from commerce_lab.acp import ACPCheckoutCreateRequest, creation_fingerprint
from commerce_lab.contracts.commerce import Offer
from commerce_lab.contracts.creation_lookup import (
    CreationFound,
    HexDigest,
    canonical_original_response,
)
from commerce_lab.contracts.primitives import Identifier, Revision, StrictModel, parse_timestamp

SCHEMA = "merchant-guarded-acp-create/1"
SNAPSHOT_PROFILE = "merchant-offer-snapshot/1"
RejectionCode = Literal[
    "guard_history_unavailable",
    "offer_not_found",
    "offer_revision_mismatch",
    "offer_snapshot_mismatch",
    "product_inactive",
    "out_of_stock",
    "offer_expired",
    "offer_invalid",
]


def offer_snapshot_sha256(offer: Offer) -> str:
    """Full validated Offer including defaults; key order ignored, arrays preserved."""
    normalized = Offer.model_validate(offer.model_dump(mode="json"))
    return hashlib.sha256(
        b"merchant-offer-snapshot/v1\0"
        + canonical_original_response(normalized.model_dump(mode="json"))
    ).hexdigest()


class GuardedInput(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    schema_version: Literal["merchant-guarded-acp-create/1"]
    acp_request: ACPCheckoutCreateRequest
    offer_id: Identifier
    expected_offer_revision: Revision
    offer_snapshot_profile: Literal["merchant-offer-snapshot/1"]
    offer_snapshot_sha256: HexDigest

    @model_validator(mode="after")
    def same_variant(self):
        if self.acp_request.line_items[0].id != self.offer_id:
            raise ValueError("Offer and ACP variant disagree")
        return self

    def acp_fingerprint(self) -> str:
        return creation_fingerprint(self.acp_request.model_dump(mode="json", exclude_unset=True))

    def fingerprint(self) -> str:
        value = self.model_dump(mode="json", exclude={"acp_request"})
        value["acp_create_fingerprint"] = self.acp_fingerprint()
        return hashlib.sha256(
            b"merchant-guarded-acp-attempt/v1\0" + canonical_original_response(value)
        ).hexdigest()


class GuardedProof(StrictModel):
    schema_version: Literal["merchant-guarded-acp-proof/1"] = "merchant-guarded-acp-proof/1"
    offer_id: Identifier
    accepted_offer_revision: Revision
    offer_snapshot_profile: Literal["merchant-offer-snapshot/1"]
    accepted_offer_snapshot_sha256: HexDigest
    guard_fingerprint: HexDigest
    checked_at: str
    creation: CreationFound

    @model_validator(mode="after")
    def same_creation_variant(self):
        parse_timestamp(self.checked_at)
        body = self.creation.original_response
        items = body.get("line_items", [])
        if (
            len(items) != 1
            or items[0].get("item", {}).get("id") != self.offer_id
            or items[0].get("quantity") != 1
            or body.get("currency") != "cop"
            or body.get("status") != "not_ready_for_payment"
        ):
            raise ValueError("Historical creation does not match accepted offer")
        return self

    def digest(self) -> str:
        return hashlib.sha256(
            b"merchant-guarded-acp-proof/v1\0"
            + canonical_original_response(self.model_dump(mode="json"))
        ).hexdigest()


class GuardedResult(StrictModel):
    schema_version: Literal["merchant-guarded-acp-create/1"] = SCHEMA
    result: Literal["created", "replayed"]
    request_id: Identifier
    proof: GuardedProof


class GuardedError(StrictModel):
    schema_version: Literal["merchant-guarded-acp-create/1"] = SCHEMA
    result: Literal["error"] = "error"
    code: (
        RejectionCode
        | Literal[
            "invalid_request",
            "unauthenticated",
            "invalid_api_version",
            "guard_unavailable",
            "idempotency_conflict",
            "guard_history_unavailable",
            "offer_not_found",
            "offer_revision_mismatch",
            "offer_snapshot_mismatch",
            "product_inactive",
            "out_of_stock",
            "offer_expired",
            "offer_invalid",
        ]
    )
    request_id: Identifier
    historical: bool = False


class GuardedRejectionRecord(StrictModel):
    schema_version: Literal["merchant-guarded-acp-rejection/1"] = "merchant-guarded-acp-rejection/1"
    run_id: Identifier
    actor_id: Identifier
    idempotency_sha256: HexDigest
    guard_fingerprint: HexDigest
    code: RejectionCode

    def digest(self) -> str:
        return hashlib.sha256(
            b"merchant-guarded-acp-rejection/v1\0"
            + canonical_original_response(self.model_dump(mode="json"))
        ).hexdigest()
