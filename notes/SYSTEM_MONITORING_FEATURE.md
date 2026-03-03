# System Monitoring Feature - Implementation Summary

## Overview

Extended the Lablet Cloud Manager frontend to expose background services and system internals through a comprehensive monitoring dashboard. This enables administrators and managers to observe the internal workings of the application including schedulers, monitoring services, health checks, and metrics collectors.

## Backend API Endpoints

### SystemController (`src/api/controllers/system_controller.py`)

All endpoints require authentication. Most endpoints are restricted to admin/manager roles.

#### 1. **GET /api/system/health**

- **Purpose**: Overall system health status
- **Access**: All authenticated users
- **Response**: Health status of all components (database, schedulers, monitoring)
- **Use Case**: Quick overview of system operational status

#### 2. **GET /api/system/scheduler/jobs**

- **Purpose**: List all APScheduler jobs with details
- **Access**: Admin, Manager
- **Response**: Array of job objects with ID, name, next run time, trigger, function
- **Use Case**: Monitor background task execution

#### 3. **GET /api/system/scheduler/status**

- **Purpose**: APScheduler overall status and statistics
- **Access**: Admin, Manager
- **Response**: Running state, job count, summary of jobs
- **Use Case**: Verify scheduler is operational

#### 4. **GET /api/system/monitoring/workers**

- **Purpose**: Worker monitoring service status
- **Access**: Admin, Manager
- **Response**: Monitoring scheduler status, active monitoring jobs
- **Use Case**: Verify worker monitoring is active

#### 5. **GET /api/system/metrics/collectors**

- **Purpose**: Status of all metrics collectors
- **Access**: Admin, Manager
- **Response**: List of collectors with status, intervals, error counts
- **Use Case**: Monitor metrics collection health

## Frontend Components

### 1. System Monitoring Dashboard (`src/ui/src/templates/components/system.jinja`)

**Overview Cards:**

- System Status (overall health badge)
- Scheduler Jobs (count and status)
- Worker Monitoring (active/inactive)
- Metrics Collectors (active count)

**Tabbed Interface:**

- **Health Tab**: Component-level health status cards
- **Scheduler Tab**: Detailed table of APScheduler jobs
- **Monitoring Tab**: Worker monitoring service details
- **Collectors Tab**: Metrics collectors status table

**Features:**

- Auto-refresh every 30 seconds
- Manual refresh buttons for scheduler and collectors tabs
- Bootstrap-based responsive design
- Loading states with spinners
- Empty states with informative messages

### 2. System API Client (`src/ui/src/scripts/api/system.js`)

JavaScript module providing typed functions for all system endpoints:

- `getSystemHealth()`
- `getSchedulerJobs()`
- `getSchedulerStatus()`
- `getWorkerMonitoringStatus()`
- `getMetricsCollectorsStatus()`

### 3. System UI Logic (`src/ui/src/scripts/ui/system.js`)

Main UI controller with:

- `initializeSystemView()` - Entry point, sets up event listeners
- Tab-specific loaders for each panel
- HTML rendering functions for each data type
- Helper functions for formatting dates, badges, component names
- Global refresh functions exposed via `window.systemApp`

### 4. System Styles (`src/ui/src/styles/components/_system.scss`)

SCSS styling for:

- Card hover effects
- Tab styling
- Table code blocks
- Badge formatting
- Loading states
- Health component cards

## Integration

### Navigation

- Added "System" tab to navbar with admin-only visibility (`admin-only-nav` class)
- Icon: Bootstrap's gear icon (`bi-gear`)
- Position: After Workers tab

### App Router (`src/ui/src/scripts/app.js`)

- Added system view to `showView()` function
- New navigation handler for system tab
- Auto-hide/show system section based on active view
- Imports system UI module

### Authentication (`src/ui/src/scripts/ui/auth.js`)

- Enhanced `showDashboard()` to control admin-only navigation visibility
- Checks for admin/manager roles to show/hide system tab
- Role-based access control integrated with existing RBAC system

### Main Template (`src/ui/src/templates/index.jinja`)

