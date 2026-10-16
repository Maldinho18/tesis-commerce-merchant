# EC-MER-07B-A — Precondición atómica D17

## A. Estado Git y repositorios

Preflight validado: árbol e índice limpios en `merchant/ec-mer-rec-02-readonly-lookup`, HEAD `c5bd8113998f26928f7d2b62771285fe4040d07f`; rama nueva ausente. Se creó desde esa base `merchant/ec-mer-07b-d17-atomic-precondition`. Origin fetch/push sigue siendo `https://github.com/Maldinho18/tesis-commerce-merchant.git`. No hay stage, commit, push, merge ni PR. HEAD conserva la base.

Cambios finales previstos: cinco archivos versionados modificados y ocho nuevos (incluido este informe). Agent no se modificó ni ejecutó: sus 335 archivos versionados conservan el agregado SHA-256 inicial `dc97facbf20a96a055448e2073ebc4db9c3f3a5410995dfb2b9bc77697a13fc2` (ordenar rutas, unir `ruta:sha256` con LF y calcular SHA-256). Su informe pendiente conserva `3dc4d9ab0ea8bfc64efc007958b89c3c5e49316e5c4b82143d02787da78e1a73`. No se ejecutó B0 ni se modificaron datos históricos, PSP o archivos de Yair.

Estado final del árbol (índice vacío; todos los cambios sin stage):

```text
## merchant/ec-mer-07b-d17-atomic-precondition
 M src/commerce_lab/acp.py
 M src/commerce_lab/api.py
 M src/commerce_lab/checkout.py
 M src/commerce_lab/db/core.py
 M tests/integration/test_acp_creation_recovery.py
?? docs/ec-mer-07b-a-d17-atomic-precondition-results.md
?? migrations/014_guarded_acp_creation.sql
?? src/commerce_lab/contracts/guarded_creation.py
?? src/commerce_lab/guarded_creation.py
?? src/commerce_lab/guarded_creation_api.py
?? tests/integration/guarded_cluster.py
?? tests/integration/test_guarded_creation.py
?? tests/test_guarded_contract.py
```

Diff versionado: 5 archivos, 140 inserciones y 57 eliminaciones; los ocho nuevos se detallan en D y no aparecen en ese stat hasta hacer stage (no autorizado).

## B. Defecto de contrato comprobado

`ACPCheckoutAdapter.create` obtenía la revisión esperada desde la oferta que acababa de leer Merchant, no desde la observación del agente. El cuerpo ACP congelado no tiene esa precondición. `CheckoutService._validate_offer` comprobaba revisión, stock, destino y expiración, pero no actividad. Por tanto, una observación anterior no condicionaba la creación; una modificación de precio sin revisión tampoco era detectada por una comparación exclusiva de revisión.

El replay ACP original se resolvía antes del catálogo y guardaba la respuesta original. Se conserva esa propiedad; no se reconstruyen respuestas históricas con términos nuevos.

## C. Opciones consideradas y contrato seleccionado

| Opción | Evaluación |
| --- | --- |
| Consulta de oferta previa al POST | No protege la ventana hasta el commit |
| Añadir campos al ACP congelado o headers ignorados | Rompe o falsea el contrato |
| Segundo algoritmo de creación | Duplica locks, fingerprints y persistencia |
| Ruta privada versionada con ACP anidado y creación compartida | Seleccionada: una transacción y el algoritmo original |

`POST /lab/governance/checkout-creation/guarded` queda fuera de discovery/OpenAPI público. Usa Bearer, API-Version e Idempotency-Key existentes. El cuerpo estricto contiene `schema_version=merchant-guarded-acp-create/1`, `acp_request`, `offer_id`, `expected_offer_revision`, `offer_snapshot_profile=merchant-offer-snapshot/1` y `offer_snapshot_sha256`. No acepta run, actor, autoridad o políticas en el cuerpo. El ámbito proviene de la sesión autenticada por Merchant.

Perfil de digest: Offer completo validado, incluyendo defaults, revisión, nombre, precios, actividad, stock, destino, observación y expiración; no incluye `updated_at` SQL. Serialización canónica existente, claves ordenadas, secuencias conservadas y dominio `merchant-offer-snapshot/v1` seguido de byte NUL. Es conservador: rechaza también cambios de metadatos. No constituye un digest material mínimo ni define un TTL nuevo.

