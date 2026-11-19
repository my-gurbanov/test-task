import typing

from polyfactory.factories.typed_dict_factory import TypedDictFactory

from payment_processing.domain import Currency


@typing.final
class PaymentPayload(typing.TypedDict):
    amount: str  # noqa: COP004
    currency: Currency
    description: str
    webhook_url: str


@typing.final
class PaymentPayloadFactory(TypedDictFactory[PaymentPayload]):
    amount = "19.50"  # noqa: COP004
    webhook_url = "https://webhooks.example.com/payments"
