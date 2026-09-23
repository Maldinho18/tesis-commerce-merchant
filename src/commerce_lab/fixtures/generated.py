"""Expande el snapshot de Wikidata a ofertas comprables, de forma determinista.

El snapshot trae producto, marca e imagen reales. Inventario, precio y configuraciones son
sintéticos, pero se derivan de un hash estable del identificador de Wikidata: la misma entrada
produce siempre la misma salida, sin red ni reloj, que es lo que permite que `verify()` compare
el catálogo sembrado contra este fixture.
"""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

from commerce_lab.contracts import DeliveryContext, Offer, Pricing

SNAPSHOT_PATH: Final = Path(__file__).with_name("catalog_snapshot.json")

_STORAGE: Final[dict[str, tuple[str, ...]]] = {
    "smartphones": ("128 GB", "256 GB", "512 GB"),
    "tablets": ("64 GB", "128 GB", "256 GB"),
    "laptops": ("512 GB", "1 TB", "2 TB"),
}
_RAM: Final[tuple[str, ...]] = ("8 GB", "16 GB", "32 GB")
_COLORS: Final[tuple[str, ...]] = ("negro", "plata", "azul", "blanco", "grafito")
_SHIP_STD: Final = 25_000_00


def _digits(entity: str) -> list[int]:
    """Doce enteros estables por producto; toda variación sintética sale de aquí."""
    raw = hashlib.sha256(entity.encode("utf-8")).digest()
    return list(raw[:12])


# Precio de referencia del mercado colombiano por gama, en centavos de COP. El snapshot solo
# trae productos vigentes, así que estos rangos corresponden a equipos que hoy se venden.
_TIER_RANGE: Final[dict[str, tuple[int, int]]] = {
    "flagship": (4_499_000_00, 8_299_000_00),
    "mid": (1_249_000_00, 2_699_000_00),
    "entry": (499_000_00, 1_149_000_00),
    "laptop": (2_499_000_00, 6_999_000_00),
    "laptop_premium": (5_999_000_00, 14_999_000_00),
    "tablet": (799_000_00, 3_499_000_00),
}

# Un equipo pierde valor cada año; sin fecha se asume una antigüedad media.
_CATALOG_YEAR: Final = 2026
_ASSUMED_AGE: Final = 3
_YEARLY_DECAY: Final = 0.16
_MIN_RESIDUAL: Final = 0.34

_FLAGSHIP = re.compile(r"\b(pro|ultra|max|fold|flip|plus)\b|\bs2[0-9]\b|\bmate\s*[456][0-9]", re.I)
_ENTRY = re.compile(r"\b(lite|mini|neo|go|a0?[0-9]|m[0-2][0-9]|redmi\s*(9|1[0-3])a?)\b", re.I)
_PREMIUM_LAPTOP = re.compile(
    r"\b(rog|legion|thinkpad\s*x1|macbook\s*pro|blade|zephyrus|xps)\b", re.I
)


def _tier(title: str, category: str) -> str:
    if category == "laptops":
        return "laptop_premium" if _PREMIUM_LAPTOP.search(title) else "laptop"
    if category == "tablets":
        return "tablet"
    if _FLAGSHIP.search(title):
        return "flagship"
    if _ENTRY.search(title):
        return "entry"
    return "mid"


def _residual(released: str | None) -> float:
    """Cuánto de su precio de lanzamiento conserva el equipo hoy."""
    if released and released[:4].isdigit():
        age = max(_CATALOG_YEAR - int(released[:4]), 0)
    else:
        age = _ASSUMED_AGE
    return max(1.0 - _YEARLY_DECAY * age, _MIN_RESIDUAL)


# Las marcas que sostienen precio conservan más valor que la media del mercado.
_BRAND_PREMIUM: Final[dict[str, float]] = {
    "apple": 2.0,
    "samsung": 1.35,
    "google": 1.3,
    "sony": 1.25,
    "asus": 1.15,
    "lenovo": 1.1,
}


