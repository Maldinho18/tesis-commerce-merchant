"""Amplía el catálogo con el surtido de una cadena, usando imágenes de Openverse.

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

ROOT: Final = Path(__file__).resolve().parents[1]
SNAPSHOT: Final = ROOT / "src/commerce_lab/fixtures/catalog_snapshot.json"
OUT_DIR: Final = ROOT / "assets/products"
USER_AGENT: Final = "TesisCommerceCatalog/1.0 (Uniandes thesis; academic use)"
ENDPOINT: Final = "https://api.openverse.org/v1/images/"
LICENSES: Final = "by,by-sa,cc0,pdm"
MIN_SIDE: Final = 400

# Surtido de una cadena como Best Buy. No vende Xiaomi, Huawei, Oppo ni vivo.
CATALOG: Final[tuple[tuple[str, str, str, int], ...]] = (
    ("Apple", "iPhone 17 Pro Max", "2025-09-19", 2025),
    ("Apple", "iPhone 17 Pro", "2025-09-19", 2025),
    ("Apple", "iPhone 17", "2025-09-19", 2025),
    ("Apple", "iPhone 16 Pro Max", "2024-09-20", 2024),
    ("Apple", "iPhone 16 Pro", "2024-09-20", 2024),
    ("Apple", "iPhone 16 Plus", "2024-09-20", 2024),
    ("Apple", "iPhone 16", "2024-09-20", 2024),
    ("Apple", "iPhone 15 Pro Max", "2023-09-22", 2023),
    ("Apple", "iPhone 15 Pro", "2023-09-22", 2023),
    ("Apple", "iPhone 15", "2023-09-22", 2023),
    ("Apple", "iPhone 14", "2022-09-16", 2022),
    ("Samsung", "Samsung Galaxy S25 Ultra", "2025-02-07", 2025),
    ("Samsung", "Samsung Galaxy S25", "2025-02-07", 2025),
    ("Samsung", "Samsung Galaxy S24 Ultra", "2024-01-31", 2024),
    ("Samsung", "Samsung Galaxy S24", "2024-01-31", 2024),
    ("Samsung", "Samsung Galaxy S23 Ultra", "2023-02-17", 2023),
    ("Samsung", "Samsung Galaxy S23", "2023-02-17", 2023),
    ("Samsung", "Samsung Galaxy Z Fold 6", "2024-07-24", 2024),
    ("Samsung", "Samsung Galaxy Z Flip 6", "2024-07-24", 2024),
    ("Samsung", "Samsung Galaxy Z Fold 5", "2023-08-11", 2023),
    ("Samsung", "Samsung Galaxy Z Flip 5", "2023-08-11", 2023),
    ("Samsung", "Samsung Galaxy A55", "2024-03-11", 2024),
    ("Samsung", "Samsung Galaxy A54", "2023-03-24", 2023),
    ("Samsung", "Samsung Galaxy A35", "2024-03-11", 2024),
    ("Samsung", "Samsung Galaxy A25", "2023-12-15", 2023),
    ("Samsung", "Samsung Galaxy A15", "2023-12-15", 2023),
    ("Google", "Google Pixel 9 Pro XL", "2024-08-22", 2024),
    ("Google", "Google Pixel 9 Pro", "2024-08-22", 2024),
    ("Google", "Google Pixel 9", "2024-08-22", 2024),
    ("Google", "Google Pixel 8 Pro", "2023-10-12", 2023),
    ("Google", "Google Pixel 8", "2023-10-12", 2023),
    ("Google", "Google Pixel 8a", "2024-05-14", 2024),
    ("Google", "Google Pixel 7 Pro", "2022-10-13", 2022),
    ("Google", "Google Pixel 7a", "2023-05-10", 2023),
    ("OnePlus", "OnePlus 12", "2024-01-23", 2024),
    ("OnePlus", "OnePlus 11", "2023-02-07", 2023),
    ("OnePlus", "OnePlus Nord 4", "2024-07-16", 2024),
    ("Motorola", "Motorola Edge 50 Pro", "2024-04-03", 2024),
    ("Motorola", "Motorola Razr 50 Ultra", "2024-06-25", 2024),
    ("Motorola", "Motorola Moto G Power", "2024-01-25", 2024),
    ("Sony", "Sony Xperia 1 VI", "2024-05-17", 2024),
    ("Sony", "Sony Xperia 10 VI", "2024-05-17", 2024),
    ("TCL", "TCL 50 XL", "2024-04-01", 2024),
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
    known = {_normalized(str(row["title"])) for row in products}
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    added: list[dict[str, Any]] = []
    attribution: list[str] = []
    missed: list[str] = []
    for index, (brand, model, released, _year) in enumerate(CATALOG, start=1):
        if _normalized(model) in known:
            continue
        item = _best_image(model)
        if item is None:
            missed.append(model)
            print(f"  [{index}/{len(CATALOG)}] sin foto  {model}", flush=True)
            time.sleep(0.5)
            continue

        # El original puede pesar cientos de megabytes; Openverse sirve una miniatura
        # dimensionada que es lo que necesita una vitrina.
        source = str(item.get("thumbnail") or item.get("url") or "")
        payload = _request(source, timeout=90)
        if payload is None:
            missed.append(model)
            time.sleep(0.5)
            continue

        entity = "OV" + re.sub(r"[^A-Za-z0-9]", "", model)[:28]
        suffix = ".png" if source.lower().endswith(".png") else ".jpg"
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
            }
        )
        attribution.append(
            f"| `{entity}{suffix}` | {model} | {item.get('creator') or 'desconocido'} "
            f"| {str(item.get('license') or '').upper()} {item.get('license_version') or ''} "
            f"| {item.get('foreign_landing_url') or source} |"
        )
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
            "| Archivo | Producto | Autor | Licencia | Origen |",
            "| --- | --- | --- | --- | --- |",
        ]
        with (OUT_DIR / "PROVENANCE.md").open("a", encoding="utf-8") as handle:
            handle.write("\n".join([*header, *attribution, ""]))

    print(json.dumps({"agregados": len(added), "sin_foto": len(missed), "faltantes": missed}))


if __name__ == "__main__":
    main()
