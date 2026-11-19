import contextlib
import typing

import fastapi
from microbootstrap.bootstrappers.fastapi import FastApiBootstrapper
from microbootstrap.config.fastapi import FastApiConfig
from microbootstrap.granian_server import create_granian_server

from payment_processing.api.rest import PAYMENT_ROUTER
from payment_processing.ioc import IOCContainer
from payment_processing.settings import settings


@contextlib.asynccontextmanager
async def run_application_lifespan(_application: fastapi.FastAPI) -> typing.AsyncGenerator[None]:
    try:
        yield
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


if __name__ == "__main__":
    create_granian_server("payment_processing.api.application:build_application", settings, factory=True).serve()
