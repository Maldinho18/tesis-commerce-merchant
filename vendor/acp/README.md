# ACP 2026-04-17 congelado

Los tres archivos originales de `2026-04-17/` provienen de
`Maldinho18/tesis-commerce-lab@e6a7cb5`. Se añadieron sin modificar
`schema.feed.json` y `openapi.feed.yaml` desde el commit upstream
`7fdd78df677a94dce04c770644b0fbbb1401272b`.
`.gitattributes` desactiva la conversión de saltos de línea para el snapshot.
El origen ACP y los hashes SHA256 de los cinco archivos están registrados en
`provenance.json`; sus bytes se comprueban en tests.

El servidor merchant y el adaptador validan create, get, update y cancel
contra el bundle congelado. El alcance de update es seleccionar la única
opción de envío existente; cancel acepta cuerpo vacío o únicamente
`intent_trace.reason_code`. Hay pruebas del servidor HTTP, idempotencia,
errores tipados, aislamiento y concurrencia. El cliente HTTP del Buyer Agent
no forma parte de este repositorio.

Discovery público y la exportación estática de Feed P0 se validan contra
`DiscoveryResponse`, `FeedMetadata` y `Product` del snapshot. El feed es un
reemplazo completo, no la Feed API incremental.

Siguen pendientes complete, capacidad de pago, order/payment y el resto de
la cobertura necesaria para conformidad ACP integral.
