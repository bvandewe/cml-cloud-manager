import logging

from application.commands import CommandHandlerBase, CreateTaskCommand
from application.events.integration.task_events import TaskCreationRequestedIntegrationEventV1
from multipledispatch import dispatch
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping.mapper import Mapper
from neuroglia.mediation.mediator import IntegrationEventHandler, Mediator

log = logging.getLogger(__name__)


class TaskCreationRequestedIntegrationEventV1Handler(CommandHandlerBase, IntegrationEventHandler[TaskCreationRequestedIntegrationEventV1]):
    mediator: Mediator
    """ Gets the service used to mediate calls """

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
    ) -> None:
        super().__init__(mediator, mapper, cloud_event_bus, cloud_event_publishing_options)

    @dispatch(TaskCreationRequestedIntegrationEventV1)
    async def handle_async(self, notification: TaskCreationRequestedIntegrationEventV1) -> None:
        log.debug(f"🌐 Handling event type: {notification.__cloudevent__type__} from {notification.__cloudevent__source__}")  # type: ignore
        if not notification.title:
            log.warning("❗ Task creation requested event is missing a title. Skipping task creation.")
            return
        await self.mediator.execute_async(
            CreateTaskCommand(
                title=notification.title,
                priority=notification.priority,
                description=notification.description,
            )
        )
