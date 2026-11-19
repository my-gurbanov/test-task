import typing

import backoff
from sqlalchemy import exc as sqlalchemy_exceptions
from sqlalchemy.ext import asyncio as sqlalchemy_async

from payment_processing.settings import settings


DATABASE_OPERATION_ERRORS: typing.Final = (
    sqlalchemy_exceptions.OperationalError,
    sqlalchemy_exceptions.InterfaceError,
    sqlalchemy_exceptions.DisconnectionError,
    sqlalchemy_exceptions.TimeoutError,
)


retry_database_operation: typing.Final = backoff.on_exception(
    backoff.expo,
    DATABASE_OPERATION_ERRORS,
    max_tries=settings.database_retry_attempts,
    factor=settings.database_retry_initial_delay,
    max_value=settings.database_retry_max_delay,
    logger=None,
)


async def create_database_engine() -> typing.AsyncIterator[sqlalchemy_async.AsyncEngine]:
    database_engine: typing.Final = sqlalchemy_async.create_async_engine(
        settings.database_url,
        connect_args={
            "connect_timeout": settings.database_connect_timeout,
            "options": f"-c statement_timeout={settings.database_statement_timeout_ms}",
        },
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_pool_max_overflow,
        pool_timeout=settings.database_pool_timeout,
        pool_recycle=settings.database_pool_recycle,
        pool_pre_ping=settings.database_pool_pre_ping,
        hide_parameters=True,
    )
    try:
        yield database_engine
    finally:
        await database_engine.dispose()


def create_sessionmaker(
    database_engine: sqlalchemy_async.AsyncEngine,
) -> sqlalchemy_async.async_sessionmaker[sqlalchemy_async.AsyncSession]:
    return sqlalchemy_async.async_sessionmaker(bind=database_engine, expire_on_commit=False)
