# Phase 5: UI Changes — Bootstrap Prompt

**Purpose**: Self-contained bootstrap prompt for the next AI coding session to implement Phase 5 of the Content Synchronization feature.
**Copy everything below the line into the next session.**

---

## Context

You are implementing **Phase 5 (UI Changes)** of the Content Synchronization feature for the **Lablet Cloud Manager** project. Phases 1–4 are complete. This phase updates the **control-plane-api** Bootstrap 5 SPA to support the new content sync workflow.

### Knowledge Manager Session

At the **START** of the conversation, run:

```
mcp_knowledge_recall_session(workspace_id="lablet-cloud-manager", focus_hint="Phase 5 UI content synchronization definitions form sync button")
```

Then set focus:

```
mcp_knowledge_set_focus(workspace_id="lablet-cloud-manager", name="Phase 5: UI Content Sync", description="UI changes for content synchronization: form updates, sync button, status badges, metadata display", priority_files=["src/control-plane-api/ui/src/scripts/components/pages/LabletsPage.js", "src/control-plane-api/ui/src/scripts/ui/lablet-modals.js", "src/control-plane-api/ui/src/templates/components/lablet_definitions.jinja", "src/control-plane-api/ui/src/scripts/api/lablet-definitions.js", "src/control-plane-api/ui/src/scripts/components/LabletDefinitionCard.js"])
```

### What Was Already Done (Phases 1–4)

- **Phase 1**: Domain model expanded — `LabletDefinitionState` now has: `form_qualified_name`, `bucket_name`, `user_session_package_name`, `grading_ruleset_package_name`, `user_session_type`, `user_session_default_region`, `content_package_hash`, `upstream_version`, `upstream_date_published`, `upstream_instance_name`, `upstream_form_id`, `grade_xml_path`, `cml_yaml_path`, `cml_yaml_content`, `devices_json`, `port_template`, `upstream_sync_status`, `sync_status`, `last_synced_at`
- **Phase 2**: CPA commands updated — `CreateLabletDefinitionCommand` accepts new fields. `SyncLabletDefinitionCommand` triggers content sync. `RecordContentSyncResultCommand` records results. Internal API endpoints exist: `GET /api/internal/lablet-definitions?sync_status=sync_requested` and `POST /api/internal/lablet-definitions/{id}/content-synced`
- **Phase 3**: Integration clients created (S3, Mosaic, EnvironmentResolver, OAuth2TokenManager) in lablet-controller
- **Phase 4**: `ContentSyncService` created — etcd watch + sync pipeline in lablet-controller

### Implementation Plan Reference

Read the full Phase 5 spec: `docs/implementation/content_synchronization.md` — Section 7 (lines ~2593–2760). The plan covers:

- 7.1: Definitions tab — "Synchronize" action button (already partially implemented!)
- 7.2: Status badge styling (PENDING_SYNC + sync_status indicators)
- 7.3: Create Definition form update (new fields replacing lab_artifact_uri)
- 7.4: Definition detail modal — show content metadata

---

## UI Architecture Quick Reference

### Stack

- **Bootstrap 5** + **Vanilla JS** (ES modules) + **Parcel 2.12** bundler
- **Nunjucks/Jinja templates** rendered at build time → single SPA HTML page
- **Web Components** extending `BaseComponent` (from `@neuroglia/ui-core` lcm-core TypeScript library)
- **Build**: `cd src/control-plane-api && make build-ui` (runs Parcel → outputs to `static/`)

### Key Files to Modify

| File | What to Change |
|------|---------------|
| `ui/src/templates/components/lablet_definitions.jinja` | **Create Definition form HTML**: Replace `defLabArtifactUri` + `defLabYamlHash` with `form_qualified_name` field + new optional fields. Add bucket_name preview. Update detail modal template. |
| `ui/src/scripts/ui/lablet-modals.js` | **Form submit handler** (`setupCreateLabletDefinitionModal`): Update field gathering to use new field IDs, build new `definitionData` payload with `form_qualified_name`, `user_session_package_name`, etc. |
| `ui/src/scripts/components/pages/LabletsPage.js` | **Definition detail modal** (`_viewDefinition`): Add content sync metadata section. **DataTable columns** (`_configureDataTables`): Add sync_status column. **Edit handler** (`_editDefinition`): Update field population for new fields. **Action handler**: Add `sync` action to DataTable row actions. |
| `ui/src/scripts/components/LabletDefinitionCard.js` | **Card rendering**: Add sync_status badge, update detail fields. Sync button already exists (wired to `syncLabletDefinition` API). |
| `ui/src/scripts/api/lablet-definitions.js` | **No changes needed** — `syncLabletDefinition()` already exists. |

