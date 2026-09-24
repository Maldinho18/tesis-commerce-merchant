import os
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from commerce_lab.api import app
from commerce_lab.context import issue_lab_session
from commerce_lab.db import migrate
from commerce_lab.feed import current_feed
from commerce_lab.managed_catalog import import_current_catalog, managed_catalog_context

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_INTEGRATION") != "1",
    reason="requires the local PostgreSQL service",
)


def test_managed_catalog_import_is_idempotent_and_published() -> None:
    migrate()
    first = import_current_catalog()
    second = import_current_catalog()
    assert first["run_id"] == second["run_id"]
    assert second["status"] == "already_imported"

    metadata, products = current_feed(base_url="https://merchant.example.test")
    assert metadata["id"] == "feed_merchant_catalog"
    assert len(products) >= 80
    for product in products:
        variants = cast(list[dict[str, Any]], product["variants"])
        assert all(variant["price"]["currency"] == "COP" for variant in variants)

    response = TestClient(app).get("/feeds/current")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["metadata"]["id"] == metadata["id"]
    assert len(response.json()["products"]) == len(products)


def test_managed_catalog_checkout_uses_live_clock_and_cop() -> None:
    migrate()
    import_current_catalog()
    context = managed_catalog_context()
    assert context is not None
    token = issue_lab_session(str(context[0]), context[1])
    _, products = current_feed()
    variant = next(
        variant
        for product in products
        for variant in cast(list[dict[str, Any]], product["variants"])
        if variant["availability"]["available"]
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "API-Version": "2026-04-17",
    }
    client = TestClient(app)
    created = client.post(
        "/checkout_sessions",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={
            "line_items": [{"id": variant["id"]}],
            "currency": "cop",
            "capabilities": {"payment": {"handlers": []}},
        },
    )
    assert created.status_code == 201
    assert created.json()["currency"] == "cop"
    canceled = client.post(
        f"/checkout_sessions/{created.json()['id']}/cancel",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={},
    )
    assert canceled.status_code == 200
    assert canceled.json()["status"] == "canceled"
