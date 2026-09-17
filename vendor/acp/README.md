# ACP 2026-04-17 congelado

Se copiaron sin cambios los tres archivos de `2026-04-17/` y
`provenance.json` desde `Maldinho18/tesis-commerce-lab@e6a7cb5`.
`.gitattributes` desactiva la conversión de saltos de línea para el snapshot.
El origen ACP y sus hashes SHA256 están registrados en `provenance.json`.

El servidor merchant y el adaptador validan create, get, update y cancel
contra el bundle congelado. El alcance de update es seleccionar la única
opción de envío existente; cancel acepta cuerpo vacío o únicamente
`intent_trace.reason_code`. Hay pruebas del servidor HTTP, idempotencia,
errores tipados, aislamiento y concurrencia. El cliente HTTP del Buyer Agent
no forma parte de este repositorio.

Siguen pendientes complete, capacidad de pago, order/payment y el resto de
la cobertura necesaria para conformidad ACP integral.
