import json
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

import psycopg
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as SchemaValidationError
from pydantic import Field
from referencing import Registry, Resource

from commerce_lab.checkout import CheckoutService
from commerce_lab.contracts import (
    ACP_VERSION,
    Checkout,
    ExecutionContext,
    Failure,
    Identifier,
    Offer,
    parse_timestamp,
)
from commerce_lab.contracts.primitives import StrictModel
from commerce_lab.db import database_url

_BUNDLE = json.loads(
    (
        Path(__file__).resolve().parents[2] / "vendor/acp/2026-04-17/schema.agentic_checkout.json"
    ).read_text(encoding="utf-8")
)
_REGISTRY = Registry().with_resource(str(_BUNDLE["$id"]), Resource.from_contents(_BUNDLE))
_UPDATE_VALIDATOR = Draft202012Validator(
    {"$ref": f"{_BUNDLE['$id']}#/$defs/CheckoutSessionUpdateRequest"}, registry=_REGISTRY
)
_CANCEL_VALIDATOR = Draft202012Validator(
    {"$ref": f"{_BUNDLE['$id']}#/$defs/CancelSessionRequest"}, registry=_REGISTRY
)
_CHECKOUT_VALIDATOR = Draft202012Validator(
    {"$ref": f"{_BUNDLE['$id']}#/$defs/CheckoutSession"}, registry=_REGISTRY
)


class ACPItemRequest(StrictModel):
    id: Identifier


class ACPPaymentCapabilities(StrictModel):
    handlers: Annotated[list[dict[str, Any]], Field(max_length=0)]


class ACPCapabilities(StrictModel):
    payment: ACPPaymentCapabilities


class ACPCheckoutCreateRequest(StrictModel):
    line_items: Annotated[list[ACPItemRequest], Field(min_length=1, max_length=1)]
    currency: Literal["usd"]
    capabilities: ACPCapabilities


class ACPSelectedFulfillmentOption(StrictModel):
    type: Literal["shipping"]
    option_id: Identifier
    item_ids: Annotated[list[Identifier], Field(min_length=1, max_length=1)]


class ACPCheckoutUpdateRequest(StrictModel):
    selected_fulfillment_options: Annotated[
        list[ACPSelectedFulfillmentOption], Field(min_length=1, max_length=1)
    ]


class ACPCheckoutAdapter:
    """Narrow ACP 2026-04-17 bridge over the internal checkout contract."""

    def __init__(self, context: ExecutionContext) -> None:
        self._context = context
        self._run_id = UUID(context.run_id)
        self._checkout = CheckoutService(context)

    def create(
        self, request: ACPCheckoutCreateRequest, idempotency_key: str
    ) -> dict[str, Any] | Failure:
        offer = self._offer(request.line_items[0].id)
        if offer is None:
            return Failure.model_validate(
                {
                    "error": {
                        "code": "OFFER_NOT_FOUND",
                        "message": "The offer does not exist in this episode.",
                    }
                }
            )
        result = self._checkout.prepare(
            {
                "offer_id": offer.id,
                "expected_offer_revision": offer.revision,
                "quantity": 1,
                "delivery_context": offer.delivery_context.model_dump(mode="json"),
                "idempotency_key": idempotency_key,
            }
        )
        if isinstance(result, Failure):
            return result
        return self._response(result.data, offer)

    def get(self, checkout_id: str) -> dict[str, Any] | Failure:
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
        return self._response(result.data, offer)

    def update(
        self, checkout_id: str, request: ACPCheckoutUpdateRequest, idempotency_key: str
    ) -> dict[str, Any] | Failure:
        _UPDATE_VALIDATOR.validate(request.model_dump(mode="json"))
        selected = request.selected_fulfillment_options[0]
        if selected.item_ids != [f"li_{checkout_id}"]:
            return Failure.model_validate(
                {"error": {"code": "INVALID_INPUT", "message": "Invalid checkout line selection."}}
            )
        result = self._checkout.update(
            {
                "checkout_id": checkout_id,
                "selected_fulfillment_option_id": selected.option_id,
                "idempotency_key": idempotency_key,
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

    def _offer(self, offer_id: str) -> Offer | None:
        with psycopg.connect(database_url()) as connection, connection.transaction():
            row = connection.execute(
                """
                SELECT offer.snapshot
                FROM catalog_offers AS offer
                JOIN experiment_runs AS run ON run.run_id = offer.run_id
                WHERE offer.run_id = %s AND run.actor_id = %s AND offer.offer_id = %s
                """,
                (self._run_id, self._context.actor_id, offer_id),
            ).fetchone()
        return None if row is None else Offer.model_validate(row[0])

    def _response(self, checkout: Checkout, offer: Offer) -> dict[str, Any]:
        line_item_id = f"li_{checkout.id}"
        fulfillment_id = f"ship_{checkout.id}"
        delivery_at = parse_timestamp(checkout.created_at) + timedelta(days=checkout.delivery_days)
        delivery_timestamp = delivery_at.isoformat().replace("+00:00", "Z")
        acp_status = "not_ready_for_payment" if checkout.status == "prepared" else checkout.status
        response = {
            "id": checkout.id,
            "protocol": {"version": ACP_VERSION},
            "status": acp_status,
            "currency": "usd",
            "capabilities": {"payment": {"handlers": []}},
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
            "selected_fulfillment_options": [
                {
                    "type": "shipping",
                    "option_id": fulfillment_id,
                    "item_ids": [line_item_id],
                }
            ],
            "messages": [],
            "links": [],
            "created_at": checkout.created_at,
            "updated_at": checkout.updated_at,
            "expires_at": checkout.expires_at,
        }
        _CHECKOUT_VALIDATOR.validate(response)
        return response
