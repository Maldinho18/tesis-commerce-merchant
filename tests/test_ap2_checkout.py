import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from ap2.sdk.generated.checkout_mandate import CheckoutMandate
from ap2.sdk.sdjwt import sd_jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from jwcrypto.jwk import JWK
from jwt.utils import base64url_encode
from pydantic import SecretStr

from commerce_lab.ap2_checkout import SHOPPING_AGENT_AUDIENCE, MerchantCheckoutSigner
from commerce_lab.api import acp_checkout, ap2_signer, app, trusted_context
from commerce_lab.contracts import ExecutionContext
from commerce_lab.fixtures import FIXTURE_NOW
from commerce_lab.settings import Settings


def _signer(now: datetime | None = None) -> MerchantCheckoutSigner:
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return MerchantCheckoutSigner(
        pem,
        issuer="https://merchant.example.test",
        clock=lambda: now or datetime(2026, 9, 23, tzinfo=UTC),
    )


def _checkout(*, status: str = "ready_for_payment", amount: int = 74_000) -> dict[str, Any]:
    return {
        "id": "chk_test",
        "status": status,
        "currency": "usd",
        "totals": [{"type": "total", "amount": amount}],
        "line_items": [{"id": "li_1", "item": {"id": "SON-01", "unit_amount": 72_000}}],
        "expires_at": "2026-09-24T00:00:00Z",
    }


def test_signed_checkout_binds_full_snapshot_and_uses_randomized_es256() -> None:
    signer = _signer()
    first = signer.sign(_checkout())
    second = signer.sign(_checkout())
    assert first != second
    jwk = jwt.PyJWK.from_dict(signer.jwk)
    claims = jwt.decode(
        first,
        jwk.key,
        algorithms=["ES256"],
        issuer="https://merchant.example.test",
        audience=SHOPPING_AGENT_AUDIENCE,
        options={"verify_exp": False, "verify_iat": False},
    )
    assert claims["checkout"] == _checkout()
    assert claims["exp"] - claims["iat"] == 300
    assert jwt.get_unverified_header(first)["kid"] == signer.jwk["kid"]

    changed = signer.sign(_checkout(amount=75_000))
    changed_claims = jwt.decode(
        changed,
        jwk.key,
        algorithms=["ES256"],
        audience=SHOPPING_AGENT_AUDIENCE,
        issuer="https://merchant.example.test",
        options={"verify_exp": False, "verify_iat": False},
    )
    assert changed_claims["checkout"]["totals"][0]["amount"] == 75_000
    with pytest.raises(jwt.InvalidSignatureError):
        header, payload, signature = first.split(".")
        jwt.decode(
            f"{header}.{payload}.{('A' if signature[0] != 'A' else 'B')}{signature[1:]}",
            jwk.key,
            algorithms=["ES256"],
            audience=SHOPPING_AGENT_AUDIENCE,
            options={"verify_exp": False, "verify_iat": False},
        )


def test_signer_refuses_non_ready_checkout_and_wrong_key_type() -> None:
    signer = _signer()
    with pytest.raises(ValueError, match="not ready"):
        signer.sign(_checkout(status="not_ready_for_payment"))
    wrong_key = ec.generate_private_key(ec.SECP384R1()).private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    with pytest.raises(ValueError, match="ES256"):
        MerchantCheckoutSigner(wrong_key.decode(), issuer="https://merchant.example.test")


def test_jwks_endpoint_fails_closed_without_signing_key(monkeypatch) -> None:
    monkeypatch.setattr(
        "commerce_lab.ap2_checkout.get_settings",
        lambda: Settings(merchant_ap2_private_key_pem=None),
    )
    response = TestClient(app).get("/.well-known/ap2/jwks.json")
    assert response.status_code == 503
    assert "private" not in response.text.lower()


