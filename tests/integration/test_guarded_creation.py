"""Real PostgreSQL conditional transactions; ASGI tests plus real socket delivery loss."""

import hashlib
import json
import os
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Event
from uuid import uuid4

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.types.json import Jsonb

from commerce_lab.acp import ACPCheckoutAdapter
from commerce_lab.api import app
from commerce_lab.checkout import CheckoutService
from commerce_lab.context import authenticate_lab_session, issue_lab_session
from commerce_lab.contracts import Failure, Offer
from commerce_lab.contracts.guarded_creation import GuardedProof, offer_snapshot_sha256
from commerce_lab.db import database_url, migrate, seed
from commerce_lab.guarded_creation import GuardedCreation
from commerce_lab.guarded_creation_api import GUARDED_PATH

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_INTEGRATION") != "1", reason="requires new isolated PostgreSQL"
)


def one(cursor):
    row = cursor.fetchone()
    assert row is not None
    return row


@pytest.fixture(scope="module", autouse=True)
def isolated_cluster():
    expected = os.environ.get("RECOVERY_TEST_CLUSTER")
    if not expected:
        pytest.skip("explicit isolated cluster required")
    with psycopg.connect(database_url()) as db:
        assert Path(one(db.execute("SHOW data_directory"))[0]).resolve() == Path(expected).resolve()
    migrate()


@pytest.fixture
def case():
    actor = "guard-owner-" + uuid4().hex[:8]
    run = str(seed(actor_id=actor, variant="B2")["run_id"])
    token = issue_lab_session(run, actor)
    with psycopg.connect(database_url()) as db:
        offer = Offer.model_validate(
            one(
                db.execute(
                    "SELECT snapshot FROM catalog_offers WHERE run_id=%s ORDER BY offer_id LIMIT 1",
                    (run,),
                )
            )[0]
        )
    value = {
        "schema_version": "merchant-guarded-acp-create/1",
        "acp_request": {
            "line_items": [{"id": offer.id}],
            "currency": "cop",
            "capabilities": {"payment": {"handlers": []}},
        },
        "offer_id": offer.id,
        "expected_offer_revision": offer.revision,
        "offer_snapshot_profile": "merchant-offer-snapshot/1",
        "offer_snapshot_sha256": offer_snapshot_sha256(offer),
    }
    headers = {
        "Authorization": "Bearer " + token,
        "API-Version": "2026-04-17",
        "Idempotency-Key": "guarded-" + uuid4().hex,
    }
    return run, headers, value, offer


def post(case, *, body=None, headers=None):
    with TestClient(app) as client:
        return client.post(GUARDED_PATH, json=body or case[2], headers=headers or case[1])


def effects():
    with psycopg.connect(database_url()) as db:
        return tuple(
            one(db.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))))[0]
            for table in [
                "checkout_sessions",
                "guarded_checkout_creations",
                "orders",
                "checkout_mutations",
                "checkout_completion_attempts",
            ]
        )


def mutate(case, change, *, db=None):
    def edit(connection):
        value = one(
            connection.execute(
                "SELECT snapshot FROM catalog_offers WHERE run_id=%s AND offer_id=%s",
                (case[0], case[3].id),
            )
        )[0]
        change(value)
        Offer.model_validate(value)
        connection.execute(
            "UPDATE catalog_offers SET revision=%s,snapshot=%s WHERE run_id=%s AND offer_id=%s",
            (value["revision"], Jsonb(value), case[0], case[3].id),
        )

    if db is not None:
        edit(db)
    else:
        with psycopg.connect(database_url()) as connection:
            edit(connection)


def test_allowed_original_acp_and_accepted_revision(case):
    before = effects()
    response = post(case)
    assert response.status_code == 201
    result = response.json()
    proof = GuardedProof.model_validate(result["proof"])
    assert result["result"] == "created"
    assert proof.accepted_offer_revision == case[3].revision
    assert proof.accepted_offer_snapshot_sha256 == case[2]["offer_snapshot_sha256"]
    assert proof.creation.run_id == case[0]
    assert (
        proof.creation.original_response["capabilities"]["payment"]["handlers"][0]["id"]
        == "tesis_sandbox"
    )
    after = effects()
    assert after[:2] == (before[0] + 1, before[1] + 1) and after[2:] == before[2:]
    with TestClient(app) as client:
        lookup = client.post(
            "/lab/recovery/checkout-creation/lookup",
            headers=case[1],
            json={
                "schema_version": "merchant-acp-creation-lookup/1",
                "idempotency_key_sha256": proof.creation.idempotency_key_sha256,
            },
        )
    assert lookup.status_code == 200
    assert lookup.json()["original_response"] == proof.creation.original_response
    assert effects() == after


