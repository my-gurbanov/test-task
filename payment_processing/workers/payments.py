import asyncio
import typing

import faststream.exceptions
import structlog
from faststream import rabbit

from payment_processing import exceptions
from payment_processing.database import connection
from payment_processing.ioc import IOCContainer
from payment_processing.settings import settings
from payment_processing.use_cases.outbox import PaymentEvent


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
        "x-delivery-limit": -1,
    },
)


@PAYMENT_WORKER_ROUTER.subscriber(PAYMENT_QUEUE, ack_policy=faststream.AckPolicy.REJECT_ON_ERROR)
async def handle_payment_event(payment_event: PaymentEvent) -> None:
    try:
        await (await IOCContainer.process_payment_use_case.resolve()).execute_use_case(payment_event.payment_id)
    except connection.DATABASE_OPERATION_ERRORS as database_error:
        logger.warning(
            "Payment processing deferred until database recovers",
            payment_id=payment_event.payment_id,
            error_type=type(database_error).__name__,
        )
        await asyncio.sleep(settings.database_redelivery_delay)
        raise faststream.exceptions.NackMessage from None
    except exceptions.PaymentProcessingError as processing_error:
        logger.error(  # noqa: TRY400
            "Payment event rejected",
            payment_id=payment_event.payment_id,
            error_type=type(processing_error).__name__,
        )
        raise faststream.exceptions.RejectMessage from None