### Files to Read for Context (in order of importance)

1. **`ui/src/scripts/ui/lablet-modals.js`** (~lines 119–200) — The `setupCreateLabletDefinitionModal()` function. This is the **form submit handler** that gathers field values and calls the API. MUST be updated to use new field names.
2. **`ui/src/templates/components/lablet_definitions.jinja`** (~lines 65–210) — The HTML form template. MUST replace `defLabArtifactUri` and `defLabYamlHash` fields.
3. **`ui/src/scripts/components/pages/LabletsPage.js`** (1267 lines) — The page component. Key methods:
   - `_renderDefinitionsTab()` (~line 460) — renders DataTable card
   - `_configureDataTables()` (~line 500) — column config for definitions table
   - `_viewDefinition(id)` (~line 996) — detail modal rendering
   - `_editDefinition(id)` (~line 1050) — edit mode population
   - Click delegation (~line 640) — action routing
4. **`ui/src/scripts/components/LabletDefinitionCard.js`** (285 lines) — Card with sync button, status badge
5. **`ui/src/scripts/components/LabletDefinitionList.js`** (302 lines) — List/grid of cards

### Patterns You MUST Follow

**Toast notifications:**

```javascript
import { showToast } from '../ui/notifications.js';
showToast('Definition created successfully', 'success');
showToast(error.message || 'Failed to sync', 'error');
```

**API calls** (always via `apiRequest` with `credentials: 'include'`):

```javascript
import { apiRequest } from './client.js';
const response = await apiRequest('/api/lablet-definitions/', { method: 'POST', body: JSON.stringify(data) });
```

**Status badge** (web component from lcm-core):

```html
<lcm-status-badge status="${def.status}"></lcm-status-badge>
```

**DataTable** (web component from lcm-core):

```javascript
definitionsTable.setColumns([
    { field: 'name', label: 'Name', sortable: true },
    { field: 'status', label: 'Status', render: val => `<lcm-status-badge status="${val}"></lcm-status-badge>` },
    // ...
]);
```

---

## Task Breakdown

### Task 5.1: Update Create Definition Form (Jinja template)

**File**: `ui/src/templates/components/lablet_definitions.jinja`

Changes to the `createLabletDefinitionForm`:

1. **Replace** `defLabArtifactUri` field with `defFormQualifiedName` field:
   - Label: "Form Qualified Name *"
   - Placeholder: "e.g., Exam Associate CCNA v1.1 LAB 1.3a"
   - Help text: "Format: {trackType} {trackLevel} {trackAcronym} {examVersion} {moduleAcronym} {formName}"
   - Required, no restrictive pattern (allow spaces and mixed case)
2. **Replace** `defLabYamlHash` field with a read-only `bucket_name_preview` element:
   - Shows auto-derived bucket name (slugified FQN) as live preview
   - Add inline `<script>` for live slugification (lowercase, spaces→dashes, strip non-alphanumeric)
3. **Add** new optional fields after the existing Resource Requirements section:
   - `defUserSessionPackageName` (text, default "SVN.zip") — Package filename
   - `defGradingRulesetPackageName` (text, default "SVN.zip") — Grading ruleset filename
   - `defUserSessionType` (select: LDS, other options TBD, default "LDS")
   - `defUserSessionDefaultRegion` (text, optional) — Default AWS region

### Task 5.2: Update Form Submit Handler (lablet-modals.js)

**File**: `ui/src/scripts/ui/lablet-modals.js` — function `setupCreateLabletDefinitionModal()`

Changes:

