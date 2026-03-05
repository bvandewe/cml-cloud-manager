"""WorkerTemplate Data Transfer Objects for API responses."""

from dataclasses import dataclass

from domain.entities.worker_template import WorkerTemplate


@dataclass
class WorkerCapacityDto:
    """DTO for worker capacity specification."""

    cpu_cores: int
    memory_gb: int
    storage_gb: int
    max_nodes: int | None


@dataclass
class WorkerTemplateCreatedDto:
    """DTO returned after creating a WorkerTemplate."""

    id: str
    name: str
    description: str
    instance_type: str
    enabled: bool
    created_at: str


@dataclass
class WorkerTemplateSummaryDto:
    """Summary DTO for list queries — lightweight representation."""

    id: str
    name: str
    description: str
    instance_type: str
    capacity: WorkerCapacityDto
    cost_per_hour_usd: float
    enabled: bool
    deleted: bool
    updated_at: str


@dataclass
class WorkerTemplateDto:
    """Full DTO for single WorkerTemplate retrieval."""

    id: str
    name: str
    description: str
    instance_type: str
    ami_name_pattern: str
    capacity: WorkerCapacityDto
    cost_per_hour_usd: float
    enabled: bool
    deleted: bool
    deleted_at: str | None
    created_at: str
    updated_at: str


def map_worker_template_to_dto(entity: WorkerTemplate) -> WorkerTemplateDto:
    """Map a WorkerTemplate entity to its full DTO representation.

    Args:
        entity: The WorkerTemplate aggregate

    Returns:
        WorkerTemplateDto with all fields populated
    """
    state = entity.state
    return WorkerTemplateDto(
        id=state.id,
        name=state.name,
        description=state.description,
        instance_type=state.instance_type.value,
        ami_name_pattern=state.ami_name_pattern,
        capacity=WorkerCapacityDto(
            cpu_cores=state.capacity.cpu_cores,
            memory_gb=state.capacity.memory_gb,
            storage_gb=state.capacity.storage_gb,
            max_nodes=state.capacity.max_nodes,
        ),
        cost_per_hour_usd=state.cost_per_hour_usd,
        enabled=state.enabled,
        deleted=state.deleted,
        deleted_at=state.deleted_at.isoformat() if state.deleted_at else None,
        created_at=state.created_at.isoformat(),
        updated_at=state.updated_at.isoformat(),
    )


def map_worker_template_to_summary_dto(entity: WorkerTemplate) -> WorkerTemplateSummaryDto:
    """Map a WorkerTemplate entity to a summary DTO for lists.

    Args:
        entity: The WorkerTemplate aggregate

    Returns:
        WorkerTemplateSummaryDto with essential fields
    """
    state = entity.state
    return WorkerTemplateSummaryDto(
        id=state.id,
        name=state.name,
        description=state.description,
        instance_type=state.instance_type.value,
        capacity=WorkerCapacityDto(
            cpu_cores=state.capacity.cpu_cores,
            memory_gb=state.capacity.memory_gb,
            storage_gb=state.capacity.storage_gb,
            max_nodes=state.capacity.max_nodes,
        ),
        cost_per_hour_usd=state.cost_per_hour_usd,
        enabled=state.enabled,
        deleted=state.deleted,
        updated_at=state.updated_at.isoformat(),
    )
