import typing

import structlog
from faststream import AckPolicy
from faststream.exceptions import RejectMessage
from faststream.rabbit import RabbitRouter

from payment_processing.external import rabbitmq
from payment_processing.external.webhooks import WebhookDeliveryError
from payment_processing.ioc import IOCContainer
from payment_processing.use_cases.outbox import PaymentEvent
from payment_processing.use_cases.payments import PaymentNotFoundError


logger: typing.Final = structlog.get_logger(__name__)  # noqa: COP005
PAYMENT_WORKER_ROUTER: typing.Final = RabbitRouter()


@PAYMENT_WORKER_ROUTER.subscriber(rabbitmq.PAYMENT_QUEUE, ack_policy=AckPolicy.REJECT_ON_ERROR)
async def handle_payment_event(payment_event: PaymentEvent) -> None:
    try:
        await (await IOCContainer.process_payment_use_case.resolve()).execute_use_case(payment_event.payment_id)
    except PaymentNotFoundError:
        logger.warning("Payment event references an unknown payment", payment_id=payment_event.payment_id)
        raise RejectMessage from None
    except WebhookDeliveryError:
        # WebhookClient already logs each failed attempt.
        logger.error("Payment notification attempts exhausted", payment_id=payment_event.payment_id)  # noqa: TRY400
        raise RejectMessage from None
