"""Generic Database Seeder for YAML-based initialization.

This module provides a reusable HostedService that seeds aggregates
from YAML files at application startup.

Seeding Strategy: "Seed-only" via Repository
- Creates aggregates that don't exist (by ID) in the database
- Does NOT update existing aggregates (idempotent)
- Domain events are published via CloudEventPublisher for external consumers

FOLDER STRUCTURE:
    data/seeds/
    ├── {entity_type_1}/
    │   ├── entity1.yaml
    │   └── entity2.yaml
    ├── {entity_type_2}/
    │   └── ...
    └── ...

Each entity is stored as an individual YAML file.
Files can be organized in subfolders for complex hierarchies (recursive search).

Usage:
    from lcm_core.infrastructure.seeding import DatabaseSeeder, DatabaseSeederService

    # In main.py:
    seeds_dir = Path(__file__).parent / "data" / "seeds"
    DatabaseSeederService.configure(
        builder,
        seeds_dir=seeds_dir,
        entity_seeders=[
            MyEntitySeeder(),  # Implements EntitySeeder protocol
        ]
    )
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generic, TypeVar

import yaml  # type: ignore[import-untyped]
from neuroglia.data.infrastructure.abstractions import Repository
from neuroglia.dependency_injection import ServiceProviderBase
from neuroglia.hosting.abstractions import HostedService

if TYPE_CHECKING:
    from neuroglia.hosting.web import WebApplicationBuilder

logger = logging.getLogger(__name__)

T = TypeVar("T")  # Entity type


@dataclass
class SeedResult:
    """Result of seeding a single entity type."""

    entity_type: str
    seeded_count: int = 0
    skipped_count: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total_processed(self) -> int:
        """Total files processed (seeded + skipped)."""
        return self.seeded_count + self.skipped_count

    @property
    def has_errors(self) -> bool:
        """Check if any errors occurred."""
        return len(self.errors) > 0


@dataclass
class SeedSummary:
    """Summary of all seeding operations."""

    results: dict[str, SeedResult] = field(default_factory=dict)
    total_seeded: int = 0
    total_skipped: int = 0
    total_errors: int = 0

    def add_result(self, result: SeedResult) -> None:
        """Add a seed result to the summary."""
        self.results[result.entity_type] = result
        self.total_seeded += result.seeded_count
        self.total_skipped += result.skipped_count
        self.total_errors += len(result.errors)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/API response."""
        return {
            "entities": {
                name: {
                    "seeded": result.seeded_count,
                    "skipped": result.skipped_count,
                    "errors": result.errors,
                }
                for name, result in self.results.items()
            },
            "total_seeded": self.total_seeded,
            "total_skipped": self.total_skipped,
            "total_errors": self.total_errors,
        }


