"""Prepare the merchant database and bind its agent credential to the managed catalog.

The curated assortment is imported only when the store is empty. Restarts never reset edits to
price or inventory. Only a hash of the agent's Bearer credential is stored.
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import psycopg
from psycopg import sql

from commerce_lab.db import database_url
from commerce_lab.db.core import migrate
from commerce_lab.managed_catalog import import_current_catalog, managed_catalog_context

SESSION_TTL_DAYS = 365


def _ensure_database() -> None:
    """Crea `tesis_lab` cuando la base gestionada arranca con otra por defecto."""
    admin_url = os.environ.get("BOOTSTRAP_ADMIN_DATABASE_URL")
    if not admin_url:
        return
    target = urlparse(database_url()).path.lstrip("/")
    with psycopg.connect(admin_url, autocommit=True) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (target,)
        ).fetchone()
        if exists is not None:
            return
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target)))
    print({"operation": "create-database", "database": target}, flush=True)


def main() -> None:
    _ensure_database()
    print(migrate(), flush=True)
    print({"operation": "catalog-import", **import_current_catalog()}, flush=True)
    catalog = managed_catalog_context()
    if catalog is None:
        raise RuntimeError("Merchant catalog is unavailable")
    run_id, actor_id = catalog

    token = os.environ.get("MERCHANT_AGENT_BEARER_TOKEN")
    if not token:
        print({"operation": "agent-session", "status": "skipped"}, flush=True)
        return

    expires_at = datetime.now(UTC) + timedelta(days=SESSION_TTL_DAYS)
    with psycopg.connect(database_url()) as connection, connection.transaction():
        connection.execute(
            """
            INSERT INTO lab_sessions (session_sha256, run_id, actor_id, expires_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (session_sha256)
            DO UPDATE SET
                run_id = EXCLUDED.run_id,
                actor_id = EXCLUDED.actor_id,
                expires_at = EXCLUDED.expires_at,
                revoked_at = NULL
            """,
            (hashlib.sha256(token.encode("utf-8")).hexdigest(), run_id, actor_id, expires_at),
        )
    print(
        {"operation": "agent-session", "status": "ready", "run_id": str(run_id)},
        flush=True,
    )


if __name__ == "__main__":
    main()
