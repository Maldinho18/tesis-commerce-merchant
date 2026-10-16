# EC-MER-07B-A2 — Lookup histórico D17

## A. Preflight

Merchant limpio, índice vacío, rama inicial `merchant/ec-mer-07b-d17-atomic-precondition`, HEAD `ab2a0a95e6bee97709fd232fda90206e37e82736`; origin fetch/push `https://github.com/Maldinho18/tesis-commerce-merchant.git`. Rama nueva ausente y creada desde esa base: `merchant/ec-mer-07b-a2-readonly-guard-proof`. Agent permanece en `35fd2d80e6f10150d5f0651b386adaa4eff2d40e`, sin ejecución ni modificaciones.

Verificación de preservación: baseline local `.local/mer07a2-baseline-1aca8a8edb99.json`; 279 archivos Merchant previos conservan exactamente sus bytes; solo API y runner difieren. Los 336 archivos Agent capturados (versionados e informe pendiente) conservan SHA-256. No se reejecutó B0 ni se operaron datos históricos.

## B. Contrato y estados (diseño previo a implementación)

`POST /lab/recovery/guarded-checkout-creation/lookup`, privado y fuera de discovery. Solo versión propia y SHA-256 de clave; ámbito exclusivamente de sesión Merchant. No acepta claves claras ni autoridad elegida por cliente.

| Historia en snapshot consistente | Resultado |
| --- | --- |
| Prueba aceptada íntegra + checkout original coherente, sin rechazo | found |
| Rechazo íntegro sin checkout, salvo guard_history_unavailable | rejected |
| Sin prueba/rechazo/checkout | not_found, nunca permiso de replay |
| Checkout ordinario sin prueba | unrecoverable |
| Checkout ordinario + rechazo guard_history_unavailable | unrecoverable: coexistencia legítima del contrato 07B-A |
| Prueba y rechazo, prueba sin checkout, rechazo comercial contradictorio, datos corruptos | error de integridad |

07B-A registra guard_history_unavailable cuando una clave ya identifica un checkout ordinario; no se puede clasificar esa coexistencia como rechazo sin creación ni promoverla a D17. Un rechazo guard_history_unavailable sin historia comercial también es inconsistente.

## C. Confianza

Reutilizar trusted_context/require_acp_version sin cambios. Una prueba confirma historia, no vigencia, consentimiento actual, firma externa ni permiso de continuación. Digest de snapshot aceptado no se reconstruye desde catálogo: se valida tipo, vínculo y fingerprint de guard con el perfil publicado. El esquema 014 no guarda el Offer completo original ni el cuerpo ACP original: no permite recalcular independientemente todos sus términos o el fingerprint ACP desde ese cuerpo ausente. Se compara el fingerprint ACP persistido y se reconstruye la identidad del guard desde los campos históricos disponibles.

## D. Implementación

Implementación aislada en tres módulos nuevos y dos archivos de pruebas nuevos. Solo se modifica API para importar/registrar el router y el runner existente para seleccionar esta validación en un clúster nuevo con prefijo propio. No cambian contratos 06D-A/07B-A, migraciones, ACP/AP2, dependencias, lockfile, checkout, pagos o runtime Agent.

| Archivo | Justificación |
| --- | --- |
| `src/commerce_lab/contracts/guarded_lookup.py` | Entrada estricta y resultados discriminados, sin permisos |
| `src/commerce_lab/guarded_lookup.py` | Tres SELECT bajo un snapshot PostgreSQL consistente; validación histórica |
| `src/commerce_lab/guarded_lookup_api.py` | Autenticación existente, HTTP acotado, errores sanitizados, sin redirects |
| `src/commerce_lab/api.py` | Dos líneas: import y registro |
| `tests/test_guarded_lookup_contract.py` | Contrato, tipos, autoridad inesperada y resultados desconocidos |
| `tests/integration/test_guarded_lookup.py` | PostgreSQL real, hash de todas las tablas, corrupción, concurrencia y TCP |
| `tests/integration/guarded_cluster.py` | Opción --guard-lookup; reutiliza aislamiento, conexión local con timeout 10 s; --full-only evita acumular fases; plan anterior se conserva sin ese flag |
| `docs/ec-mer-07b-a2-readonly-guard-proof-results.md` | Informe A–I |

Versión propia `merchant-guarded-creation-lookup/1`; body contiene exclusivamente schema_version e idempotency_key_sha256. found incorpora el GuardedProof original idéntico y proof_sha256; rejected incorpora registro original y su digest; not_found/unrecoverable solo contexto/correlación e identidad consultada. No se añaden banderas de replay, continuation, payment o completion.

