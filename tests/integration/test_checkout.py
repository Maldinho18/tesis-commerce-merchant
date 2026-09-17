import os
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from commerce_lab.checkout import CheckoutService
from commerce_lab.context import authenticate_lab_session, issue_lab_session
from commerce_lab.contracts import Failure, Success
from commerce_lab.db import database_url, migrate, seed
from commerce_lab.fixtures import FIXTURE_DELIVERY_CONTEXT, FIXTURE_EXPIRES_AT

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_INTEGRATION") != "1",
    reason="requires the local synthetic PostgreSQL service",
)


def _episode(actor_id: str) -> tuple[str, str]:
    result = seed(actor_id=actor_id, variant="B0")
    run_id = str(result["run_id"])
    return run_id, issue_lab_session(run_id, actor_id)


def _payload(key: str, offer_id: str = "SON-01") -> dict[str, object]:
    return {
        "offer_id": offer_id,
        "expected_offer_revision": 1,
        "quantity": 1,
        "delivery_context": FIXTURE_DELIVERY_CONTEXT.model_dump(),
        "idempotency_key": key,
    }


def test_prepare_is_persistent_idempotent_and_server_authoritative() -> None:
    migrate()
    run_id, token = _episode("checkout-idempotent")
    context = authenticate_lab_session(token)
    first = CheckoutService(context).prepare(_payload("same-request"))
    replay = CheckoutService(authenticate_lab_session(token)).prepare(_payload("same-request"))
    assert isinstance(first, Success)
    assert isinstance(replay, Success)
    assert replay.data == first.data
    assert first.data.pricing.total_minor == 74_000
    assert first.data.status == "prepared"

    with psycopg.connect(database_url()) as connection:
        stored = connection.execute(
            "SELECT count(*), min(idempotency_sha256) FROM checkout_sessions WHERE run_id = %s",
            (run_id,),
        ).fetchone()
    assert stored is not None and stored[0] == 1
    assert stored[1] != "same-request"


def test_same_key_with_different_content_conflicts() -> None:
    migrate()
    _, token = _episode("checkout-conflict")
    service = CheckoutService(authenticate_lab_session(token))
    assert isinstance(service.prepare(_payload("reused-key")), Success)
    conflict = service.prepare(_payload("reused-key", offer_id="SON-02"))
    assert isinstance(conflict, Failure)
    assert conflict.error.code == "IDEMPOTENCY_CONFLICT"


def test_concurrent_retries_create_exactly_one_checkout() -> None:
    migrate()
    run_id, token = _episode("checkout-concurrent")

    def prepare() -> str:
        result = CheckoutService(authenticate_lab_session(token)).prepare(
            _payload("concurrent-key")
        )
        assert isinstance(result, Success)
        return result.data.id

    with ThreadPoolExecutor(max_workers=4) as pool:
        checkout_ids = list(pool.map(lambda _: prepare(), range(4)))
    assert len(set(checkout_ids)) == 1
    with psycopg.connect(database_url()) as connection:
        count = connection.execute(
            "SELECT count(*) FROM checkout_sessions WHERE run_id = %s", (run_id,)
        ).fetchone()
    assert count is not None and count[0] == 1


def test_checkout_isolated_by_episode_and_expires_on_scenario_clock() -> None:
    migrate()
    run_a, token_a = _episode("checkout-owner-a")
    _, token_b = _episode("checkout-owner-b")
    prepared = CheckoutService(authenticate_lab_session(token_a)).prepare(_payload("owned-key"))
    assert isinstance(prepared, Success)

    foreign = CheckoutService(authenticate_lab_session(token_b)).get(
        {"checkout_id": prepared.data.id}
    )
    assert isinstance(foreign, Failure)
    assert foreign.error.code == "CHECKOUT_NOT_FOUND"

    with psycopg.connect(database_url()) as connection, connection.transaction():
        connection.execute(
            "UPDATE experiment_runs SET clock_at = %s WHERE run_id = %s",
            (FIXTURE_EXPIRES_AT, run_a),
        )
    expired = CheckoutService(authenticate_lab_session(token_a)).get(
        {"checkout_id": prepared.data.id}
    )
    assert isinstance(expired, Success)
    assert expired.data.status == "expired"