@pytest.mark.parametrize(
    "change",
    [
        "revision",
        "increase",
        "decrease",
        "same_revision_price",
        "inactive",
        "stock",
        "expiry",
        "name",
        "delivery",
    ],
)
def test_changed_since_observation_blocks_without_any_creation(case, change):
    def edit(v):
        if change == "revision":
            v["revision"] += 1
        if change in {"increase", "decrease", "same_revision_price"}:
            delta = -100 if change == "decrease" else 100
            v["pricing"]["items_total_minor"] += delta
            v["pricing"]["total_minor"] += delta
            if change != "same_revision_price":
                v["revision"] += 1
        if change == "inactive":
            v["product_status"] = "inactive"
        if change == "stock":
            v.update(available_quantity=0, availability="out_of_stock")
        if change == "expiry":
            v["observed_at"] = "2026-09-01T00:00:00Z"
            v["expires_at"] = "2026-09-02T00:00:00Z"
        if change == "name":
            v["name"] += " changed"
        if change == "delivery":
            v["delivery_days"] += 1

    mutate(case, edit)
    before = effects()
    response = post(case)
    assert response.status_code == 409
    assert response.json()["code"] in {"offer_revision_mismatch", "offer_snapshot_mismatch"}
    assert effects() == before


@pytest.mark.parametrize(
    "state,code",
    [("inactive", "product_inactive"), ("stock", "out_of_stock"), ("expiry", "offer_expired")],
)
def test_matching_snapshot_is_still_subject_to_current_validity(case, state, code):
    def edit(v):
        if state == "inactive":
            v["product_status"] = "inactive"
        if state == "stock":
            v.update(available_quantity=0, availability="out_of_stock")
        if state == "expiry":
            v["observed_at"] = "2026-09-01T00:00:00Z"
            v["expires_at"] = "2026-09-02T00:00:00Z"

    mutate(case, edit)
    with psycopg.connect(database_url()) as db:
        offer = Offer.model_validate(
            one(
                db.execute(
                    "SELECT snapshot FROM catalog_offers WHERE run_id=%s AND offer_id=%s",
                    (case[0], case[3].id),
                )
            )[0]
        )
    body = {**case[2], "offer_snapshot_sha256": offer_snapshot_sha256(offer)}
    before = effects()
    response = post(case, body=body)
    assert response.status_code == 409 and response.json()["code"] == code
    assert effects() == before


@pytest.mark.parametrize(
    "fault",
    [
        "variant",
        "currency",
        "quantity",
        "run_id",
        "actor_id",
        "revision_type",
        "version",
        "digest",
        "duplicate",
    ],
)
def test_invalid_body_has_no_effects(case, fault):
    body = json.loads(json.dumps(case[2]))
    if fault == "variant":
        body["acp_request"]["line_items"][0]["id"] = "foreign"
    elif fault == "currency":
        body["acp_request"]["currency"] = "usd"
    elif fault == "quantity":
        body["acp_request"]["line_items"][0]["quantity"] = 2
    elif fault in {"run_id", "actor_id"}:
        body[fault] = "spoofed"
    elif fault == "revision_type":
        body["expected_offer_revision"] = "1"
    elif fault == "version":
        body["schema_version"] = "unknown/1"
    elif fault == "digest":
        body["offer_snapshot_sha256"] = "x" * 64
    before = effects()
    if fault == "duplicate":
        raw = json.dumps(body)[:-1] + ',"expected_offer_revision":1}'
        with TestClient(app) as client:
            response = client.post(
                GUARDED_PATH, headers={**case[1], "content-type": "application/json"}, content=raw
            )
    else:
        response = post(case, body=body)
    assert response.status_code == 422 and response.json()["code"] == "invalid_request"
    assert effects() == before


