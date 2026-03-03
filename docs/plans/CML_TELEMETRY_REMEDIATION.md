# CML Telemetry Data Collection — Gap Analysis & Remediation Plan

> **Created:** 2026-02-10
> **Status:** In Progress
> **Scope:** worker-controller SPI client, reconciler, CPA domain, frontend SSE/UI
> **Reference:** CML v2.9 OpenAPI Spec (`docs/integration/CML/cml_v2-9_openapi.json`)

---

## 1. Problem Statement

The worker-controller's CML SPI client (`cml_system_spi.py`) uses **flat key names** that
don't match the real CML v2.9 API response structure (which is **nested**). As a result,
the control-plane-api (CPA) receives `null` for nearly every resource utilization field,
despite the CML worker being fully operational and returning rich data.

### Evidence (SSE Snapshot — Running Worker)

```
cml_system_info: {cpu_count: null, cpu_utilization: 0.0, memory_total: null, memory_free: null,
                  memory_used: null, disk_total: null, disk_free: null, disk_used: null,
                  controller_disk_total: null, controller_disk_free: null, controller_disk_used: null,
                  allocated_cpus: null, allocated_memory: null, total_nodes: null,
                  running_nodes: null, computes: {}}
cml_system_health: {valid: true, is_licensed: false, is_enterprise: false, computes: {}, controller: {}}
cml_license_info: {is_valid: false, node_limit: 0, nodes_in_use: 0, expires: null, product: null}
```

### Actual CML v2.9 API Responses (Confirmed Live)

<details>
<summary>GET /api/v0/system_stats</summary>

```json
{
  "computes": {
    "435a7bac-882a-4edd-a8f3-f4ea9307cb52": {
      "hostname": "ip-172-31-38-11",
      "is_controller": true,
      "stats": {
        "cpu": { "load": [0.004, 0.016, 0.0], "count": 48, "percent": 0.49, "model": "Intel(R) Xeon(R) Platinum 8252C CPU @ 3.80GHz", "predicted": 6 },
        "memory": { "total": 202422902784, "free": 199086161920, "used": 2033487872 },
        "disk": { "total": 266206101504, "free": 128413523968, "used": 137792577536 },
        "dominfo": { "allocated_cpus": 0, "allocated_memory": 0, "total_nodes": 2, "total_orphans": 0, "running_nodes": 0, "running_orphans": 0 }
      }
    }
  },
  "all": {
    "cpu": { "count": 48, "percent": 0.49 },
    "memory": { "total": 202422902784, "free": 199086161920, "used": 2033487872 },
    "disk": { "total": 266206101504, "free": 128413523968, "used": 137792577536 }
  },
  "controller": {
    "disk": { "total": 266206101504, "free": 128413519872, "used": 137775804416 }
  }
}
```

</details>

<details>
<summary>GET /api/v0/system_health</summary>

```json
{
  "valid": true,
  "computes": {
    "435a7bac-882a-4edd-a8f3-f4ea9307cb52": {
      "kvm_vmx_enabled": true, "enough_cpus": true, "lld_connected": true,
      "lld_synced": true, "libvirt": true, "fabric": true, "device_mux": true,
      "refplat_images_available": true, "docker_shim": true, "valid": true,
      "admission_state": "READY", "is_controller": true, "hostname": "ip-172-31-38-11"
    }
  },
  "is_licensed": true,
  "is_enterprise": true,
  "controller": {
    "core_connected": true, "nodes_loaded": true,
    "images_loaded": true, "valid": true
  }
}
```

</details>

<details>
<summary>GET /api/v0/licensing</summary>

```json
{
  "registration": { "status": "COMPLETED", "smart_account": "CML Prod", "virtual_account": "Default", "expires": "2027-01-14 00:56:19" },
  "authorization": { "status": "IN_COMPLIANCE", "expires": "2026-04-14 00:55:21" },
  "features": [
    { "name": "CML - Enterprise License", "in_use": 1, "status": "WAITING", "max": 1 },
    { "name": "CML - Expansion Node License", "in_use": 0, "status": "INIT", "max": 500 }
  ],
  "product_license": { "active": "CML_Enterprise", "is_enterprise": true },
  "udi": { "hostname": "ip-172-31-38-11", "product_uuid": "ec2a406e-..." }
}
```

