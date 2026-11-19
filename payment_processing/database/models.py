import datetime
import decimal
import typing
import uuid

import pydantic
import sqlalchemy
from sqlalchemy import orm
from sqlalchemy.dialects.postgresql import JSONB


class DatabaseBase(orm.DeclarativeBase):
    pass


@typing.final
class PaymentRecord(DatabaseBase):
    __tablename__ = "payments"
    __table_args__ = (
        sqlalchemy.CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        sqlalchemy.CheckConstraint("currency IN ('RUB', 'USD', 'EUR')", name="ck_payments_currency"),
        sqlalchemy.CheckConstraint("status IN ('pending', 'succeeded', 'failed')", name="ck_payments_status"),
    )

    payment_id: orm.Mapped[uuid.UUID] = orm.mapped_column(primary_key=True, default=uuid.uuid4)
    payment_amount: orm.Mapped[decimal.Decimal] = orm.mapped_column("amount", sqlalchemy.Numeric(18, 2))
    currency: orm.Mapped[str] = orm.mapped_column(sqlalchemy.String(3))
    description: orm.Mapped[str] = orm.mapped_column(sqlalchemy.String(1000))
    payment_metadata: orm.Mapped[dict[str, pydantic.JsonValue]] = orm.mapped_column("metadata", JSONB)
    payment_status: orm.Mapped[str] = orm.mapped_column("status", sqlalchemy.String(9))
    idempotency_key: orm.Mapped[str] = orm.mapped_column(sqlalchemy.String(255), unique=True)
    request_digest: orm.Mapped[str] = orm.mapped_column(sqlalchemy.String(64))
    webhook_url: orm.Mapped[str]
    created_at: orm.Mapped[datetime.datetime] = orm.mapped_column(
        sqlalchemy.DateTime(timezone=True), server_default=sqlalchemy.func.now()
    )
    processed_at: orm.Mapped[datetime.datetime | None] = orm.mapped_column(sqlalchemy.DateTime(timezone=True))
    webhook_delivered_at: orm.Mapped[datetime.datetime | None] = orm.mapped_column(sqlalchemy.DateTime(timezone=True))


@typing.final
class OutboxEvent(DatabaseBase):
    __tablename__ = "outbox"
    __table_args__ = (
        sqlalchemy.Index(
            "ix_outbox_unpublished",
            "created_at",
            "payment_id",
            postgresql_where=sqlalchemy.text("published_at IS NULL"),
        ),
    )

    payment_id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        sqlalchemy.ForeignKey("payments.payment_id"), primary_key=True
    )
    created_at: orm.Mapped[datetime.datetime] = orm.mapped_column(
        sqlalchemy.DateTime(timezone=True), server_default=sqlalchemy.func.now()
    )
    published_at: orm.Mapped[datetime.datetime | None] = orm.mapped_column(sqlalchemy.DateTime(timezone=True))
