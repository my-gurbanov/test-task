import asyncio
import http
import http.server
import json
import queue
import threading
import time
import typing
import uuid

import httpx
import pytest

from payment_processing.settings import settings


PAYMENTS_PATH: typing.Final = "/api/v1/payments"


@typing.final
class WebhookServer(http.server.ThreadingHTTPServer):
    notifications: queue.Queue[dict[str, str]]
    delivery_times: list[float]
    delivery_attempts: int = 0

    async def receive_notification(self, timeout_seconds: float = 30) -> dict[str, str]:
        return await asyncio.to_thread(self.notifications.get, True, timeout_seconds)


@typing.final
class WebhookHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: COP007
        webhook_server: typing.Final = typing.cast("WebhookServer", self.server)
        webhook_server.delivery_attempts += 1
        webhook_server.delivery_times.append(time.monotonic())
        webhook_server.notifications.put(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        if self.path == "/disconnect-once" and webhook_server.delivery_attempts == 1:
            return
        should_reject: typing.Final = self.path == "/reject" or (
            self.path == "/accept-after-retry" and webhook_server.delivery_attempts == 1
        )
        self.send_response(http.HTTPStatus.INTERNAL_SERVER_ERROR if should_reject else http.HTTPStatus.NO_CONTENT)
        self.end_headers()


@pytest.fixture
def webhook_server() -> typing.Iterator[WebhookServer]:
    test_webhook_server: typing.Final = WebhookServer(("", 0), WebhookHandler)
    test_webhook_server.notifications = queue.Queue()
    test_webhook_server.delivery_times = []
    server_thread: typing.Final = threading.Thread(target=test_webhook_server.serve_forever, daemon=True)
    server_thread.start()
    try:
        yield test_webhook_server
    finally:
        test_webhook_server.shutdown()
        test_webhook_server.server_close()
        server_thread.join()


@pytest.fixture
async def api_client() -> typing.AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        base_url="http://api:8000", headers={"X-API-Key": settings.payment_api_key.get_secret_value()}
    ) as payment_client:
        async with asyncio.timeout(15):
            while True:
                try:
                    await payment_client.get(f"{PAYMENTS_PATH}/{uuid.uuid4()}")
                except httpx.ConnectError:
                    await asyncio.sleep(0.2)
                else:
                    break
        yield payment_client


@pytest.fixture
def payment_payload(webhook_server: WebhookServer) -> dict[str, str]:
    return {
        "amount": "19.50",
        "currency": "EUR",
        "description": "Test invoice",
        "webhook_url": f"http://tests:{webhook_server.server_port}/accept",
    }
