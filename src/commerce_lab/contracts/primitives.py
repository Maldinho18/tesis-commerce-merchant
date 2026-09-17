import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

ACP_VERSION = "2026-04-17"
COP_MINOR_UNIT_EXPONENT = 2
MAX_SAFE_INTEGER = 9_007_199_254_740_991

Identifier = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]
IdempotencyKey = Annotated[str, StringConstraints(min_length=1, max_length=255)]
MinorAmount = Annotated[int, Field(strict=True, ge=0, le=MAX_SAFE_INTEGER)]
Revision = Annotated[int, Field(strict=True, gt=0, le=MAX_SAFE_INTEGER)]

_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not _TIMESTAMP.fullmatch(value):
        raise ValueError("Timestamp must be UTC ISO 8601 with second precision")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Money(StrictModel):
    currency: str = Field(pattern=r"^COP$")
    amount_minor: MinorAmount


def cop_from_decimal(pesos: str) -> Money:
    if not re.fullmatch(r"(0|[1-9]\d*)(\.\d{1,2})?", pesos):
        raise ValueError("COP requires nonnegative decimal text with at most two decimal places")
    try:
        minor = int(Decimal(pesos) * 100)
    except InvalidOperation as error:
        raise ValueError("Invalid COP amount") from error
    if minor > MAX_SAFE_INTEGER:
        raise ValueError("Amount exceeds safe integer range")
    return Money(currency="COP", amount_minor=minor)


def sum_minor_amounts(*amounts: int) -> int:
    total = 0
    for amount in amounts:
        if (
            isinstance(amount, bool)
            or not isinstance(amount, int)
            or not 0 <= amount <= MAX_SAFE_INTEGER
        ):
            raise ValueError("Minor amount must be a nonnegative safe integer")
        total += amount
        if total > MAX_SAFE_INTEGER:
            raise ValueError("Total exceeds safe integer range")
    return total


class ExecutionContext(StrictModel):
    """El backend crea este contexto después de autenticar; nunca es input de una tool."""

    actor_id: Identifier
    run_id: Identifier
    request_id: Identifier
    received_at: str

    @field_validator("received_at")
    @classmethod
    def validate_received_at(cls, value: str) -> str:
        parse_timestamp(value)
        return value


class ScenarioClock:
    """Reloj controlado por el escenario; nunca consulta el reloj de pared."""

    def __init__(self, initial: str) -> None:
        self._current = parse_timestamp(initial)

    def now(self) -> str:
        return self._current.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    def advance_seconds(self, seconds: int) -> None:
        if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds < 0:
            raise ValueError("Clock advance requires a nonnegative integer")
        try:
            self._current += timedelta(seconds=seconds)
        except OverflowError as error:
            raise ValueError("Clock advance is outside supported range") from error


def is_expired(expires_at: str, clock: ScenarioClock) -> bool:
    return parse_timestamp(clock.now()) >= parse_timestamp(expires_at)
