"""Real disposable PostgreSQL + ASGI HTTP. No Agent, production DB or PSP calls."""

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier, Event

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.types.json import Jsonb
from pydantic import TypeAdapter

import commerce_lab.api as api
from commerce_lab.acp import ACPCheckoutAdapter, creation_fingerprint
from commerce_lab.checkout import CheckoutService
from commerce_lab.context import authenticate_lab_session, issue_lab_session
from commerce_lab.contracts import Offer, Success
from commerce_lab.contracts.creation_lookup import (
    LOOKUP_SCHEMA,
    CreationLookupError,
    CreationLookupResult,
    original_response_sha256,
)
from commerce_lab.creation_lookup import CheckoutCreationLookup
from commerce_lab.creation_lookup_api import LOOKUP_PATH
from commerce_lab.db import database_url, migrate, seed
from commerce_lab.fixtures import FIXTURE_DELIVERY_CONTEXT

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_INTEGRATION") != "1", reason="requires isolated synthetic PostgreSQL"
)
BODY = {
    "line_items": [{"id": "Q100286751-256GB"}],
    "currency": "cop",
    "capabilities": {"payment": {"handlers": []}},
}
KEY = "synthetic-lookup-original-key-do-not-return"
DIGEST = hashlib.sha256(KEY.encode()).hexdigest()
ACTOR = "lookup-owner"


def one(cursor):
    row = cursor.fetchone()
    assert row is not None
    return row


@pytest.fixture(scope="module", autouse=True)
def disposable_cluster():
    expected = os.getenv("RECOVERY_TEST_CLUSTER")
    if not expected:
        pytest.skip("RECOVERY_TEST_CLUSTER must identify a disposable cluster")
    with psycopg.connect(database_url()) as connection:
        assert (
            Path(one(connection.execute("SHOW data_directory"))[0]).resolve()
            == Path(expected).resolve()
        )
    migrate()


def episode(actor=ACTOR):
    run = str(seed(actor_id=actor, variant="B2")["run_id"])
    token = issue_lab_session(run, actor)
    return run, {"Authorization": f"Bearer {token}", "API-Version": "2026-04-17"}


@pytest.fixture
def created():
    run, headers = episode()
    with TestClient(api.app) as client:
        first = client.post(
            "/checkout_sessions", headers={**headers, "Idempotency-Key": KEY}, json=BODY
        )
    assert first.status_code == 201
    return run, headers, first.json()


def lookup(headers, digest=DIGEST, *, extra=None, path=LOOKUP_PATH):
    with TestClient(api.app) as client:
        return client.post(
            path,
            headers=headers,
            json={
                "schema_version": LOOKUP_SCHEMA,
                "idempotency_key_sha256": digest,
                **(extra or {}),
            },
        )


def snapshot():
    with psycopg.connect(database_url()) as connection:
        tables = connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        ).fetchall()
        return {
            table: one(
                connection.execute(
                    sql.SQL(
                        "SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),"
                        "'[]'::jsonb) FROM {} t"
                    ).format(sql.Identifier(table))
                )
            )[0]
            for (table,) in tables
        }


def test_found_without_commerce_catalog_calls_or_any_table_mutation(created, monkeypatch):
    run, headers, original = created
    before = snapshot()

    def forbidden(*args, **kwargs):
        pytest.fail("Lookup attempted a commerce operation or response reconstruction")

    for target, methods in (
        (ACPCheckoutAdapter, ("create", "get", "update", "cancel", "_response", "_offer")),
        (
            CheckoutService,
            ("prepare", "prepare_in_transaction", "get", "update", "cancel", "complete"),
        ),
    ):
        for method in methods:
            monkeypatch.setattr(target, method, forbidden)
    response = lookup(headers)
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    result = TypeAdapter(CreationLookupResult).validate_python(response.json())
    assert result.result == "found"
    assert result.run_id == run and result.actor_id == ACTOR
    assert result.checkout_id == original["id"] and result.original_response == original
    assert result.acp_create_fingerprint == creation_fingerprint(BODY)
    assert result.original_response_sha256 == original_response_sha256(original)
    assert result.request_id == response.headers["Request-Id"]
    assert KEY not in response.text and headers["Authorization"].split()[1] not in response.text
    assert snapshot() == before


def test_lookup_transaction_is_read_only_and_uses_no_catalog(created, monkeypatch):
    _, headers, _ = created
    real_connect = psycopg.connect
    observed = []

    class Probe:
        def __init__(self, connection):
            self.connection = connection

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def execute(self, query, params=None):
            text = str(query)
            assert "catalog_offers" not in text.lower()
            if text.startswith("SELECT run_id,actor_id,idempotency_sha256"):
                assert one(self.connection.execute("SHOW transaction_read_only"))[0] == "on"
                observed.append(True)
            return self.connection.execute(query, params)

    @contextmanager
    def connect(*args, **kwargs):
        with real_connect(*args, **kwargs) as connection:
            yield Probe(connection)

    monkeypatch.setattr(psycopg, "connect", connect)
    assert lookup(headers).json()["result"] == "found" and observed == [True]


