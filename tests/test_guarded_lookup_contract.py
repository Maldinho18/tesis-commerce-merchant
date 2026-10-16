import pytest
from pydantic import TypeAdapter, ValidationError

from commerce_lab.contracts.guarded_lookup import (
    LOOKUP_SCHEMA,
    GuardProofLookupInput,
    GuardProofLookupResult,
    GuardProofNotFound,
)


@pytest.mark.parametrize(
    "change",
    [
        {"run_id": "chosen"},
        {"actor_id": "chosen"},
        {"bearer": "secret"},
        {"idempotency_key": "clear-key"},
        {"checkout_id": "chosen"},
        {"scope": "chosen"},
        {"authorization": True},
        {"schema_version": "future"},
        {"idempotency_key_sha256": "A" * 64},
        {"idempotency_key_sha256": "0" * 63},
        {"idempotency_key_sha256": 123},
        {"idempotency_key_sha256": "g" * 64},
    ],
)
def test_strict_request(change):
    with pytest.raises(ValidationError):
        GuardProofLookupInput.model_validate(
            {"schema_version": LOOKUP_SCHEMA, "idempotency_key_sha256": "0" * 64, **change}
        )


@pytest.mark.parametrize("field", ["replay_allowed", "continuation_allowed", "completion_allowed"])
def test_no_permission_fields(field):
    with pytest.raises(ValidationError):
        GuardProofNotFound.model_validate(
            {
                "run_id": "run",
                "actor_id": "actor",
                "request_id": "request",
                "idempotency_key_sha256": "0" * 64,
                field: True,
            }
        )


def test_discriminator_rejects_unknown_result():
    with pytest.raises(ValidationError):
        TypeAdapter(GuardProofLookupResult).validate_python({"result": "allow"})
