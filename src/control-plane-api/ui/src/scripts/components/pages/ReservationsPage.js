/**
 * ReservationsPage - Reservation Management Page Component
 *
 * Provides a dedicated view for lablet instance reservations:
 * - List all reservations with filtering by status, definition, owner
 * - Search by reservation ID
 * - Lookup by external reservation ID
 * - Quick actions: create, terminate, view details
 * - Real-time updates via SSE
 *
 * Uses LcmTabView for sub-navigation, LcmDataTable for table views,
 * and LcmMetricCard for summary statistics.
 *
 * @module components/pages/ReservationsPage
 */

import { BaseComponent } from '../../core/BaseComponent.js';
import { eventBus, EventTypes } from '../../core/EventBus.js';
import { showConfirmAsync } from '../modals.js';
import '../core/LcmTabView.js';
import '../core/LcmDataTable.js';
import '../core/LcmActionBar.js';
import '../core/LcmStatusBadge.js';
import '../core/LcmMetricCard.js';

export class ReservationsPage extends BaseComponent {
    static get observedAttributes() {
        return ['active-tab', 'view-mode'];
    }

    constructor() {
        super();
        this._currentUser = null;
        this._activeTab = 'active';
        this._viewMode = 'table';
        this._instances = [];
        this._stats = {
            total: 0,
            pending: 0,
            scheduled: 0,
            instantiating: 0,
            ready: 0,
            running: 0,
            terminated: 0,
        };
        this._isLoading = true;
        this._refreshInterval = null;
        this._lookupResult = null;
        this._lookupError = null;
    }

    /**
     * Initialize the page with user context
     * @param {Object} user - Current user object with roles
     */
    initialize(user) {
        this._currentUser = user;
        this.render();
        this._setupEventListeners();
        this._loadData();

        // Auto-refresh every 30 seconds
        this._refreshInterval = setInterval(() => this._loadData(), 30000);
    }

    onMount() {
        this.innerHTML = this._renderLoading();
    }

    onUnmount() {
        if (this._refreshInterval) {
            clearInterval(this._refreshInterval);
            this._refreshInterval = null;
        }
    }

    onAttributeChange(name, oldValue, newValue) {
        switch (name) {
            case 'active-tab':
                this._activeTab = newValue;
                this._updateTabContent();
                break;
            case 'view-mode':
                this._viewMode = newValue;
                this.render();
                break;
        }
    }

    /**
     * Check if user has admin or manager role
     */
    _isAdminOrManager() {
        if (!this._currentUser?.roles) return false;
        const adminRoles = ['admin', 'manager', 'lcm-admin', 'lcm-manager'];
        return this._currentUser.roles.some(role => adminRoles.includes(role.toLowerCase()));
    }

    /**
     * Load reservation data from API
     */
    async _loadData() {
        try {
            const { listLabletSessions } = await import('../../api/lablet-sessions.js');

            // Load active instances
            const active = await listLabletSessions({ include_terminated: false });
            // Load all instances for stats (including terminated)
            const all = await listLabletSessions({ include_terminated: true, limit: 500 });

            this._instances = all;

            // Compute stats
            this._stats = {
                total: all.length,
                pending: 0,
                scheduled: 0,
                instantiating: 0,
                ready: 0,
                running: 0,
                terminated: 0,
            };

            all.forEach(inst => {
                const status = (inst.status || '').toLowerCase();
                if (this._stats.hasOwnProperty(status)) {
                    this._stats[status]++;
                }
            });

            this._isLoading = false;
            this.render();
        } catch (error) {
            console.error('[ReservationsPage] Failed to load data:', error);
            this._isLoading = false;
            this.render();
        }
    }

    /**
     * Setup SSE event subscriptions
     */
    _setupSSESubscriptions() {
        this.subscribe(EventTypes.LABLET_SESSION_CREATED, () => this._loadData());
        this.subscribe(EventTypes.LABLET_SESSION_STATUS_CHANGED, () => this._loadData());
        this.subscribe(EventTypes.LABLET_SESSION_TERMINATED, () => this._loadData());
        this.subscribe(EventTypes.LABLET_SESSIONS_REFRESH_COMPLETED, () => this._loadData());
    }

