import hashlib
import json
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

import psycopg
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema import ValidationError as SchemaValidationError
from psycopg.types.json import Jsonb
from pydantic import Field
from pydantic import ValidationError as ModelValidationError
from referencing import Registry, Resource

from commerce_lab.checkout import CheckoutService, evaluate_readiness
from commerce_lab.checkout_creation import lock_creation
from commerce_lab.contracts import (
    ACP_VERSION,
    BuyerInfo,
    Checkout,
    ExecutionContext,
    Failure,
    FulfillmentDetailsInfo,
    Identifier,
    Offer,
    SelectedFulfillmentOptionInfo,
    parse_timestamp,
)
from commerce_lab.contracts.primitives import StrictModel
from commerce_lab.db import database_url
from commerce_lab.order_projection import order_to_acp
from commerce_lab.payment_sandbox import checkout_payment_capabilities, validate_instrument

_BUNDLE = json.loads(
    (
        Path(__file__).resolve().parents[2] / "vendor/acp/2026-04-17/schema.agentic_checkout.json"
    ).read_text(encoding="utf-8")
)
_REGISTRY = Registry().with_resource(str(_BUNDLE["$id"]), Resource.from_contents(_BUNDLE))
_CHECKER = FormatChecker()
_UPDATE_VALIDATOR = Draft202012Validator(
    {"$ref": f"{_BUNDLE['$id']}#/$defs/CheckoutSessionUpdateRequest"},
    registry=_REGISTRY,
    format_checker=_CHECKER,
)
_CANCEL_VALIDATOR = Draft202012Validator(
    {"$ref": f"{_BUNDLE['$id']}#/$defs/CancelSessionRequest"},
    registry=_REGISTRY,
    format_checker=_CHECKER,
)
_CHECKOUT_VALIDATOR = Draft202012Validator(
    {"$ref": f"{_BUNDLE['$id']}#/$defs/CheckoutSession"},
    registry=_REGISTRY,
    format_checker=_CHECKER,
)
_COMPLETE_VALIDATOR = Draft202012Validator(
    {"$ref": f"{_BUNDLE['$id']}#/$defs/CheckoutSessionCompleteRequest"},
    registry=_REGISTRY,
    format_checker=_CHECKER,
)
_ORDER_RESPONSE_VALIDATOR = Draft202012Validator(
    {"$ref": f"{_BUNDLE['$id']}#/$defs/CheckoutSessionWithOrder"},
    registry=_REGISTRY,
    format_checker=_CHECKER,
)


class ACPItemRequest(StrictModel):
    id: Identifier


class ACPPaymentCapabilities(StrictModel):
    handlers: Annotated[list[dict[str, Any]], Field(max_length=0)]


class ACPCapabilities(StrictModel):
    payment: ACPPaymentCapabilities = Field(
        default_factory=lambda: ACPPaymentCapabilities(handlers=[])
    )


class ACPCheckoutCreateRequest(StrictModel):
    line_items: Annotated[list[ACPItemRequest], Field(min_length=1, max_length=1)]
    currency: Literal["cop"]
    capabilities: ACPCapabilities


class ACPSelectedFulfillmentOption(StrictModel):
    type: Literal["shipping"]
    option_id: Identifier
    item_ids: Annotated[list[Identifier], Field(min_length=1, max_length=1)]


def creation_fingerprint(content: dict[str, Any]) -> str:
    envelope = {"api_version": ACP_VERSION, "profile": "merchant-p0-create/1", "request": content}
    canonical = json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(b"merchant-acp-create/v1\0" + canonical.encode()).hexdigest()


def _creation_unrecoverable() -> Failure:
    return Failure.model_validate(
        {
            "error": {
                "code": "CHECKOUT_CREATION_UNRECOVERABLE",
                "message": (
                    "Original ACP creation response unavailable; reconciliation is required."
                ),
            }
        }
    )


