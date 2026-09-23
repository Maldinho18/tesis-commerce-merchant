import logging
from html import escape
from time import perf_counter
from typing import Annotated, Any, Never
from uuid import uuid4

import psycopg
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from commerce_lab import __version__
from commerce_lab.acp import (
    ACPCheckoutAdapter,
    ACPCheckoutCreateRequest,
)
from commerce_lab.context import InvalidLabSession, authenticate_lab_session
from commerce_lab.contracts import (
    ACP_VERSION,
    CatalogSearchData,
    CatalogSearchInput,
    ExecutionContext,
    Failure,
    Identifier,
    Offer,
    OfferGetInput,
    Success,
)
from commerce_lab.db import DatabaseNotReady, check_database_ready, database_url
from commerce_lab.discovery import discovery_document
from commerce_lab.payment_sandbox import config_schema, handler_spec, instrument_schema
from commerce_lab.persistent_catalog import PersistentCatalogReader
from commerce_lab.request_observability import (
    RequestObservation,
    classify_checkout_route,
    hash_idempotency_key,
    write_request_observation,
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Commerce Lab",
    version=__version__,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

_PUBLIC_ERROR_CODES = {
    "IDEMPOTENCY_CONFLICT": "idempotency_conflict",
    "IDEMPOTENCY_IN_FLIGHT": "idempotency_in_flight",
    "OFFER_NOT_FOUND": "invalid_item",
    "OUT_OF_STOCK": "out_of_stock",
    "PAYMENT_DECLINED": "payment_declined",
}


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = str(uuid4())
    request.state.request_id = request_id
    route = classify_checkout_route(request.method, request.url.path)
    if route is not None:
        request.state.observation_run_id = None
        request.state.observation_actor_id = None
        request.state.observation_checkout_id = route.checkout_id
        request.state.observation_order_id = None
        request.state.observation_error_code = None
        idempotency_sha256 = (
            None
            if route.operation == "get"
            else hash_idempotency_key(request.headers.get("Idempotency-Key"))
        )
    else:
        idempotency_sha256 = None

    started_at = perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        if route is not None:
            latency_ms = max(0, round((perf_counter() - started_at) * 1000))
            observation = RequestObservation(
                request_id=request_id,
                run_id=request.state.observation_run_id,
                actor_id=request.state.observation_actor_id,
                operation=route.operation,
                result="error",
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                latency_ms=latency_ms,
                checkout_id=request.state.observation_checkout_id,
                order_id=request.state.observation_order_id,
                idempotency_sha256=idempotency_sha256,
                error_code=request.state.observation_error_code,
            )
            await run_in_threadpool(_write_observation_safely, observation)
        raise
    latency_ms = max(0, round((perf_counter() - started_at) * 1000))
    response.headers["Request-Id"] = request_id
    if route is not None:
        observation = RequestObservation(
            request_id=request_id,
            run_id=request.state.observation_run_id,
            actor_id=request.state.observation_actor_id,
            operation=route.operation,
            result="success" if response.status_code < 400 else "error",
            http_status=response.status_code,
            latency_ms=latency_ms,
            checkout_id=request.state.observation_checkout_id,
            order_id=request.state.observation_order_id,
            idempotency_sha256=idempotency_sha256,
            error_code=request.state.observation_error_code,
        )
        await run_in_threadpool(_write_observation_safely, observation)
    return response


def _write_observation_safely(observation: RequestObservation) -> None:
    try:
        write_request_observation(observation)
    except Exception:
        logger.exception(
            "Failed to persist checkout request observation",
            extra={"request_id": observation.request_id, "operation": observation.operation},
        )


@app.get("/.well-known/acp.json", include_in_schema=False)
def discovery() -> JSONResponse:
    return JSONResponse(
        content=discovery_document(),
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/payment-handlers/tesis-sandbox/spec", include_in_schema=False)
def payment_handler_spec() -> JSONResponse:
    return JSONResponse(
        content=handler_spec(),
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/payment-handlers/tesis-sandbox/config-schema", include_in_schema=False)
def payment_handler_config_schema() -> JSONResponse:
    return JSONResponse(
        content=config_schema(),
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/payment-handlers/tesis-sandbox/instrument-schema", include_in_schema=False)
def payment_handler_instrument_schema() -> JSONResponse:
    return JSONResponse(
        content=instrument_schema(),
        headers={"Cache-Control": "public, max-age=3600"},
    )


class HealthResponse(BaseModel):
    status: str
    database: str | None = None
    migrations: str | None = None
    model: str = "not_checked_by_this_endpoint"


def trusted_context(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> ExecutionContext:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid synthetic lab session is required.",
        )
    try:
        context = authenticate_lab_session(token)
    except InvalidLabSession as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid synthetic lab session is required.",
        ) from error
    trusted = context.model_copy(update={"request_id": request.state.request_id})
    request.state.observation_run_id = trusted.run_id
    request.state.observation_actor_id = trusted.actor_id
    return trusted


def persistent_catalog(
    context: Annotated[ExecutionContext, Depends(trusted_context)],
) -> PersistentCatalogReader:
    return PersistentCatalogReader(context)


def require_acp_version(
    request: Request,
    api_version: Annotated[str | None, Header(alias="API-Version")] = None,
) -> None:
    if api_version != ACP_VERSION:
        missing = api_version is None
        public_code = "missing_api_version" if missing else "unsupported_api_version"
        request.state.observation_error_code = public_code
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": public_code,
                "message": (
                    "API-Version header is required."
                    if missing
                    else "API-Version is not supported."
                ),
                "supported_versions": [ACP_VERSION],
            },
        )


def acp_checkout(
    context: Annotated[ExecutionContext, Depends(trusted_context)],
) -> ACPCheckoutAdapter:
    return ACPCheckoutAdapter(context)


def _raise_commerce_failure(
    failure: Failure,
    headers: dict[str, str] | None = None,
    *,
    request: Request | None = None,
) -> Never:
    internal_code = failure.error.code
    if internal_code in {"OFFER_NOT_FOUND", "CHECKOUT_NOT_FOUND"}:
        status_code = status.HTTP_404_NOT_FOUND
    elif internal_code == "FORBIDDEN":
        status_code = status.HTTP_403_FORBIDDEN
    elif internal_code == "INVALID_INPUT":
        status_code = status.HTTP_400_BAD_REQUEST
    elif internal_code == "IDEMPOTENCY_IN_FLIGHT":
        status_code = status.HTTP_409_CONFLICT
    elif internal_code == "IDEMPOTENCY_CONFLICT" or internal_code == "PAYMENT_DECLINED":
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    elif internal_code in {"CHECKOUT_TERMS_CHANGED", "CHECKOUT_NOT_COMPLETABLE"}:
        status_code = status.HTTP_409_CONFLICT
    elif internal_code == "PROVIDER_UNAVAILABLE":
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif internal_code == "CHECKOUT_NOT_CANCELABLE":
        status_code = status.HTTP_405_METHOD_NOT_ALLOWED
    else:
        status_code = status.HTTP_409_CONFLICT
    public_code = _PUBLIC_ERROR_CODES.get(internal_code, internal_code)
    if request is not None:
        request.state.observation_error_code = public_code
    error_headers = dict(headers or {})
    if internal_code == "IDEMPOTENCY_IN_FLIGHT":
        error_headers.setdefault("Retry-After", "1")
    detail = failure.error.model_dump(mode="json")
    detail["code"] = public_code
    raise HTTPException(
        status_code=status_code,
        detail=detail,
        headers=error_headers or None,
    )


@app.get("/health/live", response_model=HealthResponse)
def live() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/health/ready", response_model=HealthResponse)
def ready(response: Response) -> HealthResponse:
    try:
        check_database_ready()
    except DatabaseNotReady:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="not_ready", database="unavailable", migrations="unknown")
    return HealthResponse(status="ok", database="ready", migrations="applied")


