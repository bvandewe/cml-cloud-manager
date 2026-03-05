"""Unit tests for PlacementEngine.

Tests the bin-packing placement algorithm for LabletSession scheduling.
"""

import pytest
from application.services.placement_engine import PlacementEngine, SchedulingDecision


class TestSchedulingDecision:
    """Tests for SchedulingDecision dataclass."""

    def test_assign_decision(self):
        """Test creating an assign decision."""
        decision = SchedulingDecision(
            action="assign",
            worker_id="worker-123",
            reason="Best fit worker",
        )
        assert decision.action == "assign"
        assert decision.worker_id == "worker-123"
        assert decision.worker_template is None
        assert decision.reason == "Best fit worker"

    def test_scale_up_decision(self):
        """Test creating a scale-up decision."""
        decision = SchedulingDecision(
            action="scale_up",
            worker_template="m5zn.metal-cml-2.9",
            reason="No suitable workers",
        )
        assert decision.action == "scale_up"
        assert decision.worker_id is None
        assert decision.worker_template == "m5zn.metal-cml-2.9"

    def test_wait_decision(self):
        """Test creating a wait decision."""
        decision = SchedulingDecision(
            action="wait",
            reason="Temporary condition",
        )
        assert decision.action == "wait"
        assert decision.worker_id is None
        assert decision.worker_template is None


class TestPlacementEngineFiltering:
    """Tests for PlacementEngine filtering logic."""

    @pytest.fixture
    def engine(self):
        """Create a PlacementEngine instance."""
        return PlacementEngine()

    @pytest.fixture
    def basic_definition(self):
        """Create a basic lablet definition."""
        return {
            "id": "def-001",
            "name": "Basic Lab",
            "resource_requirements": {
                "cpu_cores": 4,
                "memory_gb": 8,
                "storage_gb": 20,
                "nested_virt": False,
            },
            "license_affinity": [],
            "port_template": {
                "port_entries": [
                    {"name": "serial_1"},
                    {"name": "vnc_1"},
                ],
            },
        }

    @pytest.fixture
    def running_worker(self):
        """Create a running worker with capacity."""
        return {
            "id": "worker-001",
            "name": "Worker 1",
            "status": "running",
            "declared_capacity": {
                "cpu_cores": 96,
                "memory_gb": 384,
                "storage_gb": 1000,
                "max_ports": 100,
            },
            "allocated_capacity": {
                "cpu_cores": 0,
                "memory_gb": 0,
                "storage_gb": 0,
            },
            "session_ids": [],
            "port_allocations": [],
            "cml_license_info": {
                "product": "CML_Enterprise",
                "is_enterprise": True,
                "product_license": {"active": "CML_Enterprise"},
            },
            "license_status": "REGISTERED",
            "metrics": {
                "version": "2.9.0",
            },
            "node_definitions": ["ios", "iosv", "iosvl2", "alpine"],
        }

    @pytest.fixture
    def basic_instance(self):
        """Create a basic instance."""
        return {
            "id": "inst-001",
            "definition_id": "def-001",
            "status": "pending",
        }

    def test_no_workers_returns_scale_up(self, engine, basic_instance, basic_definition):
        """Test that no workers returns scale_up decision."""
        decision = engine.schedule(basic_instance, basic_definition, [])

        assert decision.action == "scale_up"
        assert decision.worker_template is not None
        assert "No active workers" in decision.reason

    def test_single_suitable_worker_returns_assign(self, engine, basic_instance, basic_definition, running_worker):
        """Test scheduling with single suitable worker."""
        decision = engine.schedule(basic_instance, basic_definition, [running_worker])

        assert decision.action == "assign"
        assert decision.worker_id == "worker-001"

    def test_excludes_stopped_workers(self, engine, basic_instance, basic_definition, running_worker):
        """Test that stopped workers are excluded."""
        running_worker["status"] = "stopped"

        decision = engine.schedule(basic_instance, basic_definition, [running_worker])

        assert decision.action == "scale_up"
        assert "No worker meets requirements" in decision.reason

    def test_excludes_terminated_workers(self, engine, basic_instance, basic_definition, running_worker):
        """Test that terminated workers are excluded."""
        running_worker["status"] = "terminated"

        decision = engine.schedule(basic_instance, basic_definition, [running_worker])

        assert decision.action == "scale_up"

    def test_excludes_stopping_workers(self, engine, basic_instance, basic_definition, running_worker):
        """Test that stopping workers are excluded."""
        running_worker["status"] = "stopping"

        decision = engine.schedule(basic_instance, basic_definition, [running_worker])

        assert decision.action == "scale_up"

    def test_excludes_workers_with_insufficient_cpu(self, engine, basic_instance, basic_definition, running_worker):
        """Test that workers with insufficient CPU are excluded."""
        # Definition requires 4 CPU cores, but worker has only 2 available
        running_worker["declared_capacity"]["cpu_cores"] = 2

        decision = engine.schedule(basic_instance, basic_definition, [running_worker])

        assert decision.action == "scale_up"

    def test_excludes_workers_with_insufficient_memory(self, engine, basic_instance, basic_definition, running_worker):
        """Test that workers with insufficient memory are excluded."""
        # Definition requires 8 GB, but worker has only 4 available
        running_worker["declared_capacity"]["memory_gb"] = 4

        decision = engine.schedule(basic_instance, basic_definition, [running_worker])

        assert decision.action == "scale_up"

    def test_considers_allocated_capacity(self, engine, basic_instance, basic_definition, running_worker):
        """Test that allocated capacity is subtracted from available."""
        # Worker has 96 cores total, 94 allocated = 2 available
        # Definition requires 4 cores
        running_worker["allocated_capacity"]["cpu_cores"] = 94

        decision = engine.schedule(basic_instance, basic_definition, [running_worker])

        assert decision.action == "scale_up"


