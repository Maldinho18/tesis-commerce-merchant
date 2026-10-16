"""Real PostgreSQL recovery; never enable against an operational database."""

import hashlib
import json
import os
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from time import sleep
from typing import Any, LiteralString, cast
from uuid import uuid4

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.types.json import Jsonb

from commerce_lab.acp import ACPCheckoutAdapter, ACPCheckoutCreateRequest
from commerce_lab.api import app
from commerce_lab.checkout import CheckoutService
from commerce_lab.context import authenticate_lab_session, issue_lab_session
from commerce_lab.contracts import Checkout, Failure, Offer, Success
from commerce_lab.db import database_url, migrate, seed
from commerce_lab.db.core import MIGRATIONS
from commerce_lab.fixtures import FIXTURE_DELIVERY_CONTEXT

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_INTEGRATION") != "1", reason="requires isolated synthetic PostgreSQL"
)
ROOT = Path(__file__).resolve().parents[2]
WORKER = Path(__file__).with_name("recovery_worker.py")
BODY = {
    "line_items": [{"id": "Q100286751-256GB"}],
    "currency": "cop",
    "capabilities": {"payment": {"handlers": []}},
}
KEY = "synthetic-recovery-key"


def one(cursor: psycopg.Cursor[Any]) -> tuple[Any, ...]:
    row = cursor.fetchone()
    assert row is not None
    return row


@pytest.fixture(scope="module", autouse=True)
def isolated_cluster():
    expected = os.getenv("RECOVERY_TEST_CLUSTER")
    if not expected:
        pytest.skip("RECOVERY_TEST_CLUSTER must identify a disposable cluster")
    with psycopg.connect(database_url()) as connection:
        actual = Path(one(connection.execute("SHOW data_directory"))[0]).resolve()
    assert actual == Path(expected).resolve()
    migrate()
    return str(actual)


@pytest.fixture
def episode(isolated_cluster):
    run_id = str(seed(actor_id="recovery-owner", variant="B2")["run_id"])
    token = issue_lab_session(run_id, "recovery-owner")
    return run_id, {
        "Authorization": f"Bearer {token}",
        "API-Version": "2026-04-17",
        "Idempotency-Key": KEY,
    }


def post(headers, body=BODY):
    with TestClient(app) as client:
        return client.post("/checkout_sessions", headers=headers, json=body)


def count(run_id):
    with psycopg.connect(database_url()) as connection:
        return one(
            connection.execute("SELECT count(*) FROM checkout_sessions WHERE run_id=%s", (run_id,))
        )[0]


def mutate(run_id, edit):
    with psycopg.connect(database_url()) as connection:
        data = one(
            connection.execute(
                "SELECT snapshot FROM catalog_offers WHERE run_id=%s AND offer_id=%s",
                (run_id, BODY["line_items"][0]["id"]),
            )
        )[0]
        edit(data)
        Offer.model_validate(data)
        connection.execute(
            "UPDATE catalog_offers SET snapshot=%s,revision=%s WHERE run_id=%s AND offer_id=%s",
            (Jsonb(data), data["revision"], run_id, data["id"]),
        )


