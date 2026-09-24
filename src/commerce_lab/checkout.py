import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

import psycopg
from jsonschema import ValidationError as SchemaValidationError
from psycopg.types.json import Jsonb

from commerce_lab.contracts import (
    Checkout,
    CheckoutCancelInput,
    CheckoutCompletionResult,
    CheckoutCompletionSnapshot,
    CheckoutGetInput,
    CheckoutPrepareInput,
    CheckoutUpdateInput,
    CommerceError,
    CommerceErrorCode,
    ExecutionContext,
    Failure,
    Offer,
    OrderRecord,
    Success,
    parse_timestamp,
)
from commerce_lab.contracts.primitives import StrictModel
from commerce_lab.db import database_url
from commerce_lab.payment_client import PaymentProviderError, confirm_payment
from commerce_lab.payment_sandbox import payment_capability_available, validate_instrument
from commerce_lab.settings import get_settings
from commerce_lab.webhook_delivery import enqueue_order_event, update_order_to_processing


class ReadinessState(StrictModel):
    buyer_complete: bool
    fulfillment_complete: bool
    fulfillment_selected: bool
    commerce_terms_valid: bool
    payment_capability_available: bool
    ready_for_payment: bool


def evaluate_readiness(checkout: Checkout, offer: Offer | None = None) -> ReadinessState:
    buyer_complete = checkout.buyer is not None and bool(checkout.buyer.email)
    fulfillment_complete = (
        checkout.fulfillment_details is not None
        and bool(checkout.fulfillment_details.name)
        and bool(checkout.fulfillment_details.email)
        and bool(checkout.fulfillment_details.phone_number)
        and checkout.fulfillment_details.address is not None
        and checkout.fulfillment_details.address.city == "Bogota"
        and checkout.fulfillment_details.address.state == "DC"
        and checkout.fulfillment_details.address.country == "CO"
        and checkout.fulfillment_details.address.postal_code == "110111"
    )
    fulfillment_selected = (
        checkout.selected_fulfillment_option is not None
        and checkout.selected_fulfillment_option.option_id == f"ship_{checkout.id}"
    )
    commerce_terms_valid = checkout.status in {"prepared", "ready_for_payment"} and (
        offer is None or (offer.availability == "in_stock" and offer.available_quantity >= 1)
    )
    capability_available = payment_capability_available()
    ready_for_payment = (
        buyer_complete
        and fulfillment_complete
        and fulfillment_selected
        and commerce_terms_valid
        and capability_available
    )
    return ReadinessState(
        buyer_complete=buyer_complete,
        fulfillment_complete=fulfillment_complete,
        fulfillment_selected=fulfillment_selected,
        commerce_terms_valid=commerce_terms_valid,
        payment_capability_available=capability_available,
        ready_for_payment=ready_for_payment,
    )


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _as_timestamp(value: Any) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _failure(code: CommerceErrorCode, message: str) -> Failure:
    return Failure(error=CommerceError(code=code, message=message))