HTTP 200 para clasificaciones históricas; 400 versión API incorrecta; 401 autenticación; 422 entrada; 405 método no admitido; 500 history_invalid; 503 lookup_unavailable o response_too_large. Body máximo 2048 bytes, JSON sin duplicados ni NaN/Infinity, sin query strings, respuesta máxima 262144 bytes. Las respuestas del router son tipadas/no-store. La barra final se rechaza, en vez de redirigir; los métodos no admitidos se rechazan localmente sin afectar rutas anteriores. No se expone el endpoint en discovery ni OpenAPI.

El límite de respuesta se comprueba después de construir/serializar el resultado, antes de devolverlo: no es una cota del uso de memoria al cargar JSON desde PostgreSQL. Las tablas históricas pertenecen al perímetro de almacenamiento confiable; sus datos siguen validándose y los excesos no se publican.

SHA-256 de bytes locales finales (el hash de este informe se entrega aparte para evitar autorreferencia):

| Archivo | SHA-256 |
| --- | --- |
| `src/commerce_lab/api.py` | `18627c6f775feaab86b1c0df8cde8829d703a407dc0dfc04dfffb0507392e8de` |
| `tests/integration/guarded_cluster.py` | `b0a89c4b10bc4aeb4729a7169ea034dbb0991e7f362fe5149ebda8729f81f71b` |
| `src/commerce_lab/contracts/guarded_lookup.py` | `10d7255347705f5316a950f5278d9ba66358428737ec8537c76a22180b26be8f` |
| `src/commerce_lab/guarded_lookup.py` | `818787b0662a03a0ff22c09d0d5c5f83d7bc7dcdcc9dd05b5fe7596cd6b3599f` |
| `src/commerce_lab/guarded_lookup_api.py` | `8896412395adaa826185d6ad7e55639aa63b9fa8058ec8d41425aaacf96e7d75` |
| `tests/test_guarded_lookup_contract.py` | `c0feb7912298edbdcd55d965f3b88af4e6faa7dcd01ba215284beb64bfc64cd9` |
| `tests/integration/test_guarded_lookup.py` | `f8a497b3a7ab5709016fbdd78c642392a07f50b41c58b2d85e8621838681d265` |

## E. Integridad y ausencia de efectos

Cada lookup abre conexión propia y ejecuta `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY` antes de tres SELECT acotados por run/actor/hash. Las lecturas separadas comparten snapshot: no pueden combinar arbitrariamente etapas distintas de una creación concurrente. No hay advisory locks, FOR UPDATE/FOR SHARE, escrituras, llamadas de creación/consulta comercial ni acceso al catálogo o PSP.

found requiere: GuardedProof tipado, digest versionado, ámbito/clave, guard_fingerprint de fila/prueba/recalculado desde preimagen histórica, checkout_id en los tres registros, fingerprint ACP original, respuesta ACP original exacta, schema ACP congelado y digest de esa respuesta. Se valida create_snapshot tipado y su identidad/revisión/cantidad/estado original; unit_amount y los totales publicados se comparan con el pricing original. El snapshot comercial vigente no se lee ni se reconstruye. En particular, CheckoutService.update puede cambiar la columna offer_revision actual: no se la compara con la revisión histórica aceptada. Se usa create_snapshot, que 013 protege como identidad de creación; igualar la revisión actual produciría falsos errores sobre historia válida. Un checkout cancelado puede seguir devolviendo found histórico.

rejected exige registro tipado/digest y coincidencia de fila/registro/contexto/hash/fingerprint. La coexistencia con checkout solo se admite como unrecoverable para guard_history_unavailable. Prueba aceptada y rechazo simultáneos fallan cerrado. Historia ordinaria inválida también produce error, nunca se convierte en not_found. Los errores de conexión salen como 503; la corrupción como 500. Ninguno concede autorización.

La autenticación existente usa su propia conexión SELECT y no renueva sesiones. La afirmación READ ONLY se refiere a la transacción del servicio nuevo; no se atribuye esa configuración a toda conexión previa de autenticación ni a la observabilidad existente. La nueva ruta no agrega observaciones comerciales. Los tests capturan snapshots y SHA-256 de todas las tablas public —incluidas sesiones, catálogo, checkout, órdenes, mutaciones, completions, pruebas, rechazos y observaciones— antes/después de los lookups.