class EntitySeeder(ABC, Generic[T]):
    """Protocol for entity-specific seeding logic.

    Implement this class for each aggregate type you want to seed.
    The DatabaseSeeder will call these methods in order.

    Example:
        class WorkerTemplateSeeder(EntitySeeder[WorkerTemplate]):
            @property
            def entity_type(self) -> str:
                return "worker_templates"

            @property
            def folder_name(self) -> str:
                return "worker_templates"

            def get_repository(self, sp: ServiceProviderBase) -> Repository[WorkerTemplate, str]:
                return sp.get_required_service(Repository[WorkerTemplate, str])

            def create_entity(self, data: dict[str, Any]) -> WorkerTemplate:
                return WorkerTemplate(
                    name=data["name"],
                    instance_type=data["instance_type"],
                    ...
                )

            def get_entity_id(self, data: dict[str, Any]) -> str:
                return data.get("name") or data.get("id")
    """

    @property
    @abstractmethod
    def entity_type(self) -> str:
        """Human-readable name for this entity type (used in logging/results)."""
        ...

    @property
    @abstractmethod
    def folder_name(self) -> str:
        """Folder name under seeds_dir containing YAML files for this entity."""
        ...

    @property
    def recursive(self) -> bool:
        """Whether to search subfolders recursively. Default: False."""
        return False

    @property
    def seeding_order(self) -> int:
        """Order in which to seed (lower = earlier). Default: 100."""
        return 100

    @abstractmethod
    def get_repository(self, scoped_provider: Any) -> Repository[Any, str]:
        """Get the repository for this entity type.

        Args:
            scoped_provider: Scoped service provider with repositories

        Returns:
            Repository instance for this entity type
        """
        ...

    @abstractmethod
    def create_entity(self, data: dict[str, Any]) -> T:
        """Create an entity from YAML data.

        Args:
            data: Parsed YAML data dictionary

        Returns:
            Entity instance ready to be persisted
        """
        ...

    @abstractmethod
    def get_entity_id(self, data: dict[str, Any]) -> str | None:
        """Extract the entity ID from YAML data.

        Args:
            data: Parsed YAML data dictionary

        Returns:
            Entity ID string, or None if invalid/missing
        """
        ...

    def validate_data(self, data: dict[str, Any]) -> list[str]:
        """Validate YAML data before creating entity.

        Override to add custom validation.

        Args:
            data: Parsed YAML data dictionary

        Returns:
            List of validation error messages (empty if valid)
        """
        return []

    def post_create(self, entity: T, data: dict[str, Any]) -> None:
        """Called after entity is created but before save.

        Override to add related data (e.g., nested collections).

        Args:
            entity: The created entity
            data: Original YAML data dictionary
        """
        pass

    async def entity_exists_async(
        self,
        entity_id: str,
        data: dict[str, Any],
        repository: Repository[Any, str],
    ) -> bool:
        """Check if entity already exists (for duplicate detection).

        Override to customize existence check (e.g., by name+version instead of ID).
        Default implementation uses repository.get_async(entity_id).

        Args:
            entity_id: The entity ID extracted from YAML
            data: Original YAML data dictionary
            repository: The repository for this entity type

        Returns:
            True if entity exists, False otherwise
        """
        existing = await repository.get_async(entity_id)
        return existing is not None


