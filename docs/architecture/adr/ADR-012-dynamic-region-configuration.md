# ADR-012: Dynamic AWS Region Configuration

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-01-19 |
| **Deciders** | Architecture Team |
| **Related ADRs** | [ADR-001](./ADR-001-api-centric-state-management.md), [ADR-007](./ADR-007-worker-template-seeding.md) |

## Context

Worker discovery requires AWS region configuration to scan for EC2 instances. Currently:

| Configuration | Location | Behavior |
|---------------|----------|----------|
| `WORKER_DISCOVERY_REGIONS` | Environment variable | Comma-separated list of regions |
| `WORKER_DISCOVERY_AMI_NAME` | Environment variable | AMI name pattern to match |
| `AWS_REGION` | Environment variable | Default region fallback |

**Problems:**

1. **No runtime configurability**: Regions can only be changed via deployment
2. **No admin UI**: Operators cannot manage regions through the web interface
3. **No persistence**: Configuration is lost if environment isn't updated
4. **Inconsistent with other settings**: `SystemSettings` aggregate exists but doesn't include discovery regions

## Decision

**Make discovery regions configurable via both environment variables (initial defaults) AND the admin UI (runtime updates).**

### Configuration Hierarchy

```
1. SystemSettings.discovery_regions (MongoDB) ← Takes precedence if non-empty
2. WORKER_DISCOVERY_REGIONS (env var) ← Fallback / initial seeding value
3. [AWS_REGION] (env var) ← Final fallback (single region)
```

### SystemSettings Schema Update

Add `discovery_regions` to the `SystemSettings` aggregate:

```python
@dataclass
class DiscoverySettings:
    """Settings related to worker discovery."""

    enabled: bool = True
    regions: list[str] = field(default_factory=lambda: ["us-east-1"])
    ami_name_pattern: str = "CML-*"
    scan_interval_seconds: int = 300


class SystemSettingsState(AggregateState[str]):
    """Encapsulates the persisted state for the SystemSettings aggregate."""

    # ... existing fields ...
    discovery: DiscoverySettings
```

### Worker-Controller Behavior

The `WorkerReconciler._run_discovery_loop()` will:

1. **On startup**: Fetch `SystemSettings` from control-plane-api
2. **Periodically**: Re-fetch settings to detect region changes (every 5 minutes)
3. **Use regions from settings**: If `discovery.regions` is non-empty, use it
4. **Fall back to env var**: If settings not available or empty, use `WORKER_DISCOVERY_REGIONS`

> **Note:** Discovery was originally a standalone `WorkerDiscoveryService` (HostedService).
> Per AD-020, it has been consolidated into `WorkerReconciler` as an independent asyncio
> task running under leader election to prevent redundant AWS API calls across replicas.

```python
async def _get_discovery_regions(self) -> list[str]:
    """Get discovery regions with fallback chain."""
    try:
        settings = await self._api.get_system_settings()
        if settings and settings.discovery.regions:
            return settings.discovery.regions
    except Exception as e:
        logger.warning(f"Failed to fetch system settings: {e}")

    # Fallback to environment variable
    return self._settings.discovery_regions
```

## Rationale

### Benefits

1. **Runtime configurability**: Admins can add/remove regions without redeployment
2. **Consistent pattern**: Follows `SystemSettings` aggregate pattern (ADR-007)
3. **Safe fallback**: Environment variables provide reliable defaults
4. **Audit trail**: Changes to settings are tracked in MongoDB
5. **Multi-tenant ready**: Future support for per-tenant region configuration

### Trade-offs

- Worker-controller must periodically fetch settings (additional API calls)
- Settings changes require propagation delay (up to 5 minutes)
- Slightly more complex configuration logic

## Consequences

### New API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/settings/discovery` | GET | Get current discovery settings |
| `PATCH /api/settings/discovery` | PATCH | Update discovery settings |

### UI Changes

Add "Discovery Settings" section to Admin Settings page:

```html
<div class="card">
    <div class="card-header">
        <h5>Worker Discovery</h5>
    </div>
    <div class="card-body">
        <div class="mb-3">
            <label>Discovery Enabled</label>
            <input type="checkbox" id="discovery-enabled">
        </div>
        <div class="mb-3">
            <label>AWS Regions</label>
            <select multiple id="discovery-regions">
                <option value="us-east-1">US East (N. Virginia)</option>
                <option value="us-east-2">US East (Ohio)</option>
                <option value="us-west-1">US West (N. California)</option>
                <option value="us-west-2">US West (Oregon)</option>
                <option value="eu-west-1">Europe (Ireland)</option>
                <!-- ... more regions ... -->
            </select>
        </div>
        <div class="mb-3">
            <label>AMI Name Pattern</label>
            <input type="text" id="ami-pattern" placeholder="CML-*">
        </div>
        <div class="mb-3">
            <label>Scan Interval (seconds)</label>
            <input type="number" id="scan-interval" min="60" max="3600">
        </div>
        <button class="btn btn-primary" onclick="saveDiscoverySettings()">
            Save Settings
        </button>
    </div>
</div>
```

### Internal API Changes

Add endpoint for worker-controller to fetch settings:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/internal/settings/discovery` | GET | Get discovery settings (internal) |

### Seed Data Update

Update `data/seeds/system_settings.yaml`:

```yaml
id: default
worker_provisioning:
  ami_name_default: "my-cml2.7.0-lablet-v0.1.0"
  # ... existing ...
monitoring:
  worker_metrics_poll_interval_seconds: 300
idle_detection:
  enabled: true
  timeout_minutes: 60
discovery:
  enabled: true
  regions:
    - us-east-1
  ami_name_pattern: "CML-*"
  scan_interval_seconds: 300
```

## Implementation Phases

### Phase 1: SystemSettings Update

- [ ] Add `DiscoverySettings` dataclass
- [ ] Update `SystemSettingsState` to include `discovery`
- [ ] Update seed data YAML
- [ ] Update `SystemSettingsSeeder` to handle new field

### Phase 2: API Endpoints

- [ ] Add `GET /api/settings/discovery` query
- [ ] Add `PATCH /api/settings/discovery` command
- [ ] Add `GET /api/internal/settings/discovery` query
- [ ] Add to `ControlPlaneApiClient` in lcm-core

### Phase 3: Worker-Controller Integration

- [ ] Update `WorkerReconciler._run_discovery_loop()` to fetch settings
- [ ] Implement settings cache with TTL
- [ ] Add fallback chain logic

### Phase 4: Admin UI

- [ ] Create Discovery Settings card in settings page
- [ ] Implement region multi-select
- [ ] Implement save/load functionality
- [ ] Add validation for region list
