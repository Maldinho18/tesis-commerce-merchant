import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from commerce_lab.contracts import (
    Checkout,
    CheckoutCancelInput,
    CheckoutGetInput,
    CheckoutPrepareInput,
    CheckoutUpdateInput,
    CommerceError,
    CommerceErrorCode,
    ExecutionContext,
    Failure,
    Offer,
    Success,
    parse_timestamp,
)
from commerce_lab.db import database_url


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _as_timestamp(value: Any) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _failure(code: CommerceErrorCode, message: str) -> Failure:
    return Failure(error=CommerceError(code=code, message=message))


class CheckoutService:
    """Persistent, episode-scoped checkout lifecycle without order or payment effects."""

    def __init__(self, context: ExecutionContext) -> None:
        self._context = context
        self._run_id = UUID(context.run_id)

    @property
    def run_id(self) -> str:
        return str(self._run_id)

    def prepare(self, raw: object) -> Success[Checkout] | Failure:
        payload = CheckoutPrepareInput.model_validate(raw)
        fingerprint = _sha256(
            _canonical(payload.model_dump(mode="json", exclude={"idempotency_key"}))
        )
        key_hash = _sha256(payload.idempotency_key)

        with psycopg.connect(database_url()) as connection, connection.transaction():
            run = self._load_run(connection)
            if run is None:
                return _failure("FORBIDDEN", "Execution context does not own the episode.")
            scenario_at = _as_timestamp(run[0])

            existing = self._existing(connection, key_hash, fingerprint, scenario_at)
            if existing is not None:
                return existing

            offer_row = connection.execute(
                """
                SELECT revision, snapshot
                FROM catalog_offers
                WHERE run_id = %s AND offer_id = %s
                FOR SHARE
                """,
                (self._run_id, payload.offer_id),
            ).fetchone()
            if offer_row is None:
                return _failure("OFFER_NOT_FOUND", "The offer does not exist in this episode.")
            offer = Offer.model_validate(offer_row[1])
            validation = self._validate_offer(offer, payload, scenario_at)
            if validation is not None:
                return validation

            checkout = Checkout(
                id=f"chk_{uuid4().hex}",
                revision=1,
                status="prepared",
                offer_id=offer.id,
                offer_revision=offer.revision,
                quantity=1,
                pricing=offer.pricing.model_copy(deep=True),
                delivery_context=offer.delivery_context.model_copy(deep=True),
                delivery_days=offer.delivery_days,
                created_at=scenario_at,
                updated_at=scenario_at,
                expires_at=offer.expires_at,
            )
            inserted = connection.execute(
                """
                INSERT INTO checkout_sessions
                  (run_id, checkout_id, actor_id, revision, offer_id, offer_revision,
                   quantity, idempotency_sha256, request_fingerprint, status,
                   snapshot, create_snapshot,
                   created_at, updated_at, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id, actor_id, idempotency_sha256) DO NOTHING
                RETURNING checkout_id
                """,
                (
                    self._run_id,
                    checkout.id,
                    self._context.actor_id,
                    checkout.revision,
                    checkout.offer_id,
                    checkout.offer_revision,
                    checkout.quantity,
                    key_hash,
                    fingerprint,
                    checkout.status,
                    Jsonb(checkout.model_dump(mode="json")),
                    Jsonb(checkout.model_dump(mode="json")),
                    checkout.created_at,
                    checkout.updated_at,
                    checkout.expires_at,
                ),
            ).fetchone()
            if inserted is None:
                replay = self._existing(connection, key_hash, fingerprint, scenario_at)
                if replay is None:
                    return _failure(
                        "IDEMPOTENCY_IN_FLIGHT", "The checkout request is still being resolved."
                    )
                return replay
            self._record(connection, "checkout.prepared", scenario_at, checkout.id)
            return Success[Checkout](data=checkout)

    def get(self, raw: object) -> Success[Checkout] | Failure:
        payload = CheckoutGetInput.model_validate(raw)
        with psycopg.connect(database_url()) as connection, connection.transaction():
            run = self._load_run(connection)
            if run is None:
                return _failure("FORBIDDEN", "Execution context does not own the episode.")
            scenario_at = _as_timestamp(run[0])
            row = connection.execute(
                """
                SELECT snapshot
                FROM checkout_sessions
                WHERE run_id = %s AND actor_id = %s AND checkout_id = %s
                FOR UPDATE
                """,
                (self._run_id, self._context.actor_id, payload.checkout_id),
            ).fetchone()
            if row is None:
                return _failure(
                    "CHECKOUT_NOT_FOUND", "The checkout does not exist in this episode."
                )
            checkout = self._expire_if_needed(
                connection, Checkout.model_validate(row[0]), scenario_at
            )
            self._record(connection, "checkout.read", scenario_at, checkout.id)
            return Success[Checkout](data=checkout)

    def update(self, raw: object) -> Success[Checkout] | Failure:
        payload = CheckoutUpdateInput.model_validate(raw)
        return self._mutate(
            checkout_id=payload.checkout_id,
            operation="update",
            idempotency_key=payload.idempotency_key,
            content={"selected_fulfillment_option_id": payload.selected_fulfillment_option_id},
        )

    def cancel(self, raw: object) -> Success[Checkout] | Failure:
        payload = CheckoutCancelInput.model_validate(raw)
        return self._mutate(
            checkout_id=payload.checkout_id,
            operation="cancel",
            idempotency_key=payload.idempotency_key,
            content={} if payload.reason_code is None else {"reason_code": payload.reason_code},
        )

    def _mutate(
        self,
        *,
        checkout_id: str,
        operation: str,
        idempotency_key: str,
        content: dict[str, str],
    ) -> Success[Checkout] | Failure:
        key_hash = _sha256(idempotency_key)
        fingerprint = _sha256(_canonical(content))
        try:
            with psycopg.connect(database_url()) as connection, connection.transaction():
                run = self._load_run(connection)
                if run is None:
                    return _failure("FORBIDDEN", "Execution context does not own the episode.")
                scenario_at = _as_timestamp(run[0])
                row = connection.execute(
                    """
                    SELECT snapshot FROM checkout_sessions
                    WHERE run_id = %s AND actor_id = %s AND checkout_id = %s
                    FOR UPDATE NOWAIT
                    """,
                    (self._run_id, self._context.actor_id, checkout_id),
                ).fetchone()
                if row is None:
                    return _failure(
                        "CHECKOUT_NOT_FOUND", "The checkout does not exist in this episode."
                    )
                replay = connection.execute(
                    """
                    SELECT request_fingerprint, response_snapshot FROM checkout_mutations
                    WHERE run_id = %s AND actor_id = %s AND checkout_id = %s
                      AND operation = %s AND idempotency_sha256 = %s
                    """,
                    (self._run_id, self._context.actor_id, checkout_id, operation, key_hash),
                ).fetchone()
                if replay is not None:
                    if replay[0] != fingerprint:
                        return _failure(
                            "IDEMPOTENCY_CONFLICT",
                            "The idempotency key was used with different content.",
                        )
                    self._record(
                        connection, f"checkout.{operation}_replayed", scenario_at, checkout_id
                    )
                    return Success[Checkout](data=Checkout.model_validate(replay[1]))

                checkout = self._expire_if_needed(
                    connection, Checkout.model_validate(row[0]), scenario_at
                )
                if operation == "cancel" and checkout.status not in {"prepared", "expired"}:
                    return _failure("CHECKOUT_NOT_CANCELABLE", "Checkout cannot be canceled.")
                if operation == "update" and checkout.status != "prepared":
                    if checkout.status == "expired":
                        return _failure("CHECKOUT_EXPIRED", "Checkout has expired.")
                    return _failure("CHECKOUT_NOT_EDITABLE", "Checkout cannot be updated.")
                if operation == "update" and content["selected_fulfillment_option_id"] != (
                    f"ship_{checkout.id}"
                ):
                    return _failure("INVALID_INPUT", "Fulfillment option is unavailable.")

                changed = Checkout.model_validate(
                    {
                        **checkout.model_dump(mode="json"),
                        "revision": checkout.revision + 1,
                        "status": "canceled" if operation == "cancel" else checkout.status,
                        "updated_at": scenario_at,
                    }
                )
                connection.execute(
                    """
                    UPDATE checkout_sessions
                    SET revision = %s, status = %s, snapshot = %s, updated_at = %s
                    WHERE run_id = %s AND actor_id = %s AND checkout_id = %s
                    """,
                    (
                        changed.revision,
                        changed.status,
                        Jsonb(changed.model_dump(mode="json")),
                        changed.updated_at,
                        self._run_id,
                        self._context.actor_id,
                        checkout_id,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO checkout_mutations
                      (run_id, actor_id, checkout_id, operation, idempotency_sha256,
                       request_fingerprint, response_snapshot)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        self._run_id,
                        self._context.actor_id,
                        checkout_id,
                        operation,
                        key_hash,
                        fingerprint,
                        Jsonb(changed.model_dump(mode="json")),
                    ),
                )
                self._record(
                    connection,
                    "checkout.updated" if operation == "update" else "checkout.canceled",
                    scenario_at,
                    checkout_id,
                )
                return Success[Checkout](data=changed)
        except psycopg.errors.LockNotAvailable:
            return _failure("IDEMPOTENCY_IN_FLIGHT", "Checkout mutation is in flight.")

    def _load_run(self, connection: psycopg.Connection[Any]) -> tuple[Any, ...] | None:
        return connection.execute(
            """
            SELECT clock_at
            FROM experiment_runs
            WHERE run_id = %s AND actor_id = %s
            """,
            (self._run_id, self._context.actor_id),
        ).fetchone()

    def _existing(
        self,
        connection: psycopg.Connection[Any],
        key_hash: str,
        fingerprint: str,
        scenario_at: str,
    ) -> Success[Checkout] | Failure | None:
        row = connection.execute(
            """
            SELECT request_fingerprint, create_snapshot
            FROM checkout_sessions
            WHERE run_id = %s AND actor_id = %s AND idempotency_sha256 = %s
            FOR UPDATE
            """,
            (self._run_id, self._context.actor_id, key_hash),
        ).fetchone()
        if row is None:
            return None
        if row[0] != fingerprint:
            return _failure(
                "IDEMPOTENCY_CONFLICT",
                "The idempotency key was already used for different checkout content.",
            )
        checkout = Checkout.model_validate(row[1])
        self._record(connection, "checkout.prepare_replayed", scenario_at, checkout.id)
        return Success[Checkout](data=checkout)

    def _validate_offer(
        self, offer: Offer, payload: CheckoutPrepareInput, scenario_at: str
    ) -> Failure | None:
        if offer.revision != payload.expected_offer_revision:
            return _failure("OFFER_REVISION_MISMATCH", "Refresh the offer before checkout.")
        if offer.availability != "in_stock" or offer.available_quantity < payload.quantity:
            return _failure("OUT_OF_STOCK", "The requested quantity is not available.")
        if offer.delivery_context != payload.delivery_context:
            return _failure("INVALID_INPUT", "The delivery context is not supported.")
        if parse_timestamp(scenario_at) >= parse_timestamp(offer.expires_at):
            return _failure("OFFER_EXPIRED", "Refresh the offer before checkout.")
        return None

    def _expire_if_needed(
        self,
        connection: psycopg.Connection[Any],
        checkout: Checkout,
        scenario_at: str,
    ) -> Checkout:
        if checkout.status != "prepared" or parse_timestamp(scenario_at) < parse_timestamp(
            checkout.expires_at
        ):
            return checkout
        expired = Checkout.model_validate(
            {**checkout.model_dump(mode="json"), "status": "expired", "updated_at": scenario_at}
        )
        connection.execute(
            """
            UPDATE checkout_sessions
            SET status = %s, snapshot = %s, updated_at = %s
            WHERE run_id = %s AND checkout_id = %s
            """,
            (
                expired.status,
                Jsonb(expired.model_dump(mode="json")),
                expired.updated_at,
                self._run_id,
                expired.id,
            ),
        )
        return expired

    def _record(
        self,
        connection: psycopg.Connection[Any],
        event_type: str,
        scenario_at: str,
        checkout_id: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO run_events (run_id, event_type, producer, scenario_at, payload)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                self._run_id,
                event_type,
                "commerce_lab.checkout",
                scenario_at,
                Jsonb(
                    {
                        "request_id": self._context.request_id,
                        "actor_id": self._context.actor_id,
                        "received_at": self._context.received_at,
                        "checkout_id": checkout_id,
                    }
                ),
            ),
        )
