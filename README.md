# Tesis Commerce Merchant

Merchant independiente para la tesis: FastAPI → adaptador ACP REST → catálogo y
checkout autoritativos en PostgreSQL. El Buyer Agent, el LLM y el cliente HTTP ACP
viven en otro repositorio. El namespace Python sigue siendo `commerce_lab`.

## Perfil P0 implementado

- El surtido actual importado contiene más de 140 smartphones y más
  de 300 variantes. La importación ocurre una sola vez; el catálogo persistente
  del merchant conserva los cambios de precio e inventario entre reinicios.
  Cada variante del feed usa el ID aceptado por `POST /checkout_sessions`.
- Discovery público `GET /.well-known/acp.json`, ACP `2026-04-17`, transporte
  REST y solo servicio `checkout`. URL local predeterminada:
  `http://127.0.0.1:4120`. `ACP_API_BASE_URL` es configurable; fuera de
  localhost exige HTTPS.
- Checkout ACP create/get/update/cancel, Bearer sintético, API-Version,
  idempotencia persistente, aislamiento por actor y episodio, y validación de
  los esquemas ACP congelados. Buyer y fulfillment ya están implementados:
  `prepared` se publica como `not_ready_for_payment` y, tras completar buyer,
  fulfillment y selección de envío, pasa a `ready_for_payment`. Todas las
  respuestas anuncian la capability P0 `tesis_sandbox`, con endpoints públicos
  `/payment-handlers/tesis-sandbox/spec`, `/config-schema` e
  `/instrument-schema`. El handler usa `requires_delegate_payment=true` y acepta una
  credencial opaca `vt_*` emitida por el proveedor sandbox independiente. Update selecciona la
  única opción de envío; cancel acepta cuerpo vacío o `intent_trace.reason_code`.
- EC-06A añade `POST /checkout_sessions/{id}/complete` para el subconjunto
  sintético `tesis_sandbox`. Envía el token opaco al proveedor de pagos propio para confirmar
  monto, moneda, checkout y resultado; no deduce el resultado del token ni mueve dinero real.
  El éxito revalida términos, decrementa inventario y crea exactamente una
  Order en la misma transacción; el checkout queda `completed`. Declines son
  deterministas y errores temporales devuelven `503` sin efectos comerciales.
  La operación es idempotente y el permalink público `/orders/{order_id}`
  muestra únicamente datos sanitizados.
- `GET /feeds/current` publica una instantánea completa del Product Feed desde
  PostgreSQL. Su forma `{metadata, products}` es una ruta de publicación propia,
  no un endpoint normativo de ACP. Feed API incremental no está implementada.
- Perfil AP2 v0.2 Human Present: `GET /checkout_sessions/{id}/ap2/checkout-jwt` emite un JWT ES256
  firmado por el merchant para un checkout `ready_for_payment` del mismo actor/episodio.
  `GET /.well-known/ap2/jwks.json` publica la clave verificadora. Configure
  `MERCHANT_AP2_PRIVATE_KEY_PEM` con una clave EC P-256 privada (PEM, saltos de línea reales o
  `\\n`); sin ella ambos endpoints fallan cerrado. El JWT dura cinco minutos y contiene la
  instantánea ACP completa. Con `MERCHANT_AP2_REQUIRED=true` y
  `MERCHANT_AP2_AGENT_JWK_JSON` fijada, `/complete` queda bloqueado y
  `POST /checkout_sessions/{id}/ap2/complete` verifica Checkout Mandate, hash, instantánea y
  revisión antes de completar. Devuelve un Checkout Receipt firmado. Las rutas `/ap2/*` son
  puentes experimentales sobre ACP, no rutas estándar ACP ni conformidad AP2 integral.

Los errores públicos ACP usan códigos en minúsculas, incluidos
`missing_api_version`, `unsupported_api_version` y `payment_declined`.
Los códigos comerciales internos conservan sus nombres tipados en mayúsculas;
la API los traduce al contrato público.

La representación interna `Offer` es un snapshot de variante: `Offer.id` →
`Variant.id`, `Offer.product_id` → `Product.id`, `Offer.name` → títulos,
`Offer.pricing.items_total_minor` → `Variant.price.amount`. Hay una variante
por producto en los experimentos P0; el catálogo actual agrupa variantes.
`Offer.product_status` guarda explícitamente `active` o `inactive` en el
snapshot autoritativo. La disponibilidad de compra se comunica en
`Variant.availability`. El esquema Product congelado no tiene campo `status`,
por lo que no se inventa uno en el JSONL. Las URLs `merchant.example.test`
son identificadores sintéticos, no páginas comerciales reales.

**Moneda:** dominio interno, checkout y Discovery usan `cop`; el esquema Feed
usa `COP` en `Price.currency`. La conversión de casing es explícita en el
exportador. Todos los importes son enteros de centavos; no hay `float`.
El precio del feed es solo el ítem: el envío sintético determinista aparece
separado en checkout. El impuesto está incluido en el precio del ítem; no hay
motor fiscal. El feed es informativo: checkout vuelve a leer el snapshot
autoritativo en PostgreSQL y recalcula stock y totales. Create requiere una
unidad, rechaza stock cero y **no reserva ni reduce inventario**.

