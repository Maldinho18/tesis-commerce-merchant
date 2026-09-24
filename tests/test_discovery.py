import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError
from referencing import Registry, Resource

from commerce_lab.api import app
from commerce_lab.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = json.loads(
    (ROOT / "vendor/acp/2026-04-17/schema.agentic_checkout.json").read_text(encoding="utf-8")
)
REGISTRY = Registry().with_resource(str(BUNDLE["$id"]), Resource.from_contents(BUNDLE))
DISCOVERY_VALIDATOR = Draft202012Validator(
    {"$ref": f"{BUNDLE['$id']}#/$defs/DiscoveryResponse"},
    registry=REGISTRY,
    format_checker=FormatChecker(),
)


def test_public_discovery_matches_frozen_acp_schema_and_only_real_capabilities() -> None:
    response = TestClient(app).get("/.well-known/acp.json")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.headers["cache-control"] == "public, max-age=3600"
    document = response.json()
    DISCOVERY_VALIDATOR.validate(document)
    assert document == {
        "protocol": {
            "name": "acp",
            "version": "2026-04-17",
            "supported_versions": ["2026-04-17"],
        },
        "api_base_url": "http://127.0.0.1:4120",
        "transports": ["rest"],
        "capabilities": {
            "services": ["checkout"],
            "supported_currencies": ["cop"],
            "supported_locales": ["es-CO"],
        },
    }
    assert not {"orders", "delegate_payment", "carts", "payment", "webhooks"} & set(
        document["capabilities"]["services"]
    )
    assert "token" not in response.text.lower()
    assert "tesis_dev" not in response.text


def test_external_discovery_base_url_requires_https() -> None:
    assert Settings(acp_api_base_url="https://merchant.example.test/").acp_api_base_url == (
        "https://merchant.example.test"
    )
    with pytest.raises(ValidationError):
        Settings(acp_api_base_url="http://merchant.example.test")