@pytest.mark.parametrize("auth", ["absent", "invalid", "revoked"])
def test_invalid_sessions_no_creation(case, auth):
    headers = dict(case[1])
    if auth == "absent":
        headers.pop("Authorization")
    if auth == "invalid":
        headers["Authorization"] = "Bearer synthetic-invalid"
    if auth == "revoked":
        digest = hashlib.sha256(case[1]["Authorization"].split()[1].encode()).hexdigest()
        with psycopg.connect(database_url()) as db:
            db.execute(
                "UPDATE lab_sessions SET revoked_at=now() WHERE session_sha256=%s", (digest,)
            )
    before = effects()
    response = post(case, headers=headers)
    assert response.status_code == 401 and response.json()["code"] == "unauthenticated"
    assert effects() == before


def test_historical_replay_condition_conflicts_and_public_compatibility(case, monkeypatch):
    first = post(case)
    assert first.status_code == 201
    mutate(case, lambda v: v.update(revision=v["revision"] + 1, product_status="inactive"))
    before = effects()

    def forbidden(*args, **kwargs):
        raise AssertionError("Replay touched catalog")

    monkeypatch.setattr(ACPCheckoutAdapter, "_offer", forbidden)
    replay = post(case)
    assert replay.status_code == 200 and replay.json()["result"] == "replayed"
    assert replay.json()["proof"] == first.json()["proof"]
    changed = {**case[2], "expected_offer_revision": case[3].revision + 1}
    conflict = post(case, body=changed)
    assert conflict.status_code == 409 and conflict.json()["code"] == "idempotency_conflict"
    changed = {**case[2], "offer_snapshot_sha256": "0" * 64}
    assert post(case, body=changed).status_code == 409
    with TestClient(app) as client:
        public = client.post("/checkout_sessions", json=case[2]["acp_request"], headers=case[1])
    assert (
        public.status_code == 201
        and public.json() == first.json()["proof"]["creation"]["original_response"]
    )
    assert effects() == before


def test_public_creation_cannot_be_retroactively_guarded(case):
    with TestClient(app) as client:
        assert (
            client.post(
                "/checkout_sessions", json=case[2]["acp_request"], headers=case[1]
            ).status_code
            == 201
        )
    before = effects()
    response = post(case)
    assert response.status_code == 409 and response.json()["code"] == "guard_history_unavailable"
    assert effects() == before


def test_public_inactive_product_rejected_but_old_replay_survives(case):
    mutate(case, lambda v: v.update(product_status="inactive"))
    before = effects()
    with TestClient(app) as client:
        response = client.post("/checkout_sessions", json=case[2]["acp_request"], headers=case[1])
    assert response.status_code >= 400 and effects() == before


def test_unchanged_offer_becomes_expired_when_episode_clock_advances(case):
    with psycopg.connect(database_url()) as db:
        db.execute(
            "UPDATE experiment_runs SET clock_at=%s WHERE run_id=%s", (case[3].expires_at, case[0])
        )
    before = effects()
    response = post(case)
    assert response.status_code == 409 and response.json()["code"] == "offer_expired"
    assert effects() == before


def test_future_observation_cannot_justify_creation(case):
    def future(v):
        v["observed_at"] = "2027-01-01T00:00:00Z"
        v["expires_at"] = "2027-01-02T00:00:00Z"

    mutate(case, future)
    with psycopg.connect(database_url()) as db:
        offer = Offer.model_validate(
            one(
                db.execute(
                    "SELECT snapshot FROM catalog_offers WHERE run_id=%s AND offer_id=%s",
                    (case[0], case[3].id),
                )
            )[0]
        )
    body = {**case[2], "offer_snapshot_sha256": offer_snapshot_sha256(offer)}
    before = effects()
    response = post(case, body=body)
    assert response.status_code == 409 and response.json()["code"] == "offer_invalid"
    assert effects() == before


