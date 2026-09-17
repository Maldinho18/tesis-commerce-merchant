import json
import os
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from commerce_lab.api import app
from commerce_lab.context import authenticate_lab_session, issue_lab_session
from commerce_lab.db import database_url, migrate, seed
from commerce_lab.fixtures import FIXTURE_EXPIRES_AT

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_INTEGRATION") != "1",
    reason="requires the local synthetic PostgreSQL service",
)

ROOT = Path(__file__).resolve().parents[2]
BUNDLE: dict[str, Any] = json.loads(
    (ROOT / "vendor/acp/2026-04-17/schema.agentic_checkout.json").read_text(encoding="utf-8")
)
REGISTRY = Registry().with_resource(str(BUNDLE["$id"]), Resource.from_contents(BUNDLE))
CHECKOUT_VALIDATOR = Draft202012Validator(
    {"$ref": f"{BUNDLE['$id']}#/$defs/CheckoutSession"}, registry=REGISTRY
)


def _client(actor_id: str) -> tuple[TestClient, dict[str, str]]:
    result = seed(actor_id=actor_id, variant="B0")
    token = issue_lab_session(str(result["run_id"]), actor_id)
    return TestClient(app), {
        "Authorization": f"Bearer {token}",
        "API-Version": "2026-04-17",
    }


def _body(offer_id: str = "SON-01") -> dict[str, object]:
    return {
        "line_items": [{"id": offer_id}],
        "currency": "usd",
        "capabilities": {"payment": {"handlers": []}},
    }


def _selection(checkout_id: str, option_id: str | None = None) -> dict[str, object]:
    return {
        "selected_fulfillment_options": [
            {
                "type": "shipping",
                "option_id": option_id or f"ship_{checkout_id}",
                "item_ids": [f"li_{checkout_id}"],
            }
        ]
    }


