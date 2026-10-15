"""Isolated lab route: typed, non-echoing errors and no-store, including dependencies."""

from collections.abc import Callable
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from commerce_lab.contracts import ExecutionContext
from commerce_lab.contracts.creation_lookup import (
    LOOKUP_SCHEMA,
    CreationLookupError,
    CreationLookupInput,
    CreationLookupResult,
)
from commerce_lab.creation_lookup import CheckoutCreationLookup

LOOKUP_PATH = "/lab/recovery/checkout-creation/lookup"


class _LookupRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def guarded(request: Request):
            code, status = "lookup_unavailable", 503
            try:
                response = await original(request)
                response.headers["Cache-Control"] = "no-store"
                return response
            except RequestValidationError:
                code, status = "invalid_request", 422
            except HTTPException as error:
                status = error.status_code
                code = {
                    400: "invalid_api_version",
                    401: "unauthenticated",
                    422: "invalid_request",
                }.get(status, "lookup_unavailable")
            except Exception:
                # Do not reflect DB errors, exception text, submitted bodies or headers.
                pass
            result = CreationLookupError.model_validate(
                {
                    "schema_version": LOOKUP_SCHEMA,
                    "result": "error",
                    "code": code,
                    "request_id": getattr(request.state, "request_id", str(uuid4())),
                }
            )
            return JSONResponse(
                result.model_dump(mode="json"),
                status_code=status,
                headers={"Cache-Control": "no-store"},
            )

        return guarded


def creation_lookup_router(
    context_dependency: Callable[..., ExecutionContext],
    version_dependency: Callable[..., None],
) -> APIRouter:
    router = APIRouter(route_class=_LookupRoute, include_in_schema=False)

    @router.post(
        LOOKUP_PATH,
        response_model=CreationLookupResult,
        dependencies=[Depends(version_dependency)],
        responses={code: {"model": CreationLookupError} for code in (400, 401, 422, 503)},
    )
    def lookup_creation(
        request: Request,
        payload: CreationLookupInput,
        context: Annotated[ExecutionContext, Depends(context_dependency)],
    ) -> CreationLookupResult:
        if request.query_params:
            raise HTTPException(422, "Query parameters are not supported")
        return CheckoutCreationLookup(context).lookup(payload)

    return router