1. Replace `labArtifactUri` gathering with `formQualifiedName = document.getElementById('defFormQualifiedName')?.value?.trim()`
2. Remove `labYamlHash` gathering
3. Add new field gathering: `userSessionPackageName`, `gradingRulesetPackageName`, `userSessionType`, `userSessionDefaultRegion`
4. Update validation: require `name`, `version`, `formQualifiedName` (instead of `labArtifactUri`)
5. Update `definitionData` payload:

   ```javascript
   const definitionData = {
       name,
       version,
       form_qualified_name: formQualifiedName,
       user_session_package_name: userSessionPackageName || 'SVN.zip',
       grading_ruleset_package_name: gradingRulesetPackageName || 'SVN.zip',
       user_session_type: userSessionType || 'LDS',
       user_session_default_region: userSessionDefaultRegion || null,
       cpu_cores: cpuCores,
       memory_gb: memoryGb,
       // ... rest unchanged
   };
   ```

### Task 5.3: Update DataTable Columns + Row Actions (LabletsPage.js)

**File**: `ui/src/scripts/components/pages/LabletsPage.js`

Changes to `_configureDataTables()`:

1. Add `form_qualified_name` column (or replace `description` if too wide)
2. Add `sync_status` column with badge rendering:

   ```javascript
   {
       field: 'sync_status',
       label: 'Sync',
       render: val => val ? `<lcm-status-badge status="${val}"></lcm-status-badge>` : '<span class="text-muted">—</span>',
   }
   ```

3. Add a **Sync** button to the Actions column:

   ```javascript
   <button class="btn btn-outline-info" data-action="sync" data-id="${row.id}" title="Sync content">
       <i class="bi bi-arrow-repeat"></i>
   </button>
   ```

4. Add `case 'sync'` to the click delegation switch statement, calling a new `_syncDefinition(id)` method

Add new method `_syncDefinition(definitionId)`:

```javascript
async _syncDefinition(definitionId) {
    try {
        await labletDefinitionsApi.syncLabletDefinition(definitionId);
        showToast('Sync requested — content will be synchronized shortly.', 'success');
        this._refreshDefinitions();
    } catch (error) {
        showToast(`Sync failed: ${error.message}`, 'error');
    }
}
```

### Task 5.4: Update Definition Detail Modal (LabletsPage.js)

**File**: `ui/src/scripts/components/pages/LabletsPage.js`

Changes to `_viewDefinition()`:

1. Replace "Artifact URI" row with "Form Qualified Name"
2. Replace "YAML Hash" row with "Bucket Name"
3. Add a new **Content Synchronization** section below the existing info:

   ```html
   <h6 class="text-muted mb-2 mt-3">Content Synchronization</h6>
   <dl class="row mb-0">
       <dt class="col-sm-5">Sync Status</dt>
       <dd class="col-sm-7"><lcm-status-badge status="${def.sync_status || 'none'}"></lcm-status-badge></dd>
       <dt class="col-sm-5">Content Hash</dt>
       <dd class="col-sm-7"><code class="small">${def.content_package_hash || '—'}</code></dd>
       <dt class="col-sm-5">Upstream Version</dt>
       <dd class="col-sm-7">${def.upstream_version || '—'}</dd>
       <dt class="col-sm-5">Date Published</dt>
       <dd class="col-sm-7">${def.upstream_date_published || '—'}</dd>
       <dt class="col-sm-5">Mosaic Instance</dt>
       <dd class="col-sm-7">${def.upstream_instance_name || '—'}</dd>
       <dt class="col-sm-5">Package</dt>
       <dd class="col-sm-7">${def.user_session_package_name || '—'}</dd>
       <dt class="col-sm-5">Last Synced</dt>
       <dd class="col-sm-7">${def.last_synced_at ? this._formatDateTime(def.last_synced_at) : 'Never'}</dd>
   </dl>
   ```

4. Add a **Sync button** in the modal footer (next to Close):

   ```html
   <button class="btn btn-outline-primary sync-definition-btn" data-definition-id="${def.id}">
       <i class="bi bi-arrow-repeat"></i> Synchronize
   </button>
   ```

