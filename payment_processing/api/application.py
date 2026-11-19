import contextlib
import logging
import typing

import fastapi
from microbootstrap.bootstrappers.fastapi import FastApiBootstrapper
from microbootstrap.config.fastapi import FastApiConfig

from payment_processing.api.rest import PAYMENT_ROUTER
from payment_processing.ioc import IOCContainer
from payment_processing.settings import settings
from payment_processing.workers.application import run_consumer


@contextlib.asynccontextmanager
async def run_application_lifespan(_application: fastapi.FastAPI) -> typing.AsyncGenerator[None]:
    try:
        async with run_consumer():
            yield
    finally:
        await IOCContainer.tear_down()


def build_application() -> fastapi.FastAPI:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    fastapi_application: typing.Final = (
        FastApiBootstrapper(settings)
        .configure_application(FastApiConfig(lifespan=run_application_lifespan))
        .bootstrap()
    )
    fastapi_application.include_router(PAYMENT_ROUTER)
    return fastapi_application
