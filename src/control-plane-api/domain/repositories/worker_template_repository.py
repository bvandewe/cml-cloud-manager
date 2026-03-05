"""Abstract repository for WorkerTemplate entities.

Defines the contract for persisting and querying WorkerTemplate aggregates.
Templates are seeded from YAML configuration and stored in MongoDB for
consistent worker provisioning across the cluster.
"""

from abc import ABC, abstractmethod

from domain.entities.worker_template import WorkerTemplate
from domain.value_objects.worker_capacity import WorkerCapacity


class WorkerTemplateRepository(ABC):
    """Abstract repository for WorkerTemplate entities.

    WorkerTemplates are configuration-managed entities seeded from YAML.
    The repository supports queries for template selection based on
    capacity requirements and scheduling optimization.
    """

    @abstractmethod
    async def get_by_id_async(self, template_id: str) -> WorkerTemplate | None:
        """Retrieve a WorkerTemplate by its aggregate ID.

        Args:
            template_id: The unique aggregate identifier

        Returns:
            The WorkerTemplate if found, None otherwise
        """
        pass

    @abstractmethod
    async def get_by_name_async(self, name: str) -> WorkerTemplate | None:
        """Retrieve a WorkerTemplate by its unique name.

        This is the primary lookup method as template names are unique.

        Args:
            name: The template name (e.g., "small", "medium", "large")

        Returns:
            The WorkerTemplate if found, None otherwise
        """
        pass

    @abstractmethod
    async def list_enabled_async(self) -> list[WorkerTemplate]:
        """Retrieve all enabled WorkerTemplates.

        Returns:
            List of enabled WorkerTemplates, ordered by cost (ascending)
        """
        pass

    @abstractmethod
    async def list_all_async(self) -> list[WorkerTemplate]:
        """Retrieve all WorkerTemplates including disabled ones.

        Returns:
            List of all WorkerTemplates
        """
        pass

    @abstractmethod
    async def find_matching_templates_async(
        self,
        required_capacity: WorkerCapacity,
    ) -> list[WorkerTemplate]:
        """Find enabled templates that can satisfy the required capacity.

        Args:
            required_capacity: Minimum capacity requirements

        Returns:
            List of matching templates, ordered by cost (ascending)
        """
        pass

    @abstractmethod
    async def add_async(self, entity: WorkerTemplate) -> WorkerTemplate:
        """Add a new WorkerTemplate.

        Args:
            entity: The WorkerTemplate to add

        Returns:
            The added WorkerTemplate with any generated fields
        """
        pass

    @abstractmethod
    async def update_async(self, entity: WorkerTemplate) -> WorkerTemplate:
        """Update an existing WorkerTemplate.

        Args:
            entity: The WorkerTemplate to update

        Returns:
            The updated WorkerTemplate
        """
        pass

    @abstractmethod
    async def upsert_by_name_async(self, entity: WorkerTemplate) -> WorkerTemplate:
        """Upsert a WorkerTemplate by name.

        If a template with the same name exists, updates it.
        Otherwise, creates a new template.

        This is used for seeding templates from YAML configuration.

        Args:
            entity: The WorkerTemplate to upsert

        Returns:
            The upserted WorkerTemplate
        """
        pass

    @abstractmethod
    async def delete_async(self, template_id: str) -> bool:
        """Delete a WorkerTemplate.

        Args:
            template_id: The template ID to delete

        Returns:
            True if deleted, False if not found
        """
        pass
