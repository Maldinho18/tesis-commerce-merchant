import json
import os
import sys
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from commerce_lab.api import app
from commerce_lab.context import issue_lab_session
from commerce_lab.db import database_url, migrate, seed
from commerce_lab.webhook_delivery import WebhookDispatcher

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_INTEGRATION") != "1",
    reason="requires the local synthetic PostgreSQL service",
)


@pytest.fixture(autouse=True)
def synthetic_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("commerce_lab.checkout.confirm_payment", lambda **_: "approved")


def _ready_checkout(actor: str) -> tuple[TestClient, dict[str, str], str, str, str]:
    episode = seed(actor_id=actor, variant="B0")
    run_id = str(episode["run_id"])
    token = issue_lab_session(run_id, actor)
    headers = {
        "Authorization": f"Bearer {token}",
        "API-Version": "2026-04-17",
    }
    client = TestClient(app)
    created = client.post(
        "/checkout_sessions",
        headers={**headers, "Idempotency-Key": "create"},
        json={"line_items": [{"id": "ALT-01"}], "currency": "usd", "capabilities": {}},
    )
    checkout_id = str(created.json()["id"])
    updated = client.post(
        f"/checkout_sessions/{checkout_id}",
        headers={**headers, "Idempotency-Key": "ready"},
        json={
            "buyer": {"email": "buyer.webhook@example.test"},
            "fulfillment_details": {
                "name": "Webhook Buyer",
                "email": "buyer.webhook@example.test",
                "phone_number": "+573000000001",
                "address": {
                    "name": "Webhook Buyer",
                    "line_one": "Calle 100",
                    "city": "Bogota",
                    "state": "DC",
                    "country": "CO",
                    "postal_code": "110111",
                },
            },
            "selected_fulfillment_options": [
                {
                    "type": "shipping",
                    "option_id": f"ship_{checkout_id}",
                    "item_ids": [f"li_{checkout_id}"],
                }
            ],
        },
    )
    assert created.status_code == 201
    assert updated.status_code == 200
    return client, headers, checkout_id, run_id, token


def _complete(actor: str) -> tuple[str, str]:
    client, headers, checkout_id, run_id, _ = _ready_checkout(actor)
    response = client.post(
        f"/checkout_sessions/{checkout_id}/complete",
        headers={**headers, "Idempotency-Key": "complete"},
        json={
            "payment_data": {
                "handler_id": "tesis_sandbox",
                "instrument": {
                    "type": "sandbox_token",
                    "credential": {"type": "vault_token", "token": "vt_" + "a" * 64},
                },
            }
        },
    )
    assert response.status_code == 200
    order_id = str(response.json()["order"]["id"])
    with psycopg.connect(database_url()) as connection, connection.transaction():
        connection.execute(
            """UPDATE webhook_deliveries
               SET delivered_at = now(), updated_at = now()
               WHERE delivered_at IS NULL AND order_id <> %s""",
            (order_id,),
        )
    return run_id, order_id


def _settings(url: str | None = "http://127.0.0.1:9999") -> SimpleNamespace:
    return SimpleNamespace(webhook_receiver_url=url, merchant_webhook_secret="secret")


def _force_due(delivery_id: str) -> None:
    with psycopg.connect(database_url()) as connection, connection.transaction():
        connection.execute(
            "UPDATE webhook_deliveries SET next_attempt_at = now() WHERE delivery_id = %s",
            (delivery_id,),
        )


def _delivery(delivery_id: str) -> tuple[int, str | None, object]:
    with psycopg.connect(database_url()) as connection:
        row = connection.execute(
            """SELECT attempt_count, last_error, delivered_at
               FROM webhook_deliveries WHERE delivery_id = %s""",
            (delivery_id,),
        ).fetchone()
    assert row is not None
    return row


def test_order_update_cli_serializes_model_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    migrate()
    run_id, order_id = _complete("webhook-cli")
    argv = ["db", "order-update", run_id, "webhook-cli", order_id]
    monkeypatch.setattr(sys, "argv", argv)
    from commerce_lab.db import __main__ as db_main

    db_main.main()
    first = json.loads(capsys.readouterr().out)
    db_main.main()
    second = json.loads(capsys.readouterr().out)
    assert first["ok"] is True
    assert first["data"]["status"] == "processing"
    assert second["data"]["status"] == "processing"
    with psycopg.connect(database_url()) as connection:
        assert connection.execute(
            """SELECT count(*) FROM webhook_deliveries
               WHERE order_id = %s AND event_type = 'order_update'""",
            (order_id,),
        ).fetchone() == (1,)


