# Imagen de despliegue del merchant ACP. El bundle ACP congelado vive en /app/vendor.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.15 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

COPY vendor ./vendor
COPY migrations ./migrations
COPY scripts ./scripts

ENV PATH="/app/.venv/bin:$PATH"
# El arranque migra y siembra una sola vez antes de servir; ver scripts/railway_bootstrap.py.
CMD ["sh", "-c", "python scripts/railway_bootstrap.py && uvicorn commerce_lab.api:app --host 0.0.0.0 --port ${PORT:-8080}"]
