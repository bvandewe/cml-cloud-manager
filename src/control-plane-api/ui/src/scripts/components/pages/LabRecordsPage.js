/**
 * LabRecordsPage — Phase 10 (P10-1)
 *
 * Dedicated Labs management page for admin operations on LabRecords.
 * Architecture ref: §9.4 Labs Management Page.
 *
 * Features:
 * - Collapsible summary metric tiles (status counts)
 * - Filterable data table with status, worker, bound/unbound filters
 * - Search by lab title
 * - Action buttons: Start, Stop, Wipe, Clone, Export, Delete, Archive
 * - Real-time SSE updates
 * - Lab detail modal on row click
 * - Import lab button (admin only)
 *
 * @module components/pages/LabRecordsPage
 */

import { BaseComponent } from '../../core/BaseComponent.js';
import { eventBus, EventTypes } from '../../core/EventBus.js';
import * as labRecordsApi from '../../api/lab-records.js';
import { showToast } from '../../ui/notifications.js';
import { showConfirmAsync } from '../modals.js';
import * as bootstrap from 'bootstrap';
import '../core/LcmTabView.js';
import '../core/LcmDataTable.js';
import '../core/LcmActionBar.js';
import '../core/LcmStatusBadge.js';
import '../core/LcmMetricCard.js';
import './LabDetailModal.js';
import '../WorkerDetailsModal.js';

const STORAGE_KEY_METRICS = 'lcm.labs.metricsCollapsed';

/**
 * LabRecord status display configuration
 */
const STATUS_CONFIG = {
    defined: { color: 'info', icon: 'bi-file-earmark-text' },
    discovered: { color: 'info', icon: 'bi-search' },
    importing: { color: 'info', icon: 'bi-box-arrow-in-down' },
    imported: { color: 'primary', icon: 'bi-box-arrow-in-down' },
    booting: { color: 'warning', icon: 'bi-power' },
    booted: { color: 'success', icon: 'bi-play-circle-fill' },
    converging: { color: 'warning', icon: 'bi-arrow-repeat' },
    converged: { color: 'success', icon: 'bi-check-circle-fill' },
    stopping: { color: 'warning', icon: 'bi-stop-circle' },
    stopped: { color: 'secondary', icon: 'bi-stop-circle-fill' },
    wiping: { color: 'warning', icon: 'bi-eraser' },
    wiped: { color: 'secondary', icon: 'bi-eraser-fill' },
    deleting: { color: 'danger', icon: 'bi-trash' },
    deleted: { color: 'dark', icon: 'bi-trash-fill' },
    archived: { color: 'dark', icon: 'bi-archive-fill' },
    orphaned: { color: 'warning', icon: 'bi-question-diamond-fill' },
    error: { color: 'danger', icon: 'bi-exclamation-triangle-fill' },
};

export class LabRecordsPage extends BaseComponent {
    static get observedAttributes() {
        return ['active-tab', 'view-mode'];
    }

    constructor() {
        super();
        this._currentUser = null;
        this._labRecords = [];
        this._stats = this._emptyStats();
        this._isLoading = true;
        this._metricsCollapsed = localStorage.getItem(STORAGE_KEY_METRICS) === 'true';
        this._filters = {
            worker_id: null,
            status: null,
            bound: null,
            include_terminal: false,
            search: '',
        };
    }

    _emptyStats() {
        return {
            total: 0,
            booted: 0,
            stopped: 0,
            wiped: 0,
            defined: 0,
            discovered: 0,
            imported: 0,
            error: 0,
            orphaned: 0,
            running: 0,
            other: 0,
        };
    }

    /**
     * Initialize the page with user context
     * @param {Object} user - Current user object with roles
     */
    initialize(user) {
        this._currentUser = user;
        this.render();
        this._setupEventListeners();
        this._configureDataTable();

        // Load initial data after DOM is ready
        requestAnimationFrame(() => {
            this._refreshLabRecords();
        });
    }