def worker(headers, mode, cluster):
    payload = {"headers": headers, "body": BODY, "mode": mode, "cluster": cluster}
    return subprocess.run(
        [sys.executable, "-B", str(WORKER)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        timeout=20,
        cwd=ROOT,
    )


def test_same_post_across_two_processes_recovers_original(episode, isolated_cluster):
    run, headers = episode
    first = worker(headers, "create", isolated_cluster)
    second = worker(headers, "create", isolated_cluster)
    assert first.returncode == second.returncode == 0
    assert json.loads(first.stdout) == json.loads(second.stdout)
    assert json.loads(second.stdout)["status"] == 201
    assert count(run) == 1


@pytest.mark.parametrize("change", ["revision", "price", "name", "stock", "inactive", "all"])
def test_replay_ignores_mutable_catalog(episode, change):
    run, headers = episode
    first = post(headers)
    assert first.status_code == 201

    def edit(data):
        data["revision"] += 1
        if change in ("price", "all"):
            data["pricing"]["items_total_minor"] += 100
            data["pricing"]["total_minor"] += 100
        if change in ("name", "all"):
            data["name"] += " changed"
        if change in ("stock", "inactive", "all"):
            data.update(availability="out_of_stock", available_quantity=0)
        if change in ("inactive", "all"):
            data["product_status"] = "inactive"

    mutate(run, edit)
    replay = post(headers)
    assert replay.status_code == 201
    assert replay.json() == first.json()
    assert replay.content == first.content
    assert replay.headers["Request-Id"] != first.headers["Request-Id"]
    assert count(run) == 1


def test_replay_never_queries_offer_or_rebuilds_capabilities(episode, monkeypatch):
    run, headers = episode
    original = post(headers)

    def forbidden(*args, **kwargs):
        raise AssertionError("Replay touched mutable catalog/capabilities")

    monkeypatch.setattr(ACPCheckoutAdapter, "_offer", forbidden)
    monkeypatch.setattr("commerce_lab.acp.checkout_payment_capabilities", forbidden)
    monkeypatch.setattr(ACPCheckoutAdapter, "_response", forbidden)
    replay = post(headers)
    assert replay.status_code == 201 and replay.json() == original.json()
    assert count(run) == 1


def test_physical_offer_deletion_is_rejected_without_breaking_recovery(episode):
    run, headers = episode
    original = post(headers)
    with (
        psycopg.connect(database_url()) as connection,
        pytest.raises(psycopg.errors.ForeignKeyViolation),
    ):
        connection.execute(
            "DELETE FROM catalog_offers WHERE run_id=%s AND offer_id=%s",
            (run, BODY["line_items"][0]["id"]),
        )
    assert post(headers).json() == original.json()
    assert count(run) == 1


@pytest.mark.parametrize("variant", ["Q100348826-256GB", "missing-variant"])
def test_key_conflict_is_resolved_before_current_offer_lookup(episode, variant):
    run, headers = episode
    assert post(headers).status_code == 201
    response = post(headers, {**BODY, "line_items": [{"id": variant}]})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "idempotency_conflict"
    assert "id" not in response.json()["detail"] and count(run) == 1


def test_same_key_different_presence_conflicts_but_key_order_replays(episode):
    run, headers = episode
    first = post(headers)
    ordered = dict(reversed(list(BODY.items())))
    assert post(headers, ordered).json() == first.json()
    assert post(headers, {**BODY, "capabilities": {}}).status_code == 422
    assert count(run) == 1


def test_concurrent_same_key_and_conflicting_content(episode):
    run, headers = episode
    barrier = Barrier(4)

    def send(_):
        barrier.wait(timeout=10)
        return post(headers)

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(send, range(4)))
    assert [r.status_code for r in responses] == [201] * 4
    assert len({r.json()["id"] for r in responses}) == 1
    assert len({r.content for r in responses}) == 1 and count(run) == 1


def test_concurrent_different_bodies_have_one_winner(episode):
    run, headers = episode
    barrier = Barrier(2)

    def send(variant):
        barrier.wait(timeout=10)
        return post(headers, {**BODY, "line_items": [{"id": variant}]})

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(send, ["Q100286751-256GB", "Q100348826-256GB"]))
    assert sorted(r.status_code for r in responses) == [201, 422]
    assert count(run) == 1


@pytest.mark.parametrize("actor", ["recovery-owner", "recovery-other"])
def test_other_episodes_never_receive_original_creation(episode, actor):
    run, headers = episode
    first = post(headers).json()
    other = str(seed(actor_id=actor, variant="B2")["run_id"])
    token = issue_lab_session(other, actor)
    other_headers = {**headers, "Authorization": f"Bearer {token}"}
    created = post(other_headers)
    assert created.status_code == 201 and created.json()["id"] != first["id"]
    with TestClient(app) as client:
        assert (
            client.get(f"/checkout_sessions/{first['id']}", headers=other_headers).status_code
            == 404
        )
    assert count(run) == count(other) == 1


