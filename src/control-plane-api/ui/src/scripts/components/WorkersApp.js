/**
 * WorkersApp - Web Components Integration Layer
 *
 * Main application controller for the workers view using Web Components architecture.
 * Replaces workers.js orchestration with clean component composition.
 *
 * Features:
 * - Feature flag support (gradual migration)
 * - EventBus integration
 * - SSE connection management
 * - Component initialization
 */

import * as bootstrap from 'bootstrap';
import { eventBus, EventTypes } from '../core/EventBus.js';
import { setupCreateWorkerModal, setupImportWorkerModal, setupDeleteWorkerModal, setupLicenseModal } from '../ui/worker-modals.js';
import { isAdminOrManager } from '../utils/roles.js';
import './WorkerCard.js';
import './WorkerList.js';
import './FilterBar.js';
import './StatisticsPanel.js';
import './WorkerDetailsModal.js';

class WorkersApp {
    constructor() {
        this.currentUser = null;
        this.currentRegion = 'us-east-1';
        this.currentView = 'cards';
        this.initialized = false;
    }

    /**
     * Initialize the workers app
     */
    async initialize(user) {
        if (this.initialized) {
            console.warn('[WorkersApp] Already initialized');
            return;
        }

        console.log('[WorkersApp] Initializing with user:', user);
        this.currentUser = user;

        // Setup EventBus debugging in development
        if (localStorage.getItem('debug-events') === 'true') {
            eventBus.enableDebug();
        }

        // Subscribe to filter changes
        this.subscribeToEvents();

        // SSE is now connected globally by app.js via LcmSSEAdapter

        // Render the UI
        this.render();

        // Initialize modals
        setupCreateWorkerModal();
        setupImportWorkerModal();
        setupDeleteWorkerModal();
        setupLicenseModal();

        // Expose refresh method for modals
        // Note: We attach to the existing window.workersApp object or create it
        window.workersApp = window.workersApp || {};
        window.workersApp.refreshWorkers = () => this.refreshWorkers();

        // Handle page unload
        window.addEventListener('beforeunload', () => {
            this.destroy();
        });

        this.initialized = true;
        console.log('[WorkersApp] Initialization complete');
    }