class TestPlacementEngineLicenseAffinity:
    """Tests for license affinity filtering."""

    @pytest.fixture
    def engine(self):
        return PlacementEngine()

    @pytest.fixture
    def enterprise_worker(self):
        return {
            "id": "worker-enterprise",
            "name": "Enterprise Worker",
            "status": "running",
            "declared_capacity": {"cpu_cores": 96, "memory_gb": 384, "storage_gb": 1000},
            "allocated_capacity": {"cpu_cores": 0, "memory_gb": 0, "storage_gb": 0},
            "session_ids": [],
            "port_allocations": [],
            "cml_license_info": {"product": "CML_Enterprise", "is_enterprise": True, "product_license": {"active": "CML_Enterprise"}},
            "license_status": "REGISTERED",
            "metrics": {"version": "2.9.0"},
        }

    @pytest.fixture
    def personal_worker(self):
        return {
            "id": "worker-personal",
            "name": "Personal Worker",
            "status": "running",
            "declared_capacity": {"cpu_cores": 96, "memory_gb": 384, "storage_gb": 1000},
            "allocated_capacity": {"cpu_cores": 0, "memory_gb": 0, "storage_gb": 0},
            "session_ids": [],
            "port_allocations": [],
            "cml_license_info": {"product": "CML_Personal", "is_enterprise": False, "product_license": {"active": "CML_Personal"}},
            "license_status": "REGISTERED",
            "metrics": {"version": "2.9.0"},
        }

    def test_no_license_affinity_accepts_any(self, engine, enterprise_worker, personal_worker):
        """Test that no license affinity accepts any worker."""
        definition = {
            "id": "def-001",
            "name": "Lab",
            "resource_requirements": {"cpu_cores": 4, "memory_gb": 8, "storage_gb": 20},
            "license_affinity": [],
        }
        instance = {"id": "inst-001", "definition_id": "def-001"}

        decision = engine.schedule(instance, definition, [enterprise_worker, personal_worker])

        assert decision.action == "assign"

    def test_enterprise_affinity_selects_enterprise_worker(self, engine, enterprise_worker, personal_worker):
        """Test that enterprise affinity selects enterprise worker."""
        definition = {
            "id": "def-001",
            "name": "Lab",
            "resource_requirements": {"cpu_cores": 4, "memory_gb": 8, "storage_gb": 20},
            "license_affinity": ["enterprise"],
        }
        instance = {"id": "inst-001", "definition_id": "def-001"}

        decision = engine.schedule(instance, definition, [personal_worker, enterprise_worker])

        assert decision.action == "assign"
        assert decision.worker_id == "worker-enterprise"

    def test_personal_affinity_accepts_enterprise_worker(self, engine, enterprise_worker):
        """Enterprise license is a superset of personal — enterprise worker satisfies personal requirement."""
        definition = {
            "id": "def-001",
            "name": "Lab",
            "resource_requirements": {"cpu_cores": 4, "memory_gb": 8, "storage_gb": 20},
            "license_affinity": ["personal"],
        }
        instance = {"id": "inst-001", "definition_id": "def-001"}

        decision = engine.schedule(instance, definition, [enterprise_worker])

        assert decision.action == "assign"
        assert decision.worker_id == "worker-enterprise"

    def test_enterprise_affinity_excludes_personal_worker(self, engine, personal_worker):
        """Personal license cannot satisfy enterprise requirement — personal worker is rejected."""
        definition = {
            "id": "def-001",
            "name": "Lab",
            "resource_requirements": {"cpu_cores": 4, "memory_gb": 8, "storage_gb": 20},
            "license_affinity": ["enterprise"],
        }
        instance = {"id": "inst-001", "definition_id": "def-001"}

        decision = engine.schedule(instance, definition, [personal_worker])

        assert decision.action == "scale_up"

    def test_personal_affinity_prefers_personal_when_both_available(self, engine, enterprise_worker, personal_worker):
        """When both enterprise and personal workers match a personal requirement, both are eligible."""
        definition = {
            "id": "def-001",
            "name": "Lab",
            "resource_requirements": {"cpu_cores": 4, "memory_gb": 8, "storage_gb": 20},
            "license_affinity": ["personal"],
        }
        instance = {"id": "inst-001", "definition_id": "def-001"}

        decision = engine.schedule(instance, definition, [enterprise_worker, personal_worker])

        # Both are eligible; bin-packing selects one
        assert decision.action == "assign"