    onMount() {
        this.innerHTML = this._renderLoading();
    }

    /**
     * Check if user has admin or manager role
     */
    _isAdminOrManager() {
        if (!this._currentUser?.roles) return false;
        const adminRoles = ['admin', 'manager', 'lcm-admin', 'lcm-manager'];
        return this._currentUser.roles.some(role => adminRoles.includes(role.toLowerCase()));
    }

    // ===========================================================================
    // Data Loading
    // ===========================================================================

    async _refreshLabRecords() {
        this._isLoading = true;
        this._updateLoadingState();

        try {
            const filters = {};
            if (this._filters.worker_id) filters.worker_id = this._filters.worker_id;
            if (this._filters.status) filters.status = this._filters.status;
            if (this._filters.bound !== null) filters.bound = this._filters.bound;
            if (this._filters.include_terminal) filters.include_terminal = true;

            const records = await labRecordsApi.listLabRecords(filters);
            this._labRecords = Array.isArray(records) ? records : records.items || records.data || [];
            this._computeStats();
            this._updateDataTable();
            this._updateMetricCards();
        } catch (error) {
            console.error('[LabRecordsPage] Failed to load lab records:', error);
            showToast('Failed to load lab records: ' + error.message, 'error');
        } finally {
            this._isLoading = false;
            this._updateLoadingState();
        }
    }

    _computeStats() {
        const stats = this._emptyStats();
        const runningStatuses = new Set(['booted', 'converging', 'converged']);
        const countedStatuses = new Set(['booted', 'stopped', 'wiped', 'defined', 'discovered', 'imported', 'error', 'orphaned']);

        this._labRecords.forEach(lr => {
            stats.total++;
            const s = lr.status?.toLowerCase();
            if (countedStatuses.has(s)) {
                stats[s]++;
            } else {
                stats.other++;
            }
            if (runningStatuses.has(s)) {
                stats.running++;
            }
        });

        this._stats = stats;
    }

    // ===========================================================================
    // Event Listeners
    // ===========================================================================

    _setupEventListeners() {
        // SSE events for lab records
        this.subscribe(EventTypes.LAB_RECORD_DISCOVERED, data => {
            this._handleLabRecordUpdate(data);
        });
        this.subscribe(EventTypes.LAB_RECORD_STATUS_UPDATED, data => {
            this._handleLabRecordStatusUpdate(data);
        });
        this.subscribe(EventTypes.LAB_RECORD_SNAPSHOT, data => {
            this._handleLabRecordUpdate(data);
        });
        this.subscribe(EventTypes.LAB_RECORD_IMPORTED, data => {
            this._handleLabRecordUpdate(data);
        });
        this.subscribe(EventTypes.LAB_RECORD_DELETED, data => {
            this._handleLabRecordStatusUpdate({
                ...data,
                status: 'deleted',
            });
        });
        this.subscribe(EventTypes.LAB_RECORD_ARCHIVED, data => {
            this._handleLabRecordStatusUpdate({
                ...data,
                status: 'archived',
            });
        });
        this.subscribe(EventTypes.LAB_RECORD_CLONED, data => {
            this._handleLabRecordUpdate(data);
        });
        this.subscribe(EventTypes.LAB_RECORD_ACTION_COMPLETED, () => {
            // Refresh the full list to get latest states
            this._refreshLabRecords();
        });
        this.subscribe(EventTypes.LAB_RECORD_ACTION_QUEUED, data => {
            // Mark the lab record as having a pending action (AD-023)
            this._handlePendingAction(data);
        });
        this.subscribe(EventTypes.LAB_RECORD_ACTION_FAILED, data => {
            // Clear pending action on failure (AD-023)
            this._handlePendingActionCleared(data);
        });
        this.subscribe(EventTypes.LAB_RECORDS_REFRESH_COMPLETED, () => {
            this._refreshLabRecords();
        });
    }