Se conserva exactamente la presencia/omisión de campos del ACP mediante `exclude_unset=True`, y se reutiliza su fingerprint original. La identidad adicional del intento usa dominio `merchant-guarded-acp-attempt/v1` y los campos de guard junto al fingerprint ACP. La clave en claro no se persiste en la prueba.

201 significa `created`; 200, `replayed`. La prueba tipada contiene revisión y digest aceptados, `checked_at`, fingerprint del guard y un `CreationFound` histórico sin cambiar su contrato 06D-A. El Request-Id exterior pertenece a la consulta actual; la prueba conserva el de creación. La prueba y el registro de rechazo tienen dominios SHA-256 separados.

409 indica rechazo semántico/conflicto; 401 autenticación; 422 entrada; 400 versión API; 503 fallo inesperado. Errores tipados sanitizados y `Cache-Control: no-store`. No se reflejan tokens, claves, cuerpos ni errores SQL. Un 503 es incertidumbre, no demostración de ausencia de efectos.

## D. Implementación, archivos y migraciones

| Archivo | Cambio |
| --- | --- |
| `src/commerce_lab/acp.py` | Extrae creación transaccional compartida; hook bajo lock; impide reutilizar intentos guardados rechazados |
| `src/commerce_lab/api.py` | Importa y registra router privado |
| `src/commerce_lab/checkout.py` | Rechaza producto inactivo nuevo; impide bypass interno de clave rechazada, después del replay existente |
| `src/commerce_lab/db/core.py` | Registra migración 014 |
| `migrations/014_guarded_acp_creation.sql` | Tablas aditivas de prueba aceptada y rechazo semántico inmutable |
| `src/commerce_lab/contracts/guarded_creation.py` | Contratos estrictos/versionados, perfiles y digests |
| `src/commerce_lab/guarded_creation.py` | Precondición, transacción, replay, validación histórica y rechazo durable |
| `src/commerce_lab/guarded_creation_api.py` | Endpoint privado y errores sanitizados |
| `tests/test_guarded_contract.py` | 14 casos unitarios |
| `tests/integration/test_guarded_creation.py` | 44 casos con PostgreSQL real |
| `tests/integration/test_acp_creation_recovery.py` | Adapta fixture de upgrade pre-013 sin invocar runtime contra esquema incompleto; conserva aserciones |
| `tests/integration/guarded_cluster.py` | Runner opt-in de clúster nuevo, identidad, aislamiento y evidencia |
| `docs/ec-mer-07b-a-d17-atomic-precondition-results.md` | Este informe |

Migración 014: `guarded_checkout_creations` enlaza run/actor/key hash, checkout, fingerprint y prueba/digest; PK por intento y unicidad por checkout, FK y comprobaciones de ámbito. Trigger vincula respuesta/fingerprint ACP y revisión al snapshot original. `rejected_guarded_checkout_attempts` fija la identidad de un rechazo conocido sin crear checkout. Triggers impiden UPDATE/DELETE y que un intento sea simultáneamente aceptado y rechazado. No se modifican migraciones históricas ni checksums existentes. Son 12 migraciones reales en la lista histórica; la numeración no es contigua.

SHA-256 de bytes locales (antes de cualquier conversión de EOL de Git):

| Archivo | SHA-256 |
| --- | --- |
| `src/commerce_lab/acp.py` | `1a45e28e390072fc17b9d841fa1d55378249ad0b997cec7aff465f1a6940ec59` |
| `src/commerce_lab/api.py` | `a35da18dfad12d8e9c12c06348c643499a0a387ae7d2c31663e3928ea6ed3b30` |
| `src/commerce_lab/checkout.py` | `3c71ca6b6defb470ab61afe92627254b66f3d65c6714bf54e7bd71d96ea101f9` |
| `src/commerce_lab/db/core.py` | `036afb91c9c4b74eb9e924a3480ed56c8d22ff14efac3082fa307f365e33e69f` |
| `migrations/014_guarded_acp_creation.sql` | `3d78fe760d586c9b4ba058fe3376d0fb8d9c8db2dcdff745624dccd74394d536` |
| `src/commerce_lab/contracts/guarded_creation.py` | `84665bfbd62899710156d0ea106c9aaea5e6387ac3f791b8467a6b7721e0352c` |
| `src/commerce_lab/guarded_creation.py` | `b5ccd7372620bc2bdc5bc5c26fe39fc841c9c1582d0652584f2a94c87ba8d6b0` |
| `src/commerce_lab/guarded_creation_api.py` | `3e542fa5f16b0cad5ab8e92ecfcea2bb18e1f1457558f2378580870324a4d6d6` |
| `tests/test_guarded_contract.py` | `51b2841fdee475387689e0bc4d72025fddca7d673c90252101afe245acd204d1` |
| `tests/integration/test_guarded_creation.py` | `c61a5637b245a434a237561d5c4561df70caa88a9a63f9a0bfef3fee15df05cf` |
| `tests/integration/guarded_cluster.py` | `1c094acd45cc110fe48e7f1ec8da4c0ca20b853451b2a477dfea51d77b8cff15` |

