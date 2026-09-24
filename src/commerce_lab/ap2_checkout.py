import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import jwt
from ap2.sdk.generated.checkout_mandate import CheckoutMandate
from ap2.sdk.sdjwt import common, sd_jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from jwcrypto.common import JWException
from jwcrypto.jwk import JWK
from jwt.utils import base64url_encode

from commerce_lab.settings import get_settings

AP2_VERSION = "0.2"
SHOPPING_AGENT_AUDIENCE = "ap2-shopping-agent"


class MerchantCheckoutSigner:
    def __init__(
        self,
        private_key_pem: str,
        *,
        issuer: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(
            key.curve, ec.SECP256R1
        ):
            raise ValueError("AP2 checkout signing requires an ES256 private key")
        self._key = key
        self._issuer = issuer
        self._clock = clock or (lambda: datetime.now(UTC))
        public = key.public_key()
        digest = hashlib.sha256(
            public.public_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        ).digest()
        self._kid = base64url_encode(digest).decode()
        numbers = public.public_numbers()
        self.jwk = {
            "kty": "EC",
            "crv": "P-256",
            "alg": "ES256",
            "use": "sig",
            "kid": self._kid,
            "x": base64url_encode(numbers.x.to_bytes(32, "big")).decode(),
            "y": base64url_encode(numbers.y.to_bytes(32, "big")).decode(),
        }

    def sign(self, checkout: dict[str, Any], *, revision: int = 0) -> str:
        if checkout.get("status") != "ready_for_payment":
            raise ValueError("Checkout is not ready for approval")
        if not isinstance(checkout.get("id"), str):
            raise ValueError("Checkout has no identifier")
        now = self._clock()
        claims = {
            "iss": self._issuer,
            "aud": SHOPPING_AGENT_AUDIENCE,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "jti": str(uuid4()),
            "checkout": checkout,
            "checkout_revision": revision,
        }
        return jwt.encode(
            claims,
            self._key,
            algorithm="ES256",
            headers={"kid": self._kid, "typ": "JWT"},
        )

    def verify_mandate(
        self,
        token: str,
        *,
        checkout: dict[str, Any],
        trusted_agent_jwk_json: str,
    ) -> tuple[int, str]:
        try:
            trusted_jwk = json.loads(trusted_agent_jwk_json)
            if (
                not isinstance(trusted_jwk, dict)
                or trusted_jwk.get("kty") != "EC"
                or trusted_jwk.get("crv") != "P-256"
                or "d" in trusted_jwk
            ):
                raise ValueError("Trusted agent key must be a public P-256 JWK")
            verified = sd_jwt.verify(token, JWK.from_json(trusted_agent_jwk_json))
            contents = verified["delegate_payload"]
            if not isinstance(contents, list) or len(contents) != 1:
                raise ValueError("Invalid checkout mandate payload")
            mandate = CheckoutMandate.model_validate(contents[0])
            claims = jwt.decode(
                mandate.checkout_jwt,
                self._key.public_key(),
                algorithms=["ES256"],
                issuer=self._issuer,
                audience=SHOPPING_AGENT_AUDIENCE,
                options={
                    "require": ["iss", "aud", "iat", "exp", "jti", "checkout", "checkout_revision"],
                    "verify_exp": checkout.get("status") != "completed",
                },
            )
            now = int(self._clock().timestamp())
            digest = base64url_encode(
                hashlib.sha256(mandate.checkout_jwt.encode("ascii")).digest()
            ).decode()
            revision = claims["checkout_revision"]
            if (
                mandate.iat is None
                or mandate.exp is None
                or mandate.iat > now + 60
                or mandate.exp <= mandate.iat
                or mandate.exp - mandate.iat > 300
                or (mandate.exp <= now and checkout.get("status") != "completed")
                or mandate.checkout_hash != digest
                or (
                    claims["checkout"] != checkout
                    and not (
                        checkout.get("status") == "completed"
                        and claims["checkout"].get("id") == checkout.get("id")
                    )
                )
                or not isinstance(revision, int)
                or isinstance(revision, bool)
                or revision < 0
            ):
                raise ValueError("Mandate does not match current checkout")
            return revision, common.compute_sd_hash(common.parse_token(token))
        except (KeyError, TypeError, ValueError, jwt.PyJWTError, JWException) as error:
            raise ValueError("Invalid AP2 checkout mandate") from error

    def receipt(self, *, reference: str, order_id: str) -> str:
        claims = {
            "status": "Success",
            "iss": self._issuer,
            "iat": int(self._clock().timestamp()),
            "reference": reference,
            "order_id": order_id,
        }
        return jwt.encode(claims, self._key, algorithm="ES256", headers={"kid": self._kid})


def configured_checkout_signer() -> MerchantCheckoutSigner:
    settings = get_settings()
    secret = settings.merchant_ap2_private_key_pem
    if secret is None:
        raise RuntimeError("AP2 checkout signing is not configured")
    return MerchantCheckoutSigner(
        secret.get_secret_value().replace("\\n", "\n"), issuer=settings.acp_api_base_url
    )
