"""MongoJobRepository — MongoDB implementation of JobRepository.

Uses Neuroglia's MotorRepository with TracedRepositoryMixin for automatic
OpenTelemetry instrumentation and domain event publishing.
"""

import logging
from typing import cast

from domain.entities.job import Job, JobStatus
from domain.repositories.job_repository import JobRepository
from motor.motor_asyncio import AsyncIOMotorClient
from neuroglia.data.infrastructure.mongo import MotorRepository
from neuroglia.data.infrastructure.tracing_mixin import TracedRepositoryMixin
from neuroglia.mediation.mediator import Mediator
from neuroglia.serialization.json import JsonSerializer

log = logging.getLogger(__name__)


class MongoJobRepository(TracedRepositoryMixin, MotorRepository[Job, str], JobRepository):  # type: ignore[misc]
    """Motor-based async MongoDB repository for Job entities with automatic tracing
    and domain event publishing.

    Extends Neuroglia's MotorRepository to inherit standard CRUD operations with
    automatic event publishing and adds Job-specific queries.
    """

    def __init__(
        self,
        client: AsyncIOMotorClient,
        database_name: str,
        collection_name: str,
        serializer: JsonSerializer,
        entity_type: type[Job] | None = None,
        mediator: Mediator | None = None,
    ):
        super().__init__(
            client=client,
            database_name=database_name,
            collection_name=collection_name,
            serializer=serializer,
            entity_type=entity_type,
            mediator=mediator,
        )

    async def get_by_id_async(self, job_id: str) -> Job | None:
        """Retrieve a Job by its aggregate ID."""
        return cast(Job | None, await self.get_async(job_id))

    async def add_async(self, job: Job) -> Job:  # type: ignore[override]
        """Add a new Job."""
        return cast(Job, await super().add_async(job))

    async def update_async(self, job: Job) -> Job:  # type: ignore[override]
        """Update an existing Job."""
        return cast(Job, await super().update_async(job))

    async def list_async(self, limit: int = 100) -> list[Job]:
        """List recent jobs ordered by created_at descending."""
        cursor = self.collection.find({}).sort("created_at", -1).limit(limit)
        jobs: list[Job] = []
        async for document in cursor:
            job = self._deserialize_entity(document)
            jobs.append(job)
        return jobs

    async def find_by_status_async(self, status: JobStatus) -> list[Job]:
        """Find all jobs with a given status."""
        cursor = self.collection.find({"status": status.value})
        jobs: list[Job] = []
        async for document in cursor:
            job = self._deserialize_entity(document)
            jobs.append(job)
        return jobs