@app.post("/lab/catalog/search", response_model=Success[CatalogSearchData])
def catalog_search(
    payload: CatalogSearchInput,
    response: Response,
    context: Annotated[ExecutionContext, Depends(trusted_context)],
    catalog: Annotated[PersistentCatalogReader, Depends(persistent_catalog)],
) -> Success[CatalogSearchData]:
    response.headers["X-Request-Id"] = context.request_id
    return catalog.search(payload)


@app.post("/lab/offers/get", response_model=Success[Offer] | Failure)
def offer_get(
    payload: OfferGetInput,
    response: Response,
    context: Annotated[ExecutionContext, Depends(trusted_context)],
    catalog: Annotated[PersistentCatalogReader, Depends(persistent_catalog)],
) -> Success[Offer] | Failure:
    response.headers["X-Request-Id"] = context.request_id
    return catalog.get(payload)


@app.post("/checkout_sessions", status_code=status.HTTP_201_CREATED)
def checkout_session_create(
    payload: ACPCheckoutCreateRequest,
    request: Request,
    response: Response,
    _: Annotated[None, Depends(require_acp_version)],
    context: Annotated[ExecutionContext, Depends(trusted_context)],
    checkout: Annotated[ACPCheckoutAdapter, Depends(acp_checkout)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, object]:
    if not idempotency_key or len(idempotency_key) > 255:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key must contain between 1 and 255 characters.",
        )
    result = checkout.create(payload, idempotency_key)
    if isinstance(result, Failure):
        _raise_commerce_failure(result, request=request)
    response.headers["Request-Id"] = context.request_id
    response.headers["Idempotency-Key"] = idempotency_key
    request.state.observation_checkout_id = result["id"]
    return result


