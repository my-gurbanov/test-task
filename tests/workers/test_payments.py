import http
import json
import typing
import uuid

import aio_pika
import httpx
import pytest

from payment_processing.settings import settings
from tests import conftest


async def test_payment_is_processed_and_notified(
    *, api_client: httpx.AsyncClient, payment_payload: dict[str, str], webhook_server: conftest.WebhookServer
) -> None:
    payment_headers: typing.Final = {"Idempotency-Key": str(uuid.uuid4())}

    accepted_response: typing.Final = await api_client.post(
        conftest.PAYMENTS_PATH, headers=payment_headers, json=payment_payload
    )
    accepted_response.raise_for_status()
    payment_id: typing.Final = accepted_response.json()["payment_id"]
    notification: typing.Final = await webhook_server.receive_notification()
    detail_response: typing.Final = await api_client.get(f"{conftest.PAYMENTS_PATH}/{payment_id}")

    assert accepted_response.status_code == http.HTTPStatus.ACCEPTED
    assert notification["payment_id"] == notification["event_id"] == payment_id
    assert notification["status"] in {"succeeded", "failed"}
    assert detail_response.status_code == http.HTTPStatus.OK
    assert detail_response.json()["status"] == notification["status"]
    assert detail_response.json()["processed_at"] == notification["processed_at"]
    assert detail_response.json()["amount"] == payment_payload["amount"]


@pytest.mark.parametrize("receiver_path", ["/accept-after-retry", "/disconnect-once"])
async def test_webhook_delivery_recovers_after_a_failed_attempt(
    *,
    api_client: httpx.AsyncClient,
    payment_payload: dict[str, str],
    webhook_server: conftest.WebhookServer,
    receiver_path: str,
) -> None:
    payment_headers: typing.Final = {"Idempotency-Key": str(uuid.uuid4())}
    retry_payload: typing.Final = payment_payload | {
        "webhook_url": payment_payload["webhook_url"].replace("/accept", receiver_path)
    }

    accepted_response: typing.Final = await api_client.post(
        conftest.PAYMENTS_PATH, headers=payment_headers, json=retry_payload
    )
    accepted_response.raise_for_status()
    first_delivery: typing.Final = await webhook_server.receive_notification()
    second_delivery: typing.Final = await webhook_server.receive_notification(timeout_seconds=10)

    assert first_delivery == second_delivery
    assert second_delivery["payment_id"] == accepted_response.json()["payment_id"]


async def test_webhook_attempt_limit_survives_redelivery(
    *, api_client: httpx.AsyncClient, payment_payload: dict[str, str], webhook_server: conftest.WebhookServer
) -> None:
    payment_headers: typing.Final = {"Idempotency-Key": str(uuid.uuid4())}
    rejecting_payload: typing.Final = payment_payload | {
        "webhook_url": payment_payload["webhook_url"].replace("/accept", "/reject")
    }

    accepted_response: typing.Final = await api_client.post(
        conftest.PAYMENTS_PATH, headers=payment_headers, json=rejecting_payload
    )
    accepted_response.raise_for_status()
    payment_id: typing.Final = accepted_response.json()["payment_id"]
    first_delivery: typing.Final = await webhook_server.receive_notification()
    second_delivery: typing.Final = await webhook_server.receive_notification(timeout_seconds=10)
    third_delivery: typing.Final = await webhook_server.receive_notification(timeout_seconds=10)
    async with (
        await aio_pika.connect(settings.rabbitmq_url.get_secret_value()) as rabbit_connection,
        await rabbit_connection.channel() as rabbit_channel,
        (await rabbit_channel.get_queue(settings.rabbitmq_dead_letter_queue)).iterator(timeout=10) as dead_letters,
    ):
        dead_letter: typing.Final = await anext(dead_letters)
        async with dead_letter.process():
            await rabbit_channel.default_exchange.publish(
                aio_pika.Message(dead_letter.body, content_type=dead_letter.content_type),
                routing_key=settings.rabbitmq_payment_queue,
            )
        replayed_dead_letter: typing.Final = await anext(dead_letters)
        await replayed_dead_letter.ack()

    assert first_delivery == second_delivery == third_delivery
    assert third_delivery["payment_id"] == json.loads(replayed_dead_letter.body)["payment_id"] == payment_id
    first_attempt, second_attempt, third_attempt = webhook_server.delivery_times
    assert second_attempt - first_attempt >= 0.95
    assert third_attempt - second_attempt >= 1.95
    assert webhook_server.notifications.empty()
