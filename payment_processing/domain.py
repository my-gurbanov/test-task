import decimal
import enum
import typing

import pydantic


AMOUNT_ADAPTER: typing.Final = pydantic.TypeAdapter(
    typing.Annotated[decimal.Decimal, pydantic.Field(gt=0, max_digits=18, decimal_places=2)],
)
type PaymentText = typing.Annotated[str, pydantic.StringConstraints(pattern=r"^[^\x00]*$")]
type PaymentMetadataValue = (
    dict[PaymentText, PaymentMetadataValue] | list[PaymentMetadataValue] | PaymentText | bool | int | float | None
)


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

    amount: typing.Annotated[
        decimal.Decimal,
        pydantic.ValidateAs(pydantic.StrictStr, AMOUNT_ADAPTER.validate_python),
    ]
    currency: Currency
    description: typing.Annotated[PaymentText, pydantic.StringConstraints(min_length=1, max_length=1000)]
    metadata: dict[PaymentText, PaymentMetadataValue] = pydantic.Field(default_factory=dict)
    webhook_url: pydantic.HttpUrl
