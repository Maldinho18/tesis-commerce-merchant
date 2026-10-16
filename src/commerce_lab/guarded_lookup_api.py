"""Private, bounded and non-echoing read-only history route."""

import json
from collections.abc import Callable
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from commerce_lab.contracts import ExecutionContext
from commerce_lab.contracts.guarded_lookup import (
    MAX_RESPONSE_BYTES,
    GuardProofLookupError,
    GuardProofLookupInput,
    GuardProofLookupResult,
)
from commerce_lab.guarded_creation_api import _unique_pairs
from commerce_lab.guarded_lookup import GuardHistoryInvalid, GuardProofLookup

LOOKUP_PATH = "/lab/recovery/guarded-checkout-creation/lookup"
MAX_REQUEST_BYTES = 2048


def _invalid_constant(value):
    raise ValueError("Non-JSON constant")


class _GuardProofRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def guarded(request: Request):
            code, status = "lookup_unavailable", 503
            try:
                if request.method != "POST":
                    raise HTTPException(405)
                if request.query_params:
                    raise HTTPException(422)
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > MAX_REQUEST_BYTES:
                        raise HTTPException(422)
                request._body = bytes(body)
                try:
                    json.loads(
                        body, object_pairs_hook=_unique_pairs, parse_constant=_invalid_constant
                    )
                except (ValueError, UnicodeError):
                    raise HTTPException(422) from None
                response = await original(request)
                if len(response.body) > MAX_RESPONSE_BYTES:
                    code = "response_too_large"
                elif response.status_code != 200:
                    raise RuntimeError("Unexpected lookup response")
                else:
                    response.headers["Cache-Control"] = "no-store"
                    return response
            except RequestValidationError:
                code, status = "invalid_request", 422
            except HTTPException as error:
                status = error.status_code
                code = {
                    400: "invalid_api_version",
                    401: "unauthenticated",
                    405: "invalid_request",
                    422: "invalid_request",
                }.get(status, "lookup_unavailable")
            except GuardHistoryInvalid:
                code, status = "history_invalid", 500
            except Exception:
                pass
            result = GuardProofLookupError.model_validate(
                {"code": code, "request_id": getattr(request.state, "request_id", str(uuid4()))}
            )
            return JSONResponse(
                result.model_dump(mode="json"),
                status_code=status,
                headers={"Cache-Control": "no-store"},
            )

        return guarded


def guarded_lookup_router(
    context_dependency: Callable[..., ExecutionContext], version_dependency: Callable[..., None]
) -> APIRouter:
    router = APIRouter(route_class=_GuardProofRoute, include_in_schema=False)

    @router.post(
        LOOKUP_PATH,
        response_model=GuardProofLookupResult,
        dependencies=[Depends(version_dependency)],
    )
    def lookup(
        payload: GuardProofLookupInput,
        context: Annotated[ExecutionContext, Depends(context_dependency)],
    ) -> GuardProofLookupResult:
        return GuardProofLookup(context).lookup(payload)

    @router.api_route(LOOKUP_PATH, methods=["GET", "HEAD", "PUT", "PATCH", "DELETE", "OPTIONS"])
    @router.api_route(
        LOOKUP_PATH + "/", methods=["POST", "GET", "HEAD", "PUT", "PATCH", "DELETE", "OPTIONS"]
    )
    def reject_noncanonical_request():
        # Keep errors typed/no-store and override redirects for this route only.
        raise HTTPException(422)

    return router
