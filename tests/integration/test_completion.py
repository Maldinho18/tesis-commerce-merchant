import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from commerce_lab.api import app
from commerce_lab.checkout import CheckoutService
from commerce_lab.context import issue_lab_session
from commerce_lab.contracts import ExecutionContext
from commerce_lab.db import database_url, migrate, seed
from commerce_lab.fixtures import FIXTURE_EXPIRES_AT
from commerce_lab.payment_client import PaymentProviderError

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_INTEGRATION") != "1",
    reason="requires the local synthetic PostgreSQL service",
)

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = json.loads(
    (ROOT / "vendor/acp/2026-04-17/schema.agentic_checkout.json").read_text(encoding="utf-8")
)
REGISTRY = Registry().with_resource(str(BUNDLE["$id"]), Resource.from_contents(BUNDLE))
ORDER_VALIDATOR = Draft202012Validator(
    {"$ref": f"{BUNDLE['$id']}#/$defs/CheckoutSessionWithOrder"},
    registry=REGISTRY,
    format_checker=FormatChecker(),
)


@pytest.fixture(autouse=True)
def synthetic_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    def confirm_payment(*, token: str, **_: object) -> str:
        if token == "vt_" + "a" * 64:
            return "approved"
        if token == "vt_" + "b" * 64:
            return "declined"
        raise PaymentProviderError("unavailable")

    monkeypatch.setattr("commerce_lab.checkout.confirm_payment", confirm_payment)