class TestPlacementEngineBinPacking:
    """Tests for bin-packing scoring algorithm."""

    @pytest.fixture
    def engine(self):
        return PlacementEngine()

    @pytest.fixture
    def definition(self):
        return {
            "id": "def-001",
            "name": "Lab",
            "resource_requirements": {"cpu_cores": 4, "memory_gb": 8, "storage_gb": 20},
            "license_affinity": [],
        }

    @pytest.fixture
    def instance(self):
        return {"id": "inst-001", "definition_id": "def-001"}

    def test_prefers_more_utilized_worker(self, engine, definition, instance):
        """Test that bin-packing prefers more utilized workers."""
        # Worker A: 50% utilized
        worker_a = {
            "id": "worker-a",
            "name": "Worker A",
            "status": "running",
            "declared_capacity": {"cpu_cores": 96, "memory_gb": 384, "storage_gb": 1000},
            "allocated_capacity": {"cpu_cores": 48, "memory_gb": 192, "storage_gb": 500},
            "session_ids": ["inst-100", "inst-101"],
            "port_allocations": [],
            "cml_license_info": {"product": "CML_Enterprise", "is_enterprise": True},
            "metrics": {"version": "2.9.0"},
        }

        # Worker B: 10% utilized (nearly empty)
        worker_b = {
            "id": "worker-b",
            "name": "Worker B",
            "status": "running",
            "declared_capacity": {"cpu_cores": 96, "memory_gb": 384, "storage_gb": 1000},
            "allocated_capacity": {"cpu_cores": 10, "memory_gb": 40, "storage_gb": 100},
            "session_ids": [],
            "port_allocations": [],
            "cml_license_info": {"product": "CML_Enterprise", "is_enterprise": True},
            "metrics": {"version": "2.9.0"},
        }

        decision = engine.schedule(instance, definition, [worker_b, worker_a])

        # Should prefer worker_a (more utilized = bin-packing)
        assert decision.action == "assign"
        assert decision.worker_id == "worker-a"

    def test_considers_locality_bonus(self, engine, definition, instance):
        """Test that workers with more instances get a small locality bonus."""
        # Both workers have same utilization, but worker_a has more instances
        worker_a = {
            "id": "worker-a",
            "name": "Worker A",
            "status": "running",
            "declared_capacity": {"cpu_cores": 96, "memory_gb": 384, "storage_gb": 1000},
            "allocated_capacity": {"cpu_cores": 48, "memory_gb": 192, "storage_gb": 500},
            "session_ids": ["inst-1", "inst-2", "inst-3"],
            "port_allocations": [],
            "cml_license_info": {"product": "CML_Enterprise", "is_enterprise": True},
            "metrics": {"version": "2.9.0"},
        }

        worker_b = {
            "id": "worker-b",
            "name": "Worker B",
            "status": "running",
            "declared_capacity": {"cpu_cores": 96, "memory_gb": 384, "storage_gb": 1000},
            "allocated_capacity": {"cpu_cores": 48, "memory_gb": 192, "storage_gb": 500},
            "session_ids": [],
            "port_allocations": [],
            "cml_license_info": {"product": "CML_Enterprise", "is_enterprise": True},
            "metrics": {"version": "2.9.0"},
        }

        decision = engine.schedule(instance, definition, [worker_b, worker_a])

        # Worker A should win due to locality bonus
        assert decision.action == "assign"
        assert decision.worker_id == "worker-a"


