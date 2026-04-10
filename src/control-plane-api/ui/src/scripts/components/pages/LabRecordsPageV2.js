/**
 * LabRecordsPageV2 — Store-driven Labs management page
 *
 * Migration target for LabRecordsPage (Phase M1).
 * Replaces inline column definitions + LcmDataTable with:
 *   - Column registry (labRecordColumns.js) with SchemaColumn format
 *   - ui-data-table (from @neuroglia/ui-core) with component cell rendering
 *   - StateStore labRecords slice (reactive, SSE-driven updates)
 *
 * Preserves all existing features:
 *   - Collapsible metric summary tiles
 *   - Filterable data table (status, worker, bound/unbound, search)
 *   - Action buttons: Start, Stop, Wipe, Clone, Export, Delete, Archive
 *   - Real-time SSE updates (via store slice subscriptions)
 *   - Lab detail modal on row click
 *   - Import lab button (admin only)
 *   - Include terminal toggle (deleted/orphaned)
 *
 * @module components/pages/LabRecordsPageV2
 */

import { StoreConnectedPage } from '../../bridge/StoreConnectedPage.js';
import { store } from '../../app/store.js';
import { selectAllLabRecords, selectLabRecordStatusSummary, selectLabRecordFilters, selectLabRecordsListLoading, createLabRecordsActions } from '../../app/index.js';
import { eventBus, EventTypes } from '../../app/eventBus.js';
import { LAB_RECORD_COLUMNS, LAB_RECORD_DEFAULT_COLUMNS } from '../../columns/labRecordColumns.js';
import { showToast } from '../../ui/notifications.js';
import { showConfirmAsync } from '../modals.js';
import '../core/LcmActionBar.js';
import '../core/LcmMetricCard.js';
import './LabDetailModal.js';
import '../WorkerDetailsModal.js';

const STORAGE_KEY_METRICS = 'lcm.labs.metricsCollapsed';
const TABLE_STORAGE_KEY = 'lcm.labRecords.table';

/**
 * Row actions configuration.
 * Defines which actions are available per-row and their enable/disable logic.
 */
const ROW_ACTIONS = [
    {
        id: 'details',
        label: 'Details',
        icon: 'bi-info-circle',
        variant: 'outline-primary',
    },
    {
        id: 'start',
        label: 'Start',
        icon: 'bi-play',
        variant: 'outline-success',
        condition: row => {
            const st = (row.status || '').toLowerCase();
            return !row.pending_action && !['booted', 'booting', 'converging', 'converged', 'deleted', 'archived', 'orphaned'].includes(st);
        },
    },
    {
        id: 'stop',
        label: 'Stop',
        icon: 'bi-stop',
        variant: 'outline-warning',
        condition: row => {
            const st = (row.status || '').toLowerCase();
            return !row.pending_action && ['booted', 'converging', 'converged'].includes(st);
        },
    },
    {
        id: 'wipe',
        label: 'Wipe',
        icon: 'bi-eraser',
        variant: 'outline-danger',
        condition: row => {
            const st = (row.status || '').toLowerCase();
            return !row.pending_action && !['wiped', 'wiping', 'deleted', 'archived', 'defined', 'orphaned'].includes(st);
        },
    },
];

export class LabRecordsPageV2 extends StoreConnectedPage {
    static get observedAttributes() {
        return ['active-tab', 'view-mode'];
    }

    constructor() {
        super();
        this._metricsCollapsed = localStorage.getItem(STORAGE_KEY_METRICS) === 'true';
        this._clientSearchTerm = '';
    }

    // =========================================================================
    // StoreConnectedPage Overrides
    // =========================================================================

    getStoreInstance() {
        return store;
    }

    getActionCreators(storeInstance) {
        return createLabRecordsActions(storeInstance);
    }

    subscribeToStore() {
        // React to lab records list changes → update table
        this.connectSlice('labRecords', selectAllLabRecords, records => {
            this._updateDataTable(records);
        });

        // React to status summary changes → update metric cards
        this.connectSlice('labRecords', selectLabRecordStatusSummary, stats => {
            this._updateMetricCards(stats);
        });

        // React to loading state → show/hide spinner on table
        this.connectSlice('labRecords', selectLabRecordsListLoading, loading => {
            this._updateLoadingState(loading);
        });
    }

