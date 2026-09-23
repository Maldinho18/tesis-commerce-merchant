"""Descarga una vez las fotos del catálogo y las deja servidas por el propio comercio.

Enlazar a Wikimedia desde la vitrina no funciona: `Special:FilePath` redirige a través del
wiki, que limita las peticiones, y una retícula pide decenas de imágenes a la vez. Al
descargarlas el comercio las sirve desde su propio origen y la tienda deja de depender de
un tercero.

Las imágenes son de Wikimedia Commons, con licencias libres. Se escribe PROVENANCE.md con el
archivo de origen de cada una para poder citarlas.

Uso:
    uv run python scripts/fetch_product_images.py
"""

from __future__ import annotations

import json
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
WIDTH: Final = 480
# Pausa entre peticiones para no presionar a Wikimedia.
DELAY_SECONDS: Final = 0.25

_EXTENSIONS: Final = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".png",
}


def _source_url(file_name: str) -> str:
    quoted = urllib.parse.quote(file_name.replace(" ", "_"))
    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{quoted}?width={WIDTH}"


def _download(url: str) -> tuple[bytes, str] | None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read(), response.headers.get_content_type()
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def main() -> None:
    document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    products: list[dict[str, Any]] = document["products"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    provenance: list[str] = []
    saved = skipped = failed = 0
    for index, product in enumerate(products, start=1):
        entity = str(product["entity"])
        source_file = str(product["image_file"])
        existing = list(OUT_DIR.glob(f"{entity}.*"))
        if existing:
            skipped += 1
            provenance.append(f"| `{existing[0].name}` | {product['title']} | `{source_file}` |")
            continue

        result = None
        for attempt in range(3):
            result = _download(_source_url(source_file))
            if result is not None:
                break
            time.sleep(1.5 * (attempt + 1))
        if result is None:
            failed += 1
            print(f"  [{index}/{len(products)}] FALLO {entity} {source_file}", flush=True)
            continue

        body, content_type = result
        target = OUT_DIR / f"{entity}{_EXTENSIONS.get(content_type, '.jpg')}"
        target.write_bytes(body)
        saved += 1
        provenance.append(f"| `{target.name}` | {product['title']} | `{source_file}` |")
        if index % 25 == 0:
            print(f"  [{index}/{len(products)}] descargadas={saved} fallos={failed}", flush=True)
        time.sleep(DELAY_SECONDS)

    header = [
        "# Procedencia de las imágenes de producto",
        "",
        "Todas provienen de **Wikimedia Commons** y se descargaron una sola vez con",
        "`scripts/fetch_product_images.py`. Cada archivo conserva la licencia libre de su",
        "original; la página del archivo en Commons documenta autoría y licencia exacta:",
        "",
        "    https://commons.wikimedia.org/wiki/File:<archivo de origen>",
        "",
        "| Archivo servido | Producto | Archivo en Commons |",
        "| --- | --- | --- |",
    ]
    (OUT_DIR / "PROVENANCE.md").write_text("\n".join([*header, *provenance, ""]), encoding="utf-8")
    print(json.dumps({"descargadas": saved, "ya_estaban": skipped, "fallos": failed}))


if __name__ == "__main__":
    main()