@pytest.mark.parametrize("action", ["update", "delete"])
def test_accepted_guard_evidence_cannot_be_modified(case, action):
    first = post(case)
    assert first.status_code == 201
    before = effects()
    with pytest.raises(psycopg.errors.RaiseException), psycopg.connect(database_url()) as db:
        if action == "update":
            db.execute(
                "UPDATE guarded_checkout_creations SET proof=proof WHERE run_id=%s", (case[0],)
            )
        else:
            db.execute("DELETE FROM guarded_checkout_creations WHERE run_id=%s", (case[0],))
    replay = post(case)
    assert replay.status_code == 200 and replay.json()["proof"] == first.json()["proof"]
    assert effects() == before


@pytest.mark.parametrize("phase", ["before_proof", "after_proof"])
def test_proof_failure_rolls_back_checkout_and_acp_pair(case, monkeypatch, phase):
    persist = GuardedCreation._persist

    def fail(*args, **kwargs):
        if phase == "after_proof":
            persist(*args, **kwargs)
        raise OSError("synthetic persistence failure")

    monkeypatch.setattr(GuardedCreation, "_persist", fail)
    before = effects()
    response = post(case)
    assert response.status_code == 503 and effects() == before


@pytest.mark.parametrize("change", ["revision", "digest", "variant", "field_presence"])
def test_existing_key_cannot_accept_any_different_attempt(case, change):
    assert post(case).status_code == 201
    body = json.loads(json.dumps(case[2]))
    if change == "revision":
        body["expected_offer_revision"] += 1
    elif change == "digest":
        body["offer_snapshot_sha256"] = "0" * 64
    elif change == "variant":
        body["offer_id"] = "different-offer"
        body["acp_request"]["line_items"][0]["id"] = "different-offer"
    else:
        body["acp_request"]["capabilities"] = {}
    before = effects()
    response = post(case, body=body)
    assert response.status_code == 409 and response.json()["code"] == "idempotency_conflict"
    assert effects() == before


def test_rejected_attempt_cannot_change_condition_under_same_key(case):
    rejected = {**case[2], "expected_offer_revision": case[3].revision + 1}
    before = effects()
    first = post(case, body=rejected)
    assert first.status_code == 409 and first.json()["code"] == "offer_revision_mismatch"
    different = post(case)
    assert different.status_code == 409 and different.json()["code"] == "idempotency_conflict"
    replay = post(case, body=rejected)
    assert replay.status_code == 409 and replay.json()["historical"] is True
    with TestClient(app) as client:
        public = client.post("/checkout_sessions", json=case[2]["acp_request"], headers=case[1])
    assert public.status_code == 422
    assert public.json()["detail"]["code"] == "idempotency_conflict"
    context = authenticate_lab_session(case[1]["Authorization"].split()[1])
    internal = CheckoutService(context).prepare(
        {
            "offer_id": case[3].id,
            "expected_offer_revision": case[3].revision,
            "quantity": 1,
            "delivery_context": case[3].delivery_context.model_dump(mode="json"),
            "idempotency_key": case[1]["Idempotency-Key"],
        }
    )
    assert isinstance(internal, Failure) and internal.error.code == "IDEMPOTENCY_CONFLICT"
    assert effects() == before


def test_public_and_guarded_creation_share_the_same_serialization(case):
    barrier = threading.Barrier(2)

    def attempt(guarded):
        barrier.wait(timeout=5)
        if guarded:
            return post(case)
        with TestClient(app) as client:
            return client.post("/checkout_sessions", json=case[2]["acp_request"], headers=case[1])

    before = effects()
    with ThreadPoolExecutor(2) as pool:
        private, public = list(pool.map(attempt, [True, False]))
    assert public.status_code == 201 and private.status_code in {201, 409}
    after = effects()
    assert after[0] == before[0] + 1 and after[2:] == before[2:]
    assert after[1] == before[1] + int(private.status_code == 201)
    if private.status_code == 201:
        assert private.json()["proof"]["creation"]["original_response"] == public.json()
    else:
        assert private.json()["code"] == "guard_history_unavailable"


