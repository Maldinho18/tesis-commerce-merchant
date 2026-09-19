from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema import ValidationError as SchemaValidationError
from referencing import Registry, Resource

from commerce_lab.api import app
from commerce_lab.payment_sandbox import (
    config_schema,
    instrument_schema,
    payment_handler,
)


def test_payment_handler_matches_frozen_acp_definition() -> None:
    import json
    from pathlib import Path

    bundle = json.loads(
        (
            Path(__file__).parents[1]
            / "vendor"
            / "acp"
            / "2026-04-17"
            / "schema.agentic_checkout.json"
        ).read_text(encoding="utf-8")
    )
    registry = Registry().with_resource(str(bundle["$id"]), Resource.from_contents(bundle))
    validator = Draft202012Validator(
        {"$ref": f"{bundle['$id']}#/$defs/PaymentHandler"},
        registry=registry,
        format_checker=FormatChecker(),
    )
    handler = payment_handler()
    validator.validate(handler)
    assert handler["psp"] == "tesis_sandbox"
    assert handler["requires_delegate_payment"] is False
    assert handler["requires_pci_compliance"] is False


def test_payment_schemas_accept_only_sandbox_configuration_and_tokens() -> None:
    config_validator = Draft202012Validator(config_schema())
    config_validator.validate({"environment": "sandbox"})

    instrument_validator = Draft202012Validator(instrument_schema())
    for outcome in ("success", "declined", "error"):
        instrument_validator.validate(
            {
                "type": "sandbox_token",
                "credential": {
                    "type": "spt",
                    "token": f"spt_test_{outcome}_demo",
                },
            }
        )
    for invalid in (
        "spt_test_unknown_demo",
        "arbitrary-token",
    ):
        with_schema_error = {
            "type": "sandbox_token",
            "credential": {"type": "spt", "token": invalid},
        }
        try:
            instrument_validator.validate(with_schema_error)
        except SchemaValidationError:
            pass
        else:
            raise AssertionError("invalid sandbox token was accepted")

    for invalid in (
        {
            "type": "sandbox_token",
            "credential": {"type": "other", "token": "spt_test_success_demo"},
        },
        {
            "type": "sandbox_token",
            "credential": {
                "type": "spt",
                "token": "spt_test_success_demo",
                "card_number": "4111111111111111",
            },
        },
    ):
        try:
            instrument_validator.validate(invalid)
        except SchemaValidationError:
            pass
        else:
            raise AssertionError("invalid instrument was accepted")


def test_payment_handler_documents_are_public_and_deterministic() -> None:
    client = TestClient(app)
    for path in (
        "/payment-handlers/tesis-sandbox/spec",
        "/payment-handlers/tesis-sandbox/config-schema",
        "/payment-handlers/tesis-sandbox/instrument-schema",
    ):
        first = client.get(path)
        second = client.get(path)
        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()
        assert first.headers["cache-control"] == "public, max-age=3600"
