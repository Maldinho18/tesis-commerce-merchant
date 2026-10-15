# EC-GOV-06D-A / Merchant — Consulta autenticada de creación ACP

## A. Git inicial y final

Base exacta verificada: `71f9dba4de4fec96ceee0385c53f797ef9c99cb4`.
Inicialmente: `merchant/ec-mer-rec-01-recovery`, working tree limpio, origin
`https://github.com/Maldinho18/tesis-commerce-merchant.git` para fetch/push.
No había remoto org configurado; no se añadió ni se publicó en ninguno.
Se creó `merchant/ec-mer-rec-02-readonly-lookup` desde ese commit.
HEAD no cambia. Sin stage, commit, push, merge ni PR; no se usó main.

## B. Contratos inspeccionados

Se leyeron context.py, acp.py, checkout_creation.py, api.py, checkout.py,
contratos internos/primitivas, esquema ACP congelado, migraciones de contexto y
checkout, `013_acp_creation_recovery.sql`, las pruebas de recuperación y tracking,
y `docs/ec-mer-rec-01-results.md`.

El ámbito comercial real es `(run_id, actor_id, idempotency_sha256)` y ya tiene
UNIQUE. El snapshot ACP original y fingerprint se guardan juntos en checkout_sessions;
el trigger existente protege su inmutabilidad. No hace falta una migración ni un
índice nuevo. La guía PostgreSQL aplicada se limitó a revisar predicados e índices.
Un EXPLAIN real en el conjunto sintético produjo Index Scan con
`checkout_sessions_offer_lookup`: el planificador eligió su prefijo run_id para
estas filas pequeñas. El índice UNIQUE compuesto también existe. No se declara
un SLO ni se extrapola ese plan a volúmenes de producción.

## C. Endpoint y confianza

`POST /lab/recovery/checkout-creation/lookup`, privado por autenticación Bearer,
separado del ACP comercial y excluido de documentación/discovery pública.
Reutiliza trusted_context y exige `API-Version: 2026-04-17`.

Entrada estricta, sin campos adicionales:

```json
{
  "schema_version": "merchant-acp-creation-lookup/1",
  "idempotency_key_sha256": "0000000000000000000000000000000000000000000000000000000000000000"
}
```

El digest del ejemplo solo ilustra el formato. Se exige una cadena de 64 hexadecimales
minúsculos; no se normaliza ni acepta clave original, run, actor, checkout ID o
credenciales en el cuerpo. También se rechazan query parameters. Run y actor proceden
exclusivamente de la sesión autenticada; Request-Id procede del middleware del servidor,
no de una identidad elegida por el cliente. Token nuevo con mismo ámbito conserva acceso.

| HTTP / result | Significado |
| --- | --- |
| 200 / found | Fila del ámbito exacto con par ACP completo, formato y esquema verificables. |
| 200 / not_found | Esta consulta no observó una fila del ámbito/digest en su snapshot. No demuestra ausencia histórica ni autoriza POST. |
| 200 / unrecoverable | Existe una fila histórica con ambos campos ACP nulos. No se inventa un backfill ni se devuelve otro checkout. |
| 400 / error: invalid_api_version | Versión HTTP ausente/no admitida. |
| 401 / error: unauthenticated | Credencial ausente, vencida, revocada o inválida. |
| 422 / error: invalid_request | Cuerpo o query inválidos. El error no refleja el cuerpo ni valores sensibles. |
| 503 / error: lookup_unavailable | Error de autenticación contra DB, consulta, integridad o serialización. Nunca se convierte en not_found. |

Todas las variantes son modelos estrictos y versionados. Found/not_found/unrecoverable
forman una unión discriminada por result. Los errores tienen modelo cerrado separado,
con schema_version, result=error, code y request_id. Todas las respuestas de la ruta,
incluyendo fallos de dependencias/validación, llevan `Cache-Control: no-store`.
El wrapper de errores solo se aplica a esta ruta; no cambia los errores ACP existentes.

Found contiene únicamente ámbito, correlación, digest de clave, versión ACP,
fingerprint ACP original, checkout ID, respuesta original, perfil y digest de esa
respuesta. La respuesta es una afirmación del backend bajo una conexión al servidor
correcto; no es una prueba firmada ni acredita por sí sola autenticidad del transporte.

### Canonicalización e interoperabilidad

`original_response_profile = merchant-acp-original-response/1`:

