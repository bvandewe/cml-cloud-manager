"""MongoDB repository for WorkerTemplate entities using Neuroglia's MotorRepository.

This extends the framework's MotorRepository to provide WorkerTemplate-specific queries
while inheriting all standard CRUD operations with automatic domain event publishing.
"""

import logging
from typing import TYPE_CHECKING, Optional, cast

from domain.entities.worker_template import WorkerTemplate
from domain.repositories.worker_template_repository import WorkerTemplateRepository
from domain.value_objects.worker_capacity import WorkerCapacity
from motor.motor_asyncio import AsyncIOMotorClient
from neuroglia.data.infrastructure.mongo import MotorRepository
from neuroglia.data.infrastructure.tracing_mixin import TracedRepositoryMixin
from neuroglia.serialization.json import JsonSerializer

if TYPE_CHECKING:
    from neuroglia.mediation.mediator import Mediator

log = logging.getLogger(__name__)


class MongoWorkerTemplateRepository(TracedRepositoryMixin, MotorRepository[WorkerTemplate, str], WorkerTemplateRepository):  # type: ignore[misc]
    """Motor-based async MongoDB repository for WorkerTemplate entities with automatic tracing
    and domain event publishing.

    Extends Neuroglia's MotorRepository to inherit standard CRUD operations with
    automatic event publishing and adds WorkerTemplate-specific queries.
    """

    def __init__(
        self,
        client: AsyncIOMotorClient,
        database_name: str,
        collection_name: str,
        serializer: JsonSerializer,
        entity_type: type[WorkerTemplate] | None = None,
        mediator: Optional["Mediator"] = None,
    ):
        """Initialize the WorkerTemplate repository.

        Args:
            client: Motor async MongoDB client
            database_name: Name of the MongoDB database
            collection_name: Name of the collection (typically "worker_templates")
            serializer: JSON serializer for entity conversion
            entity_type: Optional entity type (WorkerTemplate)
            mediator: Optional Mediator for automatic domain event publishing
        """
        super().__init__(
            client=client,
            database_name=database_name,
            collection_name=collection_name,
            serializer=serializer,
            entity_type=entity_type,
            mediator=mediator,
        )
        self._indexes_initialized: bool = False

    async def _ensure_indexes(self) -> None:
        """Ensure required indexes exist for the collection."""
        if self._indexes_initialized:
            return

        try:
            # Unique index on name
            await self.collection.create_index(
                "name",
                unique=True,
                name="idx_name_unique",
            )

            # Index for enabled queries
            await self.collection.create_index("enabled", name="idx_enabled")

            # Compound index for capacity-based queries
            await self.collection.create_index(
                [
                    ("enabled", 1),
                    ("capacity.cpu_cores", 1),
                    ("capacity.memory_gb", 1),
                    ("cost_per_hour_usd", 1),
                ],
                name="idx_capacity_cost",
            )

            log.debug("WorkerTemplate indexes created successfully")
        except Exception:
            log.warning("Failed to create WorkerTemplate indexes", exc_info=True)
        finally:
            self._indexes_initialized = True

    async def get_by_id_async(self, template_id: str) -> WorkerTemplate | None:
        """Retrieve a WorkerTemplate by its aggregate ID."""
        return cast(WorkerTemplate | None, await self.get_async(template_id))

    async def get_by_name_async(self, name: str) -> WorkerTemplate | None:
        """Retrieve a WorkerTemplate by its unique name.

        Args:
            name: The template name (e.g., "small", "medium", "large")

        Returns:
            The WorkerTemplate if found, None otherwise
        """
        await self._ensure_indexes()
        document = await self.collection.find_one({"name": name})
        if document:
            return self._deserialize_entity(document)
        return None

    async def list_enabled_async(self) -> list[WorkerTemplate]:
        """Retrieve all enabled WorkerTemplates, ordered by cost."""
        await self._ensure_indexes()
        cursor = self.collection.find({"enabled": True}).sort("cost_per_hour_usd", 1)
        return [self._deserialize_entity(doc) async for doc in cursor]

    async def list_all_async(self) -> list[WorkerTemplate]:
        """Retrieve all WorkerTemplates."""
        await self._ensure_indexes()
        cursor = self.collection.find({}).sort("name", 1)
        return [self._deserialize_entity(doc) async for doc in cursor]

    async def find_matching_templates_async(
        self,
        required_capacity: WorkerCapacity,
    ) -> list[WorkerTemplate]:
        """Find enabled templates that can satisfy the required capacity.

        Uses MongoDB query to filter by minimum capacity requirements,
        then orders by cost for scheduling optimization.

        Args:
            required_capacity: Minimum capacity requirements

        Returns:
            List of matching templates, ordered by cost (ascending)
        """
        await self._ensure_indexes()

        query = {
            "enabled": True,
            "capacity.cpu_cores": {"$gte": required_capacity.cpu_cores},
            "capacity.memory_gb": {"$gte": required_capacity.memory_gb},
            "capacity.storage_gb": {"$gte": required_capacity.storage_gb},
        }

        # Add max_nodes constraint if specified
        if required_capacity.max_nodes is not None:
            query["$or"] = [
                {"capacity.max_nodes": {"$gte": required_capacity.max_nodes}},
                {"capacity.max_nodes": None},  # Templates without max_nodes limit
            ]

        cursor = self.collection.find(query).sort("cost_per_hour_usd", 1)
        return [self._deserialize_entity(doc) async for doc in cursor]

    async def add_async(self, entity: WorkerTemplate) -> WorkerTemplate:
        """Add a new WorkerTemplate."""
        await self._ensure_indexes()
        return cast(WorkerTemplate, await super().add_async(entity))

    async def update_async(self, entity: WorkerTemplate) -> WorkerTemplate:
        """Update an existing WorkerTemplate."""
        await self._ensure_indexes()
        return cast(WorkerTemplate, await super().update_async(entity))

    async def upsert_by_name_async(self, entity: WorkerTemplate) -> WorkerTemplate:
        """Upsert a WorkerTemplate by name.

        If a template with the same name exists, updates it.
        Otherwise, creates a new template.

        Args:
            entity: The WorkerTemplate to upsert

        Returns:
            The upserted WorkerTemplate
        """
        await self._ensure_indexes()

        existing = await self.get_by_name_async(entity.state.name)
        if existing:
            # Update existing template
            existing.update(
                description=entity.state.description,
                instance_type=entity.state.instance_type,
                capacity=entity.state.capacity,
                ami_name_pattern=entity.state.ami_name_pattern,
                cost_per_hour_usd=entity.state.cost_per_hour_usd,
                enabled=entity.state.enabled,
            )
            return await self.update_async(existing)
        else:
            # Add new template
            return await self.add_async(entity)

    async def delete_async(self, template_id: str) -> bool:
        """Delete a WorkerTemplate."""
        await self._ensure_indexes()
        result = await self.collection.delete_one({"_id": template_id})
        return result.deleted_count > 0

    def _deserialize_entity(self, document: dict) -> WorkerTemplate:
        """Deserialize a MongoDB document to a WorkerTemplate entity.

        Handles the nested WorkerCapacity value object and Ec2InstanceType enum.
        """
        from integration.enums import Ec2InstanceType

        template = WorkerTemplate()
        template.state.id = document.get("_id", document.get("id", ""))
        template.state.name = document.get("name", "")
        template.state.description = document.get("description", "")

        # Handle instance_type enum
        instance_type_value = document.get("instance_type", "small")
        if isinstance(instance_type_value, str):
            template.state.instance_type = Ec2InstanceType(instance_type_value)
        else:
            template.state.instance_type = instance_type_value

        template.state.ami_name_pattern = document.get("ami_name_pattern", "cisco-cml2.9*")

        # Handle nested capacity value object
        capacity_data = document.get("capacity", {})
        if capacity_data:
            template.state.capacity = WorkerCapacity.from_dict(capacity_data)
        else:
            template.state.capacity = WorkerCapacity.zero()

        template.state.cost_per_hour_usd = document.get("cost_per_hour_usd", 0.0)
        template.state.enabled = document.get("enabled", True)

        # Handle datetime fields
        from datetime import datetime, timezone

        created_at = document.get("created_at")
        if isinstance(created_at, str):
            template.state.created_at = datetime.fromisoformat(created_at)
        elif isinstance(created_at, datetime):
            template.state.created_at = created_at
        else:
            template.state.created_at = datetime.now(timezone.utc)

        updated_at = document.get("updated_at")
        if isinstance(updated_at, str):
            template.state.updated_at = datetime.fromisoformat(updated_at)
        elif isinstance(updated_at, datetime):
            template.state.updated_at = updated_at
        else:
            template.state.updated_at = datetime.now(timezone.utc)

        # Set state version for optimistic concurrency
        template.state.state_version = document.get("state_version", 0)

        return template
