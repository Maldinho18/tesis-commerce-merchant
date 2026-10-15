# EC-MER-REC-01 — Recuperación idempotente de creación ACP

Fecha: 2026-10-15. Dictamen: **READY_FOR_REVIEW** del incremento Merchant.
Esto no autoriza activar EC-GOV-06B ni desplegar la migración en una base operativa.

## Base y alcance

Inspección previa: `main`, HEAD `70ce92b97cee3d7aabf8d287f0bf700816dc584b`,
working tree limpio. Origin, sin cambios:
`https://github.com/Maldinho18/tesis-commerce-merchant.git` (fetch/push).
Se leyeron, sin modificarlos, el ticket y los resultados EC-GOV-06B-R1 del agente.
No hubo fetch, ramas nuevas, stage, commit, push, merge ni PR.

## Arquitectura y decisiones

La identidad de recuperación es `(run_id, actor_id, SHA256(Idempotency-Key))`.
Run y actor proceden del contexto autenticado del servidor. El token renovado no
forma parte del fingerprint; debe resolver al mismo ámbito. Request-Id sigue
siendo correlación generada por Merchant y no concede autoridad.

El adaptador valida el cuerpo del perfil ACP antes de buscar una creación. El
fingerprint nuevo aplica SHA-256 con dominio `merchant-acp-create/v1` a JSON
canónico que incluye versión ACP, perfil `merchant-p0-create/1` y cuerpo completo
validado. Conserva presencia de campos y orden de arrays; ignora orden de claves
y espacios JSON. Omitir un campo opcional y enviarlo explícitamente son contenidos
distintos, aunque sus valores efectivos por defecto coincidan.

Orden de la operación:

1. Validación HTTP, versión, credencial y solicitud; comprobación del dueño del run.
2. Lock transaccional PostgreSQL por ámbito y clave; búsqueda exacta de creación.
3. Si existe: comparar fingerprint y devolver la respuesta ACP guardada, validada
   contra el esquema congelado y asociada al mismo checkout. No consultar oferta,
   recalcular readiness ni reconstruir capacidades.
4. Si no existe: leer/bloquear oferta, preparar checkout, construir una vez la
   respuesta ACP y persistir fingerprint/respuesta en la misma fila y transacción.
5. Commit antes de entregar al endpoint la respuesta. La primera entrega también
   utiliza la representación JSONB almacenada.

Se eligieron dos columnas aditivas en `checkout_sessions` frente a una tabla de
operaciones separada: la restricción UNIQUE existente ya representa el ámbito,
y una misma fila permite conservar asociación y respuesta sin otro vínculo.
Guardar solo `create_snapshot` interno no bastaba: nombre y capacidades podían
proceder de fuentes mutables al reconstruir ACP.

`CheckoutService.prepare_in_transaction` conserva validación y semántica interna,
pero permite que el adaptador controle el commit. `prepare` conserva su interfaz
y utiliza el mismo lock para impedir carreras entre creación interna y ACP.
`_existing` interno permanece sin cambios. El lock usa 64 bits de un hash del ámbito;
una colisión solo serializa solicitudes adicionales: no cambia los filtros ni la
restricción UNIQUE y no permite recuperar otra creación.

## Persistencia y ventanas de caída

La migración nueva `013_acp_creation_recovery.sql` añade `acp_create_fingerprint`
y `acp_create_response`. Exige par nulo o completo, formato de fingerprint,
objeto JSON, checkout ID y versión ACP coherentes. Un trigger impide modificar la
identidad y el snapshot de creación, y modificar o borrar el par ACP ya guardado.
Las mutaciones posteriores del checkout conservan su snapshot vigente separado.

| Punto de fallo | Resultado comprobado |
| --- | --- |
| Excepción al construir o guardar la respuesta tras INSERT | Rollback; cero checkouts; repetir crea uno |
| Salida abrupta del proceso antes de guardar respuesta ACP | Rollback; cero checkouts; repetir crea uno |
| Salida abrupta después de guardar ACP, antes del commit | Rollback de ambas escrituras; repetir crea uno |
| Commit y pérdida del resultado antes de entregarlo al padre | Una fila; otro proceso recupera ID y JSON originales |
| Cuatro solicitudes concurrentes con mismo contenido | Cuatro 201; un ID, un cuerpo y una fila |
| Dos contenidos distintos concurrentes con K | Un 201 y un 422; una fila |

La pérdida de respuesta se inyecta con salida de proceso después del POST/commit;
no es un ensayo de rotura de socket, corte eléctrico ni caída del servidor PostgreSQL.
Sí se ejecutaron dos procesos independientes y un reinicio real del servicio HTTP
local entre la primera solicitud y la recuperación, con cambio de catálogo.