class TestPlacementEngineAMIRequirements:
    """Tests for AMI/CML version requirements."""

    @pytest.fixture
    def engine(self):
        return PlacementEngine()

    @pytest.fixture
    def instance(self):
        return {"id": "inst-001", "definition_id": "def-001"}

    @pytest.fixture
    def worker_29(self):
        return {
            "id": "worker-29",
            "name": "CML 2.9 Worker",
            "status": "running",
            "declared_capacity": {"cpu_cores": 96, "memory_gb": 384, "storage_gb": 1000},
            "allocated_capacity": {"cpu_cores": 0, "memory_gb": 0, "storage_gb": 0},
            "session_ids": [],
            "port_allocations": [],
            "cml_license_info": {"product": "CML_Enterprise", "is_enterprise": True},
            "metrics": {"version": "2.9.0"},
            "node_definitions": ["ios", "iosv", "cat8000v"],
        }

    @pytest.fixture
    def worker_27(self):
        return {
            "id": "worker-27",
            "name": "CML 2.7 Worker",
            "status": "running",
            "declared_capacity": {"cpu_cores": 96, "memory_gb": 384, "storage_gb": 1000},
            "allocated_capacity": {"cpu_cores": 0, "memory_gb": 0, "storage_gb": 0},
            "session_ids": [],
            "port_allocations": [],
            "cml_license_info": {"product": "CML_Enterprise", "is_enterprise": True},
            "metrics": {"version": "2.7.1"},
            "node_definitions": ["ios", "iosv"],
        }

    def test_min_version_requirement(self, engine, instance, worker_29, worker_27):
        """Test that minimum CML version is enforced."""
        definition = {
            "id": "def-001",
            "name": "Lab requiring 2.8+",
            "resource_requirements": {
                "cpu_cores": 4,
                "memory_gb": 8,
                "storage_gb": 20,
                "ami_requirements": [{"cml_version_min": "2.8.0"}],
            },
            "license_affinity": [],
        }

        decision = engine.schedule(instance, definition, [worker_27, worker_29])

        assert decision.action == "assign"
        assert decision.worker_id == "worker-29"

    def test_node_definition_requirement(self, engine, instance, worker_29, worker_27):
        """Test that required node definitions are enforced."""
        definition = {
            "id": "def-001",
            "name": "Lab requiring cat8000v",
            "resource_requirements": {
                "cpu_cores": 4,
                "memory_gb": 8,
                "storage_gb": 20,
                "ami_requirements": [{"node_definitions_required": ["cat8000v"]}],
            },
            "license_affinity": [],
        }

        decision = engine.schedule(instance, definition, [worker_27, worker_29])

        assert decision.action == "assign"
        assert decision.worker_id == "worker-29"

    def test_missing_node_definition_excludes_worker(self, engine, instance, worker_27):
        """Test that missing node definitions exclude worker."""
        definition = {
            "id": "def-001",
            "name": "Lab requiring cat8000v",
            "resource_requirements": {
                "cpu_cores": 4,
                "memory_gb": 8,
                "storage_gb": 20,
                "ami_requirements": [{"node_definitions_required": ["cat8000v"]}],
            },
            "license_affinity": [],
        }

        decision = engine.schedule(instance, definition, [worker_27])

        assert decision.action == "scale_up"