    render() {
        const isAdmin = this._isAdminOrManager();

        this.innerHTML = `
            <div class="reservations-page">
                <!-- Page Header -->
                <div class="page-header d-flex justify-content-between align-items-center mb-4">
                    <div>
                        <h2 class="mb-1">
                            <i class="bi bi-calendar-check me-2"></i>Reservations
                        </h2>
                        <p class="text-muted mb-0">Manage lablet instance reservations and their lifecycle</p>
                    </div>
                    <lcm-action-bar id="reservations-action-bar">
                        <lcm-action-bar-primary>
                            <button class="btn btn-primary" data-action="create-instance">
                                <i class="bi bi-plus-circle me-1"></i>New Reservation
                            </button>
                        </lcm-action-bar-primary>
                        <lcm-action-bar-secondary>
                            <button class="btn btn-outline-secondary" data-action="refresh">
                                <i class="bi bi-arrow-clockwise me-1"></i>Refresh
                            </button>
                        </lcm-action-bar-secondary>
                    </lcm-action-bar>
                </div>

                <!-- Summary Stats -->
                <div class="row g-3 mb-4">
                    <div class="col-6 col-lg-2">
                        <lcm-metric-card
                            title="Total"
                            value="${this._stats.total}"
                            icon="bi-calendar-check"
                            color="primary"
                            ${this._isLoading ? 'loading' : ''}>
                        </lcm-metric-card>
                    </div>
                    <div class="col-6 col-lg-2">
                        <lcm-metric-card
                            title="Pending"
                            value="${this._stats.pending}"
                            icon="bi-hourglass-split"
                            color="warning"
                            ${this._isLoading ? 'loading' : ''}>
                        </lcm-metric-card>
                    </div>
                    <div class="col-6 col-lg-2">
                        <lcm-metric-card
                            title="Scheduled"
                            value="${this._stats.scheduled}"
                            icon="bi-calendar-event"
                            color="info"
                            ${this._isLoading ? 'loading' : ''}>
                        </lcm-metric-card>
                    </div>
                    <div class="col-6 col-lg-2">
                        <lcm-metric-card
                            title="Ready"
                            value="${this._stats.ready}"
                            icon="bi-check-circle"
                            color="success"
                            ${this._isLoading ? 'loading' : ''}>
                        </lcm-metric-card>
                    </div>
                    <div class="col-6 col-lg-2">
                        <lcm-metric-card
                            title="Running"
                            value="${this._stats.running}"
                            icon="bi-play-circle"
                            color="success"
                            ${this._isLoading ? 'loading' : ''}>
                        </lcm-metric-card>
                    </div>
                    <div class="col-6 col-lg-2">
                        <lcm-metric-card
                            title="Terminated"
                            value="${this._stats.terminated}"
                            icon="bi-x-circle"
                            color="secondary"
                            ${this._isLoading ? 'loading' : ''}>
                        </lcm-metric-card>
                    </div>
                </div>

                <!-- Reservation Lookup -->
                <div class="card mb-4">
                    <div class="card-header bg-white py-2">
                        <span class="fw-medium"><i class="bi bi-search me-2"></i>Lookup by Reservation ID</span>
                    </div>
                    <div class="card-body">
                        <div class="row g-2 align-items-end">
                            <div class="col-md-6">
                                <label for="reservation-lookup-input" class="form-label small text-muted">External Reservation ID</label>
                                <div class="input-group">
                                    <input type="text" class="form-control" id="reservation-lookup-input"
                                           placeholder="e.g. ext-res-456" aria-label="Reservation ID">
                                    <button class="btn btn-outline-primary" id="reservation-lookup-btn" type="button">
                                        <i class="bi bi-search me-1"></i>Lookup
                                    </button>
                                </div>
                            </div>
                            <div class="col-md-6" id="reservation-lookup-result">
                                ${this._renderLookupResult()}
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Sub-tabs -->
                <lcm-tab-view id="reservations-tabs" variant="underline" persist-key="reservations-tab">
                    <lcm-tab id="active" label="Active" icon="bi-play-circle" ${this._activeTab === 'active' ? 'active' : ''}></lcm-tab>
                    <lcm-tab id="all" label="All Reservations" icon="bi-list-ul"></lcm-tab>
                    <lcm-tab id="timeline" label="Timeline" icon="bi-calendar-range"></lcm-tab>
                </lcm-tab-view>

                <!-- Tab Content -->
                <div class="tab-content mt-4">
                    <div id="reservations-active-content" class="tab-pane ${this._activeTab === 'active' ? 'active' : ''}"
                         ${this._activeTab !== 'active' ? 'style="display: none;"' : ''}>
                        ${this._renderActiveTab()}
                    </div>
                    <div id="reservations-all-content" class="tab-pane ${this._activeTab === 'all' ? 'active' : ''}"
                         ${this._activeTab !== 'all' ? 'style="display: none;"' : ''}>
                        ${this._renderAllTab()}
                    </div>
                    <div id="reservations-timeline-content" class="tab-pane ${this._activeTab === 'timeline' ? 'active' : ''}"
                         ${this._activeTab !== 'timeline' ? 'style="display: none;"' : ''}>
                        ${this._renderTimelineTab()}
                    </div>
                </div>
            </div>
        `;

        this._registerTabContent();
        this._setupEventListeners();
        this._setupSSESubscriptions();
        this._configureDataTables();
    }