Filas anteriores o creaciones internas sin respuesta ACP original devuelven
**409 `creation_unrecoverable`**: requieren conciliación. No se fabricó backfill.
Se ensayó la migración sobre un esquema temporal con una creación antigua y se
comprobó que su snapshot permaneció intacto y sin respuesta ACP inventada.

## Matriz y resultados

Nuevos tests: **6 unitarios + 38 de integración = 44 aprobados, 0 omitidos,
2 advertencias, 34.89 s**. Pruebas de integración con PostgreSQL real, no un doble
de base de datos. Los monkeypatch se limitan a inyectar errores o prohibir consultas.

| Escenarios nuevos | Resultado |
| --- | --- |
| Mismo POST en procesos nuevos y reinicio HTTP real | 201, JSON y cuerpo originales, una sesión |
| Revisión, precio, nombre, stock, baja lógica y cambios combinados | 201 original, una sesión, Request-Id nuevo |
| Consulta de oferta, constructor de respuesta y capacidades prohibidos durante replay | Recuperación exitosa sin invocarlos |
| DELETE físico de oferta referenciada | FK lo rechaza; recuperación posterior intacta |
| Otra variante existente o inexistente con la misma K | 422 `idempotency_conflict` antes de consultar catálogo |
| Cambio de presencia de campos; orden de claves distinto | Conflicto en el primero; replay en el segundo |
| Otro run del mismo actor; otro run/actor | Sesiones distintas; GET de la original: 404 |
| Otro actor intentando reclamar el mismo run en el adaptador | FORBIDDEN, sin acceso al original |
| Token vencido o revocado; token renovado del mismo ámbito | 401 con el antiguo; recuperación con el renovado |
| Versión, moneda, autoridad extra, ausencia de auth o K inválidas en replay | 400/401/422; no devuelve el original |
| Request-Id elegido/copiado por el cliente | No identifica ni autoriza recuperación entre ámbitos |
| Concurrencia entre creación interna y ACP | Una fila; mismo ID o rechazo explícito sin adoptar fila interna |
| Cancelación posterior | POST devuelve creación original; GET conserva estado actual cancelado |
| Alteración SQL del fingerprint, respuesta o create_snapshot | Trigger la rechaza |
| Excepciones, caída precommit y resultado perdido postcommit | Atomicidad según tabla anterior |
| Migración sobre fila anterior sin snapshot ACP | Conservación del snapshot; 409 sin reconstrucción |
| Canonicalización y campos desconocidos | Orden de claves estable; cambios detectados; extras rechazados |

La FK actual impide una oferta físicamente ausente con su checkout retenido.
No se deshabilitó ni modificó esa restricción. No se atribuye una prueba real de
eliminación exitosa: se verificaron el rechazo de DELETE, la baja lógica y la
ausencia de lecturas del catálogo en el camino de recuperación.

Suite general, con integración habilitada: **210 passed, 1 skipped, 2 warnings
in 92.20s**. La única omitida fue
`test_migration_tracking.py::test_fresh_database_tracks_each_migration_once`,
porque las migraciones ya estaban aplicadas en el clúster temporal.

Antes de modificar código se ejecutó esa prueba en la base vacía: **1 failed in
0.49s**. Compara el SHA-256 de bytes CRLF con el checksum LF normalizado que ya
usaba `migration_sha256`; esperado almacenado
`c06740a1f867a55a4486a1dafb5a7e85e5ceaec3cadb878233efbf2ff908e8d4`,
bytes locales `577531b2e8457504edd55677698c2121b4d91e081bf2b8c6b6bdaf54ac6fda4e`.
Es un fallo previo reproducido, pendiente de corrección separada; el skip posterior
no prueba que haya quedado resuelto. No se modificaron migraciones históricas ni
se redujeron sus verificaciones.

Advertencias: deprecación Starlette TestClient/httpx y alias anyio BlockingPortal.
Controles finales: Ruff format **63 files already formatted**; Ruff check
**All checks passed!**; Pyright **0 errors, 0 warnings, 0 informations**;
`git diff --check` sin errores. Git advierte que el archivo de checkout con LF
podría volver a CRLF por la configuración existente; no se cambió esa configuración.

Durante la edición hubo un error de sintaxis en el archivo nuevo de pruebas y
controles de estilo fallidos, corregidos antes de las corridas finales. El primer
intento de herramientas con caché de uv del sandbox falló por permisos; los
controles finales usaron caché local y el entorno ya instalado, sin sincronizar.

## Entorno y reproducción local

Validación real en Windows 11, Python 3.12.6, PostgreSQL 17.2 local; timezone UTC.
No se afirma ejecución en Linux. uv 0.12.15, Psycopg 3.3.5, Pytest 9.0.2,
Ruff 0.16.8, Pyright 1.1.414, FastAPI 0.141.1, Starlette 1.6.0, httpx 0.28.1,
Pydantic 2.12.5 y Uvicorn 0.53.0. No se instalaron ni cambiaron dependencias.

