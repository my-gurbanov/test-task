import contextlib
import typing

import backoff
import structlog
from sqlalchemy import exc as sqlalchemy_exceptions
from sqlalchemy.ext import asyncio as sqlalchemy_async

from payment_processing.settings import settings


logger: typing.Final = structlog.get_logger(__name__)  # noqa: COP005

DATABASE_DRIVER_ERRORS: typing.Final = (sqlalchemy_exceptions.OperationalError, sqlalchemy_exceptions.InterfaceError)
DATABASE_OPERATION_ERRORS: typing.Final = (
    *DATABASE_DRIVER_ERRORS,
    sqlalchemy_exceptions.DisconnectionError,
    sqlalchemy_exceptions.TimeoutError,
)


def is_permanent_database_error(database_error: Exception) -> bool:
    if isinstance(database_error, (sqlalchemy_exceptions.DisconnectionError, sqlalchemy_exceptions.TimeoutError)):
        return False
    if not isinstance(database_error, DATABASE_DRIVER_ERRORS):
        return True
    if database_error.connection_invalidated:
        return False

    sqlstate: typing.Final = getattr(database_error.orig, "sqlstate", None)
    return sqlstate is not None and not (
        sqlstate.startswith("08") or sqlstate in {"40001", "40P01", "53300", "55P03", "57P01", "57P02", "57P03"}
    )


@contextlib.contextmanager
def record_database_errors(operation: str) -> typing.Generator[None]:
    try:
        yield
    except DATABASE_OPERATION_ERRORS as database_error:
        logger.warning("PostgreSQL operation failed", operation=operation, error_type=type(database_error).__name__)
        raise


retry_database_operation: typing.Final = backoff.on_exception(
    backoff.expo,
    DATABASE_OPERATION_ERRORS,
    max_tries=settings.database_retry_attempts,
    factor=settings.database_retry_initial_delay,
    max_value=settings.database_retry_max_delay,
    giveup=is_permanent_database_error,
    logger=None,
)


async def create_database_engine() -> typing.AsyncIterator[sqlalchemy_async.AsyncEngine]:
    database_engine: typing.Final = sqlalchemy_async.create_async_engine(
        settings.database_url,
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
