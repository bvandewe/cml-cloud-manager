"""Unit tests for CML System SPI Client.

Tests the CmlSystemSpiClient's ability to correctly parse
CML v2.9 API responses with their nested JSON structures.

Uses real response structures captured from a live CML 2.9.0+build.3 instance.
"""

import pytest
from integration.services.cml_system_spi import (
    CmlLicenseInfo,
    CmlSystemHealth,
    CmlSystemStats,
)

# =============================================================================
# Test Fixtures — Real CML v2.9 API Response Data
# =============================================================================

REAL_SYSTEM_STATS_RESPONSE = {
    "computes": {
        "435a7bac-882a-4edd-a8f3-f4ea9307cb52": {
            "hostname": "ip-172-31-38-11",
            "is_controller": True,
            "stats": {
                "cpu": {
                    "load": [0.00390625, 0.015625, 0.0],
                    "count": 48,
                    "percent": 0.4895833333333333,
                    "model": "Intel(R) Xeon(R) Platinum 8252C CPU @ 3.80GHz",
                    "predicted": 6,
                },
                "memory": {
                    "total": 202422902784,
                    "free": 199086161920,
                    "used": 2033487872,
                },
                "disk": {
                    "total": 266206101504,
                    "free": 128413523968,
                    "used": 137792577536,
                },
                "dominfo": {
                    "allocated_cpus": 0,
                    "allocated_memory": 0,
                    "total_nodes": 2,
                    "total_orphans": 0,
                    "running_nodes": 0,
                    "running_orphans": 0,
                },
            },
        }
    },
    "all": {
        "cpu": {"count": 48, "percent": 0.4895833333333333},
        "memory": {"total": 202422902784, "free": 199086161920, "used": 2033487872},
        "disk": {"total": 266206101504, "free": 128413523968, "used": 137792577536},
    },
    "controller": {"disk": {"total": 266206101504, "free": 128413519872, "used": 137775804416}},
}

REAL_SYSTEM_HEALTH_RESPONSE = {
    "valid": True,
    "computes": {
        "435a7bac-882a-4edd-a8f3-f4ea9307cb52": {
            "kvm_vmx_enabled": True,
            "enough_cpus": True,
            "lld_connected": True,
            "lld_synced": True,
            "libvirt": True,
            "fabric": True,
            "device_mux": True,
            "refplat_images_available": True,
            "docker_shim": True,
            "valid": True,
            "admission_state": "READY",
            "is_controller": True,
            "hostname": "ip-172-31-38-11",
        }
    },
    "is_licensed": True,
    "is_enterprise": True,
    "controller": {
        "core_connected": True,
        "nodes_loaded": True,
        "images_loaded": True,
        "valid": True,
    },
}

REAL_LICENSING_RESPONSE = {
    "registration": {
        "status": "COMPLETED",
        "smart_account": "CML Prod",
        "virtual_account": "Default",
        "expires": "2027-01-14 00:56:19",
        "register_time": {
            "succeeded": None,
            "attempted": "2026-01-14 00:58:20",
            "scheduled": None,
            "status": None,
            "failure": "OK",
            "success": "SUCCESS",
        },
        "renew_time": {
            "succeeded": None,
            "attempted": None,
            "scheduled": "2026-07-13 00:58:19",
            "status": None,
            "failure": None,
            "success": "FAILED",
        },
    },
    "authorization": {
        "status": "IN_COMPLIANCE",
        "expires": "2026-04-14 00:55:21",
        "renew_time": {
            "succeeded": None,
            "attempted": "2026-02-09 20:11:25",
            "scheduled": "2026-02-10 19:57:27",
            "status": "FAILED",
            "failure": "Connection timed out after 60003 milliseconds",
            "success": "FAILED",
        },
    },
    "features": [
        {
            "id": "regid.2019-10.com.cisco.CML_ENT_BASE,1.0_15d3393c-846c-4e00-a54e-1ea90f2b2160",
            "name": "CML - Enterprise License",
            "description": "Cisco Modeling Labs - Enterprise License with 20 nodes capacity included",
            "in_use": 1,
            "status": "WAITING",
            "version": "1.0",
            "min": 0,
            "max": 1,
            "minEndDate": None,
            "maxEndDate": None,
        },
        {
            "id": "regid.2019-10.com.cisco.CML_NODE_COUNT,1.0_2607650b-6ca8-46d5-81e5-e6688b7383c4",
            "name": "CML - Expansion Node License",
            "description": "Cisco Modeling Labs - Expansion node capacity for CML Enterprise Servers",
            "in_use": 0,
            "status": "INIT",
            "version": "1.0",
            "min": 0,
            "max": 500,
            "minEndDate": None,
            "maxEndDate": None,
        },
    ],
    "reservation_mode": False,
    "transport": {
        "default_ssms": "https://smartreceiver.cisco.com/licservice/license",
        "ssms": "https://ssm.ciscolablets.com/SmartTransport",
        "proxy": {"server": None, "port": None},
    },
    "udi": {
        "hostname": "ip-172-31-38-11",
        "product_uuid": "ec2a406e-9a80-3338-81bc-4e0566b20ca2",
    },
    "product_license": {"active": "CML_Enterprise", "is_enterprise": True},
}


