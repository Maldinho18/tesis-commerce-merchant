from commerce_lab.db.core import fixture_snapshot


def test_fixture_manifest_is_deterministic_and_complete() -> None:
    first_offers, first_hash, first_manifest = fixture_snapshot()
    second_offers, second_hash, second_manifest = fixture_snapshot()
    assert first_offers == second_offers
    assert first_hash == second_hash
    assert first_manifest == second_manifest
    assert first_manifest["offer_count"] == 5
    assert len(first_hash) == 64
    assert [offer["id"] for offer in first_offers] == [
        "ALT-01",
        "SON-01",
        "SON-02",
        "SON-03",
        "SON-04",
    ]
