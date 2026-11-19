import typing

import httpx
import pytest
from faststream import rabbit

import payment_processing.api.application as api_application
import payment_processing.workers.application as worker_application
from payment_processing.settings import settings


PAYMENTS_PATH: typing.Final = "/api/v1/payments"


@pytest.fixture
async def api_client() -> typing.AsyncIterator[httpx.AsyncClient]:
    application: typing.Final = api_application.build_application()
    async with (
        application.router.lifespan_context(application),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://test",
            headers={"X-API-Key": settings.payment_api_key.get_secret_value()},
        ) as payment_client,
    ):
        yield payment_client


@pytest.fixture
async def payment_broker() -> typing.AsyncIterator[rabbit.RabbitBroker]:
    rabbit_broker: typing.Final = rabbit.RabbitBroker()
    worker_application.build_consumer_application(rabbit_broker)
    async with rabbit.TestRabbitBroker(rabbit_broker) as test_broker:
        yield test_broker
