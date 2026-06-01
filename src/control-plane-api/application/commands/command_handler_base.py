import datetime
import logging
import uuid
from dataclasses import asdict

from infrastructure.observability.cqrs_instrumentation import wrap_handle_async_with_enrichment
from neuroglia.eventing.cloud_events.cloud_event import (
    CloudEvent,
    CloudEventSpecVersion,
)
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import (
    CloudEventPublishingOptions,
)
from neuroglia.integration.models import IntegrationEvent
from neuroglia.mapping import Mapper
from neuroglia.mediation import CommandHandler, Mediator

log = logging.getLogger(__name__)


class CommandHandlerBase(CommandHandler):
    """Represents the base class for all services used to handle CML Worker Commands.

    Observability:
        All subclasses automatically get OTEL span enrichment via __init_subclass__.
        The TracingPipelineBehavior (registered by Observability.configure) creates the
        parent span; this base class enriches it with request dataclass field values.
    """

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        wrap_handle_async_with_enrichment(cls)

    mediator: Mediator
    """ Gets the service used to mediate calls """

    mapper: Mapper
    """ Gets the service used to map objects """

    cloud_event_bus: CloudEventBus
    """ Gets the service used to observe the cloud events consumed and produced by the application """

    cloud_event_publishing_options: CloudEventPublishingOptions
    """ Gets the options used to configure how the application should publish cloud events """

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
    ):
        self.mediator = mediator
        self.mapper = mapper
        self.cloud_event_bus = cloud_event_bus
        self.cloud_event_publishing_options = cloud_event_publishing_options

    async def publish_cloud_event_async(self, ev: IntegrationEvent) -> None:
        """Converts the specified command into a new integration event, then publishes it as a cloud event"""
        try:
            id_ = str(uuid.uuid4()).replace("-", "")
            source = self.cloud_event_publishing_options.source
            type_prefix = self.cloud_event_publishing_options.type_prefix
            type_str = f"{type_prefix}.{ev.__cloudevent__type__}"
            spec_version = CloudEventSpecVersion.v1_0
            time = datetime.datetime.now()
            subject = ev.aggregate_id
            sequencetype = None
            sequence = None
            payload = {
                "id": id_,
                "source": source,
                "type": type_str,
                "specversion": spec_version,
                "sequencetype": sequencetype,
                "sequence": sequence,
                "time": time,
                "subject": subject,
                "data": asdict(ev),
            }
            cloud_event = CloudEvent(**payload)
            self.cloud_event_bus.output_stream.on_next(cloud_event)
        except Exception as e:
            log.error(f"Failed to publish a cloudevent {ev}: Exception {e}")
