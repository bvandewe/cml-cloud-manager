# Lab CRUD Operations - Complete Implementation

## Overview

Complete implementation of lab CRUD (Create, Read, Update, Delete) operations in the Lablet Cloud Manager, providing users with comprehensive lab management capabilities through an intuitive UI.

## Features Implemented ✅

### 1. Read Operations

- **List Labs**: View all labs on a worker with state, owner, and statistics
- **Refresh Labs**: Force reload of lab data from CML API
- **Download Lab YAML**: Export lab topology definition to local file

### 2. Create/Import Operations

- **Import Lab**: Upload YAML file to create new lab on worker
- **File Validation**: YAML extension check (.yaml, .yml)
- **File Picker**: Bootstrap-integrated upload UI

### 3. Update Operations

- **Start Lab**: Activate stopped lab (starts all nodes)
- **Stop Lab**: Halt running lab (requires confirmation)
- **Wipe Lab**: Reset lab state to initial configuration (requires confirmation)

### 4. Delete Operations

- **Delete Lab**: Permanently remove lab from worker (requires confirmation)
- **Confirmation Dialog**: Danger modal with warning message
- **Non-recoverable**: Intentional design - no trash/undo functionality

## Architecture Implementation

### Backend Stack (Complete)

**CML API Client** (`integration/services/cml_api_client.py`):

```python
class CMLApiClient:
    async def get_labs(self) -> list[dict]
    async def start_lab(self, lab_id: str) -> dict
    async def stop_lab(self, lab_id: str) -> dict
    async def wipe_lab(self, lab_id: str) -> dict
    async def download_lab(self, lab_id: str) -> str  # Returns YAML
    async def import_lab(self, yaml_content: str, title: str | None = None) -> dict
    async def delete_lab(self, lab_id: str) -> bool  # Returns success status
```

**CQRS Commands** (`application/commands/*.py`):

- `GetLabsQuery` - List all labs for worker
- `RefreshLabsCommand` - Force refresh from CML API
- `StartLabCommand` - Start stopped lab
- `StopLabCommand` - Stop running lab
- `WipeLabCommand` - Wipe lab state
- `DownloadLabCommand` - Download lab YAML
- `ImportLabCommand` - Import lab from YAML file
- `DeleteLabCommand` - Permanently delete lab

**REST Endpoints** (`api/controllers/labs_controller.py`):

```python
GET  /api/labs/region/{region}/workers/{worker_id}                     # List labs
POST /api/labs/region/{region}/workers/{worker_id}/refresh             # Refresh
POST /api/labs/region/{region}/workers/{worker_id}/labs/{lab_id}/start # Start
POST /api/labs/region/{region}/workers/{worker_id}/labs/{lab_id}/stop  # Stop
POST /api/labs/region/{region}/workers/{worker_id}/labs/{lab_id}/wipe  # Wipe
POST /api/labs/region/{region}/workers/{worker_id}/labs/{lab_id}/download # Download
POST /api/labs/region/{region}/workers/{worker_id}/import              # Import
POST /api/labs/region/{region}/workers/{worker_id}/labs/{lab_id}/delete # Delete
```

### Frontend Stack (Complete)

**API Client** (`ui/src/scripts/api/workers.js`):

```javascript
export async function getLabs(region, workerId)
export async function refreshLabs(region, workerId)
export async function startLab(region, workerId, labId)
export async function stopLab(region, workerId, labId)
export async function wipeLab(region, workerId, labId)
export async function downloadLab(region, workerId, labId)
export async function importLab(region, workerId, formData)  // FormData with file
export async function deleteLab(region, workerId, labId)
```

**UI Handlers** (`ui/src/scripts/ui/worker-labs.js`):

```javascript
export async function loadLabsTab(region, workerId)           // Render labs tab
export async function handleStartLab(region, workerId, labId)
export async function handleStopLab(region, workerId, labId, labTitle)
export async function handleWipeLab(region, workerId, labId, labTitle)
export async function handleDownloadLab(region, workerId, labId, labTitle)
export async function handleLabFileSelected(event, region, workerId)  // File picker
export async function handleImportLab(region, workerId, labId, labTitle)
export async function handleDeleteLab(region, workerId, labId, labTitle)
```

**Global Exports** (`ui/src/scripts/ui/workers.js`):

```javascript
window.workersApp = {
    // ... other exports
    handleStartLab,
    handleStopLab,
    handleWipeLab,
    handleDeleteLab,
    handleDownloadLab,
    handleLabFileSelected,
    handleImportLab,
};
```

## UI Component Design

### Labs Tab Layout

