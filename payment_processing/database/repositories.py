import contextlib
import dataclasses
import datetime
import decimal
import typing
import uuid

import pydantic
import sqlalchemy
import structlog
from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext import asyncio as sqlalchemy_async

import payment_processing.database.connection as database_connection
from payment_processing import domain
from payment_processing.database import models
from payment_processing.settings import settings


logger: typing.Final = structlog.get_logger(__name__)  # noqa: COP005


@typing.final
class PaymentDetails(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(from_attributes=True)

    payment_id: uuid.UUID
    amount: decimal.Decimal = pydantic.Field(validation_alias="payment_amount")
    currency: domain.Currency
    description: str
    metadata: dict[str, pydantic.JsonValue] = pydantic.Field(validation_alias="payment_metadata")
    status: domain.PaymentStatus = pydantic.Field(validation_alias="payment_status")
    idempotency_key: str
    webhook_url: str
    created_at: datetime.datetime
    processed_at: datetime.datetime | None
    webhook_delivered_at: datetime.datetime | None = pydantic.Field(exclude=True)


@typing.final
class PaymentLookup(SQLAlchemyAsyncRepository[models.PaymentRecord]):
    model_type = models.PaymentRecord
    id_attribute = "payment_id"


@typing.final
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class PaymentRepository:
    sessionmaker: sqlalchemy_async.async_sessionmaker[sqlalchemy_async.AsyncSession]

    @database_connection.retry_database_operation
    async def save_payment(
        self,
        *,
        payment_request: domain.PaymentRequest,
        idempotency_key: str,
        request_digest: str,
    ) -> tuple[PaymentDetails, bool] | None:
        try:
            async with self.sessionmaker.begin() as database_session:
                insert_payment: typing.Final = (
                    insert(models.PaymentRecord)
                    .values(
                        payment_amount=payment_request.amount,
                        currency=payment_request.currency,
                        description=payment_request.description,
                        payment_metadata=payment_request.metadata,
                        payment_status=domain.PaymentStatus.PENDING,
                        idempotency_key=idempotency_key,
                        request_digest=request_digest,
                        webhook_url=str(payment_request.webhook_url),
                    )
                    .on_conflict_do_nothing(index_elements=[models.PaymentRecord.idempotency_key])
                    .returning(models.PaymentRecord)
                )
                inserted_payment: typing.Final = await database_session.scalar(insert_payment)
                if inserted_payment is not None:
                    database_session.add(models.OutboxEvent(payment_id=inserted_payment.payment_id))
                    return PaymentDetails.model_validate(inserted_payment), True

                existing_payment: typing.Final = await PaymentLookup(
                    session=database_session,
                    wrap_exceptions=False,
                ).get_one(idempotency_key=idempotency_key)
                if existing_payment.request_digest != request_digest:
                    return None
                return PaymentDetails.model_validate(existing_payment), False
        except database_connection.DATABASE_OPERATION_ERRORS as database_error:
            logger.warning("Failed to save payment", error_type=type(database_error).__name__)
            raise

    @database_connection.retry_database_operation
    async def fetch_payment(self, payment_id: uuid.UUID) -> PaymentDetails | None:
        try:
            async with self.sessionmaker() as database_session:
                payment_record: typing.Final = await PaymentLookup(
                    session=database_session,
                    wrap_exceptions=False,
                ).get_one_or_none(payment_id=payment_id)
                return PaymentDetails.model_validate(payment_record) if payment_record is not None else None
        except database_connection.DATABASE_OPERATION_ERRORS as database_error:
            logger.warning("Failed to fetch payment", payment_id=payment_id, error_type=type(database_error).__name__)
            raise

    @database_connection.retry_database_operation
    async def record_outcome(self, payment_id: uuid.UUID, payment_status: domain.PaymentStatus) -> PaymentDetails:
        try:
            async with self.sessionmaker.begin() as database_session:
                await database_session.execute(
                    sqlalchemy.update(models.PaymentRecord)
                    .where(
                        models.PaymentRecord.payment_id == payment_id,
                        models.PaymentRecord.payment_status == domain.PaymentStatus.PENDING,
                    )
                    .values(payment_status=payment_status, processed_at=sqlalchemy.func.now()),
                )
                return PaymentDetails.model_validate(
                    await PaymentLookup(session=database_session, wrap_exceptions=False).get(payment_id),
                )
        except database_connection.DATABASE_OPERATION_ERRORS as database_error:
            logger.warning("Failed to record outcome", payment_id=payment_id, error_type=type(database_error).__name__)
            raise

    @database_connection.retry_database_operation
    async def record_webhook_attempt(self, payment_id: uuid.UUID) -> bool:
        try:
            async with self.sessionmaker.begin() as database_session:
                reserved_payment: typing.Final = await database_session.scalar(
                    sqlalchemy.update(models.PaymentRecord)
                    .where(
                        models.PaymentRecord.payment_id == payment_id,
                        models.PaymentRecord.webhook_attempts < settings.webhook_retry_attempts,
                        models.PaymentRecord.webhook_delivered_at.is_(None),
                    )
                    .values(webhook_attempts=models.PaymentRecord.webhook_attempts + 1)
                    .returning(models.PaymentRecord.payment_id),
                )
        except database_connection.DATABASE_OPERATION_ERRORS as database_error:
            logger.warning(
                "Failed to reserve webhook attempt",
                payment_id=payment_id,
                error_type=type(database_error).__name__,
            )
            raise
        return reserved_payment is not None

    @database_connection.retry_database_operation
    async def record_webhook_delivery(self, payment_id: uuid.UUID) -> None:
        try:
            async with self.sessionmaker.begin() as database_session:
                await database_session.execute(
                    sqlalchemy.update(models.PaymentRecord)
                    .where(
                        models.PaymentRecord.payment_id == payment_id,
                        models.PaymentRecord.webhook_delivered_at.is_(None),
                    )
                    .values(webhook_delivered_at=sqlalchemy.func.now()),
                )
        except database_connection.DATABASE_OPERATION_ERRORS as database_error:
            logger.warning(
                "Failed to record webhook delivery",
                payment_id=payment_id,
                error_type=type(database_error).__name__,
            )
            raise


@typing.final
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class OutboxRepository:
    sessionmaker: sqlalchemy_async.async_sessionmaker[sqlalchemy_async.AsyncSession]

    @contextlib.asynccontextmanager
    async def lock_next_event(self) -> typing.AsyncGenerator[uuid.UUID | None]:
        async with self.sessionmaker.begin() as database_session:
            outbox_record: typing.Final = await database_session.scalar(
                sqlalchemy.select(models.OutboxEvent)
                .where(models.OutboxEvent.published_at.is_(None))
                .order_by(models.OutboxEvent.created_at, models.OutboxEvent.payment_id)
                .limit(1)
                .with_for_update(skip_locked=True),
            )
            if outbox_record is None:
                yield None
                return
            yield outbox_record.payment_id
            outbox_record.published_at = datetime.datetime.now(datetime.UTC)
