from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict

from commerce_lab.settings import get_settings


class PaymentProviderError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class PaymentResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str
    status: Literal["approved", "declined"]
    merchant_id: str
    checkout_session_id: str
    amount: int
    currency: str
    payment_receipt_jwt: str | None = None


def confirm_payment(
    *,
    token: str,
    checkout_id: str,
    amount: int,
    currency: str,
    idempotency_key: str,
) -> Literal["approved", "declined"]:
    settings = get_settings()
    if settings.payment_merchant_bearer_token is None:
        raise PaymentProviderError("unavailable")
    try:
        with httpx.Client(
            base_url=settings.payment_provider_url,
            timeout=5,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = client.post(
                "/payments/confirm",
                headers={
                    "Authorization": (
                        f"Bearer {settings.payment_merchant_bearer_token.get_secret_value()}"
                    ),
                    "Idempotency-Key": idempotency_key,
                },
                json={
                    "token": token,
                    "merchant_id": settings.payment_merchant_id,
                    "checkout_session_id": checkout_id,
                    "amount": amount,
                    "currency": currency,
                },
            )
    except httpx.HTTPError as error:
        raise PaymentProviderError("unavailable") from error
    if response.status_code in {409, 422}:
        raise PaymentProviderError("invalid_token")
    if response.status_code != 200:
        raise PaymentProviderError("unavailable")
    try:
        result = PaymentResult.model_validate(response.json())
    except (ValueError, TypeError) as error:
        raise PaymentProviderError("invalid_response") from error
    if (
        result.merchant_id != settings.payment_merchant_id
        or result.checkout_session_id != checkout_id
        or result.amount != amount
        or result.currency != currency
    ):
        raise PaymentProviderError("invalid_response")
    return result.status