```
┌─────────────────────────────────────────────────────────────┐
│ Labs (3) [Refresh] [Upload Lab YAML]                        │
├─────────────────────────────────────────────────────────────┤
│ ▼ Lab Title 1 [STARTED]                                     │
│   ├─ Description: Network topology for testing              │
│   ├─ Owner: admin                                           │
│   ├─ ID: lab-abc123                                         │
│   ├─ Nodes: 5 | Links: 6 | State: STARTED                   │
│   ├─ Controls:                                              │
│   │   [Start] [Stop] [Wipe]                                 │
│   │   [Download YAML] [Delete Lab]                          │
│   └─ Note: Stop, Wipe, and Delete require confirmation      │
├─────────────────────────────────────────────────────────────┤
│ ▶ Lab Title 2 [STOPPED]                                     │
├─────────────────────────────────────────────────────────────┤
│ ▶ Lab Title 3 [DEFINED_ON_CORE]                             │
└─────────────────────────────────────────────────────────────┘
```

### Button Groups Organization

**Group 1: State Management** (State-dependent actions)

- `[Start]` - Green, enabled when lab stopped
- `[Stop]` - Yellow/Warning, enabled when lab running, requires confirmation
- `[Wipe]` - Red/Danger, always enabled, requires confirmation

**Group 2: Data Management** (Always available actions)

- `[Download YAML]` - Blue/Primary, no confirmation
- `[Delete Lab]` - Red/Danger, requires confirmation

### Confirmation Dialogs

**Stop Lab** (Warning Modal):

```
⚠️ Confirm Stop
Are you sure you want to stop lab 'Lab Title'?
This will halt all running nodes.
[Cancel] [Stop Lab]
```

**Wipe Lab** (Danger Modal):

```
⛔ Confirm Wipe
Are you sure you want to wipe lab 'Lab Title'?
This will permanently delete all node state and configuration changes.
[Cancel] [Wipe Lab]
```

**Delete Lab** (Danger Modal):

```
⛔ Confirm Delete
Are you sure you want to permanently delete lab 'Lab Title'?
This action cannot be undone and will remove the lab and all its data from the worker.
[Cancel] [Delete Lab]
```

## User Workflows

### Importing a Lab

1. Click "Upload Lab YAML" at top of Labs tab
2. File picker opens (accepts .yaml, .yml only)
3. Select YAML file from disk
4. Frontend reads file, validates extension
5. Creates FormData with file content
6. Backend processes upload, extracts YAML
7. CML API imports lab: `POST /api/v0/import?is_json=false`
8. Success toast: "Lab imported successfully: {title}"
9. Labs list refreshes, new lab appears

### Downloading a Lab

1. Expand lab accordion
2. Click "Download YAML" button
3. Backend fetches YAML: `GET /api/v0/labs/{lab_id}/download`
4. Frontend creates Blob from YAML content
5. Browser downloads file: `{labTitle}_{labId}.yaml`
6. Success toast: "Lab downloaded successfully"

### Deleting a Lab

1. Expand lab accordion
2. Click "Delete Lab" button (red, danger styling)
3. Confirmation modal appears with warning
4. User clicks "Delete Lab" button in modal
5. Frontend calls: `POST /api/labs/.../labs/{lab_id}/delete`
6. Backend calls: `DELETE /api/v0/labs/{lab_id}`
7. Success toast: "Lab deleted successfully: {title}"
8. Labs list refreshes, lab no longer visible

## Technical Implementation Details

### Delete Operation Flow

**Command Pattern**:

```python
@dataclass
class DeleteLabCommand(Command[OperationResult[dict]]):
    worker_id: str
    lab_id: str

class DeleteLabCommandHandler(CommandHandler[DeleteLabCommand, OperationResult[dict]]):
    def __init__(self, worker_repository: CMLWorkerRepository):
        self._worker_repository = worker_repository

    async def handle_async(self, request, cancellation_token=None):
        # 1. Validate worker exists
        worker = await self._worker_repository.get_by_id_async(request.worker_id, cancellation_token)
        if not worker:
            return self.not_found("Worker", f"Worker with ID {request.worker_id} not found")

        # 2. Validate worker endpoint
        if not worker.state.https_endpoint:
            return self.bad_request("Worker does not have an HTTPS endpoint configured")

        # 3. Create CML client via factory
        client = CMLApiClientFactory.create(base_url=worker.state.https_endpoint)

        # 4. Delete lab via CML API
        success = await client.delete_lab(request.lab_id)

        # 5. Return result
        return self.ok({
            "success": success,
            "lab_id": request.lab_id,
            "message": "Lab deleted successfully"
        })
```

