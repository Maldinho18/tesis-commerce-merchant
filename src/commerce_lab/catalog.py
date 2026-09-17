from copy import deepcopy
from typing import Protocol

from commerce_lab.contracts import (
    CatalogSearchData,
    CatalogSearchInput,
    CommerceError,
    Failure,
    Offer,
    OfferGetInput,
    ScenarioClock,
    Success,
    is_expired,
)


class CatalogPort(Protocol):
    def search(self, raw: object) -> Success[CatalogSearchData]: ...

    def get(self, raw: object) -> Success[Offer] | Failure: ...


class CatalogReader:
    """Frontera de lectura sobre un snapshot aislado del catálogo."""

    def __init__(self, source: list[Offer], clock: ScenarioClock) -> None:
        self._offers = sorted(deepcopy(source), key=lambda offer: offer.id)
        self._clock = clock

    def search(self, raw: object) -> Success[CatalogSearchData]:
        payload = CatalogSearchInput.model_validate(raw)
        matches = [
            offer
            for offer in self._offers
            if offer.category == payload.category
            and (payload.brand is None or offer.brand == payload.brand)
            and (payload.condition is None or offer.condition == payload.condition)
            and (payload.color is None or offer.color == payload.color)
        ]
        end = payload.offset + payload.limit
        data = CatalogSearchData(
            offers=deepcopy(matches[payload.offset : end]),
            next_offset=end if end < len(matches) else None,
        )
        return Success[CatalogSearchData](data=data)

    def get(self, raw: object) -> Success[Offer] | Failure:
        payload = OfferGetInput.model_validate(raw)
        offer = next((item for item in self._offers if item.id == payload.offer_id), None)
        if offer is None:
            return Failure(
                error=CommerceError(
                    code="OFFER_NOT_FOUND",
                    message="The offer does not exist in this scenario.",
                )
            )
        if payload.delivery_context != offer.delivery_context:
            return Failure(
                error=CommerceError(
                    code="INVALID_INPUT", message="The delivery context is not supported."
                )
            )
        if is_expired(offer.expires_at, self._clock):
            return Failure(
                error=CommerceError(
                    code="OFFER_EXPIRED",
                    message="Refresh the offer before preparing checkout.",
                )
            )
        return Success[Offer](data=offer.model_copy(deep=True))
