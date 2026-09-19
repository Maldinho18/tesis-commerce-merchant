import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from commerce_lab.settings import get_settings

_BUNDLE: dict[str, Any] = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "vendor"
        / "acp"
        / "2026-04-17"
        / "schema.agentic_checkout.json"
    ).read_text(encoding="utf-8")
)
_REGISTRY = Registry().with_resource(str(_BUNDLE["$id"]), Resource.from_contents(_BUNDLE))
_HANDLER_VALIDATOR = Draft202012Validator(
    {"$ref": f"{_BUNDLE['$id']}#/$defs/PaymentHandler"},
    registry=_REGISTRY,
    format_checker=FormatChecker(),
)

_CONFIG_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "properties": {"environment": {"const": "sandbox"}},
    "required": ["environment"],
}
_INSTRUMENT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "type": {"const": "sandbox_token"},
        "credential": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "type": {"const": "spt"},
                "token": {
                    "type": "string",
                    "pattern": r"^spt_test_(success|declined|error)_[A-Za-z0-9._-]+$",
                },
            },
            "required": ["type", "token"],
        },
    },
    "required": ["type", "credential"],
}


def _url(path: str) -> str:
    return f"{get_settings().acp_api_base_url}{path}"


def payment_handler() -> dict[str, Any]:
    handler = {
        "id": "tesis_sandbox",
        "name": "co.edu.uniandes.tesis.sandbox",
        "display_name": "Tesis Sandbox",
        "version": "2026-09-19",
        "spec": _url("/payment-handlers/tesis-sandbox/spec"),
        "requires_delegate_payment": False,
        "requires_pci_compliance": False,
        "psp": "tesis_sandbox",
        "config_schema": _url("/payment-handlers/tesis-sandbox/config-schema"),
        "instrument_schemas": [_url("/payment-handlers/tesis-sandbox/instrument-schema")],
        "config": {"environment": "sandbox"},
    }
    _HANDLER_VALIDATOR.validate(handler)
    return handler


def payment_capability_available() -> bool:
    handler = payment_handler()
    return (
        handler["id"] == "tesis_sandbox"
        and handler["psp"] == "tesis_sandbox"
        and handler["requires_delegate_payment"] is False
        and handler["requires_pci_compliance"] is False
    )


def handler_spec() -> dict[str, Any]:
    return {
        "title": "Tesis Sandbox payment handler",
        "handler": payment_handler()["name"],
        "version": payment_handler()["version"],
        "description": "Synthetic sandbox capability; no payment tokens are processed.",
    }


def config_schema() -> dict[str, Any]:
    return _CONFIG_SCHEMA


def instrument_schema() -> dict[str, Any]:
    return _INSTRUMENT_SCHEMA


def checkout_payment_capabilities() -> dict[str, Any]:
    return {"payment": {"handlers": [payment_handler()]}}