def test_scope_isolation_and_same_key_concurrency(case):
    before = effects()
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda _: post(case), range(2)))
    assert sorted(r.status_code for r in responses) == [200, 201]
    assert responses[0].json()["proof"] == responses[1].json()["proof"]
    after = effects()
    assert after[:2] == (before[0] + 1, before[1] + 1) and after[2:] == before[2:]
    other = str(seed(actor_id="another-owner", variant="B2")["run_id"])
    token = issue_lab_session(other, "another-owner")
    # Make offer identity exist only in the first episode. No FK is violated in the other.
    with psycopg.connect(database_url()) as db:
        db.execute(
            "DELETE FROM catalog_offers WHERE run_id=%s AND offer_id=%s", (other, case[3].id)
        )
    before = effects()
    response = post(case, headers={**case[1], "Authorization": "Bearer " + token})
    assert response.status_code == 409 and response.json()["code"] == "offer_not_found"
    assert effects() == before


def test_catalog_update_commits_before_guard_reads(case):
    with psycopg.connect(database_url()) as db:
        mutate(case, lambda v: v.update(revision=v["revision"] + 1), db=db)
        before = effects()
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(post, case)
            waiting = 0
            # An uncommitted UPDATE holds the offer row; the guarded transaction must wait.
            for _ in range(100):
                with psycopg.connect(database_url()) as observer:
                    waiting = one(
                        observer.execute(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE datname=current_database() AND wait_event_type='Lock'"
                        )
                    )[0]
                if waiting:
                    break
                threading.Event().wait(0.02)
            was_waiting = waiting > 0 and not future.done()
            db.commit()
            response = future.result(timeout=10)
            assert was_waiting
    assert response.status_code == 409 and response.json()["code"] == "offer_revision_mismatch"
    assert effects() == before


def test_guard_holds_offer_until_commit_then_update_can_proceed(case, monkeypatch):
    reached, release = Event(), Event()
    original = GuardedCreation._persist

    def pause(self, *args, **kwargs):
        reached.set()
        assert release.wait(15)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(GuardedCreation, "_persist", pause)
    before = effects()
    with ThreadPoolExecutor(2) as pool:
        creating = pool.submit(post, case)
        assert reached.wait(10)
        changing = pool.submit(mutate, case, lambda v: v.update(revision=v["revision"] + 1))
        try:
            waiting = 0
            for _ in range(100):
                with psycopg.connect(database_url()) as db:
                    waiting = one(
                        db.execute(
                            "SELECT count(*) FROM pg_stat_activity WHERE "
                            "datname=current_database() AND wait_event_type='Lock'"
                        )
                    )[0]
                if waiting:
                    break
                threading.Event().wait(0.02)
            assert waiting > 0 and not changing.done()
        finally:
            release.set()
        response = creating.result(timeout=10)
        changing.result(timeout=10)
    assert response.status_code == 201
    assert response.json()["proof"]["accepted_offer_revision"] == case[3].revision
    after = effects()
    assert after[:2] == (before[0] + 1, before[1] + 1) and after[2:] == before[2:]


@contextmanager
def live_http():
    import uvicorn

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    assert port not in {55432, 55433, 62281, 4120}
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        Event().wait(0.02)
    assert server.started
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(10)
        listener.close()
        assert not thread.is_alive()


def test_real_http_response_lost_after_commit_then_historical_recovery(case):
    with live_http() as origin:
        # Drain the server response then discard it before the caller sees any ID.
        class Discard(httpx.HTTPTransport):
            def handle_request(self, request):
                response = super().handle_request(request)
                response.read()
                response.close()
                raise httpx.ReadError("controlled lost response after actual HTTP response")

        before = effects()
        with (
            httpx.Client(transport=Discard(), trust_env=False, timeout=10) as client,
            pytest.raises(httpx.ReadError),
        ):
            client.post(origin + GUARDED_PATH, json=case[2], headers=case[1])
        after = effects()
        assert after[:2] == (before[0] + 1, before[1] + 1) and after[2:] == before[2:]
        mutate(case, lambda v: v.update(revision=v["revision"] + 1, product_status="inactive"))
        with httpx.Client(trust_env=False, timeout=10) as client:
            replay = client.post(origin + GUARDED_PATH, json=case[2], headers=case[1])
        assert replay.status_code == 200 and replay.json()["result"] == "replayed"
        assert replay.json()["proof"]["accepted_offer_revision"] == case[3].revision
        assert effects() == after
