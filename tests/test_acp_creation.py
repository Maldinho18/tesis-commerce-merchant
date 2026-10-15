import pytest
from pydantic import ValidationError

from commerce_lab.acp import ACPCheckoutCreateRequest, creation_fingerprint


def test_fingerprint_preserves_content_and_ignores_object_key_order() -> None:
    first = {"line_items": [{"id": "variant-1"}], "currency": "cop", "capabilities": {}}
    second = dict(reversed(list(first.items())))
    assert creation_fingerprint(first) == creation_fingerprint(second)
    assert creation_fingerprint(first) != creation_fingerprint({**first, "currency": "usd"})
    assert creation_fingerprint(first) != creation_fingerprint(
        {
            **first,
            "line_items": [{"id": "variant-2"}],
        }
    )


def test_explicit_and_omitted_fields_are_different_original_requests() -> None:
    implicit = ACPCheckoutCreateRequest.model_validate(
        {
            "line_items": [{"id": "variant-1"}],
            "currency": "cop",
            "capabilities": {},
        }
    )
    explicit = ACPCheckoutCreateRequest.model_validate(
        {
            "line_items": [{"id": "variant-1"}],
            "currency": "cop",
            "capabilities": {"payment": {"handlers": []}},
        }
    )
    assert implicit.model_dump() == explicit.model_dump()
    assert creation_fingerprint(implicit.model_dump(mode="json", exclude_unset=True)) != (
        creation_fingerprint(explicit.model_dump(mode="json", exclude_unset=True))
    )


@pytest.mark.parametrize("extra", ["price", "actor_id", "run_id", "approved"])
def test_unknown_create_fields_are_still_rejected(extra: str) -> None:
    with pytest.raises(ValidationError):
        ACPCheckoutCreateRequest.model_validate(
            {
                "line_items": [{"id": "variant-1"}],
                "currency": "cop",
                "capabilities": {},
                extra: "untrusted",
            }
        )