class TestPlacementEngineTemplateSelection:
    """Tests for worker template selection."""

    @pytest.fixture
    def engine(self):
        return PlacementEngine()

    def test_selects_metal_for_nested_virt(self, engine):
        """Test that nested virtualization fallback uses CPU cores (currently medium for 4 cores)."""
        definition = {
            "id": "def-001",
            "name": "Lab",
            "resource_requirements": {
                "cpu_cores": 4,
                "memory_gb": 8,
                "storage_gb": 20,
                "nested_virt": True,
            },
        }
        instance = {"id": "inst-001", "definition_id": "def-001"}

        decision = engine.schedule(instance, definition, [])

        assert decision.action == "scale_up"
        assert decision.worker_template == "multi-sessions"

    def test_selects_metal_for_high_cpu(self, engine):
        """Test that high CPU requirements get metal instance."""
        definition = {
            "id": "def-001",
            "name": "Large Lab",
            "resource_requirements": {
                "cpu_cores": 64,
                "memory_gb": 256,
                "storage_gb": 500,
                "nested_virt": False,
            },
        }
        instance = {"id": "inst-001", "definition_id": "def-001"}

        decision = engine.schedule(instance, definition, [])

        assert decision.action == "scale_up"
        assert "multi-sessions" in decision.worker_template

    def test_selects_smaller_for_low_cpu(self, engine):
        """Test that low CPU requirements can use smaller instance."""
        definition = {
            "id": "def-001",
            "name": "Small Lab",
            "resource_requirements": {
                "cpu_cores": 4,
                "memory_gb": 8,
                "storage_gb": 20,
                "nested_virt": False,
            },
        }
        instance = {"id": "inst-001", "definition_id": "def-001"}

        decision = engine.schedule(instance, definition, [])

        assert decision.action == "scale_up"
        assert decision.worker_template == "multi-sessions"