def _premium(brand: str) -> float:
    head = brand.split()[0].casefold() if brand else ""
    return _BRAND_PREMIUM.get(head, 1.0)


def _price(entity: str, category: str, title: str, brand: str, released: str | None) -> int:
    low, high = _TIER_RANGE[_tier(title, category)]
    spread = _digits(entity)[0] / 255
    amount = int((low + (high - low) * spread) * _residual(released) * _premium(brand))
    # Se redondea a decenas de miles de pesos para que se lea como un precio de tienda.
    return max((amount // 10_000_00) * 10_000_00, 199_000_00)


# Wikidata nombra al fabricante por su razón social; la tienda necesita la marca comercial.
_BRAND_ALIASES: Final[dict[str, str]] = {
    "apple inc.": "Apple",
    "samsung electronics": "Samsung",
    "samsung group": "Samsung",
    "sony mobile communications": "Sony",
    "sony corporation": "Sony",
    "lg electronics": "LG",
    "guangdong oplus holdings co., ltd.": "OnePlus",
    "oneplus technology": "OnePlus",
    "beijing xiaomi mobile software": "Xiaomi",
    "huawei technologies": "Huawei",
    "google llc": "Google",
    "motorola mobility": "Motorola",
    "asustek computer": "ASUS",
    "lenovo group": "Lenovo",
    "htc corporation": "HTC",
    "nokia corporation": "Nokia",
}
# Cuando el modelo no declara fabricante, la primera palabra del título casi siempre es la
# marca; estas son las excepciones donde nombra la línea de producto.
_TITLE_BRANDS: Final[dict[str, str]] = {
    "iphone": "Apple",
    "ipad": "Apple",
    "macbook": "Apple",
    "galaxy": "Samsung",
    "redmi": "Xiaomi",
    "poco": "Xiaomi",
    "pixel": "Google",
    "thinkpad": "Lenovo",
    "legion": "Lenovo",
    "moto": "Motorola",
    "nord": "OnePlus",
    "zenfone": "ASUS",
    "xperia": "Sony",
}


def _brand_of(product: dict[str, Any]) -> str:
    brand = product.get("brand")
    if isinstance(brand, str) and brand.strip():
        cleaned = brand.strip()
        alias = _BRAND_ALIASES.get(cleaned.casefold())
        if alias:
            return alias
        # Se recorta la forma societaria para que no aparezcan dos veces la misma marca.
        for suffix in (" Inc.", " Corporation", " Electronics", " Group", " Co., Ltd.", " LLC"):
            if cleaned.endswith(suffix):
                cleaned = cleaned[: -len(suffix)]
        return cleaned[:100]
    head = str(product["title"]).split()[0]
    return _TITLE_BRANDS.get(head.casefold(), head)[:100]


_ASSETS_DIR: Final = Path(__file__).resolve().parents[3] / "assets/products"


@lru_cache
def _downloaded_images() -> dict[str, str]:
    """Nombre de archivo servido por producto, para las fotos ya descargadas."""
    if not _ASSETS_DIR.is_dir():
        return {}
    return {path.stem: path.name for path in _ASSETS_DIR.iterdir() if path.suffix != ".md"}


def _image_path(entity: str) -> str | None:
    """Ruta relativa al origen del comercio; el exportador le antepone el origen."""
    name = _downloaded_images().get(entity)
    return f"/assets/products/{name}" if name else None


def _description(product: dict[str, Any], brand: str, variants: int) -> str:
    kind = product.get("kind") or "Producto"
    released = product.get("released")
    parts = [f"{kind} {brand}."]
    if released:
        parts.append(f"Lanzado en {released[:4]}.")
    parts.append(
        "Disponible en una configuración."
        if variants == 1
        else f"Disponible en {variants} configuraciones."
    )
    parts.append("Ficha sintética para el laboratorio de la tesis.")
    return " ".join(parts)[:2000]


# Antes de este año no se inventan capacidades modernas: un teléfono de 2005 con 512 GB es
# ruido evidente en la vitrina. Los productos sin fecha se tratan como no fechables.
_MODERN_FROM: Final = 2015


def _is_modern(released: str | None) -> bool:
    if not released or len(released) < 4 or not released[:4].isdigit():
        return False
    return int(released[:4]) >= _MODERN_FROM


def _variant_specs(
    entity: str, category: str, released: str | None
) -> list[tuple[str, dict[str, str], str]]:
    """Devuelve (código, atributos, color) por variante.

    Solo los productos con fecha reciente reciben una matriz de configuraciones inventada.
    El resto queda con una sola variante y su color, que es lo único que se puede afirmar
    sin contradecir el producto real.
    """
    d = _digits(entity)
    storages = _STORAGE.get(category, _STORAGE["smartphones"])
    count = 1 + d[1] % 3
    start = d[2] % max(len(storages) - count + 1, 1)
    chosen = storages[start : start + count] or storages[:1]
    specs: list[tuple[str, dict[str, str], str]] = []
    for index, storage in enumerate(chosen):
        attributes = {"storage": storage}
        if category == "laptops":
            attributes["ram"] = _RAM[(d[3] + index) % len(_RAM)]
        color = _COLORS[(d[4] + index) % len(_COLORS)]
        specs.append((storage.replace(" ", ""), attributes, color))
    return specs


@lru_cache
def _snapshot() -> list[dict[str, Any]]:
    if not SNAPSHOT_PATH.exists():
        return []
    document = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    products: list[dict[str, Any]] = document.get("products", [])
    # Las fotos van primero; el arte vectorial queda al final del catálogo.
    return sorted(products, key=lambda row: (row["is_vector"], row["category"], row["entity"]))


def build_generated_offers(
    *, delivery_context: DeliveryContext, observed_at: str, expires_at: str
) -> list[Offer]:
    offers: list[Offer] = []
    for product in _snapshot():
        entity = str(product["entity"])
        category = str(product["category"])
        brand = _brand_of(product)
        title = str(product["title"])[:200]
        d = _digits(entity)
        released = product.get("released")
        specs = _variant_specs(entity, category, released)
        description = _description(product, brand, len(specs))
        image_path = _image_path(entity)
        base = _price(entity, category, title, brand, released)
        # Uno de cada ocho se ofrece reacondicionado, con el descuento habitual.
        refurbished = d[5] % 8 == 0
        condition = "refurbished" if refurbished else "new"

        for index, (code, attributes, color) in enumerate(specs):
            # Cada escalón de configuración sube el precio de forma estable.
            item_minor = base + index * ((d[6] % 6 + 2) * 10_000_00)
            if refurbished:
                item_minor = int(item_minor * 0.75 // 10_000_00) * 10_000_00 or base
            shipping = 0 if item_minor >= 2_000_000_00 else _SHIP_STD
            quantity = (d[7] + index * 3) % 14
            offers.append(
                Offer(
                    id=f"{entity}-{code}",
                    product_id=f"prod-{entity.lower()}",
                    product_status="active",
                    sku=f"{entity}-{code}",
                    merchant_id="merchant-sim-01",
                    revision=1,
                    category=category,
                    # Sin configuración inventada, el nombre de la variante es el del producto.
                    name=(title if code == "STD" else f"{title} {code}")[:200],
                    product_title=title,
                    product_description=description,
                    brand=brand,
                    image_url=image_path,
                    color=color,
                    attributes=dict(attributes),
                    condition=condition,
                    availability="in_stock" if quantity > 0 else "out_of_stock",
                    available_quantity=quantity,
                    pricing=Pricing(
                        currency="cop",
                        items_total_minor=item_minor,
                        shipping_total_minor=shipping,
                        total_minor=item_minor + shipping,
                        tax_included=True,
                    ),
                    delivery_context=delivery_context,
                    delivery_days=1 + d[8] % 8,
                    observed_at=observed_at,
                    expires_at=expires_at,
                )
            )
    return offers
