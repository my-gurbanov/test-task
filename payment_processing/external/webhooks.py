import asyncio
import datetime
import typing
import uuid

import backoff
import base_client
import httpx
import pydantic
import structlog

from payment_processing.domain import PaymentStatus
from payment_processing.settings import settings


logger: typing.Final = structlog.get_logger(__name__)  # noqa: COP005


@typing.final
class PaymentNotification(pydantic.BaseModel):
    event_id: uuid.UUID
    payment_id: uuid.UUID
    status: PaymentStatus
    processed_at: datetime.datetime


@typing.final
class WebhookDeliveryError(Exception):
    pass


@typing.final
class WebhookClient(base_client.BaseClient):
    @typing.override
    async def _process_request(self, request: httpx.Request) -> httpx.Response:  # noqa: COP006
        response: typing.Final = await self.client.send(request, stream=True)
        await response.aclose()
        return response

    @backoff.on_exception(
        backoff.expo,
        WebhookDeliveryError,
        max_tries=settings.webhook_retry_attempts,
        factor=settings.webhook_retry_initial_delay,
        jitter=None,
        logger=None,
    )
    async def send_notification(self, *, webhook_url: str, notification: PaymentNotification) -> None:
        webhook_request: typing.Final = self.client.build_request(
            "POST",
            webhook_url,
            json=notification.model_dump(mode="json"),
        )
        try:
            async with asyncio.timeout(settings.webhook_timeout):
                response: typing.Final = await self.send(request=webhook_request)
        except (httpx.NetworkError, httpx.RemoteProtocolError, httpx.TimeoutException, TimeoutError) as delivery_error:
            logger.warning(
                "Webhook request failed",
                payment_id=notification.payment_id,
                error_type=type(delivery_error).__name__,
            )
            raise WebhookDeliveryError(type(delivery_error).__name__) from None
        if not response.is_success:
            logger.warning(
                "Webhook rejected payment notification",
                payment_id=notification.payment_id,
                status_code=response.status_code,
            )
            raise WebhookDeliveryError(f"Webhook returned HTTP {response.status_code}")
