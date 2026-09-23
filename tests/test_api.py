from dataclasses import asdict
from uuid import UUID

import pytest
from fastapi import HTTPException, Request
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
from commerce_lab.request_observability import (
    RequestObservation,
    classify_checkout_route,
    hash_idempotency_key,
)


@pytest.mark.parametrize(
    ("method", "path", "operation", "checkout_id"),
    [
        ("POST", "/checkout_sessions", "create", None),
        ("GET", "/checkout_sessions/chk_1", "get", "chk_1"),
        ("POST", "/checkout_sessions/chk_1", "update", "chk_1"),
        ("POST", "/checkout_sessions/chk_1/complete", "complete", "chk_1"),
        ("POST", "/checkout_sessions/chk_1/cancel", "cancel", "chk_1"),
    ],
)
def test_checkout_route_classification_is_exact(
    method: str, path: str, operation: str, checkout_id: str | None
) -> None:
    route = classify_checkout_route(method, path)

    assert route is not None
    assert route.operation == operation
    assert route.checkout_id == checkout_id


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/checkout_sessions"),
        ("DELETE", "/checkout_sessions/chk_1"),
        ("GET", "/checkout_sessions/chk_1/complete"),
        ("POST", "/checkout_sessions/chk_1/cancel/extra"),
        ("GET", "/health/live"),
        ("GET", "/orders/ord_1"),
    ],
)
def test_non_checkout_routes_are_not_classified(method: str, path: str) -> None:
    assert classify_checkout_route(method, path) is None


def test_observation_hashes_idempotency_key_and_has_no_sensitive_fields() -> None:
    raw_key = "never-persist-this-key"
    digest = hash_idempotency_key(raw_key)
    observation = RequestObservation(
        request_id="request-1",
        run_id=None,
        actor_id=None,
        operation="create",
        result="error",
        http_status=401,
        latency_ms=0,
        checkout_id=None,
        order_id=None,
        idempotency_sha256=digest,
        error_code=None,
    )

    assert digest == "791aa869c952454630a643982908ffc7231dbfae72564ef1aa49f428fabd31da"
    serialized = str(asdict(observation))
    assert raw_key not in serialized
    assert not {
        "authorization",
        "session",
        "idempotency_key",
        "request_body",
        "response_body",
        "payment_data",
        "token",
        "webhook_secret",
    }.intersection(asdict(observation))


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


def test_invalid_bearer_gets_server_request_id_without_changing_auth_body(monkeypatch) -> None:
    observations: list[RequestObservation] = []
    monkeypatch.setattr("commerce_lab.api.write_request_observation", observations.append)
    response = TestClient(app).post(
        "/checkout_sessions",
        headers={
            "Authorization": "Bearer invalid",
            "API-Version": "2026-04-17",
            "Idempotency-Key": "invalid-bearer",
        },
        json={
            "line_items": [{"id": "SON-01"}],
            "currency": "cop",
            "capabilities": {"payment": {"handlers": []}},
        },
    )

    assert response.status_code == 401
    UUID(response.headers["Request-Id"])
    assert response.json()["detail"] == "A valid synthetic lab session is required."
    assert len(observations) == 1
    observation = observations[0]
    assert observation.request_id == response.headers["Request-Id"]
    assert observation.run_id is observation.actor_id is None
    assert observation.operation == "create"
    assert observation.result == "error"
    assert observation.http_status == 401
    assert observation.idempotency_sha256 == hash_idempotency_key("invalid-bearer")
    assert observation.error_code is None


def test_observation_writer_failure_does_not_change_commercial_response(monkeypatch) -> None:
    def unavailable(_observation: RequestObservation) -> None:
        raise RuntimeError("synthetic writer failure")

    monkeypatch.setattr("commerce_lab.api.write_request_observation", unavailable)
    response = TestClient(app).post(
        "/checkout_sessions",
        headers={
            "Authorization": "Bearer invalid",
            "API-Version": "2026-04-17",
            "Idempotency-Key": "writer-failure",
        },
        json={},
    )

    assert response.status_code == 401
    UUID(response.headers["Request-Id"])
    assert response.json()["detail"] == "A valid synthetic lab session is required."


def test_request_ids_are_unique_and_client_request_id_is_ignored() -> None:
    client = TestClient(app)
    first = client.get("/health/live", headers={"Request-Id": "attacker-controlled"})
    second = client.get("/health/live")

    assert UUID(first.headers["Request-Id"])
    assert UUID(second.headers["Request-Id"])
    assert first.headers["Request-Id"] != second.headers["Request-Id"]
    assert first.headers["Request-Id"] != "attacker-controlled"


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
    assert len(response.json()["data"]["offers"]) == 6
    assert response.headers["X-Request-Id"] == context.request_id
    assert injected.status_code == 422


