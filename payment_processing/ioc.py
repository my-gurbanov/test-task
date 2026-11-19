import typing

import httpx
import that_depends
from faststream import rabbit
from that_depends import providers

import payment_processing.database.repositories as database_repositories
from payment_processing.database import connection
from payment_processing.external.payment_gateway import PaymentGatewayClient
from payment_processing.external.webhooks import WebhookClient
from payment_processing.settings import settings
from payment_processing.use_cases import payments
from payment_processing.use_cases.outbox import PublishOutboxUseCase


async def create_webhook_http_client() -> typing.AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        timeout=settings.webhook_timeout,
        follow_redirects=False,
        trust_env=False,
    ) as webhook_http_client:
        yield webhook_http_client


@typing.final
class IOCContainer(that_depends.BaseContainer):
    database_engine = providers.Resource(connection.create_database_engine)
    sessionmaker = providers.Singleton(connection.create_sessionmaker, database_engine=database_engine.cast)
    payment_repository = providers.Factory(database_repositories.PaymentRepository, sessionmaker=sessionmaker.cast)
    outbox_repository = providers.Factory(database_repositories.OutboxRepository, sessionmaker=sessionmaker.cast)
    create_payment_use_case = providers.Factory(
        payments.CreatePaymentUseCase,
        payment_repository=payment_repository.cast,
    )
    fetch_payment_use_case = providers.Factory(payments.FetchPaymentUseCase, payment_repository=payment_repository.cast)

    payment_gateway_client = providers.Singleton(PaymentGatewayClient)
    webhook_http_client = providers.Resource(create_webhook_http_client)
    webhook_client = providers.Factory(WebhookClient, client=webhook_http_client.cast)
    process_payment_use_case = providers.Factory(
        payments.ProcessPaymentUseCase,
        fetch_payment_use_case=fetch_payment_use_case.cast,
        payment_repository=payment_repository.cast,
        payment_gateway_client=payment_gateway_client.cast,
        webhook_client=typing.cast("WebhookClient", webhook_client.cast),
    )

    rabbit_broker = providers.Singleton(
        rabbit.RabbitBroker,
        settings.rabbitmq_url.get_secret_value(),
        timeout=settings.rabbitmq_connect_timeout,
        reconnect_interval=settings.rabbitmq_reconnect_interval,
        default_channel=rabbit.Channel(prefetch_count=1, publisher_confirms=True, on_return_raises=True),
    )
    publish_outbox_use_case = providers.Factory(
        PublishOutboxUseCase,
        outbox_repository=outbox_repository.cast,
        rabbit_broker=rabbit_broker.cast,
    )
