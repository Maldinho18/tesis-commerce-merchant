import json
import os

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from commerce_lab.api import app
from commerce_lab.context import issue_lab_session
from commerce_lab.contracts import Offer
from commerce_lab.db import database_url, migrate, seed
from commerce_lab.feed import export_feed

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_INTEGRATION") != "1",
    reason="requires the local synthetic PostgreSQL service",
)


def _episode(actor_id: str) -> tuple[str, dict[str, str]]:
    migrate()
    run_id = str(seed(actor_id=actor_id, variant="B0")["run_id"])
    token = issue_lab_session(run_id, actor_id)
    return run_id, {"Authorization": f"Bearer {token}", "API-Version": "2026-04-17"}


def _create(client: TestClient, headers: dict[str, str], variant_id: str, key: str):
    return client.post(
        "/checkout_sessions",
        headers={**headers, "Idempotency-Key": key},
        json={
            "currency": "cop",
            "line_items": [{"id": variant_id}],
            "capabilities": {"payment": {"handlers": []}},
        },
    )


def test_feed_variant_checkout_reprices_from_current_merchant_snapshot(tmp_path) -> None:
    run_id, headers = _episode("p0-authority")
    export_feed(tmp_path, run_id=run_id)
    products = [
        json.loads(line)
        for line in (tmp_path / "products.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    published = next(
        product["variants"][0]
        for product in products
        if product["variants"][0]["id"] == "Q100286751-256GB"
    )
    assert published["price"] == {"amount": 1_310_000_00, "currency": "COP"}

    with psycopg.connect(database_url()) as connection, connection.transaction():
        row = connection.execute(
            "SELECT snapshot FROM catalog_offers WHERE run_id = %s AND offer_id = %s",
            (run_id, published["id"]),
        ).fetchone()
        assert row is not None
        changed = dict(row[0])
        changed["revision"] = 2
        changed["pricing"] = {
            **changed["pricing"],
            "items_total_minor": 1_299_000_00,
            "total_minor": 1_324_000_00,
        }
        Offer.model_validate(changed)
        connection.execute(
            """UPDATE catalog_offers SET revision = %s, snapshot = %s
               WHERE run_id = %s AND offer_id = %s""",
            (2, Jsonb(changed), run_id, published["id"]),
        )

    client = TestClient(app)
    created = _create(client, headers, published["id"], "p0-repriced")
    assert created.status_code == 201
    body = created.json()
    assert body["currency"] == "cop"
    assert body["line_items"][0]["item"]["id"] == published["id"]
    assert body["line_items"][0]["item"]["unit_amount"] == 1_299_000_00
    assert (
        next(total for total in body["totals"] if total["type"] == "total")["amount"]
        == 1_324_000_00
    )
    assert "order" not in body
    assert body["capabilities"]["payment"]["handlers"][0]["id"] == "tesis_sandbox"

    checkout_id = body["id"]
    fetched = client.get(f"/checkout_sessions/{checkout_id}", headers=headers)
    assert fetched.status_code == 200 and fetched.json() == body
    line_id = body["line_items"][0]["id"]
    shipping_id = body["fulfillment_options"][0]["id"]
    updated = client.post(
        f"/checkout_sessions/{checkout_id}",
        headers={**headers, "Idempotency-Key": "p0-update"},
        json={
            "selected_fulfillment_options": [
                {"type": "shipping", "option_id": shipping_id, "item_ids": [line_id]}
            ]
        },
    )
    assert updated.status_code == 200
    canceled = client.post(
        f"/checkout_sessions/{checkout_id}/cancel",
        headers={**headers, "Idempotency-Key": "p0-cancel"},
        json={},
    )
    assert canceled.status_code == 200 and canceled.json()["status"] == "canceled"


def test_low_stock_allows_checkout_without_decrement_and_zero_stock_rejects(tmp_path) -> None:
    run_id, headers = _episode("p0-stock")
    export_feed(tmp_path, run_id=run_id)
    variants = {
        variant["id"]: variant
        for product in (
            json.loads(line)
            for line in (tmp_path / "products.jsonl").read_text(encoding="utf-8").splitlines()
        )
        for variant in product["variants"]
    }
    assert variants["Q106629718-128GB"]["availability"]["status"] == "limited_stock"
    assert variants["Q108044294-512GB"]["availability"]["status"] == "out_of_stock"
    client = TestClient(app)
    low_stock = _create(client, headers, "Q106629718-128GB", "p0-last-unit")
    out = _create(client, headers, "Q108044294-512GB", "p0-empty")
    missing = _create(client, headers, "MISSING-01", "p0-missing")
    assert low_stock.status_code == 201
    assert out.status_code == 409 and out.json()["detail"]["code"] == "out_of_stock"
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "invalid_item"
    with psycopg.connect(database_url()) as connection:
        stored = connection.execute(
            "SELECT snapshot ->> 'available_quantity' FROM catalog_offers "
            "WHERE run_id = %s AND offer_id = %s",
            (run_id, "Q106629718-128GB"),
        ).fetchone()
    assert stored == ("1",)
