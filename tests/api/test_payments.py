import asyncio
import http
import typing
import uuid
from unittest import mock

import httpx
import pytest
import respx
from faststream import rabbit
from sqlalchemy import exc as sqlalchemy_exceptions
from sqlalchemy.ext import asyncio as sqlalchemy_async

from payment_processing.settings import settings
from tests import conftest, factories


@pytest.mark.parametrize("request_method", ["POST", "GET"])
async def test_payments_require_api_key(api_client: httpx.AsyncClient, request_method: str) -> None:
    request_path: typing.Final = (
        conftest.PAYMENTS_PATH if request_method == "POST" else f"{conftest.PAYMENTS_PATH}/{uuid.uuid4()}"
    )

    unauthenticated_response: typing.Final = await api_client.request(
        request_method, request_path, headers={"X-API-Key": "wrong"}
    )

    assert unauthenticated_response.status_code == http.HTTPStatus.UNAUTHORIZED


@pytest.mark.parametrize(
    ("invalid_fields", "supply_idempotency"),
    [
        pytest.param({"amount": "0.001"}, True, id="fractional-cent"),
        pytest.param({"amount": 100000000000000.02}, True, id="numeric-amount"),
        pytest.param({"currency": "GBP"}, True, id="unsupported-currency"),
        pytest.param({"webhook_url": "ftp://example.com"}, True, id="unsupported-webhook-scheme"),
        pytest.param({"metadata": {"entries": [{"reference": "\x00"}]}}, True, id="null-in-metadata"),
        pytest.param({}, False, id="missing-idempotency-key"),
    ],
)
async def test_create_payment_rejects_invalid_input(
    *,
    api_client: httpx.AsyncClient,
    invalid_fields: dict[str, object],
    supply_idempotency: bool,
) -> None:
    payment_payload: typing.Final = factories.PaymentPayloadFactory.build()
    payment_headers: typing.Final = {"Idempotency-Key": str(uuid.uuid4())} if supply_idempotency else {}

    validation_response: typing.Final = await api_client.post(
        conftest.PAYMENTS_PATH, headers=payment_headers, json=payment_payload | invalid_fields
    )

    assert validation_response.status_code == http.HTTPStatus.UNPROCESSABLE_CONTENT


async def test_create_payment_replays_original_acceptance(
    *,
    api_client: httpx.AsyncClient,
    payment_broker: rabbit.RabbitBroker,
    respx_mock: respx.MockRouter,
) -> None:
    payment_headers: typing.Final = {"Idempotency-Key": str(uuid.uuid4())}
    payment_payload: typing.Final = factories.PaymentPayloadFactory.build()
    equivalent_payload: typing.Final = payment_payload | {"amount": "19.5"}
    webhook_route: typing.Final = respx_mock.post(payment_payload["webhook_url"]).respond(http.HTTPStatus.NO_CONTENT)

    first_response, second_response = await asyncio.gather(
        api_client.post(conftest.PAYMENTS_PATH, headers=payment_headers, json=payment_payload),
        api_client.post(conftest.PAYMENTS_PATH, headers=payment_headers, json=equivalent_payload),
    )
    await payment_broker.publish(
        {"payment_id": first_response.json()["payment_id"]},
        queue=settings.rabbitmq_payment_queue,
    )
    replay_response: typing.Final = await api_client.post(
        conftest.PAYMENTS_PATH, headers=payment_headers, json=payment_payload
    )

    assert (
        first_response.status_code
        == second_response.status_code
        == replay_response.status_code
        == http.HTTPStatus.ACCEPTED
    )
    assert first_response.json() == second_response.json() == replay_response.json()
    assert first_response.json()["status"] == "pending"
    assert webhook_route.call_count == 1


async def test_create_payment_rejects_changed_request_for_existing_key(api_client: httpx.AsyncClient) -> None:
    payment_payload: typing.Final = factories.PaymentPayloadFactory.build()
    payment_headers: typing.Final = {"Idempotency-Key": str(uuid.uuid4())}
    accepted_response: typing.Final = await api_client.post(
        conftest.PAYMENTS_PATH, headers=payment_headers, json=payment_payload
    )
    accepted_response.raise_for_status()

    conflict_response: typing.Final = await api_client.post(
        conftest.PAYMENTS_PATH, headers=payment_headers, json=payment_payload | {"amount": "20.00"}
    )
    assert conflict_response.status_code == http.HTTPStatus.CONFLICT


async def test_fetch_payment_returns_not_found(api_client: httpx.AsyncClient) -> None:
    unknown_payment_path: typing.Final = f"{conftest.PAYMENTS_PATH}/{uuid.uuid4()}"

    missing_response: typing.Final = await api_client.get(unknown_payment_path)

    assert missing_response.status_code == http.HTTPStatus.NOT_FOUND


async def test_payment_api_recovers_from_database_errors(api_client: httpx.AsyncClient) -> None:
    payment_payload: typing.Final = factories.PaymentPayloadFactory.build()
    payment_headers: typing.Final = {"Idempotency-Key": str(uuid.uuid4())}
    database_error: typing.Final = sqlalchemy_exceptions.OperationalError(None, None, OSError())

    with mock.patch.object(
        sqlalchemy_async.AsyncSession,
        "scalar",
        autospec=True,
        wraps=sqlalchemy_async.AsyncSession.scalar,
        side_effect=[database_error, mock.DEFAULT],
    ) as insert_payment:
        accepted_response: typing.Final = await api_client.post(
            conftest.PAYMENTS_PATH, headers=payment_headers, json=payment_payload
        )
    accepted_response.raise_for_status()
    payment_id: typing.Final = accepted_response.json()["payment_id"]
    with mock.patch.object(
        sqlalchemy_async.AsyncSession,
        "execute",
        autospec=True,
        wraps=sqlalchemy_async.AsyncSession.execute,
        side_effect=[database_error, mock.DEFAULT],
    ) as fetch_payment:
        fetched_response: typing.Final = await api_client.get(f"{conftest.PAYMENTS_PATH}/{payment_id}")

    assert insert_payment.await_count == fetch_payment.await_count == 2
    assert accepted_response.status_code == http.HTTPStatus.ACCEPTED
    assert fetched_response.status_code == http.HTTPStatus.OK
    assert fetched_response.json()["payment_id"] == payment_id
