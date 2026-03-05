"""Placement Engine for LabletSession scheduling.

Implements the bin-packing algorithm to select the best CML worker
for hosting a LabletSession based on resource requirements, license
affinity, and worker utilization.

Key Concepts:
- Filter: Eliminate workers that cannot host the instance
- Score: Rank remaining workers by utilization (prefer fuller workers)
- Select: Choose the best candidate

Filtering Criteria:
1. License affinity (license_type matches definition requirements)
2. Resource requirements (cpu, memory, storage)
3. AMI requirements (CML version, node definitions)
4. Available capacity (not exceeding declared limits)
5. Available ports (enough for port template)
6. Status (exclude DRAINING/STOPPING/STOPPED workers)
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from lcm_core.domain.enums import CMLWorkerStatus

logger = logging.getLogger(__name__)


@dataclass
class CandidateScore:
    """A scored candidate worker from the placement algorithm.

    Attributes:
        worker_id: Worker identifier
        worker_name: Human-readable worker name
        score: Combined bin-packing score (0.0–1.0+)
        cpu_utilization: Current CPU utilization ratio (0.0–1.0)
        memory_utilization: Current memory utilization ratio (0.0–1.0)
        session_count: Number of sessions currently assigned
        locality_bonus: Bonus applied for session co-location
    """

    worker_id: str
    worker_name: str
    score: float
    cpu_utilization: float = 0.0
    memory_utilization: float = 0.0
    session_count: int = 0
    locality_bonus: float = 0.0


@dataclass
class WorkerRejection:
    """Reason a specific worker was rejected during filtering.

    Attributes:
        worker_id: Worker identifier
        worker_name: Human-readable worker name
        reason_category: Category of rejection (status, license, capacity, ami, ports)
        reason_detail: Human-readable explanation of why this worker failed
    """

    worker_id: str
    worker_name: str
    reason_category: str
    reason_detail: str


@dataclass
class UtilizationForecast:
    """Estimated resource utilization on the selected worker after placement.

    Attributes:
        worker_id: Selected worker identifier
        worker_name: Human-readable worker name
        cpu_percent_before: CPU utilization % before placement
        cpu_percent_after: CPU utilization % after placement
        memory_percent_before: Memory utilization % before placement
        memory_percent_after: Memory utilization % after placement
        storage_percent_before: Storage utilization % before placement
        storage_percent_after: Storage utilization % after placement
        session_count_before: Session count before placement
        session_count_after: Session count after placement
    """

    worker_id: str
    worker_name: str
    cpu_percent_before: float = 0.0
    cpu_percent_after: float = 0.0
    memory_percent_before: float = 0.0
    memory_percent_after: float = 0.0
    storage_percent_before: float = 0.0
    storage_percent_after: float = 0.0
    session_count_before: int = 0
    session_count_after: int = 0


@dataclass
class SchedulingDecision:
    """Result of a placement decision.

    Attributes:
        action: The recommended action to take
            - "assign": Worker found, schedule instance to worker_id
            - "scale_up": No suitable worker, provision new one with template
            - "wait": Temporary condition, retry in next cycle
        worker_id: ID of the selected worker (when action="assign")
        worker_template: Template name for scaling (when action="scale_up")
        reason: Human-readable explanation of the decision
        rejection_summary: Breakdown of why workers were rejected
            (e.g., {"status": 2, "capacity": 3, "license": 1})
    """

    action: Literal["assign", "scale_up", "wait"]
    worker_id: str | None = None
    worker_template: str | None = None
    reason: str = ""
    rejection_summary: dict[str, int] | None = None


@dataclass
class PlacementPreviewResult:
    """Enriched result of a dry-run placement preview.

    Extends SchedulingDecision with candidate scores, per-worker rejections,
    and estimated utilization forecast for the selected worker.

    Attributes:
        decision: The core scheduling decision (action, worker_id, reason)
        candidates: Ranked list of eligible workers with scores (best first)
        rejections: Per-worker rejection details (why each worker was filtered out)
        utilization_forecast: Estimated resource usage after placement (when action="assign")
        total_workers_evaluated: Total number of workers considered
        definition_name: Name of the definition being scheduled
    """

    decision: SchedulingDecision
    candidates: list[CandidateScore] = field(default_factory=list)
    rejections: list[WorkerRejection] = field(default_factory=list)
    utilization_forecast: UtilizationForecast | None = None
    total_workers_evaluated: int = 0
    definition_name: str = ""


class PlacementEngine:
    """Placement algorithm for LabletSessions.

    Implements a bin-packing approach that:
    1. Filters out ineligible workers
    2. Scores remaining candidates by utilization
    3. Selects the worker with highest utilization (pack bins)

    This approach minimizes the number of active workers by filling
    existing workers before starting new ones.
    """

    # Worker statuses that should be excluded from placement
    EXCLUDED_STATUSES = {
        CMLWorkerStatus.DRAINING,
        CMLWorkerStatus.STOPPING,
        CMLWorkerStatus.STOPPED,
        CMLWorkerStatus.SHUTTING_DOWN,
        CMLWorkerStatus.TERMINATING,
        CMLWorkerStatus.TERMINATED,
        CMLWorkerStatus.FAILED,
    }

    # License tier compatibility: which definition requirements each worker
    # license type can satisfy.  Enterprise is a superset of Personal —
    # an enterprise-licensed worker CAN run a lab that only requires a
    # personal license, but NOT the other way around.
    LICENSE_SATISFIES: dict[str, frozenset[str]] = {
        "enterprise": frozenset({"enterprise", "personal"}),
        "personal": frozenset({"personal"}),
        "evaluation": frozenset({"evaluation"}),
    }

    def _worker_license_satisfies(self, worker_license_type: str, required_type: str) -> bool:
        """Check if a worker's license type satisfies a required license type.

        Enterprise licenses are a superset of Personal licenses:
        - enterprise worker → satisfies enterprise AND personal requirements
        - personal worker   → satisfies only personal requirements
        - evaluation worker → satisfies only evaluation requirements

        Args:
            worker_license_type: Normalized worker license (e.g. "enterprise")
            required_type: Normalized definition requirement (e.g. "personal")

        Returns:
            True if the worker's license tier covers the requirement
        """
        satisfies = self.LICENSE_SATISFIES.get(worker_license_type, frozenset())
        return required_type.lower() in satisfies

    def schedule(
        self,
        instance: dict[str, Any],
        definition: dict[str, Any],
        workers: list[dict[str, Any]],
        etcd_capacities: dict[str, dict[str, Any]] | None = None,
        templates: list[dict[str, Any]] | None = None,
    ) -> SchedulingDecision:
        """Determine placement for a LabletSession.

        Args:
            instance: Instance data from Control Plane API
            definition: LabletDefinition data from Control Plane API
            workers: List of available workers from Control Plane API
            etcd_capacities: Optional real-time capacity data from etcd,
                keyed by worker_id. When provided, this data is preferred
                over the (potentially stale) capacity in worker dicts.
                Format per entry: {declared_capacity, allocated_capacity,
                available_capacity, assigned_instance_count, updated_at}
            templates: Optional list of worker template dicts from Control Plane API.
                Used for capacity-based template selection during scale-up.
                Each template has: name, capacity (cpu_cores, memory_gb, storage_gb),
                cost_per_hour_usd, enabled.

        Returns:
            SchedulingDecision with action and details
        """
        instance_id = instance.get("id", "unknown")
        definition_name = definition.get("name", "unknown")

        logger.debug(f"Scheduling instance {instance_id} (definition: {definition_name})")

        if not workers:
            logger.info(f"No workers available for instance {instance_id}")
            return SchedulingDecision(
                action="scale_up",
                worker_template=self._select_template(definition, templates),
                reason="No active workers available",
            )

        # Phase 1: Filter eligible workers (using etcd capacity when available)
        candidates, rejections = self._filter_eligible_workers(workers, definition, etcd_capacities)

        if not candidates:
            template = self._select_template(definition, templates)
            # Build descriptive reason based on rejection breakdown
            if rejections.get("capacity", 0) > 0 and rejections.get("capacity", 0) == sum(rejections.values()) - rejections.get("status", 0):
                reason = f"All running workers at capacity ({rejections.get('capacity', 0)} rejected for capacity)"
            else:
                reason_parts = [f"{k}={v}" for k, v in sorted(rejections.items())]
                reason = f"No worker meets requirements (rejections: {', '.join(reason_parts)})"
            logger.info(f"No eligible workers for instance {instance_id}, recommending scale_up with template {template}")
            return SchedulingDecision(
                action="scale_up",
                worker_template=template,
                reason=reason,
                rejection_summary=rejections,
            )

        # Phase 2: Score candidates by utilization (bin-packing)
        scored = self._score_candidates(candidates, definition, etcd_capacities)

        # Phase 3: Select best (highest score = most utilized = pack bins)
        best_worker, best_score = max(scored, key=lambda x: x[1])
        worker_id = best_worker.get("id", "")
        worker_name = best_worker.get("name", worker_id)

        logger.info(f"Selected worker {worker_name} (score: {best_score:.2f}) for instance {instance_id}")

        return SchedulingDecision(
            action="assign",
            worker_id=worker_id,
            reason=f"Best fit: {worker_name} (utilization score: {best_score:.2f})",
        )

    def schedule_preview(
        self,
        instance: dict[str, Any],
        definition: dict[str, Any],
        workers: list[dict[str, Any]],
        etcd_capacities: dict[str, dict[str, Any]] | None = None,
        templates: list[dict[str, Any]] | None = None,
    ) -> PlacementPreviewResult:
        """Dry-run placement preview — runs the real algorithm without executing the decision.

        Returns an enriched result with candidate scores, per-worker rejection
        reasons, and estimated utilization forecast on the selected worker.

        Args:
            instance: Instance data (or synthetic stub for preview)
            definition: LabletDefinition data from Control Plane API
            workers: List of available workers from Control Plane API
            etcd_capacities: Optional real-time capacity data from etcd
            templates: Optional list of worker template dicts

        Returns:
            PlacementPreviewResult with full placement analysis
        """
        definition_name = definition.get("name", "unknown")
        total_workers = len(workers)

        if not workers:
            decision = SchedulingDecision(
                action="scale_up",
                worker_template=self._select_template(definition, templates),
                reason="No active workers available",
            )
            return PlacementPreviewResult(
                decision=decision,
                total_workers_evaluated=0,
                definition_name=definition_name,
            )

        # Phase 1: Filter with detailed per-worker rejections
        candidates, rejection_summary, worker_rejections = self._filter_eligible_workers_detailed(workers, definition, etcd_capacities)

        if not candidates:
            template = self._select_template(definition, templates)
            if rejection_summary.get("capacity", 0) > 0 and rejection_summary.get("capacity", 0) == sum(rejection_summary.values()) - rejection_summary.get("status", 0):
                reason = f"All running workers at capacity ({rejection_summary.get('capacity', 0)} rejected for capacity)"
            else:
                reason_parts = [f"{k}={v}" for k, v in sorted(rejection_summary.items())]
                reason = f"No worker meets requirements (rejections: {', '.join(reason_parts)})"

            decision = SchedulingDecision(
                action="scale_up",
                worker_template=template,
                reason=reason,
                rejection_summary=rejection_summary,
            )
            return PlacementPreviewResult(
                decision=decision,
                candidates=[],
                rejections=worker_rejections,
                total_workers_evaluated=total_workers,
                definition_name=definition_name,
            )

        # Phase 2: Score candidates with detailed breakdown
        scored = self._score_candidates(candidates, definition, etcd_capacities)
        candidate_scores = self._build_candidate_scores(scored, etcd_capacities)

        # Phase 3: Select best
        best_worker, best_score = max(scored, key=lambda x: x[1])
        worker_id = best_worker.get("id", "")
        worker_name = best_worker.get("name", worker_id)

        decision = SchedulingDecision(
            action="assign",
            worker_id=worker_id,
            reason=f"Best fit: {worker_name} (utilization score: {best_score:.2f})",
        )

        # Phase 4: Build utilization forecast for selected worker
        forecast = self._build_utilization_forecast(best_worker, definition, etcd_capacities)

        # Sort candidates by score descending (best first)
        candidate_scores.sort(key=lambda c: c.score, reverse=True)

        return PlacementPreviewResult(
            decision=decision,
            candidates=candidate_scores,
            rejections=worker_rejections,
            utilization_forecast=forecast,
            total_workers_evaluated=total_workers,
            definition_name=definition_name,
        )

    def _filter_eligible_workers_detailed(
        self,
        workers: list[dict[str, Any]],
        definition: dict[str, Any],
        etcd_capacities: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, int], list[WorkerRejection]]:
        """Filter workers with detailed per-worker rejection tracking.

        Same logic as _filter_eligible_workers but additionally collects
        WorkerRejection objects with human-readable reasons.

        Args:
            workers: All available workers
            definition: LabletDefinition requirements
            etcd_capacities: Optional real-time capacity data from etcd

        Returns:
            Tuple of (eligible workers, rejection_summary dict, list of WorkerRejection)
        """
        eligible = []
        rejections: dict[str, int] = {}
        worker_rejections: list[WorkerRejection] = []

        for worker in workers:
            worker_id = worker.get("id", "unknown")
            worker_name = worker.get("name", worker_id)

            # Check 1: Status
            raw_status = (worker.get("status") or "").strip()
            try:
                worker_status = CMLWorkerStatus(raw_status)
            except ValueError:
                rejections["status"] = rejections.get("status", 0) + 1
                worker_rejections.append(
                    WorkerRejection(
                        worker_id=worker_id,
                        worker_name=worker_name,
                        reason_category="status",
                        reason_detail=f"Unknown status: {raw_status}",
                    )
                )
                continue

            if worker_status in self.EXCLUDED_STATUSES:
                rejections["status"] = rejections.get("status", 0) + 1
                worker_rejections.append(
                    WorkerRejection(
                        worker_id=worker_id,
                        worker_name=worker_name,
                        reason_category="status",
                        reason_detail=f"Excluded status: {worker_status.value}",
                    )
                )
                continue

            if worker_status != CMLWorkerStatus.RUNNING:
                rejections["status"] = rejections.get("status", 0) + 1
                worker_rejections.append(
                    WorkerRejection(
                        worker_id=worker_id,
                        worker_name=worker_name,
                        reason_category="status",
                        reason_detail=f"Not running (current: {worker_status.value})",
                    )
                )
                continue

            # Check 2: License affinity
            if not self._check_license_affinity(worker, definition):
                rejections["license"] = rejections.get("license", 0) + 1
                worker_license_type = self._get_worker_license_type(worker)
                required = definition.get("license_affinity") or []
                worker_rejections.append(
                    WorkerRejection(
                        worker_id=worker_id,
                        worker_name=worker_name,
                        reason_category="license",
                        reason_detail=f"License mismatch: worker has '{worker_license_type}', definition requires {required}",
                    )
                )
                continue

            # Check 3: Resource capacity
            if not self._check_resource_capacity(worker, definition, etcd_capacities):
                rejections["capacity"] = rejections.get("capacity", 0) + 1
                worker_rejections.append(
                    WorkerRejection(
                        worker_id=worker_id,
                        worker_name=worker_name,
                        reason_category="capacity",
                        reason_detail=self._describe_capacity_rejection(worker, definition, etcd_capacities),
                    )
                )
                continue

            # Check 4: AMI requirements
            if not self._check_ami_requirements(worker, definition):
                rejections["ami"] = rejections.get("ami", 0) + 1
                worker_rejections.append(
                    WorkerRejection(
                        worker_id=worker_id,
                        worker_name=worker_name,
                        reason_category="ami",
                        reason_detail="AMI/CML version or node definitions not met",
                    )
                )
                continue

            # Check 5: Port availability
            if not self._check_port_availability(worker, definition):
                rejections["ports"] = rejections.get("ports", 0) + 1
                worker_rejections.append(
                    WorkerRejection(
                        worker_id=worker_id,
                        worker_name=worker_name,
                        reason_category="ports",
                        reason_detail="Insufficient available ports",
                    )
                )
                continue

            eligible.append(worker)

        return eligible, rejections, worker_rejections

    def _get_worker_license_type(self, worker: dict[str, Any]) -> str:
        """Extract normalized license type string from worker data.

        The CPA serializes worker license data in these fields:
        - license_status: "REGISTERED" | "EVALUATION" | "UNREGISTERED" etc.
        - cml_license_info: dict with product_license.active, product, etc.

        We extract the license edition (personal/enterprise) from the CML
        license info dict, checking multiple possible locations.
        """
        license_info = worker.get("cml_license_info") or {}

        # Check 1: Direct "product" field (e.g., "CML_Personal", "CML_Enterprise")
        product = license_info.get("product")
        if product and isinstance(product, str):
            return product.lower().replace("cml_", "")

        # Check 2: product_license.active (e.g., "CML_Personal")
        product_license = license_info.get("product_license")
        if isinstance(product_license, dict):
            active_lic = product_license.get("active")
            if active_lic and isinstance(active_lic, str):
                return active_lic.lower().replace("cml_", "")

        # Check 3: is_enterprise flag
        if license_info.get("is_enterprise") is True:
            return "enterprise"
        if license_info.get("is_enterprise") is False:
            return "personal"

        return ""

    def _get_effective_declared_capacity(self, worker: dict[str, Any]) -> dict[str, Any]:
        """Get the worker's declared capacity with fallback to CML system info.

        Workers may not have declared_capacity set if:
        - They were discovered via EC2 (not provisioned from a template)
        - The capacity derivation hasn't been triggered yet
        - They predate the capacity management feature

        In those cases, we derive capacity from CML hardware metrics
        (cml_system_info) which reports actual CPU count, memory, and disk.

        Args:
            worker: Serialized worker dict from CPA

        Returns:
            Capacity dict with cpu_cores, memory_gb, storage_gb keys.
            Returns empty dict if no capacity data is available.
        """
        declared = worker.get("declared_capacity")
        if declared:
            return declared

        # Fallback: derive from CML system info (hardware metrics)
        system_info = worker.get("cml_system_info") or {}
        cpu_count = system_info.get("cpu_count")
        memory_total = system_info.get("memory_total")  # bytes
        disk_total = system_info.get("disk_total")  # bytes

        if cpu_count and memory_total and disk_total:
            derived = {
                "cpu_cores": int(cpu_count),
                "memory_gb": int(memory_total / (1024**3)),
                "storage_gb": int(disk_total / (1024**3)),
                "max_nodes": None,
            }
            worker_name = worker.get("name", worker.get("id", "unknown"))
            logger.debug(f"Worker {worker_name}: no declared_capacity, derived from cml_system_info: cpu={derived['cpu_cores']}, mem={derived['memory_gb']}GB, storage={derived['storage_gb']}GB")
            return derived

        return {}

    def _describe_capacity_rejection(
        self,
        worker: dict[str, Any],
        definition: dict[str, Any],
        etcd_capacities: dict[str, dict[str, Any]] | None = None,
    ) -> str:
        """Build a human-readable reason for capacity rejection."""
        requirements = definition.get("resource_requirements") or {}
        required_cpu = requirements.get("cpu_cores", 0)
        required_memory = requirements.get("memory_gb", 0)
        required_storage = requirements.get("storage_gb", 0)
        worker_id = worker.get("id", "unknown")

        # Check personal license limit
        worker_license_type = self._get_worker_license_type(worker)
        if worker_license_type == "personal":
            etcd_data = (etcd_capacities or {}).get(worker_id)
            session_count = 0
            if etcd_data and "assigned_session_count" in etcd_data:
                session_count = etcd_data["assigned_session_count"]
            else:
                session_count = len(worker.get("session_ids") or [])
            if session_count >= 1:
                return f"Personal license limited to 1 session (current: {session_count})"

        # Check resource capacity
        etcd_data = (etcd_capacities or {}).get(worker_id)
        if etcd_data and etcd_data.get("available_capacity"):
            available = etcd_data["available_capacity"]
            avail_cpu = available.get("cpu_cores", 0)
            avail_mem = available.get("memory_gb", 0)
            avail_stor = available.get("storage_gb", 0)
        else:
            declared = self._get_effective_declared_capacity(worker)
            allocated = worker.get("allocated_capacity") or {}
            avail_cpu = (declared.get("cpu_cores") or 0) - (allocated.get("cpu_cores") or 0)
            avail_mem = (declared.get("memory_gb") or 0) - (allocated.get("memory_gb") or 0)
            avail_stor = (declared.get("storage_gb") or 0) - (allocated.get("storage_gb") or 0)

        shortfalls = []
        if required_cpu > avail_cpu:
            shortfalls.append(f"CPU: need {required_cpu}, have {avail_cpu}")
        if required_memory > avail_mem:
            shortfalls.append(f"Memory: need {required_memory}GB, have {avail_mem}GB")
        if required_storage > avail_stor:
            shortfalls.append(f"Storage: need {required_storage}GB, have {avail_stor}GB")

        return f"Insufficient resources — {'; '.join(shortfalls)}" if shortfalls else "Insufficient capacity"

    def _build_candidate_scores(
        self,
        scored: list[tuple[dict[str, Any], float]],
        etcd_capacities: dict[str, dict[str, Any]] | None = None,
    ) -> list[CandidateScore]:
        """Convert scored tuples to CandidateScore DTOs."""
        results = []
        for worker, score in scored:
            worker_id = worker.get("id", "")
            worker_name = worker.get("name", worker_id)

            # Recalculate utilization breakdown for display
            etcd_data = (etcd_capacities or {}).get(worker_id)
            if etcd_data:
                declared = etcd_data.get("declared_capacity") or self._get_effective_declared_capacity(worker)
                allocated = etcd_data.get("allocated_capacity") or {}
            else:
                declared = self._get_effective_declared_capacity(worker)
                allocated = worker.get("allocated_capacity") or {}

            declared_cpu = declared.get("cpu_cores") or 1
            allocated_cpu = allocated.get("cpu_cores") or 0
            cpu_util = allocated_cpu / declared_cpu if declared_cpu > 0 else 0.0

            declared_mem = declared.get("memory_gb") or 1
            allocated_mem = allocated.get("memory_gb") or 0
            mem_util = allocated_mem / declared_mem if declared_mem > 0 else 0.0

            if etcd_data and "assigned_session_count" in etcd_data:
                session_count = etcd_data["assigned_session_count"]
            else:
                session_count = len(worker.get("session_ids") or [])

            locality_bonus = min(0.05, session_count * 0.01)

            results.append(
                CandidateScore(
                    worker_id=worker_id,
                    worker_name=worker_name,
                    score=round(score, 4),
                    cpu_utilization=round(cpu_util, 4),
                    memory_utilization=round(mem_util, 4),
                    session_count=session_count,
                    locality_bonus=round(locality_bonus, 4),
                )
            )
        return results

    def _build_utilization_forecast(
        self,
        worker: dict[str, Any],
        definition: dict[str, Any],
        etcd_capacities: dict[str, dict[str, Any]] | None = None,
    ) -> UtilizationForecast:
        """Build utilization forecast for placing definition on worker."""
        worker_id = worker.get("id", "")
        worker_name = worker.get("name", worker_id)

        requirements = definition.get("resource_requirements") or {}
        req_cpu = requirements.get("cpu_cores", 0)
        req_mem = requirements.get("memory_gb", 0)
        req_stor = requirements.get("storage_gb", 0)

        etcd_data = (etcd_capacities or {}).get(worker_id)
        if etcd_data:
            declared = etcd_data.get("declared_capacity") or self._get_effective_declared_capacity(worker)
            allocated = etcd_data.get("allocated_capacity") or {}
        else:
            declared = self._get_effective_declared_capacity(worker)
            allocated = worker.get("allocated_capacity") or {}

        declared_cpu = declared.get("cpu_cores") or 1
        allocated_cpu = allocated.get("cpu_cores") or 0
        declared_mem = declared.get("memory_gb") or 1
        allocated_mem = allocated.get("memory_gb") or 0
        declared_stor = declared.get("storage_gb") or 1
        allocated_stor = allocated.get("storage_gb") or 0

        cpu_before = (allocated_cpu / declared_cpu * 100) if declared_cpu > 0 else 0
        cpu_after = ((allocated_cpu + req_cpu) / declared_cpu * 100) if declared_cpu > 0 else 0
        mem_before = (allocated_mem / declared_mem * 100) if declared_mem > 0 else 0
        mem_after = ((allocated_mem + req_mem) / declared_mem * 100) if declared_mem > 0 else 0
        stor_before = (allocated_stor / declared_stor * 100) if declared_stor > 0 else 0
        stor_after = ((allocated_stor + req_stor) / declared_stor * 100) if declared_stor > 0 else 0

        if etcd_data and "assigned_session_count" in etcd_data:
            session_count = etcd_data["assigned_session_count"]
        else:
            session_count = len(worker.get("session_ids") or [])

        return UtilizationForecast(
            worker_id=worker_id,
            worker_name=worker_name,
            cpu_percent_before=round(cpu_before, 1),
            cpu_percent_after=round(cpu_after, 1),
            memory_percent_before=round(mem_before, 1),
            memory_percent_after=round(mem_after, 1),
            storage_percent_before=round(stor_before, 1),
            storage_percent_after=round(stor_after, 1),
            session_count_before=session_count,
            session_count_after=session_count + 1,
        )

    def _filter_eligible_workers(
        self,
        workers: list[dict[str, Any]],
        definition: dict[str, Any],
        etcd_capacities: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        """Filter workers that meet all placement requirements.

        Args:
            workers: All available workers
            definition: LabletDefinition requirements
            etcd_capacities: Optional real-time capacity data from etcd

        Returns:
            Tuple of (eligible workers, rejection_summary dict)
        """
        eligible = []
        rejections: dict[str, int] = {}

        for worker in workers:
            worker_id = worker.get("id", "unknown")
            worker_name = worker.get("name", worker_id)

            # Check 1: Status - must be running
            raw_status = (worker.get("status") or "").strip()
            try:
                worker_status = CMLWorkerStatus(raw_status)
            except ValueError:
                logger.debug(f"Worker {worker_name} excluded: unknown status={raw_status}")
                rejections["status"] = rejections.get("status", 0) + 1
                continue

            if worker_status in self.EXCLUDED_STATUSES:
                logger.debug(f"Worker {worker_name} excluded: status={worker_status}")
                rejections["status"] = rejections.get("status", 0) + 1
                continue

            if worker_status != CMLWorkerStatus.RUNNING:
                logger.debug(f"Worker {worker_name} excluded: not running (status={worker_status})")
                rejections["status"] = rejections.get("status", 0) + 1
                continue

            # Check 2: License affinity
            if not self._check_license_affinity(worker, definition):
                logger.debug(f"Worker {worker_name} excluded: license mismatch")
                rejections["license"] = rejections.get("license", 0) + 1
                continue

            # Check 3: Resource capacity & Personal License limits
            if not self._check_resource_capacity(worker, definition, etcd_capacities):
                logger.debug(f"Worker {worker_name} excluded: insufficient capacity or session limit reached")
                rejections["capacity"] = rejections.get("capacity", 0) + 1
                continue

            # Check 4: AMI requirements (CML version, node definitions)
            if not self._check_ami_requirements(worker, definition):
                logger.debug(f"Worker {worker_name} excluded: AMI requirements not met")
                rejections["ami"] = rejections.get("ami", 0) + 1
                continue

            # Check 5: Port availability
            if not self._check_port_availability(worker, definition):
                logger.debug(f"Worker {worker_name} excluded: insufficient ports")
                rejections["ports"] = rejections.get("ports", 0) + 1
                continue

            # All checks passed
            eligible.append(worker)
            logger.debug(f"Worker {worker_name} is eligible for placement")

        return eligible, rejections

    def _check_license_affinity(
        self,
        worker: dict[str, Any],
        definition: dict[str, Any],
    ) -> bool:
        """Check if worker license matches definition requirements.

        The worker's license edition is extracted from cml_license_info
        (the raw CML API license response) which contains fields like
        product, product_license.active, and is_enterprise.

        Args:
            worker: Worker data (serialized by CPA)
            definition: LabletDefinition with license_affinity

        Returns:
            True if license matches or no constraint specified
        """
        # Get definition's license affinity requirements
        license_affinity = definition.get("license_affinity") or []
        if not license_affinity:
            # No license constraint - any worker is acceptable
            return True

        # Get worker's license type from cml_license_info
        worker_license_type = self._get_worker_license_type(worker)

        # Check if worker's license tier satisfies any of the required types.
        # Enterprise licenses are a superset of Personal — an enterprise
        # worker can serve definitions requiring personal OR enterprise.
        for required_type in license_affinity:
            if self._worker_license_satisfies(worker_license_type, required_type):
                return True

        return False

    def _check_resource_capacity(
        self,
        worker: dict[str, Any],
        definition: dict[str, Any],
        etcd_capacities: dict[str, dict[str, Any]] | None = None,
    ) -> bool:
        """Check if worker has sufficient resources for the definition.

        Prefers real-time capacity data from etcd when available.
        Falls back to API-sourced capacity data (declared - allocated).

        Args:
            worker: Worker data with capacity info
            definition: LabletDefinition with resource requirements
            etcd_capacities: Optional real-time capacity data from etcd

        Returns:
            True if worker has sufficient available capacity
        """
        # Get definition requirements
        requirements = definition.get("resource_requirements") or {}
        required_cpu = requirements.get("cpu_cores", 0)
        required_memory = requirements.get("memory_gb", 0)
        required_storage = requirements.get("storage_gb", 0)

        worker_id = worker.get("id", "unknown")
        worker_name = worker.get("name", worker_id)

        # Try etcd real-time capacity first (Phase 2)
        etcd_data = (etcd_capacities or {}).get(worker_id)
        if etcd_data and etcd_data.get("available_capacity"):
            available = etcd_data["available_capacity"]
            available_cpu = available.get("cpu_cores", 0)
            available_memory = available.get("memory_gb", 0)
            available_storage = available.get("storage_gb", 0)
            logger.debug(f"Worker {worker_name}: using etcd capacity (cpu={available_cpu}, mem={available_memory}GB, storage={available_storage}GB)")
        else:
            # Fallback: calculate from API-sourced declared - allocated
            declared = self._get_effective_declared_capacity(worker)
            allocated = worker.get("allocated_capacity") or {}
            available_cpu = (declared.get("cpu_cores") or 0) - (allocated.get("cpu_cores") or 0)
            available_memory = (declared.get("memory_gb") or 0) - (allocated.get("memory_gb") or 0)
            available_storage = (declared.get("storage_gb") or 0) - (allocated.get("storage_gb") or 0)
            source = "API (stale)" if etcd_capacities else "API"
            logger.debug(f"Worker {worker_name}: using {source} capacity (cpu={available_cpu}, mem={available_memory}GB, storage={available_storage}GB)")

        # Evaluate personal license session limit
        # Reuse _get_worker_license_type which reads cml_license_info
        worker_license_type = self._get_worker_license_type(worker)

        if worker_license_type == "personal":
            # Personal licenses are strictly limited to exactly 1 session
            session_count = 0
            if etcd_data and "assigned_session_count" in etcd_data:
                session_count = etcd_data["assigned_session_count"]
            else:
                session_count = len(worker.get("session_ids") or [])

            if session_count >= 1:
                logger.debug(f"Worker {worker_name} excluded: personal license workers limited to 1 session")
                return False

        # Check if requirements fit
        if required_cpu > available_cpu:
            return False
        if required_memory > available_memory:
            return False
        if required_storage > available_storage:
            return False

        return True

    def _check_ami_requirements(
        self,
        worker: dict[str, Any],
        definition: dict[str, Any],
    ) -> bool:
        """Check if worker's AMI meets definition requirements.

        Checks:
        - CML version compatibility (min/max)
        - Required node definitions are available

        Args:
            worker: Worker data with AMI/CML version info
            definition: LabletDefinition with AMI requirements

        Returns:
            True if worker's AMI meets all requirements
        """
        requirements = definition.get("resource_requirements") or {}
        ami_requirements = requirements.get("ami_requirements") or []

        if not ami_requirements:
            # No AMI constraints
            return True

        # Get worker's CML version
        metrics = worker.get("metrics") or {}
        worker_version = metrics.get("version") or ""

        for ami_req in ami_requirements:
            # Check CML version constraints
            min_version = ami_req.get("cml_version_min")
            max_version = ami_req.get("cml_version_max")

            if min_version and worker_version and worker_version < min_version:
                return False
            if max_version and worker_version and worker_version > max_version:
                return False

            # Check required node definitions
            required_nodes = ami_req.get("node_definitions_required") or []
            if required_nodes:
                # Get worker's available node definitions
                # This would typically be in worker.node_definitions or similar
                worker_nodes = set(worker.get("node_definitions") or [])
                for required_node in required_nodes:
                    if required_node not in worker_nodes:
                        return False

        return True

    def _check_port_availability(
        self,
        worker: dict[str, Any],
        definition: dict[str, Any],
    ) -> bool:
        """Check if worker has enough available ports.

        Args:
            worker: Worker data with port allocation info
            definition: LabletDefinition with port template

        Returns:
            True if worker has enough available ports
        """
        # Get definition's port requirements
        port_template = definition.get("port_template") or {}
        required_ports = len(port_template.get("port_entries") or [])

        if required_ports == 0:
            return True

        # Get worker's port allocation info
        declared_capacity = self._get_effective_declared_capacity(worker)
        max_ports = declared_capacity.get("max_ports") or 1000  # Default high limit

        # Count currently allocated ports
        port_allocations = worker.get("port_allocations") or []
        used_ports = sum(len(alloc.get("ports") or {}) for alloc in port_allocations)

        available_ports = max_ports - used_ports

        return required_ports <= available_ports

    def _score_candidates(
        self,
        candidates: list[dict[str, Any]],
        definition: dict[str, Any],
        etcd_capacities: dict[str, dict[str, Any]] | None = None,
    ) -> list[tuple[dict[str, Any], float]]:
        """Score candidates by utilization for bin-packing.

        Higher score = more utilized = preferred (pack bins tightly).
        Uses etcd capacity data for accurate utilization when available.

        Score formula: utilization_percentage (0.0 - 1.0)
        Tiebreaker: Remaining capacity (less remaining = preferred)

        Args:
            candidates: Eligible workers
            definition: LabletDefinition (for tiebreaking context)
            etcd_capacities: Optional real-time capacity data from etcd

        Returns:
            List of (worker, score) tuples
        """
        scored = []

        for worker in candidates:
            worker_id = worker.get("id", "")

            # Prefer etcd capacity data for accurate scoring
            etcd_data = (etcd_capacities or {}).get(worker_id)
            if etcd_data:
                declared = etcd_data.get("declared_capacity") or self._get_effective_declared_capacity(worker)
                allocated = etcd_data.get("allocated_capacity") or {}
            else:
                declared = self._get_effective_declared_capacity(worker)
                allocated = worker.get("allocated_capacity") or {}

            # Calculate utilization based on CPU (primary metric)
            declared_cpu = declared.get("cpu_cores") or 1
            allocated_cpu = allocated.get("cpu_cores") or 0
            cpu_utilization = allocated_cpu / declared_cpu if declared_cpu > 0 else 0.0

            # Calculate utilization based on memory (secondary metric)
            declared_memory = declared.get("memory_gb") or 1
            allocated_memory = allocated.get("memory_gb") or 0
            memory_utilization = allocated_memory / declared_memory if declared_memory > 0 else 0.0

            # Combined score: average of CPU and memory utilization
            # Higher utilization = higher score = preferred for bin-packing
            score = (cpu_utilization + memory_utilization) / 2

            # Add small bonus for having more assigned sessions (locality)
            # Use etcd session count if available (more accurate)
            if etcd_data and "assigned_session_count" in etcd_data:
                session_count = etcd_data["assigned_session_count"]
            else:
                session_count = len(worker.get("session_ids") or [])
            locality_bonus = min(0.05, session_count * 0.01)  # Max 5% bonus
            score += locality_bonus

            scored.append((worker, score))

        return scored

    def _select_template(
        self,
        definition: dict[str, Any],
        templates: list[dict[str, Any]] | None = None,
    ) -> str:
        """Select a worker template for scale-up.

        Phase 3 - Scale-up default selection.
        Prioritizes the enterprise 'multi-sessions' template by default,
        unless the LabletDefinition explicitly demands strictly 'personal' affinity.

        Args:
            definition: LabletDefinition with resource requirements
            templates: Available worker templates from Control Plane API. (Unused for now)

        Returns:
            Template name for the worker to provision
        """
        license_affinity = definition.get("license_affinity") or []

        # If the definition strictly requires ONLY 'personal', provision the single-session template
        if len(license_affinity) == 1 and license_affinity[0].lower() == "personal":
            logger.info("Definition requests strictly 'personal' affinity. Scaling up with 'single-session' template.")
            return "single-session"

        # For 'enterprise', fallback, or mixed affinities, default to enterprise multi-sessions
        logger.info("Scaling up with default 'multi-sessions' template.")
        return "multi-sessions"
