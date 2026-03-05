"""Phase 2 tests for PlacementEngine with etcd capacity data.

Tests real-time capacity data integration, rejection tracking,
and scale-up decision granularity.
"""

import pytest
from application.services.placement_engine import PlacementEngine, SchedulingDecision


class TestPlacementEngineEtcdCapacity:
    """Tests for PlacementEngine with etcd real-time capacity data (Phase 2)."""

    @pytest.fixture
    def engine(self):
        return PlacementEngine()

    @pytest.fixture
    def instance(self):
        return {"id": "inst-001", "definition_id": "def-001"}

    @pytest.fixture
    def definition(self):
        return {
            "id": "def-001",
            "name": "Basic Lab",
            "resource_requirements": {
                "cpu_cores": 8,
                "memory_gb": 16,
                "storage_gb": 50,
            },
            "license_affinity": [],
            "port_template": {"port_entries": []},
        }

    @pytest.fixture
    def worker_with_api_capacity(self):
        """Worker with stale API capacity (shows plenty of room)."""
        return {
            "id": "worker-001",
            "name": "Worker 1",
            "status": "running",
            "declared_capacity": {"cpu_cores": 96, "memory_gb": 384, "storage_gb": 1000, "max_ports": 100},
            "allocated_capacity": {"cpu_cores": 0, "memory_gb": 0, "storage_gb": 0},
            "session_ids": [],
            "port_allocations": [],
            "cml_license_info": {"product": "CML_Enterprise", "is_enterprise": True},
            "metrics": {"version": "2.9.0"},
        }

    # =========================================================================
    # etcd capacity preferred over API data
    # =========================================================================

    def test_etcd_capacity_preferred_over_api_data(self, engine, instance, definition, worker_with_api_capacity):
        """Test that etcd capacity data is used when available."""
        # API says worker is empty (stale), etcd says it's almost full
        etcd_capacities = {
            "worker-001": {
                "worker_id": "worker-001",
                "declared_capacity": {"cpu_cores": 96, "memory_gb": 384, "storage_gb": 1000},
                "allocated_capacity": {"cpu_cores": 92, "memory_gb": 370, "storage_gb": 950},
                "available_capacity": {"cpu_cores": 4, "memory_gb": 14, "storage_gb": 50},
                "assigned_instance_count": 10,
                "updated_at": "2026-02-08T12:00:00Z",
            }
        }

        # Definition requires 8 CPU cores, but only 4 available per etcd
        decision = engine.schedule(instance, definition, [worker_with_api_capacity], etcd_capacities)

        # Should reject due to insufficient CPU from etcd data
        assert decision.action == "scale_up"
        assert decision.rejection_summary is not None
        assert decision.rejection_summary.get("capacity", 0) > 0

    def test_etcd_capacity_allows_scheduling_when_sufficient(self, engine, instance, definition, worker_with_api_capacity):
        """Test that scheduling succeeds when etcd shows sufficient capacity."""
        etcd_capacities = {
            "worker-001": {
                "worker_id": "worker-001",
                "declared_capacity": {"cpu_cores": 96, "memory_gb": 384, "storage_gb": 1000},
                "allocated_capacity": {"cpu_cores": 40, "memory_gb": 160, "storage_gb": 400},
                "available_capacity": {"cpu_cores": 56, "memory_gb": 224, "storage_gb": 600},
                "assigned_instance_count": 5,
                "updated_at": "2026-02-08T12:00:00Z",
            }
        }

        decision = engine.schedule(instance, definition, [worker_with_api_capacity], etcd_capacities)

        assert decision.action == "assign"
        assert decision.worker_id == "worker-001"

    def test_fallback_to_api_when_etcd_missing_for_worker(self, engine, instance, definition, worker_with_api_capacity):
        """Test fallback to API data when etcd has no data for a worker."""
        # etcd capacities empty for this worker
        etcd_capacities = {
            "worker-999": {  # Different worker, not relevant
                "worker_id": "worker-999",
                "available_capacity": {"cpu_cores": 0, "memory_gb": 0, "storage_gb": 0},
            }
        }

        # API data shows worker is empty -> should succeed
        decision = engine.schedule(instance, definition, [worker_with_api_capacity], etcd_capacities)

        assert decision.action == "assign"
        assert decision.worker_id == "worker-001"

    def test_fallback_to_api_when_no_etcd_capacities(self, engine, instance, definition, worker_with_api_capacity):
        """Test fallback to API data when etcd_capacities is None."""
        decision = engine.schedule(instance, definition, [worker_with_api_capacity], None)

        assert decision.action == "assign"
        assert decision.worker_id == "worker-001"

    def test_fallback_to_api_when_etcd_capacities_empty(self, engine, instance, definition, worker_with_api_capacity):
        """Test fallback to API data when etcd_capacities is empty dict."""
        decision = engine.schedule(instance, definition, [worker_with_api_capacity], {})

        assert decision.action == "assign"
        assert decision.worker_id == "worker-001"

    # =========================================================================
    # Scoring with etcd data
    # =========================================================================

    def test_scoring_uses_etcd_utilization(self, engine, instance, definition):
        """Test that scoring uses etcd capacity for accurate utilization."""
        worker_a = {
            "id": "worker-a",
            "name": "Worker A",
            "status": "running",
            "declared_capacity": {"cpu_cores": 96, "memory_gb": 384, "storage_gb": 1000},
            "allocated_capacity": {"cpu_cores": 10, "memory_gb": 40, "storage_gb": 100},  # API: 10% used
            "session_ids": [],
            "port_allocations": [],
            "cml_license_info": {"product": "CML_Enterprise", "is_enterprise": True},
            "metrics": {"version": "2.9.0"},
        }
        worker_b = {
            "id": "worker-b",
            "name": "Worker B",
            "status": "running",
            "declared_capacity": {"cpu_cores": 96, "memory_gb": 384, "storage_gb": 1000},
            "allocated_capacity": {"cpu_cores": 10, "memory_gb": 40, "storage_gb": 100},  # API: 10% used
            "session_ids": [],
            "port_allocations": [],
            "cml_license_info": {"product": "CML_Enterprise", "is_enterprise": True},
            "metrics": {"version": "2.9.0"},
        }

        # etcd says worker_a is actually 80% utilized (should be preferred for bin-packing)
        etcd_capacities = {
            "worker-a": {
                "worker_id": "worker-a",
                "declared_capacity": {"cpu_cores": 96, "memory_gb": 384, "storage_gb": 1000},
                "allocated_capacity": {"cpu_cores": 80, "memory_gb": 300, "storage_gb": 800},
                "available_capacity": {"cpu_cores": 16, "memory_gb": 84, "storage_gb": 200},
                "assigned_instance_count": 8,
            },
            "worker-b": {
                "worker_id": "worker-b",
                "declared_capacity": {"cpu_cores": 96, "memory_gb": 384, "storage_gb": 1000},
                "allocated_capacity": {"cpu_cores": 20, "memory_gb": 80, "storage_gb": 200},
                "available_capacity": {"cpu_cores": 76, "memory_gb": 304, "storage_gb": 800},
                "assigned_instance_count": 2,
            },
        }

        decision = engine.schedule(instance, definition, [worker_b, worker_a], etcd_capacities)

        # Bin-packing should prefer worker_a (80% utilized per etcd)
        assert decision.action == "assign"
        assert decision.worker_id == "worker-a"


