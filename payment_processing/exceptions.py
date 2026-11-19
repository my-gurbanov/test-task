import typing


class PaymentProcessingError(Exception):
    pass


@typing.final
class IdempotencyConflictError(PaymentProcessingError):
    pass


@typing.final
class PaymentNotFoundError(PaymentProcessingError):
    pass


@typing.final
class WebhookDeliveryError(PaymentProcessingError):
    pass


@typing.final
class WebhookAttemptsExhaustedError(PaymentProcessingError):
    pass