**CML API Client**:

```python
async def delete_lab(self, lab_id: str) -> bool:
    """Delete a lab permanently."""
    response = await self._request(
        method="DELETE",
        path=f"/api/v0/labs/{lab_id}",
        expected_statuses=[200, 204]
    )
    return response.status_code in [200, 204]
```

**Frontend Handler**:

```javascript
export async function handleDeleteLab(region, workerId, labId, labTitle) {
    // Show confirmation dialog
    const confirmed = await showModal(
        'Confirm Delete',
        `Are you sure you want to permanently delete lab '${labTitle}'?<br><br>` +
        `<strong class='text-danger'>This action cannot be undone</strong> and will remove the lab and all its data from the worker.`,
        'danger',
        'Delete Lab'
    );

    if (!confirmed) return;

    try {
        // Call API
        const result = await deleteLab(region, workerId, labId);

        // Show success toast
        showToast(`Lab deleted successfully: ${labTitle}`, 'success');

        // Reload labs
        await loadLabsTab(region, workerId);
    } catch (error) {
        showToast(`Failed to delete lab: ${error.message}`, 'danger');
    }
}
```

### File Upload FormData Pattern

**Problem**: Setting `Content-Type: application/json` breaks multipart file uploads

**Solution**: Auto-detect FormData and let browser set headers

```javascript
// client.js - apiRequest function
if (options.body instanceof FormData) {
    // Don't set Content-Type - browser will set multipart/form-data with boundary
} else {
    headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(options.body);
}
```

**Usage**:

```javascript
const formData = new FormData();
formData.append('file', file);
formData.append('title', title);  // Optional
await importLab(region, workerId, formData);
```

## Files Modified/Created

### Backend Files Created

- `src/application/commands/delete_lab_command.py` - Delete lab command and handler
- `src/application/commands/download_lab_command.py` - Download lab command and handler
- `src/application/commands/import_lab_command.py` - Import lab command and handler
- `src/application/commands/start_lab_command.py` - Start lab command and handler
- `src/application/commands/stop_lab_command.py` - Stop lab command and handler
- `src/application/commands/wipe_lab_command.py` - Wipe lab command and handler
- `src/application/commands/refresh_labs_command.py` - Refresh labs command and handler
- `src/application/queries/get_labs_query.py` - Get labs query and handler
- `src/api/controllers/labs_controller.py` - All lab management endpoints

### Backend Files Modified

- `src/integration/services/cml_api_client.py` - Added 7 lab operation methods
- `src/application/commands/__init__.py` - Exported all lab commands

### Frontend Files Modified

- `src/ui/src/scripts/api/workers.js` - Added 8 lab API functions
- `src/ui/src/scripts/ui/worker-labs.js` - Added 8 lab handlers + UI rendering
- `src/ui/src/scripts/ui/workers.js` - Exported handlers to window.workersApp
- `src/ui/src/scripts/api/client.js` - Fixed FormData detection

## CML API Endpoints Used

| Endpoint | Method | Purpose | Request | Response |
|----------|--------|---------|---------|----------|
| `/api/v0/labs` | GET | List all labs | - | JSON array |
| `/api/v0/labs/{lab_id}/start` | PUT | Start lab | - | Lab state JSON |
| `/api/v0/labs/{lab_id}/stop` | PUT | Stop lab | - | Lab state JSON |
| `/api/v0/labs/{lab_id}/wipe` | PUT | Wipe lab | - | Lab state JSON |
| `/api/v0/labs/{lab_id}/download` | GET | Download YAML | - | YAML text |
| `/api/v0/import?is_json=false` | POST | Import lab | YAML body | Lab details JSON |
| `/api/v0/labs/{lab_id}` | DELETE | Delete lab | - | 200/204 status |

## Testing Checklist ✅

### Delete Feature

- [x] Backend: `DeleteLabCommand` created with worker validation
- [x] Backend: `CMLApiClient.delete_lab()` method implemented
- [x] Backend: Controller endpoint `POST /labs/.../delete`
- [x] Backend: Command registered in `__init__.py`
- [x] Frontend: API function `deleteLab()` implemented
- [x] Frontend: Handler `handleDeleteLab()` with danger confirmation
- [x] Frontend: Delete button added to lab controls (separate group)
- [x] Frontend: Handler exported to `window.workersApp`
- [x] Frontend: Confirmation message includes "cannot be undone" warning
- [x] Build: UI rebuilt with `make build-ui`

### Download Feature

