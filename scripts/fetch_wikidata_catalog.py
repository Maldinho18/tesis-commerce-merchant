"""Recolecta un catálogo de productos reales desde Wikidata, de una sola pasada.

El resultado se commitea como snapshot (`src/commerce_lab/fixtures/catalog_snapshot.json`)
junto con su sha256. El fixture lee ese archivo, nunca la red: el catálogo sigue siendo
determinista y `verify()` puede comparar el snapshot sembrado byte a byte.

Las imágenes son de Wikimedia Commons, con licencias libres, así que se pueden publicar y
citar. Se guarda el nombre del archivo para poder atribuirlas.

Uso:
    uv run python scripts/fetch_wikidata_catalog.py \
        --out src/commerce_lab/fixtures/catalog_snapshot.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Final

ENDPOINT: Final = "https://query.wikidata.org/sparql"
USER_AGENT: Final = "TesisCommerceCatalog/1.0 (Uniandes thesis; academic use)"
QID: Final = re.compile(r"^Q\d+$")

# Clases de Wikidata que dan modelos de producto con imagen.
FAMILIES: Final[tuple[tuple[str, str, str], ...]] = (
    ("Q19723444", "smartphones", "Teléfono"),
    ("Q73343954", "laptops", "Portátil"),
    ("Q3962", "laptops", "Portátil"),
    ("Q155972", "tablets", "Tableta"),
)

QUERY: Final = """
SELECT ?item ?itemLabel (SAMPLE(?brandLabel) AS ?brand) (MIN(?date) AS ?released)
       (SAMPLE(?img) AS ?image) WHERE {
  ?item wdt:P31/wdt:P279* wd:%s .
  ?item wdt:P18 ?img .
  OPTIONAL { ?item wdt:P176 ?brandItem .
             ?brandItem rdfs:label ?brandLabel . FILTER(LANG(?brandLabel) = "en") }
  OPTIONAL { ?item wdt:P577 ?date }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
GROUP BY ?item ?itemLabel
LIMIT 4000
"""


def _sparql(query: str) -> list[dict[str, Any]]:
    url = f"{ENDPOINT}?{urllib.parse.urlencode({'query': query})}"
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/sparql-results+json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload["results"]["bindings"]


def _value(row: dict[str, Any], key: str) -> str | None:
    cell = row.get(key)
    if not cell:
        return None
    value = str(cell.get("value", "")).strip()
    return value or None


def _commons_file(image_url: str) -> str | None:
    """`Special:FilePath/Foo.jpg` -> `Foo.jpg`, ya decodificado."""
    marker = "/Special:FilePath/"
    if marker not in image_url:
        return None
    return urllib.parse.unquote(image_url.split(marker, 1)[1])


def collect() -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for class_id, category, kind in FAMILIES:
        rows = _sparql(QUERY % class_id)
        print(f"  {class_id} ({category}): {len(rows)} filas", flush=True)
        for row in rows:
            item = _value(row, "item")
            label = _value(row, "itemLabel")
            image = _value(row, "image")
            if not item or not label or not image:
                continue
            # Sin etiqueta traducida Wikidata devuelve el propio Q-id: no sirve como título.
            if QID.match(label):
                continue
            file_name = _commons_file(image)
            if not file_name:
                continue
            entity = item.rsplit("/", 1)[-1]
            if entity in seen:
                continue
            brand = _value(row, "brand")
            if brand and QID.match(brand):
                brand = None
            released = _value(row, "released")
            seen[entity] = {
                "entity": entity,
                "title": label,
                "brand": brand,
                "category": category,
                "kind": kind,
                "released": released[:10] if released else None,
                "image_file": file_name,
                # Las fotos reales se prefieren sobre el arte vectorial al ordenar.
                "is_vector": file_name.lower().endswith((".svg", ".svgz")),
            }
        time.sleep(1)
    return sorted(seen.values(), key=lambda row: (row["category"], row["title"], row["entity"]))


def main() -> None:
    parser = argparse.ArgumentParser(prog="fetch_wikidata_catalog")
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()

    print("Consultando Wikidata...", flush=True)
    products = collect()
    document = {
        "source": "Wikidata (https://www.wikidata.org), imágenes de Wikimedia Commons",
        "license": "Datos: CC0. Imágenes: licencias libres por archivo, ver image_file.",
        "product_count": len(products),
        "products": products,
    }
    body = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(body, encoding="utf-8")
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    arguments.out.with_suffix(".sha256").write_text(digest + "\n", encoding="utf-8")

    by_category: dict[str, int] = {}
    for product in products:
        by_category[product["category"]] = by_category.get(product["category"], 0) + 1
    print(json.dumps({"total": len(products), "por_categoria": by_category, "sha256": digest[:16]}))


if __name__ == "__main__":
    main()