| `tests/integration/test_acp_creation_recovery.py` | `c766e7525b39c90ba5301273f52c684044df4b577f57dcb410454e2665169e12` |

Este informe no incluye su propio hash autorreferencial. Los 21 archivos protegidos de vendor, migraciones históricas, pyproject y lock se compararon contra blobs HEAD sin diferencias de contenido (normalizando únicamente CRLF/LF para esa comparación). Git solo muestra los cinco archivos versionados autorizados; no se normalizó el repositorio.

## E. Transacción, idempotencia y recuperación

Orden: autenticación existente → ámbito servidor → run FOR SHARE → advisory lock por run/actor/key hash compartido con ACP → rechazo/prueba/replay antes del catálogo → lectura de oferta FOR SHARE → comparación de identidad/revisión/digest y vigencia → preparación original → respuesta ACP original y prueba → última comprobación temporal → commit → respuesta.

Los locks de oferta permanecen hasta commit. El run lock estabiliza el reloj sintético; para variante merchant se usa `clock_timestamp()`, evitando autorizar con `now()` anterior a una espera. Se rechaza observación futura y expiración. `checked_at` acredita comprobación, no vigencia indefinida después del commit ni identidad criptográfica externa.

Un savepoint engloba toda creación provisional. Rechazo semántico revierte checkout/ACP/prueba y confirma únicamente la identidad del intento rechazado en la transacción exterior. Repetición exacta devuelve rechazo histórico; otra condición con esa clave es conflicto. También se impide bypass mediante ACP público (su código HTTP de conflicto previo sigue siendo 422) o preparación interna. Peticiones malformadas/no autenticadas no reservan clave. Fallos inesperados revierten toda la transacción, sin inventar un rechazo conocido.

Éxito seguido de caída antes de respuesta: checkout, respuesta ACP y prueba se confirman conjuntamente. Repetición explícita del guard original devuelve la misma prueba histórica sin catálogo y sin segunda sesión. Condición distinta produce conflicto. Una creación anterior no guardada no adquiere autorización retrospectiva. El replay histórico público/interno existente se consulta antes de las nuevas comprobaciones, conservando su comportamiento.

El lookup 06D-A sigue devolviendo la respuesta ACP original; no incorpora silenciosamente la prueba D17. Repetir el POST guardado no es recuperación de solo lectura: si no existe historia podría crear. Por ello NO habilita reenvíos automáticos desde Agent; hace falta una consulta autenticada de prueba sin efectos para esa recuperación.

## F. Validación ejecutada

Entorno real: Windows, Python 3.12.6, PostgreSQL 17.2, psycopg 3.3.5, FastAPI 0.141.1, httpx 0.28.1, Pydantic 2.12.5, pytest 9.0.2. No se declara ejecución Linux.

Comandos finales desde raíz (dependencias existentes, sin sync ni red):

```powershell
$env:UV_NO_SYNC='true'
$env:UV_OFFLINE='true'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:RUFF_NO_CACHE='true'
uv run ruff format --check .
uv run ruff check .
uv run pyright
$env:RUN_MER07_REAL='1'
uv run python -B tests/integration/guarded_cluster.py
git diff --check
git diff --cached --stat
```

El runner ejecuta primero las dos pruebas de migración sobre clúster vacío; después los dos archivos nuevos y cuatro suites ACP/recuperación/lookup; después `pytest` general con integración habilitada, sin cacheprovider y sin plugins externos. Captura conteos, advertencias y fallos sanitizados en `validation.json`. No cambia Settings/runtime productivo: impide lectura dotenv en el proceso de pruebas, elimina variables externas y verifica DSN, identidad, rol y directorio antes de migrar/sembrar y en cada conexión.

