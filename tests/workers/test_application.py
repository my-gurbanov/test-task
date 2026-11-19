import asyncio
import http
import json
import typing
import uuid
from unittest import mock

import httpx
import pytest
import respx
import sqlalchemy
from faststream import rabbit
from sqlalchemy.ext import asyncio as sqlalchemy_async

from payment_processing.database import connection, models
from payment_processing.ioc import IOCContainer
from payment_processing.settings import settings
from payment_processing.workers import application
from tests import conftest, factories


@pytest.fixture
async def isolated_outbox_database() -> typing.AsyncIterator[sqlalchemy_async.AsyncEngine]:
    schema_name: typing.Final = f"test_{uuid.uuid4().hex}"
    isolated_engine: typing.Final = sqlalchemy_async.create_async_engine(
        settings.database_url, execution_options={"schema_translate_map": {None: schema_name}}
    )
    try:
        async with isolated_engine.begin() as database_connection:
            await database_connection.execute(sqlalchemy.schema.CreateSchema(schema_name))
            await database_connection.run_sync(models.DatabaseBase.metadata.create_all)
        try:
            with IOCContainer.sessionmaker.override_context_sync(connection.create_sessionmaker(isolated_engine)):
                yield isolated_engine
        finally:
            async with isolated_engine.begin() as database_connection:
                await database_connection.execute(sqlalchemy.schema.DropSchema(schema_name, cascade=True))
    finally:
        await isolated_engine.dispose()


async def test_consumer_retries_and_delivers_outbox_event(
    *,
    api_client: httpx.AsyncClient,
    isolated_outbox_database: sqlalchemy_async.AsyncEngine,
    respx_mock: respx.MockRouter,
) -> None:
    payment_payload: typing.Final = factories.PaymentPayloadFactory.build()
    webhook_route: typing.Final = respx_mock.post(payment_payload["webhook_url"]).respond(http.HTTPStatus.NO_CONTENT)

    async with rabbit.TestRabbitBroker(rabbit.RabbitBroker(), connect_only=True) as payment_broker:
        with (
            IOCContainer.rabbit_broker.override_context_sync(payment_broker),
            mock.patch.object(
                payment_broker, "publish", wraps=payment_broker.publish, side_effect=[ConnectionError, mock.DEFAULT]
            ) as publish_event,
        ):
            async with asyncio.timeout(10), application.run_consumer():
                accepted_response: typing.Final = await api_client.post(
                    conftest.PAYMENTS_PATH,
                    headers={"Idempotency-Key": str(uuid.uuid4())},
                    json=payment_payload,
                )
                accepted_response.raise_for_status()
                payment_id: typing.Final = accepted_response.json()["payment_id"]
                publication: typing.Final = sqlalchemy.select(models.OutboxEvent.published_at).where(
                    models.OutboxEvent.payment_id == uuid.UUID(payment_id),
                )
                async with isolated_outbox_database.connect() as database_connection:
                    # The relay commits in a separate transaction after delivery.
                    while await database_connection.scalar(publication) is None:  # noqa: ASYNC110
                        await asyncio.sleep(0.01)

    assert accepted_response.status_code == http.HTTPStatus.ACCEPTED
    assert publish_event.await_count == 2
    assert webhook_route.call_count == 1
    assert json.loads(webhook_route.calls.last.request.content)["payment_id"] == payment_id