1. Se opera sobre el valor JSONB original almacenado, no sobre el cuerpo HTTP crudo.
2. Objetos: claves string ordenadas lexicográficamente por puntos de código Unicode,
   recursivamente; arrays conservan su orden.
3. JSON compacto sin espacios ni newline final, con separadores `,` y `:`; cadenas
   con escapado JSON de Python json.dumps, ensure_ascii=False; codificación UTF-8 estricta.
4. No hay normalización Unicode (NFC/NFD se distinguen). Se admiten null, boolean,
   string, array, object e integers en [-9007199254740991, 9007199254740991].
   Se rechazan floats/NaN/infinities, claves no string y Unicode no codificable.
5. Perfil conservador: se rechazan claves de credenciales conocidas en cualquier
   nivel, sin quitarlas del objeto ni fabricar una representación filtrada. La lista
   exacta está en contracts/creation_lookup.py; un objeto no representable da 503.
6. Digest: SHA-256 de `b"merchant-acp-original-response/v1\0" + canonical_bytes`.
   `\0` es un byte NUL, no los caracteres backslash y cero. Salida hexadecimal minúscula,
   sin prefijo `sha256:`. El digest excluye correlación y metadatos externos a original_response.

Vector reproducible: `{"z":[2,1],"a":"café"}` produce bytes UTF-8 de
`{"a":"café","z":[2,1]}` y digest
`94e595e954f31d50753f13f634cae7761ce942aeabc9b37fefd39b5fe4da4348`.

El fingerprint ACP devuelto es el almacenado por el creador 71f9dba: dominio
`merchant-acp-create/v1` y perfil merchant-p0-create/1. Se comprueba formato,
no se reconstruye la petición para recalcularlo; esa comparación corresponde al
futuro Agent que conserve el original. No se presenta el nuevo digest de respuesta
como sello independiente frente a manipulación administrativa de la DB.

## D. Archivos

Modificado: `src/commerce_lab/api.py`, únicamente import y registro del router.

Nuevos:

- `src/commerce_lab/contracts/creation_lookup.py`: solicitudes, variantes, errores,
  canonicalización y verificación de respuesta original.
- `src/commerce_lab/creation_lookup.py`: consulta backend acotada y read-only.
- `src/commerce_lab/creation_lookup_api.py`: ruta privada y errores no reflectivos.
- `tests/test_creation_lookup.py`: 29 pruebas unitarias.
- `tests/integration/test_acp_creation_lookup.py`: 32 casos PostgreSQL/HTTP.
- Este informe.

No se cambian contratos ACP, acp.py, checkout.py, context.py, migraciones 001–013,
dependencias, uv.lock ni pruebas históricas. El entorno descartable/runner/logs están
solo en `.local/mer-rec-02-073d51ab/`, ignorado por Git.

## E. Invariantes SQL, autenticación y aislamiento

La conexión del lector inicia `SET TRANSACTION READ ONLY` y ejecuta un único SELECT
sobre checkout_sessions, con run/actor del servidor y digest como parámetros.
No hay FOR UPDATE, lock de creación, catálogo, prepare/create/update/cancel/complete,
constructor de respuesta, generación de clave ni modificación de columnas ACP.
También se coteja el ámbito de la fila devuelta antes de construir una variante.

El par nulo/nulo es unrecoverable. Cualquier par incompleto, digest malformado,
respuesta inválida para el esquema congelado, ID o versión inconsistente es error
de integridad, nunca found. La respuesta original se valida sin reconstruirla;
el checkout vigente no se consulta ni se confunde con el snapshot de creación.

La autenticación ya existente comprueba hash de token, vigencia, revocación y
correspondencia con experiment_runs. La consulta hereda ese punto de autenticación;
no añade garantía de revocación concurrente a mitad de petición.
El middleware existente sigue generando correlación. Esta ruta lab no se clasifica
como una operación comercial ni escribe request_observations. No se registran cuerpos.

## F. Resultados y reproducción

Entorno real: Windows 11 10.0.26220, Python 3.12.6, PostgreSQL 17.2, timezone SQL UTC.
No se declara validación Linux, despliegue ni integración Agent–Merchant.
Clúster nuevo: `.local/mer-rec-02-073d51ab/pgdata`, solo 127.0.0.1:62281,
base tesis_lab y rol sintético exclusivo. Nunca se conectó a 55432/55433 ni bases operativas.

