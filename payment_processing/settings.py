import typing

import microbootstrap
import pydantic


@typing.final
class Settings(microbootstrap.FastApiSettings, microbootstrap.FastStreamSettings):
    service_name: str = "payment-processing"
    service_version: str = "0.1.0"
    server_reload: bool = False
    asyncapi_path: str | None = None

    health_checks_enabled: bool = False
    health_checks_include_in_schema: bool = False

    cors_allowed_origins: list[str] = pydantic.Field(default_factory=lambda: ["*"])
    cors_allowed_methods: list[str] = pydantic.Field(default_factory=lambda: ["GET", "POST"])
    cors_allowed_headers: list[str] = pydantic.Field(default_factory=lambda: ["*"])

    payment_api_key: pydantic.SecretStr = pydantic.Field(validation_alias="API_KEY", min_length=1)
    database_url: str
    rabbitmq_url: pydantic.SecretStr
    database_pool_size: pydantic.PositiveInt = 5
    database_pool_max_overflow: pydantic.NonNegativeInt = 10
    database_pool_timeout: pydantic.PositiveFloat = 30
    database_pool_recycle: pydantic.PositiveInt = 1800
    database_pool_pre_ping: bool = True
    database_retry_attempts: pydantic.PositiveInt = 3
    database_retry_initial_delay: pydantic.PositiveFloat = 0.1
    database_retry_max_delay: pydantic.PositiveFloat = 1

    rabbitmq_payment_queue: str = "payments.new"
    rabbitmq_dead_letter_exchange: str = "payments.dlx"
    rabbitmq_dead_letter_queue: str = "payments.dead"
    rabbitmq_connect_timeout: pydantic.PositiveFloat = 5
    rabbitmq_reconnect_interval: pydantic.PositiveFloat = 2
    rabbitmq_publish_timeout: pydantic.PositiveFloat = 5
    outbox_poll_interval: pydantic.PositiveFloat = 0.5
    outbox_retry_initial_delay: pydantic.PositiveFloat = 0.5
    outbox_retry_max_delay: pydantic.PositiveFloat = 30

    webhook_timeout: pydantic.PositiveFloat = 5
    webhook_retry_attempts: pydantic.PositiveInt = 3
    webhook_retry_initial_delay: pydantic.PositiveFloat = 1
    gateway_min_delay: pydantic.NonNegativeFloat = 2
    gateway_max_delay: pydantic.NonNegativeFloat = 5
    gateway_success_probability: typing.Annotated[float, pydantic.Field(ge=0, le=1)] = 0.9


settings: typing.Final = Settings()