def test_ap2_checkout_endpoint_requires_existing_acp_authorization_and_version() -> None:
    signer = _signer()

    class StubCheckout:
        def get_with_revision(self, checkout_id: str) -> tuple[dict[str, Any], int]:
            assert checkout_id == "chk_test"
            return _checkout(), 2

    context = ExecutionContext(
        actor_id="buyer-agent",
        run_id="00000000-0000-0000-0000-000000000001",
        request_id="request-test",
        received_at=FIXTURE_NOW,
    )
    path = "/checkout_sessions/chk_test/ap2/checkout-jwt"
    with TestClient(app) as client:
        assert client.get(path, headers={"API-Version": "2026-04-17"}).status_code == 401
        app.dependency_overrides[trusted_context] = lambda: context
        app.dependency_overrides[acp_checkout] = StubCheckout
        app.dependency_overrides[ap2_signer] = lambda: signer
        try:
            assert client.get(path).status_code == 400
            response = client.get(path, headers={"API-Version": "2026-04-17"})
            assert response.status_code == 200, response.text
            assert response.headers["cache-control"] == "no-store"
            assert response.json()["checkout_jwt"]
            jwks = client.get("/.well-known/ap2/jwks.json")
            assert jwks.status_code == 200
            assert jwks.json() == {"keys": [signer.jwk]}
        finally:
            app.dependency_overrides.clear()