Clúster final: `.local/mer07-4e06175d50d8/pgdata`, loopback 50137, base sintética `tesis_lab`, rol `mer07_app` sin superusuario/CREATEDB/CREATEROLE. HBA solo loopback para roles sintéticos; trust local no constituye configuración productiva. Puertos habituales de servicios excluidos. No se conectó a una base operativa.

Resultados de cierre (2026-10-16):

| Control | Resultado | Duración medida |
| --- | --- | --- |
| Migración desde base vacía, repetición y checksums | 2 passed, 0 failed, 0 skipped, 0 warnings | 0.794474 s |
| Nuevos casos y regresiones ACP/recuperación/lookup | 163 passed, 0 failed, 0 skipped, 2 warnings | 175.010043 s |
| Suite general con integración | 330 passed, 0 failed, 1 skipped, 0 warnings | 298.271223 s |
| Ruff format | 77 files already formatted | No se mide rendimiento |
| Ruff check | All checks passed! | No se mide rendimiento |
| Pyright | 0 errors, 0 warnings, 0 informations | No se mide rendimiento |
| git diff --check | Sin errores de whitespace | No se mide rendimiento |
| Índice | Vacío | No aplica |

La única omisión general es `test_fresh_database_tracks_each_migration_once`: en esa fase la base ya tiene migraciones. Esa misma prueba sí se ejecutó y aprobó al inicio sobre base vacía junto con la prueba canónica de checksum. No se omitió ninguna prueba nueva. Los conteos de fases son ejecuciones separadas sobre el mismo clúster aislado; no deben sumarse como tests únicos.

Evidencia local: `.local/mer07-4e06175d50d8/validation.json`, SHA-256 `d09faedc6e8dfec8bd902c0fa6e1ff80b09cb86de4a2e609f9a8a70e0ab13328`. Contiene las tres fases, versiones, 12 filas de migraciones y cierre PostgreSQL (`postgres_port_closed=true`). Se verificó 014 exactamente una vez con checksum `3d78fe760d586c9b4ba058fe3376d0fb8d9c8db2dcdff745624dccd74394d536`; los 12 checksums coinciden con sus fuentes canónicas. Se retiene el directorio descartable; no se modifica una base anterior.

Los 163 incluyen 58 casos nuevos (14 unitarios, 44 con PostgreSQL) y 105 regresiones existentes. Ninguno nuevo omitido. Las dos advertencias del primer import corresponden a StarletteDeprecationWarning (`testclient.py:1`) y DeprecationWarning (`testclient.py:53`); no se cambiaron dependencias ni filtros para ocultarlas. Git avisa LF→CRLF futuro en acp.py/checkout.py, sin errores del diff ni cambio de configuración global. El informe nuevo usa UTF-8/LF.

Trazabilidad de desarrollo: ejecuciones anteriores aprobaron 319, 325 y 329 casos generales al ampliarse el corpus. No validan el último parche. La prueba nueva de clave rechazada primero falló, confirmando que podía cambiarse la condición; se añadió persistencia del rechazo. La siguiente ejecución tuvo 162 aprobados/1 fallo: el test esperaba erróneamente 409 en ACP público; el contrato previo devuelve 422. Se corrigió la expectativa manteniendo el código público. No se eliminó ni omitió ningún caso para obtener verde.

La ejecución previa `mer07-fd10eaf8cc16` quedó interrumpida después de 2 migraciones aprobadas; no se le atribuye suite completa ni teardown registrado. Al retomar, pg_ctl confirmó que no había servidor activo. Un intento de cierre condicionado a verificar PID se detuvo sin actuar porque el proceso ya no existía. La validación inicial bajo sandbox encontró permisos del caché uv; se repitió con ejecución local autorizada. La pausa anterior por cuota impidió ejecutar, no fue resultado de tests.

## G. Matriz adversarial y evidencia de concurrencia