Se creó únicamente el clúster descartable `.local/mer-rec-01/pgdata`, en loopback
puerto 61363, base nueva `tesis_lab`, rol y sesiones sintéticos. El runner comprueba
`SHOW data_directory` y UTC antes de migrar/sembrar, elimina variables de proveedores
y desactiva dotenv antes de importar la aplicación. No se abrió ninguna base operativa.
Las llamadas HTTP reales fueron solo al servidor efímero de loopback; las pruebas
históricas de pagos usan sus transportes simulados, sin servicio PSP externo.

Comandos desde la raíz Merchant, usando `UV_NO_SYNC=true`, `UV_OFFLINE=true`,
caché bajo `.local/mer-rec-01/uv-cache` y `PYTHONDONTWRITEBYTECODE=1`:

```text
uv run python -B .local/mer-rec-01/run_tests.py tests/test_acp_creation.py tests/integration/test_acp_creation_recovery.py -q -p no:cacheprovider --basetemp=.local/mer-rec-01/new-final --junitxml=.local/mer-rec-01/new-final.xml
uv run python -B .local/mer-rec-01/run_tests.py -q -p no:cacheprovider --basetemp=.local/mer-rec-01/full --junitxml=.local/mer-rec-01/full.xml
uv run ruff format --check .
uv run ruff check .
uv run pyright
git diff --check
```

El runner llama a `pytest.main` con esos argumentos sobre el mismo intérprete del
entorno uv. Los tests nuevos requieren `RUN_DB_INTEGRATION=1` y que
`RECOVERY_TEST_CLUSTER` coincida exactamente con `SHOW data_directory`; no habilitar
la suite sobre una base operativa. Runner, manifiesto previo, stdout, JUnit, datos
y logs se conservan como evidencia local ignorada en `.local/mer-rec-01/`.
Para repetir, preparar/arrancar expresamente ese clúster y usar directorios de
temporales nuevos. El clúster se detiene al cerrar este incremento.

## Archivos y preservación

Modificados: `acp.py` (recuperación), `checkout.py` (transacción compartida),
`api.py` (traducción del error local), `contracts/commerce.py` (código del error),
`db/core.py` (registro de la migración), todos bajo `src/commerce_lab/`.

Nuevos: `src/commerce_lab/checkout_creation.py`, migración 013,
`tests/test_acp_creation.py`, `tests/integration/test_acp_creation_recovery.py`,
`tests/integration/recovery_worker.py` y este informe.

De los **261 archivos inicialmente versionados**, solo cambiaron bytes de los
cinco archivos previstos; los otros **256** coinciden con el manifiesto SHA-256
previo. Esto incluye esquemas ACP/AP2, migraciones históricas, fixtures y artefactos
históricos/B0. Los episodios sembrados por los tests son datos nuevos del clúster
temporal, no una reejecución del baseline experimental.

`uv.lock` intacto:
`8c2f1a51afcbfa2bb7cafac180837d29698698cf1473981d7a061a6a532484f9`.
`pyproject.toml` intacto:
`b2e28b7fab86868db14f38269be76104b1280262e438a1578e5b7a70e7170eba`.
No se modificaron Agent, Lab, PSP ni bases operativas. Índice vacío; HEAD, rama y
remotos permanecen como al inicio. Cambios locales pendientes de revisión.

## Riesgos y siguiente frontera EC-GOV-06B

- Revisar y desplegar expresamente la migración antes de ejecutar código nuevo;
  aquí solo se aplicó en PostgreSQL aislado. Conservar UTC: sigue pendiente la
  incidencia histórica de conversión de timestamps fuera de UTC.
- Resolver mediante conciliación los registros preexistentes sin respuesta ACP;
  no existe garantía retrospectiva de su JSON original.
- El replay devuelve el resultado histórico de creación, no autorización para
  completar ni estado actual. No cambia revisiones, pagos, firmas o aprobación.
- La retención de la garantía depende de conservar episodio y checkout. Borrar el
  episodio elimina registros por el cascade ya existente; no se añade retención.
- La autenticación sigue comprobándose al entrar la solicitud. No se ensayó una
  revocación concurrente a mitad de transacción ni se promete ese nuevo contrato.
- Los locks nuevos protegen unicidad; no se introdujo un timeout ni se midió un SLO
  de contención o volumen. No se probó recuperación tras caída del SO/PostgreSQL.
- Antes de reactivar enforce, Agent requiere revisión independiente del binding
  remoto, recuperación de uncertain, evidencia append-only/CAS y su frontera de
  despacho. Este incremento no añade reintentos automáticos ni modifica Agent.

Se detiene el trabajo para revisión humana, sin activación comercial.
