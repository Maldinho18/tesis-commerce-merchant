from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Local synthetic merchant configuration."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql://tesis_dev:tesis_local_only@127.0.0.1:55433/tesis_lab"


@lru_cache
def get_settings() -> Settings:
    return Settings()
