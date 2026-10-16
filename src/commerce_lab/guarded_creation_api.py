"""Private versioned route. No changes to ACP discovery or lookup schemas."""

import json
from collections.abc import Callable
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from commerce_lab.contracts import ExecutionContext
from commerce_lab.contracts.guarded_creation import GuardedError, GuardedInput, GuardedResult
from commerce_lab.guarded_creation import GuardedCreation, GuardRejected

GUARDED_PATH = "/lab/governance/checkout-creation/guarded"


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate request field")
        result[key] = value
    return result


class _GuardedRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def guarded(request: Request):
            code, status = "guard_unavailable", 503
            historical = False
            try:
                if request.query_params:
                    raise HTTPException(422)
                body = await request.body()
                if len(body) > 32768:
                    raise HTTPException(422)
                try:
                    json.loads(body, object_pairs_hook=_unique_pairs)
                except (ValueError, UnicodeError):
                    raise HTTPException(422) from None
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
                }.get(status, "guard_unavailable")
            except GuardRejected as error:
                code, status = error.code, 409
                historical = error.historical
                if code == "invalid_request":
                    status = 422
            except Exception:
                # No request, raw key, DB error or credential is reflected.
                pass
            payload = GuardedError.model_validate(
                {
                    "code": code,
                    "historical": historical,
                    "request_id": getattr(request.state, "request_id", str(uuid4())),
                }
            )
            return JSONResponse(
                payload.model_dump(mode="json"),
                status_code=status,
                headers={"Cache-Control": "no-store"},
            )

        return guarded


def guarded_creation_router(
    context_dependency: Callable[..., ExecutionContext], version_dependency: Callable[..., None]
) -> APIRouter:
    router = APIRouter(route_class=_GuardedRoute, include_in_schema=False)

    @router.post(
        GUARDED_PATH, response_model=GuardedResult, dependencies=[Depends(version_dependency)]
    )
    def create_guarded(
        request: Request,
        response: Response,
        payload: GuardedInput,
        context: Annotated[ExecutionContext, Depends(context_dependency)],
        key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> GuardedResult:
        result = GuardedCreation(context).create(payload, key)
        response.status_code = 201 if result.result == "created" else 200
        return result

    return router
