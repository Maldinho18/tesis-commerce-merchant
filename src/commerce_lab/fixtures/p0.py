"""Catálogo sintético P0: tienda de tecnología con variantes reales por configuración.

Los modelos y las especificaciones son reales; los precios son de referencia del mercado
colombiano y los inventarios son sintéticos. El catálogo es determinista: no se consulta red
ni reloj de pared, de modo que `verify()` puede comparar el snapshot sembrado contra este
fixture byte a byte.

Convención de montos: enteros en centavos de COP (exponente 2 de ISO 4217). Se escriben como
`8_999_000_00` para que se lea "8.999.000 pesos con 00 centavos".
"""

from typing import Final, Literal, NamedTuple

from commerce_lab.contracts import DeliveryContext, Offer, Pricing
from commerce_lab.fixtures.generated import build_generated_offers

FIXTURE_NOW: Final = "2026-09-10T14:00:00Z"
FIXTURE_EXPIRES_AT: Final = "2026-09-10T14:15:00Z"
FIXTURE_DELIVERY_CONTEXT: Final = DeliveryContext(country="CO", city="Bogota", postal_code="110111")

type Condition = Literal["new", "refurbished"]


class Variant(NamedTuple):
    """Una configuración comprable de un producto."""

    sku: str
    # Se concatena al título del producto para formar el título de la variante.
    suffix: str
    attributes: dict[str, str]
    color: str | None
    condition: Condition
    item_minor: int
    shipping_minor: int
    delivery_days: int
    quantity: int


class Product(NamedTuple):
    product_id: str
    title: str
    description: str
    brand: str
    category: str
    variants: tuple[Variant, ...]


# Envío gratis por encima de dos millones; por debajo, tarifa plana sintética.
_FREE: Final = 0
_SHIP_STD: Final = 25_000_00
_SHIP_BULK: Final = 89_000_00