    loadInitialData() {
        const filters = this.getSliceState('labRecords')?.filters || {};
        this.actions.loadLabRecords(filters);
    }

    // =========================================================================
    // SSE Event Listeners (EventBus — supplements store-driven updates)
    // =========================================================================

    _setupPageEventListeners() {
        // LAB_RECORD_ACTION_QUEUED → set pending_action optimistically
        this.subscribe(EventTypes.LAB_RECORD_ACTION_QUEUED, data => {
            const labRecordId = data.lab_record_id || data.id;
            if (labRecordId) {
                this.dispatch('labRecords', 'setPendingAction', {
                    labRecordId,
                    action: data.action,
                    requested_at: data.requested_at,
                });
            }
        });

        // LAB_RECORD_ACTION_COMPLETED → clear pending + refresh
        this.subscribe(EventTypes.LAB_RECORD_ACTION_COMPLETED, () => {
            this.actions.loadLabRecords(this._getCurrentFilters());
        });

        // LAB_RECORD_ACTION_FAILED → clear pending action
        this.subscribe(EventTypes.LAB_RECORD_ACTION_FAILED, data => {
            const labRecordId = data.lab_record_id || data.id;
            if (labRecordId) {
                this.dispatch('labRecords', 'clearPendingAction', labRecordId);
            }
        });

        // Full refresh events
        this.subscribe(EventTypes.LAB_RECORDS_REFRESH_COMPLETED, () => {
            // Data already in store via SSE adapter — just confirm table is current
        });
    }