class TestPlacementEngineRejectionSummary:
    """Tests for rejection summary tracking (Phase 2)."""

    @pytest.fixture
    def engine(self):
        return PlacementEngine()

    @pytest.fixture
    def instance(self):
        return {"id": "inst-001", "definition_id": "def-001"}

    def test_rejection_summary_tracks_capacity_rejections(self, engine, instance):
        """Test that rejection summary correctly tracks capacity rejections."""
        definition = {
            "id": "def-001",
            "name": "Large Lab",
            "resource_requirements": {"cpu_cores": 64, "memory_gb": 256, "storage_gb": 500},
            "license_affinity": [],
        }

        worker_full = {
            "id": "worker-full",
            "name": "Full Worker",
            "status": "running",
            "declared_capacity": {"cpu_cores": 96, "memory_gb": 384, "storage_gb": 1000},
            "allocated_capacity": {"cpu_cores": 90, "memory_gb": 350, "storage_gb": 900},
            "session_ids": [],
            "port_allocations": [],
            "cml_license_info": {"product": "CML_Enterprise", "is_enterprise": True},
            "metrics": {"version": "2.9.0"},
        }

        decision = engine.schedule(instance, definition, [worker_full])

        assert decision.action == "scale_up"
        assert decision.rejection_summary is not None
        assert decision.rejection_summary.get("capacity", 0) == 1
        assert "capacity" in decision.reason.lower()

    def test_rejection_summary_tracks_status_rejections(self, engine, instance):
        """Test that rejection summary tracks status rejections."""
        definition = {
            "id": "def-001",
            "name": "Lab",
            "resource_requirements": {"cpu_cores": 4, "memory_gb": 8, "storage_gb": 20},
            "license_affinity": [],
        }

        stopped_worker = {
            "id": "worker-stopped",
            "name": "Stopped Worker",
            "status": "stopped",
            "declared_capacity": {"cpu_cores": 96, "memory_gb": 384, "storage_gb": 1000},
            "allocated_capacity": {"cpu_cores": 0, "memory_gb": 0, "storage_gb": 0},
            "session_ids": [],
            "port_allocations": [],
            "cml_license_info": {"product": "CML_Enterprise", "is_enterprise": True},
        }

        decision = engine.schedule(instance, definition, [stopped_worker])

        assert decision.action == "scale_up"
        assert decision.rejection_summary is not None
        assert decision.rejection_summary.get("status", 0) == 1

    def test_rejection_summary_tracks_license_rejections(self, engine, instance):
        """Test that rejection summary tracks license rejections."""
        definition = {
            "id": "def-001",
            "name": "Lab",
            "resource_requirements": {"cpu_cores": 4, "memory_gb": 8, "storage_gb": 20},
            "license_affinity": ["enterprise"],
        }

        personal_worker = {
            "id": "worker-personal",
            "name": "Personal Worker",
            "status": "running",
            "declared_capacity": {"cpu_cores": 96, "memory_gb": 384, "storage_gb": 1000},
            "allocated_capacity": {"cpu_cores": 0, "memory_gb": 0, "storage_gb": 0},
            "session_ids": [],
            "port_allocations": [],
            "cml_license_info": {"product": "CML_Personal", "is_enterprise": False},
            "metrics": {"version": "2.9.0"},
        }

        decision = engine.schedule(instance, definition, [personal_worker])

        assert decision.action == "scale_up"
        assert decision.rejection_summary is not None
        assert decision.rejection_summary.get("license", 0) == 1

    def test_rejection_summary_with_mixed_rejections(self, engine, instance):
        """Test rejection summary with multiple rejection types."""
        definition = {
            "id": "def-001",
            "name": "Lab",
            "resource_requirements": {"cpu_cores": 4, "memory_gb": 8, "storage_gb": 20},
            "license_affinity": ["enterprise"],
        }

        # Worker 1: wrong status
        stopped_worker = {
            "id": "worker-1",
            "name": "Stopped Worker",
            "status": "stopped",
            "declared_capacity": {"cpu_cores": 96, "memory_gb": 384, "storage_gb": 1000},
            "allocated_capacity": {"cpu_cores": 0, "memory_gb": 0, "storage_gb": 0},
            "session_ids": [],
            "port_allocations": [],
            "cml_license_info": {"product": "CML_Enterprise", "is_enterprise": True},
        }

        # Worker 2: wrong license
        personal_worker = {
            "id": "worker-2",
            "name": "Personal Worker",
            "status": "running",
            "declared_capacity": {"cpu_cores": 96, "memory_gb": 384, "storage_gb": 1000},
            "allocated_capacity": {"cpu_cores": 0, "memory_gb": 0, "storage_gb": 0},
            "session_ids": [],
            "port_allocations": [],
            "cml_license_info": {"product": "CML_Personal", "is_enterprise": False},
            "metrics": {"version": "2.9.0"},
        }

        # Worker 3: insufficient capacity
        full_worker = {
            "id": "worker-3",
            "name": "Full Worker",
            "status": "running",
            "declared_capacity": {"cpu_cores": 2, "memory_gb": 4, "storage_gb": 10},
            "allocated_capacity": {"cpu_cores": 0, "memory_gb": 0, "storage_gb": 0},
            "session_ids": [],
            "port_allocations": [],
            "cml_license_info": {"product": "CML_Enterprise", "is_enterprise": True},
            "metrics": {"version": "2.9.0"},
        }

        decision = engine.schedule(instance, definition, [stopped_worker, personal_worker, full_worker])

        assert decision.action == "scale_up"
        assert decision.rejection_summary is not None
        assert decision.rejection_summary.get("status", 0) == 1
        assert decision.rejection_summary.get("license", 0) == 1
        assert decision.rejection_summary.get("capacity", 0) == 1

    def test_no_rejection_summary_on_successful_assign(self, engine, instance):
        """Test that successful assignment has no rejection summary."""
        definition = {
            "id": "def-001",
            "name": "Lab",
            "resource_requirements": {"cpu_cores": 4, "memory_gb": 8, "storage_gb": 20},
            "license_affinity": [],
        }

        worker = {
            "id": "worker-001",
            "name": "Worker 1",
            "status": "running",
            "declared_capacity": {"cpu_cores": 96, "memory_gb": 384, "storage_gb": 1000},
            "allocated_capacity": {"cpu_cores": 0, "memory_gb": 0, "storage_gb": 0},
            "session_ids": [],
            "port_allocations": [],
            "cml_license_info": {"product": "CML_Enterprise", "is_enterprise": True},
            "metrics": {"version": "2.9.0"},
        }

        decision = engine.schedule(instance, definition, [worker])

        assert decision.action == "assign"
        assert decision.rejection_summary is None


class TestSchedulingDecisionEnhancements:
    """Tests for SchedulingDecision with new rejection_summary field (Phase 2)."""

    def test_decision_with_rejection_summary(self):
        """Test creating a decision with rejection summary."""
        decision = SchedulingDecision(
            action="scale_up",
            worker_template="m5zn.metal-cml-2.9",
            reason="All workers at capacity",
            rejection_summary={"capacity": 3, "status": 2},
        )
        assert decision.rejection_summary is not None
        assert decision.rejection_summary["capacity"] == 3
        assert decision.rejection_summary["status"] == 2

    def test_decision_without_rejection_summary_defaults_to_none(self):
        """Test that rejection_summary defaults to None."""
        decision = SchedulingDecision(action="assign", worker_id="w-1")
        assert decision.rejection_summary is None
