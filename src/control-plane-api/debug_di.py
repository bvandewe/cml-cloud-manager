from application.services.worker_template_service import WorkerTemplateService
from application.settings import Settings
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from main import create_app
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Mediator

app = create_app()
provider = app.state.services
# we must use a scoped provider for scoped services
scope = provider.create_scope()
scoped_provider = scope.get_service_provider()

dependencies = [
    Mediator,
    Mapper,
    CloudEventBus,
    CloudEventPublishingOptions,
    CMLWorkerRepository,
    WorkerTemplateService,
    Settings,
]

for dep in dependencies:
    print(f"\nResolving: {dep.__name__}...")
    try:
        instance = scoped_provider.get_service(dep)
        print(f"  Success: {type(instance)}")
    except Exception as e:
        print(f"  Failed: {e}")
        import traceback

        traceback.print_exc(limit=4)