def _create(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post(
        "/checkout_sessions", headers={**headers, "Idempotency-Key": "create-key"}, json=_body()
    )
    assert response.status_code == 201
    return str(response.json()["id"])


def test_acp_create_and_get_round_trip_validates_against_frozen_schema() -> None:
    migrate()
    client, headers = _client("acp-round-trip")
    create = client.post(
        "/checkout_sessions",
        headers={**headers, "Idempotency-Key": "acp-create-001"},
        json=_body(),
    )
    assert create.status_code == 201
    CHECKOUT_VALIDATOR.validate(create.json())
    assert create.headers["Idempotency-Key"] == "acp-create-001"
    assert create.headers["Request-Id"]
    assert create.json()["status"] == "not_ready_for_payment"
    assert create.json()["capabilities"]["payment"]["handlers"] == []
    assert "order" not in create.json()
    assert "revision" not in create.json()

    checkout_id = create.json()["id"]
    get = client.get(f"/checkout_sessions/{checkout_id}", headers=headers)
    assert get.status_code == 200
    CHECKOUT_VALIDATOR.validate(get.json())
    assert get.json() == create.json()
    assert get.headers["Request-Id"] != create.headers["Request-Id"]


def test_acp_create_replays_same_checkout_and_rejects_conflicting_content() -> None:
    migrate()
    client, headers = _client("acp-idempotency")
    request_headers = {**headers, "Idempotency-Key": "same-acp-key"}
    first = client.post("/checkout_sessions", headers=request_headers, json=_body("SON-01"))
    replay = client.post("/checkout_sessions", headers=request_headers, json=_body("SON-01"))
    conflict = client.post("/checkout_sessions", headers=request_headers, json=_body("SON-02"))
    assert first.status_code == replay.status_code == 201
    assert first.json()["id"] == replay.json()["id"]
    assert conflict.status_code == 422
    assert conflict.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_acp_fails_closed_on_protocol_headers_and_unsupported_fields() -> None:
    migrate()
    client, headers = _client("acp-validation")
    no_version = client.post(
        "/checkout_sessions",
        headers={"Authorization": headers["Authorization"], "Idempotency-Key": "key-a"},
        json=_body(),
    )
    no_key = client.post("/checkout_sessions", headers=headers, json=_body())
    injected = client.post(
        "/checkout_sessions",
        headers={**headers, "Idempotency-Key": "key-b"},
        json={**_body(), "revision": 1},
    )
    multiple = client.post(
        "/checkout_sessions",
        headers={**headers, "Idempotency-Key": "key-c"},
        json={**_body(), "line_items": [{"id": "SON-01"}, {"id": "SON-02"}]},
    )
    assert no_version.status_code == 400
    assert no_key.status_code == 400
    assert injected.status_code == 422
    assert multiple.status_code == 422


def test_acp_checkout_cannot_be_read_from_another_episode() -> None:
    migrate()
    owner, owner_headers = _client("acp-owner")
    other, other_headers = _client("acp-other")
    created = owner.post(
        "/checkout_sessions",
        headers={**owner_headers, "Idempotency-Key": "owner-key"},
        json=_body(),
    )
    foreign = other.get(f"/checkout_sessions/{created.json()['id']}", headers=other_headers)
    assert foreign.status_code == 404
    assert foreign.json()["detail"]["code"] == "CHECKOUT_NOT_FOUND"


def test_acp_update_get_replay_conflict_and_authoritative_revision() -> None:
    migrate()
    client, headers = _client("acp-update-cycle")
    checkout_id = _create(client, headers)
    run_id = authenticate_lab_session(headers["Authorization"].split(" ", 1)[1]).run_id
    with psycopg.connect(database_url()) as connection, connection.transaction():
        connection.execute(
            "UPDATE experiment_runs SET clock_at = %s WHERE run_id = %s",
            ("2026-09-10T14:01:00Z", run_id),
        )
    path = f"/checkout_sessions/{checkout_id}"
    request_headers = {**headers, "Idempotency-Key": "update-key"}
    first = client.post(path, headers=request_headers, json=_selection(checkout_id))
    replay = client.post(path, headers=request_headers, json=_selection(checkout_id))
    conflict = client.post(
        path, headers=request_headers, json=_selection(checkout_id, "ship_other")
    )
    current = client.get(path, headers=headers)
    assert first.status_code == replay.status_code == current.status_code == 200
    CHECKOUT_VALIDATOR.validate(first.json())
    assert first.json() == replay.json() == current.json()
    assert first.json()["updated_at"] == "2026-09-10T14:01:00Z"
    assert first.json()["status"] == "not_ready_for_payment"
    assert conflict.status_code == 422
    assert conflict.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"
    with psycopg.connect(database_url()) as connection:
        row = connection.execute(
            """SELECT revision, status, snapshot FROM checkout_sessions
               WHERE run_id = %s AND checkout_id = %s""",
            (run_id, checkout_id),
        ).fetchone()
        events = connection.execute(
            """SELECT event_type, payload FROM run_events
               WHERE run_id = %s
                 AND event_type IN ('checkout.updated', 'checkout.update_replayed')
               ORDER BY event_id""",
            (run_id,),
        ).fetchall()
    assert row is not None and row[0] == 2 and row[1] == "prepared"
    assert row[2]["revision"] == 2
    assert [event[0] for event in events] == ["checkout.updated", "checkout.update_replayed"]
    assert all(event[1]["checkout_id"] == checkout_id for event in events)
    assert all(event[1]["actor_id"] == "acp-update-cycle" for event in events)
    assert all(event[1]["request_id"] for event in events)


def test_acp_cancel_get_replay_and_second_cancel_is_405() -> None:
    migrate()
    client, headers = _client("acp-cancel-cycle")
    checkout_id = _create(client, headers)
    run_id = authenticate_lab_session(headers["Authorization"].split(" ", 1)[1]).run_id
    with psycopg.connect(database_url()) as connection, connection.transaction():
        connection.execute(
            "UPDATE experiment_runs SET clock_at = %s WHERE run_id = %s",
            ("2026-09-10T14:02:00Z", run_id),
        )
    path = f"/checkout_sessions/{checkout_id}/cancel"
    request_headers = {**headers, "Idempotency-Key": "cancel-key"}
    first = client.post(path, headers=request_headers)
    replay = client.post(path, headers=request_headers, json={})
    conflict = client.post(
        path, headers=request_headers, json={"intent_trace": {"reason_code": "other"}}
    )
    second = client.post(path, headers={**headers, "Idempotency-Key": "another-key"}, json={})
    current = client.get(f"/checkout_sessions/{checkout_id}", headers=headers)
    create_replay = client.post(
        "/checkout_sessions", headers={**headers, "Idempotency-Key": "create-key"}, json=_body()
    )
    assert first.status_code == replay.status_code == current.status_code == 200
    CHECKOUT_VALIDATOR.validate(first.json())
    assert first.json() == replay.json() == current.json()
    assert first.json()["status"] == "canceled"
    assert first.json()["updated_at"] == "2026-09-10T14:02:00Z"
    assert create_replay.status_code == 201
    assert create_replay.json()["id"] == checkout_id
    assert create_replay.json()["status"] == "not_ready_for_payment"
    assert conflict.status_code == 422
    assert conflict.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert second.status_code == 405
    assert second.json()["detail"]["code"] == "CHECKOUT_NOT_CANCELABLE"
    with psycopg.connect(database_url()) as connection:
        row = connection.execute(
            "SELECT revision, status FROM checkout_sessions WHERE run_id = %s AND checkout_id = %s",
            (run_id, checkout_id),
        ).fetchone()
        events = connection.execute(
            """SELECT event_type, payload FROM run_events
               WHERE run_id = %s
                 AND event_type IN ('checkout.canceled', 'checkout.cancel_replayed')
               ORDER BY event_id""",
            (run_id,),
        ).fetchall()
    assert row == (2, "canceled")
    assert [event[0] for event in events] == ["checkout.canceled", "checkout.cancel_replayed"]
    assert all(event[1]["checkout_id"] == checkout_id for event in events)
    assert all(event[1]["actor_id"] == "acp-cancel-cycle" for event in events)
    assert all(event[1]["request_id"] for event in events)


def test_acp_lifecycle_rejects_missing_headers_foreign_ids_and_terminal_update() -> None:
    migrate()
    owner, headers = _client("acp-lifecycle-owner")
    other, foreign_headers = _client("acp-lifecycle-foreign")
    checkout_id = _create(owner, headers)
    update_path = f"/checkout_sessions/{checkout_id}"
    cancel_path = f"{update_path}/cancel"
    unsupported_update = owner.post(
        update_path,
        headers={**headers, "Idempotency-Key": "unsupported-update"},
        json={**_selection(checkout_id), "revision": 2},
    )
    unsupported_cancel = owner.post(
        cancel_path,
        headers={**headers, "Idempotency-Key": "unsupported-cancel"},
        json={"intent_trace": {"reason_code": "other", "trace_summary": "private"}},
    )
    assert unsupported_update.status_code == 422
    assert unsupported_cancel.status_code == 400
    assert unsupported_cancel.json()["detail"]["code"] == "INVALID_INPUT"
    for path, body in ((update_path, _selection(checkout_id)), (cancel_path, {})):
        assert owner.post(path, headers=headers, json=body).status_code == 400
        assert owner.post(path, headers={"API-Version": "2026-04-17"}, json=body).status_code == 401
        assert (
            owner.post(
                path,
                headers={"Authorization": headers["Authorization"], "Idempotency-Key": "x"},
                json=body,
            ).status_code
            == 400
        )
        foreign = other.post(
            path, headers={**foreign_headers, "Idempotency-Key": "foreign"}, json=body
        )
        assert foreign.status_code == 404
        assert foreign.json()["detail"]["code"] == "CHECKOUT_NOT_FOUND"
        missing_path = path.replace(checkout_id, "chk_missing")
        missing_body = _selection("chk_missing") if path == update_path else {}
        missing = owner.post(
            missing_path, headers={**headers, "Idempotency-Key": "missing"}, json=missing_body
        )
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "CHECKOUT_NOT_FOUND"
    canceled = owner.post(cancel_path, headers={**headers, "Idempotency-Key": "cancel"}, json={})
    assert canceled.status_code == 200
    blocked = owner.post(
        update_path,
        headers={**headers, "Idempotency-Key": "update-after-cancel"},
        json=_selection(checkout_id),
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "CHECKOUT_NOT_EDITABLE"


def test_acp_idempotency_key_is_scoped_by_mutation_endpoint() -> None:
    migrate()
    client, headers = _client("acp-operation-scoping")
    shared = {**headers, "Idempotency-Key": "same-opaque-key"}
    created = client.post("/checkout_sessions", headers=shared, json=_body())
    assert created.status_code == 201
    checkout_id = created.json()["id"]
    updated = client.post(
        f"/checkout_sessions/{checkout_id}",
        headers=shared,
        json=_selection(checkout_id),
    )
    canceled = client.post(f"/checkout_sessions/{checkout_id}/cancel", headers=shared, json={})
    update_replay = client.post(
        f"/checkout_sessions/{checkout_id}", headers=shared, json=_selection(checkout_id)
    )
    assert updated.status_code == canceled.status_code == 200
    assert update_replay.status_code == 200
    assert update_replay.json() == updated.json()
    assert updated.json()["status"] == "not_ready_for_payment"
    assert canceled.json()["status"] == "canceled"
    assert (
        client.get(f"/checkout_sessions/{checkout_id}", headers=headers).json()["status"]
        == "canceled"
    )


def test_acp_update_reports_in_flight_as_http_409() -> None:
    migrate()
    client, headers = _client("acp-http-in-flight")
    checkout_id = _create(client, headers)
    run_id = authenticate_lab_session(headers["Authorization"].split(" ", 1)[1]).run_id
    with psycopg.connect(database_url()) as connection, connection.transaction():
        connection.execute(
            """SELECT checkout_id FROM checkout_sessions
               WHERE run_id = %s AND checkout_id = %s FOR UPDATE""",
            (run_id, checkout_id),
        ).fetchone()
        response = client.post(
            f"/checkout_sessions/{checkout_id}",
            headers={**headers, "Idempotency-Key": "in-flight"},
            json=_selection(checkout_id),
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "IDEMPOTENCY_IN_FLIGHT"


def test_acp_expired_checkout_cannot_be_updated_but_can_be_canceled() -> None:
    migrate()
    client, headers = _client("acp-expired-lifecycle")
    checkout_id = _create(client, headers)
    run_id = authenticate_lab_session(headers["Authorization"].split(" ", 1)[1]).run_id
    with psycopg.connect(database_url()) as connection, connection.transaction():
        connection.execute(
            "UPDATE experiment_runs SET clock_at = %s WHERE run_id = %s",
            (FIXTURE_EXPIRES_AT, run_id),
        )
    updated = client.post(
        f"/checkout_sessions/{checkout_id}",
        headers={**headers, "Idempotency-Key": "expired-update"},
        json=_selection(checkout_id),
    )
    canceled = client.post(
        f"/checkout_sessions/{checkout_id}/cancel",
        headers={**headers, "Idempotency-Key": "expired-cancel"},
        json={},
    )
    assert updated.status_code == 409
    assert updated.json()["detail"]["code"] == "CHECKOUT_EXPIRED"
    assert canceled.status_code == 200
    assert canceled.json()["status"] == "canceled"
    assert (
        client.get(f"/checkout_sessions/{checkout_id}", headers=headers).json()["status"]
        == "canceled"
    )
