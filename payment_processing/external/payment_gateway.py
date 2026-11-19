import asyncio
import dataclasses
import random
import typing

from payment_processing.domain import PaymentStatus
from payment_processing.settings import settings


@typing.final
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class PaymentGatewayClient:
    async def process_payment(self) -> PaymentStatus:
        await asyncio.sleep(random.uniform(settings.gateway_min_delay, settings.gateway_max_delay))  # noqa: S311
        if random.random() < settings.gateway_success_probability:  # noqa: S311
            return PaymentStatus.SUCCEEDED
        return PaymentStatus.FAILED
