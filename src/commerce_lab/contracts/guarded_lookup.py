"""Read-only D17 history v1; no permissions or changes to published schemas."""

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from commerce_lab.contracts.creation_lookup import HexDigest
from commerce_lab.contracts.guarded_creation import GuardedProof, GuardedRejectionRecord
from commerce_lab.contracts.primitives import Identifier, StrictModel

LOOKUP_SCHEMA = "merchant-guarded-creation-lookup/1"
MAX_RESPONSE_BYTES = 262144


class GuardProofLookupInput(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    schema_version: Literal["merchant-guarded-creation-lookup/1"]
    idempotency_key_sha256: HexDigest


class _ScopedHistory(StrictModel):
    schema_version: Literal["merchant-guarded-creation-lookup/1"] = LOOKUP_SCHEMA
    run_id: Identifier
    actor_id: Identifier
    idempotency_key_sha256: HexDigest
    request_id: Identifier


class GuardProofFound(_ScopedHistory):
    result: Literal["found"] = "found"
    proof: GuardedProof
    proof_sha256: HexDigest

    @model_validator(mode="after")
    def verified(self):
        creation = self.proof.creation
        if (
            self.proof.digest() != self.proof_sha256
            or creation.run_id != self.run_id
            or creation.actor_id != self.actor_id
            or creation.idempotency_key_sha256 != self.idempotency_key_sha256
        ):
            raise ValueError("Historical proof binding mismatch")
        return self


class GuardProofRejected(_ScopedHistory):
    result: Literal["rejected"] = "rejected"
    rejection: GuardedRejectionRecord
    rejection_sha256: HexDigest

    @model_validator(mode="after")
    def verified(self):
        if (
            self.rejection.digest() != self.rejection_sha256
            or self.rejection.run_id != self.run_id
            or self.rejection.actor_id != self.actor_id
            or self.rejection.idempotency_sha256 != self.idempotency_key_sha256
        ):
            raise ValueError("Historical rejection binding mismatch")
        return self


class GuardProofNotFound(_ScopedHistory):
    result: Literal["not_found"] = "not_found"


class GuardProofUnrecoverable(_ScopedHistory):
    result: Literal["unrecoverable"] = "unrecoverable"


class GuardProofLookupError(StrictModel):
    schema_version: Literal["merchant-guarded-creation-lookup/1"] = LOOKUP_SCHEMA
    result: Literal["error"] = "error"
    code: Literal[
        "invalid_request",
        "unauthenticated",
        "invalid_api_version",
        "history_invalid",
        "lookup_unavailable",
        "response_too_large",
    ]
    request_id: Identifier


GuardProofLookupResult = Annotated[
    GuardProofFound | GuardProofRejected | GuardProofNotFound | GuardProofUnrecoverable,
    Field(discriminator="result"),
]