def test_renewed_token_and_client_request_id_do_not_change_authority(created):
    run, _, original = created
    renewed = issue_lab_session(run, ACTOR)
    first = lookup(
        {
            "Authorization": f"Bearer {renewed}",
            "API-Version": "2026-04-17",
            "Request-Id": "client-chosen",
        }
    )
    assert first.status_code == 200 and first.json()["original_response"] == original
    assert first.json()["request_id"] != "client-chosen"


@pytest.mark.parametrize("invalid", ["expire", "revoke", "missing"])
def test_unauthenticated_expired_or_revoked_are_rejected(created, invalid):
    _, headers, _ = created
    if invalid == "missing":
        headers = {"API-Version": "2026-04-17"}
    else:
        token_hash = hashlib.sha256(headers["Authorization"].split()[1].encode()).hexdigest()
        with psycopg.connect(database_url()) as connection:
            if invalid == "expire":
                connection.execute(
                    "UPDATE lab_sessions SET created_at=now()-interval '1 hour',"
                    "expires_at=now()-interval '1 second' WHERE session_sha256=%s",
                    (token_hash,),
                )
            else:
                connection.execute(
                    "UPDATE lab_sessions SET revoked_at=now() WHERE session_sha256=%s",
                    (token_hash,),
                )
    before = snapshot()
    response = lookup(headers)
    assert response.status_code == 401
    assert CreationLookupError.model_validate(response.json()).code == "unauthenticated"
    assert response.headers["Cache-Control"] == "no-store" and snapshot() == before


@pytest.mark.parametrize("other_actor", [False, True])
def test_other_actor_or_run_cannot_read_original_creation(created, other_actor):
    _, _, original = created
    other_run, headers = episode("different-owner" if other_actor else ACTOR)
    response = lookup(headers)
    assert response.status_code == 200 and response.json()["result"] == "not_found"
    assert response.json()["run_id"] == other_run
    assert original["id"] not in response.text and "original_response" not in response.json()


def test_unknown_digest_is_not_evidence_of_absence_or_permission(created):
    _, headers, _ = created
    before = snapshot()
    response = lookup(headers, "0" * 64)
    assert response.json()["result"] == "not_found"
    assert set(response.json()) == {
        "schema_version",
        "result",
        "run_id",
        "actor_id",
        "request_id",
        "idempotency_key_sha256",
    }
    assert snapshot() == before


@pytest.mark.parametrize(
    "change",
    [
        {"idempotency_key_sha256": "A" * 64},
        {"idempotency_key_sha256": "bad"},
        {"schema_version": "unknown"},
        {"run_id": "do-not-echo-private"},
        {"actor_id": "do-not-echo-private"},
        {"checkout_id": "do-not-echo-private"},
        {"idempotency_key": "do-not-echo-private"},
        {"bearer_token": "do-not-echo-private"},
    ],
)
def test_strict_invalid_requests_are_non_echoing_and_no_store(created, change):
    _, headers, _ = created
    response = lookup(headers, extra=change)
    assert response.status_code == 422 and "do-not-echo-private" not in response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert CreationLookupError.model_validate(response.json()).code == "invalid_request"


@pytest.mark.parametrize("version", [None, "unknown"])
def test_api_version_remains_required(created, version):
    _, headers, _ = created
    headers = {k: v for k, v in headers.items() if k != "API-Version"}
    if version is not None:
        headers["API-Version"] = version
    response = lookup(headers)
    assert response.status_code == 400 and response.headers["Cache-Control"] == "no-store"


def test_query_scope_or_key_substitutes_are_rejected(created):
    _, headers, _ = created
    assert lookup(headers, path=LOOKUP_PATH + "?run_id=forged").status_code == 422


def test_historical_internal_creation_is_unrecoverable_without_backfill():
    _, headers = episode()
    context = authenticate_lab_session(headers["Authorization"].split()[1])
    result = CheckoutService(context).prepare(
        {
            "offer_id": BODY["line_items"][0]["id"],
            "expected_offer_revision": 1,
            "quantity": 1,
            "delivery_context": FIXTURE_DELIVERY_CONTEXT.model_dump(),
            "idempotency_key": KEY,
        }
    )
    assert isinstance(result, Success)
    before = snapshot()
    response = lookup(headers)
    assert response.json()["result"] == "unrecoverable"
    assert "checkout_id" not in response.json() and snapshot() == before


