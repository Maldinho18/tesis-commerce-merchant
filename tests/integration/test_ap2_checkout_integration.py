import os

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from commerce_lab.ap2_checkout import SHOPPING_AGENT_AUDIENCE, MerchantCheckoutSigner
from commerce_lab.api import ap2_signer, app
from commerce_lab.context import issue_lab_session
from commerce_lab.db import migrate, seed

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_INTEGRATION") != "1",
    reason="requires the local synthetic PostgreSQL service",
)


def test_merchant_signs_the_authoritative_ready_checkout_only_for_its_episode() -> None:
    migrate()
    episode = seed(actor_id="ap2-checkout-owner", variant="B0")
    owner_token = issue_lab_session(str(episode["run_id"]), "ap2-checkout-owner")
    headers = {"Authorization": f"Bearer {owner_token}", "API-Version": "2026-04-17"}
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    signer = MerchantCheckoutSigner(pem, issuer="http://127.0.0.1:4120")
    client = TestClient(app)
    app.dependency_overrides[ap2_signer] = lambda: signer
    try:
        created = client.post(
            "/checkout_sessions",
            headers={**headers, "Idempotency-Key": "ap2-create"},
            json={
                "line_items": [{"id": "SON-01"}],
                "currency": "usd",
                "capabilities": {"payment": {"handlers": []}},
            },
        )
        assert created.status_code == 201, created.text
        checkout_id = created.json()["id"]
        path = f"/checkout_sessions/{checkout_id}/ap2/checkout-jwt"
        assert client.get(path, headers=headers).status_code == 409

        updated = client.post(
            f"/checkout_sessions/{checkout_id}",
            headers={**headers, "Idempotency-Key": "ap2-update"},
            json={
                "buyer": {
                    "email": "buyer.ap2@example.test",
                    "first_name": "Buyer",
                    "last_name": "AP2",
                },
                "fulfillment_details": {
                    "name": "Buyer AP2",
                    "email": "buyer.ap2@example.test",
                    "phone_number": "+573000000000",
                    "address": {
                        "name": "Buyer AP2",
                        "line_one": "Calle 100 # 10-20",
                        "city": "Bogota",
                        "state": "DC",
                        "country": "CO",
                        "postal_code": "110111",
                    },
                },
                "selected_fulfillment_options": [
                    {
                        "type": "shipping",
                        "option_id": f"ship_{checkout_id}",
                        "item_ids": [f"li_{checkout_id}"],
                    }
                ],
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["status"] == "ready_for_payment"

        signed = client.get(path, headers=headers)
        assert signed.status_code == 200, signed.text
        checkout = client.get(f"/checkout_sessions/{checkout_id}", headers=headers)
        public_key = jwt.PyJWK.from_dict(signer.jwk)
        claims = jwt.decode(
            signed.json()["checkout_jwt"],
            public_key.key,
            algorithms=["ES256"],
            issuer="http://127.0.0.1:4120",
            audience=SHOPPING_AGENT_AUDIENCE,
        )
        assert claims["checkout"] == checkout.json()

        other_episode = seed(actor_id="ap2-checkout-other", variant="B0")
        other_token = issue_lab_session(str(other_episode["run_id"]), "ap2-checkout-other")
        foreign = client.get(
            path,
            headers={"Authorization": f"Bearer {other_token}", "API-Version": "2026-04-17"},
        )
        assert foreign.status_code in {403, 404}
    finally:
        app.dependency_overrides.clear()
