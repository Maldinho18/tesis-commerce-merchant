"""Amplía el catálogo con el surtido de una cadena, usando renders de producto.

Wikidata solo expone una imagen designada por modelo y su cobertura deja fuera líneas
enteras: no tiene ningún Google Pixel. Openverse agrega Flickr y otros bancos con licencia
Creative Commons, y sí tiene fotos de producto de los modelos vigentes.

El filtro clave: una foto de producto lleva el modelo al inicio del título, mientras que una
foto *tomada con* ese teléfono lo lleva entre paréntesis al final ("Ant on a Daisy (OnePlus
12)"). Sin esa regla el catálogo se llenaba de flores.

Solo se aceptan licencias que permiten redistribución con atribución. La atribución exigida
por la licencia queda registrada en el archivo de procedencia.

Uso:
    uv run python scripts/fetch_openverse_catalog.py
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Final

from fetch_render_images import _download as _render_download
from fetch_render_images import _urls as _render_urls

ROOT: Final = Path(__file__).resolve().parents[1]
SNAPSHOT: Final = ROOT / "src/commerce_lab/fixtures/catalog_snapshot.json"
OUT_DIR: Final = ROOT / "assets/products"
USER_AGENT: Final = "TesisCommerceCatalog/1.0 (Uniandes thesis; academic use)"
ENDPOINT: Final = "https://api.openverse.org/v1/images/"
LICENSES: Final = "by,by-sa,cc0,pdm"
MIN_SIDE: Final = 400

# Surtido de una cadena como Best Buy. No vende Xiaomi, Huawei, Oppo ni vivo.
# Surtido de una cadena como Best Buy. No vende Xiaomi, Huawei, Oppo ni vivo.
# Cada entrada lleva las capacidades reales que Apple, Samsung o Google ofrecieron para ese
# modelo; el generador solo inventa capacidades cuando no se declaran aquí.
CATALOG: Final[tuple[tuple[str, str, str, tuple[str, ...]], ...]] = (
    # iPhone, de la generación 11 a la 18.
    ("Apple", "iPhone 11", "2019-09-20", ("64 GB", "128 GB", "256 GB")),
    ("Apple", "iPhone 11 Pro", "2019-09-20", ("64 GB", "256 GB", "512 GB")),
    ("Apple", "iPhone 11 Pro Max", "2019-09-20", ("64 GB", "256 GB", "512 GB")),
    ("Apple", "iPhone 12 mini", "2020-11-13", ("64 GB", "128 GB", "256 GB")),
    ("Apple", "iPhone 12", "2020-10-23", ("64 GB", "128 GB", "256 GB")),
    ("Apple", "iPhone 12 Pro", "2020-10-23", ("128 GB", "256 GB", "512 GB")),
    ("Apple", "iPhone 12 Pro Max", "2020-11-13", ("128 GB", "256 GB", "512 GB")),
    ("Apple", "iPhone 13 mini", "2021-09-24", ("128 GB", "256 GB", "512 GB")),
    ("Apple", "iPhone 13", "2021-09-24", ("128 GB", "256 GB", "512 GB")),
    ("Apple", "iPhone 13 Pro", "2021-09-24", ("128 GB", "256 GB", "512 GB", "1 TB")),
    ("Apple", "iPhone 13 Pro Max", "2021-09-24", ("128 GB", "256 GB", "512 GB", "1 TB")),
    ("Apple", "iPhone 14", "2022-09-16", ("128 GB", "256 GB", "512 GB")),
    ("Apple", "iPhone 14 Plus", "2022-10-07", ("128 GB", "256 GB", "512 GB")),
    ("Apple", "iPhone 14 Pro", "2022-09-16", ("128 GB", "256 GB", "512 GB", "1 TB")),
    ("Apple", "iPhone 14 Pro Max", "2022-09-16", ("128 GB", "256 GB", "512 GB", "1 TB")),
    ("Apple", "iPhone 15", "2023-09-22", ("128 GB", "256 GB", "512 GB")),
    ("Apple", "iPhone 15 Plus", "2023-09-22", ("128 GB", "256 GB", "512 GB")),
    ("Apple", "iPhone 15 Pro", "2023-09-22", ("128 GB", "256 GB", "512 GB", "1 TB")),
    ("Apple", "iPhone 15 Pro Max", "2023-09-22", ("256 GB", "512 GB", "1 TB")),
    ("Apple", "iPhone 16e", "2025-02-28", ("128 GB", "256 GB", "512 GB")),
    ("Apple", "iPhone 16", "2024-09-20", ("128 GB", "256 GB", "512 GB")),
    ("Apple", "iPhone 16 Plus", "2024-09-20", ("128 GB", "256 GB", "512 GB")),
    ("Apple", "iPhone 16 Pro", "2024-09-20", ("128 GB", "256 GB", "512 GB", "1 TB")),
    ("Apple", "iPhone 16 Pro Max", "2024-09-20", ("256 GB", "512 GB", "1 TB")),
    ("Apple", "iPhone 17", "2025-09-19", ("256 GB", "512 GB")),
    ("Apple", "iPhone 17 Pro", "2025-09-19", ("256 GB", "512 GB", "1 TB")),
    ("Apple", "iPhone 17 Pro Max", "2025-09-19", ("256 GB", "512 GB", "1 TB", "2 TB")),
    ("Apple", "iPhone Air", "2025-09-19", ("256 GB", "512 GB", "1 TB")),
    ("Apple", "iPhone 18", "2026-09-18", ("256 GB", "512 GB")),
    ("Apple", "iPhone 18 Pro", "2026-09-18", ("256 GB", "512 GB", "1 TB")),
    ("Apple", "iPhone 18 Pro Max", "2026-09-18", ("256 GB", "512 GB", "1 TB", "2 TB")),
    ("Apple", "iPhone SE (2022)", "2022-03-18", ("64 GB", "128 GB", "256 GB")),
    # Resto del surtido.
    ("Samsung", "Samsung Galaxy S25 Ultra", "2025-02-07", ("256 GB", "512 GB", "1 TB")),
    ("Samsung", "Samsung Galaxy S25", "2025-02-07", ("128 GB", "256 GB", "512 GB")),
    ("Samsung", "Samsung Galaxy S24 Ultra", "2024-01-31", ("256 GB", "512 GB", "1 TB")),
    ("Samsung", "Samsung Galaxy S24", "2024-01-31", ("128 GB", "256 GB", "512 GB")),
    ("Samsung", "Samsung Galaxy S23 Ultra", "2023-02-17", ("256 GB", "512 GB", "1 TB")),
    ("Samsung", "Samsung Galaxy S23", "2023-02-17", ("128 GB", "256 GB")),
    ("Samsung", "Samsung Galaxy Z Fold 6", "2024-07-24", ("256 GB", "512 GB", "1 TB")),
    ("Samsung", "Samsung Galaxy Z Flip 6", "2024-07-24", ("256 GB", "512 GB")),
    ("Samsung", "Samsung Galaxy A55", "2024-03-11", ("128 GB", "256 GB")),
    ("Samsung", "Samsung Galaxy A54", "2023-03-24", ("128 GB", "256 GB")),
    ("Samsung", "Samsung Galaxy A35", "2024-03-11", ("128 GB", "256 GB")),
    ("Samsung", "Samsung Galaxy A25", "2023-12-15", ("128 GB", "256 GB")),
    ("Samsung", "Samsung Galaxy A15", "2023-12-15", ("128 GB", "256 GB")),
    ("Google", "Google Pixel 9 Pro XL", "2024-08-22", ("128 GB", "256 GB", "512 GB", "1 TB")),
    ("Google", "Google Pixel 9 Pro", "2024-08-22", ("128 GB", "256 GB", "512 GB", "1 TB")),
    ("Google", "Google Pixel 9", "2024-08-22", ("128 GB", "256 GB")),
    ("Google", "Google Pixel 8 Pro", "2023-10-12", ("128 GB", "256 GB", "512 GB")),
    ("Google", "Google Pixel 8", "2023-10-12", ("128 GB", "256 GB")),
    ("Google", "Google Pixel 8a", "2024-05-14", ("128 GB", "256 GB")),
    ("Google", "Google Pixel 7a", "2023-05-10", ("128 GB",)),
    ("OnePlus", "OnePlus 12", "2024-01-23", ("256 GB", "512 GB")),
    ("OnePlus", "OnePlus 11", "2023-02-07", ("128 GB", "256 GB")),
    ("Motorola", "Motorola Edge 50 Pro", "2024-04-03", ("256 GB", "512 GB")),
    ("Motorola", "Motorola Razr 50 Ultra", "2024-06-25", ("256 GB", "512 GB")),
    ("Motorola", "Motorola Moto G Power", "2024-01-25", ("128 GB",)),
    ("Sony", "Sony Xperia 1 VI", "2024-05-17", ("256 GB", "512 GB")),
    ("Sony", "Sony Xperia 10 VI", "2024-05-17", ("128 GB",)),
    ("TCL", "TCL 50 XL", "2024-04-01", ("128 GB", "256 GB")),
)


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _request(url: str, timeout: int = 45) -> bytes | None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(2 * (attempt + 1))
    return None


def _best_image(model: str) -> dict[str, Any] | None:
    query = urllib.parse.urlencode({"q": model, "page_size": 20, "license": LICENSES})
    body = _request(f"{ENDPOINT}?{query}")
    if body is None:
        return None
    try:
        results: list[dict[str, Any]] = json.loads(body).get("results") or []
    except json.JSONDecodeError:
        return None

    key = _normalized(model)
    candidates: list[tuple[int, dict[str, Any]]] = []
    for item in results:
        title = _normalized(str(item.get("title") or ""))
        if not title.startswith(key):
            continue
        width, height = int(item.get("width") or 0), int(item.get("height") or 0)
        if width < MIN_SIDE or height < MIN_SIDE:
            continue
        candidates.append((width * height, item))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: -pair[0])
    return candidates[0][1]


def main() -> None:
    document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    products: list[dict[str, Any]] = document["products"]
    by_title = {_normalized(str(row["title"])): row for row in products}
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    added: list[dict[str, Any]] = []
    updated = 0
    attribution: list[str] = []
    missed: list[str] = []
    for index, (brand, model, released, storages) in enumerate(CATALOG, start=1):
        existing = by_title.get(_normalized(model))
        if existing is not None:
            # Ya está en el catálogo, pero probablemente sin capacidades declaradas: el
            # snapshot de Wikidata no las trae y el generador las inventaría.
            existing["storage_options"] = list(storages)
            if released and not existing.get("released"):
                existing["released"] = released
            updated += 1
            continue
        payload = None
        for url in _render_urls(brand, model):
            payload = _render_download(url)
            if payload is not None:
                break
            time.sleep(0.15)
        if payload is None:
            missed.append(model)
            print(f"  [{index}/{len(CATALOG)}] sin foto  {model}", flush=True)
            time.sleep(0.2)
            continue

        entity = "BB" + re.sub(r"[^A-Za-z0-9]", "", model)[:28]
        suffix = ".jpg"
        (OUT_DIR / f"{entity}{suffix}").write_bytes(payload)
        added.append(
            {
                "entity": entity,
                "title": model,
                "brand": brand,
                "category": "smartphones",
                "kind": "Teléfono",
                "released": released,
                "image_file": f"{entity}{suffix}",
                "is_vector": False,
                "storage_options": list(storages),
            }
        )
        attribution.append(f"| `{entity}{suffix}` | {model} | render del fabricante |")
        print(f"  [{index}/{len(CATALOG)}] OK  {model}", flush=True)
        time.sleep(0.6)

    document["products"] = sorted(
        products + added, key=lambda row: (row["category"], row["entity"])
    )
    document["product_count"] = len(document["products"])
    SNAPSHOT.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    if attribution:
        header = [
            "",
            "## Imágenes de Openverse",
            "",
            "Licencias Creative Commons que exigen atribución. Se conserva autor, licencia y",
            "página de origen de cada archivo.",
            "",
            "| Archivo | Producto | Origen |",
            "| --- | --- | --- |",
        ]
        with (OUT_DIR / "PROVENANCE.md").open("a", encoding="utf-8") as handle:
            handle.write("\n".join([*header, *attribution, ""]))

    print(
        json.dumps(
            {
                "agregados": len(added),
                "actualizados": updated,
                "sin_foto": len(missed),
                "faltantes": missed,
            }
        )
    )


if __name__ == "__main__":
    main()