class ACPCheckoutAdapter:
    """Narrow ACP 2026-04-17 bridge over the internal checkout contract."""

    def __init__(self, context: ExecutionContext) -> None:
        self._context = context
        self._run_id = UUID(context.run_id)
        self._checkout = CheckoutService(context)

    @property
    def last_completion_replayed(self) -> bool:
        return self._checkout.last_completion_replayed

    def create(
        self, request: ACPCheckoutCreateRequest, idempotency_key: str
    ) -> dict[str, Any] | Failure:
        # Preserve field presence as well as values. JSON object order/whitespace
        # are immaterial; omitted defaults and explicit fields are different content.
        content = request.model_dump(mode="json", exclude_unset=True)
        request = ACPCheckoutCreateRequest.model_validate(content)
        if not 1 <= len(idempotency_key) <= 255:
            raise ValueError("Invalid creation key length")
        fingerprint = creation_fingerprint(content)
        key_hash = hashlib.sha256(idempotency_key.encode()).hexdigest()
        with psycopg.connect(database_url()) as connection, connection.transaction():
            owned = connection.execute(
                "SELECT 1 FROM experiment_runs WHERE run_id=%s AND actor_id=%s FOR KEY SHARE",
                (self._run_id, self._context.actor_id),
            ).fetchone()
            if owned is None:
                return Failure.model_validate(
                    {
                        "error": {
                            "code": "FORBIDDEN",
                            "message": "Execution context does not own the episode.",
                        }
                    }
                )
            lock_creation(connection, self._run_id, self._context.actor_id, key_hash)
            existing = self._existing_creation(connection, key_hash, fingerprint)
            if existing is not None:
                return existing
            offer = self._offer(request.line_items[0].id, connection=connection)
            if offer is None:
                return Failure.model_validate(
                    {
                        "error": {
                            "code": "OFFER_NOT_FOUND",
                            "message": "The offer does not exist in this episode.",
                        }
                    }
                )
            result = self._checkout.prepare_in_transaction(
                {
                    "offer_id": offer.id,
                    "expected_offer_revision": offer.revision,
                    "quantity": 1,
                    "delivery_context": offer.delivery_context.model_dump(mode="json"),
                    "idempotency_key": idempotency_key,
                },
                connection=connection,
            )
            if isinstance(result, Failure):
                return result
            response = self._response(result.data, offer)
            return self._save_creation(connection, key_hash, fingerprint, result.data.id, response)

    def _existing_creation(
        self, connection: psycopg.Connection[Any], key_hash: str, fingerprint: str
    ) -> dict[str, Any] | Failure | None:
        row = connection.execute(
            """SELECT checkout_id, acp_create_fingerprint, acp_create_response
               FROM checkout_sessions
               WHERE run_id=%s AND actor_id=%s AND idempotency_sha256=%s FOR UPDATE""",
            (self._run_id, self._context.actor_id, key_hash),
        ).fetchone()
        if row is None:
            return None
        if row[1] is None or row[2] is None:
            return _creation_unrecoverable()
        if row[1] != fingerprint:
            return Failure.model_validate(
                {
                    "error": {
                        "code": "IDEMPOTENCY_CONFLICT",
                        "message": "The creation key was used with different ACP request content.",
                    }
                }
            )
        try:
            _CHECKOUT_VALIDATOR.validate(row[2])
        except SchemaValidationError:
            return _creation_unrecoverable()
        if not isinstance(row[2], dict) or row[2].get("id") != row[0]:
            return _creation_unrecoverable()
        return row[2]

    def _save_creation(
        self,
        connection: psycopg.Connection[Any],
        key_hash: str,
        fingerprint: str,
        checkout_id: str,
        response: dict[str, Any],
    ) -> dict[str, Any]:
        row = connection.execute(
            """UPDATE checkout_sessions SET acp_create_fingerprint=%s, acp_create_response=%s
               WHERE run_id=%s AND actor_id=%s AND idempotency_sha256=%s AND checkout_id=%s
                 AND acp_create_fingerprint IS NULL AND acp_create_response IS NULL
               RETURNING acp_create_response""",
            (
                fingerprint,
                Jsonb(response),
                self._run_id,
                self._context.actor_id,
                key_hash,
                checkout_id,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("Creation response could not be persisted atomically")
        # First delivery and replay both use PostgreSQL's stored representation.
        return row[0]

    def get(self, checkout_id: str) -> dict[str, Any] | Failure:
        result = self.get_with_revision(checkout_id)
        return result if isinstance(result, Failure) else result[0]

    def get_with_revision(self, checkout_id: str) -> tuple[dict[str, Any], int] | Failure:
        result = self._checkout.get({"checkout_id": checkout_id})
        if isinstance(result, Failure):
            return result
        offer = self._offer(result.data.offer_id)
        if offer is None:
            return Failure.model_validate(
                {
                    "error": {
                        "code": "OFFER_NOT_FOUND",
                        "message": "The checkout offer no longer exists in this episode.",
                    }
                }
            )
        return self._response(result.data, offer), result.data.revision

    def update(
        self, checkout_id: str, request: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any] | Failure:
        try:
            _UPDATE_VALIDATOR.validate(request)
        except SchemaValidationError:
            return Failure.model_validate(
                {"error": {"code": "INVALID_INPUT", "message": "Invalid ACP update request."}}
            )

        unsupported_keys = {
            "line_items",
            "discounts",
            "coupons",
            "fulfillment_groups",
            "order_notes",
        }
        if any(key in request for key in unsupported_keys):
            return Failure.model_validate(
                {
                    "error": {
                        "code": "INVALID_INPUT",
                        "message": "Unsupported update fields for P0 profile.",
                    }
                }
            )

        buyer_info: BuyerInfo | None = None
        fulfillment_info: FulfillmentDetailsInfo | None = None
        selected_info: SelectedFulfillmentOptionInfo | None = None

        if "buyer" in request:
            try:
                buyer_info = BuyerInfo.model_validate(request["buyer"])
            except ModelValidationError:
                return Failure.model_validate(
                    {"error": {"code": "INVALID_INPUT", "message": "Invalid buyer details."}}
                )

        if "fulfillment_details" in request:
            try:
                fulfillment_info = FulfillmentDetailsInfo.model_validate(
                    request["fulfillment_details"]
                )
            except ModelValidationError:
                return Failure.model_validate(
                    {
                        "error": {
                            "code": "INVALID_INPUT",
                            "message": "The delivery context is not supported.",
                        }
                    }
                )

        if "selected_fulfillment_options" in request:
            options = request["selected_fulfillment_options"]
            if not isinstance(options, list) or len(options) != 1:
                return Failure.model_validate(
                    {
                        "error": {
                            "code": "INVALID_INPUT",
                            "message": "Invalid fulfillment option selection.",
                        }
                    }
                )
            try:
                selected_info = SelectedFulfillmentOptionInfo.model_validate(options[0])
            except ModelValidationError:
                return Failure.model_validate(
                    {
                        "error": {
                            "code": "INVALID_INPUT",
                            "message": "Invalid fulfillment option selection.",
                        }
                    }
                )

        result = self._checkout.update(
            {
                "checkout_id": checkout_id,
                "idempotency_key": idempotency_key,
                "buyer": buyer_info.model_dump(mode="json") if buyer_info else None,
                "fulfillment_details": (
                    fulfillment_info.model_dump(mode="json") if fulfillment_info else None
                ),
                "selected_fulfillment_option": (
                    selected_info.model_dump(mode="json") if selected_info else None
                ),
            }
        )
        if isinstance(result, Failure):
            return result
        offer = self._offer(result.data.offer_id)
        if offer is None:
            return Failure.model_validate(
                {"error": {"code": "OFFER_NOT_FOUND", "message": "Checkout offer is unavailable."}}
            )
        return self._response(result.data, offer)

    def cancel(
        self, checkout_id: str, request: dict[str, Any] | None, idempotency_key: str
    ) -> dict[str, Any] | Failure:
        body = request if request is not None else {}
        try:
            _CANCEL_VALIDATOR.validate(body)
        except SchemaValidationError:
            return Failure.model_validate(
                {"error": {"code": "INVALID_INPUT", "message": "Invalid cancellation details."}}
            )
        reason_code: str | None = None
        if body:
            trace = body.get("intent_trace")
            if (
                set(body) != {"intent_trace"}
                or not isinstance(trace, dict)
                or set(trace) != {"reason_code"}
            ):
                return Failure.model_validate(
                    {
                        "error": {
                            "code": "INVALID_INPUT",
                            "message": "Cancel details are unsupported.",
                        }
                    }
                )
            reason_code = trace["reason_code"]
        result = self._checkout.cancel(
            {
                "checkout_id": checkout_id,
                "idempotency_key": idempotency_key,
                "reason_code": reason_code,
            }
        )
        if isinstance(result, Failure):
            return result
        offer = self._offer(result.data.offer_id)
        if offer is None:
            return Failure.model_validate(
                {"error": {"code": "OFFER_NOT_FOUND", "message": "Checkout offer is unavailable."}}
            )
        return self._response(result.data, offer)

    def complete(
        self,
        checkout_id: str,
        request: Any,
        idempotency_key: str,
        *,
        expected_revision: int | None = None,
    ) -> dict[str, Any] | Failure:
        try:
            _COMPLETE_VALIDATOR.validate(request)
        except SchemaValidationError:
            return Failure.model_validate(
                {"error": {"code": "INVALID_INPUT", "message": "Invalid completion request."}}
            )
        if set(request) != {"payment_data"}:
            return Failure.model_validate(
                {
                    "error": {
                        "code": "INVALID_INPUT",
                        "message": "Only payment_data is supported for sandbox completion.",
                    }
                }
            )
        payment_data = request["payment_data"]
        if not isinstance(payment_data, dict) or set(payment_data) != {
            "handler_id",
            "instrument",
        }:
            return Failure.model_validate(
                {
                    "error": {
                        "code": "INVALID_INPUT",
                        "message": "Unsupported sandbox payment fields.",
                    }
                }
            )
        if payment_data.get("handler_id") != "tesis_sandbox":
            return Failure.model_validate(
                {"error": {"code": "INVALID_INPUT", "message": "Unsupported payment handler."}}
            )
        try:
            validate_instrument(payment_data["instrument"])
        except SchemaValidationError:
            return Failure.model_validate(
                {
                    "error": {
                        "code": "INVALID_INPUT",
                        "message": "Invalid sandbox payment instrument.",
                    }
                }
            )

        result = self._checkout.complete(
            checkout_id, payment_data, idempotency_key, expected_revision=expected_revision
        )
        if isinstance(result, Failure):
            return result
        return self._response(
            result.data.snapshot.checkout,
            result.data.snapshot.offer,
            order=self._order_response(result.data.snapshot.order),
            validator=_ORDER_RESPONSE_VALIDATOR,
        )

    def _offer(
        self, offer_id: str, *, connection: psycopg.Connection[Any] | None = None
    ) -> Offer | None:
        if connection is None:
            with psycopg.connect(database_url()) as owned, owned.transaction():
                return self._offer(offer_id, connection=owned)
        row = connection.execute(
            """
                SELECT offer.snapshot
                FROM catalog_offers AS offer
                JOIN experiment_runs AS run ON run.run_id = offer.run_id
                WHERE offer.run_id = %s AND run.actor_id = %s AND offer.offer_id = %s
                FOR SHARE OF offer
                """,
            (self._run_id, self._context.actor_id, offer_id),
        ).fetchone()
        return None if row is None else Offer.model_validate(row[0])

    def _response(
        self,
        checkout: Checkout,
        offer: Offer,
        *,
        order: dict[str, Any] | None = None,
        validator: Draft202012Validator | None = None,
    ) -> dict[str, Any]:
        line_item_id = f"li_{checkout.id}"
        fulfillment_id = f"ship_{checkout.id}"
        delivery_at = parse_timestamp(checkout.created_at) + timedelta(days=checkout.delivery_days)
        delivery_timestamp = delivery_at.isoformat().replace("+00:00", "Z")
        acp_status = "not_ready_for_payment" if checkout.status == "prepared" else checkout.status

        readiness = evaluate_readiness(checkout, offer)
        messages: list[dict[str, Any]] = []

        if not readiness.buyer_complete:
            messages.append(
                {
                    "type": "info",
                    "severity": "info",
                    "content_type": "plain",
                    "content": "Buyer information is missing.",
                }
            )
        if not readiness.fulfillment_complete:
            messages.append(
                {
                    "type": "info",
                    "severity": "info",
                    "content_type": "plain",
                    "content": "Fulfillment contact and address details are missing.",
                }
            )
        if not readiness.fulfillment_selected:
            messages.append(
                {
                    "type": "info",
                    "severity": "info",
                    "content_type": "plain",
                    "content": "Fulfillment option selection is missing.",
                }
            )
        if (
            readiness.buyer_complete
            and readiness.fulfillment_complete
            and readiness.fulfillment_selected
            and readiness.commerce_terms_valid
            and not readiness.payment_capability_available
        ):
            messages.append(
                {
                    "type": "info",
                    "severity": "info",
                    "content_type": "plain",
                    "content": (
                        "Buyer/fulfillment readiness is complete, but payment capability is not"
                        " implemented until the payment-sandbox ticket."
                    ),
                }
            )

        selected_fulfillment_options = (
            [checkout.selected_fulfillment_option.model_dump(mode="json")]
            if checkout.selected_fulfillment_option is not None
            else []
        )

        response: dict[str, Any] = {
            "id": checkout.id,
            "protocol": {"version": ACP_VERSION},
            "status": acp_status,
            "currency": "cop",
            "capabilities": checkout_payment_capabilities(),
            "line_items": [
                {
                    "id": line_item_id,
                    "item": {
                        "id": offer.id,
                        "name": offer.name,
                        "unit_amount": checkout.pricing.items_total_minor,
                    },
                    "quantity": checkout.quantity,
                    "totals": [
                        {
                            "type": "subtotal",
                            "display_text": "Producto con impuestos incluidos",
                            "amount": checkout.pricing.items_total_minor,
                        },
                        {
                            "type": "total",
                            "display_text": "Total del producto",
                            "amount": checkout.pricing.items_total_minor,
                        },
                    ],
                }
            ],
            "totals": [
                {
                    "type": "subtotal",
                    "display_text": "Producto con impuestos incluidos",
                    "amount": checkout.pricing.items_total_minor,
                },
                {
                    "type": "fulfillment",
                    "display_text": "Envio simulado",
                    "amount": checkout.pricing.shipping_total_minor,
                },
                {
                    "type": "total",
                    "display_text": "Total de la compra",
                    "amount": checkout.pricing.total_minor,
                },
            ],
            "fulfillment_options": [
                {
                    "type": "shipping",
                    "id": fulfillment_id,
                    "title": f"Envio simulado a {checkout.delivery_context.city}",
                    "earliest_delivery_time": delivery_timestamp,
                    "latest_delivery_time": delivery_timestamp,
                    "totals": [
                        {
                            "type": "total",
                            "display_text": "Total del envio",
                            "amount": checkout.pricing.shipping_total_minor,
                        }
                    ],
                }
            ],
            "selected_fulfillment_options": selected_fulfillment_options,
            "messages": messages,
            "links": [],
            "created_at": checkout.created_at,
            "updated_at": checkout.updated_at,
            "expires_at": checkout.expires_at,
        }
        if checkout.buyer is not None:
            response["buyer"] = checkout.buyer.model_dump(mode="json", exclude_none=True)
        if checkout.fulfillment_details is not None:
            response["fulfillment_details"] = checkout.fulfillment_details.model_dump(
                mode="json", exclude_none=True
            )

        if order is not None:
            response["order"] = order
        (validator or _CHECKOUT_VALIDATOR).validate(response)
        return response

    @staticmethod
    def _order_response(order: Any) -> dict[str, Any]:
        return order_to_acp(order)