- [x] Backend: `DownloadLabCommand` created
- [x] Backend: `CMLApiClient.download_lab()` method
- [x] Backend: Controller endpoint `POST /labs/.../download`
- [x] Frontend: `downloadLab()` API function
- [x] Frontend: `handleDownloadLab()` with blob download
- [x] Frontend: Download button in lab controls
- [x] Build: UI rebuilt

### Import Feature

- [x] Backend: `ImportLabCommand` created
- [x] Backend: `CMLApiClient.import_lab()` with YAML support
- [x] Backend: Controller endpoint accepts multipart/form-data
- [x] Frontend: `importLab()` with FormData
- [x] Frontend: File picker with YAML validation
- [x] Frontend: `handleLabFileSelected()` file reader
- [x] Frontend: Upload button at top of Labs tab
- [x] Fix: `client.js` FormData detection
- [x] Build: UI rebuilt

## Security Considerations

### Authentication

- All endpoints require authentication via `get_current_user` dependency
- Supports both JWT (bearer token) and cookie-based authentication
- Session-based auth preferred for UI operations

### Authorization

- Worker validation ensures user can only access authorized workers
- No RBAC enforcement yet (all authenticated users can perform all operations)
- Future: Role-based restrictions (e.g., only admins can delete labs)

### Input Validation

- File upload: Extension validation (.yaml, .yml only)
- Worker ID validation: Ensures worker exists before operations
- Lab ID validation: Passed through to CML API for validation
- YAML parsing: Handled by CML API (backend passes through raw content)

### Destructive Operations

- Stop, Wipe, Delete require explicit user confirmation
- Confirmation dialogs clearly state consequences
- No undo functionality (intentional design for simplicity)
- Toast notifications confirm successful operations

## Future Enhancements

### Planned Features

- **Lab Creation UI**: Form-based lab creation with templates
- **Lab Cloning**: Duplicate existing lab with new ID
- **Bulk Operations**: Start/stop/delete multiple labs at once
- **Lab Search**: Filter labs by name, owner, state
- **Lab Templates**: Pre-configured topologies for common use cases
- **Lab Sharing**: Export/import labs between workers
- **Lab Snapshots**: Save/restore lab state at specific points
- **Lab Diff Viewer**: Compare lab YAML before/after changes
- **Lab Trash/Recovery**: Soft delete with 7-day recovery period

### Technical Improvements

- **Real-time Updates**: SSE for lab state changes
- **Optimistic UI**: Update UI before API response for faster UX
- **Lab Validation**: Pre-import YAML syntax/schema validation
- **Batch Import**: Upload multiple YAML files at once
- **Operation History**: Audit log of all lab operations
- **Resource Monitoring**: Per-lab CPU/memory/storage usage
- **Auto-cleanup**: Delete labs idle for >N days
- **Lab Access Control**: Owner vs shared lab permissions

## Known Limitations

### Current Constraints

- **No Undo**: Delete operation is permanent and immediate
- **No Validation**: YAML validation happens only on CML side
- **No Versioning**: Can't track lab changes over time
- **No Notifications**: No email/Slack alerts for lab events
- **Single File Upload**: Can't batch import multiple labs
- **No Preview**: Can't preview YAML before import
- **No Templates**: Must provide complete YAML topology

### Design Decisions

- **Permanent Delete**: Intentionally simple - no trash/recovery
  - Rationale: Reduces complexity, matches CML API behavior
  - Mitigation: Confirmation dialog with clear warning
- **YAML Only**: No JSON import support
  - Rationale: CML API prefers YAML for topology definitions
  - Note: `is_json=false` parameter required for import endpoint
- **No Inline Editing**: Can't edit lab YAML in UI
  - Rationale: Complex editor out of scope for v1
  - Workaround: Download → edit locally → delete → re-import

## Related Documentation

- CML API Spec: `notes/cml_v2.9_openapi.json`
- Lab Storage: `notes/LABS_INTEGRATION_COMPLETE.md`
- Authentication: `notes/AUTHENTICATION_ARCHITECTURE.md`
- Worker Monitoring: `notes/WORKER_MONITORING_ARCHITECTURE.md`
- Frontend Refactor: `notes/FRONTEND_REFACTOR_PLAN.md`

## Completion Status

**Backend Implementation**: ✅ Complete (8 operations)
**Frontend Implementation**: ✅ Complete (8 handlers)
**UI Components**: ✅ Complete (buttons, modals, file picker)
**Documentation**: ✅ Complete
**Testing**: ⏳ Pending manual validation

All CRUD operations for lab management are fully implemented across the stack with proper error handling, user confirmations, and feedback mechanisms.
