import http
import json
import time
import typing
import uuid

import httpx
import pytest
import respx
from faststream import rabbit

from payment_processing.settings import settings
from tests import conftest, factories


@pytest.mark.parametrize(
    "expected_status",
    ["succeeded", "failed"],
    ids=["gateway-accepted", "gateway-declined"],
)
async def test_payment_is_processed_and_notified(
    *,
    api_client: httpx.AsyncClient,
    payment_broker: rabbit.RabbitBroker,
    respx_mock: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
    expected_status: str,
) -> None:
    monkeypatch.setattr(settings, "gateway_success_probability", 1.0 if expected_status == "succeeded" else 0.0)
    payment_payload: typing.Final = factories.PaymentPayloadFactory.build()
    webhook_route: typing.Final = respx_mock.post(payment_payload["webhook_url"]).respond(http.HTTPStatus.NO_CONTENT)
    accepted_response: typing.Final = await api_client.post(
        conftest.PAYMENTS_PATH,
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json=payment_payload,
    )
    accepted_response.raise_for_status()
    payment_id: typing.Final = accepted_response.json()["payment_id"]

    await payment_broker.publish({"payment_id": payment_id}, queue=settings.rabbitmq_payment_queue)
    detail_response: typing.Final = await api_client.get(f"{conftest.PAYMENTS_PATH}/{payment_id}")

    assert accepted_response.status_code == http.HTTPStatus.ACCEPTED
    assert webhook_route.call_count == 1
    notification: typing.Final = json.loads(webhook_route.calls.last.request.content)
    assert notification["payment_id"] == notification["event_id"] == payment_id
    assert notification["status"] == expected_status
    assert detail_response.status_code == http.HTTPStatus.OK
    assert detail_response.json()["status"] == notification["status"]
    assert detail_response.json()["processed_at"] == notification["processed_at"]
    assert detail_response.json()["amount"] == payment_payload["amount"]


@pytest.mark.parametrize(
    "first_attempt",
    [
        pytest.param(httpx.Response(http.HTTPStatus.INTERNAL_SERVER_ERROR), id="http-500"),
        pytest.param(httpx.RemoteProtocolError("Disconnected"), id="connection-dropped"),
    ],
)
async def test_webhook_delivery_recovers_after_a_failed_attempt(
    *,
    api_client: httpx.AsyncClient,
    payment_broker: rabbit.RabbitBroker,
    respx_mock: respx.MockRouter,
    first_attempt: httpx.Response | httpx.RemoteProtocolError,
) -> None:
    payment_payload: typing.Final = factories.PaymentPayloadFactory.build()
    webhook_route: typing.Final = respx_mock.post(payment_payload["webhook_url"]).mock(
        side_effect=[first_attempt, httpx.Response(http.HTTPStatus.NO_CONTENT)],
    )
    accepted_response: typing.Final = await api_client.post(
        conftest.PAYMENTS_PATH,
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json=payment_payload,
    )
    accepted_response.raise_for_status()
    payment_id: typing.Final = accepted_response.json()["payment_id"]

    await payment_broker.publish({"payment_id": payment_id}, queue=settings.rabbitmq_payment_queue)

    assert webhook_route.call_count == 2
    assert webhook_route.calls[0].request.content == webhook_route.calls[1].request.content
    assert json.loads(webhook_route.calls.last.request.content)["payment_id"] == payment_id


async def test_webhook_attempt_limit_survives_redelivery(
    *,
    api_client: httpx.AsyncClient,
    payment_broker: rabbit.RabbitBroker,
    respx_mock: respx.MockRouter,
) -> None:
    delivery_times: typing.Final[list[float]] = []

    def reject_webhook(_request: httpx.Request) -> httpx.Response:
        delivery_times.append(time.monotonic())
        return httpx.Response(http.HTTPStatus.INTERNAL_SERVER_ERROR)

    payment_payload: typing.Final = factories.PaymentPayloadFactory.build()
    webhook_route: typing.Final = respx_mock.post(payment_payload["webhook_url"]).mock(side_effect=reject_webhook)
    accepted_response: typing.Final = await api_client.post(
        conftest.PAYMENTS_PATH,
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json=payment_payload,
    )
    accepted_response.raise_for_status()
    payment_id: typing.Final = accepted_response.json()["payment_id"]
    payment_event: typing.Final = {"payment_id": payment_id}

    await payment_broker.publish(payment_event, queue=settings.rabbitmq_payment_queue)
    await payment_broker.publish(payment_event, queue=settings.rabbitmq_payment_queue)

    assert webhook_route.call_count == 3
    assert len({one_delivery.request.content for one_delivery in webhook_route.calls}) == 1
    assert json.loads(webhook_route.calls.last.request.content)["payment_id"] == payment_id
    first_attempt, second_attempt, third_attempt = delivery_times
    assert second_attempt - first_attempt >= 0.95
    assert third_attempt - second_attempt >= 1.95
