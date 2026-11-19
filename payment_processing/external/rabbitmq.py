import typing

from faststream import rabbit

from payment_processing.settings import settings


DEAD_LETTER_EXCHANGE: typing.Final = rabbit.RabbitExchange(settings.rabbitmq_dead_letter_exchange)
DEAD_LETTER_QUEUE: typing.Final = rabbit.RabbitQueue(settings.rabbitmq_dead_letter_queue, rabbit.QueueType.QUORUM)
PAYMENT_QUEUE: typing.Final = rabbit.RabbitQueue(
    settings.rabbitmq_payment_queue,
    rabbit.QueueType.QUORUM,
    arguments={
        "x-single-active-consumer": True,
        "x-dead-letter-exchange": DEAD_LETTER_EXCHANGE.name,
        "x-dead-letter-routing-key": DEAD_LETTER_QUEUE.name,
        "x-dead-letter-strategy": "at-least-once",
        "x-overflow": "reject-publish",
    },
)