# =============================================================================
# Tests — CmlSystemStats.from_api_response()
# =============================================================================


class TestCmlSystemStatsFromApiResponse:
    """Tests for parsing CML /api/v0/system_stats responses."""

    def test_parses_all_cpu_stats(self):
        stats = CmlSystemStats.from_api_response(REAL_SYSTEM_STATS_RESPONSE)
        assert stats.cpu.count == 48
        assert stats.cpu.percent == pytest.approx(0.4896, abs=0.001)

    def test_parses_all_memory_stats(self):
        stats = CmlSystemStats.from_api_response(REAL_SYSTEM_STATS_RESPONSE)
        assert stats.memory.total == 202422902784
        assert stats.memory.free == 199086161920
        assert stats.memory.used == 2033487872

    def test_parses_all_disk_stats(self):
        stats = CmlSystemStats.from_api_response(REAL_SYSTEM_STATS_RESPONSE)
        assert stats.disk.total == 266206101504
        assert stats.disk.free == 128413523968
        assert stats.disk.used == 137792577536

    def test_parses_controller_disk_stats(self):
        stats = CmlSystemStats.from_api_response(REAL_SYSTEM_STATS_RESPONSE)
        assert stats.controller_disk.total == 266206101504
        assert stats.controller_disk.free == 128413519872
        assert stats.controller_disk.used == 137775804416

    def test_parses_compute_nodes(self):
        stats = CmlSystemStats.from_api_response(REAL_SYSTEM_STATS_RESPONSE)
        assert len(stats.computes) == 1
        node = stats.computes[0]
        assert node.compute_id == "435a7bac-882a-4edd-a8f3-f4ea9307cb52"
        assert node.hostname == "ip-172-31-38-11"
        assert node.is_controller is True

    def test_parses_compute_node_cpu(self):
        stats = CmlSystemStats.from_api_response(REAL_SYSTEM_STATS_RESPONSE)
        node = stats.computes[0]
        assert node.stats.cpu.count == 48
        assert node.stats.cpu.percent == pytest.approx(0.4896, abs=0.001)

    def test_parses_compute_node_memory(self):
        stats = CmlSystemStats.from_api_response(REAL_SYSTEM_STATS_RESPONSE)
        node = stats.computes[0]
        assert node.stats.memory.total == 202422902784
        assert node.stats.memory.free == 199086161920
        assert node.stats.memory.used == 2033487872

    def test_parses_compute_node_disk(self):
        stats = CmlSystemStats.from_api_response(REAL_SYSTEM_STATS_RESPONSE)
        node = stats.computes[0]
        assert node.stats.disk.total == 266206101504

    def test_parses_compute_node_dominfo(self):
        stats = CmlSystemStats.from_api_response(REAL_SYSTEM_STATS_RESPONSE)
        node = stats.computes[0]
        assert node.stats.dominfo.allocated_cpus == 0
        assert node.stats.dominfo.allocated_memory == 0
        assert node.stats.dominfo.total_nodes == 2
        assert node.stats.dominfo.running_nodes == 0
        assert node.stats.dominfo.total_orphans == 0
        assert node.stats.dominfo.running_orphans == 0

    def test_handles_empty_response(self):
        stats = CmlSystemStats.from_api_response({})
        assert stats.cpu.count == 0
        assert stats.cpu.percent == 0.0
        assert stats.memory.total == 0
        assert stats.disk.total == 0
        assert stats.controller_disk.total == 0
        assert len(stats.computes) == 0

    def test_handles_partial_response(self):
        """CML may return partial data if computes are initializing."""
        data = {"all": {"cpu": {"count": 8}}, "computes": {}}
        stats = CmlSystemStats.from_api_response(data)
        assert stats.cpu.count == 8
        assert stats.cpu.percent == 0.0
        assert stats.memory.total == 0
        assert len(stats.computes) == 0

    def test_handles_multiple_compute_nodes(self):
        data = {
            "all": {
                "cpu": {"count": 96, "percent": 5.0},
                "memory": {"total": 400000000000, "free": 300000000000, "used": 100000000000},
                "disk": {"total": 500000000000, "free": 400000000000, "used": 100000000000},
            },
            "controller": {"disk": {"total": 250000000000, "free": 200000000000, "used": 50000000000}},
            "computes": {
                "aaaa-bbbb": {
                    "hostname": "controller-node",
                    "is_controller": True,
                    "stats": {
                        "cpu": {"count": 48, "percent": 3.0},
                        "memory": {"total": 200000000000, "free": 150000000000, "used": 50000000000},
                        "disk": {"total": 250000000000, "free": 200000000000, "used": 50000000000},
                        "dominfo": {
                            "allocated_cpus": 4,
                            "allocated_memory": 8192,
                            "total_nodes": 10,
                            "running_nodes": 5,
                            "total_orphans": 0,
                            "running_orphans": 0,
                        },
                    },
                },
                "cccc-dddd": {
                    "hostname": "compute-node-2",
                    "is_controller": False,
                    "stats": {
                        "cpu": {"count": 48, "percent": 7.0},
                        "memory": {"total": 200000000000, "free": 150000000000, "used": 50000000000},
                        "disk": {"total": 250000000000, "free": 200000000000, "used": 50000000000},
                        "dominfo": {
                            "allocated_cpus": 8,
                            "allocated_memory": 16384,
                            "total_nodes": 15,
                            "running_nodes": 10,
                            "total_orphans": 1,
                            "running_orphans": 0,
                        },
                    },
                },
            },
        }
        stats = CmlSystemStats.from_api_response(data)
        assert len(stats.computes) == 2
        assert stats.cpu.count == 96
        hostnames = {n.hostname for n in stats.computes}
        assert hostnames == {"controller-node", "compute-node-2"}


