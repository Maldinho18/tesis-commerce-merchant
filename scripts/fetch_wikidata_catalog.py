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

# Clases de Wikidata que dan modelos de producto con imagen. Se usa "modelo de smartphone"
# y no "modelo de celular": la segunda arrastra plegables de los 2000 que no tienen lugar en
# una tienda actual.
FAMILIES: Final[tuple[tuple[str, str, str], ...]] = (("Q19723451", "smartphones", "Teléfono"),)

# El catálogo replica el surtido de una cadena como Best Buy: no vende Xiaomi, Huawei, Oppo
# ni vivo. La marca se compara ya normalizada.
STORE_BRANDS: Final[frozenset[str]] = frozenset(
    {"apple", "samsung", "google", "motorola", "oneplus", "tcl", "sony", "nokia"}
)
# Series que la cadena efectivamente ofrece hoy.
STORE_SERIES: Final = re.compile(
    r"(iphone|galaxy|pixel|moto\s*g|motorola\s*edge|razr|oneplus|nord|xperia)", re.I
)

# Un producto entra al catálogo si su fecha de lanzamiento es reciente o si su nombre
# pertenece a una serie vigente. La segunda regla existe porque solo uno de cada seis
# modelos trae fecha en Wikidata, y sin ella se perderían casi todos los equipos actuales.
MODERN_FROM: Final = 2016
MODERN_SERIES: Final = re.compile(
    r"""(
     iphone\s*(1[1-9]|se)| galaxy\s*(s(1[0-9]|2[0-9])|z\s*(fold|flip)|a[0-9]{2}|m[0-9]{2}
      |note\s*(1[0-9]|2[0-9]))| pixel\s*([6-9]|1[0-9])| redmi\s*(note\s*)?(9|1[0-9]|k[0-9]{2})|
     poco\s*[fxm][0-9]| (mi|xiaomi)\s*1[0-4]| oneplus\s*([7-9]|1[0-9]|nord)| mate\s*[2-6][0-9]|
     moto\s*g[0-9]{2}| edge\s*[0-9]{2}| reno\s*[0-9]| find\s*x[0-9]| vivo\s*[xyv][0-9]{2}|
     realme\s*([7-9]|1[0-9])| zenfone\s*[6-9]| rog\s*phone| xperia\s*(1|5|10)\s*i
    )""",
    re.I | re.X,
)


_CORPORATE: Final = re.compile(
    r"\s*(Inc\.|Corporation|Electronics|Group|Co\., Ltd\.|Mobile Communications"
    r"|Technologies|LLC|Mobility).*$"
)
_TITLE_BRANDS: Final[dict[str, str]] = {
    "iphone": "Apple",
    "galaxy": "Samsung",
    "pixel": "Google",
    "moto": "Motorola",
    "razr": "Motorola",
    "nord": "OnePlus",
    "xperia": "Sony",
}


def _normalized_brand(brand: str | None, label: str) -> str:
    """Nombre comercial de la marca; Wikidata devuelve razones sociales o nada."""
    if brand:
        cleaned = _CORPORATE.sub("", brand).strip()
        if cleaned:
            return cleaned
    head = label.split()[0].casefold()
    return _TITLE_BRANDS.get(head, label.split()[0])


def _is_modern(label: str, released: str | None) -> bool:
    if released and released[:4].isdigit():
        return int(released[:4]) >= MODERN_FROM
    return bool(MODERN_SERIES.search(label))


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
LIMIT 1500
"""


def _sparql(query: str) -> list[dict[str, Any]]:
    url = f"{ENDPOINT}?{urllib.parse.urlencode({'query': query})}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/sparql-results+json",
            "User-Agent": USER_AGENT,
            # Sin esto la respuesta llega comprimida y `read()` puede cortarla a la mitad.
            "Accept-Encoding": "identity",
        },
    )
    # Wikidata corta la respuesta cuando limita al cliente; se reintenta con espera.
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                body = response.read()
            payload = json.loads(body.decode("utf-8"))
            return payload["results"]["bindings"]
        except (json.JSONDecodeError, OSError) as error:
            last_error = error
            wait = 10 * (attempt + 1)
            print(f"    respuesta incompleta, reintento en {wait}s", flush=True)
            time.sleep(wait)
    raise RuntimeError("Wikidata no devolvió una respuesta completa") from last_error


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
            released = _value(row, "released")
            released_year = released[:10] if released else None
            if not _is_modern(label, released_year):
                continue
            normalized = _normalized_brand(brand, label)
            if normalized.casefold() not in STORE_BRANDS or not STORE_SERIES.search(label):
                continue
            seen[entity] = {
                "entity": entity,
                "title": label,
                "brand": normalized,
                "category": category,
                "kind": kind,
                "released": released_year,
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