El runner fija el DSN aislado, desactiva dotenv/proveedores, comprueba SHOW data_directory
y timezone antes de ejecutar pruebas, bloquea conexiones PG fuera de ese puerto/base,
sockets externos/operativos y escrituras al repositorio fuera de la carpeta nueva.
Los workers heredados usan el mismo DSN y comprueban el clúster antes de operar.
Las suites que mutan esta misma base deben ejecutarse secuencialmente.

| Control | Resultado |
| --- | --- |
| Tracking sobre base inicialmente vacía | 2 passed in 0.57s; sin skips. Incluye primera aplicación, segunda idempotente y control de canonicalización LF/CRLF con cambio real de contenido. |
| Unitarios nuevos, aislados | 29 passed in 0.65s. |
| Nuevos unitarios + integración finales | 61 passed, 2 warnings in 40.46s; ninguna omisión. |
| Regresiones de creación/recovery | 44 passed, 2 warnings in 43.58s; ninguna omisión. |
| `uv run ruff format --check .` | 69 files already formatted. |
| `uv run ruff check .` | All checks passed! |
| `uv run pyright` | 0 errors, 0 warnings, 0 informations. |
| Suite general protegida secuencial | 272 passed, 1 skipped, 2 warnings in 266.52s. |
| `git diff --check` | Sin errores; se comprueban también los archivos nuevos contra NUL, sin stage. |

La primera corrida general se lanzó erróneamente en paralelo con las regresiones
contra el mismo clúster: 5 failed, 267 passed, 1 skipped, 2 warnings in 168.58s.
Los cinco fallos fueron diferencias entre snapshots globales mientras la otra suite
sembraba episodios/sesiones. No se cambió código ni se redujeron aserciones para
resolverlos: se corrigió la planificación y se repitió la general en exclusividad.
La shell de arranque en Windows dejó comandos pendientes hasta el cierre del
servidor: su intento tardío de createdb recibió connection refused después del
stop. La base se había creado expresamente en otra invocación antes de las pruebas
de migraciones. Esa incidencia del harness no fue una corrida de tests ni motivó
conexiones a otra base; el clúster terminó detenido.

Advertencias conocidas: StarletteDeprecationWarning por TestClient/httpx y
DeprecationWarning por anyio.abc.BlockingPortal. No se cambiaron dependencias.
El único skip esperado en la general es el test que exige base vacía: ya pasó primero
en este clúster. No se oculta con ese skip un fallo de checksums. El test actual del
commit base ya usa lectura/canonicalización LF, y su comprobación sobre base nueva
pasó sin modificar fuentes SQL ni checksums registrados.

Se auditaron 11 versiones registradas (numeración hasta 013): 013 aparece exactamente
una vez y coincide con migration_sha256. Checksum canónico 013:
`ff9d9833f5d221c2f51cfdc9df34d9b499fb0e3e3240f1c332af08401669d70a`.

Comandos, desde Merchant con PYTHONDONTWRITEBYTECODE=1 y UV_NO_SYNC/UV_OFFLINE:

```text
.venv/Scripts/python.exe -B .local/mer-rec-02-073d51ab/run_tests.py tests/integration/test_migration_tracking.py -q --tb=short -p no:cacheprovider --basetemp=.local/mer-rec-02-073d51ab/migrations-first
.venv/Scripts/python.exe -B .local/mer-rec-02-073d51ab/run_tests.py tests/test_creation_lookup.py tests/integration/test_acp_creation_lookup.py -q --tb=short -p no:cacheprovider --basetemp=.local/mer-rec-02-073d51ab/new-final
.venv/Scripts/python.exe -B .local/mer-rec-02-073d51ab/run_tests.py tests/test_acp_creation.py tests/integration/test_acp_creation_recovery.py -q --tb=short -p no:cacheprovider --basetemp=.local/mer-rec-02-073d51ab/recovery-regressions
.venv/Scripts/python.exe -B .local/mer-rec-02-073d51ab/run_tests.py -q --tb=short -p no:cacheprovider --basetemp=.local/mer-rec-02-073d51ab/full-sequential
uv run ruff format --check .
uv run ruff check .
uv run pyright
git diff --check
```

Repetir tracking vacío requiere otro clúster nuevo; los demás comandos requieren
arrancar expresamente este clúster aislado o ajustar el runner para otro igualmente
verificado. No reutilizar ni apuntar estos tests a una base operativa.

## G. Escenarios negativos, concurrencia y fallos

