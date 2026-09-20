import hashlib
import hmac
import json
from pathlib import Path

import httpx
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from commerce_lab.contracts import OrderRecord
from commerce_lab.order_projection import order_to_acp, webhook_order_event
from commerce_lab.webhook_delivery import WebhookDispatcher, sign_payload


def test_sign_payload_uses_exact_raw_body_vector() -> None:
    secret = "test-secret"
    timestamp = 1_709_123_456
    raw_body = b'{"data":{"type":"order"},"type":"order_create"}'
    expected = hmac.new(
        secret.encode(),
        str(timestamp).encode() + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()

    assert sign_payload(secret, timestamp, raw_body) == f"t={timestamp},v1={expected}"


def test_webhook_projection_is_full_order_with_exact_event_shape() -> None:
    order = OrderRecord(
        id="ord_001",
        checkout_session_id="cs_001",
        order_number="TST-0001",
        status="confirmed",
        offer_id="ALT-01",
        product_id="prod-alt-01",
        title="Alt",
        quantity=1,
        currency="usd",
        unit_price=60_000,
        subtotal=60_000,
        shipping_total=2_000,
        total=62_000,
        fulfillment_option_id="ship_cs_001",
        created_at="2026-09-19T00:00:00Z",
        permalink_url="http://127.0.0.1:4120/orders/ord_001",
    )
    event = webhook_order_event("order_create", order)

    assert set(event) == {"type", "data"}
    assert event["type"] == "order_create"
    assert event["data"]["type"] == "order"
    assert event["data"]["id"] == order.id
    assert event["data"]["checkout_session_id"] == order.checkout_session_id
    assert event["data"]["line_items"][0]["product_id"] == order.product_id
    assert "event_id" not in event
    assert "run_id" not in event
    assert "actor_id" not in event
    assert order_to_acp(order) == {
        key: value for key, value in event["data"].items() if key != "type"
    }


def test_webhook_projection_validates_against_frozen_order_schema() -> None:
    root = Path(__file__).resolve().parents[1]
    bundle = json.loads((root / "vendor/acp/2026-04-17/schema.agentic_checkout.json").read_text())
    registry = Registry().with_resource(str(bundle["$id"]), Resource.from_contents(bundle))
    validator = Draft202012Validator(
        {"$ref": f"{bundle['$id']}#/$defs/Order"},
        registry=registry,
        format_checker=FormatChecker(),
    )
    order = OrderRecord(
        id="ord_001",
        checkout_session_id="cs_001",
        order_number="TST-0001",
        status="confirmed",
        offer_id="ALT-01",
        product_id="prod-alt-01",
        title="Alt",
        quantity=1,
        currency="usd",
        unit_price=60_000,
        subtotal=60_000,
        shipping_total=2_000,
        total=62_000,
        fulfillment_option_id="ship_cs_001",
        created_at="2026-09-19T00:00:00Z",
        permalink_url="http://127.0.0.1:4120/orders/ord_001",
    )
    data = webhook_order_event("order_update", order)["data"]
    validator.validate(data)
    assert set(webhook_order_event("order_update", order)) == {"type", "data"}
    assert data["type"] == "order"


def test_dispatcher_send_preserves_raw_body_and_request_id(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        captured["url"] = url
        captured.update(kwargs)
        return httpx.Response(200, json={"received": True, "request_id": "whd_001"})

    monkeypatch.setattr("commerce_lab.webhook_delivery.httpx.post", fake_post)
    outcome = WebhookDispatcher(timeout_seconds=2)._send(
        "http://127.0.0.1:4120",
        "secret",
        "whd_001",
        b'{"raw":true}',
    )

    assert outcome == ("delivered", 200, None)
    assert captured["url"] == "http://127.0.0.1:4120/agentic_checkout/webhooks/order_events"
    assert captured["content"] == b'{"raw":true}'
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["Request-Id"] == "whd_001"
    assert headers["Content-Type"] == "application/json"
    assert headers["Merchant-Signature"].startswith("t=")
    assert ",v1=" in headers["Merchant-Signature"]
    assert len(headers["Merchant-Signature"].split(",v1=", 1)[1]) == 64


def test_dispatcher_classifies_retry_and_terminal_responses(monkeypatch) -> None:
    responses = iter(
        [
            httpx.Response(429, json={"error": "busy"}),
            httpx.Response(500, json={"error": "down"}),
            httpx.Response(400, json={"error": "bad"}),
            httpx.Response(200, json={"received": False}),
        ]
    )
    monkeypatch.setattr(
        "commerce_lab.webhook_delivery.httpx.post",
        lambda *args, **kwargs: next(responses),
    )
    dispatcher = WebhookDispatcher()

    assert dispatcher._send("http://127.0.0.1:4120", "secret", "whd_001", b"{}")[0] == "retry"
    assert dispatcher._send("http://127.0.0.1:4120", "secret", "whd_001", b"{}")[0] == "retry"
    assert dispatcher._send("http://127.0.0.1:4120", "secret", "whd_001", b"{}")[0] == "terminal"
    assert dispatcher._send("http://127.0.0.1:4120", "secret", "whd_001", b"{}")[0] == "terminal"
