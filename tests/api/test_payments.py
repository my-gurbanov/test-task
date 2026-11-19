import asyncio
import http
import typing
import uuid

import httpx
import pytest

from tests import conftest


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
        ({"amount": "0.001"}, True),
        ({"amount": 100000000000000.02}, True),
        ({"currency": "GBP"}, True),
        ({"webhook_url": "ftp://example.com"}, True),
        ({"metadata": {"entries": [{"reference": "\x00"}]}}, True),
        ({}, False),
    ],
)
async def test_create_payment_rejects_invalid_input(
    *,
    api_client: httpx.AsyncClient,
    payment_payload: dict[str, str],
    invalid_fields: dict[str, object],
    supply_idempotency: bool,
) -> None:
    payment_headers: typing.Final = {"Idempotency-Key": str(uuid.uuid4())} if supply_idempotency else {}

    validation_response: typing.Final = await api_client.post(
        conftest.PAYMENTS_PATH, headers=payment_headers, json=payment_payload | invalid_fields
    )

    assert validation_response.status_code == http.HTTPStatus.UNPROCESSABLE_CONTENT


async def test_create_payment_replays_original_acceptance(
    *, api_client: httpx.AsyncClient, payment_payload: dict[str, str], webhook_server: conftest.WebhookServer
) -> None:
    payment_headers: typing.Final = {"Idempotency-Key": str(uuid.uuid4())}
    equivalent_payload: typing.Final = payment_payload | {"amount": "19.5"}

    first_response, second_response = await asyncio.gather(
        api_client.post(conftest.PAYMENTS_PATH, headers=payment_headers, json=payment_payload),
        api_client.post(conftest.PAYMENTS_PATH, headers=payment_headers, json=equivalent_payload),
    )
    notification: typing.Final = await webhook_server.receive_notification()
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
    assert first_response.json()["payment_id"] == notification["payment_id"]


async def test_create_payment_rejects_changed_request_for_existing_key(
    *, api_client: httpx.AsyncClient, payment_payload: dict[str, str], webhook_server: conftest.WebhookServer
) -> None:
    payment_headers: typing.Final = {"Idempotency-Key": str(uuid.uuid4())}
    accepted_response: typing.Final = await api_client.post(
        conftest.PAYMENTS_PATH, headers=payment_headers, json=payment_payload
    )
    accepted_response.raise_for_status()

    conflict_response: typing.Final = await api_client.post(
        conftest.PAYMENTS_PATH, headers=payment_headers, json=payment_payload | {"amount": "20.00"}
    )
    await webhook_server.receive_notification()

    assert conflict_response.status_code == http.HTTPStatus.CONFLICT


async def test_fetch_payment_returns_not_found(api_client: httpx.AsyncClient) -> None:
    unknown_payment_path: typing.Final = f"{conftest.PAYMENTS_PATH}/{uuid.uuid4()}"

    missing_response: typing.Final = await api_client.get(unknown_payment_path)

    assert missing_response.status_code == http.HTTPStatus.NOT_FOUND