def _client(
    actor: str, offer_id: str = "Q100348826-512GB"
) -> tuple[TestClient, dict[str, str], str, str]:
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
        json={
            "line_items": [{"id": offer_id}],
            "currency": "cop",
            "capabilities": {},
        },
    )
    assert created.status_code == 201
    checkout_id = str(created.json()["id"])
    updated = client.post(
        f"/checkout_sessions/{checkout_id}",
        headers={**headers, "Idempotency-Key": "ready"},
        json={
            "buyer": {
                "email": "buyer.complete@example.test",
                "first_name": "Buyer",
                "last_name": "Complete",
            },
            "fulfillment_details": {
                "name": "Buyer Complete",
                "email": "buyer.complete@example.test",
                "phone_number": "+573000000000",
                "address": {
                    "name": "Buyer Complete",
                    "line_one": "Calle 100 # 10-20",
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
    assert updated.status_code == 200
    assert updated.json()["status"] == "ready_for_payment"
    return client, headers, checkout_id, run_id


def _payment(outcome: str = "success") -> dict[str, object]:
    prefix = {"success": "a", "declined": "b", "error": "c"}[outcome]
    return {
        "payment_data": {
            "handler_id": "tesis_sandbox",
            "instrument": {
                "type": "sandbox_token",
                "credential": {"type": "vault_token", "token": "vt_" + prefix * 64},
            },
        }
    }


def _observation(request_id: str) -> tuple[object, ...]:
    with psycopg.connect(database_url()) as connection:
        row = connection.execute(
            """SELECT run_id::text, actor_id, operation, result, http_status, latency_ms,
                      checkout_id, order_id, error_code
               FROM request_observations WHERE request_id = %s""",
            (request_id,),
        ).fetchone()
    assert row is not None
    return row


def test_complete_success_is_atomic_idempotent_and_schema_valid() -> None:
    migrate()
    client, headers, checkout_id, run_id = _client("complete-success")
    path = f"/checkout_sessions/{checkout_id}/complete"
    first = client.post(path, headers={**headers, "Idempotency-Key": "complete"}, json=_payment())
    replay = client.post(path, headers={**headers, "Idempotency-Key": "complete"}, json=_payment())
    assert first.status_code == replay.status_code == 200
    ORDER_VALIDATOR.validate(first.json())
    assert first.json() == replay.json()
    assert replay.headers["Idempotent-Replayed"] == "true"
    order_id = first.json()["order"]["id"]
    first_observation = _observation(first.headers["Request-Id"])
    assert first_observation[:5] == (
        run_id,
        "complete-success",
        "complete",
        "success",
        200,
    )
    assert isinstance(first_observation[5], int)
    assert first_observation[5] >= 0
    assert first_observation[6:] == (checkout_id, order_id, None)
    with psycopg.connect(database_url()) as connection:
        assert connection.execute(
            "SELECT count(*) FROM webhook_deliveries WHERE order_id = %s",
            (order_id,),
        ).fetchone() == (1,)
    assert (
        client.get(f"/checkout_sessions/{checkout_id}", headers=headers).json()["status"]
        == "completed"
    )
    permalink = client.get(f"/orders/{order_id}")
    assert permalink.status_code == 200
    assert "buyer.complete@example.test" not in permalink.text
    assert "+573000000000" not in permalink.text
    assert "Calle 100" not in permalink.text
    assert "Buyer Complete" not in permalink.text
    assert "vt_" not in permalink.text

    with psycopg.connect(database_url()) as connection:
        offer = connection.execute(
            """
            SELECT revision, snapshot
            FROM catalog_offers
            WHERE run_id = %s AND offer_id = 'Q100348826-512GB'
            """,
            (run_id,),
        ).fetchone()
        deliveries = connection.execute(
            """SELECT event_type, count(*), payload ->> 'type', payload -> 'data' ->> 'type'
           FROM webhook_deliveries
           WHERE order_id = %s
           GROUP BY event_type, payload ->> 'type', payload -> 'data' ->> 'type'
           ORDER BY event_type""",
            (order_id,),
        ).fetchall()
        stored = connection.execute(
            """SELECT status, snapshot ->> 'status'
               FROM checkout_sessions WHERE checkout_id = %s""",
            (checkout_id,),
        ).fetchone()
        orders = connection.execute(
            "SELECT count(*) FROM orders WHERE order_id = %s", (order_id,)
        ).fetchone()
        completion_snapshot = connection.execute(
            """SELECT result_snapshot::text
               FROM checkout_completion_attempts
               WHERE checkout_id = %s""",
            (checkout_id,),
        ).fetchone()
    assert stored == ("completed", "completed")
    assert orders == (1,)
    assert deliveries == [("order_create", 1, "order_create", "order")]
    assert completion_snapshot is not None
    for secret in (
        "buyer.complete@example.test",
        "+573000000000",
        "Calle 100",
        "Buyer Complete",
        "vt_",
    ):
        assert secret not in completion_snapshot[0]
    assert offer is not None
    assert offer[0] == 2
    serialized = json.dumps(offer[1])
    assert "vt_" not in serialized
    rerun = migrate()
    assert rerun["applied"] == []
    assert rerun["already_applied"] == [
        "001_preparation.sql",
        "002_snapshot_constraints.sql",
        "003_execution_context.sql",
        "004_checkout_sessions.sql",
        "007_checkout_mutations.sql",
        "008_checkout_payment_capability.sql",
        "009_checkout_completion.sql",
        "010_webhook_delivery.sql",
        "011_request_observability.sql",
    ]


@pytest.mark.parametrize(
    ("outcome", "status", "code"),
    [
        ("declined", 422, "payment_declined"),
        ("error", 503, "PROVIDER_UNAVAILABLE"),
    ],
)
def test_complete_sandbox_outcomes_are_deterministic(outcome: str, status: int, code: str) -> None:
    migrate()
    client, headers, checkout_id, run_id = _client(f"complete-{outcome}")
    path = f"/checkout_sessions/{checkout_id}/complete"
    first = client.post(
        path, headers={**headers, "Idempotency-Key": outcome}, json=_payment(outcome)
    )
    replay = client.post(
        path, headers={**headers, "Idempotency-Key": outcome}, json=_payment(outcome)
    )
    assert first.status_code == status
    assert first.json()["detail"]["code"] == code
    assert first.headers["Request-Id"]
    assert "order" not in first.json()
    assert replay.status_code == status
    assert replay.json() == first.json()
    observation = _observation(first.headers["Request-Id"])
    assert observation[:5] == (
        run_id,
        f"complete-{outcome}",
        "complete",
        "error",
        status,
    )
    assert observation[6:8] == (checkout_id, None)
    assert observation[8] == code
    if outcome == "declined":
        assert replay.headers["Idempotent-Replayed"] == "true"
        with psycopg.connect(database_url()) as connection:
            assert connection.execute(
                "SELECT count(*) FROM webhook_deliveries WHERE run_id = %s",
                (run_id,),
            ).fetchone() == (0,)
            assert connection.execute(
                "SELECT count(*) FROM orders WHERE checkout_id = %s",
                (checkout_id,),
            ).fetchone() == (0,)
            assert connection.execute(
                "SELECT snapshot ->> 'available_quantity' FROM catalog_offers "
                "WHERE run_id = %s AND offer_id = 'Q100348826-512GB'",
                (run_id,),
            ).fetchone() == ("10",)
            stored_attempt = connection.execute(
                "SELECT result_snapshot::text FROM checkout_completion_attempts "
                "WHERE checkout_id = %s",
                (checkout_id,),
            ).fetchone()
        assert stored_attempt is not None
        assert "spt_test_" not in stored_attempt[0]
    assert (
        client.get(f"/checkout_sessions/{checkout_id}", headers=headers).json()["status"]
        == "ready_for_payment"
    )


def test_complete_in_flight_returns_retry_header_and_request_headers() -> None:
    migrate()
    client, headers, checkout_id, run_id = _client("complete-in-flight")
    with psycopg.connect(database_url(), autocommit=False) as connection, connection.transaction():
        connection.execute(
            """SELECT checkout_id FROM checkout_sessions
               WHERE run_id = %s AND checkout_id = %s FOR UPDATE""",
            (run_id, checkout_id),
        ).fetchone()
        response = client.post(
            f"/checkout_sessions/{checkout_id}/complete",
            headers={**headers, "Idempotency-Key": "in-flight"},
            json=_payment(),
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "idempotency_in_flight"
        assert response.headers["Retry-After"] == "1"
        assert response.headers["Request-Id"]
        assert response.headers["Idempotency-Key"] == "in-flight"
    observation = _observation(response.headers["Request-Id"])
    assert observation[:5] == (
        run_id,
        "complete-in-flight",
        "complete",
        "error",
        409,
    )
    assert observation[6:] == (checkout_id, None, "idempotency_in_flight")


def test_expired_checkout_completion_does_not_create_order_or_decrement_stock() -> None:
    migrate()
    client, headers, checkout_id, run_id = _client("complete-expired")
    with psycopg.connect(database_url()) as connection:
        before = connection.execute(
            """SELECT snapshot ->> 'available_quantity' FROM catalog_offers
               WHERE run_id = %s AND offer_id = 'Q100348826-512GB'""",
            (run_id,),
        ).fetchone()
        with connection.transaction():
            connection.execute(
                "UPDATE experiment_runs SET clock_at = %s WHERE run_id = %s",
                (FIXTURE_EXPIRES_AT, run_id),
            )
    response = client.post(
        f"/checkout_sessions/{checkout_id}/complete",
        headers={**headers, "Idempotency-Key": "expired-complete"},
        json=_payment(),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "CHECKOUT_EXPIRED"
    with psycopg.connect(database_url()) as connection:
        after = connection.execute(
            """SELECT snapshot ->> 'available_quantity' FROM catalog_offers
               WHERE run_id = %s AND offer_id = 'Q100348826-512GB'""",
            (run_id,),
        ).fetchone()
        orders = connection.execute(
            "SELECT count(*) FROM orders WHERE checkout_id = %s", (checkout_id,)
        ).fetchone()
    assert after == before
    assert orders == (0,)


def test_complete_non_object_body_returns_typed_invalid_input() -> None:
    migrate()
    client, headers, checkout_id, _ = _client("complete-non-object")
    response = client.post(
        f"/checkout_sessions/{checkout_id}/complete",
        headers={**headers, "Idempotency-Key": "non-object"},
        json=["not", "an", "object"],
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_INPUT"


def test_complete_rejects_unsupported_fields_and_conflicting_key() -> None:
    migrate()
    client, headers, checkout_id, _ = _client("complete-validation")
    path = f"/checkout_sessions/{checkout_id}/complete"
    invalid = client.post(
        path,
        headers={**headers, "Idempotency-Key": "invalid"},
        json={**_payment(), "buyer": {"email": "not-used@example.test"}},
    )
    assert invalid.status_code == 400
    assert invalid.json()["detail"]["code"] == "INVALID_INPUT"
    first = client.post(path, headers={**headers, "Idempotency-Key": "conflict"}, json=_payment())
    assert first.status_code == 200
    conflict = client.post(
        path, headers={**headers, "Idempotency-Key": "conflict"}, json=_payment("declined")
    )
    assert conflict.status_code == 422
    assert conflict.json()["detail"]["code"] == "idempotency_conflict"


def test_last_unit_completion_serializes_to_one_order() -> None:
    migrate()
    client, headers, first_id, _ = _client("complete-last-unit", offer_id="Q106629718-128GB")
    second = client.post(
        "/checkout_sessions",
        headers={**headers, "Idempotency-Key": "create-second"},
        json={
            "line_items": [{"id": "Q106629718-128GB"}],
            "currency": "cop",
            "capabilities": {},
        },
    )
    assert second.status_code == 201
    second_id = str(second.json()["id"])
    update = {
        "buyer": {
            "email": "buyer.complete@example.test",
            "first_name": "Buyer",
            "last_name": "Complete",
        },
        "fulfillment_details": {
            "name": "Buyer Complete",
            "email": "buyer.complete@example.test",
            "phone_number": "+573000000000",
            "address": {
                "name": "Buyer Complete",
                "line_one": "Calle 100 # 10-20",
                "city": "Bogota",
                "state": "DC",
                "country": "CO",
                "postal_code": "110111",
            },
        },
        "selected_fulfillment_options": [
            {
                "type": "shipping",
                "option_id": f"ship_{second_id}",
                "item_ids": [f"li_{second_id}"],
            }
        ],
    }
    ready = client.post(
        f"/checkout_sessions/{second_id}",
        headers={**headers, "Idempotency-Key": "ready-second"},
        json=update,
    )
    assert ready.status_code == 200

    def complete(checkout_id: str, key: str):
        return client.post(
            f"/checkout_sessions/{checkout_id}/complete",
            headers={**headers, "Idempotency-Key": key},
            json=_payment(),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda args: complete(*args),
                ((first_id, "complete-first"), (second_id, "complete-second")),
            )
        )
    assert sorted(response.status_code for response in results) == [200, 409]
    assert sum(response.status_code == 200 for response in results) == 1
    failed = next(response for response in results if response.status_code == 409)
    assert failed.json()["detail"]["code"] == "out_of_stock"


def test_completed_checkout_rejects_update_and_cancel() -> None:
    migrate()
    client, headers, checkout_id, _ = _client("complete-terminal")
    complete = client.post(
        f"/checkout_sessions/{checkout_id}/complete",
        headers={**headers, "Idempotency-Key": "terminal-complete"},
        json=_payment(),
    )
    assert complete.status_code == 200
    update = client.post(
        f"/checkout_sessions/{checkout_id}",
        headers={**headers, "Idempotency-Key": "terminal-update"},
        json={"buyer": {"email": "another@example.test"}},
    )
    cancel = client.post(
        f"/checkout_sessions/{checkout_id}/cancel",
        headers={**headers, "Idempotency-Key": "terminal-cancel"},
        json={},
    )
    assert update.status_code == 409
    assert update.json()["detail"]["code"] == "CHECKOUT_NOT_EDITABLE"
    assert cancel.status_code == 405
    assert cancel.json()["detail"]["code"] == "CHECKOUT_NOT_CANCELABLE"
    assert cancel.headers["Request-Id"]
    observation = _observation(cancel.headers["Request-Id"])
    assert observation[2:5] == ("cancel", "error", 405)
    assert observation[6:] == (checkout_id, None, "CHECKOUT_NOT_CANCELABLE")


def test_order_update_creates_one_full_delivery_and_is_idempotent() -> None:
    migrate()
    client, headers, checkout_id, run_id = _client("order-update")
    complete = client.post(
        f"/checkout_sessions/{checkout_id}/complete",
        headers={**headers, "Idempotency-Key": "update-complete"},
        json=_payment(),
    )
    assert complete.status_code == 200
    order_id = complete.json()["order"]["id"]
    changed = CheckoutService(
        ExecutionContext(
            run_id=run_id,
            actor_id="order-update",
            request_id="update-1",
            received_at="2026-09-19T00:00:00Z",
        )
    ).update_order_status(order_id)
    repeated = CheckoutService(
        ExecutionContext(
            run_id=run_id,
            actor_id="order-update",
            request_id="update-2",
            received_at="2026-09-19T00:00:00Z",
        )
    ).update_order_status(order_id)
    assert changed.ok is True
    assert repeated.ok is True
    assert changed.data.status == "processing"
    assert repeated.data.status == "processing"
    with psycopg.connect(database_url()) as connection:
        rows = connection.execute(
            """SELECT event_type, payload ->> 'type', payload -> 'data' ->> 'type',
                      payload -> 'data' ->> 'status'
               FROM webhook_deliveries WHERE order_id = %s ORDER BY event_type""",
            (order_id,),
        ).fetchall()
    assert rows == [
        ("order_create", "order_create", "order", "confirmed"),
        ("order_update", "order_update", "order", "processing"),
    ]