    _renderLoading() {
        return `
            <div class="d-flex justify-content-center align-items-center" style="min-height: 200px;">
                <div class="spinner-border text-primary" role="status">
                    <span class="visually-hidden">Loading...</span>
                </div>
            </div>
        `;
    }

    _renderLookupResult() {
        if (this._lookupError) {
            return `
                <div class="alert alert-warning mb-0 py-2">
                    <i class="bi bi-exclamation-triangle me-1"></i>${this._lookupError}
                </div>
            `;
        }
        if (this._lookupResult) {
            const r = this._lookupResult;
            return `
                <div class="alert alert-success mb-0 py-2 d-flex justify-content-between align-items-center">
                    <div>
                        <i class="bi bi-check-circle me-1"></i>
                        <strong>${r.definition_name || r.definition_id}</strong>
                        <lcm-status-badge status="${r.status}" class="ms-2"></lcm-status-badge>
                        <span class="text-muted ms-2 small">${r.id}</span>
                    </div>
                    <button class="btn btn-sm btn-outline-primary" data-action="view-lookup-result" data-id="${r.id}">
                        <i class="bi bi-eye me-1"></i>View
                    </button>
                </div>
            `;
        }
        return '';
    }

    _renderActiveTab() {
        const activeInstances = this._instances.filter(i => {
            const s = (i.status || '').toLowerCase();
            return s !== 'terminated' && s !== 'stopped';
        });

        return `
            <div class="card shadow-sm no-hover-lift">
                <div class="card-header d-flex justify-content-between align-items-center bg-white py-2">
                    <div class="d-flex align-items-center gap-2">
                        <span class="fw-medium text-muted">Active Reservations (${activeInstances.length})</span>
                    </div>
                    <div class="d-flex align-items-center gap-2">
                        <select class="form-select form-select-sm" id="active-status-filter" style="min-width: 140px;">
                            <option value="">All Active</option>
                            <option value="pending">Pending</option>
                            <option value="scheduled">Scheduled</option>
                            <option value="instantiating">Instantiating</option>
                            <option value="ready">Ready</option>
                            <option value="running">Running</option>
                        </select>
                        <div class="input-group input-group-sm" style="width: 250px;">
                            <span class="input-group-text bg-white"><i class="bi bi-search"></i></span>
                            <input type="search" class="form-control" placeholder="Search by name, ID, owner..." id="active-search">
                        </div>
                    </div>
                </div>
                <div class="card-body p-0">
                    ${this._renderReservationTable(activeInstances, 'active-reservations-table')}
                </div>
            </div>
        `;
    }

