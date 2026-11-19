import asyncio
import dataclasses
import typing
import uuid

import backoff
import pydantic
import structlog
from aio_pika import exceptions
from faststream.rabbit import RabbitBroker

from payment_processing.database import connection
from payment_processing.database.repositories import OutboxRepository
from payment_processing.settings import settings


logger: typing.Final = structlog.get_logger(__name__)  # noqa: COP005


RABBITMQ_PUBLISH_ERRORS: typing.Final = (
    ConnectionError,
    TimeoutError,
    exceptions.ChannelClosed,
    exceptions.ChannelInvalidStateError,
    exceptions.DeliveryError,
)
OUTBOX_OPERATION_ERRORS: typing.Final = (*RABBITMQ_PUBLISH_ERRORS, *connection.DATABASE_OPERATION_ERRORS)


@typing.final
class PaymentEvent(pydantic.BaseModel):
    payment_id: uuid.UUID


@typing.final
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class PublishOutboxUseCase:
    outbox_repository: OutboxRepository
    rabbit_broker: RabbitBroker

    async def execute_use_case(self) -> None:
        while True:
            if not await self.publish_next_event():
                await asyncio.sleep(settings.outbox_poll_interval)

    @backoff.on_exception(
        backoff.expo,
        OUTBOX_OPERATION_ERRORS,
        factor=settings.outbox_retry_initial_delay,
        max_value=settings.outbox_retry_max_delay,
        logger=None,
    )
    async def publish_next_event(self) -> bool:
        try:
            async with self.outbox_repository.lock_next_event() as payment_id:
                if payment_id is None:
                    return False
                await self.rabbit_broker.publish(
                    PaymentEvent(payment_id=payment_id).model_dump(mode="json"),
                    queue=settings.rabbitmq_payment_queue,
                    message_id=str(payment_id),
                    mandatory=True,
                    persist=True,
                    timeout=settings.rabbitmq_publish_timeout,
                )
        except OUTBOX_OPERATION_ERRORS as publication_error:
            logger.warning("Outbox publication failed", error_type=type(publication_error).__name__)
            raise
        logger.info("Payment event published from outbox", payment_id=payment_id)
        return True
