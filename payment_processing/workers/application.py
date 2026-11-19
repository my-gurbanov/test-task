import asyncio
import contextlib
import typing

import structlog
from faststream.asgi import AsgiFastStream
from faststream.rabbit import RabbitBroker
from microbootstrap.bootstrappers.faststream import FastStreamBootstrapper
from microbootstrap.config.faststream import FastStreamConfig

from payment_processing.external import rabbitmq
from payment_processing.ioc import IOCContainer
from payment_processing.settings import settings
from payment_processing.workers.payments import PAYMENT_WORKER_ROUTER


logger: typing.Final = structlog.get_logger(__name__)  # noqa: COP005


def build_consumer_application(rabbit_broker: RabbitBroker) -> AsgiFastStream:
    rabbit_broker.include_router(PAYMENT_WORKER_ROUTER)
    return FastStreamBootstrapper(settings).configure_application(FastStreamConfig(broker=rabbit_broker)).bootstrap()


@contextlib.asynccontextmanager
async def run_consumer() -> typing.AsyncGenerator[None]:
    rabbit_broker: typing.Final = await IOCContainer.rabbit_broker.resolve()
    consumer_application: typing.Final = build_consumer_application(rabbit_broker)
    try:
        await rabbit_broker.connect()
        dead_letter_queue: typing.Final = await rabbit_broker.declare_queue(rabbitmq.DEAD_LETTER_QUEUE)
        dead_letter_exchange: typing.Final = await rabbit_broker.declare_exchange(rabbitmq.DEAD_LETTER_EXCHANGE)
        await dead_letter_queue.bind(dead_letter_exchange, routing_key=dead_letter_queue.name)
        await rabbit_broker.declare_queue(rabbitmq.PAYMENT_QUEUE)
        logger.info(
            "RabbitMQ payment topology ready",
            payment_queue=rabbitmq.PAYMENT_QUEUE.name,
            dead_letter_exchange=dead_letter_exchange.name,
            dead_letter_queue=dead_letter_queue.name,
        )
        await consumer_application.start()
        publish_outbox_use_case: typing.Final = await IOCContainer.publish_outbox_use_case.resolve()
        async with asyncio.TaskGroup() as worker_tasks:
            relay_task: typing.Final = worker_tasks.create_task(publish_outbox_use_case.execute_use_case())
            logger.info("Payment consumer and outbox relay started")
            try:
                yield
            finally:
                relay_task.cancel()
    finally:
        logger.info("Stopping payment consumer")
        await consumer_application.stop()
