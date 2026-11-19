import typing

import faststream
import structlog
from faststream import rabbit
from faststream.exceptions import RejectMessage

from payment_processing.external.webhooks import WebhookDeliveryError
from payment_processing.ioc import IOCContainer
from payment_processing.settings import settings
from payment_processing.use_cases.outbox import PaymentEvent
from payment_processing.use_cases.payments import PaymentNotFoundError


logger: typing.Final = structlog.get_logger(__name__)  # noqa: COP005
PAYMENT_WORKER_ROUTER: typing.Final = rabbit.RabbitRouter()
PAYMENT_QUEUE: typing.Final = rabbit.RabbitQueue(
    settings.rabbitmq_payment_queue,
    rabbit.QueueType.QUORUM,
    arguments={
        "x-single-active-consumer": True,
        "x-dead-letter-exchange": settings.rabbitmq_dead_letter_exchange,
        "x-dead-letter-routing-key": settings.rabbitmq_dead_letter_queue,
        "x-dead-letter-strategy": "at-least-once",
        "x-overflow": "reject-publish",
    },
)


@PAYMENT_WORKER_ROUTER.subscriber(PAYMENT_QUEUE, ack_policy=faststream.AckPolicy.REJECT_ON_ERROR)
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