@app.get("/checkout_sessions/{checkout_id}")
def checkout_session_get(
    checkout_id: Identifier,
    request: Request,
    response: Response,
    _: Annotated[None, Depends(require_acp_version)],
    context: Annotated[ExecutionContext, Depends(trusted_context)],
    checkout: Annotated[ACPCheckoutAdapter, Depends(acp_checkout)],
) -> dict[str, object]:
    result = checkout.get(checkout_id)
    if isinstance(result, Failure):
        _raise_commerce_failure(result, request=request)
    response.headers["Request-Id"] = context.request_id
    return result


@app.post("/checkout_sessions/{checkout_id}/complete")
def checkout_session_complete(
    checkout_id: Identifier,
    payload: Annotated[Any, Body()],
    request: Request,
    response: Response,
    _: Annotated[None, Depends(require_acp_version)],
    context: Annotated[ExecutionContext, Depends(trusted_context)],
    checkout: Annotated[ACPCheckoutAdapter, Depends(acp_checkout)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, object]:
    if not idempotency_key or len(idempotency_key) > 255:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key must contain between 1 and 255 characters.",
        )
    result = checkout.complete(checkout_id, payload, idempotency_key)
    if isinstance(result, Failure):
        error_headers = {
            "Request-Id": context.request_id,
            "Idempotency-Key": idempotency_key,
        }
        if checkout.last_completion_replayed:
            error_headers["Idempotent-Replayed"] = "true"
        _raise_commerce_failure(result, headers=error_headers, request=request)
    response.headers["Request-Id"] = context.request_id
    response.headers["Idempotency-Key"] = idempotency_key
    if checkout.last_completion_replayed:
        response.headers["Idempotent-Replayed"] = "true"
    order = result.get("order")
    if isinstance(order, dict):
        request.state.observation_order_id = order.get("id")
    return result


@app.get("/orders/{order_id}", response_class=HTMLResponse, include_in_schema=False)
def order_permalink(order_id: str) -> HTMLResponse:
    with psycopg.connect(database_url()) as connection:
        row = connection.execute(
            "SELECT snapshot FROM orders WHERE order_id = %s",
            (order_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")
    snapshot = row[0]
    line = snapshot.get("title", "")
    currency = str(snapshot.get("currency", "cop")).upper()

    def money(minor: object) -> str:
        """Los montos se guardan en unidades menores; el permalink es para una persona."""
        if not isinstance(minor, int):
            return escape(str(minor))
        units, cents = divmod(minor, 100)
        return f"$ {units:,.0f}".replace(",", ".") + f",{cents:02d} {currency}"

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Order {escape(snapshot["order_number"])}</title></head>
<body>
<h1>Order {escape(snapshot["order_number"])}</h1>
<p>Status: {escape(snapshot["status"])}</p>
<p>Product: {escape(line)}</p>
<p>Quantity: {snapshot["quantity"]}</p>
<p>Unit price: {money(snapshot["unit_price"])}</p>
<p>Subtotal: {money(snapshot["subtotal"])}</p>
<p>Shipping: {money(snapshot["shipping_total"])}</p>
<p>Total: {money(snapshot["total"])}</p>
<p>Fulfillment: shipping / pending</p>
</body></html>"""
    return HTMLResponse(content=html)


@app.post("/checkout_sessions/{checkout_id}")
def checkout_session_update(
    checkout_id: Identifier,
    payload: dict[str, Any],
    request: Request,
    response: Response,
    _: Annotated[None, Depends(require_acp_version)],
    context: Annotated[ExecutionContext, Depends(trusted_context)],
    checkout: Annotated[ACPCheckoutAdapter, Depends(acp_checkout)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, object]:
    if not idempotency_key or len(idempotency_key) > 255:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key must contain between 1 and 255 characters.",
        )
    result = checkout.update(checkout_id, payload, idempotency_key)
    if isinstance(result, Failure):
        _raise_commerce_failure(result, request=request)
    response.headers["Request-Id"] = context.request_id
    response.headers["Idempotency-Key"] = idempotency_key
    return result


@app.post("/checkout_sessions/{checkout_id}/cancel")
def checkout_session_cancel(
    checkout_id: Identifier,
    request: Request,
    response: Response,
    _: Annotated[None, Depends(require_acp_version)],
    context: Annotated[ExecutionContext, Depends(trusted_context)],
    checkout: Annotated[ACPCheckoutAdapter, Depends(acp_checkout)],
    payload: dict[str, Any] | None = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, object]:
    if not idempotency_key or len(idempotency_key) > 255:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key must contain between 1 and 255 characters.",
        )
    result = checkout.cancel(checkout_id, payload, idempotency_key)
    if isinstance(result, Failure):
        _raise_commerce_failure(result, request=request)
    response.headers["Request-Id"] = context.request_id
    response.headers["Idempotency-Key"] = idempotency_key
    return result
