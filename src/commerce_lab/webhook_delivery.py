import hashlib
import hmac
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx
import psycopg
from psycopg.types.json import Jsonb

from commerce_lab.contracts import OrderRecord
from commerce_lab.db import database_url
from commerce_lab.order_projection import webhook_order_event
from commerce_lab.settings import get_settings

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
BACKOFF_SECONDS = (1, 2, 4, 8)
WEBHOOK_PATH = "/agentic_checkout/webhooks/order_events"


def _canonical_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def payload_sha256(raw_body: bytes) -> str:
    return hashlib.sha256(raw_body).hexdigest()


def sign_payload(secret: str, timestamp: int, raw_body: bytes) -> str:
    signed = str(timestamp).encode("utf-8") + b"." + raw_body
    digest = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def enqueue_order_event(
    connection: psycopg.Connection[Any],
    *,
    run_id: str,
    actor_id: str,
    scenario_at: str,
    event_type: str,
    order: OrderRecord,
) -> str:
    if event_type not in {"order_create", "order_update"}:
        raise ValueError("Unsupported webhook event type")
    payload = webhook_order_event(event_type, order)
    raw_body = _canonical_payload(payload)
    digest = payload_sha256(raw_body)
    delivery_id = f"whd_{hashlib.sha256(raw_body + order.id.encode()).hexdigest()[:32]}"
    connection.execute(
        """
        INSERT INTO webhook_deliveries
          (delivery_id, run_id, actor_id, event_type, order_id, payload,
           payload_sha256, attempt_count, next_attempt_at, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 0, %s, %s, %s)
        ON CONFLICT (run_id, event_type, order_id, payload_sha256) DO NOTHING
        """,
        (
            delivery_id,
            run_id,
            actor_id,
            event_type,
            order.id,
            Jsonb(payload),
            digest,
            scenario_at,
            scenario_at,
            scenario_at,
        ),
    )
    return delivery_id


def _valid_receiver_url(value: str) -> bool:
    parsed = urlparse(value)
    local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    return bool(
        parsed.scheme in {"http", "https"}
        and (local or parsed.scheme == "https")
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
        and parsed.path in {"", "/"}
    )


def _next_attempt(attempt_no: int) -> datetime:
    return datetime.now(UTC) + timedelta(seconds=BACKOFF_SECONDS[attempt_no - 1])