_CATALOG: Final[tuple[Product, ...]] = (
    Product(
        product_id="prod-asus-rog-zephyrus-g16",
        title="ASUS ROG Zephyrus G16 (2025)",
        description=(
            "Portátil gamer de 16 pulgadas con pantalla OLED 2.5K a 240 Hz, chasis de "
            "aleación de magnesio de 1.5 kg y procesador Intel Core Ultra 9 285H. "
            "Disponible en varias configuraciones de memoria, gráficos y almacenamiento."
        ),
        brand="ASUS",
        category="laptops",
        variants=(
            Variant(
                "ASUS-G16-16-5060-1TB",
                "16GB RTX 5060 1TB",
                {
                    "cpu": "Intel Core Ultra 9 285H",
                    "ram": "16 GB",
                    "gpu": "RTX 5060",
                    "storage": "1 TB",
                },
                "gris eclipse",
                "new",
                8_999_000_00,
                _FREE,
                4,
                6,
            ),
            Variant(
                "ASUS-G16-32-5070-1TB",
                "32GB RTX 5070 1TB",
                {
                    "cpu": "Intel Core Ultra 9 285H",
                    "ram": "32 GB",
                    "gpu": "RTX 5070",
                    "storage": "1 TB",
                },
                "gris eclipse",
                "new",
                11_499_000_00,
                _FREE,
                4,
                4,
            ),
            Variant(
                "ASUS-G16-32-5070TI-2TB",
                "32GB RTX 5070 Ti 2TB",
                {
                    "cpu": "Intel Core Ultra 9 285H",
                    "ram": "32 GB",
                    "gpu": "RTX 5070 Ti",
                    "storage": "2 TB",
                },
                "platino",
                "new",
                13_999_000_00,
                _FREE,
                6,
                1,
            ),
            Variant(
                "ASUS-G16-32-5080-2TB",
                "32GB RTX 5080 2TB",
                {
                    "cpu": "Intel Core Ultra 9 285H",
                    "ram": "32 GB",
                    "gpu": "RTX 5080",
                    "storage": "2 TB",
                },
                "platino",
                "new",
                16_999_000_00,
                _FREE,
                8,
                2,
            ),
        ),
    ),
    Product(
        product_id="prod-lenovo-legion-pro-5",
        title='Lenovo Legion Pro 5 Gen 10 (16")',
        description=(
            "Portátil gamer de 16 pulgadas con panel PureSight de 2560x1600 a 240 Hz y "
            "sistema de refrigeración Coldfront Vapor. Procesador Intel Core i9-275HX."
        ),
        brand="Lenovo",
        category="laptops",
        variants=(
            Variant(
                "LEN-LP5-16-5060-1TB",
                "16GB RTX 5060 1TB",
                {
                    "cpu": "Intel Core i9-275HX",
                    "ram": "16 GB",
                    "gpu": "RTX 5060",
                    "storage": "1 TB",
                },
                "gris tormenta",
                "new",
                7_799_000_00,
                _FREE,
                3,
                8,
            ),
            Variant(
                "LEN-LP5-32-5070-1TB",
                "32GB RTX 5070 1TB",
                {
                    "cpu": "Intel Core i9-275HX",
                    "ram": "32 GB",
                    "gpu": "RTX 5070",
                    "storage": "1 TB",
                },
                "gris tormenta",
                "new",
                9_899_000_00,
                _FREE,
                3,
                5,
            ),
            Variant(
                "LEN-LP5-32-5070TI-1TB",
                "32GB RTX 5070 Ti 1TB",
                {
                    "cpu": "Intel Core i9-275HX",
                    "ram": "32 GB",
                    "gpu": "RTX 5070 Ti",
                    "storage": "1 TB",
                },
                "gris tormenta",
                "new",
                11_299_000_00,
                _FREE,
                5,
                3,
            ),
        ),
    ),
    Product(
        product_id="prod-apple-macbook-air-13-m4",
        title='Apple MacBook Air 13" M4',
        description=(
            "Portátil ultraliviano de 1.24 kg con chip Apple M4 de 10 núcleos, pantalla "
            "Liquid Retina de 13.6 pulgadas y hasta 18 horas de autonomía."
        ),
        brand="Apple",
        category="laptops",
        variants=(
            Variant(
                "APL-MBA13-16-256",
                "16GB 256GB",
                {"cpu": "Apple M4", "ram": "16 GB", "storage": "256 GB"},
                "medianoche",
                "new",
                5_499_000_00,
                _FREE,
                3,
                10,
            ),
            Variant(
                "APL-MBA13-16-512",
                "16GB 512GB",
                {"cpu": "Apple M4", "ram": "16 GB", "storage": "512 GB"},
                "medianoche",
                "new",
                6_299_000_00,
                _FREE,
                3,
                7,
            ),
            Variant(
                "APL-MBA13-24-512",
                "24GB 512GB",
                {"cpu": "Apple M4", "ram": "24 GB", "storage": "512 GB"},
                "blanco estelar",
                "new",
                7_499_000_00,
                _FREE,
                5,
                4,
            ),
            Variant(
                "APL-MBA13-16-256-REF",
                "16GB 256GB reacondicionado",
                {"cpu": "Apple M4", "ram": "16 GB", "storage": "256 GB"},
                "medianoche",
                "refurbished",
                4_699_000_00,
                _FREE,
                7,
                2,
            ),
        ),
    ),
    Product(
        product_id="prod-lenovo-thinkpad-x1-carbon",
        title="Lenovo ThinkPad X1 Carbon Gen 13",
        description=(
            "Portátil corporativo de 14 pulgadas y 1.09 kg con chasis de fibra de carbono, "
            "certificación MIL-STD-810H y procesador Intel Core Ultra 7 268V."
        ),
        brand="Lenovo",
        category="laptops",
        variants=(
            Variant(
                "LEN-X1C13-16-512",
                "16GB 512GB",
                {"cpu": "Intel Core Ultra 7 268V", "ram": "16 GB", "storage": "512 GB"},
                "negro",
                "new",
                8_999_000_00,
                _FREE,
                5,
                5,
            ),
            Variant(
                "LEN-X1C13-32-1TB",
                "32GB 1TB",
                {"cpu": "Intel Core Ultra 7 268V", "ram": "32 GB", "storage": "1 TB"},
                "negro",
                "new",
                11_999_000_00,
                _FREE,
                5,
                3,
            ),
        ),
    ),
    Product(
        product_id="prod-sony-wh-1000xm6",
        title="Sony WH-1000XM6",
        description=(
            "Audífonos over-ear inalámbricos con cancelación activa de ruido, procesador "
            "QN3, 30 horas de batería y plegado para transporte."
        ),
        brand="Sony",
        category="headphones",
        variants=(
            Variant(
                "SON-XM6-BLK",
                "negro",
                {"connectivity": "Bluetooth 5.3"},
                "negro",
                "new",
                1_899_000_00,
                _FREE,
                2,
                12,
            ),
            Variant(
                "SON-XM6-PLT",
                "plata",
                {"connectivity": "Bluetooth 5.3"},
                "plata",
                "new",
                1_899_000_00,
                _FREE,
                2,
                6,
            ),
            Variant(
                "SON-XM6-BLU",
                "azul medianoche",
                {"connectivity": "Bluetooth 5.3"},
                "azul medianoche",
                "new",
                1_949_000_00,
                _FREE,
                2,
                0,
            ),
        ),
    ),
    Product(
        product_id="prod-apple-airpods-pro-3",
        title="Apple AirPods Pro 3",
        description=(
            "Audífonos in-ear con cancelación activa de ruido, audio espacial "
            "personalizado, sensor de frecuencia cardiaca y estuche con USB-C."
        ),
        brand="Apple",
        category="headphones",
        variants=(
            Variant(
                "APL-APP3",
                "estándar",
                {"connectivity": "Bluetooth 5.3"},
                "blanco",
                "new",
                1_099_000_00,
                _SHIP_STD,
                2,
                15,
            ),
        ),
    ),
    Product(
        product_id="prod-sennheiser-momentum-4",
        title="Sennheiser Momentum 4 Wireless",
        description=(
            "Audífonos over-ear con 60 horas de batería, cancelación adaptativa de ruido "
            "y transductores de 42 mm."
        ),
        brand="Sennheiser",
        category="headphones",
        variants=(
            Variant(
                "SEN-MOM4-BLK",
                "negro",
                {"connectivity": "Bluetooth 5.2"},
                "negro",
                "new",
                1_249_000_00,
                _SHIP_STD,
                4,
                5,
            ),
            Variant(
                "SEN-MOM4-WHT",
                "blanco",
                {"connectivity": "Bluetooth 5.2"},
                "blanco",
                "new",
                1_249_000_00,
                _SHIP_STD,
                4,
                3,
            ),
        ),
    ),
    Product(
        product_id="prod-lg-ultragear-27gx790a",
        title="LG UltraGear 27GX790A",
        description=(
            "Monitor gamer OLED de 27 pulgadas, 2560x1440 a 480 Hz, 0.03 ms de respuesta "
            "y compatibilidad con NVIDIA G-SYNC."
        ),
        brand="LG",
        category="monitors",
        variants=(
            Variant(
                "LG-27GX790A",
                '27" QHD 480Hz',
                {
                    "size": "27 pulgadas",
                    "resolution": "2560x1440",
                    "refresh_rate": "480 Hz",
                    "panel": "OLED",
                },
                "negro",
                "new",
                4_299_000_00,
                _FREE,
                6,
                4,
            ),
        ),
    ),
    Product(
        product_id="prod-dell-ultrasharp-4k",
        title="Dell UltraSharp 4K USB-C Hub",
        description=(
            "Monitor profesional IPS Black 4K con cobertura 100% sRGB, hub USB-C con "
            "entrega de 140 W y conexión Ethernet integrada."
        ),
        brand="Dell",
        category="monitors",
        variants=(
            Variant(
                "DEL-U2725QE",
                '27" 4K',
                {
                    "size": "27 pulgadas",
                    "resolution": "3840x2160",
                    "refresh_rate": "120 Hz",
                    "panel": "IPS Black",
                },
                "plata",
                "new",
                2_899_000_00,
                _FREE,
                5,
                9,
            ),
            Variant(
                "DEL-U3225QE",
                '32" 4K',
                {
                    "size": "32 pulgadas",
                    "resolution": "3840x2160",
                    "refresh_rate": "120 Hz",
                    "panel": "IPS Black",
                },
                "plata",
                "new",
                3_999_000_00,
                _FREE,
                5,
                5,
            ),
        ),
    ),
    Product(
        product_id="prod-samsung-odyssey-g9",
        title='Samsung Odyssey G9 49"',
        description=(
            "Monitor ultrapanorámico curvo de 49 pulgadas con relación 32:9, resolución "
            "5120x1440 a 240 Hz y curvatura 1000R."
        ),
        brand="Samsung",
        category="monitors",
        variants=(
            Variant(
                "SAM-ODYG9-49",
                '49" DQHD 240Hz',
                {
                    "size": "49 pulgadas",
                    "resolution": "5120x1440",
                    "refresh_rate": "240 Hz",
                    "panel": "QD-OLED",
                },
                "negro",
                "new",
                6_499_000_00,
                _SHIP_BULK,
                8,
                2,
            ),
        ),
    ),
    Product(
        product_id="prod-keychron-q3-max",
        title="Keychron Q3 Max",
        description=(
            "Teclado mecánico inalámbrico de formato TKL con chasis de aluminio, montaje "
            "en junta, conexión 2.4 GHz y switches hot-swappable."
        ),
        brand="Keychron",
        category="keyboards",
        variants=(
            Variant(
                "KEY-Q3MAX-RED",
                "switch rojo",
                {
                    "switch": "Gateron Jupiter Red",
                    "layout": "TKL",
                    "connectivity": "2.4 GHz / Bluetooth",
                },
                "negro carbón",
                "new",
                899_000_00,
                _SHIP_STD,
                7,
                6,
            ),
            Variant(
                "KEY-Q3MAX-BRN",
                "switch café",
                {
                    "switch": "Gateron Jupiter Brown",
                    "layout": "TKL",
                    "connectivity": "2.4 GHz / Bluetooth",
                },
                "negro carbón",
                "new",
                899_000_00,
                _SHIP_STD,
                7,
                4,
            ),
            Variant(
                "KEY-Q3MAX-BAN",
                "switch banana",
                {
                    "switch": "Gateron Jupiter Banana",
                    "layout": "TKL",
                    "connectivity": "2.4 GHz / Bluetooth",
                },
                "plata",
                "new",
                949_000_00,
                _SHIP_STD,
                9,
                1,
            ),
        ),
    ),
    Product(
        product_id="prod-logitech-mx-keys-s",
        title="Logitech MX Keys S",
        description=(
            "Teclado inalámbrico de perfil bajo con retroiluminación adaptativa, "
            "conexión a tres equipos y hasta 10 días de batería con luz encendida."
        ),
        brand="Logitech",
        category="keyboards",
        variants=(
            Variant(
                "LOG-MXKS-GRA",
                "grafito",
                {"layout": "Full size", "connectivity": "Bluetooth / Logi Bolt"},
                "grafito",
                "new",
                549_000_00,
                _SHIP_STD,
                3,
                11,
            ),
            Variant(
                "LOG-MXKS-PAL",
                "gris pálido",
                {"layout": "Full size", "connectivity": "Bluetooth / Logi Bolt"},
                "gris pálido",
                "new",
                549_000_00,
                _SHIP_STD,
                3,
                7,
            ),
        ),
    ),
    Product(
        product_id="prod-samsung-galaxy-s25-ultra",
        title="Samsung Galaxy S25 Ultra",
        description=(
            "Teléfono de 6.9 pulgadas con pantalla Dynamic AMOLED 2X, marco de titanio, "
            "S Pen integrado y cámara principal de 200 MP."
        ),
        brand="Samsung",
        category="smartphones",
        variants=(
            Variant(
                "SAM-S25U-256",
                "256GB",
                {"storage": "256 GB", "ram": "12 GB", "size": "6.9 pulgadas"},
                "negro titanio",
                "new",
                5_899_000_00,
                _FREE,
                2,
                9,
            ),
            Variant(
                "SAM-S25U-512",
                "512GB",
                {"storage": "512 GB", "ram": "12 GB", "size": "6.9 pulgadas"},
                "gris titanio",
                "new",
                6_499_000_00,
                _FREE,
                2,
                6,
            ),
            Variant(
                "SAM-S25U-1TB",
                "1TB",
                {"storage": "1 TB", "ram": "16 GB", "size": "6.9 pulgadas"},
                "azul titanio",
                "new",
                7_299_000_00,
                _FREE,
                4,
                2,
            ),
        ),
    ),
    Product(
        product_id="prod-apple-iphone-17-pro",
        title="Apple iPhone 17 Pro",
        description=(
            "Teléfono de 6.3 pulgadas con chip A19 Pro, chasis de aluminio unibody, "
            "sistema de tres cámaras de 48 MP y pantalla ProMotion de 120 Hz."
        ),
        brand="Apple",
        category="smartphones",
        variants=(
            Variant(
                "APL-IP17P-256",
                "256GB",
                {"storage": "256 GB", "size": "6.3 pulgadas"},
                "azul intenso",
                "new",
                6_499_000_00,
                _FREE,
                2,
                8,
            ),
            Variant(
                "APL-IP17P-512",
                "512GB",
                {"storage": "512 GB", "size": "6.3 pulgadas"},
                "naranja cósmico",
                "new",
                7_499_000_00,
                _FREE,
                2,
                5,
            ),
            Variant(
                "APL-IP17P-1TB",
                "1TB",
                {"storage": "1 TB", "size": "6.3 pulgadas"},
                "plata",
                "new",
                8_499_000_00,
                _FREE,
                5,
                3,
            ),
        ),
    ),
)


