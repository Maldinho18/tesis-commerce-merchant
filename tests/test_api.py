import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from commerce_lab.api import (
    _raise_commerce_failure,
    acp_checkout,
    app,
    persistent_catalog,
    trusted_context,
)
from commerce_lab.catalog import CatalogReader
from commerce_lab.contracts import CommerceError, ExecutionContext, Failure, ScenarioClock
from commerce_lab.db import DatabaseNotReady
from commerce_lab.fixtures import FIXTURE_NOW, fresh_p0_offers


def test_live_reports_process_without_claiming_model_check() -> None:
    response = TestClient(app).get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["model"] == "not_checked_by_this_endpoint"


def test_ready_checks_database_and_migrations(monkeypatch) -> None:
    monkeypatch.setattr("commerce_lab.api.check_database_ready", lambda: None)
    response = TestClient(app).get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "ready",
        "migrations": "applied",
        "model": "not_checked_by_this_endpoint",
    }


def test_ready_fails_closed_when_database_is_unavailable(monkeypatch) -> None:
    def unavailable() -> None:
        raise DatabaseNotReady("synthetic test failure")

    monkeypatch.setattr("commerce_lab.api.check_database_ready", unavailable)
    response = TestClient(app).get("/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["model"] == "not_checked_by_this_endpoint"


def test_lab_catalog_requires_server_resolved_session() -> None:
    response = TestClient(app).post("/lab/catalog/search", json={"category": "headphones"})
    assert response.status_code == 401
    assert "actor_id" not in response.text


def test_lab_catalog_uses_trusted_context_and_rejects_identity_in_body() -> None:
    context = ExecutionContext(
        actor_id="actor-a",
        run_id="00000000-0000-0000-0000-000000000001",
        request_id="00000000-0000-0000-0000-000000000002",
        received_at="2026-09-16T12:00:00Z",
    )
    reader = CatalogReader(fresh_p0_offers(), ScenarioClock(FIXTURE_NOW))
    app.dependency_overrides[trusted_context] = lambda: context
    app.dependency_overrides[persistent_catalog] = lambda: reader
    try:
        client = TestClient(app)
        response = client.post("/lab/catalog/search", json={"category": "headphones"})
        injected = client.post(
            "/lab/catalog/search",
            json={"category": "headphones", "actor_id": "attacker"},
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert len(response.json()["data"]["offers"]) == 10
    assert response.headers["X-Request-Id"] == context.request_id
    assert injected.status_code == 422


@pytest.mark.parametrize(
    ("code", "http_status"),
    [
        ("INVALID_INPUT", 400),
        ("OFFER_NOT_FOUND", 404),
        ("CHECKOUT_NOT_FOUND", 404),
        ("FORBIDDEN", 403),
        ("OUT_OF_STOCK", 409),
        ("OFFER_EXPIRED", 409),
        ("IDEMPOTENCY_IN_FLIGHT", 409),
        ("IDEMPOTENCY_CONFLICT", 422),
    ],
)
def test_acp_http_error_status_preserves_typed_commercial_code(code: str, http_status: int) -> None:
    failure = Failure(error=CommerceError.model_validate({"code": code, "message": "Test failure"}))

    with pytest.raises(HTTPException) as captured:
        _raise_commerce_failure(failure)

    assert captured.value.status_code == http_status
    assert captured.value.detail == {"code": code, "message": "Test failure"}


@pytest.mark.parametrize(
    ("method", "path", "body", "success_status"),
    [
        (
            "POST",
            "/checkout_sessions",
            {
                "line_items": [{"id": "SON-01"}],
                "currency": "usd",
                "capabilities": {"payment": {"handlers": []}},
            },
            201,
        ),
        ("GET", "/checkout_sessions/chk_test", None, 200),
        (
            "POST",
            "/checkout_sessions/chk_test",
            {
                "selected_fulfillment_options": [
                    {"type": "shipping", "option_id": "ship_test", "item_ids": ["li_test"]}
                ]
            },
            200,
        ),
        ("POST", "/checkout_sessions/chk_test/cancel", {}, 200),
    ],
)
def test_every_acp_checkout_endpoint_has_machine_readable_version_errors(
    method: str, path: str, body: dict[str, object] | None, success_status: int
) -> None:
    class StubCheckout:
        calls = 0

        def create(self, payload, idempotency_key):
            self.calls += 1
            return {"id": "chk_test"}

        def get(self, checkout_id):
            self.calls += 1
            return {"id": checkout_id}

        def update(self, checkout_id, payload, idempotency_key):
            self.calls += 1
            return {"id": checkout_id}

        def cancel(self, checkout_id, payload, idempotency_key):
            self.calls += 1
            return {"id": checkout_id}

    checkout = StubCheckout()
    context = ExecutionContext(
        actor_id="version-test",
        run_id="00000000-0000-0000-0000-000000000001",
        request_id="version-request",
        received_at=FIXTURE_NOW,
    )
    app.dependency_overrides[trusted_context] = lambda: context
    app.dependency_overrides[acp_checkout] = lambda: checkout
    try:
        client = TestClient(app)
        headers = {"Idempotency-Key": "version-key"}
        missing = client.request(method, path, headers=headers, json=body)
        unsupported = client.request(
            method, path, headers={**headers, "API-Version": "2025-09-29"}, json=body
        )
        assert checkout.calls == 0
        accepted = client.request(
            method, path, headers={**headers, "API-Version": "2026-04-17"}, json=body
        )
    finally:
        app.dependency_overrides.clear()

    assert missing.status_code == unsupported.status_code == 400
    assert missing.json()["detail"]["code"] == "missing_api_version"
    assert unsupported.json()["detail"]["code"] == "unsupported_api_version"
    assert missing.json()["detail"]["supported_versions"] == ["2026-04-17"]
    assert unsupported.json()["detail"]["supported_versions"] == ["2026-04-17"]
    assert accepted.status_code == success_status
    assert checkout.calls == 1
    anonymous = TestClient(app)
    missing_without_auth = anonymous.request(method, path, json=body)
    assert missing_without_auth.status_code == 400
    assert missing_without_auth.json()["detail"]["code"] == "missing_api_version"
    assert (
        anonymous.request(
            method, path, headers={"API-Version": "2026-04-17"}, json=body
        ).status_code
        == 401
    )
