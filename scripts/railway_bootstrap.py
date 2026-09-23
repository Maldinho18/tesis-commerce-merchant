"""Arranque del merchant en Railway: migra, siembra una sola vez y publica la sesión del comprador.

Es idempotente: reiniciar el contenedor no duplica el catálogo ni las sesiones. El Bearer del
comprador llega por `MERCHANT_AGENT_BEARER_TOKEN` y, igual que en `issue-session`, solo se guarda
su sha256; el valor en claro nunca se persiste ni se imprime.
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import psycopg
from psycopg import sql

from commerce_lab.db import database_url
from commerce_lab.db.core import FIXTURE_VERSION, migrate, seed

SESSION_TTL_DAYS = 365

P0_RUNS = """
SELECT run_id, actor_id FROM experiment_runs
WHERE fixture_version = %s AND variant = 'preparation'
ORDER BY created_at, run_id LIMIT 2
"""


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


def _first_run() -> tuple[Any, str] | None:
    with psycopg.connect(database_url()) as connection:
        rows = connection.execute(P0_RUNS, (FIXTURE_VERSION,)).fetchall()
    return _single_p0_run(rows)


def _single_p0_run(rows: list[tuple[Any, str]]) -> tuple[Any, str] | None:
    if len(rows) > 1:
        raise RuntimeError("Deployment database contains more than one P0 preparation episode")
    return rows[0] if rows else None


def main() -> None:
    _ensure_database()
    print(migrate(), flush=True)

    episode = _first_run()
    if episode is None:
        print(seed(), flush=True)
        episode = _first_run()
    else:
        print({"operation": "seed", "status": "already_seeded"}, flush=True)
    if episode is None:
        raise RuntimeError("El catálogo quedó sin episodio tras sembrar")
    run_id, actor_id = episode

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
            DO UPDATE SET expires_at = EXCLUDED.expires_at, revoked_at = NULL
            """,
            (hashlib.sha256(token.encode("utf-8")).hexdigest(), run_id, actor_id, expires_at),
        )
    print(
        {"operation": "agent-session", "status": "ready", "run_id": str(run_id)},
        flush=True,
    )


if __name__ == "__main__":
    main()