class DatabaseSeeder:
    """Generic seeder for aggregates from YAML files.

    This service seeds aggregates from YAML files at startup:
    - Creates aggregates via Repository[T, str]
    - Domain events are published via CloudEventPublisher for external consumers
    - Skips existing entities (idempotent)

    Folder Structure:
        Each entity type has its own folder under seeds_dir.
        Each entity is stored as an individual YAML file.
    """

    def __init__(
        self,
        service_provider: ServiceProviderBase,
        seeds_dir: str | Path,
        entity_seeders: list["EntitySeeder[Any]"],
    ) -> None:
        """Initialize the database seeder.

        Args:
            service_provider: The root service provider for creating scopes
            seeds_dir: Directory containing seed folders
            entity_seeders: List of EntitySeeder implementations
        """
        self._service_provider = service_provider
        self._seeds_dir = Path(seeds_dir)
        self._entity_seeders = sorted(entity_seeders, key=lambda s: s.seeding_order)

        logger.debug(f"DatabaseSeeder initialized with seeds_dir: {self._seeds_dir}")
        logger.debug(f"Entity seeders: {[s.entity_type for s in self._entity_seeders]}")

    def _get_yaml_files(self, folder_name: str, recursive: bool = False) -> list[Path]:
        """Get all YAML files from an entity folder.

        Args:
            folder_name: Name of the folder (e.g., 'worker_templates')
            recursive: If True, search subfolders recursively

        Returns:
            List of Path objects for .yaml and .yml files, sorted by name
        """
        folder = self._seeds_dir / folder_name
        if not folder.exists():
            logger.debug(f"Seed folder does not exist: {folder}")
            return []

        if recursive:
            yaml_files = list(folder.glob("**/*.yaml")) + list(folder.glob("**/*.yml"))
        else:
            yaml_files = list(folder.glob("*.yaml")) + list(folder.glob("*.yml"))

        return sorted(yaml_files)

    def _load_yaml_file(self, file_path: Path) -> dict[str, Any] | None:
        """Load and parse a YAML file.

        Args:
            file_path: Path to the YAML file

        Returns:
            Parsed YAML data as dict, or None on error
        """
        try:
            with open(file_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
                # Handle single-document YAML
                if isinstance(data, dict):
                    return data
                # Handle multi-document YAML (return first doc)
                if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                    return data[0]
                return {}
        except Exception as e:
            logger.error(f"Error loading YAML file {file_path}: {e}")
            return None

    async def seed_all_async(self) -> SeedSummary:
        """Seed all entity types from YAML files.

        Uses a scoped service provider to access repositories.
        Seeding is done in order specified by EntitySeeder.seeding_order.

        Returns:
            SeedSummary with counts for each entity type
        """
        summary = SeedSummary()

        if not self._seeds_dir.exists():
            logger.warning(f"Seeds directory does not exist: {self._seeds_dir}")
            return summary

        # Create a scope for repository access
        async with self._service_provider.create_async_scope() as scoped_provider:  # type: ignore[no-untyped-call]
            for seeder in self._entity_seeders:
                result = await self._seed_entity_type_async(seeder, scoped_provider)
                summary.add_result(result)

        logger.info(f"Seeding complete: {summary.to_dict()}")
        return summary

    async def _seed_entity_type_async(
        self,
        seeder: EntitySeeder[T],
        scoped_provider: Any,
    ) -> SeedResult:
        """Seed a single entity type from YAML files.

        Args:
            seeder: EntitySeeder implementation for this type
            scoped_provider: Scoped service provider with repositories

        Returns:
            SeedResult with counts
        """
        result = SeedResult(seeder.entity_type)
        yaml_files = self._get_yaml_files(seeder.folder_name, recursive=seeder.recursive)

        if not yaml_files:
            logger.debug(f"No YAML files found in {seeder.folder_name}/ folder")
            return result

        try:
            repository = seeder.get_repository(scoped_provider)
        except Exception as e:
            error_msg = f"Failed to get repository for {seeder.entity_type}: {e}"
            logger.error(error_msg)
            result.errors.append(error_msg)
            return result

        for yaml_file in yaml_files:
            try:
                data = self._load_yaml_file(yaml_file)
                if data is None:
                    result.errors.append(f"Failed to load {yaml_file.name}")
                    continue

                entity_id = seeder.get_entity_id(data)
                if not entity_id:
                    result.errors.append(f"File {yaml_file.name} missing ID field")
                    continue

                # Validate data
                validation_errors = seeder.validate_data(data)
                if validation_errors:
                    for error in validation_errors:
                        result.errors.append(f"{yaml_file.name}: {error}")
                    continue

                # Check if exists (uses seeder's custom logic if overridden)
                exists = await seeder.entity_exists_async(entity_id, data, repository)
                if exists:
                    logger.debug(f"{seeder.entity_type} already exists, skipping: {entity_id}")
                    result.skipped_count += 1
                    continue

                # Create and save entity
                entity = seeder.create_entity(data)
                seeder.post_create(entity, data)
                await repository.add_async(entity)
                result.seeded_count += 1
                logger.info(f"Seeded {seeder.entity_type}: {entity_id}")

            except Exception as e:
                error_msg = f"Error seeding {seeder.entity_type} from {yaml_file.name}: {e}"
                logger.error(error_msg)
                result.errors.append(error_msg)

        return result


# Module-level singleton for access by other modules
_database_seeder: DatabaseSeeder | None = None


def get_database_seeder() -> DatabaseSeeder:
    """Get the singleton database seeder instance.

    Returns:
        The DatabaseSeeder singleton

    Raises:
        RuntimeError: If seeder not initialized
    """
    if _database_seeder is None:
        raise RuntimeError("DatabaseSeeder not initialized.")
    return _database_seeder


def set_database_seeder(seeder: DatabaseSeeder) -> None:
    """Set the singleton database seeder.

    Called during application configuration.

    Args:
        seeder: The DatabaseSeeder instance to set as singleton
    """
    global _database_seeder
    _database_seeder = seeder


class DatabaseSeederService(HostedService):
    """Hosted service that seeds the database on startup.

    Implements HostedService for automatic lifecycle management:
    - start_async(): Called on application startup to seed aggregates
    - stop_async(): Called on application shutdown (cleanup if needed)

    Usage:
        seeds_dir = Path(__file__).parent / "data" / "seeds"
        DatabaseSeederService.configure(
            builder,
            seeds_dir=seeds_dir,
            entity_seeders=[WorkerTemplateSeeder(), ...]
        )
    """

    def __init__(self, service_provider: ServiceProviderBase) -> None:
        """Initialize the database seeder service.

        Args:
            service_provider: The root service provider for accessing DI container
        """
        self._service_provider = service_provider
        self._initialized = False
        self._seed_summary: SeedSummary | None = None

    @property
    def seed_summary(self) -> SeedSummary | None:
        """Get the results from the most recent seeding operation."""
        return self._seed_summary

    @property
    def initialized(self) -> bool:
        """Check if seeding completed successfully."""
        return self._initialized

    async def start_async(self) -> None:
        """Start the service by seeding the database.

        Called automatically by the Neuroglia host during application startup.
        Seeds aggregates from YAML files via the Repository.
        """
        try:
            logger.info("🌱 DatabaseSeederService starting...")

            # Get the DatabaseSeeder from DI container
            seeder: DatabaseSeeder = self._service_provider.get_required_service(DatabaseSeeder)
            self._seed_summary = await seeder.seed_all_async()
            self._initialized = True

            if self._seed_summary is not None:
                summary_dict = self._seed_summary.to_dict()
                logger.info(
                    f"✅ DatabaseSeederService started: " f"{summary_dict['total_seeded']} entities seeded, " f"{summary_dict['total_skipped']} skipped, " f"{summary_dict['total_errors']} errors"
                )

        except Exception as e:
            logger.error(f"❌ DatabaseSeederService failed to start: {e}")
            import traceback

            logger.debug(traceback.format_exc())
            # Don't raise - allow app to start even if seeding fails
            self._initialized = False

    async def stop_async(self) -> None:
        """Stop the service.

        Called automatically by the Neuroglia host during application shutdown.
        """
        logger.info("✅ DatabaseSeederService stopped")

    @staticmethod
    def configure(
        builder: "WebApplicationBuilder",
        seeds_dir: str | Path,
        entity_seeders: "list[EntitySeeder[Any]]",
    ) -> "WebApplicationBuilder":
        """Configure the DatabaseSeederService.

        Args:
            builder: The WebApplicationBuilder to configure
            seeds_dir: Directory containing seed YAML files
            entity_seeders: List of EntitySeeder implementations

        Returns:
            The builder instance for fluent chaining
        """
        logger.info(f"🔧 Configuring DatabaseSeederService with seeds_dir: {seeds_dir}")
        logger.info(f"   Entity seeders: {[s.entity_type for s in entity_seeders]}")

        def create_seeder(sp: ServiceProviderBase) -> DatabaseSeeder:
            """Factory to create DatabaseSeeder with service provider access."""
            seeder = DatabaseSeeder(
                service_provider=sp,
                seeds_dir=seeds_dir,
                entity_seeders=entity_seeders,
            )
            set_database_seeder(seeder)
            return seeder

        # Register seeder singleton
        builder.services.add_singleton(DatabaseSeeder, implementation_factory=create_seeder)

        # Register hosted service for automatic lifecycle management
        # IMPORTANT: Set return type annotation to concrete class to avoid Neuroglia DI deduplication bug
        def seeder_service_factory(sp: ServiceProviderBase) -> DatabaseSeederService:
            return DatabaseSeederService(sp)

        seeder_service_factory.__annotations__["return"] = DatabaseSeederService
        builder.services.add_singleton(DatabaseSeederService, implementation_factory=seeder_service_factory)

        # Also register as generic HostedService for discovery
        # IMPORTANT: Use concrete return type to avoid deduplication
        def hosted_service_factory(sp: ServiceProviderBase) -> HostedService:
            return sp.get_required_service(DatabaseSeederService)

        hosted_service_factory.__annotations__["return"] = DatabaseSeederService
        builder.services.add_singleton(HostedService, implementation_factory=hosted_service_factory)

        logger.info("✅ DatabaseSeederService configured")
        return builder
