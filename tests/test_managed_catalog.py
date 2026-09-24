from datetime import UTC, datetime

import pytest

from commerce_lab.fixtures import fresh_p0_offers
from commerce_lab.managed_catalog import changed_offer


def test_managed_edit_revisions_price_and_inventory() -> None:
    original = fresh_p0_offers()[0]
    now = datetime(2026, 9, 23, 12, tzinfo=UTC)
    edited = changed_offer(original, now, price_minor=123_450_000, stock=0)

    assert edited.id == original.id
    assert edited.revision == original.revision + 1
    assert edited.pricing.items_total_minor == 123_450_000
    assert edited.pricing.total_minor == 123_450_000 + original.pricing.shipping_total_minor
    assert edited.available_quantity == 0
    assert edited.availability == "out_of_stock"
    assert edited.observed_at == "2026-09-23T12:00:00Z"
    assert original.available_quantity != 0 or original.revision != edited.revision


@pytest.mark.parametrize("changes", [{}, {"price_minor": -1}, {"stock": -1}])
def test_managed_edit_rejects_invalid_changes(changes: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        changed_offer(fresh_p0_offers()[0], datetime.now(UTC), **changes)
