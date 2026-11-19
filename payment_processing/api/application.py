import contextlib
import typing

import fastapi
from microbootstrap.bootstrappers.fastapi import FastApiBootstrapper
from microbootstrap.config.fastapi import FastApiConfig

from payment_processing.api.rest import PAYMENT_ROUTER
from payment_processing.ioc import IOCContainer
from payment_processing.settings import settings
from payment_processing.workers.application import run_consumer


@contextlib.asynccontextmanager
async def run_application_lifespan(application: fastapi.FastAPI) -> typing.AsyncGenerator[None]:
    try:
        async with run_consumer():
            application.state.payment_worker_ready = True
            try:
                yield
            finally:
                application.state.payment_worker_ready = False
    finally:
        await IOCContainer.tear_down()


def build_application() -> fastapi.FastAPI:
    fastapi_application: typing.Final = (
        FastApiBootstrapper(settings)
        .configure_application(FastApiConfig(lifespan=run_application_lifespan))
        .bootstrap()
    )
    fastapi_application.include_router(PAYMENT_ROUTER)
    return fastapi_application