class WebhookDispatcher:
    def __init__(self, *, timeout_seconds: float = 5.0) -> None:
        if not 0 < timeout_seconds <= 30:
            raise ValueError("Webhook timeout must be between 0 and 30 seconds")
        self._timeout_seconds = timeout_seconds

    def dispatch_due(self, *, limit: int = 1) -> list[dict[str, object]]:
        if limit < 1:
            raise ValueError("Webhook dispatch limit must be positive")
        results: list[dict[str, object]] = []
        for _ in range(limit):
            result = self.dispatch_one()
            if result is None:
                break
            results.append(result)
        return results

    def dispatch_one(self) -> dict[str, object] | None:
        settings = get_settings()
        if not settings.webhook_receiver_url or not settings.merchant_webhook_secret:
            logger.info("webhook delivery skipped: configuration unavailable")
            return None
        if not _valid_receiver_url(settings.webhook_receiver_url):
            logger.error("webhook delivery disabled: receiver URL is invalid")
            return None

        with psycopg.connect(database_url()) as connection, connection.transaction():
            row = connection.execute(
                """
                SELECT delivery_id, run_id, actor_id, event_type, order_id, payload,
                       payload_sha256, attempt_count
                FROM webhook_deliveries
                WHERE delivered_at IS NULL
                  AND attempt_count < %s
                  AND next_attempt_at <= now()
                  AND (
                    attempt_count = 0
                    OR last_error IN ('TIMEOUT', 'CONNECTION_ERROR', 'HTTP_429')
                    OR last_error LIKE 'HTTP_5%%'
                  )
                ORDER BY next_attempt_at, created_at, delivery_id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """,
                (MAX_ATTEMPTS,),
            ).fetchone()
            if row is None:
                return None
            (
                delivery_id,
                run_id,
                _actor_id,
                event_type,
                order_id,
                payload,
                expected_digest,
                attempt_count,
            ) = row
            raw_body = _canonical_payload(payload)
            actual_digest = payload_sha256(raw_body)
            attempt_no = attempt_count + 1
            attempted_at = datetime.now(UTC)
            if actual_digest != expected_digest:
                outcome, status_code, error_code = "terminal", None, "PAYLOAD_HASH_MISMATCH"
            else:
                outcome, status_code, error_code = self._send(
                    settings.webhook_receiver_url,
                    settings.merchant_webhook_secret,
                    str(delivery_id),
                    raw_body,
                )
            if outcome == "retry" and attempt_no >= MAX_ATTEMPTS:
                outcome = "exhausted"
                error_code = error_code or "MAX_ATTEMPTS"
            finished_at = datetime.now(UTC)
            latency_ms = max(0, round((finished_at - attempted_at).total_seconds() * 1000))
            connection.execute(
                """
                INSERT INTO webhook_delivery_attempts
                  (delivery_id, attempt_no, attempted_at, finished_at,
                   http_status, outcome, latency_ms, error_code)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    delivery_id,
                    attempt_no,
                    attempted_at,
                    finished_at,
                    status_code,
                    outcome,
                    latency_ms,
                    error_code,
                ),
            )
            if outcome == "delivered":
                connection.execute(
                    """
                    UPDATE webhook_deliveries
                    SET attempt_count = %s, delivered_at = %s, last_http_status = %s,
                        last_error = NULL, updated_at = %s
                    WHERE delivery_id = %s
                    """,
                    (attempt_no, finished_at, status_code, finished_at, delivery_id),
                )
            elif outcome == "retry" and attempt_no < MAX_ATTEMPTS:
                connection.execute(
                    """
                    UPDATE webhook_deliveries
                    SET attempt_count = %s, next_attempt_at = %s, last_http_status = %s,
                        last_error = %s, updated_at = %s
                    WHERE delivery_id = %s
                    """,
                    (
                        attempt_no,
                        _next_attempt(attempt_no),
                        status_code,
                        error_code,
                        finished_at,
                        delivery_id,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE webhook_deliveries
                    SET attempt_count = %s, next_attempt_at = %s, last_http_status = %s,
                        last_error = %s, updated_at = %s
                    WHERE delivery_id = %s
                    """,
                    (
                        attempt_no,
                        finished_at,
                        status_code,
                        error_code or "MAX_ATTEMPTS",
                        finished_at,
                        delivery_id,
                    ),
                )
            logger.info(
                "webhook delivery %s run=%s order=%s event=%s attempt=%s outcome=%s "
                "status=%s latency_ms=%s error=%s",
                delivery_id,
                run_id,
                order_id,
                event_type,
                attempt_no,
                outcome,
                status_code,
                latency_ms,
                error_code,
            )
            return {
                "delivery_id": str(delivery_id),
                "attempt_no": attempt_no,
                "outcome": outcome,
                "http_status": status_code,
                "error_code": error_code,
            }

    def _send(
        self, origin: str, secret: str, delivery_id: str, raw_body: bytes
    ) -> tuple[str, int | None, str | None]:
        timestamp = int(time.time())
        signature = sign_payload(secret, timestamp, raw_body)
        headers = {
            "Content-Type": "application/json",
            "Request-Id": delivery_id,
            "Merchant-Signature": signature,
        }
        try:
            response = httpx.post(
                origin.rstrip("/") + WEBHOOK_PATH,
                content=raw_body,
                headers=headers,
                timeout=self._timeout_seconds,
                follow_redirects=False,
                trust_env=False,
            )
        except httpx.TimeoutException:
            return "retry", None, "TIMEOUT"
        except httpx.RequestError:
            return "retry", None, "CONNECTION_ERROR"
        if response.status_code == 200:
            try:
                body = response.json()
            except ValueError:
                return "terminal", response.status_code, "INVALID_RESPONSE"
            if (
                not isinstance(body, dict)
                or body.get("received") is not True
                or (body.get("request_id") is not None and body.get("request_id") != delivery_id)
            ):
                return "terminal", response.status_code, "INVALID_RESPONSE"
            return "delivered", response.status_code, None
        if response.status_code == 429 or response.status_code >= 500:
            return "retry", response.status_code, f"HTTP_{response.status_code}"
        return "terminal", response.status_code, f"HTTP_{response.status_code}"


def update_order_to_processing(
    connection: psycopg.Connection[Any],
    *,
    run_id: str,
    actor_id: str,
    order_id: str,
    scenario_at: str,
) -> OrderRecord:
    row = connection.execute(
        """
        SELECT snapshot FROM orders
        WHERE run_id = %s AND actor_id = %s AND order_id = %s
        FOR UPDATE
        """,
        (run_id, actor_id, order_id),
    ).fetchone()
    if row is None:
        raise ValueError("Order does not exist in this episode")
    order = OrderRecord.model_validate(row[0])
    if order.status == "confirmed":
        changed = OrderRecord.model_validate(
            {**order.model_dump(mode="json"), "status": "processing"}
        )
        connection.execute(
            "UPDATE orders SET snapshot = %s WHERE order_id = %s",
            (Jsonb(changed.model_dump(mode="json")), order_id),
        )
        enqueue_order_event(
            connection,
            run_id=run_id,
            actor_id=actor_id,
            scenario_at=scenario_at,
            event_type="order_update",
            order=changed,
        )
        return changed
    if order.status == "processing":
        return order
    raise ValueError("Order is not eligible for P0 processing update")