    _handleLabRecordUpdate(data) {
        if (!data || !data.id) return;
        const index = this._labRecords.findIndex(lr => lr.id === data.id);
        if (index >= 0) {
            this._labRecords[index] = { ...this._labRecords[index], ...data };
        } else {
            this._labRecords.push(data);
        }
        this._computeStats();
        this._updateDataTable();
        this._updateMetricCards();
    }

    _handleLabRecordStatusUpdate(data) {
        const labRecordId = data.lab_record_id || data.id;
        if (!labRecordId) return;
        const index = this._labRecords.findIndex(lr => lr.id === labRecordId);
        if (index >= 0) {
            this._labRecords[index] = {
                ...this._labRecords[index],
                status: data.status,
                updated_at: data.updated_at || new Date().toISOString(),
            };
            this._computeStats();
            this._updateDataTable();
            this._updateMetricCards();
        }
    }

    /**
     * Handle a pending action being set on a lab record (AD-023).
     * Updates local state and re-renders the table row to show the spinner.
     */
    _handlePendingAction(data) {
        const labRecordId = data.lab_record_id || data.id;
        if (!labRecordId) return;
        const index = this._labRecords.findIndex(lr => lr.id === labRecordId);
        if (index >= 0) {
            this._labRecords[index] = {
                ...this._labRecords[index],
                pending_action: data.action,
                pending_action_requested_at: data.requested_at,
            };
            this._updateDataTable();
        }
    }

    /**
     * Handle a pending action being cleared (completed or failed) (AD-023).
     * Updates local state and re-renders the table row.
     */
    _handlePendingActionCleared(data) {
        const labRecordId = data.lab_record_id || data.id;
        if (!labRecordId) return;
        const index = this._labRecords.findIndex(lr => lr.id === labRecordId);
        if (index >= 0) {
            this._labRecords[index] = {
                ...this._labRecords[index],
                pending_action: null,
                pending_action_requested_at: null,
            };
            this._updateDataTable();
        }
    }

    // ===========================================================================
    // Actions
    // ===========================================================================

    async _handleAction(action, labRecord) {
        if (!labRecord || !labRecord.id) return;

        const confirmActions = ['delete', 'wipe', 'archive'];
        if (confirmActions.includes(action)) {
            const confirmed = await showConfirmAsync(`${action.charAt(0).toUpperCase() + action.slice(1)} Lab`, `Are you sure you want to ${action} lab "${labRecord.title || labRecord.id}"?`, {
                actionLabel: action.charAt(0).toUpperCase() + action.slice(1),
                actionClass: action === 'delete' ? 'btn-danger' : 'btn-warning',
            });
            if (!confirmed) return;
        }

        try {
            switch (action) {
                case 'start':
                    await labRecordsApi.startLabRecord(labRecord.id);
                    showToast(`Start queued for ${labRecord.title || labRecord.id}`, 'info');
                    break;
                case 'stop':
                    await labRecordsApi.stopLabRecord(labRecord.id);
                    showToast(`Stop queued for ${labRecord.title || labRecord.id}`, 'info');
                    break;
                case 'wipe':
                    await labRecordsApi.wipeLabRecord(labRecord.id);
                    showToast(`Wipe queued for ${labRecord.title || labRecord.id}`, 'info');
                    break;
                case 'delete':
                    await labRecordsApi.deleteLabRecord(labRecord.id);
                    showToast(`Delete queued for ${labRecord.title || labRecord.id}`, 'warning');
                    break;
                case 'clone':
                    await labRecordsApi.cloneLabRecord(labRecord.id);
                    showToast(`Clone initiated for ${labRecord.title || labRecord.id}`, 'info');
                    break;
                case 'export':
                    await this._handleExport(labRecord);
                    break;
                case 'archive':
                    await labRecordsApi.archiveLabRecord(labRecord.id);
                    showToast(`Archive initiated for ${labRecord.title || labRecord.id}`, 'info');
                    break;
                case 'details':
                    this._openDetailModal(labRecord.id);
                    break;
                default:
                    console.warn('[LabRecordsPage] Unknown action:', action);
            }
        } catch (error) {
            console.error(`[LabRecordsPage] Action ${action} failed:`, error);
            showToast(`Failed to ${action}: ${error.message}`, 'error');
        }
    }

