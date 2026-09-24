import httpx
import pytest
from pydantic import SecretStr

from commerce_lab import payment_client
from commerce_lab.settings import Settings


def _confirm(monkeypatch: pytest.MonkeyPatch, handler: httpx.MockTransport) -> str:
    settings = Settings(
        payment_provider_url="http://127.0.0.1:4130",
        payment_merchant_bearer_token=SecretStr("merchant-payment-token"),
    )
    monkeypatch.setattr(payment_client, "get_settings", lambda: settings)

    class StubClient(httpx.Client):
        def __init__(
            self, *, base_url: str, timeout: float, follow_redirects: bool, trust_env: bool
        ) -> None:
            assert trust_env is False
            super().__init__(
                base_url=base_url,
                timeout=timeout,
                follow_redirects=follow_redirects,
                transport=handler,
            )

    monkeypatch.setattr(payment_client.httpx, "Client", StubClient)
    return payment_client.confirm_payment(
        token="vt_" + "a" * 64,
        checkout_id="cs_1",
        amount=62000,
        currency="cop",
        idempotency_key="complete-1",
    )


def test_merchant_confirms_authoritative_checkout_with_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/payments/confirm"
        assert request.headers["Idempotency-Key"] == "complete-1"
        assert request.headers["Authorization"] == "Bearer merchant-payment-token"
        assert request.read().decode().count("62000") == 1
        return httpx.Response(
            200,
            json={
                "id": "pay_1",
                "status": "approved",
                "merchant_id": "tesis_merchant",
                "checkout_session_id": "cs_1",
                "amount": 62000,
                "currency": "cop",
            },
        )

    assert _confirm(monkeypatch, httpx.MockTransport(handler)) == "approved"


def test_merchant_rejects_mismatched_provider_result(monkeypatch: pytest.MonkeyPatch) -> None:
    response = httpx.Response(
        200,
        json={
            "id": "pay_1",
            "status": "approved",
            "merchant_id": "tesis_merchant",
            "checkout_session_id": "another-checkout",
            "amount": 62000,
            "currency": "cop",
        },
    )
    with pytest.raises(payment_client.PaymentProviderError) as captured:
        _confirm(monkeypatch, httpx.MockTransport(lambda _: response))
    assert captured.value.code == "invalid_response"


def test_merchant_rejects_unknown_provider_token(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(payment_client.PaymentProviderError) as captured:
        _confirm(monkeypatch, httpx.MockTransport(lambda _: httpx.Response(422)))
    assert captured.value.code == "invalid_token"
