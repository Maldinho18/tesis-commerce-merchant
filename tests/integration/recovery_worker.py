"""Subprocess fault injector and loopback server for isolated recovery tests."""

import json
import os
import sys
from pathlib import Path


def main() -> None:
    from commerce_lab.settings import Settings, get_settings

    Settings.model_config["env_file"] = None
    get_settings.cache_clear()
    data = json.load(sys.stdin)
    import psycopg

    from commerce_lab.db import database_url

    with psycopg.connect(database_url()) as connection:
        row = connection.execute("SHOW data_directory").fetchone()
        assert row is not None
        actual = Path(row[0]).resolve()
        if actual != Path(data["cluster"]).resolve():
            raise RuntimeError("Refuse a non-isolated database")
    from commerce_lab.acp import ACPCheckoutAdapter
    from commerce_lab.api import app

    mode = data["mode"]
    if mode == "serve":
        import uvicorn

        uvicorn.run(app, host="127.0.0.1", port=data["port"], log_level="error", access_log=False)
        return
    original = ACPCheckoutAdapter._save_creation
    if mode in ("before_save", "after_save"):

        def save(self, *args, **kwargs):
            if mode == "after_save":
                original(self, *args, **kwargs)
            os._exit(72)

        ACPCheckoutAdapter._save_creation = save
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        response = client.post("/checkout_sessions", headers=data["headers"], json=data["body"])
    if mode == "lost_response":
        os._exit(73)  # Server committed; parent receives neither response nor checkout ID.
    print(json.dumps({"status": response.status_code, "body": response.json()}))


if __name__ == "__main__":
    main()