@pytest.mark.parametrize("change", ["price", "name", "revision", "availability"])
def test_lookup_returns_original_after_catalog_changes(created, change):
    run, headers, original = created
    with psycopg.connect(database_url()) as connection:
        value = one(
            connection.execute(
                "SELECT snapshot FROM catalog_offers WHERE run_id=%s AND offer_id=%s",
                (run, BODY["line_items"][0]["id"]),
            )
        )[0]
        value["revision"] += 1
        if change == "price":
            value["pricing"]["items_total_minor"] += 100
            value["pricing"]["total_minor"] += 100
        elif change == "name":
            value["name"] = "Modified name"
        elif change == "availability":
            value.update(availability="out_of_stock", available_quantity=0)
        Offer.model_validate(value)
        connection.execute(
            "UPDATE catalog_offers SET snapshot=%s,revision=%s WHERE run_id=%s AND offer_id=%s",
            (Jsonb(value), value["revision"], run, value["id"]),
        )
    before = snapshot()
    assert lookup(headers).json()["original_response"] == original
    assert snapshot() == before


def test_canceled_checkout_does_not_change_historical_lookup(created):
    _, headers, original = created
    with TestClient(api.app) as client:
        canceled = client.post(
            f"/checkout_sessions/{original['id']}/cancel",
            headers={**headers, "Idempotency-Key": "synthetic-lookup-cancel"},
            json={},
        )
    assert canceled.status_code == 200 and canceled.json()["status"] == "canceled"
    before = snapshot()
    recovered = lookup(headers).json()
    assert recovered["original_response"] == original
    assert recovered["original_response"]["status"] == "not_ready_for_payment"
    assert snapshot() == before


@pytest.mark.parametrize("damage", ["schema", "credential"])
def test_corrupt_response_is_unavailable_never_found_or_rebuilt(created, damage):
    run, headers, original = created
    damaged = (
        {**original, "status": "invalid-state"}
        if damage == "schema"
        else {**original, "bearer_token": "do-not-expose"}
    )
    with psycopg.connect(database_url()) as connection:
        connection.execute(
            "ALTER TABLE checkout_sessions DISABLE TRIGGER checkout_creation_immutable"
        )
        connection.execute(
            "UPDATE checkout_sessions SET acp_create_response=%s WHERE run_id=%s",
            (Jsonb(damaged), run),
        )
        connection.execute(
            "ALTER TABLE checkout_sessions ENABLE TRIGGER checkout_creation_immutable"
        )
    before = snapshot()
    response = lookup(headers)
    assert response.status_code == 503 and "do-not-expose" not in response.text
    assert CreationLookupError.model_validate(response.json()).code == "lookup_unavailable"
    assert snapshot() == before


def test_concurrent_repeated_queries_do_not_create_or_change_any_row(created):
    _, headers, original = created
    before = snapshot()
    barrier = Barrier(4)

    def call(_):
        barrier.wait(timeout=10)
        return lookup(headers)

    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(executor.map(call, range(4)))
    assert all(
        r.status_code == 200 and r.json()["original_response"] == original for r in responses
    )
    assert len({r.json()["request_id"] for r in responses}) == 4
    assert snapshot() == before


@pytest.mark.parametrize("stage", ["query", "authentication"])
def test_internal_error_is_not_mistaken_for_not_found(created, monkeypatch, stage):
    _, headers, _ = created
    before = snapshot()

    def fail(*args, **kwargs):
        raise psycopg.OperationalError("do-not-reflect-internal-secret")

    monkeypatch.setattr(
        CheckoutCreationLookup, "lookup", fail
    ) if stage == "query" else monkeypatch.setattr(api, "authenticate_lab_session", fail)
    response = lookup(headers)
    assert response.status_code == 503 and "do-not-reflect" not in response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["result"] == "error" and snapshot() == before


def test_not_found_can_coexist_with_an_uncommitted_creation(monkeypatch):
    _, headers = episode()
    written, release = Event(), Event()
    save = ACPCheckoutAdapter._save_creation

    def hold_commit(self, *args, **kwargs):
        result = save(self, *args, **kwargs)
        written.set()
        assert release.wait(timeout=15)
        return result

    monkeypatch.setattr(ACPCheckoutAdapter, "_save_creation", hold_commit)

    def explicitly_create():
        with TestClient(api.app) as client:
            return client.post(
                "/checkout_sessions", headers={**headers, "Idempotency-Key": KEY}, json=BODY
            )

    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(explicitly_create)
        try:
            assert written.wait(timeout=10)
            during = lookup(headers)
            assert during.status_code == 200 and during.json()["result"] == "not_found"
        finally:
            release.set()
        assert pending.result(timeout=20).status_code == 201
    assert lookup(headers).json()["result"] == "found"
