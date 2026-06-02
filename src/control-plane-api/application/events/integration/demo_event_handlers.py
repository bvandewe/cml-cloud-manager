import logging
from dataclasses import dataclass
from typing import Any

from multipledispatch import dispatch
from neuroglia.eventing.cloud_events.decorators import cloudevent
from neuroglia.integration.models import IntegrationEvent
from neuroglia.mediation.mediator import IntegrationEventHandler

log = logging.getLogger(__name__)


@cloudevent("com.source.dummy.test.requested.v1")
@dataclass
class TestRequestedIntegrationEventV1(IntegrationEvent[str]):
    foo: str
    """A string field."""

    bar: int | None
    """An integer field."""

    boo: bool | None
    """A boolean field."""

    data: Any | None
    """Additional data."""


class TestIntegrationEventHandler(IntegrationEventHandler[TestRequestedIntegrationEventV1]):
    def __init__(self) -> None:
        pass

    @dispatch(TestRequestedIntegrationEventV1)
    async def handle_async(self, e: TestRequestedIntegrationEventV1) -> None:
        log.debug(f"🌐 Handling event type: {e.__cloudevent__type__}")
