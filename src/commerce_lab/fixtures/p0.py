"""Deterministic synthetic P0 catalog: one stable variant per product."""

from typing import Final, Literal

from commerce_lab.contracts import DeliveryContext, Offer, Pricing

FIXTURE_NOW: Final = "2026-09-10T14:00:00Z"
FIXTURE_EXPIRES_AT: Final = "2026-09-10T14:15:00Z"
FIXTURE_DELIVERY_CONTEXT: Final = DeliveryContext(country="CO", city="Bogota", postal_code="110111")

type Brand = Literal["Sonora", "Alterna"]
type Color = Literal["black", "white", "blue"]
type Condition = Literal["new", "refurbished"]
type FixtureRow = tuple[str, Brand, Color, Condition, int, int, int, int]

# Item and shipping prices are integer USD cents. Tax is included in the item amount.
_ROWS: tuple[FixtureRow, ...] = (
    ("ALT-01", "Alterna", "black", "new", 60_000, 2_000, 2, 10),
    ("ALT-02", "Alterna", "white", "new", 65_000, 2_500, 4, 6),
    ("ALT-03", "Alterna", "blue", "new", 70_000, 1_500, 5, 3),
    ("SON-01", "Sonora", "black", "new", 72_000, 2_000, 3, 10),
    ("SON-02", "Sonora", "white", "new", 76_000, 2_000, 4, 8),
    ("SON-03", "Sonora", "black", "new", 79_000, 3_000, 3, 1),
    ("SON-04", "Sonora", "black", "refurbished", 64_000, 2_000, 3, 5),
    ("SON-05", "Sonora", "blue", "new", 95_000, 3_000, 3, 4),
    ("SON-06", "Sonora", "white", "new", 69_000, 4_000, 7, 2),
    ("SON-07", "Sonora", "blue", "new", 71_000, 2_000, 3, 0),
)


def _build_offers() -> tuple[Offer, ...]:
    offers: list[Offer] = []
    for offer_id, brand, color, condition, item_minor, shipping_minor, days, quantity in _ROWS:
        offers.append(
            Offer(
                id=offer_id,
                product_id=f"prod-{offer_id.lower()}",
                product_status="active",
                sku=offer_id,
                merchant_id="merchant-sim-01",
                revision=1,
                category="headphones",
                name=f"Audifonos {brand} {offer_id}",
                brand=brand,
                color=color,
                attributes={"color": color},
                condition=condition,
                availability="in_stock" if quantity > 0 else "out_of_stock",
                available_quantity=quantity,
                pricing=Pricing(
                    currency="usd",
                    items_total_minor=item_minor,
                    shipping_total_minor=shipping_minor,
                    total_minor=item_minor + shipping_minor,
                    tax_included=True,
                ),
                delivery_context=FIXTURE_DELIVERY_CONTEXT,
                delivery_days=days,
                observed_at=FIXTURE_NOW,
                expires_at=FIXTURE_EXPIRES_AT,
            )
        )
    return tuple(offers)


P0_OFFERS: Final = _build_offers()


def fresh_p0_offers() -> list[Offer]:
    return [offer.model_copy(deep=True) for offer in P0_OFFERS]
