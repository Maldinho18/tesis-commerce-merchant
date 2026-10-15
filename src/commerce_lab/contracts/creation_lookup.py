"""Private lookup v1. Digests identify JSON values, never original wire bytes."""

import hashlib
import json
from typing import Annotated, Any, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from .primitives import ACP_VERSION, MAX_SAFE_INTEGER, Identifier, StrictModel

LOOKUP_SCHEMA = "merchant-acp-creation-lookup/1"
RESPONSE_PROFILE = "merchant-acp-original-response/1"
HexDigest = Annotated[
    str, StringConstraints(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
]
_SENSITIVE_KEYS = {
    "authorization",
    "bearer",
    "token",
    "bearer_token",
    "access_token",
    "refresh_token",
    "session_token",
    "idempotency_key",
    "credentials",
    "credential",
    "payment_data",
    "checkout_jwt",
}


def canonical_original_response(value: object) -> bytes:
    """Sorted Unicode keys; UTF-8; integer-only JSON; arrays retain order."""

    def check(item: object) -> None:
        if item is None or isinstance(item, (str, bool)):
            return
        if type(item) is int and abs(item) <= MAX_SAFE_INTEGER:
            return
        if isinstance(item, list):
            for child in item:
                check(child)
            return
        if isinstance(item, dict) and all(isinstance(key, str) for key in item):
            if any(key.lower() in _SENSITIVE_KEYS for key in item):
                raise ValueError("Credential field in historical response")
            for child in item.values():
                check(child)
            return
        raise ValueError("Unsupported canonical JSON value")

    check(value)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def original_response_sha256(value: object) -> str:
    return hashlib.sha256(
        b"merchant-acp-original-response/v1\0" + canonical_original_response(value)
    ).hexdigest()


class CreationLookupInput(StrictModel):
    schema_version: Literal["merchant-acp-creation-lookup/1"]
    idempotency_key_sha256: HexDigest


class _ScopedResult(StrictModel):
    schema_version: Literal["merchant-acp-creation-lookup/1"]
    run_id: Identifier
    actor_id: Identifier
    idempotency_key_sha256: HexDigest
    request_id: Identifier


class CreationFound(_ScopedResult):
    result: Literal["found"]
    acp_api_version: Literal["2026-04-17"]
    acp_create_fingerprint: HexDigest
    checkout_id: Identifier
    original_response: dict[str, Any]
    original_response_profile: Literal["merchant-acp-original-response/1"]
    original_response_sha256: HexDigest

    @model_validator(mode="after")
    def verified(self) -> Self:
        # Reuse the frozen schema validator; never call ACP's response constructor.
        from commerce_lab.acp import _CHECKOUT_VALIDATOR

        _CHECKOUT_VALIDATOR.validate(self.original_response)
        if (
            self.original_response.get("id") != self.checkout_id
            or self.original_response.get("protocol", {}).get("version") != ACP_VERSION
            or original_response_sha256(self.original_response) != self.original_response_sha256
        ):
            raise ValueError("Inconsistent historical creation")
        return self


class CreationNotFound(_ScopedResult):
    result: Literal["not_found"]


class CreationUnrecoverable(_ScopedResult):
    result: Literal["unrecoverable"]


CreationLookupResult = Annotated[
    CreationFound | CreationNotFound | CreationUnrecoverable, Field(discriminator="result")
]


class CreationLookupError(StrictModel):
    schema_version: Literal["merchant-acp-creation-lookup/1"]
    result: Literal["error"]
    code: Literal["invalid_request", "unauthenticated", "invalid_api_version", "lookup_unavailable"]
    request_id: Identifier
