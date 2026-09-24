import pytest

from commerce_lab.settings import Settings, get_settings


@pytest.fixture(autouse=True)
def ignore_developer_dotenv(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