Se reutilizan los validadores y dominios existentes; no se llama a GuardedCreation.create, ACPCheckoutAdapter.create/_response/_offer, servicios comerciales ni PSP. Una prueba con dobles que fallan ante cualquiera de esas invocaciones complementa la comprobación real de PostgreSQL. Los snapshots nuevos calculan SHA-256 de cada fila convertida a JSONB, ordenan esos digests de 32 bytes y calculan el digest de tabla con dominio propio y cantidad de filas. Se conservan contenido, duplicados y orden de secuencias dentro de cada fila, sin transportar/agregar tablas JSON completas. Un test sintético añade/elimina duplicados y permuta una secuencia, verificando cuatro hashes distintos; crea y elimina exclusivamente su tabla de prueba en el clúster nuevo. La rutina histórica de snapshots 06D-A queda intacta.

La prueba de READ ONLY consulta SHOW para las tres lecturas e intenta un UPDATE sin filas dentro de un savepoint: PostgreSQL debe rechazarlo, revertir el savepoint y permitir completar la lectura.

## F. Validación

Windows; dependencias existentes, sin sync/install ni llamadas externas. El runner inhabilita dotenv en su proceso antes de cargar la API, limpia variables de proveedores/DSN, verifica identidad de base/rol/host/puerto/data_directory antes de migrar o sembrar y en cada conexión, y restringe escrituras a su raíz nueva. PostgreSQL instalado localmente; HBA/roles y credenciales solo sintéticos. No se utiliza una base operativa. No se afirma validación Linux.

```powershell
$env:UV_NO_SYNC='true'
$env:UV_OFFLINE='true'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:RUFF_NO_CACHE='true'
uv run ruff format --check .
uv run ruff check .
uv run pyright
$env:RUN_MER07_REAL='1'
uv run python -B tests/integration/guarded_cluster.py --guard-lookup
# Repetición final en otra base vacía, después de ajustar el harness:
uv run python -B tests/integration/guarded_cluster.py --guard-lookup --full-only
git diff --check
git diff --cached --stat
```

Plan: migraciones sobre base vacía → pruebas nuevas de A2 → las 163 regresiones anteriores de contratos/ACP/recuperación/lookup/guard → suite general con integración. No se crean migraciones nuevas. El plan anterior del runner se conserva si no se pasa --guard-lookup; se añade únicamente el campo informativo de timeout a su evidencia.

Resultados previos al ajuste de verificación (no son el cierre final):

| Fase en mer07a2-9a1988caa36b | Resultado | Duración medida |
| --- | --- | --- |
| Migraciones sobre base vacía | 2 passed, 0 failed, 0 skipped, 0 warnings | 1.276714 s |
| Nuevos tests A2 iniciales | 61 passed, 0 failed, 0 skipped, 2 warnings | 156.152479 s |
| Regresiones 06D-A / 07B-A / ACP | 163 passed, 0 failed, 0 skipped, 0 warnings | 311.091141 s |
| Suite general | 390 passed, 1 failed, 1 skipped, 0 warnings | 1129.686147 s |

El fallo general fue `test_bad_input_no_effects[change5]`, psycopg.errors.ConnectionTimeout al abrir una conexión del verificador con PGCONNECT_TIMEOUT=2. No fue un permiso emitido incorrectamente. Las consultas activas observadas correspondían a agregación de snapshots, sin espera de locks; no se determinó una causa de sistema operativo más específica. No se convirtió el fallo en skip ni se repitió automáticamente una operación comercial.

Se ajustó solo la infraestructura de pruebas: timeout 10 segundos para el clúster A2, sin reintentos; hashes completos por filas en lugar de JSON agregado; test adicional de contenido/duplicados/secuencias; repetición de la suite completa desde base vacía sin acumular fases previas. No se tocaron el servicio ni el contrato HTTP por ese fallo. No se rebajó ningún control de integridad. El harness antiguo conserva timeout de dos segundos si no se solicita el modo A2.

Cierre final ejecutado el 2026-10-16 en `.local/mer07a2-c98405d47adf`, PostgreSQL nuevo e independiente, loopback 56699; timeout de conexión 10 s. Versiones medidas: PostgreSQL 17.2, Python 3.12.6, psycopg 3.3.5, FastAPI 0.141.1, httpx 0.28.1, Pydantic 2.12.5, pytest 9.0.2. Las pruebas nuevas son ahora 62 (16 unitarias y 46 con PostgreSQL), incluida la prueba del algoritmo de snapshots. La suite completa vuelve a ejecutar las regresiones y todos los casos nuevos.

| Control final | Resultado |
| --- | --- |
| Primera aplicación/repetición/checksums de las 12 migraciones existentes | 2 passed, 0 failed, 0 skipped, 0 warnings; 0.825805 s |
| Suite completa desde base nueva | 392 passed, 0 failed, 1 skipped, 2 warnings; 259.599549 s |
| Ruff format | 83 files already formatted |
| Ruff check | All checks passed! |
| Pyright | 0 errors, 0 warnings, 0 informations |
| git diff --check | Sin errores |

