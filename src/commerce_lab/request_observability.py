import hashlib
import re
from dataclasses import dataclass
from typing import Literal

import psycopg

from commerce_lab.db import database_url

CheckoutOperation = Literal["create", "get", "update", "complete", "cancel"]
RequestResult = Literal["success", "error"]

_CHECKOUT_PATH = re.compile(r"^/checkout_sessions/([^/]+)$")
_CHECKOUT_ACTION_PATH = re.compile(r"^/checkout_sessions/([^/]+)/(complete|cancel)$")


@dataclass(frozen=True)
class CheckoutRoute:
    operation: CheckoutOperation
    checkout_id: str | None


@dataclass(frozen=True)
class RequestObservation:
    request_id: str
    run_id: str | None
    actor_id: str | None
    operation: CheckoutOperation
    result: RequestResult
    http_status: int
    latency_ms: int
    checkout_id: str | None
    order_id: str | None
    idempotency_sha256: str | None
    error_code: str | None


def classify_checkout_route(method: str, path: str) -> CheckoutRoute | None:
    normalized_method = method.upper()
    if normalized_method == "POST" and path == "/checkout_sessions":
        return CheckoutRoute(operation="create", checkout_id=None)

    action_match = _CHECKOUT_ACTION_PATH.fullmatch(path)
    if normalized_method == "POST" and action_match is not None:
        operation = action_match.group(2)
        if operation == "complete":
            return CheckoutRoute(operation="complete", checkout_id=action_match.group(1))
        return CheckoutRoute(operation="cancel", checkout_id=action_match.group(1))

    checkout_match = _CHECKOUT_PATH.fullmatch(path)
    if checkout_match is None:
        return None
    if normalized_method == "GET":
        return CheckoutRoute(operation="get", checkout_id=checkout_match.group(1))
    if normalized_method == "POST":
        return CheckoutRoute(operation="update", checkout_id=checkout_match.group(1))
    return None


def hash_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def write_request_observation(observation: RequestObservation) -> None:
    with psycopg.connect(database_url()) as connection, connection.transaction():
        connection.execute(
            """
            INSERT INTO request_observations
              (request_id, run_id, actor_id, operation, result, http_status,
               latency_ms, checkout_id, order_id, idempotency_sha256, error_code)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                observation.request_id,
                observation.run_id,
                observation.actor_id,
                observation.operation,
                observation.result,
                observation.http_status,
                observation.latency_ms,
                observation.checkout_id,
                observation.order_id,
                observation.idempotency_sha256,
                observation.error_code,
            ),
        )
