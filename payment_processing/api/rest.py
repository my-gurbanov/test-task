import datetime
import hmac
import typing
import uuid

import fastapi
import pydantic
import structlog
from fastapi import security

from payment_processing import domain
from payment_processing.database.repositories import PaymentDetails
from payment_processing.ioc import IOCContainer
from payment_processing.settings import settings
from payment_processing.use_cases import payments


logger: typing.Final = structlog.get_logger(__name__)  # noqa: COP005
API_KEY_HEADER: typing.Final = security.APIKeyHeader(name="X-API-Key", auto_error=False)


@typing.final
class AcceptedPayment(pydantic.BaseModel):
    payment_id: uuid.UUID
    status: typing.Literal[domain.PaymentStatus.PENDING] = domain.PaymentStatus.PENDING
    created_at: datetime.datetime


async def verify_api_key(presented_key: typing.Annotated[str | None, fastapi.Security(API_KEY_HEADER)]) -> None:
    if presented_key is None or not hmac.compare_digest(
        presented_key.encode(),
        settings.payment_api_key.get_secret_value().encode(),
    ):
        logger.info("Payment API authentication failed")
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


# /v1 оставляем по ТЗ. Версию лучше передавать в заголовке, чтобы в URL остался адрес самого ресурса.
PAYMENT_ROUTER: typing.Final = fastapi.APIRouter(
    prefix="/api/v1/payments",
    tags=["payments"],
    dependencies=[fastapi.Depends(verify_api_key)],
)

type CreatePaymentUseCaseDependency = typing.Annotated[
    payments.CreatePaymentUseCase,
    fastapi.Depends(IOCContainer.create_payment_use_case),
]
type FetchPaymentUseCaseDependency = typing.Annotated[
    payments.FetchPaymentUseCase,
    fastapi.Depends(IOCContainer.fetch_payment_use_case),
]


@PAYMENT_ROUTER.post("", status_code=fastapi.status.HTTP_202_ACCEPTED)
async def create_payment(
    *,
    payment_request: domain.PaymentRequest,
    idempotency_key: typing.Annotated[str, fastapi.Header(alias="Idempotency-Key", min_length=1, max_length=255)],
    create_payment_use_case: CreatePaymentUseCaseDependency,
) -> AcceptedPayment:
    try:
        payment_record: typing.Final = await create_payment_use_case.execute_use_case(payment_request, idempotency_key)
    except payments.IdempotencyConflictError as conflict_error:
        raise fastapi.HTTPException(
            status_code=fastapi.status.HTTP_409_CONFLICT,
            detail="Idempotency key already used for a different request",
        ) from conflict_error
    return AcceptedPayment(payment_id=payment_record.payment_id, created_at=payment_record.created_at)


@PAYMENT_ROUTER.get("/{payment_id}")
async def fetch_payment(payment_id: uuid.UUID, fetch_payment_use_case: FetchPaymentUseCaseDependency) -> PaymentDetails:
    try:
        payment_record: typing.Final = await fetch_payment_use_case.execute_use_case(payment_id)
    except payments.PaymentNotFoundError as missing_payment:
        logger.info("Payment requested by API was not found", payment_id=payment_id)
        raise fastapi.HTTPException(
            status_code=fastapi.status.HTTP_404_NOT_FOUND,
            detail="Payment not found",
        ) from missing_payment
    logger.info("Payment retrieved", payment_id=payment_id, payment_status=payment_record.status)
    return payment_record