Las fases no deben sumarse como tests únicos. Las advertencias observadas de importación son StarletteDeprecationWarning (testclient.py:1) y DeprecationWarning (testclient.py:53); no se modificaron dependencias/filtros para ocultarlas. La indisponibilidad de almacenamiento se inyecta mediante OperationalError del conector, no mediante caída física del servidor. El límite de respuesta se ejercita reduciendo temporalmente el umbral a 128 bytes, sin afirmar que se envió un artefacto de 256 KiB. La identidad es el valor JSON canónico/digest, no los bytes originales del transporte. Los tiempos incluyen fixtures, snapshots, hashes y probes; no son latencia del endpoint ni SLO comercial.


La única omisión final es test_fresh_database_tracks_each_migration_once: exige base vacía y ya había sido ejecutada satisfactoriamente en la primera fase. No hay tests nuevos omitidos. Los dos avisos finales son las deprecaciones de TestClient listadas arriba; no se suprimieron.

Se comprobaron las 12 filas de schema_migrations y sus checksums canónicos; 014 aparece exactamente una vez con `3d78fe760d586c9b4ba058fe3376d0fb8d9c8db2dcdff745624dccd74394d536`. No se modificó ninguna migración. La evidencia final `.local/mer07a2-c98405d47adf/validation.json` tiene SHA-256 `bcaeb427144551569a7a5d7a04a60b38cd22c45571af22b0483e80d7c7506af9` y registra postgres_port_closed=true. Los tres clústeres de esta tarea se detuvieron y se conservan sus directorios como evidencia descartable; nunca se reutilizó una base anterior. La comprobación final independiente obtuvo pg_ctl status=3 (no server running) y ausencia de postmaster.pid en los tres. Un sondeo adicional de socket devolvió WSAEWOULDBLOCK (10035), inconcluso en Windows, y no se utiliza como prueba de cierre.

Los hashes de todas las tablas permanecieron idénticos antes/después de cada lookup medido, incluidos fallos, negativos y lecturas concurrentes. Se ejecutó y aprobó la comprobación real READ ONLY con escritura rechazada. Se confirmó cero efectos comerciales atribuibles al lookup en estos escenarios; las creaciones, cancelación, corrupción y tabla de prueba pertenecen a la preparación/control del corpus, no al servicio lector. No se afirma integración Agent–Merchant, autenticidad criptográfica externa ni disponibilidad comercial.

Trazabilidad: la primera ejecución `.local/mer07a2-7d25f335a8e6` (puerto 51474) aprobó las dos migraciones y 59/60 pruebas nuevas, con 2 advertencias de TestClient. Un test asumía una ruta OpenAPI publicada y falló con KeyError; Merchant tiene openapi_url=None. Se corrigió para inspeccionar el schema generado localmente y el discovery real `/.well-known/acp.json`, sin habilitar OpenAPI ni cambiar producción. Se añadió una prueba de rechazo sin redirect para barra final/métodos no admitidos. Esa ejecución fallida se conserva y no se presenta como suite general validada. Los errores preliminares de Ruff y los 57 errores de tipos iniciales se corrigieron usando el cursor dict_row tipado y validación Pydantic, sin ignores ni reducción de verificaciones.

## G. Casos adversariales y pérdida de respuesta

| Escenario | Resultado requerido |
| --- | --- |
| Creación guardada válida | found, misma prueba y digest, ámbito autenticado |
| Rechazo de revisión conocido | rejected tipado, sin checkout |
| Clave desconocida | not_found sin permisos |
| Creación ordinaria, con/sin rechazo guard_history_unavailable | unrecoverable, sin promoción a D17 |
| Catálogo actualizado y checkout cancelado | found idéntico, sin reconstrucción comercial |
| Otro run del mismo actor u otro actor | Solo not_found propio, sin datos del checkout ajeno |
| Sesión revocada/vencida/ausente/incorrecta | 401, ninguna escritura |
| Sesión renovada y Request-Id elegido por cliente | Mismo ámbito/prueba; servidor genera correlación |
| Versiones/tipos/digest/autoridad/campos desconocidos | Error tipado, cero efectos |
| JSON malformado/duplicado/no estándar, exceso de tamaño, query | 422 sin eco |
| Barra final/método no admitido | Sin redirects; 422/405 tipado y no-store |
| Digest/fingerprint/revisión/digest de oferta/fingerprint ACP/respuesta corruptos | 500 conservador, aun recalculando digest para ejercitar vínculos cruzados |
| Snapshot original o respuesta ACP almacenada contradictorios | 500, sin usar estado actual como sustituto |
| Rechazo con digest corrupto o aceptación y rechazo simultáneos | 500, sin escoger historia arbitraria |
| Ocho lookups en cuatro threads | Mismo hecho histórico, sin cambios de hashes |
| Almacenamiento no disponible | 503 sanitizado, nunca not_found ficticio |
| Respuesta excede límite | 503 sin publicar prueba parcial |
| Transacción con UPDATE de prueba sintético | PostgreSQL rechaza escritura READ ONLY; rollback al savepoint |
| TCP: creación confirmada cuya respuesta se descarta | Recuperación exclusivamente mediante lookup; ninguna segunda creación |

