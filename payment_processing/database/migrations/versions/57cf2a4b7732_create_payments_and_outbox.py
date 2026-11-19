import typing

import sqlalchemy
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: typing.Final = "57cf2a4b7732"
down_revision: typing.Final = None
branch_labels: typing.Final = None
depends_on: typing.Final = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sqlalchemy.Column("payment_id", sqlalchemy.Uuid(), primary_key=True),
        sqlalchemy.Column("amount", sqlalchemy.Numeric(18, 2), nullable=False),
        sqlalchemy.Column("currency", sqlalchemy.String(3), nullable=False),
        sqlalchemy.Column("description", sqlalchemy.String(1000), nullable=False),
        sqlalchemy.Column("metadata", JSONB(), nullable=False),
        sqlalchemy.Column("status", sqlalchemy.String(9), nullable=False),
        sqlalchemy.Column("idempotency_key", sqlalchemy.String(255), nullable=False, unique=True),
        sqlalchemy.Column("request_digest", sqlalchemy.String(64), nullable=False),
        sqlalchemy.Column("webhook_url", sqlalchemy.String(), nullable=False),
        sqlalchemy.Column("processed_at", sqlalchemy.DateTime(timezone=True)),
        sqlalchemy.Column("webhook_attempts", sqlalchemy.Integer(), server_default="0", nullable=False),
        sqlalchemy.Column("webhook_delivered_at", sqlalchemy.DateTime(timezone=True)),
        sqlalchemy.Column(
            "created_at", sqlalchemy.DateTime(timezone=True), server_default=sqlalchemy.func.now(), nullable=False
        ),
        sqlalchemy.Column(
            "updated_at", sqlalchemy.DateTime(timezone=True), server_default=sqlalchemy.func.now(), nullable=False
        ),
        sqlalchemy.Column("deleted_at", sqlalchemy.DateTime(timezone=True)),
        sqlalchemy.CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        sqlalchemy.CheckConstraint("currency IN ('RUB', 'USD', 'EUR')", name="ck_payments_currency"),
        sqlalchemy.CheckConstraint("status IN ('pending', 'succeeded', 'failed')", name="ck_payments_status"),
    )
    op.create_table(
        "outbox",
        sqlalchemy.Column(
            "payment_id", sqlalchemy.Uuid(), sqlalchemy.ForeignKey("payments.payment_id"), primary_key=True
        ),
        sqlalchemy.Column("published_at", sqlalchemy.DateTime(timezone=True)),
        sqlalchemy.Column(
            "created_at", sqlalchemy.DateTime(timezone=True), server_default=sqlalchemy.func.now(), nullable=False
        ),
        sqlalchemy.Column(
            "updated_at", sqlalchemy.DateTime(timezone=True), server_default=sqlalchemy.func.now(), nullable=False
        ),
        sqlalchemy.Column("deleted_at", sqlalchemy.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_outbox_unpublished",
        "outbox",
        ["created_at", "payment_id"],
        postgresql_where=sqlalchemy.text("published_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("outbox")
    op.drop_table("payments")
