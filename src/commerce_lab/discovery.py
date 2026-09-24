"""Public, deterministic ACP discovery document for implemented merchant capabilities."""

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from commerce_lab.contracts import ACP_VERSION
from commerce_lab.settings import get_settings

_BUNDLE: dict[str, Any] = json.loads(
    (
        Path(__file__).resolve().parents[2] / "vendor/acp/2026-04-17/schema.agentic_checkout.json"
    ).read_text(encoding="utf-8")
)
_REGISTRY = Registry().with_resource(str(_BUNDLE["$id"]), Resource.from_contents(_BUNDLE))
_VALIDATOR = Draft202012Validator(
    {"$ref": f"{_BUNDLE['$id']}#/$defs/DiscoveryResponse"},
    registry=_REGISTRY,
    format_checker=FormatChecker(),
)


def discovery_document() -> dict[str, object]:
    document: dict[str, object] = {
        "protocol": {
            "name": "acp",
            "version": ACP_VERSION,
            "supported_versions": [ACP_VERSION],
        },
        "api_base_url": get_settings().acp_api_base_url,
        "transports": ["rest"],
        "capabilities": {
            "services": ["checkout"],
            "supported_currencies": ["cop"],
            "supported_locales": ["es-CO"],
        },
    }
    _VALIDATOR.validate(document)
    return document