def test_same_episode_cannot_be_claimed_by_another_actor(episode):
    run, headers = episode
    original = post(headers).json()
    context = authenticate_lab_session(headers["Authorization"].split()[1])
    forged = context.model_copy(update={"actor_id": "recovery-other"})
    result = ACPCheckoutAdapter(forged).create(ACPCheckoutCreateRequest.model_validate(BODY), KEY)
    assert isinstance(result, Failure) and result.error.code == "FORBIDDEN"
    assert post(headers).json() == original and count(run) == 1


@pytest.mark.parametrize("invalid", ["version", "currency", "authority", "no_auth", "key"])
def test_replay_does_not_bypass_request_validation(episode, invalid):
    run, headers = episode
    original = post(headers).json()
    changed = dict(headers)
    body = dict(BODY)
    expected = 422
    if invalid == "version":
        changed["API-Version"] = "2099-01-01"
        expected = 400
    elif invalid == "currency":
        body["currency"] = "usd"
    elif invalid == "authority":
        body["actor_id"] = "recovery-owner"
    elif invalid == "no_auth":
        del changed["Authorization"]
        expected = 401
    else:
        changed["Idempotency-Key"] = ""
        expected = 400
    response = post(changed, body)
    assert response.status_code == expected and response.json() != original
    assert count(run) == 1


def test_client_request_id_does_not_grant_recovery_authority(episode):
    run, headers = episode
    first = post({**headers, "Request-Id": "client-supplied-correlation"})
    other = str(seed(actor_id="recovery-other", variant="B2")["run_id"])
    token = issue_lab_session(other, "recovery-other")
    replay = post(
        {
            **headers,
            "Authorization": f"Bearer {token}",
            "Request-Id": first.headers["Request-Id"],
        }
    )
    assert replay.status_code == 201 and replay.json()["id"] != first.json()["id"]
    assert replay.headers["Request-Id"] != first.headers["Request-Id"]
    assert count(run) == count(other) == 1


def test_internal_and_acp_creation_share_the_same_serialization_scope(episode):
    run, headers = episode
    context = authenticate_lab_session(headers["Authorization"].split()[1])
    barrier = Barrier(2)

    def internal():
        barrier.wait(timeout=10)
        return CheckoutService(context).prepare(
            {
                "offer_id": BODY["line_items"][0]["id"],
                "expected_offer_revision": 1,
                "quantity": 1,
                "delivery_context": FIXTURE_DELIVERY_CONTEXT.model_dump(),
                "idempotency_key": KEY,
            }
        )

    def acp():
        barrier.wait(timeout=10)
        return post(headers)

    with ThreadPoolExecutor(max_workers=2) as pool:
        internal_future = pool.submit(internal)
        acp_future = pool.submit(acp)
        domain = internal_future.result(timeout=15)
        response = acp_future.result(timeout=15)
    assert isinstance(domain, Success) and count(run) == 1
    if response.status_code == 201:
        assert response.json()["id"] == domain.data.id
    else:
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "creation_unrecoverable"


@pytest.mark.parametrize("invalid", ["expire", "revoke"])
def test_invalid_credentials_block_and_renewal_same_scope_recovers(episode, invalid):
    run, headers = episode
    first = post(headers).json()
    key_hash = hashlib.sha256(headers["Authorization"].split()[1].encode()).hexdigest()
    with psycopg.connect(database_url()) as connection:
        if invalid == "expire":
            connection.execute(
                """UPDATE lab_sessions
                SET created_at=now()-interval '1 hour',expires_at=now()-interval '1 second'
                WHERE session_sha256=%s""",
                (key_hash,),
            )
        else:
            connection.execute(
                "UPDATE lab_sessions SET revoked_at=now() WHERE session_sha256=%s", (key_hash,)
            )
    assert post(headers).status_code == 401
    renewed = issue_lab_session(run, "recovery-owner")
    assert post({**headers, "Authorization": f"Bearer {renewed}"}).json() == first
    assert count(run) == 1


def test_replay_keeps_original_response_after_cancel(episode):
    run, headers = episode
    first = post(headers)
    with TestClient(app) as client:
        canceled = client.post(
            f"/checkout_sessions/{first.json()['id']}/cancel",
            headers={**headers, "Idempotency-Key": "synthetic-cancel"},
            json={},
        )
        assert canceled.status_code == 200 and canceled.json()["status"] == "canceled"
        current = client.get(f"/checkout_sessions/{first.json()['id']}", headers=headers)
    assert current.json()["status"] == "canceled"
    assert post(headers).json() == first.json()
    assert count(run) == 1