    _renderAllTab() {
        return `
            <div class="card shadow-sm no-hover-lift">
                <div class="card-header d-flex justify-content-between align-items-center bg-white py-2">
                    <div class="d-flex align-items-center gap-2">
                        <span class="fw-medium text-muted">All Reservations (${this._instances.length})</span>
                    </div>
                    <div class="d-flex align-items-center gap-2">
                        <select class="form-select form-select-sm" id="all-status-filter" style="min-width: 140px;">
                            <option value="">All Statuses</option>
                            <option value="pending">Pending</option>
                            <option value="scheduled">Scheduled</option>
                            <option value="instantiating">Instantiating</option>
                            <option value="ready">Ready</option>
                            <option value="running">Running</option>
                            <option value="terminated">Terminated</option>
                        </select>
                        <div class="input-group input-group-sm" style="width: 250px;">
                            <span class="input-group-text bg-white"><i class="bi bi-search"></i></span>
                            <input type="search" class="form-control" placeholder="Search..." id="all-search">
                        </div>
                    </div>
                </div>
                <div class="card-body p-0">
                    ${this._renderReservationTable(this._instances, 'all-reservations-table')}
                </div>
            </div>
        `;
    }

    _renderTimelineTab() {
        // Group instances by date for a timeline view
        const grouped = {};
        this._instances.forEach(inst => {
            const date = inst.timeslot_start
                ? new Date(inst.timeslot_start).toLocaleDateString('en-US', {
                      weekday: 'short',
                      year: 'numeric',
                      month: 'short',
                      day: 'numeric',
                  })
                : 'Unscheduled';
            if (!grouped[date]) grouped[date] = [];
            grouped[date].push(inst);
        });

        const sortedDates = Object.keys(grouped).sort((a, b) => {
            if (a === 'Unscheduled') return 1;
            if (b === 'Unscheduled') return -1;
            return new Date(a) - new Date(b);
        });

        if (sortedDates.length === 0) {
            return `
                <div class="card">
                    <div class="card-body text-center text-muted py-5">
                        <i class="bi bi-calendar-x fs-1 mb-3"></i>
                        <p>No reservations found. Create your first reservation to see the timeline.</p>
                    </div>
                </div>
            `;
        }

        return `
            <div class="timeline-view">
                ${sortedDates
                    .map(
                        date => `
                    <div class="mb-4">
                        <h6 class="text-muted border-bottom pb-2">
                            <i class="bi bi-calendar3 me-2"></i>${date}
                            <span class="badge bg-secondary ms-2">${grouped[date].length}</span>
                        </h6>
                        <div class="list-group">
                            ${grouped[date]
                                .map(
                                    inst => `
                                <div class="list-group-item list-group-item-action d-flex justify-content-between align-items-center">
                                    <div>
                                        <div class="fw-medium">${inst.definition_name || inst.definition_id || 'N/A'}</div>
                                        <div class="small text-muted">
                                            ${this._formatTimeRange(inst.timeslot_start, inst.timeslot_end)}
                                            ${inst.owner_id ? `<span class="ms-2"><i class="bi bi-person me-1"></i>${inst.owner_id}</span>` : ''}
                                        </div>
                                    </div>
                                    <div class="d-flex align-items-center gap-2">
                                        <lcm-status-badge status="${inst.status}"></lcm-status-badge>
                                        ${
                                            inst.lds_login_url
                                                ? `<a href="${inst.lds_login_url}" target="_blank" class="btn btn-sm btn-outline-success" title="Open Lab">
                                                <i class="bi bi-box-arrow-up-right"></i>
                                            </a>`
                                                : ''
                                        }
                                    </div>
                                </div>
                            `
                                )
                                .join('')}
                        </div>
                    </div>
                `
                    )
                    .join('')}
            </div>
        `;
    }

