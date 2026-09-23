"""Deterministic full-replacement Product Feed export from merchant DB snapshots."""

import argparse
import json
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import psycopg
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from commerce_lab.contracts import Offer
from commerce_lab.db import database_url
from commerce_lab.db.core import FIXTURE_VERSION
from commerce_lab.settings import get_settings

_BUNDLE: dict[str, Any] = json.loads(
    (Path(__file__).resolve().parents[2] / "vendor/acp/2026-04-17/schema.feed.json").read_text(
        encoding="utf-8"
    )
)
_REGISTRY = Registry().with_resource(str(_BUNDLE["$id"]), Resource.from_contents(_BUNDLE))
_CHECKER = FormatChecker()
_METADATA_VALIDATOR = Draft202012Validator(
    {"$ref": f"{_BUNDLE['$id']}#/$defs/FeedMetadata"},
    registry=_REGISTRY,
    format_checker=_CHECKER,
)
_PRODUCT_VALIDATOR = Draft202012Validator(
    {"$ref": f"{_BUNDLE['$id']}#/$defs/Product"},
    registry=_REGISTRY,
    format_checker=_CHECKER,
)


def _json_line(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


# Etiqueta legible por dimensión de variante. La clave del atributo es un Identifier ASCII
# en minúsculas; el feed publica el nombre presentable. El agente normaliza ambos lados antes
# de comparar (selection.py), así que "RAM" y "ram" resuelven igual.
_OPTION_LABELS: Final[dict[str, str]] = {
    "color": "Color",
    "ram": "RAM",
    "gpu": "GPU",
    "cpu": "Procesador",
    "storage": "Almacenamiento",
    "size": "Tamaño",
    "resolution": "Resolución",
    "refresh_rate": "Refresco",
    "panel": "Panel",
    "switch": "Switch",
    "layout": "Distribución",
    "connectivity": "Conectividad",
}


def _option_value(value: str | int | bool) -> str:
    """Las opciones del feed son strings; los atributos admiten int y bool."""
    if isinstance(value, bool):
        return "sí" if value else "no"
    return str(value)


def _variant_options(offer: Offer) -> list[dict[str, str]]:
    """Color primero y luego los atributos en el orden estable de _OPTION_LABELS.

    Un atributo sin etiqueta conocida se publica con su clave capitalizada, para que agregar
    una dimensión al catálogo no exija tocar el exportador.
    """
    values: dict[str, str] = {}
    if offer.color:
        values["color"] = offer.color
    for key, value in offer.attributes.items():
        values.setdefault(key, _option_value(value))
    known = [key for key in _OPTION_LABELS if key in values]
    unknown = sorted(key for key in values if key not in _OPTION_LABELS)
    return [
        {"name": _OPTION_LABELS.get(key, key.replace("_", " ").capitalize()), "value": values[key]}
        for key in (*known, *unknown)
    ]


def _absolute(image_url: object, origin: str, product_id: str) -> str:
    if isinstance(image_url, str) and image_url:
        if image_url.startswith(("http://", "https://")):
            return image_url
        return f"{origin}{image_url if image_url.startswith('/') else '/' + image_url}"
    return f"{origin}/assets/products/{product_id}.jpg"


def _single(group: list[Offer], field: str, product_id: str) -> object:
    """Las variantes de un producto deben coincidir en los campos de nivel producto."""
    distinct = {getattr(offer, field) for offer in group}
    if len(distinct) != 1:
        raise ValueError(f"Product {product_id} has conflicting {field} across its variants")
    return distinct.pop()


def build_feed(
    offers: list[Offer], *, base_url: str | None = None
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Project authoritative Offer snapshots to Products, grouping variants by product_id."""
    if not offers:
        raise ValueError("P0 feed requires merchant offers")
    if len({offer.id for offer in offers}) != len(offers):
        raise ValueError("P0 feed requires unique variant IDs")
    if any(offer.pricing.currency != "cop" for offer in offers):
        raise ValueError("P0 feed requires COP merchant snapshots")
    if len({offer.delivery_context.country for offer in offers}) != 1:
        raise ValueError("P0 feed requires one target country")

    origin = (base_url or get_settings().acp_api_base_url).rstrip("/")
    metadata: dict[str, object] = {
        "id": "feed_p0_tech",
        "target_country": offers[0].delivery_context.country,
        "updated_at": max(offer.observed_at for offer in offers),
    }

    grouped: dict[str, list[Offer]] = {}
    for offer in offers:
        grouped.setdefault(offer.product_id, []).append(offer)

    products: list[dict[str, object]] = []
    for product_id in sorted(grouped):
        group = sorted(grouped[product_id], key=lambda item: item.id)
        brand = _single(group, "brand", product_id)
        image_url = _single(group, "image_url", product_id)
        title = _single(group, "product_title", product_id) or f"{brand} {product_id}"
        description = _single(group, "product_description", product_id) or (
            f"{brand} disponible en {len(group)} configuraciones."
        )
        url = f"{origin}/products/{product_id}"

        variants: list[dict[str, object]] = []
        for offer in group:
            availability_status = (
                "out_of_stock"
                if offer.available_quantity == 0
                else "limited_stock"
                if offer.available_quantity == 1
                else "in_stock"
            )
            variants.append(
                {
                    "id": offer.id,
                    "title": offer.name,
                    "url": f"{url}?variant={offer.id}",
                    # Checkout y discovery usan cop en minúscula; Price del feed exige ISO 4217
                    # en mayúscula. COP tiene exponente 2, así que amount sigue siendo centavos.
                    "price": {"amount": offer.pricing.items_total_minor, "currency": "COP"},
                    "availability": {
                        "available": offer.available_quantity > 0,
                        "status": availability_status,
                    },
                    # La marca se publica como categoría en su propia taxonomía: el esquema
                    # ACP no tiene campo de marca, y derivarla del título da "iPhone" en vez
                    # de "Apple". Quien consuma el feed debe filtrar por `taxonomy`.
                    "categories": [
                        {"value": offer.category, "taxonomy": "merchant"},
                        {"value": offer.brand, "taxonomy": "brand"},
                    ],
                    "condition": [offer.condition],
                    "variant_options": _variant_options(offer),
                    "seller": {"name": "Synthetic Commerce Merchant"},
                }
            )

        product: dict[str, object] = {
            "id": product_id,
            "title": title,
            "description": {"plain": description},
            "url": url,
            "media": [
                {
                    "type": "image",
                    # `image_url` puede venir como ruta relativa del propio comercio o como
                    # URL absoluta de un catálogo externo; ambas se publican absolutas.
                    "url": _absolute(image_url, origin, product_id),
                    "alt_text": title,
                }
            ],
            "variants": variants,
        }
        _PRODUCT_VALIDATOR.validate(product)
        products.append(product)
    _METADATA_VALIDATOR.validate(metadata)
    return metadata, products


def _read_offers(run_id: str | None) -> list[Offer]:
    with psycopg.connect(database_url()) as connection, connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        if run_id is None:
            selected = connection.execute(
                """SELECT run_id FROM experiment_runs
                   WHERE fixture_version = %s
                   ORDER BY created_at DESC, run_id DESC LIMIT 1""",
                (FIXTURE_VERSION,),
            ).fetchone()
        else:
            selected = connection.execute(
                "SELECT run_id FROM experiment_runs WHERE run_id = %s AND fixture_version = %s",
                (UUID(run_id), FIXTURE_VERSION),
            ).fetchone()
        if selected is None:
            raise ValueError("Seed a P0 merchant episode before exporting the feed")
        rows = connection.execute(
            "SELECT snapshot FROM catalog_offers WHERE run_id = %s ORDER BY offer_id",
            (selected[0],),
        ).fetchall()
    return [Offer.model_validate(row[0]) for row in rows]


_PREPARATION_RUN = """
SELECT run_id FROM experiment_runs
WHERE fixture_version = %s AND variant = 'preparation'
ORDER BY created_at DESC, run_id DESC LIMIT 1
"""


def current_feed(
    *, base_url: str | None = None
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Catálogo del episodio P0 vigente, en la misma forma que consume el comprador.

    El storefront y el agente leen la misma proyección: un solo catálogo autoritativo
    servido por dos canales. Lee de la base en cada llamada, así que el inventario que
    ve una persona refleja las compras que ya hizo el agente.

    Se ancla al episodio `preparation`, que es al que el bootstrap vincula el Bearer del
    comprador. Sin ese filtro, un episodio sintético creado por otra prueba podría quedar
    más reciente y la tienda mostraría un inventario distinto del que compra el agente.
    """
    with psycopg.connect(database_url()) as connection, connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        selected = connection.execute(_PREPARATION_RUN, (FIXTURE_VERSION,)).fetchone()
        if selected is None:
            raise ValueError("Seed a P0 merchant episode before serving the storefront")
        rows = connection.execute(
            "SELECT snapshot FROM catalog_offers WHERE run_id = %s ORDER BY offer_id",
            (selected[0],),
        ).fetchall()
    return build_feed([Offer.model_validate(row[0]) for row in rows], base_url=base_url)


def export_feed(
    output_dir: Path, *, run_id: str | None = None, base_url: str | None = None
) -> dict[str, object]:
    metadata, products = build_feed(_read_offers(run_id), base_url=base_url)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "metadata.json").write_text(_json_line(metadata), encoding="utf-8")
    (output_dir / "products.jsonl").write_text(
        "".join(_json_line(product) for product in products), encoding="utf-8"
    )
    return {
        "metadata": str(output_dir / "metadata.json"),
        "products": str(output_dir / "products.jsonl"),
        "product_count": len(products),
        "variant_count": sum(
            len(variants)
            for product in products
            if isinstance(variants := product["variants"], list)
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m commerce_lab.feed")
    parser.add_argument("command", choices=["export"])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-id")
    # Origen público del merchant que se publica en las URLs y las imágenes del feed.
    # Por defecto sale de ACP_API_BASE_URL.
    parser.add_argument("--base-url")
    arguments = parser.parse_args()
    try:
        result = export_feed(
            arguments.output_dir, run_id=arguments.run_id, base_url=arguments.base_url
        )
    except Exception:
        parser.exit(1, "P0 feed export failed. Check merchant database and snapshots.\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
