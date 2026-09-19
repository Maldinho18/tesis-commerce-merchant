from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from commerce_lab.contracts.primitives import (
    IdempotencyKey,
    Identifier,
    MinorAmount,
    Revision,
    StrictModel,
    parse_timestamp,
    sum_minor_amounts,
)


class DeliveryContext(StrictModel):
    country: Literal["CO"]
    city: Literal["Bogota"]
    postal_code: Literal["110111"]


class Pricing(StrictModel):
    currency: Literal["usd"]
    items_total_minor: MinorAmount
    shipping_total_minor: MinorAmount
    total_minor: MinorAmount
    tax_included: Literal[True]

    @model_validator(mode="after")
    def validate_total(self) -> "Pricing":
        expected = sum_minor_amounts(self.items_total_minor, self.shipping_total_minor)
        if self.total_minor != expected:
            raise ValueError("Total must equal items plus shipping, with tax already included")
        return self


Category = Annotated[
    str, StringConstraints(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
]
Brand = Annotated[str, StringConstraints(min_length=1, max_length=100, strip_whitespace=True)]
Color = Annotated[str, StringConstraints(min_length=1, max_length=64, strip_whitespace=True)]
AttributeValue = Annotated[str, StringConstraints(min_length=1, max_length=200)] | int | bool


class Offer(StrictModel):
    id: Identifier
    product_id: Identifier
    product_status: Literal["active", "inactive"] = "active"
    sku: Identifier = Field(default_factory=lambda data: data["id"])
    merchant_id: Identifier
    revision: Revision
    category: Category
    name: Annotated[str, Field(min_length=1, max_length=200)]
    brand: Brand
    color: Color | None = None
    attributes: Annotated[dict[Identifier, AttributeValue], Field(max_length=32)] = Field(
        default_factory=dict
    )
    condition: Literal["new", "refurbished"]
    availability: Literal["in_stock", "out_of_stock"]
    available_quantity: Annotated[int, Field(strict=True, ge=0)]
    pricing: Pricing
    delivery_context: DeliveryContext
    delivery_days: Annotated[int, Field(strict=True, gt=0)]
    observed_at: str
    expires_at: str

    @model_validator(mode="after")
    def validate_offer(self) -> "Offer":
        observed = parse_timestamp(self.observed_at)
        expires = parse_timestamp(self.expires_at)
        if expires <= observed:
            raise ValueError("Offer must expire after observation")
        if (self.availability == "in_stock") != (self.available_quantity > 0):
            raise ValueError("Availability and quantity disagree")
        return self


class BuyerInfo(StrictModel):
    email: str
    first_name: str | None = None
    last_name: str | None = None


class AddressInfo(StrictModel):
    name: str
    line_one: str
    line_two: str | None = None
    city: Literal["Bogota"]
    state: Literal["DC"]
    country: Literal["CO"]
    postal_code: Literal["110111"]
    company: str | None = None


class FulfillmentDetailsInfo(StrictModel):
    name: str
    email: str
    phone_number: str
    address: AddressInfo


class SelectedFulfillmentOptionInfo(StrictModel):
    type: Literal["shipping"]
    option_id: Identifier
    item_ids: Annotated[list[Identifier], Field(min_length=1)]


class Checkout(StrictModel):
    id: Identifier
    revision: Revision
    status: Literal["prepared", "ready_for_payment", "completed", "expired", "canceled"]
    offer_id: Identifier
    offer_revision: Revision
    quantity: Literal[1]
    pricing: Pricing
    delivery_context: DeliveryContext
    delivery_days: Annotated[int, Field(strict=True, gt=0)]
    buyer: BuyerInfo | None = None
    fulfillment_details: FulfillmentDetailsInfo | None = None
    selected_fulfillment_option: SelectedFulfillmentOptionInfo | None = None
    created_at: str
    updated_at: str
    expires_at: str

    @model_validator(mode="after")
    def validate_checkout(self) -> "Checkout":
        created = parse_timestamp(self.created_at)
        if parse_timestamp(self.updated_at) < created:
            raise ValueError("Update cannot precede creation")
        if parse_timestamp(self.expires_at) <= created:
            raise ValueError("Checkout must expire after creation")
        return self


type CommerceErrorCode = Literal[
    "INVALID_INPUT",
    "OFFER_NOT_FOUND",
    "OUT_OF_STOCK",
    "OFFER_EXPIRED",
    "OFFER_REVISION_MISMATCH",
    "CHECKOUT_NOT_FOUND",
    "CHECKOUT_EXPIRED",
    "CHECKOUT_NOT_EDITABLE",
    "CHECKOUT_NOT_CANCELABLE",
    "RUN_NOT_FOUND",
    "FORBIDDEN",
    "SESSION_INVALID",
    "IDEMPOTENCY_IN_FLIGHT",
    "IDEMPOTENCY_CONFLICT",
    "PROVIDER_UNAVAILABLE",
    "PAYMENT_DECLINED",
    "CHECKOUT_TERMS_CHANGED",
    "CHECKOUT_NOT_COMPLETABLE",
]


class CommerceError(StrictModel):
    code: CommerceErrorCode
    message: Annotated[str, Field(min_length=1, max_length=500)]


class Success[T](StrictModel):
    ok: Literal[True] = True
    data: T


class Failure(StrictModel):
    ok: Literal[False] = False
    error: CommerceError


class CatalogSearchInput(StrictModel):
    category: Category
    brand: Brand | None = None
    condition: Literal["new", "refurbished"] | None = None
    color: Color | None = None
    offset: Annotated[int, Field(strict=True, ge=0)] = 0
    limit: Annotated[int, Field(strict=True, ge=1, le=20)] = 20


class CatalogSearchData(StrictModel):
    offers: Annotated[list[Offer], Field(max_length=20)]
    next_offset: Annotated[int, Field(strict=True, ge=0)] | None


class OfferGetInput(StrictModel):
    offer_id: Identifier
    delivery_context: DeliveryContext


class CheckoutPrepareInput(StrictModel):
    offer_id: Identifier
    expected_offer_revision: Revision
    quantity: Literal[1]
    delivery_context: DeliveryContext
    idempotency_key: IdempotencyKey


class CheckoutGetInput(StrictModel):
    checkout_id: Identifier


class CheckoutUpdateInput(StrictModel):
    checkout_id: Identifier
    idempotency_key: IdempotencyKey
    buyer: BuyerInfo | None = None
    fulfillment_details: FulfillmentDetailsInfo | None = None
    selected_fulfillment_option: SelectedFulfillmentOptionInfo | None = None


class CheckoutCancelInput(StrictModel):
    checkout_id: Identifier
    idempotency_key: IdempotencyKey
    reason_code: str | None = None


class OrderRecord(StrictModel):
    id: Identifier
    checkout_session_id: Identifier
    order_number: Identifier
    status: Literal["confirmed"]
    offer_id: Identifier
    product_id: Identifier
    title: str
    quantity: Literal[1]
    currency: Literal["usd"]
    unit_price: int
    subtotal: int
    shipping_total: int
    total: int
    fulfillment_option_id: Identifier
    created_at: str
    permalink_url: str


class CheckoutCompletionSnapshot(StrictModel):
    checkout: Checkout
    order: OrderRecord
    offer: Offer


class CheckoutCompletionResult(StrictModel):
    snapshot: CheckoutCompletionSnapshot
    replayed: bool = False
