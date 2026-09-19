from typing import Annotated, Any, Never

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

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
from commerce_lab.db import DatabaseNotReady, check_database_ready
from commerce_lab.discovery import discovery_document
from commerce_lab.payment_sandbox import config_schema, handler_spec, instrument_schema
from commerce_lab.persistent_catalog import PersistentCatalogReader

app = FastAPI(
    title="Commerce Lab",
    version=__version__,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
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
    authorization: Annotated[str | None, Header()] = None,
) -> ExecutionContext:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid synthetic lab session is required.",
        )
    try:
        return authenticate_lab_session(token)
    except InvalidLabSession as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid synthetic lab session is required.",
        ) from error


def persistent_catalog(
    context: Annotated[ExecutionContext, Depends(trusted_context)],
) -> PersistentCatalogReader:
    return PersistentCatalogReader(context)


def require_acp_version(
    api_version: Annotated[str | None, Header(alias="API-Version")] = None,
) -> None:
    if api_version != ACP_VERSION:
        missing = api_version is None
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "missing_api_version" if missing else "unsupported_api_version",
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


def _raise_commerce_failure(failure: Failure) -> Never:
    code = failure.error.code
    if code in {"OFFER_NOT_FOUND", "CHECKOUT_NOT_FOUND"}:
        status_code = status.HTTP_404_NOT_FOUND
    elif code == "FORBIDDEN":
        status_code = status.HTTP_403_FORBIDDEN
    elif code == "INVALID_INPUT":
        status_code = status.HTTP_400_BAD_REQUEST
    elif code == "IDEMPOTENCY_IN_FLIGHT":
        status_code = status.HTTP_409_CONFLICT
    elif code == "IDEMPOTENCY_CONFLICT":
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    elif code == "CHECKOUT_NOT_CANCELABLE":
        status_code = status.HTTP_405_METHOD_NOT_ALLOWED
    else:
        status_code = status.HTTP_409_CONFLICT
    raise HTTPException(status_code=status_code, detail=failure.error.model_dump(mode="json"))


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
        _raise_commerce_failure(result)
    response.headers["Request-Id"] = context.request_id
    response.headers["Idempotency-Key"] = idempotency_key
    return result


@app.get("/checkout_sessions/{checkout_id}")
def checkout_session_get(
    checkout_id: Identifier,
    response: Response,
    _: Annotated[None, Depends(require_acp_version)],
    context: Annotated[ExecutionContext, Depends(trusted_context)],
    checkout: Annotated[ACPCheckoutAdapter, Depends(acp_checkout)],
) -> dict[str, object]:
    result = checkout.get(checkout_id)
    if isinstance(result, Failure):
        _raise_commerce_failure(result)
    response.headers["Request-Id"] = context.request_id
    return result


@app.post("/checkout_sessions/{checkout_id}")
def checkout_session_update(
    checkout_id: Identifier,
    payload: dict[str, Any],
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
        _raise_commerce_failure(result)
    response.headers["Request-Id"] = context.request_id
    response.headers["Idempotency-Key"] = idempotency_key
    return result


@app.post("/checkout_sessions/{checkout_id}/cancel")
def checkout_session_cancel(
    checkout_id: Identifier,
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
        _raise_commerce_failure(result)
    response.headers["Request-Id"] = context.request_id
    response.headers["Idempotency-Key"] = idempotency_key
    return result
