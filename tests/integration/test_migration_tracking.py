import hashlib
import os

import psycopg
import pytest

from commerce_lab.db import database_url, migrate
from commerce_lab.db.core import MIGRATIONS

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_INTEGRATION") != "1",
    reason="requires the local synthetic PostgreSQL service",
)


def test_fresh_database_tracks_each_migration_once() -> None:
    with psycopg.connect(database_url()) as connection:
        existing = connection.execute("SELECT to_regclass('public.schema_migrations')").fetchone()
    if existing is not None and existing[0] is not None:
        pytest.skip("requires a fresh PostgreSQL volume")

    first = migrate()
    assert first["applied"] == list(MIGRATIONS)
    assert first["already_applied"] == []

    second = migrate()
    assert second["applied"] == []
    assert second["already_applied"] == list(MIGRATIONS)

    with psycopg.connect(database_url()) as connection:
        rows = connection.execute(
            "SELECT version, sha256 FROM schema_migrations ORDER BY version"
        ).fetchall()
    assert [version for version, _ in rows] == sorted(MIGRATIONS)
    assert all(
        len(checksum) == 64 and all(character in "0123456789abcdef" for character in checksum)
        for _, checksum in rows
    )
    for version, checksum in rows:
        with open(f"migrations/{version}", "rb") as migration_file:
            assert checksum == hashlib.sha256(migration_file.read()).hexdigest()
