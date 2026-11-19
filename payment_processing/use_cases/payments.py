import dataclasses
import decimal
import hashlib
import json
import typing
import uuid

import structlog

from payment_processing import domain
from payment_processing.database import repositories
from payment_processing.external import webhooks
from payment_processing.external.payment_gateway import PaymentGatewayClient


logger: typing.Final = structlog.get_logger(__name__)  # noqa: COP005


@typing.final
class IdempotencyConflictError(Exception):
    pass


@typing.final
class PaymentNotFoundError(Exception):
    pass


@typing.final
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class CreatePaymentUseCase:
    payment_repository: repositories.PaymentRepository

    async def execute_use_case(
        self,
        payment_request: domain.PaymentRequest,
        idempotency_key: str,
    ) -> repositories.PaymentDetails:
        normalized_request: typing.Final = payment_request.model_dump(mode="json")
        normalized_request["amount"] = str(payment_request.amount.quantize(decimal.Decimal("0.01")))
        request_digest: typing.Final = hashlib.sha256(
            json.dumps(normalized_request, sort_keys=True).encode(),
        ).hexdigest()
        payment_result: typing.Final = await self.payment_repository.save_payment(
            payment_request=payment_request,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if payment_result is None:
            logger.info("Payment idempotency conflict")
            raise IdempotencyConflictError
        accepted_payment, newly_created = payment_result
        logger.info(
            "Payment accepted" if newly_created else "Original payment acceptance replayed",
            payment_id=accepted_payment.payment_id,
        )
        return accepted_payment


@typing.final
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FetchPaymentUseCase:
    payment_repository: repositories.PaymentRepository

    async def execute_use_case(self, payment_id: uuid.UUID) -> repositories.PaymentDetails:
        payment_record: typing.Final = await self.payment_repository.fetch_payment(payment_id)
        if payment_record is None:
            raise PaymentNotFoundError(payment_id)
        return payment_record


@typing.final
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class ProcessPaymentUseCase:
    fetch_payment_use_case: FetchPaymentUseCase
    payment_repository: repositories.PaymentRepository
    payment_gateway_client: PaymentGatewayClient
    webhook_client: webhooks.WebhookClient

    async def execute_use_case(self, payment_id: uuid.UUID) -> None:
        existing_payment: typing.Final = await self.fetch_payment_use_case.execute_use_case(payment_id)
        if existing_payment.webhook_delivered_at is not None:
            logger.info("Payment notification already delivered", payment_id=payment_id)
            return
        was_pending: typing.Final = existing_payment.status == domain.PaymentStatus.PENDING
        payment_record: typing.Final = (
            await self.payment_repository.record_outcome(
                payment_id,
                await self.payment_gateway_client.process_payment(),
            )
            if was_pending
            else existing_payment
        )
        logger.info(
            "Payment outcome recorded" if was_pending else "Resuming notification for completed payment",
            payment_id=payment_id,
            payment_status=payment_record.status,
        )
        if payment_record.processed_at is None:
            raise RuntimeError("A terminal payment has no processing timestamp")

        notification: typing.Final = webhooks.PaymentNotification(
            event_id=payment_id,
            payment_id=payment_id,
            status=payment_record.status,
            processed_at=payment_record.processed_at,
        )
        await self.webhook_client.send_notification(webhook_url=payment_record.webhook_url, notification=notification)
        await self.payment_repository.record_webhook_delivery(payment_id)
        logger.info("Payment notification delivered", payment_id=payment_id)
