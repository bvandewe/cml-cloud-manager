/**
 * LabletsPage - Unified Lablet Management Page Component
 *
 * Provides a tabbed interface for Lablets combining instance management
 * and reservation lifecycle:
 * - Active: Non-terminated lablet instances (cards or table view)
 * - All Reservations: All instances including terminated
 * - Timeline: Date-grouped timeline of reservations
 * - Definitions: Manage lablet definitions/templates (Admin only)
 *
 * Includes:
 * - Collapsible summary metric tiles (localStorage persisted)
 * - Inline reservation ID lookup in datatable headers
 * - Full status filter with all LabletInstanceStatus values
 * - Cards/table view toggle (cards default for non-admin, table for admin)
 * - Real-time SSE updates
 * - Full CRUD for definitions (view/edit/create instance/delete)
 *
 * @module components/pages/LabletsPage
 */

import { BaseComponent } from '../../core/BaseComponent.js';
import { eventBus, EventTypes } from '../../core/EventBus.js';
import * as labletSessionsApi from '../../api/lablet-sessions.js';
import * as labletDefinitionsApi from '../../api/lablet-definitions.js';
import { showToast } from '../../ui/notifications.js';
import { showConfirmAsync } from '../modals.js';
import * as bootstrap from 'bootstrap';
import '../core/LcmTabView.js';
import '../core/LcmDataTable.js';
import '../core/LcmActionBar.js';
import '../core/LcmStatusBadge.js';
import '../core/LcmMetricCard.js';
import '../core/LcmCodeViewer.js';
import { renderDefinitionDetailsHtml, mountDefinitionContentViewer, mountPortPreferenceHandlers } from '../shared/definition-details-renderer.js';
import '../LabletSessionCard.js';
import '../LabletSessionList.js';

const STORAGE_KEY_METRICS = 'lcm.lablets.metricsCollapsed';

export class LabletsPage extends BaseComponent {
    static get observedAttributes() {
        return ['active-tab', 'view-mode'];
    }

    constructor() {
        super();
        this._currentUser = null;
        this._activeTab = 'active';
        this._viewMode = null;
        this._instances = [];
        this._definitions = [];
        this._stats = this._emptyStats();
        this._isLoading = true;
        this._refreshInterval = null;
        this._metricsCollapsed = localStorage.getItem(STORAGE_KEY_METRICS) === 'true';
    }

    _emptyStats() {
        return {
            total: 0,
            pending: 0,
            scheduled: 0,
            worker_assigned: 0,
            instantiating: 0,
            provisioning: 0,
            ready: 0,
            running: 0,
            collecting: 0,
            grading: 0,
            terminating: 0,
            terminated: 0,
        };
    }

