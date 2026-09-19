from commerce_lab.db.core import fixture_snapshot, migration_sha256


def test_fixture_manifest_is_deterministic_and_complete() -> None:
    first_offers, first_hash, first_manifest = fixture_snapshot()
    second_offers, second_hash, second_manifest = fixture_snapshot()
    assert first_offers == second_offers
    assert first_hash == second_hash
    assert first_manifest == second_manifest
    assert first_manifest["offer_count"] == 10
    assert len(first_hash) == 64
    assert [offer["id"] for offer in first_offers] == [
        "ALT-01",
        "ALT-02",
        "ALT-03",
        "SON-01",
        "SON-02",
        "SON-03",
        "SON-04",
        "SON-05",
        "SON-06",
        "SON-07",
    ]


def test_migration_sha256_normalizes_line_endings_but_detects_content_changes(tmp_path) -> None:
    lf = tmp_path / "lf.sql"
    crlf = tmp_path / "crlf.sql"
    changed = tmp_path / "changed.sql"
    lf.write_text("SELECT 1;\n", encoding="utf-8", newline="")
    crlf.write_bytes(b"SELECT 1;\r\n")
    changed.write_text("SELECT 2;\n", encoding="utf-8", newline="")

    assert migration_sha256(lf) == migration_sha256(crlf)
    assert migration_sha256(lf) != migration_sha256(changed)
    assert len(migration_sha256(lf)) == 64