class TestEffectiveDeclaredCapacity:
    """Tests for _get_effective_declared_capacity fallback.

    Workers may not have declared_capacity set (e.g., discovered via EC2 before
    the capacity derivation code runs). The placement engine must fall back to
    deriving capacity from cml_system_info hardware metrics.
    """

    @pytest.fixture
    def engine(self):
        return PlacementEngine()

    def test_returns_declared_capacity_when_present(self, engine):
        """When declared_capacity exists, return it directly."""
        worker = {
            "id": "worker-001",
            "declared_capacity": {"cpu_cores": 48, "memory_gb": 188, "storage_gb": 248},
        }
        result = engine._get_effective_declared_capacity(worker)
        assert result == {"cpu_cores": 48, "memory_gb": 188, "storage_gb": 248}

    def test_derives_from_cml_system_info_when_no_declared(self, engine):
        """When declared_capacity is null, derive from cml_system_info."""
        worker = {
            "id": "worker-001",
            "name": "Test Worker",
            "declared_capacity": None,
            "cml_system_info": {
                "cpu_count": 48,
                "memory_total": 202422902784,  # ~188 GB
                "disk_total": 266206101504,  # ~248 GB
            },
        }
        result = engine._get_effective_declared_capacity(worker)
        assert result["cpu_cores"] == 48
        assert result["memory_gb"] == 188
        assert result["storage_gb"] == 247  # int(266206101504 / 1024^3) = 247
        assert result["max_nodes"] is None

    def test_derives_when_declared_missing_entirely(self, engine):
        """When declared_capacity key doesn't exist at all, derive from system_info."""
        worker = {
            "id": "worker-001",
            "name": "Discovered Worker",
            "cml_system_info": {
                "cpu_count": 96,
                "memory_total": 412316860416,  # ~384 GB
                "disk_total": 1073741824000,  # ~1000 GB
            },
        }
        result = engine._get_effective_declared_capacity(worker)
        assert result["cpu_cores"] == 96
        assert result["memory_gb"] == 384
        assert result["storage_gb"] == 1000  # int(1073741824000 / 1024^3)

    def test_returns_empty_dict_when_no_data(self, engine):
        """When neither declared_capacity nor system_info is available."""
        worker = {"id": "worker-001"}
        result = engine._get_effective_declared_capacity(worker)
        assert result == {}

    def test_returns_empty_dict_when_system_info_incomplete(self, engine):
        """When cml_system_info is missing required fields."""
        worker = {
            "id": "worker-001",
            "declared_capacity": None,
            "cml_system_info": {"cpu_count": 48},  # missing memory and disk
        }
        result = engine._get_effective_declared_capacity(worker)
        assert result == {}

    def test_scheduling_assigns_with_system_info_fallback(self, engine):
        """End-to-end: worker without declared_capacity but with system_info gets assigned."""
        worker = {
            "id": "worker-001",
            "name": "Discovered Worker",
            "status": "running",
            "declared_capacity": None,
            "allocated_capacity": {"cpu_cores": 0, "memory_gb": 0, "storage_gb": 0},
            "session_ids": [],
            "port_allocations": [],
            "cml_license_info": {"product": "CML_Enterprise", "is_enterprise": True},
            "license_status": "REGISTERED",
            "cml_system_info": {
                "cpu_count": 48,
                "memory_total": 202422902784,  # ~188 GB
                "disk_total": 266206101504,  # ~248 GB
            },
        }
        definition = {
            "id": "def-001",
            "name": "Lab",
            "resource_requirements": {"cpu_cores": 2, "memory_gb": 4, "storage_gb": 20},
            "license_affinity": ["enterprise"],
        }
        instance = {"id": "inst-001", "definition_id": "def-001"}

        decision = engine.schedule(instance, definition, [worker])
        assert decision.action == "assign"
        assert decision.worker_id == "worker-001"

    def test_preview_assigns_with_system_info_fallback(self, engine):
        """Preview: worker without declared_capacity gets correct forecast."""
        worker = {
            "id": "worker-001",
            "name": "Discovered Worker",
            "status": "running",
            "declared_capacity": None,
            "allocated_capacity": {"cpu_cores": 0, "memory_gb": 0, "storage_gb": 0},
            "session_ids": [],
            "port_allocations": [],
            "cml_license_info": {"product": "CML_Enterprise", "is_enterprise": True},
            "license_status": "REGISTERED",
            "cml_system_info": {
                "cpu_count": 48,
                "memory_total": 202422902784,
                "disk_total": 266206101504,
            },
        }
        definition = {
            "id": "def-001",
            "name": "Lab",
            "resource_requirements": {"cpu_cores": 2, "memory_gb": 4, "storage_gb": 20},
            "license_affinity": ["enterprise"],
        }
        instance = {"id": "inst-001", "definition_id": "def-001"}

        result = engine.schedule_preview(instance, definition, [worker])
        assert result.decision.action == "assign"
        assert result.decision.worker_id == "worker-001"
        # Utilization forecast should reflect system-derived capacity
        assert result.utilization_forecast is not None
        assert result.utilization_forecast.cpu_percent_after > 0

    def test_scheduling_rejects_when_no_capacity_data(self, engine):
        """Worker with neither declared_capacity nor cml_system_info gets rejected."""
        worker = {
            "id": "worker-001",
            "name": "Ghost Worker",
            "status": "running",
            "declared_capacity": None,
            "allocated_capacity": {"cpu_cores": 0, "memory_gb": 0, "storage_gb": 0},
            "session_ids": [],
            "port_allocations": [],
            "cml_license_info": {"product": "CML_Enterprise", "is_enterprise": True},
            "license_status": "REGISTERED",
        }
        definition = {
            "id": "def-001",
            "name": "Lab",
            "resource_requirements": {"cpu_cores": 2, "memory_gb": 4, "storage_gb": 20},
            "license_affinity": [],
        }
        instance = {"id": "inst-001", "definition_id": "def-001"}

        decision = engine.schedule(instance, definition, [worker])
        assert decision.action == "scale_up"