def test_dispatch_missing_configuration_does_not_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrate()
    _, order_id = _complete("webhook-no-config")
    monkeypatch.setattr("commerce_lab.webhook_delivery.get_settings", lambda: _settings(None))
    assert WebhookDispatcher().dispatch_one() is None
    with psycopg.connect(database_url()) as connection:
        assert connection.execute(
            "SELECT count(*) FROM webhook_delivery_attempts WHERE delivery_id IN "
            "(SELECT delivery_id FROM webhook_deliveries WHERE order_id = %s)",
            (order_id,),
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT attempt_count FROM webhook_deliveries WHERE order_id = %s",
            (order_id,),
        ).fetchone() == (0,)


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(429), "retry"),
        (httpx.Response(500), "retry"),
        (httpx.Response(400), "terminal"),
        (httpx.Response(401), "terminal"),
        (httpx.Response(302), "terminal"),
        (httpx.Response(200, json={"received": False}), "terminal"),
        (httpx.Response(200, json={"received": True, "request_id": "wrong"}), "terminal"),
        (httpx.Response(200, json={"received": True}), "delivered"),
    ],
)
def test_dispatch_persists_http_outcomes(
    monkeypatch: pytest.MonkeyPatch, response: httpx.Response, expected: str
) -> None:
    migrate()
    _, order_id = _complete(f"webhook-outcome-{response.status_code}-{expected}")
    monkeypatch.setattr("commerce_lab.webhook_delivery.get_settings", lambda: _settings())
    monkeypatch.setattr("commerce_lab.webhook_delivery.httpx.post", lambda *a, **k: response)
    result = WebhookDispatcher().dispatch_one()
    assert result is not None
    assert result["outcome"] == expected
    with psycopg.connect(database_url()) as connection:
        assert connection.execute(
            """SELECT a.outcome FROM webhook_delivery_attempts a
               JOIN webhook_deliveries d USING (delivery_id)
               WHERE d.order_id = %s""",
            (order_id,),
        ).fetchone() == (expected,)


@pytest.mark.parametrize(
    "error",
    [httpx.ReadTimeout("safe"), httpx.ConnectError("safe")],
)
def test_dispatch_transport_errors_retry(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    migrate()
    _, order_id = _complete(f"webhook-transport-{type(error).__name__}")
    monkeypatch.setattr("commerce_lab.webhook_delivery.get_settings", lambda: _settings())
    monkeypatch.setattr(
        "commerce_lab.webhook_delivery.httpx.post",
        lambda *a, **k: (_ for _ in ()).throw(error),
    )
    result = WebhookDispatcher().dispatch_one()
    assert result is not None
    assert result["outcome"] == "retry"
    with psycopg.connect(database_url()) as connection:
        row = connection.execute(
            """SELECT d.attempt_count, a.outcome, d.next_attempt_at
               FROM webhook_deliveries d JOIN webhook_delivery_attempts a USING (delivery_id)
               WHERE d.order_id = %s""",
            (order_id,),
        ).fetchone()
    assert row is not None
    assert row[0] == 1
    assert row[1] == "retry"
    assert row[2] is not None


def test_dispatch_retries_use_backoff_then_exhaust(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrate()
    _, order_id = _complete("webhook-backoff")
    monkeypatch.setattr("commerce_lab.webhook_delivery.get_settings", lambda: _settings())
    monkeypatch.setattr(
        "commerce_lab.webhook_delivery.httpx.post",
        lambda *a, **k: httpx.Response(500),
    )
    dispatcher = WebhookDispatcher()
    expected_delays = [1, 2, 4, 8]
    for expected_delay in expected_delays:
        before = datetime.now(UTC)
        result = dispatcher.dispatch_one()
        assert result is not None
        assert result["outcome"] == "retry"
        with psycopg.connect(database_url()) as connection:
            row = connection.execute(
                """SELECT d.delivery_id, d.attempt_count, d.next_attempt_at
                   FROM webhook_deliveries d WHERE d.order_id = %s""",
                (order_id,),
            ).fetchone()
        assert row is not None
        assert row[1] == expected_delays.index(expected_delay) + 1
        assert expected_delay - 1 <= (row[2] - before).total_seconds() <= expected_delay + 2
        _force_due(row[0])
    result = dispatcher.dispatch_one()
    assert result is not None
    assert result["outcome"] == "exhausted"
    assert dispatcher.dispatch_one() is None
    with psycopg.connect(database_url()) as connection:
        assert connection.execute(
            """SELECT d.attempt_count, a.outcome
               FROM webhook_deliveries d JOIN webhook_delivery_attempts a USING (delivery_id)
               WHERE d.order_id = %s ORDER BY a.attempt_no DESC LIMIT 1""",
            (order_id,),
        ).fetchone() == (5, "exhausted")


def test_dispatch_payload_hash_mismatch_is_terminal_without_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrate()
    _, order_id = _complete("webhook-hash")
    monkeypatch.setattr("commerce_lab.webhook_delivery.get_settings", lambda: _settings())
    calls = 0

    def post(*args: object, **kwargs: object) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"received": True})

    monkeypatch.setattr("commerce_lab.webhook_delivery.httpx.post", post)
    with psycopg.connect(database_url()) as connection, connection.transaction():
        connection.execute(
            "UPDATE webhook_deliveries "
            "SET payload = jsonb_set(payload, '{type}', '\"order_update\"') "
            "WHERE order_id = %s",
            (order_id,),
        )
        delivery_row = connection.execute(
            "SELECT delivery_id FROM webhook_deliveries WHERE order_id = %s",
            (order_id,),
        ).fetchone()
    assert delivery_row is not None
    delivery_id = delivery_row[0]
    result = WebhookDispatcher().dispatch_one()
    assert result is not None
    assert result["outcome"] == "terminal"
    assert calls == 0
    assert _delivery(delivery_id)[1] == "PAYLOAD_HASH_MISMATCH"