class CheckoutService:
    """Persistent, episode-scoped checkout lifecycle and synthetic completion."""

    def __init__(self, context: ExecutionContext) -> None:
        self._context = context
        self._run_id = UUID(context.run_id)
        self.last_completion_replayed = False

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
                buyer=None,
                fulfillment_details=None,
                selected_fulfillment_option=None,
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
        content: dict[str, Any] = {}
        if payload.buyer is not None:
            content["buyer"] = payload.buyer.model_dump(mode="json")
        if payload.fulfillment_details is not None:
            content["fulfillment_details"] = payload.fulfillment_details.model_dump(mode="json")
        if payload.selected_fulfillment_option is not None:
            content["selected_fulfillment_option"] = payload.selected_fulfillment_option.model_dump(
                mode="json"
            )
        return self._mutate(
            checkout_id=payload.checkout_id,
            operation="update",
            idempotency_key=payload.idempotency_key,
            content=content,
            update_payload=payload,
        )

    def cancel(self, raw: object) -> Success[Checkout] | Failure:
        payload = CheckoutCancelInput.model_validate(raw)
        return self._mutate(
            checkout_id=payload.checkout_id,
            operation="cancel",
            idempotency_key=payload.idempotency_key,
            content={} if payload.reason_code is None else {"reason_code": payload.reason_code},
        )

    def complete(
        self,
        checkout_id: str,
        payment_data: dict[str, Any],
        idempotency_key: str,
        *,
        expected_revision: int | None = None,
    ) -> Success[CheckoutCompletionResult] | Failure:
        self.last_completion_replayed = False
        fingerprint = _sha256(_canonical({"payment_data": payment_data}))
        key_hash = _sha256(idempotency_key)
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
                    SELECT request_fingerprint, result_snapshot
                    FROM checkout_completion_attempts
                    WHERE run_id = %s AND actor_id = %s AND checkout_id = %s
                      AND idempotency_sha256 = %s
                    """,
                    (self._run_id, self._context.actor_id, checkout_id, key_hash),
                ).fetchone()
                if replay is not None:
                    if replay[0] != fingerprint:
                        return _failure(
                            "IDEMPOTENCY_CONFLICT",
                            "The idempotency key was used with different content.",
                        )
                    return self._completion_replay(replay[1], Checkout.model_validate(row[0]))

                checkout = self._expire_if_needed(
                    connection, Checkout.model_validate(row[0]), scenario_at
                )
                if expected_revision is not None and checkout.revision != expected_revision:
                    failure = _failure(
                        "CHECKOUT_TERMS_CHANGED", "Checkout changed after AP2 authorization."
                    )
                elif checkout.status == "expired":
                    failure = _failure("CHECKOUT_EXPIRED", "Checkout has expired.")
                elif checkout.status != "ready_for_payment":
                    failure = _failure(
                        "CHECKOUT_NOT_COMPLETABLE",
                        "Checkout is not ready for payment.",
                    )
                else:
                    failure = None
                if failure is not None:
                    self._store_completion_failure(
                        connection,
                        checkout_id,
                        key_hash,
                        fingerprint,
                        failure,
                        scenario_at,
                    )
                    return failure
                if (
                    checkout.buyer is None
                    or checkout.fulfillment_details is None
                    or checkout.selected_fulfillment_option is None
                ):
                    failure = _failure(
                        "CHECKOUT_NOT_COMPLETABLE",
                        "Checkout is missing required completion details.",
                    )
                    self._store_completion_failure(
                        connection,
                        checkout_id,
                        key_hash,
                        fingerprint,
                        failure,
                        scenario_at,
                    )
                    return failure

                offer_row = connection.execute(
                    """
                    SELECT revision, snapshot
                    FROM catalog_offers
                    WHERE run_id = %s AND offer_id = %s
                    FOR UPDATE
                    """,
                    (self._run_id, checkout.offer_id),
                ).fetchone()
                if offer_row is None:
                    failure = _failure("OFFER_NOT_FOUND", "Checkout offer is unavailable.")
                    self._store_completion_failure(
                        connection,
                        checkout_id,
                        key_hash,
                        fingerprint,
                        failure,
                        scenario_at,
                    )
                    return failure
                offer = Offer.model_validate(offer_row[1])
                if (
                    offer.pricing != checkout.pricing
                    or offer.delivery_context != checkout.delivery_context
                    or offer.delivery_days != checkout.delivery_days
                    or offer.expires_at != checkout.expires_at
                ):
                    failure = _failure(
                        "CHECKOUT_TERMS_CHANGED",
                        "Checkout terms changed before completion.",
                    )
                    self._store_completion_failure(
                        connection,
                        checkout_id,
                        key_hash,
                        fingerprint,
                        failure,
                        scenario_at,
                    )
                    return failure
                if (
                    offer.product_status != "active"
                    or offer.availability != "in_stock"
                    or offer.available_quantity < checkout.quantity
                ):
                    failure = _failure(
                        "OUT_OF_STOCK",
                        "The requested quantity is not available.",
                    )
                    self._store_completion_failure(
                        connection,
                        checkout_id,
                        key_hash,
                        fingerprint,
                        failure,
                        scenario_at,
                    )
                    return failure
                if not payment_capability_available():
                    return _failure(
                        "PROVIDER_UNAVAILABLE",
                        "The sandbox payment capability is unavailable.",
                    )
                if payment_data.get("handler_id") != "tesis_sandbox":
                    return _failure("INVALID_INPUT", "Unsupported payment handler.")
                try:
                    instrument = payment_data["instrument"]
                    validate_instrument(instrument)
                    token = instrument["credential"]["token"]
                except (KeyError, TypeError, SchemaValidationError):
                    return _failure("INVALID_INPUT", "Invalid sandbox payment instrument.")
                try:
                    outcome = confirm_payment(
                        token=token,
                        checkout_id=checkout_id,
                        amount=checkout.pricing.total_minor,
                        currency=checkout.pricing.currency,
                        idempotency_key=idempotency_key,
                    )
                except PaymentProviderError as error:
                    if error.code == "invalid_token":
                        return _failure("INVALID_INPUT", "Payment token is not valid for checkout.")
                    return _failure("PROVIDER_UNAVAILABLE", "Payment provider is unavailable.")
                if outcome == "declined":
                    failure = _failure("PAYMENT_DECLINED", "The sandbox payment was declined.")
                    self._store_completion_failure(
                        connection,
                        checkout_id,
                        key_hash,
                        fingerprint,
                        failure,
                        scenario_at,
                    )
                    self._record_sanitized(
                        connection,
                        "payment.declined",
                        scenario_at,
                        checkout_id,
                        {
                            "checkout_id": checkout_id,
                            "offer_id": offer.id,
                            "payment_handler_id": "tesis_sandbox",
                            "payment_outcome": "declined",
                        },
                    )
                    return failure

                order_id = f"ord_{uuid4().hex}"
                order = OrderRecord(
                    id=order_id,
                    checkout_session_id=checkout.id,
                    order_number=f"TST-{order_id[4:12].upper()}",
                    status="confirmed",
                    offer_id=offer.id,
                    product_id=offer.product_id,
                    title=offer.name,
                    quantity=checkout.quantity,
                    currency=checkout.pricing.currency,
                    unit_price=checkout.pricing.items_total_minor,
                    subtotal=checkout.pricing.items_total_minor,
                    shipping_total=checkout.pricing.shipping_total_minor,
                    total=checkout.pricing.total_minor,
                    fulfillment_option_id=checkout.selected_fulfillment_option.option_id,
                    created_at=scenario_at,
                    permalink_url=f"{get_settings().acp_api_base_url}/orders/{order_id}",
                )
                completed = Checkout.model_validate(
                    {
                        **checkout.model_dump(mode="json"),
                        "revision": checkout.revision + 1,
                        "status": "completed",
                        "updated_at": scenario_at,
                    }
                )
                updated_offer = Offer.model_validate(
                    {
                        **offer.model_dump(mode="json"),
                        "revision": offer.revision + 1,
                        "available_quantity": offer.available_quantity - checkout.quantity,
                        "availability": (
                            "in_stock"
                            if offer.available_quantity - checkout.quantity > 0
                            else "out_of_stock"
                        ),
                    }
                )
                snapshot = CheckoutCompletionSnapshot(
                    checkout=completed,
                    order=order,
                    offer=offer,
                )
                connection.execute(
                    """
                    UPDATE catalog_offers
                    SET revision = %s, snapshot = %s
                    WHERE run_id = %s AND offer_id = %s
                    """,
                    (
                        updated_offer.revision,
                        Jsonb(updated_offer.model_dump(mode="json")),
                        self._run_id,
                        offer.id,
                    ),
                )
                connection.execute(
                    """
                    UPDATE checkout_sessions
                    SET revision = %s, status = %s, snapshot = %s, updated_at = %s
                    WHERE run_id = %s AND actor_id = %s AND checkout_id = %s
                    """,
                    (
                        completed.revision,
                        completed.status,
                        Jsonb(completed.model_dump(mode="json")),
                        completed.updated_at,
                        self._run_id,
                        self._context.actor_id,
                        checkout_id,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO orders
                      (order_id, run_id, actor_id, checkout_id, snapshot, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        order.id,
                        self._run_id,
                        self._context.actor_id,
                        checkout_id,
                        Jsonb(order.model_dump(mode="json")),
                        order.created_at,
                    ),
                )
                enqueue_order_event(
                    connection,
                    run_id=str(self._run_id),
                    actor_id=self._context.actor_id,
                    scenario_at=scenario_at,
                    event_type="order_create",
                    order=order,
                )
                self._record_sanitized(
                    connection,
                    "payment.approved",
                    scenario_at,
                    checkout_id,
                    {
                        "checkout_id": checkout_id,
                        "order_id": order.id,
                        "offer_id": offer.id,
                        "quantity": checkout.quantity,
                        "currency": checkout.pricing.currency,
                        "total_minor": checkout.pricing.total_minor,
                        "payment_handler_id": "tesis_sandbox",
                        "payment_outcome": "approved",
                    },
                )
                self._record_sanitized(
                    connection,
                    "order_create",
                    scenario_at,
                    checkout_id,
                    {
                        "checkout_id": checkout_id,
                        "order_id": order.id,
                        "offer_id": offer.id,
                        "quantity": checkout.quantity,
                        "currency": checkout.pricing.currency,
                        "total_minor": checkout.pricing.total_minor,
                    },
                )
                connection.execute(
                    """
                    INSERT INTO checkout_completion_attempts
                      (run_id, actor_id, checkout_id, idempotency_sha256,
                       request_fingerprint, result_snapshot, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        self._run_id,
                        self._context.actor_id,
                        checkout_id,
                        key_hash,
                        fingerprint,
                        Jsonb(
                            {
                                "kind": "success",
                                "order": order.model_dump(mode="json"),
                                "offer": offer.model_dump(mode="json"),
                            }
                        ),
                        scenario_at,
                    ),
                )
                return Success[CheckoutCompletionResult](
                    data=CheckoutCompletionResult(snapshot=snapshot)
                )
        except psycopg.errors.LockNotAvailable:
            return _failure("IDEMPOTENCY_IN_FLIGHT", "Checkout completion is in flight.")

    def update_order_status(self, order_id: str) -> Success[OrderRecord] | Failure:
        try:
            with psycopg.connect(database_url()) as connection, connection.transaction():
                run = self._load_run(connection)
                if run is None:
                    return _failure("FORBIDDEN", "Execution context does not own the episode.")
                changed = update_order_to_processing(
                    connection,
                    run_id=str(self._run_id),
                    actor_id=self._context.actor_id,
                    order_id=order_id,
                    scenario_at=_as_timestamp(run[0]),
                )
                return Success[OrderRecord](data=changed)
        except ValueError as error:
            return _failure("CHECKOUT_NOT_COMPLETABLE", str(error))

    def _completion_replay(
        self, snapshot: Any, checkout: Checkout
    ) -> Success[CheckoutCompletionResult] | Failure:
        self.last_completion_replayed = True
        if snapshot.get("kind") == "failure":
            return _failure(snapshot["code"], snapshot["message"])
        if checkout.status != "completed":
            return _failure(
                "CHECKOUT_NOT_COMPLETABLE",
                "Completed checkout snapshot is unavailable.",
            )
        return Success[CheckoutCompletionResult](
            data=CheckoutCompletionResult(
                snapshot=CheckoutCompletionSnapshot.model_validate(
                    {
                        "checkout": checkout,
                        "order": snapshot["order"],
                        "offer": snapshot["offer"],
                    }
                ),
                replayed=True,
            )
        )

    def _store_completion_failure(
        self,
        connection: psycopg.Connection[Any],
        checkout_id: str,
        key_hash: str,
        fingerprint: str,
        failure: Failure,
        scenario_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO checkout_completion_attempts
              (run_id, actor_id, checkout_id, idempotency_sha256,
               request_fingerprint, result_snapshot, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                self._run_id,
                self._context.actor_id,
                checkout_id,
                key_hash,
                fingerprint,
                Jsonb(
                    {
                        "kind": "failure",
                        "code": failure.error.code,
                        "message": failure.error.message,
                    }
                ),
                scenario_at,
            ),
        )

    def _mutate(
        self,
        *,
        checkout_id: str,
        operation: str,
        idempotency_key: str,
        content: dict[str, Any],
        update_payload: CheckoutUpdateInput | None = None,
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
                if operation == "cancel" and checkout.status not in {
                    "prepared",
                    "ready_for_payment",
                    "expired",
                }:
                    return _failure("CHECKOUT_NOT_CANCELABLE", "Checkout cannot be canceled.")
                if operation == "update" and checkout.status not in {
                    "prepared",
                    "ready_for_payment",
                }:
                    if checkout.status == "expired":
                        return _failure("CHECKOUT_EXPIRED", "Checkout has expired.")
                    return _failure("CHECKOUT_NOT_EDITABLE", "Checkout cannot be updated.")

                if operation == "update":
                    if update_payload is None:
                        return _failure("INVALID_INPUT", "Update payload is missing.")

                    offer_row = connection.execute(
                        """
                        SELECT revision, snapshot
                        FROM catalog_offers
                        WHERE run_id = %s AND offer_id = %s
                        FOR SHARE
                        """,
                        (self._run_id, checkout.offer_id),
                    ).fetchone()
                    if offer_row is None:
                        return _failure("OFFER_NOT_FOUND", "Checkout offer is unavailable.")
                    offer = Offer.model_validate(offer_row[1])

                    if (
                        offer.availability != "in_stock"
                        or offer.available_quantity < checkout.quantity
                    ):
                        return _failure("OUT_OF_STOCK", "The requested quantity is not available.")
                    if parse_timestamp(scenario_at) >= parse_timestamp(offer.expires_at):
                        return _failure("OFFER_EXPIRED", "Offer has expired.")

                    if update_payload.selected_fulfillment_option is not None:
                        sel = update_payload.selected_fulfillment_option
                        if sel.option_id != f"ship_{checkout_id}" or sel.item_ids != [
                            f"li_{checkout_id}"
                        ]:
                            return _failure("INVALID_INPUT", "Fulfillment option is unavailable.")

                    new_buyer = (
                        update_payload.buyer if update_payload.buyer is not None else checkout.buyer
                    )
                    new_fulfillment = (
                        update_payload.fulfillment_details
                        if update_payload.fulfillment_details is not None
                        else checkout.fulfillment_details
                    )
                    new_selection = (
                        update_payload.selected_fulfillment_option
                        if update_payload.selected_fulfillment_option is not None
                        else checkout.selected_fulfillment_option
                    )

                    prev_readiness = evaluate_readiness(checkout, offer)

                    changed = Checkout.model_validate(
                        {
                            **checkout.model_dump(mode="json"),
                            "revision": checkout.revision + 1,
                            "offer_revision": offer.revision,
                            "pricing": offer.pricing.model_dump(mode="json"),
                            "delivery_days": offer.delivery_days,
                            "buyer": new_buyer.model_dump(mode="json") if new_buyer else None,
                            "fulfillment_details": (
                                new_fulfillment.model_dump(mode="json") if new_fulfillment else None
                            ),
                            "selected_fulfillment_option": (
                                new_selection.model_dump(mode="json") if new_selection else None
                            ),
                            "updated_at": scenario_at,
                        }
                    )

                    new_readiness = evaluate_readiness(changed, offer)
                    if new_readiness.ready_for_payment:
                        changed = Checkout.model_validate(
                            {
                                **changed.model_dump(mode="json"),
                                "status": "ready_for_payment",
                            }
                        )
                        new_readiness = evaluate_readiness(changed, offer)

                    connection.execute(
                        """
                        UPDATE checkout_sessions
                        SET revision = %s, offer_revision = %s, status = %s,
                            snapshot = %s, updated_at = %s
                        WHERE run_id = %s AND actor_id = %s AND checkout_id = %s

                        """,
                        (
                            changed.revision,
                            changed.offer_revision,
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

                    if update_payload.buyer is not None:
                        self._record_readiness_event(
                            connection,
                            "checkout.buyer_updated",
                            scenario_at,
                            checkout_id,
                            changed,
                            new_readiness,
                        )
                    if update_payload.fulfillment_details is not None:
                        self._record_readiness_event(
                            connection,
                            "checkout.fulfillment_updated",
                            scenario_at,
                            checkout_id,
                            changed,
                            new_readiness,
                        )
                    if (
                        prev_readiness.model_dump() != new_readiness.model_dump()
                        or checkout.status != changed.status
                    ):
                        self._record_readiness_event(
                            connection,
                            "checkout.ready_state_changed",
                            scenario_at,
                            checkout_id,
                            changed,
                            new_readiness,
                        )

                    return Success[Checkout](data=changed)

                changed = Checkout.model_validate(
                    {
                        **checkout.model_dump(mode="json"),
                        "revision": checkout.revision + 1,
                        "status": "canceled",
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
                    "checkout.canceled",
                    scenario_at,
                    checkout_id,
                )
                return Success[Checkout](data=changed)
        except psycopg.errors.LockNotAvailable:
            return _failure("IDEMPOTENCY_IN_FLIGHT", "Checkout mutation is in flight.")

    def _record_readiness_event(
        self,
        connection: psycopg.Connection[Any],
        event_type: str,
        scenario_at: str,
        checkout_id: str,
        checkout: Checkout,
        readiness: ReadinessState,
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
                        "buyer_present": checkout.buyer is not None,
                        "fulfillment_present": checkout.fulfillment_details is not None,
                        "fulfillment_selected": checkout.selected_fulfillment_option is not None,
                        "buyer_complete": readiness.buyer_complete,
                        "fulfillment_complete": readiness.fulfillment_complete,
                        "fulfillment_selected_flag": readiness.fulfillment_selected,
                        "commerce_terms_valid": readiness.commerce_terms_valid,
                        "payment_capability_available": readiness.payment_capability_available,
                        "ready_for_payment": readiness.ready_for_payment,
                    }
                ),
            ),
        )

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
        if checkout.status not in {"prepared", "ready_for_payment"} or parse_timestamp(
            scenario_at
        ) < parse_timestamp(checkout.expires_at):
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
        self._record_readiness_event(
            connection,
            "checkout.ready_state_changed",
            scenario_at,
            expired.id,
            expired,
            evaluate_readiness(expired),
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

    def _record_sanitized(
        self,
        connection: psycopg.Connection[Any],
        event_type: str,
        scenario_at: str,
        checkout_id: str,
        payload: dict[str, Any],
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
                        **payload,
                    }
                ),
            ),
        )
