"""Mejora las fotos del catálogo con renders oficiales de producto, donde existan.

Las imágenes de Wikimedia Commons son de licencia libre pero muchas son fotos de usuario:
un teléfono sobre una tela, una caja en una vitrina. Este recolector intenta reemplazarlas
por el render oficial del fabricante, que es lo que muestra una tienda real.

Solo consulta el CDN de imágenes, que responde a un cliente normal; no toca las páginas del
sitio, que sí bloquean el acceso automatizado. Un modelo sin render conserva su foto de
Commons, así que el catálogo nunca pierde cobertura.

Las imágenes son renders del fabricante, no material de licencia libre: quedan registradas
aparte en PROVENANCE.md para poder citarlas.

Uso:
    uv run python scripts/fetch_render_images.py
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
SNAPSHOT: Final = ROOT / "src/commerce_lab/fixtures/catalog_snapshot.json"
OUT_DIR: Final = ROOT / "assets/products"
# El catálogo publica el render en dos rutas distintas según la antigüedad del modelo.
CDN_BIG: Final = "https://fdn2.gsmarena.com/vv/bigpic/{slug}.jpg"
CDN_PICS: Final = "https://fdn2.gsmarena.com/vv/pics/{brand}/{slug}-{n}.jpg"
AGENT: Final = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0 Safari/537.36"
)
MIN_BYTES: Final = 2_000


def _slugs(brand: str, title: str) -> list[str]:
    """Variantes de nombre con las que el CDN publica un mismo modelo."""
    full = title if title.lower().startswith(brand.lower()) else f"{brand} {title}"
    base = re.sub(r"[^a-z0-9]+", "-", full.lower()).strip("-")
    bare = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    candidates = [base, f"{base}-5g", bare, f"{bare}-5g"]
    # Algunos modelos se publican sin el sufijo de variante.
    trimmed = re.sub(r"-(5g|4g|plus|lite)$", "", base)
    if trimmed != base:
        candidates.append(trimmed)
    seen: list[str] = []
    for slug in candidates:
        if slug and slug not in seen:
            seen.append(slug)
    return seen


def _urls(brand: str, title: str) -> list[str]:
    folder = re.sub(r"[^a-z0-9]+", "", brand.lower()) or "misc"
    out: list[str] = []
    for slug in _slugs(brand, title):
        out.append(CDN_BIG.format(slug=slug))
        for n in (1, 2):
            out.append(CDN_PICS.format(brand=folder, slug=slug, n=n))
    return out


def _download(url: str) -> bytes | None:
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            if response.status != 200:
                return None
            body = response.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    return body if len(body) >= MIN_BYTES else None


def main() -> None:
    products: list[dict[str, Any]] = json.loads(SNAPSHOT.read_text(encoding="utf-8"))["products"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    upgraded: list[str] = []
    for index, product in enumerate(products, start=1):
        if product.get("is_vector"):
            continue
        entity = str(product["entity"])
        brand = str(product.get("brand") or "")
        title = str(product["title"])
        body = None
        for url in _urls(brand, title):
            body = _download(url)
            if body is not None:
                break
            time.sleep(0.15)
        if body is None:
            continue
        # Se reemplaza la foto anterior del producto, cualquiera fuese su extensión.
        for existing in OUT_DIR.glob(f"{entity}.*"):
            existing.unlink()
        (OUT_DIR / f"{entity}.jpg").write_bytes(body)
        upgraded.append(f"| `{entity}.jpg` | {title} | render del fabricante |")
        if index % 20 == 0:
            print(f"  [{index}/{len(products)}] mejoradas={len(upgraded)}", flush=True)
        time.sleep(0.3)

    if upgraded:
        header = [
            "",
            "## Renders de fabricante",
            "",
            "Imágenes de producto publicadas por los fabricantes. No son de licencia libre:",
            "se usan aquí con fines académicos y deben citarse como tales en la tesis.",
            "",
            "| Archivo | Producto | Origen |",
            "| --- | --- | --- |",
        ]
        with (OUT_DIR / "PROVENANCE.md").open("a", encoding="utf-8") as handle:
            handle.write("\n".join([*header, *upgraded, ""]))
    print(json.dumps({"mejoradas": len(upgraded), "total": len(products)}))


if __name__ == "__main__":
    main()