| Requisito | Evidencia |
| --- | --- |
| Sesión válida y renovada | found con ámbito servidor, mismo snapshot/fingerprint; Request-Id de cliente no otorga identidad. |
| Token vencido/revocado/ausente | 401 tipado, no-store y ninguna mutación de tablas. |
| Otro actor/run; hash desconocido | not_found en su propio ámbito, sin checkout ni respuesta ajenos. |
| Hash inválido, versión desconocida, extra authority/secret fields, query | Rechazo estricto; valores sensibles no reflejados. |
| Histórico interno sin par ACP | unrecoverable, sin checkout ID ni backfill. |
| Precio, nombre, revisión o disponibilidad modificados | Se conserva íntegramente el JSON original; cero mutaciones durante lookup. |
| Cancelación posterior | found devuelve creación not_ready_for_payment; estado actual canceled permanece intacto. |
| ID/fingerprint/version/digest | Modelos negativos y comparación real con ID/fingerprint almacenados; la DB conserva además sus constraints originales. |
| Respuesta corrupta o campo de credencial inesperado | 503, no found ni not_found, sin filtrar contenido. Fault injection solo sobre filas de la DB descartable. |
| Error interno de autenticación/lector | 503 tipado no reflectivo, nunca falsa ausencia. |
| Cuatro consultas concurrentes | Misma evidencia, cuatro correlaciones servidor distintas; ninguna tabla pública cambia. |
| Creación aún no confirmada | Un POST explícito de fixture queda antes de commit; el lookup observa not_found. Tras liberar ese mismo commit, found. Prueba real de que not_found no acredita ausencia. |
| Sin operaciones comerciales internas | Se prohíben los métodos de adaptador/servicio y constructor/catálogo durante lookup; found sigue funcionando. |
| Read-only real | Probe de conexión consulta SHOW transaction_read_only dentro del SELECT: on. |

Los snapshots comparan todas las tablas públicas, incluidos número de checkouts,
estados, revisiones y columnas originales. La prueba concurrente solo repite consultas;
no provoca un segundo POST. Las creaciones/cancelaciones de setup son operaciones
explícitas de fixture, no efectos causados por lookup ni autorización derivada de este.

## H. Límites

No replay, reintentos, GET de estado vigente, actualización, cancelación, payment,
completion, firmas ni autorización de continuación. No se garantiza retención futura,
ausencia de creaciones fuera de esta DB o ausencia de un POST todavía en tránsito.
Una fila ausente no es prueba verificable de ausencia. Un HTTP 200 no significa allow.
El digest no es firma ni prueba independiente contra un administrador que altere DB
y esquema. El transporte y la comparación con el envelope Agent quedan para 06D-B/C.
No se modificaron Agent, Lab, PSP, UI/React/SSE, AP2, B0, Notion ni trabajo ajeno.
No se activó enforce ni se reejecutó el baseline experimental.

## I. Dictamen y preservación

**READY_FOR_REVIEW** para EC-GOV-06D-A Merchant. Se detiene para auditoría
independiente, sin commit, push, merge ni PR. No se autoriza ni implementa 06D-B/C.

Estado final:

```text
## merchant/ec-mer-rec-02-readonly-lookup
 M src/commerce_lab/api.py
?? docs/ec-gov-06d-a-merchant-lookup-results.md
?? src/commerce_lab/contracts/creation_lookup.py
?? src/commerce_lab/creation_lookup.py
?? src/commerce_lab/creation_lookup_api.py
?? tests/integration/test_acp_creation_lookup.py
?? tests/test_creation_lookup.py
```

El único diff de archivos previamente versionados es api.py: cuatro inserciones.
Índice vacío y HEAD base intacto. De los 267 archivos originales, 266 conservan
exactamente sus bytes SHA-256; la única excepción es ese registro de router previsto.
Esto preserva fuentes ACP/AP2, migraciones, contratos comerciales, fixtures, uv.lock
y resultados B0. No se alteraron archivos locales anteriores del directorio .local.
La revisión de whitespace incluye los seis archivos nuevos contra NUL. Git solo
advierte la posible conversión futura LF a CRLF en esos archivos por su configuración
existente; no se modificó core.autocrlf ni se normalizó el repositorio.

El clúster nuevo se detuvo al finalizar: pg_ctl confirmó server stopped y
posteriormente no server running. Se conservan datos/runner/logs ignorados para
auditoría; no queda un servicio de pruebas activo ni se tocó el servidor operativo.
