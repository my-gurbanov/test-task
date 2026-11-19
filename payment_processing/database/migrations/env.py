import typing

import sqlalchemy
from alembic import context

from payment_processing.database import connection
from payment_processing.database.models import DatabaseBase
from payment_processing.settings import settings


def apply_offline_migrations() -> None:
    context.configure(url=settings.database_url, target_metadata=DatabaseBase.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


@connection.retry_database_operation
def apply_online_migrations() -> None:
    with connection.record_database_errors("apply_online_migrations"):
        migration_engine: typing.Final = sqlalchemy.create_engine(settings.database_url, poolclass=sqlalchemy.NullPool)
        try:
            with migration_engine.connect() as migration_connection:
                context.configure(connection=migration_connection, target_metadata=DatabaseBase.metadata)
                with context.begin_transaction():
                    context.run_migrations()
        finally:
            migration_engine.dispose()


if context.is_offline_mode():
    apply_offline_migrations()
else:
    apply_online_migrations()
