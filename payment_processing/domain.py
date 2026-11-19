import decimal
import enum
import typing

import pydantic


@typing.final
class Currency(enum.StrEnum):
    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"


@typing.final
class PaymentStatus(enum.StrEnum):
    PENDING = enum.auto()
    SUCCEEDED = enum.auto()
    FAILED = enum.auto()


@typing.final
class PaymentRequest(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    amount: typing.Annotated[decimal.Decimal, pydantic.Field(gt=0, max_digits=18, decimal_places=2)]
    currency: Currency
    description: typing.Annotated[str, pydantic.Field(min_length=1, max_length=1000)]
    metadata: dict[str, pydantic.JsonValue] = pydantic.Field(default_factory=dict)
    webhook_url: pydantic.HttpUrl