</details>

---

## 2. Root Cause Analysis

### Gap 1: `system_stats` — Wrong Key Mapping 🔴 Critical

| SPI Code (WRONG) | Actual CML Key | Impact |
|---|---|---|
| `data.get("cpu_percent", 0.0)` | `data["all"]["cpu"]["percent"]` | CPU always 0.0 |
| `data.get("memory_percent", 0.0)` | Doesn't exist — calculate from `used/total` | Memory always 0.0 |
| `data.get("memory_total")` | `data["all"]["memory"]["total"]` | Always null |
| `data.get("memory_used")` | `data["all"]["memory"]["used"]` | Always null |
| `data.get("disk_percent")` | Doesn't exist — calculate from `used/total` | Always null |
| `data.get("disk_total")` | `data["all"]["disk"]["total"]` | Always null |
| `data.get("disk_used")` | `data["all"]["disk"]["used"]` | Always null |
| `data.get("uptime")` | Not in `system_stats` endpoint | Always null |
| _Not collected_ | `data["all"]["cpu"]["count"]` | CPU count null |
| _Not collected_ | `data["all"]["memory"]["free"]` | Memory free null |
| _Not collected_ | `data["all"]["disk"]["free"]` | Disk free null |
| _Not collected_ | `data["controller"]["disk"].*` | Controller disk null |
| _Not collected_ | `data["computes"].*` (per-node, dominfo) | Compute Nodes empty |

### Gap 2: `system_health` — Endpoint Never Called 🔴 Critical

- The SPI client has **no `get_system_health()` method**.
- The reconciler fakes it with `check_health()` which only checks `system_info.ready`.
- Result: `is_licensed: false`, `is_enterprise: false`, empty `computes` and `controller`.

### Gap 3: `licensing` — Wrong Key Mapping 🟡 Medium

| SPI Code (WRONG) | Actual CML Key | Impact |
|---|---|---|
| `data.get("is_valid", False)` | Derive from `registration.status == "COMPLETED"` | Shows unregistered |
| `data.get("node_limit", 0)` | Derive from `features[].max` (base license) | Shows 0 nodes |
| `data.get("nodes_in_use", 0)` | Derive from `features[].in_use` | Shows 0 |
| `data.get("expires")` | `registration.expires` or `authorization.expires` | Null |
| `data.get("product")` | `product_license.active` | Null |

### Gap 4: Reconciler — Incomplete system_info Dict 🔴 Critical

The reconciler sends only 5 of the 15+ keys the CPA expects:

```python
# Current (5 keys):
"system_info": {
    "all_cpu_percent": ..., "all_memory_total": ..., "all_memory_used": ...,
    "all_disk_total": ..., "all_disk_used": ...
}

# CPA expects (15+ keys):
"system_info": {
    "all_cpu_count", "all_cpu_percent",
    "all_memory_total", "all_memory_free", "all_memory_used",
    "all_disk_total", "all_disk_free", "all_disk_used",
    "controller_disk_total", "controller_disk_free", "controller_disk_used",
    "allocated_cpus", "allocated_memory", "total_nodes", "running_nodes",
    "computes": { "<uuid>": { "hostname", "is_controller", "stats": {...} } }
}
```

---

## 3. Remediation Plan

### Phase 1: Fix SPI Client (`cml_system_spi.py`)

**Files:** `src/worker-controller/integration/services/cml_system_spi.py`