# =============================================================================
# Tests — CmlSystemHealth.from_api_response()
# =============================================================================


class TestCmlSystemHealthFromApiResponse:
    """Tests for parsing CML /api/v0/system_health responses."""

    def test_parses_overall_health(self):
        health = CmlSystemHealth.from_api_response(REAL_SYSTEM_HEALTH_RESPONSE)
        assert health.valid is True
        assert health.is_licensed is True
        assert health.is_enterprise is True

    def test_parses_controller_health(self):
        health = CmlSystemHealth.from_api_response(REAL_SYSTEM_HEALTH_RESPONSE)
        assert health.controller.core_connected is True
        assert health.controller.nodes_loaded is True
        assert health.controller.images_loaded is True
        assert health.controller.valid is True

    def test_parses_compute_health(self):
        health = CmlSystemHealth.from_api_response(REAL_SYSTEM_HEALTH_RESPONSE)
        assert len(health.computes) == 1
        ch = health.computes[0]
        assert ch.compute_id == "435a7bac-882a-4edd-a8f3-f4ea9307cb52"
        assert ch.hostname == "ip-172-31-38-11"
        assert ch.is_controller is True
        assert ch.kvm_vmx_enabled is True
        assert ch.enough_cpus is True
        assert ch.lld_connected is True
        assert ch.lld_synced is True
        assert ch.libvirt is True
        assert ch.fabric is True
        assert ch.device_mux is True
        assert ch.refplat_images_available is True
        assert ch.docker_shim is True
        assert ch.valid is True
        assert ch.admission_state == "READY"

    def test_handles_empty_response(self):
        health = CmlSystemHealth.from_api_response({})
        assert health.valid is None
        assert health.is_licensed is None
        assert health.is_enterprise is False
        assert len(health.computes) == 0
        assert health.controller.valid is False

    def test_handles_unlicensed_system(self):
        data = {
            "valid": True,
            "is_licensed": False,
            "is_enterprise": False,
            "computes": {},
            "controller": {"core_connected": True, "nodes_loaded": True, "images_loaded": True, "valid": True},
        }
        health = CmlSystemHealth.from_api_response(data)
        assert health.valid is True
        assert health.is_licensed is False
        assert health.is_enterprise is False


