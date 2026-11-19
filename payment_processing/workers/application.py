import asyncio
import contextlib
import signal
import typing

import structlog
from faststream import rabbit
from faststream.asgi import AsgiFastStream
from microbootstrap.bootstrappers.faststream import FastStreamBootstrapper
from microbootstrap.config.faststream import FastStreamConfig

from payment_processing.ioc import IOCContainer
from payment_processing.settings import settings
from payment_processing.workers.payments import PAYMENT_WORKER_ROUTER


logger: typing.Final = structlog.get_logger(__name__)  # noqa: COP005
DEAD_LETTER_QUEUE: typing.Final = rabbit.RabbitQueue(settings.rabbitmq_dead_letter_queue, rabbit.QueueType.QUORUM)
DEAD_LETTER_EXCHANGE: typing.Final = rabbit.RabbitExchange(settings.rabbitmq_dead_letter_exchange)


def build_consumer_application(rabbit_broker: rabbit.RabbitBroker) -> AsgiFastStream:
    rabbit_broker.include_router(PAYMENT_WORKER_ROUTER)
    return FastStreamBootstrapper(settings).configure_application(FastStreamConfig(broker=rabbit_broker)).bootstrap()


@contextlib.asynccontextmanager
async def run_consumer() -> typing.AsyncGenerator[None]:
    rabbit_broker: typing.Final = await IOCContainer.rabbit_broker.resolve()
    consumer_application: typing.Final = build_consumer_application(rabbit_broker)
    try:
        await rabbit_broker.connect()
        dead_letter_queue: typing.Final = await rabbit_broker.declare_queue(DEAD_LETTER_QUEUE)
        dead_letter_exchange: typing.Final = await rabbit_broker.declare_exchange(DEAD_LETTER_EXCHANGE)
        await dead_letter_queue.bind(dead_letter_exchange, routing_key=dead_letter_queue.name)
        await consumer_application.start()
        logger.info(
            "RabbitMQ payment topology ready",
            payment_queue=settings.rabbitmq_payment_queue,
            dead_letter_exchange=dead_letter_exchange.name,
            dead_letter_queue=dead_letter_queue.name,
        )
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


async def run_main() -> None:
    shutdown_event: typing.Final = asyncio.Event()
    event_loop: typing.Final = asyncio.get_running_loop()
    event_loop.add_signal_handler(signal.SIGINT, shutdown_event.set)
    event_loop.add_signal_handler(signal.SIGTERM, shutdown_event.set)
    try:
        async with run_consumer():
            await shutdown_event.wait()
    finally:
        await IOCContainer.tear_down()


if __name__ == "__main__":
    asyncio.run(run_main())