| Casos (44 integración, más 14 unitarios) | Garantía comprobada por las pruebas |
| --- | --- |
| Oferta observada válida | 201, revisión/digest aceptados, respuesta ACP original, un checkout, ningún order/complete |
| Revisión anterior, precio mayor/menor, precio sin cambio de revisión, nombre/destino alterados | 409, cero efectos comerciales nuevos |
| Inactivo, agotado, vencido incluso con digest actualizado | Rechazo de validez independiente del digest |
| Reloj sintético avanza y observación futura | Rechazo temporal aun con snapshot coincidente |
| Variante, moneda, cantidad, campos de autoridad, versión/tipos/digest, JSON duplicado | Entrada/recurso rechazado, cero efectos comerciales |
| Sesión ausente, inválida, revocada | Autenticación real Merchant rechaza; cero efectos comerciales |
| Otro run/actor | Sin acceso a oferta/historia ajenas, cero efectos comerciales |
| Misma clave/guard aceptado | 200 replay, prueba idéntica sin leer catálogo |
| Otra revisión/digest/variante/presencia ACP con clave aceptada | Conflicto, cero creaciones adicionales |
| Clave rechazada: repetir/cambiar condición, bypass público/interno | Rechazo histórico o conflicto; cero creaciones |
| Creación pública anterior | No se promueve retrospectivamente a guardada; replay público permanece |
| Dos creadores guardados concurrentes | Un 201 y un 200, un checkout y una prueba |
| ACP público y guardado concurrentes | Una sola sesión; solo hay prueba si gana la condición guardada |
| Actualizador bloquea primero la oferta | Se observa espera Lock en PostgreSQL; al confirmar cambio el guard rechaza |
| Guard bloquea primero la oferta | Actualizador espera; prueba/checkout consumen snapshot anterior, después actualiza catálogo |
| Error antes/después de insertar prueba | Rollback conjunto de checkout, ACP y prueba |
| Pérdida de respuesta después de commit | POST TCP real 201 leído y descartado por transporte controlado; recuperación explícita 200, mismo checkout |
| Cambios posteriores de catálogo | Historia y lookup original permanecen; no prueba vigencia actual |
| UPDATE/DELETE de prueba | Triggers rechazan; historia original sigue recuperable |

Los negativos comparan conteos de checkout_sessions, guarded_checkout_creations, orders, checkout_mutations y checkout_completion_attempts. Un rechazo semántico puede añadir registro de rechazo, deliberadamente; no se confunde ausencia de efectos comerciales con ausencia de toda escritura.

PostgreSQL, transacciones, locks, sesiones y concurrencia son reales. La mayoría de llamadas API usan TestClient ASGI; una prueba usa Uvicorn en socket TCP real y transporte que provoca ReadError DESPUÉS de recibir el 201. Es pérdida de respuesta inyectada en cliente, no corte físico de red, ni integración independiente Agent–Merchant. El servidor de esa prueba se cierra y su thread se une. No hay llamada PSP/LLM ni dinero real.

## H. Límites y dependencias de Agent 07B

No se activa continuación comercial, D2/D3, HNP, pago, complete, reserva de inventario ni runtime Agent. No se afirma D17 completo. Agent todavía debe implementar el lector autoritativo que produzca este Offer/perfil completo, su política de frescura/materialidad/TTL, transporte guardado y verificación de prueba enlazada a su envelope durable. Un feed parcial no basta para calcular este digest.

Hace falta definir e implementar lectura autenticada sin efectos de la prueba D17 tras respuesta perdida. El lookup ACP existente no lleva esa prueba; no se puede inferir de precios vigentes ni reenviar automáticamente un POST. Historia de creación no autoriza nuevos efectos, ni acredita checkout o consentimiento vigente.

Los triggers protegen de mutaciones ordinarias, no de un administrador PostgreSQL que los retire. SHA-256 es integridad local, no firma ni autenticación fuera del canal/sesión. El digest completo puede rechazar cambios inocuos de metadatos; es una elección conservadora explícita. La última comprobación temporal sucede antes del commit, no promete vigencia ilimitada después.

La nueva migración requiere despliegue coordinado antes del código que consulta sus tablas. No todos los entornos ni main tienen este contrato automáticamente. Los clústeres de desarrollo se retienen como artefactos locales ignorados, sin reusarlos: la migración 014 cambió durante el incremento y sus checksums anteriores no deben sobrescribirse ni reaplicarse a esas bases.

## I. Dictamen

**READY_FOR_REVIEW** para este incremento Merchant local. Se comprobaron primera migración/repetición/checksums, 58 casos nuevos, 105 regresiones seleccionadas, suite general, Ruff, Pyright e integridad del diff. Cinco archivos versionados modificados y ocho nuevos; índice vacío y HEAD base intacto. Los ocho archivos nuevos también pasan comprobación de whitespace sin stage (`git diff --no-index --check` contra NUL, con LF de estos archivos nuevos).

No es autorización de despliegue, integración comercial ni D17 completo. Agent/PSP/B0 permanecen fuera del incremento. Sin stage, commit, push, merge o PR; detenerse para revisión humana y no continuar con Agent.