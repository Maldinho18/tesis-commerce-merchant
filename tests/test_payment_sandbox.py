import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema import ValidationError as SchemaValidationError
from referencing import Registry, Resource

from commerce_lab.api import app
from commerce_lab.payment_sandbox import (
    config_schema,
    instrument_schema,
    payment_handler,
    validate_instrument,
)

TOKEN = "vt_" + "a" * 64


def test_payment_handler_matches_frozen_acp_definition() -> None:
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
    assert handler["requires_delegate_payment"] is True
    assert handler["requires_pci_compliance"] is False


def test_payment_schemas_accept_only_delegated_tokens() -> None:
    Draft202012Validator(config_schema()).validate({"environment": "sandbox"})
    instrument = {
        "type": "sandbox_token",
        "credential": {"type": "vault_token", "token": TOKEN},
    }
    Draft202012Validator(instrument_schema()).validate(instrument)
    validate_instrument(instrument)
    for invalid in (
        {"type": "sandbox_token", "credential": {"type": "vault_token", "token": "fake"}},
        {"type": "sandbox_token", "credential": {"type": "spt", "token": TOKEN}},
        {**instrument, "card_number": "4111111111111111"},
    ):
        with pytest.raises(SchemaValidationError):
            validate_instrument(invalid)


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