def test_revision_and_expiration_fail_before_creating_checkout() -> None:
    migrate()
    run_id, token = _episode("checkout-validation")
    service = CheckoutService(authenticate_lab_session(token))
    mismatch = service.prepare({**_payload("wrong-revision"), "expected_offer_revision": 2})
    assert isinstance(mismatch, Failure)
    assert mismatch.error.code == "OFFER_REVISION_MISMATCH"

    with psycopg.connect(database_url()) as connection, connection.transaction():
        connection.execute(
            "UPDATE experiment_runs SET clock_at = %s WHERE run_id = %s",
            (FIXTURE_EXPIRES_AT, run_id),
        )
    expired = service.prepare(_payload("expired-offer"))
    assert isinstance(expired, Failure)
    assert expired.error.code == "OFFER_EXPIRED"


def test_two_concurrent_cancels_have_one_effect() -> None:
    migrate()
    run_id, token = _episode("checkout-concurrent-cancel")
    prepared = CheckoutService(authenticate_lab_session(token)).prepare(_payload("create"))
    assert isinstance(prepared, Success)
    checkout_id = prepared.data.id

    def cancel(key: str):
        return CheckoutService(authenticate_lab_session(token)).cancel(
            {"checkout_id": checkout_id, "idempotency_key": key}
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(cancel, ("cancel-a", "cancel-b")))
    assert any(isinstance(result, Success) for result in results)
    assert all(
        isinstance(result, Success)
        or result.error.code in {"IDEMPOTENCY_IN_FLIGHT", "CHECKOUT_NOT_CANCELABLE"}
        for result in results
    )
    with psycopg.connect(database_url()) as connection:
        row = connection.execute(
            "SELECT revision, status FROM checkout_sessions WHERE run_id = %s AND checkout_id = %s",
            (run_id, checkout_id),
        ).fetchone()
        events = connection.execute(
            """SELECT count(*) FROM run_events
               WHERE run_id = %s AND event_type = 'checkout.canceled'""",
            (run_id,),
        ).fetchone()
    assert row == (2, "canceled")
    assert events == (1,)


def test_two_concurrent_updates_serialize_and_increment_revision() -> None:
    migrate()
    run_id, token = _episode("checkout-concurrent-update")
    prepared = CheckoutService(authenticate_lab_session(token)).prepare(_payload("create"))
    assert isinstance(prepared, Success)
    checkout_id = prepared.data.id

    def update(key: str):
        return CheckoutService(authenticate_lab_session(token)).update(
            {
                "checkout_id": checkout_id,
                "selected_fulfillment_option_id": f"ship_{checkout_id}",
                "idempotency_key": key,
            }
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, ("update-a", "update-b")))
    for index, result in enumerate(results):
        if isinstance(result, Failure) and result.error.code == "IDEMPOTENCY_IN_FLIGHT":
            results[index] = update(("update-a", "update-b")[index])
    assert all(isinstance(result, Success) for result in results)
    with psycopg.connect(database_url()) as connection:
        row = connection.execute(
            "SELECT revision, status FROM checkout_sessions WHERE run_id = %s AND checkout_id = %s",
            (run_id, checkout_id),
        ).fetchone()
        events = connection.execute(
            "SELECT count(*) FROM run_events WHERE run_id = %s AND event_type = 'checkout.updated'",
            (run_id,),
        ).fetchone()
    assert row == (3, "prepared")
    assert events == (2,)


def test_locked_checkout_reports_in_flight_without_side_effect() -> None:
    migrate()
    run_id, token = _episode("checkout-in-flight")
    prepared = CheckoutService(authenticate_lab_session(token)).prepare(_payload("create"))
    assert isinstance(prepared, Success)
    checkout_id = prepared.data.id
    with psycopg.connect(database_url()) as connection, connection.transaction():
        connection.execute(
            """SELECT checkout_id FROM checkout_sessions
               WHERE run_id = %s AND checkout_id = %s FOR UPDATE""",
            (run_id, checkout_id),
        ).fetchone()
        result = CheckoutService(authenticate_lab_session(token)).update(
            {
                "checkout_id": checkout_id,
                "selected_fulfillment_option_id": f"ship_{checkout_id}",
                "idempotency_key": "locked-key",
            }
        )
        assert isinstance(result, Failure)
        assert result.error.code == "IDEMPOTENCY_IN_FLIGHT"
    with psycopg.connect(database_url()) as connection:
        row = connection.execute(
            "SELECT revision FROM checkout_sessions WHERE run_id = %s AND checkout_id = %s",
            (run_id, checkout_id),
        ).fetchone()
    assert row == (1,)
