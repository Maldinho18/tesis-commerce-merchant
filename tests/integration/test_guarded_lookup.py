"""Real isolated PostgreSQL; ASGI plus one real TCP recovery without commercial retry."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.types.json import Jsonb
from test_guarded_creation import case as case
from test_guarded_creation import isolated_cluster as isolated_cluster
from test_guarded_creation import live_http, mutate, post

import commerce_lab.api as api
import commerce_lab.guarded_lookup_api as lookup_api
from commerce_lab.acp import ACPCheckoutAdapter
from commerce_lab.checkout import CheckoutService
from commerce_lab.context import authenticate_lab_session, issue_lab_session
from commerce_lab.contracts import Success
from commerce_lab.contracts.guarded_creation import GuardedProof, GuardedRejectionRecord
from commerce_lab.contracts.guarded_lookup import LOOKUP_SCHEMA, GuardProofLookupInput
from commerce_lab.db import database_url, seed
from commerce_lab.guarded_creation import GuardedCreation
from commerce_lab.guarded_creation_api import GUARDED_PATH
from commerce_lab.guarded_lookup import GuardProofLookup
from commerce_lab.guarded_lookup_api import LOOKUP_PATH

pytestmark = pytest.mark.usefixtures("isolated_cluster")


def body(case):
    return {
        "schema_version": LOOKUP_SCHEMA,
        "idempotency_key_sha256": hashlib.sha256(case[1]["Idempotency-Key"].encode()).hexdigest(),
    }


def lookup(case, *, value=None, headers=None, path=LOOKUP_PATH):
    with TestClient(api.app) as client:
        return client.post(
            path,
            json=body(case) if value is None else value,
            headers=case[1] if headers is None else headers,
            follow_redirects=False,
        )


def hashes():
    # Snapshot every public row, including duplicates and nested JSON sequence
    # order. Sort fixed-size digests, rather than aggregating entire JSON tables.
    with psycopg.connect(database_url()) as db:
        tables = db.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        ).fetchall()
        result = {}
        for (name,) in tables:
            rows = sorted(
                bytes(row[0])
                for row in db.execute(
                    sql.SQL("SELECT sha256(convert_to(to_jsonb(t)::text,'UTF8')) FROM {} t").format(
                        sql.Identifier(name)
                    )
                )
            )
            result[name] = hashlib.sha256(
                b"merchant-lookup-table-snapshot/v1\0"
                + str(len(rows)).encode()
                + b"\0"
                + b"".join(rows)
            ).hexdigest()
        return result


def test_table_hash_detects_content_duplicates_and_sequence_order():
    table = sql.Identifier("guard_lookup_hash_probe")
    with psycopg.connect(database_url()) as db:
        db.execute(sql.SQL("CREATE TABLE {} (payload jsonb NOT NULL)").format(table))
    try:
        empty = hashes()["guard_lookup_hash_probe"]
        with psycopg.connect(database_url()) as db:
            db.execute(sql.SQL("INSERT INTO {} VALUES (%s)").format(table), (Jsonb([1, 2]),))
        first = hashes()["guard_lookup_hash_probe"]
        with psycopg.connect(database_url()) as db:
            db.execute(sql.SQL("INSERT INTO {} VALUES (%s)").format(table), (Jsonb([1, 2]),))
        duplicate = hashes()["guard_lookup_hash_probe"]
        with psycopg.connect(database_url()) as db:
            db.execute(sql.SQL("DELETE FROM {}").format(table))
            db.execute(sql.SQL("INSERT INTO {} VALUES (%s)").format(table), (Jsonb([2, 1]),))
        reordered = hashes()["guard_lookup_hash_probe"]
        assert len({empty, first, duplicate, reordered}) == 4
    finally:
        with psycopg.connect(database_url()) as db:
            db.execute(sql.SQL("DROP TABLE {}").format(table))


def assert_readonly(case, *, expected, **kwargs):
    before = hashes()
    response = lookup(case, **kwargs)
    assert response.headers["Cache-Control"] == "no-store"
    assert not response.is_redirect
    assert response.json()["result"] == expected
    assert hashes() == before
    assert case[1]["Idempotency-Key"] not in response.text
    assert case[1]["Authorization"].split()[1] not in response.text
    return response


def no_commerce(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("History lookup attempted a commercial operation")

    for target, names in (
        (GuardedCreation, ("create",)),
        (
            ACPCheckoutAdapter,
            ("create", "create_in_transaction", "get", "update", "cancel", "_offer", "_response"),
        ),
        (
            CheckoutService,
            ("prepare", "prepare_in_transaction", "get", "update", "cancel", "complete"),
        ),
    ):
        for name in names:
            monkeypatch.setattr(target, name, forbidden)


def test_found_exact_proof_without_commerce_or_any_table_write(case, monkeypatch):
    original = post(case).json()["proof"]
    no_commerce(monkeypatch)
    response = assert_readonly(case, expected="found")
    assert response.status_code == 200
    assert response.json()["proof"] == original
    assert response.json()["proof_sha256"] == GuardedProof.model_validate(original).digest()
    assert response.json()["run_id"] == case[0]
    assert response.json()["request_id"] == response.headers["Request-Id"]
    assert LOOKUP_PATH not in api.app.openapi()["paths"]
    with TestClient(api.app) as client:
        discovery = client.get("/.well-known/acp.json")
    assert discovery.status_code == 200 and LOOKUP_PATH not in discovery.text


def test_unknown_has_no_permissions(case):
    response = assert_readonly(case, expected="not_found")
    assert set(response.json()) == {
        "schema_version",
        "result",
        "run_id",
        "actor_id",
        "request_id",
        "idempotency_key_sha256",
    }


def test_rejected_known_and_exact_record(case):
    rejected = {**case[2], "expected_offer_revision": case[3].revision + 1}
    assert post(case, body=rejected).status_code == 409
    response = assert_readonly(case, expected="rejected")
    record = GuardedRejectionRecord.model_validate(response.json()["rejection"])
    assert record.code == "offer_revision_mismatch"
    assert record.digest() == response.json()["rejection_sha256"]


@pytest.mark.parametrize("record_rejection", [False, True])
def test_ordinary_checkout_never_promoted(case, record_rejection):
    with TestClient(api.app) as client:
        assert (
            client.post(
                "/checkout_sessions", json=case[2]["acp_request"], headers=case[1]
            ).status_code
            == 201
        )
    if record_rejection:
        assert post(case).json()["code"] == "guard_history_unavailable"
    assert_readonly(case, expected="unrecoverable")


def test_catalog_and_current_checkout_changes_preserve_history(case):
    proof = post(case).json()["proof"]
    mutate(
        case,
        lambda v: v.update(
            name=v["name"] + " changed", revision=v["revision"] + 1, product_status="inactive"
        ),
    )
    context = authenticate_lab_session(case[1]["Authorization"].split()[1])
    canceled = CheckoutService(context).cancel(
        {"checkout_id": proof["creation"]["checkout_id"], "idempotency_key": "synthetic-cancel"}
    )
    assert isinstance(canceled, Success) and canceled.data.status == "canceled"
    assert assert_readonly(case, expected="found").json()["proof"] == proof


@pytest.mark.parametrize("other", ["run", "actor"])
def test_scoped_without_foreign_history(case, other):
    proof = post(case).json()["proof"]
    actor = proof["creation"]["actor_id"] if other == "run" else "other-lookup-owner"
    run = str(seed(actor_id=actor, variant="B2")["run_id"])
    headers = {**case[1], "Authorization": "Bearer " + issue_lab_session(run, actor)}
    response = assert_readonly(case, expected="not_found", headers=headers)
    assert response.json()["run_id"] == run
    assert proof["creation"]["checkout_id"] not in response.text


@pytest.mark.parametrize("invalid", ["missing", "incorrect", "revoked", "expired"])
def test_sessions_fail_closed(case, invalid):
    assert post(case).status_code == 201
    headers = dict(case[1])
    if invalid == "missing":
        headers.pop("Authorization")
    elif invalid == "incorrect":
        headers["Authorization"] = "Bearer incorrect-synthetic-session"
    else:
        digest = hashlib.sha256(headers["Authorization"].split()[1].encode()).hexdigest()
        with psycopg.connect(database_url()) as db:
            if invalid == "revoked":
                db.execute(
                    "UPDATE lab_sessions SET revoked_at=now() WHERE session_sha256=%s", (digest,)
                )
            else:
                db.execute(
                    "UPDATE lab_sessions SET created_at=now()-interval '1 hour',"
                    "expires_at=now()-interval '1 second' WHERE session_sha256=%s",
                    (digest,),
                )
    assert assert_readonly(case, expected="error", headers=headers).status_code == 401


def test_renewal_preserves_scope_and_client_request_id_has_no_authority(case):
    proof = post(case).json()["proof"]
    token = issue_lab_session(case[0], proof["creation"]["actor_id"])
    response = assert_readonly(
        case,
        expected="found",
        headers={
            **case[1],
            "Authorization": "Bearer " + token,
            "Request-Id": "client-correlation-only",
        },
    )
    assert response.json()["proof"] == proof
    assert response.json()["request_id"] != "client-correlation-only"


@pytest.mark.parametrize(
    "change",
    [
        {"idempotency_key_sha256": "A" * 64},
        {"idempotency_key_sha256": "x"},
        {"idempotency_key_sha256": 1},
        {"schema_version": "future"},
        {"run_id": "chosen"},
        {"actor_id": "chosen"},
        {"checkout_id": "chosen"},
        {"bearer": "synthetic"},
        {"idempotency_key": "synthetic"},
    ],
)
def test_bad_input_no_effects(case, change):
    assert (
        assert_readonly(case, expected="error", value={**body(case), **change}).status_code == 422
    )


@pytest.mark.parametrize(
    "raw",
    [
        b"{",
        b"[]",
        b"null",
        b'{"a":NaN}',
        b'{"schema_version":"one","schema_version":"two"}',
        b" " * 2049,
    ],
)
def test_bad_json_and_size(case, raw):
    before = hashes()
    with TestClient(api.app) as client:
        response = client.post(
            LOOKUP_PATH, content=raw, headers={**case[1], "Content-Type": "application/json"}
        )
    assert response.status_code == 422 and response.json()["result"] == "error"
    assert response.headers["Cache-Control"] == "no-store" and hashes() == before


def test_query_and_api_version(case):
    assert (
        assert_readonly(case, expected="error", path=LOOKUP_PATH + "?digest=forbidden").status_code
        == 422
    )
    assert (
        assert_readonly(
            case, expected="error", headers={**case[1], "API-Version": "future"}
        ).status_code
        == 400
    )


def test_no_redirects_for_trailing_slash_or_other_methods(case):
    response = assert_readonly(case, expected="error", path=LOOKUP_PATH + "/")
    assert response.status_code == 422 and "Location" not in response.headers
    with TestClient(api.app) as client:
        for path in (LOOKUP_PATH, LOOKUP_PATH + "/"):
            response = client.get(path, headers=case[1], follow_redirects=False)
            assert response.status_code == 405 and "Location" not in response.headers
            assert response.headers["Cache-Control"] == "no-store"
            assert response.json()["code"] == "invalid_request"


@contextmanager
def unprotected(table):
    with psycopg.connect(database_url()) as db:
        db.execute(sql.SQL("ALTER TABLE {} DISABLE TRIGGER USER").format(sql.Identifier(table)))
        try:
            yield db
        finally:
            db.execute(sql.SQL("ALTER TABLE {} ENABLE TRIGGER USER").format(sql.Identifier(table)))


@pytest.mark.parametrize(
    "damage",
    [
        "digest",
        "guard",
        "revision",
        "offer_digest",
        "acp_fingerprint",
        "response",
        "snapshot",
        "checkout_response",
    ],
)
def test_corrupt_accepted_is_error_without_writes(case, damage):
    proof = post(case).json()["proof"]
    digest = body(case)["idempotency_key_sha256"]
    if damage in {"snapshot", "checkout_response"}:
        with unprotected("checkout_sessions") as db:
            if damage == "snapshot":
                db.execute(
                    "UPDATE checkout_sessions SET create_snapshot=jsonb_set(create_snapshot,"
                    "'{offer_revision}','999'::jsonb) WHERE run_id=%s",
                    (case[0],),
                )
            else:
                changed = proof["creation"]["original_response"]
                changed["status"] = "canceled"
                db.execute(
                    "UPDATE checkout_sessions SET acp_create_response=%s WHERE run_id=%s",
                    (Jsonb(changed), case[0]),
                )
    else:
        if damage == "guard":
            proof["guard_fingerprint"] = "0" * 64
        elif damage == "revision":
            proof["accepted_offer_revision"] += 1
        elif damage == "offer_digest":
            proof["accepted_offer_snapshot_sha256"] = "0" * 64
        elif damage == "acp_fingerprint":
            proof["creation"]["acp_create_fingerprint"] = "0" * 64
        elif damage == "response":
            proof["creation"]["original_response"]["status"] = "canceled"
        # Canonical digest recomputed to exercise cross-record bindings, not only hash rejection.
        from commerce_lab.contracts.creation_lookup import canonical_original_response

        encoded = hashlib.sha256(
            b"merchant-guarded-acp-proof/v1\0" + canonical_original_response(proof)
        ).hexdigest()
        with unprotected("guarded_checkout_creations") as db:
            db.execute(
                "UPDATE guarded_checkout_creations SET proof=%s,proof_sha256=%s,"
                "guard_fingerprint=%s "
                "WHERE run_id=%s AND idempotency_sha256=%s",
                (
                    Jsonb(proof),
                    "0" * 64 if damage == "digest" else encoded,
                    proof["guard_fingerprint"],
                    case[0],
                    digest,
                ),
            )
    response = assert_readonly(case, expected="error")
    assert response.status_code == 500 and response.json()["code"] == "history_invalid"


def test_corrupt_rejection_is_not_not_found(case):
    assert post(case, body={**case[2], "expected_offer_revision": 999}).status_code == 409
    with unprotected("rejected_guarded_checkout_attempts") as db:
        db.execute(
            "UPDATE rejected_guarded_checkout_attempts SET record_sha256=%s WHERE run_id=%s",
            ("0" * 64, case[0]),
        )
    assert assert_readonly(case, expected="error").status_code == 500


def test_contradictory_accepted_and_rejected_fails_closed(case):
    proof = post(case).json()["proof"]
    record = GuardedRejectionRecord(
        run_id=case[0],
        actor_id=proof["creation"]["actor_id"],
        idempotency_sha256=body(case)["idempotency_key_sha256"],
        guard_fingerprint=proof["guard_fingerprint"],
        code="offer_invalid",
    )
    with unprotected("rejected_guarded_checkout_attempts") as db:
        db.execute(
            "INSERT INTO rejected_guarded_checkout_attempts "
            "(run_id,actor_id,idempotency_sha256,guard_fingerprint,record,record_sha256) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (
                case[0],
                record.actor_id,
                record.idempotency_sha256,
                record.guard_fingerprint,
                Jsonb(record.model_dump()),
                record.digest(),
            ),
        )
    assert assert_readonly(case, expected="error").status_code == 500


def test_concurrent_lookups_same_history_no_mutations(case):
    proof = post(case).json()["proof"]
    before = hashes()
    with ThreadPoolExecutor(4) as pool:
        responses = list(pool.map(lambda _: lookup(case), range(8)))
    assert all(r.status_code == 200 and r.json()["proof"] == proof for r in responses)
    assert hashes() == before


def test_database_down_is_sanitized_not_not_found(case, monkeypatch):
    before = hashes()
    with monkeypatch.context() as patch:

        def down(*args, **kwargs):
            raise psycopg.OperationalError("synthetic-private-SQL-token")

        patch.setattr(psycopg, "connect", down)
        response = lookup(case)
    assert response.status_code == 503 and response.json()["code"] == "lookup_unavailable"
    assert "synthetic-private" not in response.text and hashes() == before


def test_response_bound(case, monkeypatch):
    assert post(case).status_code == 201
    monkeypatch.setattr(lookup_api, "MAX_RESPONSE_BYTES", 128)
    response = assert_readonly(case, expected="error")
    assert response.status_code == 503 and response.json()["code"] == "response_too_large"


def test_actual_read_only_transaction_and_write_rejected(case, monkeypatch):
    assert post(case).status_code == 201
    context = authenticate_lab_session(case[1]["Authorization"].split()[1])
    connect = psycopg.connect
    observed = []

    class Probe:
        def __init__(self, connection):
            self.connection = connection

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def cursor(self, *args, **kwargs):
            cursor = self.connection.cursor(*args, **kwargs)
            probe = self

            class CursorProbe:
                def __enter__(self):
                    cursor.__enter__()
                    return self

                def __exit__(self, *args):
                    return cursor.__exit__(*args)

                def execute(self, query, params=None):
                    return probe.execute(query, params, cursor=cursor)

            return CursorProbe()

        def execute(self, query, params=None, *, cursor=None):
            text = str(query)
            if text.startswith("SELECT run_id::text"):
                assert self.connection.execute("SHOW transaction_read_only").fetchone()[0] == "on"
                assert (
                    self.connection.execute("SHOW transaction_isolation").fetchone()[0]
                    == "repeatable read"
                )
                assert "FOR UPDATE" not in text and "FOR SHARE" not in text
                observed.append(True)
                if len(observed) == 1:
                    with (
                        pytest.raises(psycopg.errors.ReadOnlySqlTransaction),
                        self.connection.transaction(),
                    ):
                        self.connection.execute(
                            "UPDATE guarded_checkout_creations "
                            "SET proof_sha256=proof_sha256 WHERE false"
                        )
            return (cursor or self.connection).execute(query, params)

    @contextmanager
    def wrapped(*args, **kwargs):
        with connect(*args, **kwargs) as db:
            yield Probe(db)

    before = hashes()
    with monkeypatch.context() as patch:
        patch.setattr(psycopg, "connect", wrapped)
        result = GuardProofLookup(context).lookup(GuardProofLookupInput.model_validate(body(case)))
    assert result.result == "found" and observed == [True, True, True]
    assert hashes() == before


def test_real_tcp_lost_create_response_recovery_only_lookup(case, monkeypatch):
    with live_http() as origin:

        class Discard(httpx.HTTPTransport):
            def handle_request(self, request):
                response = super().handle_request(request)
                assert response.status_code == 201
                response.read()
                response.close()
                raise httpx.ReadError("controlled loss after real commit and response")

        with (
            httpx.Client(transport=Discard(), trust_env=False, timeout=10) as client,
            pytest.raises(httpx.ReadError),
        ):
            client.post(origin + GUARDED_PATH, json=case[2], headers=case[1])
        before = hashes()
        no_commerce(monkeypatch)
        with httpx.Client(trust_env=False, timeout=10, follow_redirects=False) as client:
            response = client.post(origin + LOOKUP_PATH, json=body(case), headers=case[1])
        assert response.status_code == 200 and response.json()["result"] == "found"
        assert hashes() == before