    // =========================================================================
    // Actions (user interactions)
    // =========================================================================

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
                    await this.actions.startLabRecord(labRecord.id);
                    showToast(`Start queued for ${labRecord.title || labRecord.id}`, 'info');
                    break;
                case 'stop':
                    await this.actions.stopLabRecord(labRecord.id);
                    showToast(`Stop queued for ${labRecord.title || labRecord.id}`, 'info');
                    break;
                case 'wipe':
                    await this.actions.wipeLabRecord(labRecord.id);
                    showToast(`Wipe queued for ${labRecord.title || labRecord.id}`, 'info');
                    break;
                case 'delete':
                    await this.actions.deleteLabRecord(labRecord.id);
                    showToast(`Delete queued for ${labRecord.title || labRecord.id}`, 'warning');
                    break;
                case 'details':
                    this._openDetailModal(labRecord.id);
                    break;
                default:
                    console.warn('[LabRecordsPageV2] Unknown action:', action);
            }
        } catch (error) {
            console.error(`[LabRecordsPageV2] Action ${action} failed:`, error);
            showToast(`Failed to ${action}: ${error.message}`, 'error');
        }
    }

    _openDetailModal(labRecordId) {
        const modal = this.querySelector('lab-detail-modal');
        if (modal) {
            modal.open(labRecordId);
        }
    }

    // =========================================================================
    // Data Table
    // =========================================================================

    _configureDataTable() {
        const table = this.querySelector('#lab-records-table-v2');
        if (!table) return;

        // Configure schema-driven columns with defaults
        table.setSchemaColumns(LAB_RECORD_COLUMNS, LAB_RECORD_DEFAULT_COLUMNS);

        // Add row actions
        table.setRowActions(ROW_ACTIONS);

        // Handle row actions
        table.addEventListener('row-action', e => {
            const { action, row } = e.detail;
            this._handleAction(action, row);
        });

        // Handle row click → open detail modal
        table.addEventListener('row-click', e => {
            const { row } = e.detail;
            if (row?.id) {
                this._openDetailModal(row.id);
            }
        });
    }

    _updateDataTable(records) {
        const table = this.querySelector('#lab-records-table-v2');
        if (!table) return;

        let data = Array.isArray(records) ? [...records] : [];

        // Apply client-side search filter
        if (this._clientSearchTerm) {
            const term = this._clientSearchTerm.toLowerCase();
            data = data.filter(lr => (lr.title || '').toLowerCase().includes(term) || (lr.worker_name || '').toLowerCase().includes(term) || (lr.status || '').toLowerCase().includes(term) || (lr.id || '').toLowerCase().includes(term));
        }

        table.setData(data);
    }

    _updateLoadingState(isLoading) {
        const table = this.querySelector('#lab-records-table-v2');
        if (!table) return;

        if (isLoading) {
            table.setAttribute('loading', '');
        } else {
            table.removeAttribute('loading');
        }
    }

    // =========================================================================
    // Metric Cards
    // =========================================================================

    _updateMetricCards(stats) {
        if (!stats) return;
        this._setMetricValue('metric-total-v2', stats.total);
        this._setMetricValue('metric-running-v2', stats.running);
        this._setMetricValue('metric-stopped-v2', stats.stopped);
        this._setMetricValue('metric-wiped-v2', stats.wiped);
        this._setMetricValue('metric-discovered-v2', stats.discovered);
        this._setMetricValue('metric-error-v2', stats.error);
    }

    _setMetricValue(id, value) {
        const card = this.querySelector(`#${id}`);
        if (card) card.setAttribute('value', String(value ?? 0));
    }

    // =========================================================================
    // Filters
    // =========================================================================

    _getCurrentFilters() {
        return this.getSliceState('labRecords')?.filters || {};
    }

    _applyFilter(field, value) {
        const filterUpdate = { [field]: value === '' || value === 'all' ? null : value };
        this.actions.setFiltersAndReload(filterUpdate);
    }

    _clearFilters() {
        // Reset UI controls
        const statusFilter = this.querySelector('#labs-status-filter-v2');
        const boundFilter = this.querySelector('#labs-bound-filter-v2');
        const searchInput = this.querySelector('#labs-search-input-v2');
        const terminalToggle = this.querySelector('#labs-terminal-toggle-v2');
        if (statusFilter) statusFilter.value = 'all';
        if (boundFilter) boundFilter.value = 'all';
        if (searchInput) searchInput.value = '';
        if (terminalToggle) terminalToggle.checked = false;
        this._clientSearchTerm = '';

        // Reset store filters and reload
        this.dispatch('labRecords', 'clearFilters');
        this.actions.loadLabRecords({});
    }

    // =========================================================================
    // Rendering
    // =========================================================================

    render() {
        const isAdmin = this.isAdminOrManager();
        const metricsCollapsed = this._metricsCollapsed;

        this.innerHTML = `
            <div class="lab-records-page">
                <!-- Page Header -->
                <div class="page-header d-flex justify-content-between align-items-center mb-4">
                    <div>
                        <h2 class="mb-1">Lab Records</h2>
                        <p class="text-muted mb-0">Manage CML lab environments across workers</p>
                    </div>
                    <lcm-action-bar id="labs-action-bar-v2">
                        <lcm-action-bar-primary>
                            ${
                                isAdmin
                                    ? `
                            <button class="btn btn-outline-primary" data-action="import">
                                <i class="bi bi-box-arrow-in-down me-1"></i>Import Lab
                            </button>`
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
                        id="labs-metrics-toggle-v2" type="button">
                        <i class="bi bi-${metricsCollapsed ? 'chevron-right' : 'chevron-down'} me-1"></i>
                        Summary
                    </button>
                    <div id="labs-metrics-panel-v2" class="${metricsCollapsed ? 'd-none' : ''}">
                        <div class="row g-3 mb-3">
                            <div class="col-6 col-md-4 col-xl-2">
                                <lcm-metric-card id="metric-total-v2" title="Total Labs"
                                    value="0" icon="bi-flask" color="primary">
                                </lcm-metric-card>
                            </div>
                            <div class="col-6 col-md-4 col-xl-2">
                                <lcm-metric-card id="metric-running-v2" title="Running"
                                    value="0" icon="bi-play-circle" color="success">
                                </lcm-metric-card>
                            </div>
                            <div class="col-6 col-md-4 col-xl-2">
                                <lcm-metric-card id="metric-stopped-v2" title="Stopped"
                                    value="0" icon="bi-stop-circle" color="secondary">
                                </lcm-metric-card>
                            </div>
                            <div class="col-6 col-md-4 col-xl-2">
                                <lcm-metric-card id="metric-wiped-v2" title="Wiped"
                                    value="0" icon="bi-eraser" color="secondary">
                                </lcm-metric-card>
                            </div>
                            <div class="col-6 col-md-4 col-xl-2">
                                <lcm-metric-card id="metric-discovered-v2" title="Discovered"
                                    value="0" icon="bi-search" color="info">
                                </lcm-metric-card>
                            </div>
                            <div class="col-6 col-md-4 col-xl-2">
                                <lcm-metric-card id="metric-error-v2" title="Errors"
                                    value="0" icon="bi-exclamation-triangle" color="danger">
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
                                <input type="text" class="form-control" id="labs-search-input-v2"
                                    placeholder="Search labs...">
                            </div>
                            <select class="form-select form-select-sm" id="labs-bound-filter-v2" style="width: 160px;">
                                <option value="all">All Bindings</option>
                                <option value="true">Bound</option>
                                <option value="false">Unbound</option>
                            </select>
                            <select class="form-select form-select-sm" id="labs-status-filter-v2" style="width: 160px;">
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
                                <input class="form-check-input" type="checkbox" id="labs-terminal-toggle-v2">
                                <label class="form-check-label small" for="labs-terminal-toggle-v2">Incl. Deleted & Orphaned</label>
                            </div>
                            <button class="btn btn-sm btn-outline-secondary" id="labs-clear-filters-v2" title="Clear all filters">
                                <i class="bi bi-x-lg"></i>
                            </button>
                        </div>
                    </div>
                    <div class="card-body p-0">
                        <ui-data-table id="lab-records-table-v2"
                            page-size="25"
                            no-toolbar
                            column-picker
                            storage-key="${TABLE_STORAGE_KEY}"
                            empty-message="No lab records found. Labs appear here when discovered on workers or imported."
                            loading>
                        </ui-data-table>
                    </div>
                </div>

                <!-- Lab Detail Modal -->
                <lab-detail-modal id="lab-detail-modal-v2"></lab-detail-modal>

                <!-- Worker Details Modal (for cross-links) -->
                <worker-details-modal></worker-details-modal>
            </div>
        `;

        this._bindInteractions();
        this._configureDataTable();
    }

    _bindInteractions() {
        // Action bar
        const actionBar = this.querySelector('#labs-action-bar-v2');
        if (actionBar) {
            actionBar.addEventListener('click', e => {
                const action = e.target.closest('[data-action]')?.dataset.action;
                if (action === 'refresh') {
                    this.actions.loadLabRecords(this._getCurrentFilters());
                }
                if (action === 'import') {
                    showToast('Lab import is not yet implemented in the UI', 'info');
                }
            });
        }

        // Metrics toggle
        this.querySelector('#labs-metrics-toggle-v2')?.addEventListener('click', () => {
            this._metricsCollapsed = !this._metricsCollapsed;
            localStorage.setItem(STORAGE_KEY_METRICS, String(this._metricsCollapsed));
            const panel = this.querySelector('#labs-metrics-panel-v2');
            const icon = this.querySelector('#labs-metrics-toggle-v2 i');
            if (panel) panel.classList.toggle('d-none', this._metricsCollapsed);
            if (icon) {
                icon.className = `bi bi-${this._metricsCollapsed ? 'chevron-right' : 'chevron-down'} me-1`;
            }
        });

        // Search input (client-side, debounced)
        const searchInput = this.querySelector('#labs-search-input-v2');
        let searchTimeout;
        searchInput?.addEventListener('input', e => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                this._clientSearchTerm = e.target.value;
                // Re-filter current store data
                const records = selectAllLabRecords(this.getStoreState());
                this._updateDataTable(records);
            }, 300);
        });

        // Status filter (server-side via store action)
        this.querySelector('#labs-status-filter-v2')?.addEventListener('change', e => {
            this._applyFilter('status', e.target.value);
        });

        // Bound filter
        this.querySelector('#labs-bound-filter-v2')?.addEventListener('change', e => {
            const value = e.target.value;
            this._applyFilter('bound', value === 'all' ? null : value === 'true');
        });

        // Terminal toggle
        this.querySelector('#labs-terminal-toggle-v2')?.addEventListener('change', e => {
            this._applyFilter('include_terminal', e.target.checked);
        });

        // Clear filters
        this.querySelector('#labs-clear-filters-v2')?.addEventListener('click', () => {
            this._clearFilters();
        });
    }
}

if (!customElements.get('lab-records-page-v2')) {
    customElements.define('lab-records-page-v2', LabRecordsPageV2);
}

export default LabRecordsPageV2;