# =============================================================================
# Tests — CmlLicenseInfo.from_api_response()
# =============================================================================


class TestCmlLicenseInfoFromApiResponse:
    """Tests for parsing CML /api/v0/licensing responses."""

    def test_parses_registered_license(self):
        info = CmlLicenseInfo.from_api_response(REAL_LICENSING_RESPONSE)
        assert info.is_valid is True
        assert info.registration_status == "COMPLETED"
        assert info.authorization_status == "IN_COMPLIANCE"

    def test_parses_product_info(self):
        info = CmlLicenseInfo.from_api_response(REAL_LICENSING_RESPONSE)
        assert info.product == "CML_Enterprise"
        assert info.is_enterprise is True

    def test_parses_node_limits(self):
        info = CmlLicenseInfo.from_api_response(REAL_LICENSING_RESPONSE)
        # Base license max=1 + Expansion max=500 = 501 total
        assert info.node_limit == 501
        # Base in_use=1 + Expansion in_use=0 = 1
        assert info.nodes_in_use == 1

    def test_parses_expiration_dates(self):
        info = CmlLicenseInfo.from_api_response(REAL_LICENSING_RESPONSE)
        assert info.expires_at == "2027-01-14 00:56:19"
        assert info.authorization_expires_at == "2026-04-14 00:55:21"

    def test_parses_account_info(self):
        info = CmlLicenseInfo.from_api_response(REAL_LICENSING_RESPONSE)
        assert info.smart_account == "CML Prod"
        assert info.virtual_account == "Default"

    def test_preserves_raw_features(self):
        info = CmlLicenseInfo.from_api_response(REAL_LICENSING_RESPONSE)
        assert len(info.features) == 2
        assert info.features[0]["name"] == "CML - Enterprise License"
        assert info.features[1]["name"] == "CML - Expansion Node License"

    def test_unregistered_license(self):
        data = {
            "registration": {"status": "NOT_REGISTERED"},
            "authorization": {"status": "EVAL_MODE"},
            "features": [],
            "product_license": {"active": "CML_Personal", "is_enterprise": False},
        }
        info = CmlLicenseInfo.from_api_response(data)
        assert info.is_valid is False
        assert info.registration_status == "NOT_REGISTERED"
        assert info.authorization_status == "EVAL_MODE"
        assert info.node_limit == 0
        assert info.nodes_in_use == 0
        assert info.product == "CML_Personal"
        assert info.is_enterprise is False

    def test_out_of_compliance_license(self):
        data = {
            "registration": {"status": "COMPLETED"},
            "authorization": {"status": "OUT_OF_COMPLIANCE"},
            "features": [{"name": "CML", "max": 20, "in_use": 25}],
            "product_license": {"active": "CML_Enterprise", "is_enterprise": True},
        }
        info = CmlLicenseInfo.from_api_response(data)
        assert info.is_valid is False  # OUT_OF_COMPLIANCE → not valid
        assert info.registration_status == "COMPLETED"
        assert info.authorization_status == "OUT_OF_COMPLIANCE"
        assert info.node_limit == 20
        assert info.nodes_in_use == 25

    def test_handles_empty_response(self):
        info = CmlLicenseInfo.from_api_response({})
        assert info.is_valid is False
        assert info.registration_status == "NOT_REGISTERED"
        assert info.authorization_status == "UNKNOWN"
        assert info.node_limit == 0
        assert info.nodes_in_use == 0
        assert info.product is None