    /**
     * Refresh the workers list by triggering the AutoImportWorkersJob
     * This will discover new EC2 instances and import them as workers.
     * After triggering, we also reload the local workers list.
     */
    async refreshWorkers() {
        console.log('[WorkersApp] Triggering workers refresh...');

        // Show loading state on refresh button
        const refreshBtn = document.querySelector('[onclick*="refreshWorkers"]');
        const originalContent = refreshBtn?.innerHTML;
        if (refreshBtn) {
            refreshBtn.disabled = true;
            refreshBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span> Refreshing...';
        }

        try {
            // Trigger the auto-import job via API
            const response = await fetch('/api/workers/refresh', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                credentials: 'include',
            });

            const result = await response.json();
            console.log('[WorkersApp] Refresh response:', result);

            // Import toast notification function
            const { showToast } = await import('../ui/notifications.js');

            // Handle different response states
            switch (result.status) {
                case 'triggered':
                    showToast('Workers refresh triggered. List will update automatically.', 'success');
                    break;
                case 'running':
                    showToast('Workers refresh already in progress. Please wait.', 'info');
                    break;
                case 'scheduled':
                    showToast(`Workers refresh scheduled in ${result.seconds_until_next}s. Please wait.`, 'info');
                    break;
                case 'unavailable':
                    showToast('Auto-import is not enabled. Check system settings.', 'warning');
                    break;
                default:
                    if (!response.ok) {
                        showToast(`Refresh failed: ${result.detail || 'Unknown error'}`, 'error');
                    }
            }

            // Always reload the local workers list (to show any changes)
            const workerList = document.querySelector('worker-list');
            if (workerList && typeof workerList.loadWorkers === 'function') {
                workerList.loadWorkers();
            }
        } catch (error) {
            console.error('[WorkersApp] Failed to trigger refresh:', error);
            const { showToast } = await import('../ui/notifications.js');
            showToast('Failed to trigger workers refresh', 'error');

            // Still try to reload workers list even if API call failed
            const workerList = document.querySelector('worker-list');
            if (workerList && typeof workerList.loadWorkers === 'function') {
                workerList.loadWorkers();
            }
        } finally {
            // Restore button state
            if (refreshBtn) {
                refreshBtn.disabled = false;
                refreshBtn.innerHTML = originalContent || '<i class="bi bi-arrow-clockwise"></i> Refresh';
            }
        }
    }

    /**
     * Subscribe to EventBus events
     */
    subscribeToEvents() {
        // Handle filter changes
        eventBus.on(EventTypes.UI_FILTER_CHANGED, data => {
            console.log('[WorkersApp] Filter changed:', data);

            switch (data.type) {
                case 'region':
                    this.currentRegion = data.value;
                    this.updateWorkerList();
                    break;
                case 'status':
                    this.updateFilterAttribute('filter-status', data.value);
                    break;
                case 'include_terminated':
                    this.updateFilterAttribute('include-terminated', data.value);
                    break;
                case 'search':
                    this.updateFilterAttribute('search', data.value);
                    break;
                case 'view':
                    this.currentView = data.value;
                    this.updateFilterAttribute('view', data.value);
                    break;
            }
        });

        // Handle modal open requests (legacy event type)
        eventBus.on(EventTypes.UI_MODAL_OPENED, data => {
            console.log('[WorkersApp] Modal open requested:', data);

            if (data.type === 'worker-details') {
                // Legacy path - convert to new event format
                eventBus.emit('UI_OPEN_WORKER_DETAILS', {
                    workerId: data.workerId,
                    region: data.worker?.aws_region,
                });
            }
        });

        // Note: WorkerDetailsModal subscribes to 'UI_OPEN_WORKER_DETAILS' directly
        // No need to re-emit here to avoid infinite loop

        // Handle SSE connection status
        eventBus.on(EventTypes.SSE_CONNECTED, () => {
            this.updateSSEStatus('connected');
        });

        eventBus.on(EventTypes.SSE_DISCONNECTED, () => {
            this.updateSSEStatus('disconnected');
        });

        eventBus.on(EventTypes.SSE_ERROR, () => {
            this.updateSSEStatus('error');
        });

        // Handle workers refresh completed (auto-import job finished)
        eventBus.on(EventTypes.WORKERS_REFRESH_COMPLETED, data => {
            console.log('[WorkersApp] Workers refresh completed:', data);
            // Reload the workers list from database
            const workerList = document.querySelector('worker-list');
            if (workerList && typeof workerList.loadWorkers === 'function') {
                workerList.loadWorkers();
            }
        });

        // Handle individual worker imports (also triggers list reload)
        eventBus.on(EventTypes.WORKER_IMPORTED, data => {
            console.log('[WorkersApp] Worker imported:', data);
            // Reload the workers list to show new worker
            const workerList = document.querySelector('worker-list');
            if (workerList && typeof workerList.loadWorkers === 'function') {
                workerList.loadWorkers();
            }
        });

        // Handle worker created events
        eventBus.on(EventTypes.WORKER_CREATED, data => {
            console.log('[WorkersApp] Worker created:', data);
            // Reload the workers list to show new worker
            const workerList = document.querySelector('worker-list');
            if (workerList && typeof workerList.loadWorkers === 'function') {
                workerList.loadWorkers();
            }
        });

        // Handle worker terminated events
        eventBus.on(EventTypes.WORKER_TERMINATED, data => {
            console.log('[WorkersApp] Worker terminated:', data);
            // Reload the workers list to reflect terminated worker
            const workerList = document.querySelector('worker-list');
            if (workerList && typeof workerList.loadWorkers === 'function') {
                workerList.loadWorkers();
            }
        });
    }

    /**
     * Cleanup on app unmount
     */
    destroy() {
        console.log('[WorkersApp] Destroying...');
        // SSE disconnect is handled globally by app.js
        this.initialized = false;
    }

    /**
     * Render the UI components
     */
    render() {
        const container = document.getElementById('workers-container');
        if (!container) {
            console.error('[WorkersApp] workers-container not found');
            return;
        }

        // Hide legacy views
        const adminView = document.getElementById('workers-admin-view');
        const userView = document.getElementById('workers-user-view');
        if (adminView) adminView.style.display = 'none';
        if (userView) userView.style.display = 'none';

        // Determine view mode based on user role
        // Use the utility function which checks localStorage 'user_roles'
        // This is more reliable than checking the user object passed to initialize
        // as that object structure might vary depending on the auth provider response
        const isAdmin = isAdminOrManager();

        console.log('[WorkersApp] User roles check:', {
            user: this.currentUser,
            roles: this.currentUser?.realm_access?.roles,
            isAdmin,
        });

        const defaultView = isAdmin ? 'table' : 'cards';
        this.currentView = defaultView;

        container.innerHTML = `
            <!-- Action Buttons -->
            <div class="row mb-4">
                <div class="col d-flex align-items-center gap-2">
                    <h2 class="mb-0">
                        <i class="bi bi-server"></i> CML Workers Management
                    </h2>
                    <div id="sse-connection-status">
                        <span class="badge bg-secondary" data-bs-toggle="tooltip" data-bs-placement="right" title="Connecting to real-time updates...">
                            <i class="bi bi-wifi"></i>
                        </span>
                    </div>
                </div>
                <div class="col-auto">
                    <div class="btn-group" role="group">
                        ${
                            isAdmin
                                ? `
                            <button class="btn btn-primary" data-bs-toggle="modal" data-bs-target="#createWorkerModal">
                                <i class="bi bi-plus-circle"></i> New
                            </button>
                            <button class="btn btn-outline-primary" data-bs-toggle="modal" data-bs-target="#importWorkerModal">
                                <i class="bi bi-box-arrow-in-down"></i> Import
                            </button>
                        `
                                : ''
                        }
                        <button class="btn btn-outline-secondary" onclick="location.reload()">
                            <i class="bi bi-arrow-clockwise"></i> Refresh
                        </button>
                    </div>
                </div>
            </div>

            <!-- Tabs -->
            <ul class="nav nav-tabs" id="workersTabs" role="tablist">
                <li class="nav-item" role="presentation">
                    <button class="nav-link active" id="workers-tab" data-bs-toggle="tab" data-bs-target="#workers-panel" type="button" role="tab" aria-controls="workers-panel" aria-selected="true">
                        <i class="bi bi-server me-2"></i>Workers
                    </button>
                </li>
                <li class="nav-item" role="presentation">
                    <button class="nav-link" id="lablets-tab" data-bs-toggle="tab" data-bs-target="#lablets-panel" type="button" role="tab" aria-controls="lablets-panel" aria-selected="false">
                        <i class="bi bi-diagram-3 me-2"></i>Lablets
                    </button>
                </li>
                <li class="nav-item" role="presentation">
                    <button class="nav-link" id="reports-tab" data-bs-toggle="tab" data-bs-target="#reports-panel" type="button" role="tab" aria-controls="reports-panel" aria-selected="false">
                        <i class="bi bi-file-earmark-bar-graph me-2"></i>Reports
                    </button>
                </li>
                <li class="nav-item" role="presentation">
                    <button class="nav-link" id="tracks-tab" data-bs-toggle="tab" data-bs-target="#tracks-panel" type="button" role="tab" aria-controls="tracks-panel" aria-selected="false">
                        <i class="bi bi-signpost-split me-2"></i>Tracks
                    </button>
                </li>
            </ul>

            <!-- Tab Content -->
            <div class="tab-content border border-top-0 p-4 bg-body" id="workersTabContent">
                <!-- Workers Panel -->
                <div class="tab-pane fade show active" id="workers-panel" role="tabpanel" aria-labelledby="workers-tab">
                    <!-- Filter Bar -->
                    <filter-bar view="${this.currentView}" is-admin="${isAdmin}"></filter-bar>

                    <!-- Workers List -->
                    <worker-list
                        region="${this.currentRegion}"
                        view="${this.currentView}"
                    ></worker-list>
                </div>

                <!-- Lablets Panel (Placeholder) -->
                <div class="tab-pane fade" id="lablets-panel" role="tabpanel" aria-labelledby="lablets-tab">
                    <div class="text-center py-5 text-muted">
                        <i class="bi bi-diagram-3 display-1"></i>
                        <h3 class="mt-3">Lablets Management</h3>
                        <p>Coming soon...</p>
                    </div>
                </div>

                <!-- Reports Panel (Placeholder) -->
                <div class="tab-pane fade" id="reports-panel" role="tabpanel" aria-labelledby="reports-tab">
                    <div class="text-center py-5 text-muted">
                        <i class="bi bi-file-earmark-bar-graph display-1"></i>
                        <h3 class="mt-3">Reports & Analytics</h3>
                        <p>Coming soon...</p>
                    </div>
                </div>

                <!-- Tracks Panel (Placeholder) -->
                <div class="tab-pane fade" id="tracks-panel" role="tabpanel" aria-labelledby="tracks-tab">
                    <div class="text-center py-5 text-muted">
                        <i class="bi bi-signpost-split display-1"></i>
                        <h3 class="mt-3">Learning Tracks</h3>
                        <p>Coming soon...</p>
                    </div>
                </div>
            </div>

            <!-- Worker Details Modal -->
            <worker-details-modal></worker-details-modal>
        `;

        console.log('[WorkersApp] Rendered with view:', this.currentView);

        // Initialize tooltip for SSE status
        const sseStatusEl = document.getElementById('sse-connection-status');
        if (sseStatusEl) {
            const badge = sseStatusEl.querySelector('.badge');
            if (badge) {
                new bootstrap.Tooltip(badge, {
                    trigger: 'hover',
                });
            }
        }
    }

    /**
     * Update worker list component
     */
    updateWorkerList() {
        const workerList = document.querySelector('worker-list');
        if (workerList) {
            workerList.setAttribute('region', this.currentRegion);
        }
    }

    /**
     * Update filter attribute on worker list
     */
    updateFilterAttribute(attr, value) {
        const workerList = document.querySelector('worker-list');
        if (workerList) {
            workerList.setAttribute(attr, value);
        }
    }

    /**
     * Update SSE connection status indicator
     */
    updateSSEStatus(status) {
        const statusEl = document.getElementById('sse-connection-status');
        if (!statusEl) return;

        const statusConfig = {
            connected: {
                class: 'bg-success',
                icon: 'wifi',
                text: 'Real-time updates active',
            },
            disconnected: {
                class: 'bg-secondary',
                icon: 'wifi-off',
                text: 'Real-time updates disconnected',
            },
            error: {
                class: 'bg-danger',
                icon: 'exclamation-triangle',
                text: 'Real-time updates error',
            },
        };

        const config = statusConfig[status] || statusConfig.disconnected;

        statusEl.innerHTML = `
            <span class="badge ${config.class}" data-bs-toggle="tooltip" data-bs-placement="right" title="${config.text}">
                <i class="bi bi-${config.icon}"></i>
            </span>
        `;

        // Initialize tooltip
        const badge = statusEl.querySelector('.badge');
        if (badge) {
            new bootstrap.Tooltip(badge, {
                trigger: 'hover',
            });
        }
    }

    /**
     * Open worker details modal (for programmatic use)
     * This method is kept for backward compatibility but should not re-emit the event
     * to avoid infinite loops. Components should emit 'UI_OPEN_WORKER_DETAILS' directly.
     */
    async openWorkerDetailsModal(workerId, region) {
        console.log('[WorkersApp] Opening worker details modal (direct call):', workerId, region);

        // Emit event only if called programmatically (not from event handler)
        // The modal subscribes to this event directly
        if (workerId && region) {
            eventBus.emit('UI_OPEN_WORKER_DETAILS', { workerId, region });
        } else {
            console.warn('[WorkersApp] Invalid parameters for opening modal:', { workerId, region });
        }
    }
}

// Create singleton instance
const workersApp = new WorkersApp();

/**
 * Initialize workers view (called from app.js)
 * Now always uses WorkersPage component.
 */
export function initializeWorkersView(user) {
    console.log('[WorkersApp] initializeWorkersView called');

    // Use WorkersPage component
    console.log('[WorkersApp] Using WorkersPage component');
    const container = document.getElementById('workers-container');
    if (container) {
        // Clear and insert WorkersPage component
        container.innerHTML = '<workers-page id="workers-page"></workers-page>';
        const workersPage = container.querySelector('workers-page');
        if (workersPage) {
            workersPage.initialize(user);
        }
    }
}

export default workersApp;