- [x] **1a.** Rework `CmlSystemStats` dataclass to capture the full nested `all.*`, `controller.*`, `computes.*` structure
- [x] **1b.** Add new `get_system_health()` method calling `GET /api/v0/system_health` (auth required)
- [x] **1c.** Fix `get_license_info()` to parse nested `registration`, `authorization`, `features`, `product_license`
- [x] **1d.** Add `CmlSystemHealth`, `CmlComputeNode`, `CmlComputeHealth`, `CmlControllerHealth` dataclasses

### Phase 2: Fix Reconciler (`worker_reconciler.py`)

**Files:** `src/worker-controller/application/hosted_services/worker_reconciler.py`

- [x] **2a.** Rewrite `_collect_and_report_cml_data()` → build complete `system_info` dict with all keys CPA expects
- [x] **2b.** Replace fake `check_health()` with real `get_system_health()` call → forward full response
- [x] **2c.** Fix `license_info` dict construction to use correct parsed fields
- [x] **2d.** Fix `_collect_worker_metrics()` CML section to use correct stats from new dataclass

### Phase 3: Tests

**Files:** `src/worker-controller/tests/test_cml_system_spi.py` (new)

- [x] **3a.** Unit tests for `get_system_stats()` with mocked CML API response (real nested structure)
- [x] **3b.** Unit tests for `get_system_health()` with mocked response
- [x] **3c.** Unit tests for `get_license_info()` with mocked response
- [x] **3d.** Unit tests for `_collect_and_report_cml_data()` verifying complete dict construction

### Phase 4: Frontend — SSE Events & UI Components

> **Status:** TODO — Blocked on Phase 1-2 completion (backend must send correct data first)

#### 4a. Backend SSE Event Emission (control-plane-api)

**Files to check:**

- `src/control-plane-api/application/services/sse_event_relay.py`
- `src/control-plane-api/api/controllers/events_controller.py`
- `src/control-plane-api/domain/entities/cml_worker.py` (snapshot DTO)

**Tasks:**

- [ ] Verify `worker.snapshot` event includes the newly-populated system_info fields
- [ ] Verify `worker.metrics.updated.batch` events include cpu/memory/storage utilization
  from the CML native data (not just CloudWatch nulls)
- [ ] Confirm the snapshot DTO maps `CmlSystemInfoVO` fields correctly for serialization
- [ ] Add integration test: trigger CML data update → verify SSE event contains all fields

#### 4b. Frontend: Worker Detail Modal — CML Tab

**Files to update:**

- `src/core/lcm_ui/src/components/workerDetailModal/cmlTab.ts`
- `src/core/lcm_ui/src/components/workerDetailModal/cmlTab.scss` (if needed)

**Current state:** UI shows N/A for CPU cores, Memory total/free, Disk total/free,
all controller disk values, and "No compute nodes found."

**Tasks:**

- [ ] Verify `cmlTab.ts` component subscribes to correct SSE event fields
- [ ] Verify Resource Utilization section renders `cpu.count`, `memory.total/free`, `disk.total/free`
  from `cml_system_info` in the snapshot
- [ ] Verify Controller Status section renders `controller.core_connected`, `nodes_loaded`,
  `images_loaded`, `valid` from `cml_system_health.controller`
- [ ] Verify Compute Nodes section renders the `computes` map — each node with hostname,
  admission_state, kvm_vmx_enabled, etc.
- [ ] Add unit formatting helpers for memory bytes → human readable (GB), disk bytes → GB
- [ ] Consider adding License section to CML tab or refreshing AWS tab's license display

#### 4c. Frontend: Worker Detail Modal — Monitoring Tab

**Files to update:**

- `src/core/lcm_ui/src/components/workerDetailModal/monitoringTab.ts`
- `src/core/lcm_ui/src/components/workerDetailModal/monitoringTab.scss` (if needed)

**Tasks:**

- [ ] Verify "Recent Resource Utilization" section now displays CML-native CPU/Memory values
  instead of N/A (once backend sends correct data)
- [ ] Update CPU Utilization display to prefer CML native over CloudWatch
- [ ] Add Memory Utilization display using CML native memory data
- [ ] Add Storage Utilization display using CML native disk data
- [ ] Update the info note to reflect when data is from CML vs CloudWatch