    _renderReservationTable(instances, tableId) {
        if (instances.length === 0) {
            return `
                <div class="text-center text-muted py-5">
                    <i class="bi bi-calendar-x fs-1 mb-3"></i>
                    <p>No reservations found.</p>
                </div>
            `;
        }

        const rows = instances
            .map(
                inst => `
            <tr data-id="${inst.id}">
                <td>
                    <div class="fw-medium">${inst.definition_name || inst.definition_id || 'N/A'}</div>
                    <div class="small text-muted text-truncate" style="max-width: 200px;" title="${inst.id}">${inst.id}</div>
                </td>
                <td><lcm-status-badge status="${inst.status}"></lcm-status-badge></td>
                <td>${inst.owner_id || '-'}</td>
                <td>
                    <div class="small">${this._formatDateTime(inst.timeslot_start)}</div>
                    <div class="small text-muted">${this._formatDateTime(inst.timeslot_end)}</div>
                </td>
                <td>${inst.worker_id ? `<span class="badge bg-light text-dark">${inst.worker_id.substring(0, 8)}...</span>` : '<span class="text-muted">—</span>'}</td>
                <td>
                    ${
                        inst.lds_login_url
                            ? `<a href="${inst.lds_login_url}" target="_blank" class="btn btn-sm btn-outline-success" title="Open Lab Session">
                            <i class="bi bi-box-arrow-up-right me-1"></i>Open
                        </a>`
                            : inst.lds_session_id
                              ? `<span class="badge bg-info">Provisioned</span>`
                              : '<span class="text-muted">—</span>'
                    }
                </td>
                <td>
                    <div class="btn-group btn-group-sm">
                        <button class="btn btn-outline-danger" data-action="terminate" data-id="${inst.id}"
                                ${(inst.status || '').toLowerCase() === 'terminated' ? 'disabled' : ''}
                                title="Terminate">
                            <i class="bi bi-x-circle"></i>
                        </button>
                    </div>
                </td>
            </tr>
        `
            )
            .join('');

        return `
            <div class="table-responsive">
                <table class="table table-hover mb-0" id="${tableId}">
                    <thead class="table-light">
                        <tr>
                            <th>Definition / ID</th>
                            <th>Status</th>
                            <th>Owner</th>
                            <th>Timeslot</th>
                            <th>Worker</th>
                            <th>LDS Session</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${rows}
                    </tbody>
                </table>
            </div>
        `;
    }

    _registerTabContent() {
        const tabView = this.querySelector('#reservations-tabs');
        if (!tabView) return;

        const contents = {
            active: this.querySelector('#reservations-active-content'),
            all: this.querySelector('#reservations-all-content'),
            timeline: this.querySelector('#reservations-timeline-content'),
        };

        Object.entries(contents).forEach(([id, el]) => {
            if (el) tabView.registerContent(id, el);
        });
    }

    _setupEventListeners() {
        // Tab change
        const tabView = this.querySelector('#reservations-tabs');
        if (tabView) {
            tabView.addEventListener('tab-change', e => {
                this._activeTab = e.detail.tabId;
            });
        }

        // Action bar
        this.addEventListener('click', e => {
            const actionEl = e.target.closest('[data-action]');
            if (!actionEl) return;

            const action = actionEl.dataset.action;
            const id = actionEl.dataset.id;

            switch (action) {
                case 'create-instance':
                    this._openCreateModal();
                    break;
                case 'refresh':
                    this._loadData();
                    break;
                case 'terminate':
                    if (id) this._terminateInstance(id);
                    break;
                case 'view-lookup-result':
                    // Navigate to lablet instances view
                    if (id) window.location.hash = `#lablet-instances?id=${id}`;
                    break;
            }
        });

        // Reservation lookup
        const lookupBtn = this.querySelector('#reservation-lookup-btn');
        const lookupInput = this.querySelector('#reservation-lookup-input');
        if (lookupBtn && lookupInput) {
            lookupBtn.addEventListener('click', () => this._lookupReservation(lookupInput.value));
            lookupInput.addEventListener('keypress', e => {
                if (e.key === 'Enter') this._lookupReservation(lookupInput.value);
            });
        }

        // Status filters
        const activeFilter = this.querySelector('#active-status-filter');
        if (activeFilter) {
            activeFilter.addEventListener('change', e => this._filterTable('active-reservations-table', 'status', e.target.value));
        }
        const allFilter = this.querySelector('#all-status-filter');
        if (allFilter) {
            allFilter.addEventListener('change', e => this._filterTable('all-reservations-table', 'status', e.target.value));
        }

        // Search inputs
        const activeSearch = this.querySelector('#active-search');
        if (activeSearch) {
            activeSearch.addEventListener(
                'input',
                this._debounce(e => this._searchTable('active-reservations-table', e.target.value), 300)
            );
        }
        const allSearch = this.querySelector('#all-search');
        if (allSearch) {
            allSearch.addEventListener(
                'input',
                this._debounce(e => this._searchTable('all-reservations-table', e.target.value), 300)
            );
        }
    }