    /**
     * Initialize the page with user context
     * @param {Object} user - Current user object with roles
     */
    initialize(user) {
        this._currentUser = user;
        this._viewMode = this._isAdminOrManager() ? 'table' : 'cards';
        this.render();
        this._setupEventListeners();
        this._setupSSESubscriptions();
        this._configureDataTables();
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
                this._updateViewMode();
                break;
        }
    }

    _isAdminOrManager() {
        if (!this._currentUser?.roles) return false;
        const adminRoles = ['admin', 'manager', 'lcm-admin', 'lcm-manager'];
        return this._currentUser.roles.some(role => adminRoles.includes(role.toLowerCase()));
    }

    // ========== Data Loading ==========

    async _loadData() {
        try {
            const all = await labletSessionsApi.listLabletSessions({ include_terminated: true, limit: 500 });
            this._instances = all;
            this._stats = this._emptyStats();
            this._stats.total = all.length;

            all.forEach(inst => {
                const status = (inst.status || '').toLowerCase();
                if (this._stats.hasOwnProperty(status)) {
                    this._stats[status]++;
                }
            });

            this._isLoading = false;
            this.render();
        } catch (error) {
            console.error('[LabletsPage] Failed to load data:', error);
            this._isLoading = false;
            this.render();
        }
    }

    // ========== SSE ==========

    _setupSSESubscriptions() {
        this.subscribe(EventTypes.LABLET_SESSION_CREATED, () => this._loadData());
        this.subscribe(EventTypes.LABLET_SESSION_STATUS_CHANGED, () => this._loadData());
        this.subscribe(EventTypes.LABLET_SESSION_TERMINATED, () => this._loadData());
        this.subscribe(EventTypes.LABLET_SESSIONS_REFRESH_COMPLETED, () => this._loadData());

        // Definition sync lifecycle -> update table row in-place
        this.subscribe(EventTypes.LABLET_DEFINITION_CONTENT_SYNCED, data => {
            if (!data?.definition_id) return;
            const table = this.querySelector('#lablet-definitions-table');
            if (table) {
                const updates = {
                    sync_status: data.sync_status,
                    last_synced_at: data.synced_at,
                };
                if (data.sync_status === 'success') {
                    updates.status = 'active';
                }
                table.updateRow(data.definition_id, updates);
            }
        });

        this.subscribe(EventTypes.LABLET_DEFINITION_SYNC_REQUESTED, data => {
            if (!data?.definition_id) return;
            const table = this.querySelector('#lablet-definitions-table');
            if (table) {
                table.updateRow(data.definition_id, {
                    sync_status: 'syncing',
                });
            }
        });
    }

    // ========== Render ==========

    render() {
        const isAdmin = this._isAdminOrManager();
        const activeCount = this._instances.filter(i => {
            const s = (i.status || '').toLowerCase();
            return s !== 'terminated' && s !== 'terminating';
        }).length;

        this.innerHTML = `
            <div class="lablets-page">
                <!-- Page Header with Action Bar -->
                <div class="page-header d-flex justify-content-between align-items-center mb-4">
                    <div>
                        <h2 class="mb-1"><i class="bi bi-collection me-2"></i>Lablets</h2>
                        <p class="text-muted mb-0">Manage lab instances, reservations, and definitions</p>
                    </div>
                    <lcm-action-bar id="lablets-action-bar">
                        <lcm-action-bar-primary>
                            <button class="btn btn-primary" data-action="create-instance">
                                <i class="bi bi-plus-circle me-1"></i>New Lablet
                            </button>
                            ${
                                isAdmin
                                    ? `
                            <button class="btn btn-outline-primary" data-action="create-definition">
                                <i class="bi bi-file-earmark-plus me-1"></i>New Definition
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

                <!-- Collapsible Summary Stats Tiles -->
                <div class="mb-4">
                    <div class="d-flex align-items-center mb-2" role="button" id="metrics-toggle">
                        <span class="fw-medium text-muted small text-uppercase me-2">
                            <i class="bi bi-bar-chart-line me-1"></i>Summary
                        </span>
                        <hr class="flex-grow-1 my-0">
                        <i class="bi bi-chevron-${this._metricsCollapsed ? 'down' : 'up'} ms-2 text-muted" id="metrics-chevron"></i>
                    </div>
                    <div id="metrics-panel" class="${this._metricsCollapsed ? 'd-none' : ''}">
                        <div class="row g-3">
                            <div class="col-6 col-lg-2">
                                <lcm-metric-card title="Total" value="${this._stats.total}"
                                    icon="bi-calendar-check" color="primary"
                                    ${this._isLoading ? 'loading' : ''}></lcm-metric-card>
                            </div>
                            <div class="col-6 col-lg-2" data-bs-toggle="tooltip" data-bs-placement="bottom"
                                 title="pending / scheduled / assigned">
                                <lcm-metric-card title="Pending" value="${this._stats.pending + this._stats.scheduled + this._stats.worker_assigned}"
                                    icon="bi-hourglass-split" color="warning"
                                    ${this._isLoading ? 'loading' : ''}></lcm-metric-card>
                            </div>
                            <div class="col-6 col-lg-2">
                                <lcm-metric-card title="Provisioning" value="${this._stats.instantiating + this._stats.provisioning}"
                                    icon="bi-gear-wide-connected" color="info"
                                    ${this._isLoading ? 'loading' : ''}></lcm-metric-card>
                            </div>
                            <div class="col-6 col-lg-2">
                                <lcm-metric-card title="Ready" value="${this._stats.ready}"
                                    icon="bi-check-circle" color="success"
                                    ${this._isLoading ? 'loading' : ''}></lcm-metric-card>
                            </div>
                            <div class="col-6 col-lg-2">
                                <lcm-metric-card title="Running" value="${this._stats.running}"
                                    icon="bi-play-circle" color="success"
                                    ${this._isLoading ? 'loading' : ''}></lcm-metric-card>
                            </div>
                            <div class="col-6 col-lg-2">
                                <lcm-metric-card title="Terminated" value="${this._stats.terminated}"
                                    icon="bi-x-circle" color="secondary"
                                    ${this._isLoading ? 'loading' : ''}></lcm-metric-card>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Sub-tabs with View Toggle -->
                <div class="d-flex justify-content-between align-items-center">
                    <lcm-tab-view id="lablets-tabs" variant="underline" persist-key="lablets-tab">
                        <lcm-tab id="active" label="Active (${activeCount})" icon="bi-play-circle" ${this._activeTab === 'active' ? 'active' : ''}></lcm-tab>
                        <lcm-tab id="all" label="All Reservations" icon="bi-list-ul" ${this._activeTab === 'all' ? 'active' : ''}></lcm-tab>
                        <lcm-tab id="timeline" label="Timeline" icon="bi-calendar-range" ${this._activeTab === 'timeline' ? 'active' : ''}></lcm-tab>
                        ${isAdmin ? `<lcm-tab id="definitions" label="Definitions" icon="bi-file-earmark-code" ${this._activeTab === 'definitions' ? 'active' : ''}></lcm-tab>` : ''}
                    </lcm-tab-view>

                    <div class="btn-group btn-group-sm" role="group" aria-label="View mode" id="view-toggle-group"
                         style="${this._activeTab === 'active' || this._activeTab === 'all' ? '' : 'display: none;'}">
                        <button type="button" class="btn btn-outline-secondary ${this._viewMode === 'cards' ? 'active' : ''}"
                                data-view="cards" title="Card view">
                            <i class="bi bi-grid-3x2-gap"></i>
                        </button>
                        <button type="button" class="btn btn-outline-secondary ${this._viewMode === 'table' ? 'active' : ''}"
                                data-view="table" title="Table view">
                            <i class="bi bi-list-ul"></i>
                        </button>
                    </div>
                </div>

                <!-- Tab Content -->
                <div class="tab-content mt-4">
                    <div id="lablets-active-content" class="tab-pane ${this._activeTab === 'active' ? 'active' : ''}"
                         ${this._activeTab !== 'active' ? 'style="display: none;"' : ''}>
                        ${this._renderActiveTab()}
                    </div>
                    <div id="lablets-all-content" class="tab-pane ${this._activeTab === 'all' ? 'active' : ''}"
                         ${this._activeTab !== 'all' ? 'style="display: none;"' : ''}>
                        ${this._renderAllTab()}
                    </div>
                    <div id="lablets-timeline-content" class="tab-pane ${this._activeTab === 'timeline' ? 'active' : ''}"
                         ${this._activeTab !== 'timeline' ? 'style="display: none;"' : ''}>
                        ${this._renderTimelineTab()}
                    </div>
                    ${
                        isAdmin
                            ? `
                    <div id="lablets-definitions-content" class="tab-pane ${this._activeTab === 'definitions' ? 'active' : ''}"
                         ${this._activeTab !== 'definitions' ? 'style="display: none;"' : ''}>
                        ${this._renderDefinitionsTab()}
                    </div>`
                            : ''
                    }
                </div>
            </div>
        `;

        this._registerTabContent();
        this._setupEventListeners();
        this._configureDataTables();
        this._initTooltips();
    }

    _initTooltips() {
        this.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => {
            bootstrap.Tooltip.getOrCreateInstance(el);
        });
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

    // ========== Tab Renderers ==========

    _renderActiveTab() {
        const activeInstances = this._instances.filter(i => {
            const s = (i.status || '').toLowerCase();
            return s !== 'terminated' && s !== 'terminating';
        });

        if (this._viewMode === 'cards') {
            return `
                <div class="d-flex justify-content-end mb-3 gap-2">
                    ${this._renderStatusFilterDropdown('active-status-filter', false)}
                </div>
                <lablet-session-list id="lablet-sessions-list" view="cards"></lablet-session-list>
            `;
        }
        return this._renderInstancesTable(activeInstances, 'active', false);
    }

    _renderAllTab() {
        if (this._viewMode === 'cards') {
            return `
                <div class="d-flex justify-content-end mb-3 gap-2">
                    ${this._renderStatusFilterDropdown('all-status-filter', true)}
                </div>
                <lablet-session-list id="lablet-all-sessions-list" view="cards" show-terminated></lablet-session-list>
            `;
        }
        return this._renderInstancesTable(this._instances, 'all', true);
    }

    /**
     * Render a table view with inline filters (region, status, reservation lookup, search)
     */
    _renderInstancesTable(instances, prefix, includeTerminal) {
        const label = prefix === 'active' ? `Active Lablets (${instances.length})` : `All Reservations (${instances.length})`;

        return `
            <div class="card shadow-sm no-hover-lift">
                <div class="card-header bg-white py-2">
                    <div class="d-flex justify-content-between align-items-center gap-2">
                        <span class="fw-medium text-muted text-nowrap">${label}</span>
                        <div class="d-flex align-items-center gap-2 flex-nowrap">
                            <select class="form-select form-select-sm" id="${prefix}-region-filter" style="width: 110px;">
                                <option value="">All Regions</option>
                                <option value="us-east-1">us-east-1</option>
                                <option value="us-west-1">us-west-1</option>
                                <option value="us-west-2">us-west-2</option>
                                <option value="eu-west-1">eu-west-1</option>
                                <option value="eu-central-1">eu-central-1</option>
                                <option value="ap-northeast-1">ap-northeast-1</option>
                                <option value="ap-southeast-1">ap-southeast-1</option>
                            </select>
                            ${this._renderStatusFilterDropdown(`${prefix}-status-filter`, includeTerminal)}
                            <div class="input-group input-group-sm" style="width: 170px;">
                                <span class="input-group-text bg-white" title="Reservation ID"><i class="bi bi-bookmark"></i></span>
                                <input type="search" class="form-control" placeholder="Reservation..."
                                       id="${prefix}-reservation-lookup" title="Lookup by external reservation ID">
                            </div>
                            <div class="input-group input-group-sm" style="width: 160px;">
                                <span class="input-group-text bg-white"><i class="bi bi-search"></i></span>
                                <input type="search" class="form-control" placeholder="Search..." id="${prefix}-search">
                            </div>
                        </div>
                    </div>
                </div>
                <div class="card-body p-0">
                    ${this._renderReservationTable(instances, `${prefix}-reservations-table`)}
                </div>
            </div>
        `;
    }

    _renderStatusFilterDropdown(id, includeTerminal = false) {
        return `
            <select class="form-select form-select-sm" id="${id}" style="width: 130px;">
                <option value="">All Statuses</option>
                <option value="pending">Pending</option>
                <option value="scheduled">Scheduled</option>
                <option value="worker_assigned">Worker Assigned</option>
                <option value="instantiating">Instantiating</option>
                <option value="provisioning">Provisioning</option>
                <option value="ready">Ready</option>
                <option value="running">Running</option>
                <option value="collecting">Collecting</option>
                <option value="grading">Grading</option>
                ${
                    includeTerminal
                        ? `
                <option value="terminating">Terminating</option>
                <option value="terminated">Terminated</option>`
                        : ''
                }
            </select>
        `;
    }

    _renderReservationTable(instances, tableId) {
        if (instances.length === 0) {
            return `
                <div class="text-center text-muted py-5">
                    <i class="bi bi-collection fs-1 mb-3 d-block"></i>
                    <h6 class="text-muted">No Lablet Instances</h6>
                    <p>No instances match your current filters.</p>
                </div>
            `;
        }

        const rows = instances
            .map(
                inst => `
            <tr data-id="${inst.id}" role="button">
                <td>
                    <div class="fw-medium">${inst.definition_name || inst.definition_id || 'N/A'}</div>
                    <div class="small text-muted text-truncate" style="max-width: 200px;" title="${inst.id}">${inst.id}</div>
                </td>
                <td><lcm-status-badge status="${inst.status}"></lcm-status-badge></td>
                <td>${inst.owner_id || '—'}</td>
                <td>
                    <div class="small">${this._formatDateTime(inst.timeslot_start)}</div>
                    <div class="small text-muted">${this._formatDateTime(inst.timeslot_end)}</div>
                </td>
                <td>${inst.worker_id ? `<span class="badge bg-light text-dark">${inst.worker_id.substring(0, 8)}...</span>` : '<span class="text-muted">—</span>'}</td>
                <td>
                    ${
                        inst.lds_login_url
                            ? `<a href="${inst.lds_login_url}" target="_blank" class="btn btn-sm btn-outline-success" title="Open Lab Session">
                            <i class="bi bi-box-arrow-up-right me-1"></i>Open</a>`
                            : inst.lds_session_id
                              ? `<span class="badge bg-info">Provisioned</span>`
                              : '<span class="text-muted">—</span>'
                    }
                </td>
                <td>
                    <div class="btn-group btn-group-sm">
                        <button class="btn btn-outline-primary btn-sm" data-action="view-instance" data-id="${inst.id}" title="View details">
                            <i class="bi bi-eye"></i>
                        </button>
                        <button class="btn btn-outline-danger btn-sm" data-action="terminate" data-id="${inst.id}"
                                ${['terminated', 'terminating'].includes((inst.status || '').toLowerCase()) ? 'disabled' : ''}
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
                    <tbody>${rows}</tbody>
                </table>
            </div>
        `;
    }

    _renderTimelineTab() {
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
                        <i class="bi bi-calendar-x fs-1 mb-3 d-block"></i>
                        <p>No reservations found. Create your first lablet to see the timeline.</p>
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
                                <div class="list-group-item list-group-item-action d-flex justify-content-between align-items-center"
                                     role="button" data-action="view-instance" data-id="${inst.id}">
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
                                                <i class="bi bi-box-arrow-up-right"></i></a>`
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

    _renderDefinitionsTab() {
        return `
            <div class="card shadow-sm no-hover-lift">
                <div class="card-header d-flex justify-content-between align-items-center bg-white py-2">
                    <span class="fw-medium text-muted">All Definitions</span>
                    <div class="d-flex align-items-center gap-2">
                        <select class="form-select form-select-sm" id="definition-table-status-filter" style="width: auto;">
                            <option value="">All Statuses</option>
                            <option value="active">Active</option>
                            <option value="pending_sync">Pending Sync</option>
                            <option value="draft">Draft</option>
                            <option value="archived">Archived</option>
                        </select>
                        <div class="input-group input-group-sm" style="width: 200px;">
                            <span class="input-group-text bg-white"><i class="bi bi-search"></i></span>
                            <input type="search" class="form-control" placeholder="Search..." id="definition-table-search">
                        </div>
                    </div>
                </div>
                <div class="card-body p-0">
                    <lcm-data-table
                        id="lablet-definitions-table"
                        data-source="/api/lablet-definitions/"
                        page-size="25"
                        selectable
                        panel-mode
                        empty-message="No lablet definitions found. Create your first definition to get started.">
                    </lcm-data-table>
                </div>
            </div>
        `;
    }

    // ========== Tab Management ==========

    _registerTabContent() {
        const tabView = this.querySelector('#lablets-tabs');
        if (!tabView) return;

        const contents = {
            active: this.querySelector('#lablets-active-content'),
            all: this.querySelector('#lablets-all-content'),
            timeline: this.querySelector('#lablets-timeline-content'),
            definitions: this.querySelector('#lablets-definitions-content'),
        };

        Object.entries(contents).forEach(([id, el]) => {
            if (el) tabView.registerContent(id, el);
        });
    }

    // ========== Event Listeners ==========

    _setupEventListeners() {
        // Metrics panel toggle
        const metricsToggle = this.querySelector('#metrics-toggle');
        if (metricsToggle) {
            metricsToggle.addEventListener('click', () => {
                this._metricsCollapsed = !this._metricsCollapsed;
                localStorage.setItem(STORAGE_KEY_METRICS, this._metricsCollapsed);

                const panel = this.querySelector('#metrics-panel');
                const chevron = this.querySelector('#metrics-chevron');
                if (panel) panel.classList.toggle('d-none', this._metricsCollapsed);
                if (chevron) {
                    chevron.classList.toggle('bi-chevron-down', this._metricsCollapsed);
                    chevron.classList.toggle('bi-chevron-up', !this._metricsCollapsed);
                }
            });
        }

        // Tab change
        const tabView = this.querySelector('#lablets-tabs');
        if (tabView) {
            tabView.addEventListener('tab-change', e => {
                this._activeTab = e.detail.tabId;
                this._onTabChange(e.detail);
            });
        }

        // Click delegation for all actions
        this.addEventListener('click', e => {
            const actionEl = e.target.closest('[data-action]');
            if (!actionEl) return;

            const action = actionEl.dataset.action;
            const id = actionEl.dataset.id;

            switch (action) {
                case 'create-instance':
                    this._openCreateModal();
                    break;
                case 'create-definition':
                    this._openCreateDefinitionModal();
                    break;
                case 'refresh':
                    this._handleRefresh();
                    break;
                case 'terminate':
                    if (id) this._terminateInstance(id);
                    break;
                case 'view-instance':
                    if (id) this._showInstanceDetails(id);
                    break;
                case 'view':
                    if (id) this._viewDefinition(id);
                    break;
                case 'edit':
                    if (id) this._editDefinition(id);
                    break;
                case 'deploy':
                    if (id) this._createInstanceFromDefinition(id);
                    break;
                case 'delete':
                    if (id) this._deleteDefinition(id);
                    break;
                case 'sync':
                    if (id) this._syncDefinition(id);
                    break;
            }
        });

        // View toggle
        this.querySelectorAll('#view-toggle-group [data-view]').forEach(btn => {
            btn.addEventListener('click', e => {
                this._setViewMode(e.currentTarget.dataset.view);
            });
        });

        // Status filters
        this._setupFilter('active-status-filter', 'active-reservations-table', 'status');
        this._setupFilter('all-status-filter', 'all-reservations-table', 'status');

        // Region filters
        this._setupFilter('active-region-filter', 'active-reservations-table', 'region');
        this._setupFilter('all-region-filter', 'all-reservations-table', 'region');

        // Search inputs
        this._setupSearch('active-search', 'active-reservations-table');
        this._setupSearch('all-search', 'all-reservations-table');

        // Reservation lookup inputs
        this._setupReservationLookup('active-reservation-lookup', 'active-reservations-table');
        this._setupReservationLookup('all-reservation-lookup', 'all-reservations-table');

        // Definition filters
        const defStatusFilter = this.querySelector('#definition-table-status-filter');
        if (defStatusFilter) {
            defStatusFilter.addEventListener('change', e => this._filterDefinitionsByStatus(e.target.value));
        }
        const defSearchInput = this.querySelector('#definition-table-search');
        if (defSearchInput) {
            defSearchInput.addEventListener(
                'input',
                this._debounce(e => this._searchDefinitions(e.target.value), 300)
            );
        }

        // Row click handlers for instance tables
        this.querySelectorAll('tbody tr[data-id]').forEach(row => {
            row.addEventListener('click', e => {
                if (e.target.closest('button, a')) return;
                const id = row.dataset.id;
                if (id) this._showInstanceDetails(id);
            });
        });
    }

    _setupFilter(selectId, tableId, column) {
        const el = this.querySelector(`#${selectId}`);
        if (el) {
            el.addEventListener('change', e => this._filterTable(tableId, column, e.target.value));
        }
    }

    _setupSearch(inputId, tableId) {
        const el = this.querySelector(`#${inputId}`);
        if (el) {
            el.addEventListener(
                'input',
                this._debounce(e => this._searchTable(tableId, e.target.value), 300)
            );
        }
    }

    _setupReservationLookup(inputId, tableId) {
        const el = this.querySelector(`#${inputId}`);
        if (!el) return;

        const handler = this._debounce(async e => {
            const query = e.target.value.trim();
            if (!query) {
                // Clear: show all rows again
                this._searchTable(tableId, '');
                el.classList.remove('is-valid', 'is-invalid');
                return;
            }

            try {
                const result = await labletSessionsApi.getLabletSessionByReservation(query);
                if (result) {
                    const table = this.querySelector(`#${tableId}`);
                    if (table) {
                        table.querySelectorAll('tbody tr').forEach(row => {
                            row.style.display = row.dataset.id === result.id ? '' : 'none';
                        });
                    }
                    el.classList.remove('is-invalid');
                    el.classList.add('is-valid');
                }
            } catch {
                el.classList.remove('is-valid');
                el.classList.add('is-invalid');
            }
        }, 500);

        el.addEventListener('input', handler);
    }

    _configureDataTables() {
        const definitionsTable = this.querySelector('#lablet-definitions-table');
        if (!definitionsTable) return;

        definitionsTable.setColumns([
            { field: 'name', label: 'Name', sortable: true },
            { field: 'form_qualified_name', label: 'Form QN', sortable: true, render: val => (val ? `<span class="text-truncate d-inline-block" style="max-width: 200px;" title="${val}">${val}</span>` : '<span class="text-muted">—</span>') },
            {
                field: 'status',
                label: 'Status',
                sortable: true,
                render: val => `<lcm-status-badge status="${val}"></lcm-status-badge>`,
            },
            {
                field: 'sync_status',
                label: 'Sync',
                sortable: true,
                render: val => (val ? `<lcm-status-badge status="${val}"></lcm-status-badge>` : '<span class="text-muted">—</span>'),
            },
            { field: 'node_count', label: 'Nodes', sortable: true },
            { field: 'link_count', label: 'Links', sortable: true },
            { field: 'updated_at', label: 'Updated', sortable: true, type: 'datetime' },
            {
                field: 'actions',
                label: 'Actions',
                render: (_, row) => `
                    <div class="btn-group btn-group-sm">
                        <button class="btn btn-outline-primary" data-action="view" data-id="${row.id}" title="View details">
                            <i class="bi bi-eye"></i>
                        </button>
                        <button class="btn btn-outline-secondary" data-action="edit" data-id="${row.id}" title="Edit">
                            <i class="bi bi-pencil"></i>
                        </button>
                        <button class="btn btn-outline-info" data-action="sync" data-id="${row.id}" title="Sync content">
                            <i class="bi bi-arrow-repeat"></i>
                        </button>
                        <button class="btn btn-outline-success" data-action="deploy" data-id="${row.id}" title="Create instance from this definition">
                            <i class="bi bi-rocket"></i>
                        </button>
                        <button class="btn btn-outline-danger" data-action="delete" data-id="${row.id}" title="Delete">
                            <i class="bi bi-trash"></i>
                        </button>
                    </div>
                `,
            },
        ]);

        definitionsTable.setBulkActions([
            { id: 'activate', label: 'Activate Selected', icon: 'bi-check-circle', variant: 'success' },
            { id: 'archive', label: 'Archive Selected', icon: 'bi-archive', variant: 'secondary' },
            { id: 'delete', label: 'Delete Selected', icon: 'bi-trash', variant: 'danger' },
        ]);

        // Row click navigates to view
        definitionsTable.addEventListener('row-click', e => {
            const row = e.detail?.row;
            if (row?.id) this._viewDefinition(row.id);
        });
    }

    // ========== Tab Change ==========

    _onTabChange({ tabId, previousTabId }) {
        console.log(`[LabletsPage] Tab changed: ${previousTabId} → ${tabId}`);

        const viewToggle = this.querySelector('#view-toggle-group');
        if (viewToggle) {
            viewToggle.style.display = tabId === 'active' || tabId === 'all' ? '' : 'none';
        }

        eventBus.emit('lablets.tab.changed', { tabId, previousTabId });

        if (tabId === 'definitions') {
            this._refreshDefinitions();
        }
    }

    _handleRefresh() {
        if (this._activeTab === 'definitions') {
            this._refreshDefinitions();
        } else {
            this._loadData();
        }
    }

    // ========== Modal Actions ==========

    _openCreateModal(preselectedDefinitionId = null) {
        const modal = document.getElementById('createLabletSessionModal');
        if (!modal) {
            console.warn('[LabletsPage] createLabletSessionModal not found');
            return;
        }

        // Populate definitions dropdown before showing
        this._populateDefinitionDropdown(preselectedDefinitionId);

        // Set default start time to now + 2 minutes
        const startInput = document.getElementById('instanceTimeslotStart');
        if (startInput) {
            const defaultStart = new Date(Date.now() + 2 * 60 * 1000);
            // Format as YYYY-MM-DDTHH:mm for datetime-local input
            const pad = n => String(n).padStart(2, '0');
            startInput.value = `${defaultStart.getFullYear()}-${pad(defaultStart.getMonth() + 1)}-${pad(defaultStart.getDate())}T${pad(defaultStart.getHours())}:${pad(defaultStart.getMinutes())}`;
        }

        // Ensure duration has default value
        const durationInput = document.getElementById('instanceDuration');
        if (durationInput && !durationInput.value) {
            durationInput.value = '120';
        }

        bootstrap.Modal.getOrCreateInstance(modal).show();
    }

    async _populateDefinitionDropdown(preselectedId = null) {
        const select = document.getElementById('instanceDefinitionId');
        if (!select) return;

        try {
            const definitions = await labletDefinitionsApi.listLabletDefinitions({ status: 'active' });

            // Clear existing options (keep placeholder)
            select.innerHTML = '<option value="">Select a definition...</option>';

            definitions.forEach(def => {
                const option = document.createElement('option');
                option.value = def.id;
                option.textContent = `${def.name} v${def.version} (${def.node_count || 0} nodes, ${def.cpu_cores || 0} CPU, ${def.memory_gb || 0} GB RAM)`;
                option.dataset.name = def.name;
                option.dataset.version = def.version || '';
                option.dataset.cpu = def.cpu_cores || 0;
                option.dataset.memory = def.memory_gb || 0;
                option.dataset.nodes = def.node_count || 0;
                select.appendChild(option);
            });

            if (preselectedId) {
                select.value = preselectedId;
                select.dispatchEvent(new Event('change'));
            }
        } catch (error) {
            console.error('[LabletsPage] Failed to load definitions for dropdown:', error);
            select.innerHTML = '<option value="">Failed to load definitions</option>';
        }
    }

    _openCreateDefinitionModal() {
        const modal = document.getElementById('createLabletDefinitionModal');
        if (!modal) return;
        bootstrap.Modal.getOrCreateInstance(modal).show();
    }

    // ========== View Mode ==========

    _setViewMode(mode) {
        this._viewMode = mode;
        this.querySelectorAll('#view-toggle-group [data-view]').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.view === mode);
        });

        // Re-render only the visible tab
        if (this._activeTab === 'active') {
            const el = this.querySelector('#lablets-active-content');
            if (el) {
                el.innerHTML = this._renderActiveTab();
                this._setupEventListeners();
            }
        } else if (this._activeTab === 'all') {
            const el = this.querySelector('#lablets-all-content');
            if (el) {
                el.innerHTML = this._renderAllTab();
                this._setupEventListeners();
            }
        }
    }

    _updateViewMode() {
        const instanceList = this.querySelector('#lablet-sessions-list');
        if (instanceList) instanceList.setAttribute('view', this._viewMode);
    }

    // ========== Table Filtering ==========

    _filterTable(tableId, column, value) {
        const table = this.querySelector(`#${tableId}`);
        if (!table) return;

        table.querySelectorAll('tbody tr').forEach(row => {
            if (!value) {
                row.style.display = '';
                return;
            }
            if (column === 'status') {
                const badges = row.querySelectorAll('lcm-status-badge');
                const matches = Array.from(badges).some(b => (b.getAttribute('status') || '').toLowerCase() === value.toLowerCase());
                row.style.display = matches ? '' : 'none';
            } else {
                const text = row.textContent.toLowerCase();
                row.style.display = text.includes(value.toLowerCase()) ? '' : 'none';
            }
        });
    }

    _searchTable(tableId, query) {
        const table = this.querySelector(`#${tableId}`);
        if (!table) return;

        const lowerQuery = (query || '').toLowerCase();
        table.querySelectorAll('tbody tr').forEach(row => {
            row.style.display = !lowerQuery || row.textContent.toLowerCase().includes(lowerQuery) ? '' : 'none';
        });
    }

    _filterDefinitionsByStatus(status) {
        const t = this.querySelector('#lablet-definitions-table');
        if (t) t.setFilter('status', status);
    }

    _searchDefinitions(term) {
        const t = this.querySelector('#lablet-definitions-table');
        if (t) t.setSearch(term);
    }

    _refreshDefinitions() {
        const t = this.querySelector('#lablet-definitions-table');
        if (t) t.loadData();
    }

    async _syncDefinition(definitionId) {
        try {
            await labletDefinitionsApi.syncLabletDefinition(definitionId);
            showToast('Sync requested — content will be synchronized shortly.', 'success');
            this._refreshDefinitions();
        } catch (error) {
            console.error('[LabletsPage] Failed to sync definition:', error);
            showToast(`Sync failed: ${error.message}`, 'error');
        }
    }

    // ========== Definition CRUD Actions ==========

    async _viewDefinition(definitionId) {
        try {
            const def = await labletDefinitionsApi.getLabletDefinition(definitionId);
            const modal = document.getElementById('labletDefinitionDetailsModal');
            const content = document.getElementById('labletDefinitionDetailsContent');
            if (!modal || !content) return;

            content.innerHTML = renderDefinitionDetailsHtml(def, this._formatDateTime.bind(this));
            mountDefinitionContentViewer(content, def);
            mountPortPreferenceHandlers(content);

            // Show and wire up the sync button in modal footer
            const syncBtn = document.getElementById('syncDefinitionFromDetailBtn');
            if (syncBtn) {
                syncBtn.classList.remove('d-none');
                syncBtn.dataset.definitionId = def.id;
                const newSyncBtn = syncBtn.cloneNode(true);
                syncBtn.parentNode.replaceChild(newSyncBtn, syncBtn);
                newSyncBtn.addEventListener('click', () => this._syncDefinition(def.id));
            }

            bootstrap.Modal.getOrCreateInstance(modal).show();
        } catch (error) {
            console.error('[LabletsPage] Failed to load definition:', error);
            showToast(`Failed to load definition: ${error.message}`, 'error');
        }
    }

    async _editDefinition(definitionId) {
        try {
            const def = await labletDefinitionsApi.getLabletDefinition(definitionId);
            const modal = document.getElementById('createLabletDefinitionModal');
            if (!modal) return;

            // Switch to edit mode
            const titleEl = modal.querySelector('.modal-title');
            if (titleEl) titleEl.innerHTML = '<i class="bi bi-pencil"></i> Edit Lablet Definition';

            const submitBtn = document.getElementById('submitCreateLabletDefinition');
            if (submitBtn) {
                submitBtn.innerHTML = '<i class="bi bi-check-circle"></i> Save Changes';
                submitBtn.dataset.editId = definitionId;
            }

            // Populate form fields
            this._setFormValue('defName', def.name);
            this._setFormValue('defVersion', def.version);
            this._setFormValue('defFormQualifiedName', def.form_qualified_name);
            this._setFormValue('defUserSessionPackageName', def.user_session_package_name);
            this._setFormValue('defGradingRulesetPackageName', def.grading_ruleset_package_name);
            this._setFormValue('defUserSessionType', def.user_session_type);
            this._setFormValue('defUserSessionDefaultRegion', def.user_session_default_region);

            // Trigger bucket name preview update
            const fqnInput = document.getElementById('defFormQualifiedName');
            if (fqnInput) fqnInput.dispatchEvent(new Event('input'));

            this._setFormValue('defCpuCores', def.resource_requirements?.cpu_cores);
            this._setFormValue('defMemoryGb', def.resource_requirements?.memory_gb);
            this._setFormValue('defStorageGb', def.resource_requirements?.storage_gb);
            this._setFormValue('defNodeCount', def.node_count);
            this._setFormValue('defMaxDuration', def.max_duration_minutes);
            this._setFormValue('defWarmPoolDepth', def.warm_pool_depth);
            this._setFormValue('defBootLeadTime', def.boot_lead_time_minutes);

            const nestedVirt = document.getElementById('defNestedVirt');
            if (nestedVirt) nestedVirt.checked = def.resource_requirements?.nested_virt ?? true;

            // License checkboxes
            const affinity = def.license_affinity || [];
            ['Personal', 'Enterprise', 'Evaluation'].forEach(lic => {
                const cb = document.getElementById(`defLicense${lic}`);
                if (cb) cb.checked = affinity.includes(lic.toLowerCase());
            });

            // Reset to create mode when modal closes
            modal.addEventListener(
                'hidden.bs.modal',
                () => {
                    if (titleEl) titleEl.innerHTML = '<i class="bi bi-plus-circle"></i> Create Lablet Definition';
                    if (submitBtn) {
                        submitBtn.innerHTML = '<i class="bi bi-plus-circle"></i> Create Definition';
                        delete submitBtn.dataset.editId;
                    }
                    document.getElementById('createLabletDefinitionForm')?.reset();
                },
                { once: true }
            );

            bootstrap.Modal.getOrCreateInstance(modal).show();
        } catch (error) {
            console.error('[LabletsPage] Failed to load definition for editing:', error);
            showToast(`Failed to load definition: ${error.message}`, 'error');
        }
    }

    _setFormValue(id, value) {
        const el = document.getElementById(id);
        if (el && value !== undefined && value !== null) el.value = value;
    }

    _createInstanceFromDefinition(definitionId) {
        this._openCreateModal(definitionId);
    }

    async _deleteDefinition(definitionId) {
        // Use the existing confirm modal if available
        const confirmModal = document.getElementById('confirmModal');
        if (confirmModal) {
            const body = confirmModal.querySelector('.modal-body');
            if (body) {
                body.innerHTML = `
                    <div class="alert alert-warning">
                        <i class="bi bi-exclamation-triangle me-2"></i>
                        <strong>Warning:</strong> This action cannot be undone.
                    </div>
                    <p>Are you sure you want to delete this lablet definition?</p>
                    <p class="text-muted small">Existing instances using this definition will not be affected, but no new instances can be created from it.</p>
                `;
            }

            const confirmBtn = confirmModal.querySelector('.modal-footer .btn-danger') || confirmModal.querySelector('.modal-footer .btn-primary');
            if (confirmBtn) {
                // Clone to remove previous listeners
                const newBtn = confirmBtn.cloneNode(true);
                newBtn.textContent = 'Delete';
                newBtn.className = 'btn btn-danger';
                confirmBtn.parentNode.replaceChild(newBtn, confirmBtn);

                newBtn.addEventListener(
                    'click',
                    async () => {
                        try {
                            await labletDefinitionsApi.deleteLabletDefinition(definitionId);
                            showToast('Definition deleted successfully', 'success');
                            bootstrap.Modal.getInstance(confirmModal)?.hide();
                            this._refreshDefinitions();
                        } catch (error) {
                            showToast(`Failed to delete: ${error.message}`, 'error');
                        }
                    },
                    { once: true }
                );
            }

            bootstrap.Modal.getOrCreateInstance(confirmModal).show();
        } else {
            if (!(await showConfirmAsync('Delete Definition', 'Are you sure you want to delete this definition?', { actionLabel: 'Delete', actionClass: 'btn-danger' }))) return;
            try {
                await labletDefinitionsApi.deleteLabletDefinition(definitionId);
                showToast('Definition deleted successfully', 'success');
                this._refreshDefinitions();
            } catch (error) {
                showToast(`Failed to delete: ${error.message}`, 'error');
            }
        }
    }

    // ========== Instance Actions ==========

    async _terminateInstance(instanceId) {
        if (!(await showConfirmAsync('Terminate Lablet', 'Are you sure you want to terminate this lablet?', { actionLabel: 'Terminate', actionClass: 'btn-danger' }))) return;

        try {
            await labletSessionsApi.terminateLabletSession(instanceId, 'Terminated from Lablets page');
            showToast('Lablet terminated successfully', 'success');
            await this._loadData();
        } catch (error) {
            console.error('[LabletsPage] Failed to terminate:', error);
            showToast(`Failed to terminate: ${error.message}`, 'error');
        }
    }

    async _showInstanceDetails(instanceId) {
        try {
            const inst = await labletSessionsApi.getLabletSession(instanceId);
            const modal = document.getElementById('labletSessionDetailsModal');
            const content = document.getElementById('labletSessionDetailsContent');
            if (!modal || !content) return;

            content.innerHTML = `
                <div class="row g-3">
                    <div class="col-md-6">
                        <dl class="row mb-0">
                            <dt class="col-sm-4">Definition</dt><dd class="col-sm-8">${inst.definition_name || inst.definition_id || '—'}</dd>
                            <dt class="col-sm-4">Status</dt><dd class="col-sm-8"><lcm-status-badge status="${inst.status}"></lcm-status-badge></dd>
                            <dt class="col-sm-4">Owner</dt><dd class="col-sm-8">${inst.owner_id || '—'}</dd>
                            <dt class="col-sm-4">Reservation</dt><dd class="col-sm-8">${inst.reservation_id || '—'}</dd>
                        </dl>
                    </div>
                    <div class="col-md-6">
                        <dl class="row mb-0">
                            <dt class="col-sm-4">Start</dt><dd class="col-sm-8">${this._formatDateTime(inst.timeslot_start)}</dd>
                            <dt class="col-sm-4">End</dt><dd class="col-sm-8">${this._formatDateTime(inst.timeslot_end)}</dd>
                            <dt class="col-sm-4">Worker</dt><dd class="col-sm-8">${inst.worker_id || '—'}</dd>
                            <dt class="col-sm-4">LDS Session</dt><dd class="col-sm-8">${inst.lds_session_id || '—'}</dd>
                            ${inst.lds_login_url ? `<dt class="col-sm-4">Lab URL</dt><dd class="col-sm-8"><a href="${inst.lds_login_url}" target="_blank">${inst.lds_login_url}</a></dd>` : ''}
                        </dl>
                    </div>
                </div>
                <div class="mt-3 pt-3 border-top">
                    <small class="text-muted">ID: <code>${inst.id}</code></small>
                </div>
            `;

            bootstrap.Modal.getOrCreateInstance(modal).show();
        } catch (error) {
            console.error('[LabletsPage] Failed to load instance:', error);
            showToast(`Failed to load instance details: ${error.message}`, 'error');
        }
    }

    // ========== Utilities ==========

    _updateTabContent() {
        const tabView = this.querySelector('#lablets-tabs');
        if (tabView) tabView.setActiveTab(this._activeTab);
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

    _debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => func(...args), wait);
        };
    }
}

// Register custom element
if (!customElements.get('lablets-page')) {
    customElements.define('lablets-page', LabletsPage);
}

export default LabletsPage;