    async _handleExport(labRecord) {
        try {
            const yaml = await labRecordsApi.exportLabRecord(labRecord.id);
            const blob = new Blob([yaml], { type: 'text/yaml' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${labRecord.title || 'lab'}.yaml`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
            showToast(`Exported ${labRecord.title || labRecord.id}`, 'success');
        } catch (error) {
            console.error('[LabRecordsPage] Export failed:', error);
            showToast(`Export failed: ${error.message}`, 'error');
        }
    }

    _openDetailModal(labRecordId) {
        const modal = this.querySelector('lab-detail-modal');
        if (modal) {
            modal.open(labRecordId);
        }
    }

    // ===========================================================================
    // Data Table Configuration
    // ===========================================================================

    _configureDataTable() {
        const table = this.querySelector('#lab-records-table');
        if (!table) return;

        table.setColumns([
            {
                field: 'title',
                label: 'Title',
                sortable: true,
                render: (value, row) => {
                    const icon = STATUS_CONFIG[row.status?.toLowerCase()]?.icon || 'bi-file-earmark';
                    return `<span class="d-flex align-items-center gap-2">
                        <i class="${icon} text-muted"></i>
                        <strong class="lab-title-link" role="button" data-lab-id="${row.id}">${this._escapeHtml(value || 'Untitled')}</strong>
                    </span>`;
                },
            },
            {
                field: 'worker_name',
                label: 'Worker',
                sortable: true,
                render: (value, row) => value || row.worker_id?.substring(0, 12) || '—',
            },
            {
                field: 'status',
                label: 'Status',
                sortable: true,
                render: (value, row) => {
                    const badge = `<lcm-status-badge status="${value || 'unknown'}" icon pill></lcm-status-badge>`;
                    if (row.pending_action) {
                        return `${badge} <span class="badge bg-warning text-dark ms-1"><i class="bi bi-hourglass-split me-1"></i>${row.pending_action}…</span>`;
                    }
                    return badge;
                },
            },
            {
                field: 'node_count',
                label: 'Nodes',
                sortable: true,
                render: value => (value != null ? String(value) : '—'),
            },
            {
                field: 'link_count',
                label: 'Links',
                sortable: true,
                render: value => (value != null ? String(value) : '—'),
            },
            {
                field: 'source',
                label: 'Source',
                sortable: true,
                render: value => {
                    const icons = { discovery: 'bi-search', import: 'bi-box-arrow-in-down', manual: 'bi-pencil' };
                    const icon = icons[value] || 'bi-question-circle';
                    return `<span><i class="${icon} me-1"></i>${value || 'unknown'}</span>`;
                },
            },
            {
                field: 'updated_at',
                label: 'Updated',
                sortable: true,
                type: 'datetime',
            },
            {
                field: 'actions',
                label: 'Actions',
                render: (_, row) => {
                    const st = (row.status || '').toLowerCase();
                    const hasPending = !!row.pending_action;
                    const canStart = !hasPending && !['booted', 'booting', 'converging', 'converged', 'deleted', 'archived', 'orphaned'].includes(st);
                    const canStop = !hasPending && ['booted', 'converging', 'converged'].includes(st);
                    const canWipe = !hasPending && !['wiped', 'wiping', 'deleted', 'archived', 'defined', 'orphaned'].includes(st);
                    return `
                        <div class="btn-group btn-group-sm">
                            <button class="btn btn-sm btn-outline-primary lcm-row-action p-1" data-action="details" data-row-id="${row.id}" title="View Details">
                                <i class="bi bi-info-circle"></i>
                            </button>
                            <button class="btn btn-sm btn-outline-success lcm-row-action p-1" data-action="start" data-row-id="${row.id}" title="Start Lab"
                                    ${canStart ? '' : 'disabled'}>
                                <i class="bi ${hasPending && row.pending_action === 'start' ? 'bi-hourglass-split' : 'bi-play'}"></i>
                            </button>
                            <button class="btn btn-sm btn-outline-warning lcm-row-action p-1" data-action="stop" data-row-id="${row.id}" title="Stop Lab"
                                    ${canStop ? '' : 'disabled'}>
                                <i class="bi ${hasPending && row.pending_action === 'stop' ? 'bi-hourglass-split' : 'bi-stop'}"></i>
                            </button>
                            <button class="btn btn-sm btn-outline-danger lcm-row-action p-1" data-action="wipe" data-row-id="${row.id}" title="Wipe Lab"
                                    ${canWipe ? '' : 'disabled'}>
                                <i class="bi ${hasPending && row.pending_action === 'wipe' ? 'bi-hourglass-split' : 'bi-eraser'}"></i>
                            </button>
                        </div>
                    `;
                },
            },
        ]);

        // Handle row actions
        table.addEventListener('row-action', e => {
            const { action, row } = e.detail;
            this._handleAction(action, row);
        });

        // Handle row click -> open detail modal
        table.addEventListener('row-click', e => {
            const { row } = e.detail;
            if (row?.id) {
                this._openDetailModal(row.id);
            }
        });
    }

    _updateDataTable() {
        const table = this.querySelector('#lab-records-table');
        if (!table) return;

        let data = [...this._labRecords];

        // Apply client-side search filter
        if (this._filters.search) {
            const term = this._filters.search.toLowerCase();
            data = data.filter(lr => (lr.title || '').toLowerCase().includes(term) || (lr.worker_name || '').toLowerCase().includes(term) || (lr.status || '').toLowerCase().includes(term) || (lr.id || '').toLowerCase().includes(term));
        }

        table.setData(data);
    }

    _updateLoadingState() {
        const table = this.querySelector('#lab-records-table');
        if (table) {
            if (this._isLoading) {
                table.setAttribute('loading', '');
            } else {
                table.removeAttribute('loading');
            }
        }
    }

    // ===========================================================================
    // Metric Cards
    // ===========================================================================

    _updateMetricCards() {
        const s = this._stats;
        this._setMetricValue('metric-total', s.total);
        this._setMetricValue('metric-running', s.running);
        this._setMetricValue('metric-stopped', s.stopped);
        this._setMetricValue('metric-wiped', s.wiped);
        this._setMetricValue('metric-discovered', s.discovered);
        this._setMetricValue('metric-error', s.error);
    }

    _setMetricValue(id, value) {
        const card = this.querySelector(`#${id}`);
        if (card) card.setAttribute('value', String(value));
    }

    // ===========================================================================
    // Filters
    // ===========================================================================

    _applyFilter(field, value) {
        this._filters[field] = value === '' || value === 'all' ? null : value;
        this._refreshLabRecords();
    }

    _clearFilters() {
        this._filters = { worker_id: null, status: null, bound: null, include_terminal: false, search: '' };
        const statusFilter = this.querySelector('#labs-status-filter');
        const workerFilter = this.querySelector('#labs-worker-filter');
        const boundFilter = this.querySelector('#labs-bound-filter');
        const searchInput = this.querySelector('#labs-search-input');
        const terminalToggle = this.querySelector('#labs-terminal-toggle');
        if (statusFilter) statusFilter.value = 'all';
        if (workerFilter) workerFilter.value = '';
        if (boundFilter) boundFilter.value = 'all';
        if (searchInput) searchInput.value = '';
        if (terminalToggle) terminalToggle.checked = false;
        this._refreshLabRecords();
    }

    // ===========================================================================
    // Rendering
    // ===========================================================================

    _renderLoading() {
        return `
            <div class="d-flex justify-content-center align-items-center py-5">
                <div class="spinner-border text-primary" role="status">
                    <span class="visually-hidden">Loading...</span>
                </div>
            </div>
        `;
    }

    render() {
        const isAdmin = this._isAdminOrManager();
        const metricsCollapsed = this._metricsCollapsed;

        this.innerHTML = `
            <div class="lab-records-page">
                <!-- Page Header -->
                <div class="page-header d-flex justify-content-between align-items-center mb-4">
                    <div>
                        <h2 class="mb-1">
                            Lab Records
                        </h2>
                        <p class="text-muted mb-0">Manage CML lab environments across workers</p>
                    </div>
                    <lcm-action-bar id="labs-action-bar">
                        <lcm-action-bar-primary>
                            ${
                                isAdmin
                                    ? `
                            <button class="btn btn-outline-primary" data-action="import">
                                <i class="bi bi-box-arrow-in-down me-1"></i>Import Lab
                            </button>
                        `
                                    : ''
                            }
                        </lcm-action-bar-primary>
                        <lcm-action-bar-secondary>
                            <button class="btn btn-outline-secondary" data-action="refresh">
                                <i class="bi bi-arrow-clockwise me-1"></i>Refresh
                            </button>
                        </lcm-action-bar-secondary>
                    </lcm-action-bar>
                </div>

                <!-- Metrics Summary (Collapsible) -->
                <div class="mb-3">
                    <button class="btn btn-sm btn-link text-decoration-none p-0 mb-2"
                        id="labs-metrics-toggle" type="button">
                        <i class="bi bi-${metricsCollapsed ? 'chevron-right' : 'chevron-down'} me-1"></i>
                        Summary
                    </button>
                    <div id="labs-metrics-panel" class="${metricsCollapsed ? 'd-none' : ''}">
                        <div class="row g-3 mb-3">
                            <div class="col-6 col-md-4 col-xl-2">
                                <lcm-metric-card id="metric-total" title="Total Labs"
                                    value="${this._stats.total}" icon="bi-flask" color="primary">
                                </lcm-metric-card>
                            </div>
                            <div class="col-6 col-md-4 col-xl-2">
                                <lcm-metric-card id="metric-running" title="Running"
                                    value="${this._stats.running}" icon="bi-play-circle" color="success">
                                </lcm-metric-card>
                            </div>
                            <div class="col-6 col-md-4 col-xl-2">
                                <lcm-metric-card id="metric-stopped" title="Stopped"
                                    value="${this._stats.stopped}" icon="bi-stop-circle" color="secondary">
                                </lcm-metric-card>
                            </div>
                            <div class="col-6 col-md-4 col-xl-2">
                                <lcm-metric-card id="metric-wiped" title="Wiped"
                                    value="${this._stats.wiped}" icon="bi-eraser" color="secondary">
                                </lcm-metric-card>
                            </div>
                            <div class="col-6 col-md-4 col-xl-2">
                                <lcm-metric-card id="metric-discovered" title="Discovered"
                                    value="${this._stats.discovered}" icon="bi-search" color="info">
                                </lcm-metric-card>
                            </div>
                            <div class="col-6 col-md-4 col-xl-2">
                                <lcm-metric-card id="metric-error" title="Errors"
                                    value="${this._stats.error}" icon="bi-exclamation-triangle" color="danger">
                                </lcm-metric-card>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Data Table with Filters -->
                <div class="card shadow-sm no-hover-lift">
                    <div class="card-header d-flex align-items-center bg-white py-2 gap-2">
                        <span class="fw-medium text-muted small">Lab Records</span>
                        <div class="d-flex align-items-center gap-2 ms-auto">
                            <div class="input-group input-group-sm" style="width: 250px;">
                                <span class="input-group-text bg-white"><i class="bi bi-search"></i></span>
                                <input type="text" class="form-control" id="labs-search-input"
                                    placeholder="Search labs..." value="${this._filters.search || ''}">
                            </div>
                            <select class="form-select form-select-sm" id="labs-bound-filter" style="width: 160px;">
                                <option value="all">All Bindings</option>
                                <option value="true">Bound</option>
                                <option value="false">Unbound</option>
                            </select>
                            <select class="form-select form-select-sm" id="labs-status-filter" style="width: 160px;">
                                <option value="all">All Statuses</option>
                                <option value="defined">Defined</option>
                                <option value="discovered">Discovered</option>
                                <option value="imported">Imported</option>
                                <option value="booted">Booted</option>
                                <option value="stopped">Stopped</option>
                                <option value="wiped">Wiped</option>
                                <option value="error">Error</option>
                                <option value="orphaned">Orphaned</option>
                            </select>
                            <div class="form-check form-switch ms-1" style="white-space: nowrap;">
                                <input class="form-check-input" type="checkbox" id="labs-terminal-toggle"
                                    ${this._filters.include_terminal ? 'checked' : ''}>
                                <label class="form-check-label small" for="labs-terminal-toggle">Incl. Deleted & Orphaned</label>
                            </div>
                            <button class="btn btn-sm btn-outline-secondary" id="labs-clear-filters" title="Clear all filters">
                                <i class="bi bi-x-lg"></i>
                            </button>
                        </div>
                    </div>
                    <div class="card-body p-0">
                        <lcm-data-table id="lab-records-table"
                            page-size="25"
                            no-toolbar
                            panel-mode
                            empty-message="No lab records found. Labs appear here when discovered on workers or imported."
                            ${this._isLoading ? 'loading' : ''}>
                        </lcm-data-table>
                    </div>
                </div>

                <!-- Lab Detail Modal -->
                <lab-detail-modal id="lab-detail-modal"></lab-detail-modal>

                <!-- Worker Details Modal (for cross-links from lab overview → worker details) -->
                <worker-details-modal></worker-details-modal>
            </div>
        `;

        this._bindInteractions();
        this._configureDataTable();
    }

    _bindInteractions() {
        // Action bar handling (matches Workers pattern)
        const actionBar = this.querySelector('#labs-action-bar');
        if (actionBar) {
            actionBar.addEventListener('click', e => {
                const action = e.target.closest('[data-action]')?.dataset.action;
                if (action === 'refresh') this._refreshLabRecords();
                if (action === 'import') showToast('Lab import is not yet implemented in the UI', 'info');
            });
        }

        // Metrics toggle
        this.querySelector('#labs-metrics-toggle')?.addEventListener('click', () => {
            this._metricsCollapsed = !this._metricsCollapsed;
            localStorage.setItem(STORAGE_KEY_METRICS, String(this._metricsCollapsed));
            const panel = this.querySelector('#labs-metrics-panel');
            const icon = this.querySelector('#labs-metrics-toggle i');
            if (panel) panel.classList.toggle('d-none', this._metricsCollapsed);
            if (icon) {
                icon.className = `bi bi-${this._metricsCollapsed ? 'chevron-right' : 'chevron-down'} me-1`;
            }
        });

        // Search input (debounced)
        const searchInput = this.querySelector('#labs-search-input');
        let searchTimeout;
        searchInput?.addEventListener('input', e => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                this._filters.search = e.target.value;
                this._updateDataTable();
            }, 300);
        });

        // Status filter
        this.querySelector('#labs-status-filter')?.addEventListener('change', e => {
            this._applyFilter('status', e.target.value);
        });

        // Bound filter
        this.querySelector('#labs-bound-filter')?.addEventListener('change', e => {
            const value = e.target.value;
            this._applyFilter('bound', value === 'all' ? null : value === 'true');
        });

        // Terminal toggle
        this.querySelector('#labs-terminal-toggle')?.addEventListener('change', e => {
            this._filters.include_terminal = e.target.checked;
            this._refreshLabRecords();
        });

        // Clear filters
        this.querySelector('#labs-clear-filters')?.addEventListener('click', () => {
            this._clearFilters();
        });
    }

    _escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }
}

if (!customElements.get('lab-records-page')) {
    customElements.define('lab-records-page', LabRecordsPage);
}

export default LabRecordsPage;
