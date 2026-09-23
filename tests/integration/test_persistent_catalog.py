import os
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from fastapi.testclient import TestClient

from commerce_lab.api import app
from commerce_lab.context import authenticate_lab_session, issue_lab_session
from commerce_lab.db import database_url, migrate, seed
from commerce_lab.fixtures import FIXTURE_DELIVERY_CONTEXT
from commerce_lab.persistent_catalog import PersistentCatalogReader

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_INTEGRATION") != "1",
    reason="requires the local synthetic PostgreSQL service",
)


def _seed_actor(actor_id: str) -> tuple[str, str]:
    result = seed(actor_id=actor_id, variant="B0")
    run_id = str(result["run_id"])
    return run_id, issue_lab_session(run_id, actor_id)


def test_session_scopes_persistent_reads_and_records_evidence() -> None:
    migrate()
    run_a, token_a = _seed_actor("integration-a")
    run_b, token_b = _seed_actor("integration-b")
    context_a = authenticate_lab_session(token_a)
    context_b = authenticate_lab_session(token_b)

    result_a = PersistentCatalogReader(context_a).search({"category": "smartphones"})
    result_b = PersistentCatalogReader(context_b).get(
        {
            "offer_id": "Q100286751-256GB",
            "delivery_context": FIXTURE_DELIVERY_CONTEXT.model_dump(),
        }
    )
    assert len(result_a.data.offers) == 20
    assert result_b.ok is True

    with psycopg.connect(database_url()) as connection:
        events_a = connection.execute(
            "SELECT event_type, payload FROM run_events WHERE run_id = %s ORDER BY event_id",
            (run_a,),
        ).fetchall()
        events_b = connection.execute(
            "SELECT event_type, payload FROM run_events WHERE run_id = %s ORDER BY event_id",
            (run_b,),
        ).fetchall()
    assert [event[0] for event in events_a][-1] == "catalog.searched"
    assert events_a[-1][1]["actor_id"] == "integration-a"
    assert [event[0] for event in events_b][-1] == "offer.read"
    assert events_b[-1][1]["actor_id"] == "integration-b"


def test_real_http_routes_create_unique_request_contexts_concurrently() -> None:
    migrate()
    _, token = _seed_actor("integration-http")
    client = TestClient(app)

    def search() -> str:
        response = client.post(
            "/lab/catalog/search",
            headers={"Authorization": f"Bearer {token}"},
            json={"category": "smartphones"},
        )
        assert response.status_code == 200
        assert len(response.json()["data"]["offers"]) == 20
        return response.headers["X-Request-Id"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        request_ids = list(pool.map(lambda _: search(), range(4)))
    assert len(set(request_ids)) == 4


def test_unknown_session_fails_closed() -> None:
    migrate()
    response = TestClient(app).post(
        "/lab/catalog/search",
        headers={"Authorization": "Bearer not-a-session"},
        json={"category": "smartphones"},
    )
    assert response.status_code == 401