@pytest.mark.parametrize(
    ("code", "http_status", "public_code"),
    [
        ("INVALID_INPUT", 400, "INVALID_INPUT"),
        ("OFFER_NOT_FOUND", 404, "invalid_item"),
        ("CHECKOUT_NOT_FOUND", 404, "CHECKOUT_NOT_FOUND"),
        ("FORBIDDEN", 403, "FORBIDDEN"),
        ("OUT_OF_STOCK", 409, "out_of_stock"),
        ("OFFER_EXPIRED", 409, "OFFER_EXPIRED"),
        ("PAYMENT_DECLINED", 422, "payment_declined"),
        ("IDEMPOTENCY_IN_FLIGHT", 409, "idempotency_in_flight"),
        ("IDEMPOTENCY_CONFLICT", 422, "idempotency_conflict"),
    ],
)
def test_acp_http_error_status_preserves_typed_commercial_code(
    code: str, http_status: int, public_code: str
) -> None:
    failure = Failure(error=CommerceError.model_validate({"code": code, "message": "Test failure"}))

    with pytest.raises(HTTPException) as captured:
        _raise_commerce_failure(failure)

    assert captured.value.status_code == http_status
    assert captured.value.detail == {"code": public_code, "message": "Test failure"}
    if code == "IDEMPOTENCY_IN_FLIGHT":
        assert captured.value.headers == {"Retry-After": "1"}
    else:
        assert captured.value.headers is None


def test_commerce_failure_exposes_public_error_code_to_observation_state() -> None:
    request = Request({"type": "http", "method": "POST", "path": "/checkout_sessions"})
    failure = Failure(
        error=CommerceError.model_validate({"code": "PAYMENT_DECLINED", "message": "Test failure"})
    )

    with pytest.raises(HTTPException):
        _raise_commerce_failure(failure, request=request)

    assert request.state.observation_error_code == "payment_declined"


def test_raise_commerce_failure_accepts_http_headers() -> None:
    failure = Failure(
        error=CommerceError.model_validate(
            {"code": "IDEMPOTENCY_IN_FLIGHT", "message": "Test failure"}
        )
    )

    with pytest.raises(HTTPException) as captured:
        _raise_commerce_failure(failure, headers={"Retry-After": "1"})

    assert captured.value.headers == {"Retry-After": "1"}


def test_raise_commerce_failure_keeps_request_id_and_adds_retry_after() -> None:
    failure = Failure(
        error=CommerceError.model_validate(
            {"code": "IDEMPOTENCY_IN_FLIGHT", "message": "Test failure"}
        )
    )

    with pytest.raises(HTTPException) as captured:
        _raise_commerce_failure(failure, headers={"Request-Id": "request-1"})

    assert captured.value.status_code == 409
    assert captured.value.detail == {
        "code": "idempotency_in_flight",
        "message": "Test failure",
    }
    assert captured.value.headers == {"Request-Id": "request-1", "Retry-After": "1"}


@pytest.mark.parametrize(
    ("method", "path", "body", "success_status"),
    [
        (
            "POST",
            "/checkout_sessions",
            {
                "line_items": [{"id": "SON-01"}],
                "currency": "cop",
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
        (
            "POST",
            "/checkout_sessions/chk_test/complete",
            {"payment_data": {}},
            200,
        ),
    ],
)
def test_every_acp_checkout_endpoint_has_machine_readable_version_errors(
    method: str,
    path: str,
    body: dict[str, object] | None,
    success_status: int,
    monkeypatch,
) -> None:
    class StubCheckout:
        calls = 0
        last_completion_replayed = False

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

        def complete(self, checkout_id, payload, idempotency_key):
            self.calls += 1
            return {"id": checkout_id, "order": {"id": "ord_test"}}

    checkout = StubCheckout()
    context = ExecutionContext(
        actor_id="version-test",
        run_id="00000000-0000-0000-0000-000000000001",
        request_id="version-request",
        received_at=FIXTURE_NOW,
    )
    app.dependency_overrides[trusted_context] = lambda: context
    app.dependency_overrides[acp_checkout] = lambda: checkout
    observations: list[RequestObservation] = []
    monkeypatch.setattr("commerce_lab.api.write_request_observation", observations.append)
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
    UUID(missing.headers["Request-Id"])
    UUID(unsupported.headers["Request-Id"])
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
    observation = next(
        item
        for item in observations
        if item.request_id == missing_without_auth.headers["Request-Id"]
    )
    assert observation.error_code == "missing_api_version"
    assert observation.run_id is observation.actor_id is None


def test_storefront_catalog_is_public_read_only_and_never_cached(monkeypatch) -> None:
    """La vitrina humana lee sin Bearer; el canal ACP sigue exigiéndolo."""
    metadata = {"id": "feed_p0_tech", "target_country": "CO", "updated_at": "2026-09-10T14:00:00Z"}
    products = [{"id": "prod-x", "title": "X", "variants": [{"id": "X-1", "title": "X 1"}]}]
    monkeypatch.setattr("commerce_lab.api.current_feed", lambda **_: (metadata, products))

    response = TestClient(app).get("/storefront/catalog")

    assert response.status_code == 200
    assert response.json() == {"metadata": metadata, "products": products}
    # El inventario cambia con cada compra del agente: una respuesta cacheada mentiría.
    assert response.headers["Cache-Control"] == "no-store"


def test_storefront_catalog_reports_unavailable_before_the_catalog_is_seeded(monkeypatch) -> None:
    def unseeded(**_: object) -> tuple[dict[str, object], list[dict[str, object]]]:
        raise ValueError("Seed a P0 merchant episode before serving the storefront")

    monkeypatch.setattr("commerce_lab.api.current_feed", unseeded)

    response = TestClient(app).get("/storefront/catalog")

    assert response.status_code == 503
    assert "seed" not in response.text.lower() or "Catalog" in response.text