def _build_offers() -> tuple[Offer, ...]:
    """Catálogo curado primero, luego el generado desde el snapshot de Wikidata.

    El bloque curado conserva los casos borde que las pruebas usan como anclaje: última
    unidad, agotado y reacondicionado. El generado aporta la escala con productos, marcas
    e imágenes reales.
    """
    offers: list[Offer] = []
    for product in _CATALOG:
        for variant in product.variants:
            offers.append(
                Offer(
                    id=variant.sku,
                    product_id=product.product_id,
                    product_status="active",
                    sku=variant.sku,
                    merchant_id="merchant-sim-01",
                    revision=1,
                    category=product.category,
                    name=f"{product.title} {variant.suffix}",
                    product_title=product.title,
                    product_description=product.description,
                    brand=product.brand,
                    color=variant.color,
                    attributes=dict(variant.attributes),
                    condition=variant.condition,
                    availability="in_stock" if variant.quantity > 0 else "out_of_stock",
                    available_quantity=variant.quantity,
                    pricing=Pricing(
                        currency="cop",
                        items_total_minor=variant.item_minor,
                        shipping_total_minor=variant.shipping_minor,
                        total_minor=variant.item_minor + variant.shipping_minor,
                        tax_included=True,
                    ),
                    delivery_context=FIXTURE_DELIVERY_CONTEXT,
                    delivery_days=variant.delivery_days,
                    observed_at=FIXTURE_NOW,
                    expires_at=FIXTURE_EXPIRES_AT,
                )
            )
    offers.extend(
        build_generated_offers(
            delivery_context=FIXTURE_DELIVERY_CONTEXT,
            observed_at=FIXTURE_NOW,
            expires_at=FIXTURE_EXPIRES_AT,
        )
    )
    return tuple(offers)


P0_OFFERS: Final = _build_offers()


def fresh_p0_offers() -> list[Offer]:
    return [offer.model_copy(deep=True) for offer in P0_OFFERS]
