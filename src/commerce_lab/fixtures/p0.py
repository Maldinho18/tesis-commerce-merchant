"""Catálogo sintético P0: tienda de teléfonos con productos, marcas e imágenes reales.

Los modelos, las marcas y las fotografías salen de Wikidata y Wikimedia Commons, recolectados
una sola vez y commiteados como snapshot. El surtido replica el de una cadena como Best Buy:
solo teléfonos, y solo de las marcas que esa cadena vende.

Inventario, precios y configuraciones son sintéticos, pero se derivan de un hash estable del
identificador de Wikidata: el catálogo es determinista, no consulta red ni reloj, y `verify()`
puede comparar el snapshot sembrado contra este fixture byte a byte.

Convención de montos: enteros en centavos de COP (exponente 2 de ISO 4217).
"""

from typing import Final

from commerce_lab.contracts import DeliveryContext, Offer
from commerce_lab.fixtures.generated import build_generated_offers

FIXTURE_NOW: Final = "2026-09-10T14:00:00Z"
FIXTURE_EXPIRES_AT: Final = "2026-09-10T14:15:00Z"
FIXTURE_DELIVERY_CONTEXT: Final = DeliveryContext(country="CO", city="Bogota", postal_code="110111")


def _build_offers() -> tuple[Offer, ...]:
    return tuple(
        build_generated_offers(
            delivery_context=FIXTURE_DELIVERY_CONTEXT,
            observed_at=FIXTURE_NOW,
            expires_at=FIXTURE_EXPIRES_AT,
        )
    )


P0_OFFERS: Final = _build_offers()


def fresh_p0_offers() -> list[Offer]:
    return [offer.model_copy(deep=True) for offer in P0_OFFERS]
