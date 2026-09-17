from typing import Final, Literal

from commerce_lab.contracts import DeliveryContext, Offer, Pricing, cop_from_decimal

FIXTURE_NOW: Final = "2026-09-10T14:00:00Z"
FIXTURE_EXPIRES_AT: Final = "2026-09-10T14:15:00Z"
FIXTURE_DELIVERY_CONTEXT: Final = DeliveryContext(country="CO", city="Bogota", postal_code="110111")

type Brand = Literal["Sonora", "Alterna"]
type Color = Literal["black", "white"]
type Condition = Literal["new", "refurbished"]
type FixtureRow = tuple[str, Brand, Color, Condition, str, str, int]

_ROWS: tuple[FixtureRow, ...] = (
    ("SON-01", "Sonora", "black", "new", "720000", "20000", 3),
    ("SON-02", "Sonora", "white", "new", "760000", "20000", 4),
    ("SON-03", "Sonora", "black", "new", "790000", "30000", 3),
    ("SON-04", "Sonora", "black", "refurbished", "640000", "20000", 3),
    ("ALT-01", "Alterna", "black", "new", "600000", "20000", 2),
)


def _build_offers() -> tuple[Offer, ...]:
    offers: list[Offer] = []
    for offer_id, brand, color, condition, item_price, shipping_price, days in _ROWS:
        item_minor = cop_from_decimal(item_price).amount_minor
        shipping_minor = cop_from_decimal(shipping_price).amount_minor
        offers.append(
            Offer(
                id=offer_id,
                product_id=offer_id,
                sku=offer_id,
                merchant_id="merchant-sim-01",
                revision=1,
                category="headphones",
                name=f"Audifonos {brand} {offer_id}",
                brand=brand,
                color=color,
                attributes={"color": color},
                condition=condition,
                availability="in_stock",
                available_quantity=10,
                pricing=Pricing(
                    currency="COP",
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


SONORA_OFFERS: Final = _build_offers()


def fresh_sonora_offers() -> list[Offer]:
    """Cada episodio recibe una copia profunda independiente."""

    return [offer.model_copy(deep=True) for offer in SONORA_OFFERS]