### Task 5.5: Update Edit Definition Handler (LabletsPage.js)

**File**: `ui/src/scripts/components/pages/LabletsPage.js`

Changes to `_editDefinition()`:

1. Replace `this._setFormValue('defLabArtifactUri', def.lab_artifact_uri)` with `this._setFormValue('defFormQualifiedName', def.form_qualified_name)`
2. Replace `this._setFormValue('defLabYamlHash', def.lab_yaml_hash)` with new fields:

   ```javascript
   this._setFormValue('defUserSessionPackageName', def.user_session_package_name);
   this._setFormValue('defGradingRulesetPackageName', def.grading_ruleset_package_name);
   this._setFormValue('defUserSessionType', def.user_session_type);
   this._setFormValue('defUserSessionDefaultRegion', def.user_session_default_region);
   ```

### Task 5.6: Update LabletDefinitionCard (status + metadata)

**File**: `ui/src/scripts/components/LabletDefinitionCard.js`

Changes:

1. Add `sync_status` badge next to the existing status badge in the card header
2. Update the card body to show `form_qualified_name` instead of (or in addition to) `lab_artifact_uri`
3. Optionally show `last_synced_at` timestamp
4. The Sync button already exists and works — no changes needed to the sync handler

### Task 5.7: Verify & Build

1. Run `cd src/control-plane-api && make build-ui` to verify Parcel build succeeds
2. Check for JS errors in browser console
3. Run `cd src/control-plane-api && make lint` to verify no Python regressions

---

## Verification Checklist

- [ ] Create Definition form shows `form_qualified_name` field (not `lab_artifact_uri`)
- [ ] Bucket name preview updates live as user types FQN
- [ ] Form submit sends correct payload with new field names
- [ ] Definitions DataTable shows sync_status column
- [ ] Sync button in DataTable row triggers API call and shows toast
- [ ] Definition detail modal shows content sync metadata section
- [ ] Definition detail modal has Sync button
- [ ] Edit mode populates new fields correctly
- [ ] LabletDefinitionCard shows sync_status badge
- [ ] `make build-ui` succeeds without errors
- [ ] No JS console errors at runtime

---

## API Payload Reference

### Create Definition (POST /api/lablet-definitions/)

```json
{
    "name": "cisco-netacad-lab-01",
    "version": "1.0.0",
    "form_qualified_name": "Exam Associate CCNA v1.1 LAB 1.3a",
    "user_session_package_name": "SVN.zip",
    "grading_ruleset_package_name": "SVN.zip",
    "user_session_type": "LDS",
    "user_session_default_region": "us-east-1",
    "cpu_cores": 2,
    "memory_gb": 4,
    "storage_gb": 20,
    "nested_virt": true,
    "node_count": 3,
    "max_duration_minutes": 60,
    "license_affinity": ["enterprise"],
    "warm_pool_depth": 0
}
```

### Definition DTO Response (new fields)

```json
{
    "id": "uuid",
    "name": "cisco-netacad-lab-01",
    "version": "1.0.0",
    "status": "active",
    "form_qualified_name": "Exam Associate CCNA v1.1 LAB 1.3a",
    "bucket_name": "exam-associate-ccna-v1.1-lab-1.3a",
    "user_session_package_name": "SVN.zip",
    "grading_ruleset_package_name": "SVN.zip",
    "user_session_type": "LDS",
    "user_session_default_region": "us-east-1",
    "sync_status": "success",
    "content_package_hash": "sha256:abc123...",
    "upstream_version": "2.1.0",
    "upstream_date_published": "2026-02-20T10:00:00Z",
    "upstream_instance_name": "mosaic-prod",
    "upstream_form_id": "form-123",
    "grade_xml_path": "content/grade.xml",
    "cml_yaml_path": "content/cml.yaml",
    "last_synced_at": "2026-02-25T14:30:00Z",
    "upstream_sync_status": {
        "lds": {"status": "success", "synced_at": "...", "version": "2.1.0"}
    }
}
```

### Sync Definition (POST /api/lablet-definitions/{id}/sync)

No request body. Returns `202 Accepted` with sync confirmation.
