"""CloudEventPublisher — standalone integration event publisher.

ADR-042: Extracted from CommandHandlerBase to adhere to ISP.
Only handlers that actually emit integration events should inject this service.

Previously, all 73 command handlers carried CloudEventBus and
CloudEventPublishingOptions dependencies even though only 1 handler
(UpdatePipelineProgressCommandHandler) ever published cloud events.
"""

import datetime
import logging
import uuid
from dataclasses import asdict

from neuroglia.eventing.cloud_events.cloud_event import (
    CloudEvent,
    CloudEventSpecVersion,
)
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import (
    CloudEventPublishingOptions,
)
from neuroglia.integration.models import IntegrationEvent

log = logging.getLogger(__name__)


class CloudEventPublisher:
    """Publishes integration events as CloudEvents to the event bus.

    Extracted from CommandHandlerBase (ADR-042) so only handlers that
    actually emit integration events need to depend on this service.
    """

    def __init__(
        self,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
    ):
        self._cloud_event_bus = cloud_event_bus
        self._cloud_event_publishing_options = cloud_event_publishing_options

    async def publish_async(self, ev: IntegrationEvent) -> None:
        """Convert an IntegrationEvent to a CloudEvent and publish it.

        Args:
            ev: The integration event to publish. Must have an
                ``__cloudevent__type__`` attribute and an ``aggregate_id``.
        """
        try:
            id_ = str(uuid.uuid4()).replace("-", "")
            source = self._cloud_event_publishing_options.source
            type_prefix = self._cloud_event_publishing_options.type_prefix
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
            self._cloud_event_bus.output_stream.on_next(cloud_event)
        except Exception as e:
            log.error(f"Failed to publish a cloudevent {ev}: Exception {e}")