#### 4d. Frontend: Worker Detail Modal — AWS Tab

**Files to update:**

- `src/core/lcm_ui/src/components/workerDetailModal/awsTab.ts`

**Tasks:**

- [ ] Verify License Status badge updates from `unregistered` to correct status when
  license data is properly parsed

#### 4e. Frontend: Workers Table / Overview

**Files to update:**

- `src/core/lcm_ui/src/components/workersTable.ts`
- `src/core/lcm_ui/src/services/sseService.ts`

**Tasks:**

- [ ] Verify workers table correctly reflects resource utilization in summary columns (if any)
- [ ] Verify SSE service correctly updates worker store when `worker.snapshot` arrives with full data

---

## 4. Key Data Flow Mapping

```
┌──────────────────┐     ┌──────────────────────┐     ┌──────────────────────┐
│  CML v2.9 API    │────▶│  Worker Controller    │────▶│  Control Plane API   │
│                  │     │  (SPI + Reconciler)   │     │  (Domain + SSE)      │
└──────────────────┘     └──────────────────────┘     └──────────────────────┘
                                                               │
GET /system_stats         CmlSystemStats (full)        CMLMetricsUpdatedEvent
  .all.cpu.count    ──▶   .cpu_count            ──▶    system_info["all_cpu_count"]
  .all.cpu.percent  ──▶   .cpu_percent          ──▶    system_info["all_cpu_percent"]
  .all.memory.*     ──▶   .memory_total/free/.. ──▶    system_info["all_memory_*"]
  .all.disk.*       ──▶   .disk_total/free/used ──▶    system_info["all_disk_*"]
  .controller.disk  ──▶   .controller_disk_*    ──▶    system_info["controller_disk_*"]
  .computes.{uuid}  ──▶   .computes[...]        ──▶    system_info["computes"]

GET /system_health        CmlSystemHealth               system_health dict
  .valid            ──▶   .valid                ──▶    system_health["valid"]
  .is_licensed      ──▶   .is_licensed          ──▶    system_health["is_licensed"]
  .is_enterprise    ──▶   .is_enterprise        ──▶    system_health["is_enterprise"]
  .computes.{uuid}  ──▶   .computes[...]        ──▶    system_health["computes"]
  .controller       ──▶   .controller           ──▶    system_health["controller"]

GET /licensing            CmlLicenseInfo                 license_info dict
  .registration.*   ──▶   .registration_status  ──▶    license_info["registration_status"]
  .features[].max   ──▶   .node_limit           ──▶    license_info["node_limit"]
  .product_license  ──▶   .product              ──▶    license_info["product"]
```

---

## 5. CML v2.9 OpenAPI Schema Reference

| Schema | Key Properties |
|---|---|
| `SystemStats` | `computes` (map), `all` (ComputeHostStats), `controller` (ControllerDiskStats) |
| `ComputeHostStats` | `cpu` (CpuStats), `memory` (MemoryStats), `disk` (DiskStats) |
| `ComputeHostWithStats` | `hostname`, `is_controller`, `stats` (ComputeHostStatsWithDomInfo) |
| `CpuStats` | `count` (int), `percent` (float 0-100) |
| `MemoryStats` | `used`, `free`, `total` (number, bytes) |
| `DiskStats` | `used`, `free`, `total` (number, bytes) |
| `DomInfo` | `allocated_cpus`, `allocated_memory`, `total_nodes`, `running_nodes` |
| `SystemHealth` | `valid`, `computes` (map→ComputeHealth), `is_licensed`, `is_enterprise`, `controller` |
| `ComputeHealth` | `kvm_vmx_enabled`, `enough_cpus`, `lld_connected`, `valid`, `admission_state`, ... |
| `ControllerHealth` | `core_connected`, `nodes_loaded`, `images_loaded`, `valid` |
| `LicensingStatus` | `registration`, `authorization`, `features[]`, `product_license`, `udi`, `transport` |