@pytest.mark.parametrize("phase", ["before_save", "after_save"])
def test_process_crash_before_commit_leaves_no_partial_creation(episode, isolated_cluster, phase):
    run, headers = episode
    crashed = worker(headers, phase, isolated_cluster)
    assert crashed.returncode == 72
    assert count(run) == 0
    assert post(headers).status_code == 201 and count(run) == 1


def test_committed_creation_with_lost_response_recovers(episode, isolated_cluster):
    run, headers = episode
    lost = worker(headers, "lost_response", isolated_cluster)
    assert lost.returncode == 73 and not lost.stdout.strip()
    assert count(run) == 1
    recovered = worker(headers, "create", isolated_cluster)
    assert recovered.returncode == 0 and json.loads(recovered.stdout)["status"] == 201
    with psycopg.connect(database_url()) as connection:
        original = one(
            connection.execute(
                "SELECT acp_create_response FROM checkout_sessions WHERE run_id=%s", (run,)
            )
        )[0]
    assert json.loads(recovered.stdout)["body"] == original and count(run) == 1


@pytest.mark.parametrize("where", ["response", "store"])
def test_python_exception_after_checkout_insert_rolls_back(episode, monkeypatch, where):
    run, headers = episode

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic failure")

    with monkeypatch.context() as patch:
        patch.setattr(
            ACPCheckoutAdapter, "_response" if where == "response" else "_save_creation", fail
        )
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post("/checkout_sessions", headers=headers, json=BODY)
        assert response.status_code == 500
    assert count(run) == 0
    assert post(headers).status_code == 201 and count(run) == 1


def test_legacy_internal_creation_is_not_silently_adopted(episode):
    run, headers = episode
    context = authenticate_lab_session(headers["Authorization"].split()[1])
    internal = CheckoutService(context).prepare(
        {
            "offer_id": BODY["line_items"][0]["id"],
            "expected_offer_revision": 1,
            "quantity": 1,
            "delivery_context": FIXTURE_DELIVERY_CONTEXT.model_dump(),
            "idempotency_key": KEY,
        }
    )
    assert isinstance(internal, Success)
    response = post(headers)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "creation_unrecoverable"
    assert count(run) == 1


@pytest.mark.parametrize(
    "column", ["acp_create_response", "acp_create_fingerprint", "create_snapshot"]
)
def test_original_creation_is_immutable_in_database(episode, column):
    run, headers = episode
    first = post(headers).json()
    with (
        psycopg.connect(database_url()) as connection,
        pytest.raises(psycopg.errors.RaiseException),
    ):
        connection.execute(
            sql.SQL("UPDATE checkout_sessions SET {}=NULL WHERE run_id=%s").format(
                sql.Identifier(column)
            ),
            (run,),
        )
    assert post(headers).json() == first