def test_dispatch_retry_keeps_request_id_and_raw_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrate()
    _, order_id = _complete("webhook-stable-request")
    monkeypatch.setattr("commerce_lab.webhook_delivery.get_settings", lambda: _settings())
    sent: list[tuple[str, bytes]] = []
    monkeypatch.setattr(
        "commerce_lab.webhook_delivery.httpx.post",
        lambda url, **kwargs: (
            sent.append((kwargs["headers"]["Request-Id"], kwargs["content"])) or httpx.Response(500)
        ),
    )
    dispatcher = WebhookDispatcher()
    first = dispatcher.dispatch_one()
    with psycopg.connect(database_url()) as connection:
        delivery_row = connection.execute(
            "SELECT delivery_id FROM webhook_deliveries WHERE order_id = %s",
            (order_id,),
        ).fetchone()
    assert delivery_row is not None
    delivery_id = delivery_row[0]
    _force_due(delivery_id)
    second = dispatcher.dispatch_one()
    assert first is not None
    assert second is not None
    assert first["outcome"] == second["outcome"] == "retry"
    assert sent[0][0] == sent[1][0] == delivery_id
    assert sent[0][1] == sent[1][1]


def test_webhook_attempt_metadata_excludes_sensitive_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrate()
    _, order_id = _complete("webhook-privacy")
    monkeypatch.setattr("commerce_lab.webhook_delivery.get_settings", lambda: _settings())
    monkeypatch.setattr(
        "commerce_lab.webhook_delivery.httpx.post",
        lambda *a, **k: httpx.Response(500),
    )
    WebhookDispatcher().dispatch_one()
    with psycopg.connect(database_url()) as connection:
        rows = connection.execute(
            """SELECT d.payload::text, a::text
               FROM webhook_deliveries d JOIN webhook_delivery_attempts a USING (delivery_id)
               WHERE d.order_id = %s""",
            (order_id,),
        ).fetchall()
    serialized = json.dumps(rows)
    for value in (
        "vt_",
        "Bearer ",
        "Merchant-Signature",
        "secret",
        "buyer.webhook@",
        "+573",
        "Calle 100",
    ):
        assert value not in serialized


def test_completion_rolls_back_when_outbox_insert_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrate()
    _client, headers, checkout_id, run_id, _ = _ready_checkout("webhook-rollback")
    with psycopg.connect(database_url()) as connection:
        before = connection.execute(
            "SELECT snapshot ->> 'available_quantity' FROM catalog_offers "
            "WHERE run_id = %s AND offer_id = 'ALT-01'",
            (run_id,),
        ).fetchone()

    def fail_outbox(*args: object, **kwargs: object) -> str:
        raise RuntimeError("outbox failure")

    monkeypatch.setattr("commerce_lab.checkout.enqueue_order_event", fail_outbox)
    failed_client = TestClient(app, raise_server_exceptions=False)
    response = failed_client.post(
        f"/checkout_sessions/{checkout_id}/complete",
        headers={**headers, "Idempotency-Key": "rollback"},
        json={
            "payment_data": {
                "handler_id": "tesis_sandbox",
                "instrument": {
                    "type": "sandbox_token",
                    "credential": {"type": "vault_token", "token": "vt_" + "a" * 64},
                },
            }
        },
    )
    assert response.status_code == 500
    with psycopg.connect(database_url()) as connection:
        after = connection.execute(
            "SELECT snapshot ->> 'available_quantity' FROM catalog_offers "
            "WHERE run_id = %s AND offer_id = 'ALT-01'",
            (run_id,),
        ).fetchone()
        state = connection.execute(
            "SELECT status FROM checkout_sessions WHERE checkout_id = %s",
            (checkout_id,),
        ).fetchone()
        counts = connection.execute(
            """SELECT
                 (SELECT count(*) FROM orders WHERE checkout_id = %s),
                 (SELECT count(*) FROM checkout_completion_attempts WHERE checkout_id = %s),
                 (SELECT count(*) FROM webhook_deliveries WHERE run_id = %s)""",
            (checkout_id, checkout_id, run_id),
        ).fetchone()
    assert after == before
    assert state == ("ready_for_payment",)
    assert counts == (0, 0, 0)