- Included `components/system.jinja`
- System view added to container alongside tasks and workers

## RBAC Implementation

**Admin/Manager Access:**

- System tab visible in navigation
- All system monitoring endpoints accessible
- Full visibility into scheduler jobs, monitoring, and collectors

**User Access:**

- System tab hidden from navigation
- Can access health endpoint (useful for general status)
- Cannot access detailed system internals

## Technical Details

### Dependencies

- **Backend**: FastAPI, Neuroglia framework, APScheduler
- **Frontend**: Bootstrap 5, vanilla JavaScript ES6 modules
- **Integration**: Existing authentication flow via Keycloak

### Data Flow

1. User clicks System tab (admin/manager only)
2. `showView('system')` called in app.js
3. `initializeSystemView()` loads initial data
4. API calls made via system.js API client
5. Responses rendered using system.js UI functions
6. Auto-refresh keeps data current every 30 seconds

### Error Handling

- Try-catch blocks around all API calls
- Toast notifications for errors
- Fallback messages for empty/error states
- Loading spinners during data fetches

## Files Created/Modified

### Created Files

1. `src/api/controllers/system_controller.py` - Backend API controller
2. `src/ui/src/scripts/api/system.js` - Frontend API client
3. `src/ui/src/scripts/ui/system.js` - Frontend UI logic
4. `src/ui/src/templates/components/system.jinja` - Dashboard template
5. `src/ui/src/styles/components/_system.scss` - Component styles

### Modified Files

1. `src/api/controllers/__init__.py` - Registered SystemController
2. `src/ui/src/scripts/app.js` - Added system view routing
3. `src/ui/src/scripts/ui/auth.js` - Added RBAC for system tab
4. `src/ui/src/templates/index.jinja` - Included system component
5. `src/ui/src/templates/components/navbar.jinja` - Added system nav tab
6. `src/ui/src/styles/main.scss` - Imported system styles

## Verification

### Backend Status

✅ SystemController registered at `/api/system/*`
✅ 5 endpoints available in OpenAPI spec
✅ App restarted and running successfully

### Frontend Status

✅ UI builder compiled successfully (4.11s build time)
✅ Static assets generated (272KB CSS, 441KB JS)
✅ System component integrated into main app

## Usage Examples

### Accessing System Monitoring

1. Log in as admin or manager
2. Click "System" tab in navigation
3. View health overview cards
4. Switch between tabs for detailed information
5. Use refresh buttons to update data manually

### Health Check Response Example

```json
{
  "status": "healthy",
  "components": {
    "database": {
      "status": "healthy",
      "type": "mongodb"
    },
    "background_scheduler": {
      "status": "healthy",
      "running": true,
      "job_count": 3
    },
    "worker_monitoring": {
      "status": "healthy",
      "running": true
    }
  }
}
```

### Scheduler Jobs Response Example

```json
[
  {
    "id": "worker_health_check",
    "name": "Worker Health Check",
    "next_run_time": "2025-11-16T19:15:00",
    "trigger": "interval[0:01:00]",
    "func": "application.services.worker_monitoring.check_health",
    "pending": false
  }
]
```

## Future Enhancements

Potential additions to system monitoring:

- Real-time metrics charts (CPU, memory, API latency)
- Event stream viewer for CloudEvents
- Redis connection pool statistics
- AWS API call metrics and rate limits
- Historical trend analysis
- Alert configuration interface
- Job execution history with logs
- Manual job trigger capability
- System configuration viewer/editor

## Testing Recommendations

1. **Authentication Tests**: Verify RBAC for each endpoint
2. **Integration Tests**: Test data flow from backend to frontend
3. **UI Tests**: Verify tab switching, auto-refresh, manual refresh
4. **Error Handling**: Test with simulated failures
5. **Load Tests**: Verify auto-refresh doesn't overwhelm backend

## Deployment Notes

- No database migrations required
- No configuration changes needed
- Backward compatible with existing functionality
- Requires app restart to load new controller
- UI auto-rebuilds on file changes in development