def test_existing_legacy_rows_survive_additive_migration(isolated_cluster, monkeypatch):
    # Separate schema in the verified disposable cluster; do not touch existing public data.
    schema = "recovery_upgrade_" + uuid4().hex
    with psycopg.connect(database_url(), autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        monkeypatch.setenv("PGOPTIONS", f"-c search_path={schema}")
        upgrade_start = MIGRATIONS.index("013_acp_creation_recovery.sql")
        with psycopg.connect(database_url()) as connection:
            for migration in MIGRATIONS[:upgrade_start]:
                connection.execute(
                    sql.SQL(
                        cast(
                            LiteralString,
                            (ROOT / "migrations" / migration).read_text(encoding="utf-8"),
                        )
                    )
                )
        run = str(seed(actor_id="upgrade-owner", variant="B2")["run_id"])
        token = issue_lab_session(run, "upgrade-owner")
        # Build a pre-013 row using its SQL contract, not current application
        # code, which correctly requires every registered migration.
        with psycopg.connect(database_url()) as connection:
            offer = Offer.model_validate(
                one(
                    connection.execute(
                        "SELECT snapshot FROM catalog_offers WHERE run_id=%s AND offer_id=%s",
                        (run, BODY["line_items"][0]["id"]),
                    )
                )[0]
            )
            legacy = Checkout(
                id="legacy-upgrade-checkout",
                revision=1,
                status="prepared",
                offer_id=offer.id,
                offer_revision=offer.revision,
                quantity=1,
                pricing=offer.pricing,
                delivery_context=offer.delivery_context,
                delivery_days=offer.delivery_days,
                created_at=offer.observed_at,
                updated_at=offer.observed_at,
                expires_at=offer.expires_at,
            )
            snapshot = legacy.model_dump(mode="json")
            connection.execute(
                "INSERT INTO checkout_sessions "
                "(run_id,checkout_id,actor_id,revision,offer_id,offer_revision,quantity,"
                "idempotency_sha256,request_fingerprint,status,snapshot,create_snapshot,"
                "created_at,updated_at,expires_at) "
                "VALUES (%s,%s,%s,1,%s,%s,1,%s,%s,'prepared',%s,%s,%s,%s,%s)",
                (
                    run,
                    legacy.id,
                    "upgrade-owner",
                    offer.id,
                    offer.revision,
                    hashlib.sha256(KEY.encode()).hexdigest(),
                    "0" * 64,
                    Jsonb(snapshot),
                    Jsonb(snapshot),
                    legacy.created_at,
                    legacy.updated_at,
                    legacy.expires_at,
                ),
            )
            before = one(connection.execute("SELECT create_snapshot FROM checkout_sessions"))[0]
            for migration in MIGRATIONS[upgrade_start:]:
                connection.execute(
                    sql.SQL(
                        cast(
                            LiteralString,
                            (ROOT / "migrations" / migration).read_text(encoding="utf-8"),
                        )
                    )
                )
            row = one(
                connection.execute(
                    "SELECT create_snapshot,acp_create_response FROM checkout_sessions"
                )
            )
        assert row[0] == before and row[1] is None
        response = post(
            {
                "Authorization": f"Bearer {token}",
                "API-Version": "2026-04-17",
                "Idempotency-Key": KEY,
            }
        )
        assert response.status_code == 409 and count(run) == 1
    finally:
        monkeypatch.delenv("PGOPTIONS")
        with psycopg.connect(database_url(), autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def free_port():
    with socket.socket() as stream:
        stream.bind(("127.0.0.1", 0))
        return stream.getsockname()[1]


def start_server(cluster):
    port = free_port()
    process = subprocess.Popen(
        [sys.executable, "-B", str(WORKER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        cwd=ROOT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert process.stdin is not None
    process.stdin.write(json.dumps({"mode": "serve", "cluster": cluster, "port": port}))
    process.stdin.close()
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        if process.poll() is not None:
            raise AssertionError("Isolated HTTP server failed")
        try:
            with httpx.Client(trust_env=False, timeout=0.2) as client:
                if client.get(url + "/health/live").status_code == 200:
                    return process, url
        except httpx.TransportError:
            pass
        sleep(0.05)
    process.terminate()
    process.wait(timeout=5)
    raise AssertionError("Isolated HTTP server readiness timeout")


def test_real_http_service_restart_preserves_original_response(episode, isolated_cluster):
    run, headers = episode
    server, url = start_server(isolated_cluster)
    try:
        with httpx.Client(trust_env=False, timeout=5) as client:
            first = client.post(url + "/checkout_sessions", headers=headers, json=BODY)
        assert first.status_code == 201
    finally:
        server.terminate()
        server.wait(timeout=5)
    mutate(
        run, lambda data: data.update(revision=data["revision"] + 1, name="Changed after restart")
    )
    server, url = start_server(isolated_cluster)
    try:
        with httpx.Client(trust_env=False, timeout=5) as client:
            recovered = client.post(url + "/checkout_sessions", headers=headers, json=BODY)
        assert recovered.status_code == 201 and recovered.content == first.content
    finally:
        server.terminate()
        server.wait(timeout=5)
    assert count(run) == 1
