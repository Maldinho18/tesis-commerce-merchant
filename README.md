# Tesis Commerce Merchant

Merchant experimental independiente para la tesis. Este repositorio contiene
FastAPI → adaptador ACP REST → dominio de catálogo/checkout → PostgreSQL. El
Buyer Agent, el LLM y el cliente HTTP ACP viven fuera de este repositorio.

La extracción conserva el comportamiento del checkpoint histórico
`Maldinho18/tesis-commerce-lab@e6a7cb5` (rama
`ecommerce/ec-03-checkout-lifecycle`). El namespace Python sigue siendo
`commerce_lab` de forma temporal para mantener la equivalencia. El protocolo
ACP queda fijado en `2026-04-17`; el snapshot vendorizado está intacto.

## Alcance implementado

- Catálogo experimental temporal de cinco ofertas Sonora, con IDs, precios COP,
  inventario y snapshots conocidos.
- Bearer sintético asociado a actor y episodio; `API-Version: 2026-04-17`.
- `POST /checkout_sessions`, `GET /checkout_sessions/{id}`,
  `POST /checkout_sessions/{id}` y `POST /checkout_sessions/{id}/cancel`.
- Idempotencia persistente por endpoint, aislamiento de actor/episodio,
  validación contra los esquemas ACP y concurrencia con locks PostgreSQL.
- `GET /health/live` y `GET /health/ready`.

Update acepta solo la selección explícita de la única opción de envío disponible
para un ítem. Cancel acepta cuerpo vacío o `intent_trace.reason_code`. El estado
interno `prepared` se expone como `not_ready_for_payment`; `expired` y
`canceled` conservan esos nombres ACP.

## Preparación local

Se requieren Python 3.12, uv y Docker Compose. Los puertos del merchant son
independientes de los del repositorio de origen.

```powershell
uv sync
docker compose up -d --wait postgres
uv run python -m commerce_lab.db migrate
uv run python -m commerce_lab.db seed
uv run uvicorn commerce_lab.api:app --host 127.0.0.1 --port 4120
```

La base sintética usa `127.0.0.1:55433/tesis_lab` por defecto; copie
`.env.example` a `.env` solo si necesita ajustar parámetros locales.
La semilla imprime `run_id`; para probar endpoints protegidos, el comando
local `uv run python -m commerce_lab.db issue-session RUN_ID ACTOR_ID`
emite un Bearer sintético **solo a la consola local**. No lo guarde en
artefactos o logs. No hay endpoint público que emita sesiones.

La secuencia merchant ejecuta `001`, `002`, `003`, `004` y `007`.
`007_checkout_mutations.sql` depende de checkout y contexto de ejecución,
pero no de `005`/`006`: estas últimas son exclusivas del carril
live/browser y se omiten. Se mantienen los números históricos para que la
diferencia respecto de la fuente sea explícita.

## Verificación

```powershell
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
$env:RUN_DB_INTEGRATION="1"
uv run pytest tests/integration
Remove-Item Env:RUN_DB_INTEGRATION
```

El PRD P0 aún requiere discovery, Product Feed, al menos diez productos,
perfil USD, fulfillment y buyer completos, `ready_for_payment`, payment
sandbox, complete, order, order permalink y webhooks. Este repositorio no
afirma conformidad ACP integral, ni implementa dinero real o pagos.
