from functools import lru_cache
from urllib.parse import urlparse

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Local synthetic merchant configuration."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql://tesis_dev:tesis_local_only@127.0.0.1:55433/tesis_lab"
    acp_api_base_url: str = "http://127.0.0.1:4120"
    webhook_receiver_url: str | None = None
    merchant_webhook_secret: str | None = None
    payment_provider_url: str = "http://127.0.0.1:4130"
    payment_merchant_bearer_token: SecretStr | None = None
    payment_merchant_id: str = "tesis_merchant"

    @field_validator("acp_api_base_url", "payment_provider_url")
    @classmethod
    def validate_acp_api_base_url(cls, value: str) -> str:
        parsed = urlparse(value)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if (
            parsed.scheme not in {"http", "https"}
            or (not local and parsed.scheme != "https")
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError(
                "Service base URL must use HTTPS outside localhost and contain no path"
            )
        return value.rstrip("/")

    @field_validator("webhook_receiver_url")
    @classmethod
    def validate_webhook_receiver_url(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        parsed = urlparse(value)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if (
            parsed.scheme not in {"http", "https"}
            or (not local and parsed.scheme != "https")
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("Webhook receiver URL must use HTTPS outside localhost")
        return value.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
