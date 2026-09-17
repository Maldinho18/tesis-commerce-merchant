# Merchant experimental

Este repositorio ejecuta únicamente el merchant ACP REST local. Python 3.12 y uv; use
`uv sync`, no `pip`, y no edite `uv.lock` a mano.

PostgreSQL es la fuente autoritativa de catálogo, checkout, idempotencia y eventos.
Use SQL explícito con Psycopg; un ORM requiere decisión técnica justificada.
Mantenga separado el dominio interno de `ACPCheckoutAdapter`.

ACP está fijado en 2026-04-17. No modifique archivos en
`vendor/acp/2026-04-17`. El servicio usa únicamente datos y credenciales
sintéticos locales: sin dinero real, credenciales reales ni LLM dentro del merchant.
El cliente no fija precio autoritativo. Todo POST con efecto debe ser idempotente.

La base se publica solo en 127.0.0.1:55433 y FastAPI solo en 127.0.0.1:4120.
No incorpore Buyer Agent, LangGraph, navegador, payment, order ni OPA en esta extracción.