def test_checkout_mandate_requires_trusted_signature_and_current_terms() -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    agent_key = JWK.from_pem(pem)
    other_key = JWK.from_pem(
        ec.generate_private_key(ec.SECP256R1()).private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    trusted = json.dumps(json.loads(agent_key.export_public()))
    now = datetime.now(UTC)
    signer = _signer(now)
    checkout = _checkout()
    checkout["expires_at"] = (now + timedelta(minutes=10)).isoformat()
    signed_checkout = signer.sign(checkout, revision=4)
    digest = base64url_encode(hashlib.sha256(signed_checkout.encode()).digest()).decode()
    mandate = CheckoutMandate(
        checkout_jwt=signed_checkout,
        checkout_hash=digest,
        iat=int(now.timestamp()),
        exp=int((now + timedelta(minutes=5)).timestamp()),
    )
    token = sd_jwt.create(mandate, agent_key).sd_jwt_issuance
    revision, reference = signer.verify_mandate(
        token, checkout=checkout, trusted_agent_jwk_json=trusted
    )
    assert revision == 4
    assert reference
    receipt = jwt.decode(
        signer.receipt(reference=reference, order_id="ord_1"),
        jwt.PyJWK.from_dict(signer.jwk).key,
        algorithms=["ES256"],
        issuer="https://merchant.example.test",
        options={"verify_aud": False},
    )
    assert receipt["reference"] == reference
    assert receipt["order_id"] == "ord_1"

    with pytest.raises(ValueError, match="Invalid AP2"):
        signer.verify_mandate(
            sd_jwt.create(mandate, other_key).sd_jwt_issuance,
            checkout=checkout,
            trusted_agent_jwk_json=trusted,
        )
    with pytest.raises(ValueError, match="Invalid AP2"):
        signer.verify_mandate(
            token,
            checkout=checkout,
            trusted_agent_jwk_json=agent_key.export(),
        )
    with pytest.raises(ValueError, match="Invalid AP2"):
        signer.verify_mandate(
            token,
            checkout={**checkout, "totals": [{"type": "total", "amount": 75_000}]},
            trusted_agent_jwk_json=trusted,
        )
    long_lived = CheckoutMandate(
        checkout_jwt=signed_checkout,
        checkout_hash=digest,
        iat=int(now.timestamp()),
        exp=int((now + timedelta(hours=1)).timestamp()),
    )
    with pytest.raises(ValueError, match="Invalid AP2"):
        signer.verify_mandate(
            sd_jwt.create(long_lived, agent_key).sd_jwt_issuance,
            checkout=checkout,
            trusted_agent_jwk_json=trusted,
        )


def test_ap2_completion_blocks_legacy_route_and_requires_current_mandate(monkeypatch) -> None:
    now = datetime.now(UTC)
    signer = _signer(now)
    agent_key = JWK.from_pem(
        ec.generate_private_key(ec.SECP256R1()).private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    checkout_snapshot = _checkout()
    checkout_snapshot["expires_at"] = (now + timedelta(minutes=10)).isoformat()
    trusted_key = agent_key.export_public()
    monkeypatch.setattr(
        "commerce_lab.api.get_settings",
        lambda: Settings(
            merchant_ap2_required=True,
            merchant_ap2_agent_jwk_json=SecretStr(trusted_key),
        ),
    )

    class StubCheckout:
        calls = 0
        revision = 3

        def get_with_revision(self, checkout_id: str) -> tuple[dict[str, Any], int]:
            assert checkout_id == "chk_test"
            return checkout_snapshot, self.revision

        def complete(
            self,
            checkout_id: str,
            payload: dict[str, Any],
            idempotency_key: str,
            *,
            expected_revision: int | None = None,
        ) -> dict[str, Any]:
            assert checkout_id == "chk_test"
            assert payload == {"payment_data": {"test": True}}
            assert idempotency_key == "complete-1"
            assert expected_revision == 3
            self.calls += 1
            return {**checkout_snapshot, "status": "completed", "order": {"id": "ord_1"}}

    checkout_adapter = StubCheckout()
    context = ExecutionContext(
        actor_id="buyer-agent",
        run_id="00000000-0000-0000-0000-000000000001",
        request_id="request-test",
        received_at=FIXTURE_NOW,
    )
    app.dependency_overrides[trusted_context] = lambda: context
    app.dependency_overrides[acp_checkout] = lambda: checkout_adapter
    app.dependency_overrides[ap2_signer] = lambda: signer
    headers = {"API-Version": "2026-04-17", "Idempotency-Key": "complete-1"}
    try:
        with TestClient(app) as client:
            legacy = client.post(
                "/checkout_sessions/chk_test/complete",
                headers=headers,
                json={"payment_data": {"test": True}},
            )
            assert legacy.status_code == 403
            assert checkout_adapter.calls == 0

            signed_checkout = signer.sign(checkout_snapshot, revision=3)
            digest = base64url_encode(hashlib.sha256(signed_checkout.encode()).digest()).decode()
            mandate = CheckoutMandate(
                checkout_jwt=signed_checkout,
                checkout_hash=digest,
                iat=int(now.timestamp()),
                exp=int((now + timedelta(minutes=5)).timestamp()),
            )
            token = sd_jwt.create(mandate, agent_key).sd_jwt_issuance
            body = {"checkout_mandate": token, "payment_data": {"test": True}}
            changed_terms = {**checkout_snapshot, "totals": [{"type": "total", "amount": 75_000}]}
            checkout_snapshot = changed_terms
            rejected = client.post(
                "/checkout_sessions/chk_test/ap2/complete", headers=headers, json=body
            )
            assert rejected.status_code == 422
            assert checkout_adapter.calls == 0

            checkout_snapshot = _checkout()
            checkout_snapshot["expires_at"] = (now + timedelta(minutes=10)).isoformat()
            completed = client.post(
                "/checkout_sessions/chk_test/ap2/complete", headers=headers, json=body
            )
            assert completed.status_code == 200, completed.text
            assert completed.json()["checkout"]["order"]["id"] == "ord_1"
            assert completed.json()["checkout_receipt_jwt"]
            assert checkout_adapter.calls == 1

            checkout_snapshot = {**checkout_snapshot, "status": "completed"}
            checkout_adapter.revision = 4
            replay = client.post(
                "/checkout_sessions/chk_test/ap2/complete", headers=headers, json=body
            )
            assert replay.status_code == 200, replay.text
            checkout_adapter.revision = 5
            rejected_replay = client.post(
                "/checkout_sessions/chk_test/ap2/complete", headers=headers, json=body
            )
            assert rejected_replay.status_code == 422
            assert checkout_adapter.calls == 2
    finally:
        app.dependency_overrides.clear()
