import hashlib
import os
from pathlib import Path

import psycopg
import pytest

from commerce_lab.db import database_url, migrate
from commerce_lab.db.core import MIGRATIONS, migration_sha256

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
        content = Path("migrations", version).read_text(encoding="utf-8")
        canonical = content.replace("\r\n", "\n").replace("\r", "\n")
        assert checksum == hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_migration_checksum_normalizes_only_line_endings(tmp_path: Path) -> None:
    content = "CREATE TABLE example (id integer);\n-- original\n"
    expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
    migration = tmp_path / "synthetic.sql"
    for newline in ("\n", "\r\n", "\r"):
        migration.write_bytes(content.replace("\n", newline).encode("utf-8"))
        assert migration_sha256(migration) == expected
    migration.write_bytes(content.replace("integer", "text").encode("utf-8"))
    assert migration_sha256(migration) != expected