## Preparación y exportación

Se requieren Python 3.12, uv y Docker Compose. PostgreSQL merchant escucha
solo en `127.0.0.1:55433`; FastAPI solo en `127.0.0.1:4120`.

```powershell
uv sync --frozen
docker compose up -d --wait postgres
uv run python -m commerce_lab.db migrate
uv run python -m commerce_lab.managed_catalog import-current
uv run uvicorn commerce_lab.api:app --host 127.0.0.1 --port 4120
```

`import-current` solo llena un merchant vacío; repetirlo no sobrescribe precios
ni stock. Para editarlos use `uv run python -m commerce_lab.managed_catalog
update-offer VARIANT_ID --price-minor 123450000 --stock 5`. Los importes son
centavos de COP. `GET /feeds/current` refleja los cambios sin reexportar archivos;
el checkout revalida el snapshot autoritativo. La ruta no implementa la API
incremental de feeds de ACP.

Por compatibilidad con las claves foráneas existentes de checkout, el catálogo
administrado ocupa un contexto persistente `variant='merchant'` en las tablas
actuales. No se recrea como episodio de prueba en cada arranque; los episodios
experimentales siguen separados.

El exportador `python -m commerce_lab.feed export` permanece para experimentos
reproducibles con episodios P0; no participa en el flujo normal del merchant.

Para probar checkout protegido,
`uv run python -m commerce_lab.db issue-session RUN_ID ACTOR_ID` emite un Bearer
sintético solo en consola local.
No lo copie a Git, artefactos ni logs. No hay endpoint público para emitirlo.
Las migraciones merchant son `001`, `002`, `003`, `004`, `007`, `008`, `009`, `010`, `011` y `012`;
`005`/`006` pertenecen al carril live/browser legado y no se ejecutan aquí. Los
episodios experimentales históricos no se reescriben.

El outbox webhook usa `WEBHOOK_RECEIVER_URL` y `MERCHANT_WEBHOOK_SECRET` solo
para el dispatcher local. La creación de una Order y su entrega `order_create`
se registran en la misma transacción; si falta configuración, la entrega queda
pendiente sin intentar HTTP. `python -m commerce_lab.db order-update RUN_ID
ACTOR_ID ORDER_ID` produce la transición sintética P0 `confirmed` →
`processing`, y `python -m commerce_lab.db webhook-dispatch` procesa entregas
vencidas con un máximo de cinco intentos.

Para completar compras configure `PAYMENT_PROVIDER_URL`, `PAYMENT_MERCHANT_BEARER_TOKEN` y
`PAYMENT_MERCHANT_ID` con el proveedor sandbox separado. Sin esa credencial, `/complete` falla
cerrado con `PROVIDER_UNAVAILABLE`; el merchant nunca acepta un token por su prefijo como
evidencia de pago.

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

Feed API incremental y frontend no están implementados. El handler sandbox no procesa
credenciales reales ni dinero real; este subconjunto no afirma conformidad ACP integral.

## Despliegue de la demo sintética

El `Dockerfile` ejecuta `scripts/railway_bootstrap.py` antes de servir la API. En una instancia
PostgreSQL dedicada y privada, configure `DATABASE_URL` para la base `tesis_lab`, y
`BOOTSTRAP_ADMIN_DATABASE_URL` para la base administrativa inicial si `tesis_lab` aún no existe.
`MERCHANT_ALLOW_REMOTE_DB=true` permite únicamente hosts `*.railway.internal`; en local sigue
exigiéndose loopback. El bootstrap migra, importa el surtido solo si no existe un catálogo
administrado y registra el hash de `MERCHANT_AGENT_BEARER_TOKEN` sin imprimir el Bearer. Reiniciar
no restablece precios ni stock.

Configure `ACP_API_BASE_URL` con el origen HTTPS público del merchant. El agente debe usar ese
mismo origen como `MERCHANT_BASE_URL` y el mismo Bearer. `PAYMENT_PROVIDER_URL` y
`PAYMENT_MERCHANT_BEARER_TOKEN` apuntan al proveedor sandbox independiente;
`PAYMENT_MERCHANT_ID` debe coincidir en los tres servicios. Para entregar webhooks configure
`WEBHOOK_RECEIVER_URL` con el origen HTTPS del agente (sin la ruta) y comparta
`MERCHANT_WEBHOOK_SECRET` solo con él. El outbox requiere ejecutar su dispatcher; arrancar la API
no lo despacha automáticamente.

El episodio P0 usa tiempo sintético `2026-09-10T14:00:00Z`; agente y proveedor necesitan sus
relojes sandbox correspondientes para no tratar como vencido el checkout. La configuración
completa de la demo está en el [runbook del agente](https://github.com/YairAndrade1/tesis-commerce-agent/blob/main/docs/deployment-railway.md).
