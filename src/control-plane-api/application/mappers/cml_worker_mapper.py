"""Mapper functions for CML Worker entity to DTO.

This module provides mapping between domain entities and DTOs using
Neuroglia's Mapper.map() function instead of manual dict crafting.
"""

import json
import logging

from application.dtos.cml_worker_dto import CMLWorkerDto
from domain.entities.cml_worker import CMLWorker
from domain.value_objects.worker_capacity import WorkerCapacity
from neuroglia.serialization.json import JsonSerializer

log = logging.getLogger(__name__)


def map_worker_to_dto(worker: CMLWorker) -> CMLWorkerDto:
    """Map CMLWorker aggregate to CMLWorkerDto.

    Args:
        worker: CMLWorker aggregate root

    Returns:
        CMLWorkerDto with all fields properly mapped
    """
    s = worker.state

    # Get calculated utilization
    cpu_util, mem_util, storage_util = s.metrics.get_utilization()

    # Fallback to CloudWatch if CML metrics not available
    if cpu_util is None and s.cloudwatch_cpu_utilization is not None:
        cpu_util = s.cloudwatch_cpu_utilization
    if mem_util is None and s.cloudwatch_memory_utilization is not None:
        mem_util = s.cloudwatch_memory_utilization

    # Clamp values to [0, 100]
    def _clamp(v):
        if v is None:
            return None
        try:
            fv = float(v)
        except (ValueError, TypeError):
            return None
        return max(0.0, min(100.0, fv))

    # Derive declared_capacity: use persisted value if available, otherwise
    # fall back to CML system_info hardware metrics so the frontend can show
    # fleet capacity even before the aggregate persists a capacity update.
    declared_cap = getattr(s, "declared_capacity", None)
    if declared_cap is None and hasattr(s, "metrics") and s.metrics and s.metrics.system_info:
        si = s.metrics.system_info
        if si.cpu_count and si.memory_total and si.disk_total:
            declared_cap = WorkerCapacity(
                cpu_cores=int(si.cpu_count),
                memory_gb=int(si.memory_total / (1024**3)),
                storage_gb=int(si.disk_total / (1024**3)),
                max_nodes=None,
            )

    return CMLWorkerDto(
        # Identity
        id=s.id,
        name=s.name,
        aws_region=s.aws_region,
        aws_instance_id=s.aws_instance_id,
        instance_type=getattr(s, "instance_type", "unknown"),
        state_version=s.state_version,
        # Status
        status=s.status.value,
        desired_status=s.desired_status.value,
        service_status=s.service_status.value,
        # AMI
        ami_id=s.ami_id,
        ami_name=s.ami_name,
        ami_description=s.ami_description,
        ami_creation_date=s.ami_creation_date,
        # Template
        template_name=s.template_name,
        # Network
        https_endpoint=s.https_endpoint,
        public_ip=s.public_ip,
        private_ip=s.private_ip,
        # AWS Tags
        aws_tags=s.aws_tags,
        # License
        license_status=s.license.status.value if s.license.status else None,
        license_token=s.license.token,
        cml_license_info=s.license.raw_info,
        # CML Metrics
        cml_version=s.metrics.version,
        cml_ready=s.metrics.ready,
        cml_uptime_seconds=s.metrics.uptime_seconds,
        cml_labs_count=s.metrics.labs_count,
        cml_system_info=s.metrics.system_info.to_dict() if s.metrics.system_info else None,
        cml_system_health=_serialize_system_health(s.metrics.system_health),
        cml_last_synced_at=s.metrics.last_synced_at.isoformat() if s.metrics.last_synced_at else None,
        # EC2 Metrics
        ec2_instance_state_detail=s.ec2_instance_state_detail,
        ec2_system_status_check=s.ec2_system_status_check,
        ec2_last_checked_at=s.ec2_last_checked_at.isoformat() if s.ec2_last_checked_at else None,
        # CloudWatch Metrics
        cloudwatch_cpu_utilization=s.cloudwatch_cpu_utilization,
        cloudwatch_memory_utilization=s.cloudwatch_memory_utilization,
        cloudwatch_last_collected_at=(s.cloudwatch_last_collected_at.isoformat() if s.cloudwatch_last_collected_at else None),
        cloudwatch_detailed_monitoring_enabled=s.cloudwatch_detailed_monitoring_enabled,
        # Calculated utilization
        cpu_utilization=_clamp(cpu_util),
        memory_utilization=_clamp(mem_util),
        storage_utilization=_clamp(storage_util),
        disk_utilization=_clamp(storage_util),  # Alias
        # Backward compatibility
        active_labs_count=s.metrics.labs_count,
        # Timing
        poll_interval=s.poll_interval,
        next_refresh_at=s.next_refresh_at.isoformat() if s.next_refresh_at else None,
        created_at=s.created_at.isoformat(),
        updated_at=s.updated_at.isoformat(),
        start_initiated_at=s.start_initiated_at.isoformat() if s.start_initiated_at else None,
        stop_initiated_at=s.stop_initiated_at.isoformat() if s.stop_initiated_at else None,
        terminated_at=s.terminated_at.isoformat() if s.terminated_at else None,
        created_by=s.created_by,
        # Activity tracking
        last_activity_at=s.last_activity_at.isoformat() if s.last_activity_at else None,
        last_activity_check_at=s.last_activity_check_at.isoformat() if s.last_activity_check_at else None,
        next_idle_check_at=s.next_idle_check_at.isoformat() if s.next_idle_check_at else None,
        target_pause_at=s.target_pause_at.isoformat() if s.target_pause_at else None,
        is_idle_detection_enabled=s.is_idle_detection_enabled,
        # Pause/resume tracking
        auto_pause_count=s.auto_pause_count,
        manual_pause_count=s.manual_pause_count,
        auto_resume_count=s.auto_resume_count,
        manual_resume_count=s.manual_resume_count,
        last_paused_at=s.last_paused_at.isoformat() if s.last_paused_at else None,
        last_resumed_at=s.last_resumed_at.isoformat() if s.last_resumed_at else None,
        paused_by=s.paused_by,
        pause_reason=s.pause_reason,
        # Capacity Management
        # Use getattr with defaults for fields that may not exist on workers
        # persisted before the capacity management phase was added.
        # declared_cap computed above (with system_info fallback for imported workers).
        declared_capacity=declared_cap.to_dict() if declared_cap else None,
        allocated_capacity=s.allocated_capacity.to_dict() if getattr(s, "allocated_capacity", None) else None,
        session_ids=list(getattr(s, "session_ids", None) or []),
        # Port Usage — defaults to 0; enriched by query handler via PortAllocationService
        allocated_port_count=0,
        available_port_count=0,
        port_utilization_pct=0.0,
    )


def worker_dto_to_dict(dto: CMLWorkerDto) -> dict:
    """Convert CMLWorkerDto to dict for JSON serialization.

    Args:
        dto: CMLWorkerDto instance

    Returns:
        Dictionary representation suitable for JSON serialization
    """
    # Use Neuroglia's JsonSerializer to handle complex types and Any correctly
    # This avoids the deepcopy issues with Any type in Python 3.11 that occur with dataclasses.asdict()
    serializer = JsonSerializer()
    return json.loads(serializer.serialize(dto))


def _serialize_system_health(health) -> dict | None:
    """Serialize system health to dict."""
    if not health:
        return None
    return {
        "valid": health.valid,
        "is_licensed": health.is_licensed,
        "is_enterprise": health.is_enterprise,
        "computes": health.computes,
        "controller": health.controller,
    }