La mayoría de pruebas usan FastAPI TestClient/ASGI y PostgreSQL real. La prueba TCP usa Uvicorn en loopback con puerto nuevo y httpx: recibe/draina un 201 real y descarta la respuesta mediante ReadError controlado. Después se prohíben las funciones comerciales y se llama solo al lookup; los hashes de todas las tablas deben permanecer idénticos. No es corte físico de red ni ejecución de Agent; no simula autenticación: usa Bearer emitido y comprobado por Merchant. El thread del servidor se cierra y se une al terminar.

Para corrupción sintética se deshabilitan temporalmente triggers USER solo dentro de una transacción sobre el clúster descartable, se alteran datos de prueba y se reactivan antes de confirmar. No se alteran migraciones ni triggers productivos. El servicio debe rechazar esa corrupción y no repararla ni escribir encima.

## H. Limitaciones y Agent 07B-B

No se ejecutó integración con Agent, caída física de red/servidor, ni una carrera entre un escritor y las tres lecturas de un lookup. Sí se verificaron PostgreSQL real, modo READ ONLY, aislamiento repeatable read, escritura denegada, ocho lectores concurrentes y transporte TCP con pérdida inyectada. SHA-256 no es firma externa ni protección contra un administrador capaz de reescribir coherentemente tablas/digests; el canal y el ámbito Merchant siguen siendo fronteras de confianza. El estado vigente del checkout y la oferta queda fuera de este contrato histórico.

Debe implementar transporte privado sin reenvíos comerciales, conservar su envelope esperado y verificar explícitamente versión de lookup/perfiles, run/actor, hash de clave, fingerprint ACP/guard, checkout, revisión/digest de oferta y prueba histórica; consumir estados tipados, verificar binding con su envelope esperado y tratar todos los resultados como historia sin autorización comercial. Not_found solo significa ausencia de registros en el snapshot de esa lectura: puede competir con una operación todavía no confirmada. No demuestra ausencia de POST ni autoriza reenvío. No hay visibilidad global de operaciones remotas no persistidas. Para HTTP 200, validar GuardProofLookupResult discriminado; los demás estados usan GuardProofLookupError con result=error y catálogo cerrado. Resultados o códigos inesperados deben fallar cerrado. No se presume que otros entornos tengan esta rama/endpoint: 404, versión incompatible o almacenamiento no disponible no habilitan fallback a creación ACP ordinaria. No se activa Agent, HNP, D2-HP, PSP, pagos o enforce.

## I. Dictamen

**READY_FOR_REVIEW** para este incremento Merchant local. El lookup devuelve hechos históricos tipados sin autorización comercial. La ejecución final aprueba 392 casos y conserva una omisión existente. No hay bloqueos funcionales conocidos del alcance implementado; las dependencias Agent y límites experimentales se mantienen en H. HEAD conserva `ab2a0a95e6bee97709fd232fda90206e37e82736`; Agent conserva `35fd2d80e6f10150d5f0651b386adaa4eff2d40e`. Índice vacío. Dos archivos previos modificados y seis nuevos. Diff versionado: 2 archivos, 21 inserciones, 3 eliminaciones; los seis nuevos no aparecen en ese stat al seguir sin stage.

```text
## merchant/ec-mer-07b-a2-readonly-guard-proof
 M src/commerce_lab/api.py
 M tests/integration/guarded_cluster.py
?? docs/ec-mer-07b-a2-readonly-guard-proof-results.md
?? src/commerce_lab/contracts/guarded_lookup.py
?? src/commerce_lab/guarded_lookup.py
?? src/commerce_lab/guarded_lookup_api.py
?? tests/integration/test_guarded_lookup.py
?? tests/test_guarded_lookup_contract.py
```

Sin stage, commit, push, merge ni PR. No continuar con Agent ni activar efectos comerciales.
