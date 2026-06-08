"""Integration event handlers package.

Contains :class:`IntegrationEventHandler` implementations for CloudEvents
received from external services. The :class:`CloudEventIngestor` discovers
the ``@cloudevent``-decorated event classes here at startup and the
:class:`Mediator` discovers the matching handlers via subclass scanning.
"""

from application.events.integration.scenario_engine_events import (
    ScenarioEngineJobCancelledIntegrationEventV1,
    ScenarioEngineJobCompletedIntegrationEventV1,
    ScenarioEngineJobFailedIntegrationEventV1,
    ScenarioEngineJobProgressIntegrationEventV1,
    ScenarioEngineJobStartedIntegrationEventV1,
)
from application.events.integration.scenario_engine_handler import (
    ScenarioEngineJobCancelledHandler,
    ScenarioEngineJobCompletedHandler,
    ScenarioEngineJobFailedHandler,
    ScenarioEngineJobProgressHandler,
    ScenarioEngineJobStartedHandler,
)

__all__ = [
    # Events
    "ScenarioEngineJobStartedIntegrationEventV1",
    "ScenarioEngineJobProgressIntegrationEventV1",
    "ScenarioEngineJobCompletedIntegrationEventV1",
    "ScenarioEngineJobFailedIntegrationEventV1",
    "ScenarioEngineJobCancelledIntegrationEventV1",
    # Handlers
    "ScenarioEngineJobStartedHandler",
    "ScenarioEngineJobProgressHandler",
    "ScenarioEngineJobCompletedHandler",
    "ScenarioEngineJobFailedHandler",
    "ScenarioEngineJobCancelledHandler",
]