    _configureDataTables() {
        // Tables are rendered as plain HTML tables for simplicity
        // Row click handlers
        this.querySelectorAll('tbody tr[data-id]').forEach(row => {
            row.style.cursor = 'pointer';
            row.addEventListener('click', e => {
                // Don't navigate if clicking on a button or link
                if (e.target.closest('button, a')) return;
                const id = row.dataset.id;
                if (id) window.location.hash = `#lablet-instances?id=${id}`;
            });
        });
    }

    async _lookupReservation(reservationId) {
        if (!reservationId || !reservationId.trim()) {
            this._lookupError = 'Please enter a reservation ID';
            this._lookupResult = null;
            this._updateLookupResult();
            return;
        }

        try {
            const { getLabletSessionByReservation } = await import('../../api/lablet-sessions.js');
            const result = await getLabletSessionByReservation(reservationId.trim());
            this._lookupResult = result;
            this._lookupError = null;
        } catch (error) {
            this._lookupError = `Reservation "${reservationId.trim()}" not found`;
            this._lookupResult = null;
        }
        this._updateLookupResult();
    }

    _updateLookupResult() {
        const container = this.querySelector('#reservation-lookup-result');
        if (container) {
            container.innerHTML = this._renderLookupResult();
        }
    }

    _filterTable(tableId, column, value) {
        const table = this.querySelector(`#${tableId}`);
        if (!table) return;

        const rows = table.querySelectorAll('tbody tr');
        rows.forEach(row => {
            if (!value) {
                row.style.display = '';
                return;
            }
            const badges = row.querySelectorAll('lcm-status-badge');
            const matches = Array.from(badges).some(b => (b.getAttribute('status') || '').toLowerCase() === value.toLowerCase());
            row.style.display = matches ? '' : 'none';
        });
    }

    _searchTable(tableId, query) {
        const table = this.querySelector(`#${tableId}`);
        if (!table) return;

        const lowerQuery = (query || '').toLowerCase();
        const rows = table.querySelectorAll('tbody tr');
        rows.forEach(row => {
            if (!lowerQuery) {
                row.style.display = '';
                return;
            }
            const text = row.textContent.toLowerCase();
            row.style.display = text.includes(lowerQuery) ? '' : 'none';
        });
    }

    async _openCreateModal() {
        const modal = document.getElementById('createLabletInstanceModal');
        if (modal) {
            const bootstrap = await import('bootstrap');
            new bootstrap.Modal(modal).show();
        } else {
            console.warn('[ReservationsPage] createLabletInstanceModal not found');
        }
    }

    async _terminateInstance(instanceId) {
        if (!(await showConfirmAsync('Terminate Reservation', 'Are you sure you want to terminate this reservation?', { actionLabel: 'Terminate', actionClass: 'btn-danger' }))) return;

        try {
            const { terminateLabletSession } = await import('../../api/lablet-sessions.js');
            await terminateLabletSession(instanceId, 'Terminated from Reservations page');

            const { showToast } = await import('../../ui/notifications.js');
            showToast('Reservation terminated successfully', 'success');

            // Refresh data
            await this._loadData();
        } catch (error) {
            console.error('[ReservationsPage] Failed to terminate:', error);
            const { showToast } = await import('../../ui/notifications.js');
            showToast(`Failed to terminate: ${error.message}`, 'error');
        }
    }

    _formatDateTime(isoString) {
        if (!isoString) return '—';
        try {
            return new Date(isoString).toLocaleString('en-US', {
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
            });
        } catch {
            return isoString;
        }
    }

    _formatTimeRange(start, end) {
        const s = this._formatDateTime(start);
        const e = this._formatDateTime(end);
        if (s === '—' && e === '—') return 'No timeslot';
        return `${s} → ${e}`;
    }

    _updateTabContent() {
        // Handled by LcmTabView registerContent
    }

    /**
     * Debounce utility
     */
    _debounce(fn, delay) {
        let timer;
        return (...args) => {
            clearTimeout(timer);
            timer = setTimeout(() => fn(...args), delay);
        };
    }
}

// Register the component
customElements.define('reservations-page', ReservationsPage);

export default ReservationsPage;
