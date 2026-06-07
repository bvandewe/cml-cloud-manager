"""JobRepository — abstract repository interface for Job aggregates."""

from abc import ABC, abstractmethod

from domain.entities.job import Job, JobStatus


class JobRepository(ABC):
    """Abstract repository for Job persistence.

    Implementations: MongoJobRepository (integration layer).
    """

    @abstractmethod
    async def get_by_id_async(self, job_id: str) -> Job | None:
        """Retrieve a job by its ID."""
        ...

    @abstractmethod
    async def add_async(self, job: Job) -> None:
        """Persist a new job."""
        ...

    @abstractmethod
    async def update_async(self, job: Job) -> None:
        """Update an existing job."""
        ...

    @abstractmethod
    async def list_async(self, limit: int = 100) -> list[Job]:
        """List recent jobs."""
        ...

    @abstractmethod
    async def find_by_status_async(self, status: JobStatus) -> list[Job]:
        """Find all jobs with a given status."""
        ...
