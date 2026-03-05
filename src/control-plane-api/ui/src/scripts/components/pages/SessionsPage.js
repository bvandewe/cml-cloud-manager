/**
 * SessionsPage — Consolidated Session Management Page
 *
 * Unified view replacing the old LabletsPage and SessionsPage.
 * Provides a tabbed interface following the WorkersPage pattern:
 * - Lablets: LcmDataTable of LabletSession lifecycle (create, monitor, terminate)
 * - Definitions: LcmDataTable of LabletDefinition templates (CRUD, admin-editable)
 *
 * Includes:
 * - Collapsible summary metric tiles (localStorage persisted)
 * - Multi-select with bulk operations (Terminate Selected)
 * - Session detail modal (click row → modal)
 * - Real-time SSE updates
 * - Action buttons: New Lablet, New Definition, Refresh
 *
 * AD-UI-01: Consolidation decision.
 *
 * @module components/pages/SessionsPage
 */

import { BaseComponent } from '../../core/BaseComponent.js';
import { eventBus, EventTypes } from '../../core/EventBus.js';
import * as labletSessionsApi from '../../api/lablet-sessions.js';
import * as labletDefinitionsApi from '../../api/lablet-definitions.js';
import { showToast } from '../../ui/notifications.js';
import { showConfirmAsync } from '../modals.js';
import { previewPlacement } from '../../api/scheduler.js';
import { showPlacementPreviewModal } from '../PlacementPreviewModal.js';
import * as bootstrap from 'bootstrap';
import '../core/LcmTabView.js';
import { getRelativeTime, parseUTCDate, formatDuration } from '../../utils/dates.js';
import { escapeHtml } from '../escape.js';
import '../core/LcmDataTable.js';
import '../core/LcmActionBar.js';
import '../core/LcmStatusBadge.js';
import '../core/LcmMetricCard.js';
import { renderDefinitionDetailsHtml, mountDefinitionContentViewer } from '../shared/definition-details-renderer.js';
import { populatePortDefinitions } from '../../ui/lablet-modals.js';
import '../modals/SessionDetailsModal.js';

const STORAGE_KEY_METRICS = 'lcm.sessions.metricsCollapsed';

export class SessionsPage extends BaseComponent {
    static get observedAttributes() {
        return ['active-tab'];
    }

    constructor() {
        super();
        this._currentUser = null;
        this._activeTab = 'lablets';
        this._sessions = [];
        this._definitions = [];
        this._stats = this._emptyStats();
        this._isLoading = true;
        this._metricsCollapsed = localStorage.getItem(STORAGE_KEY_METRICS) === 'true';
        this._filters = {
            status: null,
            include_terminated: false,
            search: '',
        };
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
        this.render();
        // Note: render() already calls _setupEventListeners() and _configureDataTables()
        this._setupSSESubscriptions();
        this._loadSessions();
    }

    onMount() {
        this.innerHTML = this._renderLoading();
    }

    onUnmount() {
        // Cleanup if needed
    }

    onAttributeChange(name, _oldValue, newValue) {
        if (name === 'active-tab') {
            this._activeTab = newValue;
            this._updateTabContent();
        }
    }

    _isAdminOrManager() {
        if (!this._currentUser?.roles) return false;
        const adminRoles = ['admin', 'manager', 'lcm-admin', 'lcm-manager'];
        return this._currentUser.roles.some(role => adminRoles.includes(role.toLowerCase()));
    }

    // =========================================================================
    // Data Loading
    // =========================================================================

    async _loadSessions() {
        this._isLoading = true;
        this._updateLoadingState();

        try {
            const filters = {};
            if (this._filters.status) filters.status = this._filters.status;
            if (this._filters.include_terminated) filters.include_terminated = true;

            const sessions = await labletSessionsApi.listLabletSessions(filters);
            this._sessions = Array.isArray(sessions) ? sessions : [];
            this._computeStats();
            this._updateSessionsTable();
            this._updateMetricCards();
        } catch (error) {
            console.error('[SessionsPage] Failed to load sessions:', error);
            showToast('Failed to load sessions: ' + error.message, 'error');
        } finally {
            this._isLoading = false;
            this._updateLoadingState();
        }
    }

    _computeStats() {
        const stats = this._emptyStats();
        this._sessions.forEach(s => {
            stats.total++;
            const status = (s.status || '').toLowerCase();
            if (stats.hasOwnProperty(status)) {
                stats[status]++;
            }
        });
        this._stats = stats;
    }

    _refreshDefinitions() {
        const t = this.querySelector('#sessions-definitions-table');
        if (t) t.loadData();
    }

    // =========================================================================
    // SSE Subscriptions
    // =========================================================================

    _setupSSESubscriptions() {
        this.subscribe(EventTypes.LABLET_SESSION_CREATED, () => this._loadSessions());
        this.subscribe(EventTypes.LABLET_SESSION_STATUS_CHANGED, () => this._loadSessions());
        this.subscribe(EventTypes.LABLET_SESSION_TERMINATED, () => this._loadSessions());
        this.subscribe(EventTypes.LABLET_SESSIONS_REFRESH_COMPLETED, () => this._loadSessions());

        // Refresh definitions table on definition CRUD events
        this.subscribe(EventTypes.LABLET_DEFINITION_CREATED, () => this._refreshDefinitions());
        this.subscribe(EventTypes.LABLET_DEFINITION_UPDATED, () => this._refreshDefinitions());
        this.subscribe(EventTypes.LABLET_DEFINITION_DELETED, () => this._refreshDefinitions());
        this.subscribe(EventTypes.LABLET_DEFINITION_ACTIVATED, () => this._refreshDefinitions());
        this.subscribe(EventTypes.LABLET_DEFINITION_CONTENT_SYNCED, () => this._refreshDefinitions());
        this.subscribe(EventTypes.LABLET_DEFINITION_DEPRECATED, () => this._refreshDefinitions());
        this.subscribe(EventTypes.LABLET_DEFINITION_SYNC_REQUESTED, () => this._refreshDefinitions());
    }

    // =========================================================================
    // Rendering
    // =========================================================================

    _renderLoading() {
        return `
            <div class="d-flex justify-content-center align-items-center" style="min-height: 200px;">
                <div class="spinner-border text-primary" role="status">
                    <span class="visually-hidden">Loading...</span>
                </div>
            </div>
        `;
    }

    render() {
        const activeCount = this._sessions.filter(s => {
            const st = (s.status || '').toLowerCase();
            return st !== 'terminated' && st !== 'terminating';
        }).length;

        this.innerHTML = `
            <div class="sessions-page">
                <!-- Page Header with Action Bar -->
                <div class="page-header d-flex justify-content-between align-items-center mb-4">
                    <div>
                        <h2 class="mb-1"><i class="bi bi-easel me-2"></i>Sessions</h2>
                        <p class="text-muted mb-0">Manage lab sessions, reservations, and definitions</p>
                    </div>
                    <lcm-action-bar id="sessions-action-bar">
                        <lcm-action-bar-primary>
                            <button class="btn btn-primary" data-action="create-session">
                                <i class="bi bi-plus-circle me-1"></i>New Lablet
                            </button>
                            <button class="btn btn-outline-primary" data-action="create-definition">
                                <i class="bi bi-file-earmark-plus me-1"></i>New Definition
                            </button>
                        </lcm-action-bar-primary>
                        <lcm-action-bar-secondary>
                            <button class="btn btn-outline-secondary" data-action="refresh">
                                <i class="bi bi-arrow-clockwise me-1"></i>Refresh
                            </button>
                        </lcm-action-bar-secondary>
                    </lcm-action-bar>
                </div>

                <!-- Collapsible Summary Metrics -->
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
                                <lcm-metric-card id="metric-total" title="Total" value="${this._stats.total}"
                                    icon="bi-calendar-check" color="primary"
                                    ${this._isLoading ? 'loading' : ''}></lcm-metric-card>
                            </div>
                            <div class="col-6 col-lg-2" data-bs-toggle="tooltip" data-bs-placement="bottom"
                                 title="pending / scheduled / assigned">
                                <lcm-metric-card id="metric-pending" title="Pending" value="${this._stats.pending + this._stats.scheduled + this._stats.worker_assigned}"
                                    icon="bi-hourglass-split" color="warning"
                                    ${this._isLoading ? 'loading' : ''}></lcm-metric-card>
                            </div>
                            <div class="col-6 col-lg-2">
                                <lcm-metric-card id="metric-provisioning" title="Provisioning" value="${this._stats.instantiating + this._stats.provisioning}"
                                    icon="bi-gear-wide-connected" color="info"
                                    ${this._isLoading ? 'loading' : ''}></lcm-metric-card>
                            </div>
                            <div class="col-6 col-lg-2">
                                <lcm-metric-card id="metric-ready" title="Ready" value="${this._stats.ready}"
                                    icon="bi-check-circle" color="success"
                                    ${this._isLoading ? 'loading' : ''}></lcm-metric-card>
                            </div>
                            <div class="col-6 col-lg-2">
                                <lcm-metric-card id="metric-running" title="Running" value="${this._stats.running}"
                                    icon="bi-play-circle" color="success"
                                    ${this._isLoading ? 'loading' : ''}></lcm-metric-card>
                            </div>
                            <div class="col-6 col-lg-2">
                                <lcm-metric-card id="metric-terminated" title="Terminated" value="${this._stats.terminated}"
                                    icon="bi-x-circle" color="secondary"
                                    ${this._isLoading ? 'loading' : ''}></lcm-metric-card>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Sub-tabs -->
                <lcm-tab-view id="sessions-tabs" variant="underline" persist-key="sessions-tab">
                    <lcm-tab id="lablets" label="Lablets (${activeCount})" icon="bi-collection" ${this._activeTab === 'lablets' ? 'active' : ''}></lcm-tab>
                    <lcm-tab id="definitions" label="Definitions" icon="bi-file-earmark-code" ${this._activeTab === 'definitions' ? 'active' : ''}></lcm-tab>
                </lcm-tab-view>

                <!-- Tab Content -->
                <div class="tab-content mt-4">
                    <div id="sessions-lablets-content" class="tab-pane ${this._activeTab === 'lablets' ? 'active' : ''}"
                         ${this._activeTab !== 'lablets' ? 'style="display: none;"' : ''}>
                        ${this._renderLabletsTab()}
                    </div>
                    <div id="sessions-definitions-content" class="tab-pane ${this._activeTab === 'definitions' ? 'active' : ''}"
                         ${this._activeTab !== 'definitions' ? 'style="display: none;"' : ''}>
                        ${this._renderDefinitionsTab()}
                    </div>
                </div>

                <!-- Session Details Modal (Phase 3) -->
                <session-details-modal></session-details-modal>
            </div>
        `;

        this._registerTabContent();
        this._setupEventListeners();
        this._configureDataTables();
        this._initTooltips();
    }

    // =========================================================================
    // Tab Renderers
    // =========================================================================

    _renderLabletsTab() {
        return `
            <div class="card shadow-sm no-hover-lift">
                <div class="card-header d-flex align-items-center bg-white py-2 gap-2">
                    <span class="fw-medium text-muted small">Lablet Sessions</span>
                    <div class="d-flex align-items-center gap-2 ms-auto">
                        <div class="input-group input-group-sm" style="width: 250px;">
                            <span class="input-group-text bg-white"><i class="bi bi-search"></i></span>
                            <input type="text" class="form-control" id="lablets-search-input"
                                placeholder="Search sessions..." value="${this._filters.search || ''}">
                        </div>
                        <select class="form-select form-select-sm" id="lablets-status-filter" style="width: 160px;">
                            <option value="">All Statuses</option>
                            <option value="pending" ${this._filters.status === 'pending' ? 'selected' : ''}>Pending</option>
                            <option value="scheduled" ${this._filters.status === 'scheduled' ? 'selected' : ''}>Scheduled</option>
                            <option value="worker_assigned" ${this._filters.status === 'worker_assigned' ? 'selected' : ''}>Worker Assigned</option>
                            <option value="instantiating" ${this._filters.status === 'instantiating' ? 'selected' : ''}>Instantiating</option>
                            <option value="provisioning" ${this._filters.status === 'provisioning' ? 'selected' : ''}>Provisioning</option>
                            <option value="ready" ${this._filters.status === 'ready' ? 'selected' : ''}>Ready</option>
                            <option value="running" ${this._filters.status === 'running' ? 'selected' : ''}>Running</option>
                            <option value="collecting" ${this._filters.status === 'collecting' ? 'selected' : ''}>Collecting</option>
                            <option value="grading" ${this._filters.status === 'grading' ? 'selected' : ''}>Grading</option>
                            <option value="terminated" ${this._filters.status === 'terminated' ? 'selected' : ''}>Terminated</option>
                        </select>
                        <div class="form-check form-switch ms-1" style="white-space: nowrap;">
                            <input class="form-check-input" type="checkbox" id="lablets-terminal-toggle"
                                ${this._filters.include_terminated ? 'checked' : ''}>
                            <label class="form-check-label small" for="lablets-terminal-toggle">Incl. Terminated</label>
                        </div>
                        <button class="btn btn-sm btn-outline-secondary" id="lablets-clear-filters" title="Clear all filters">
                            <i class="bi bi-x-lg"></i>
                        </button>
                    </div>
                </div>
                <div class="card-body p-0">
                    <lcm-data-table id="sessions-lablets-table"
                        page-size="25"
                        selectable
                        no-toolbar
                        panel-mode
                        empty-message="No lablet sessions found. Create your first lablet to get started."
                        ${this._isLoading ? 'loading' : ''}>
                    </lcm-data-table>
                </div>
            </div>
        `;
    }

    _renderDefinitionsTab() {
        return `
            <div class="card shadow-sm no-hover-lift">
                <div class="card-header d-flex justify-content-between align-items-center bg-white py-2">
                    <span class="fw-medium text-muted small">All Definitions</span>
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
                        id="sessions-definitions-table"
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

    // =========================================================================
    // Tab Management
    // =========================================================================

    _registerTabContent() {
        const tabView = this.querySelector('#sessions-tabs');
        if (!tabView) return;

        const contents = {
            lablets: this.querySelector('#sessions-lablets-content'),
            definitions: this.querySelector('#sessions-definitions-content'),
        };

        Object.entries(contents).forEach(([id, el]) => {
            if (el) tabView.registerContent(id, el);
        });
    }

    _updateTabContent() {
        const tabView = this.querySelector('#sessions-tabs');
        if (tabView) tabView.setActiveTab(this._activeTab);
    }

    _onTabChange({ tabId }) {
        console.log(`[SessionsPage] Tab changed → ${tabId}`);
        this._activeTab = tabId;

        if (tabId === 'definitions') {
            this._refreshDefinitions();
        }
    }

    // =========================================================================
    // Data Table Configuration
    // =========================================================================

    _configureDataTables() {
        this._configureLabletSessionsTable();
        this._configureDefinitionsTable();
    }

    _configureLabletSessionsTable() {
        const table = this.querySelector('#sessions-lablets-table');
        if (!table) return;

        table.setColumns([
            // 1. Definition — name + FQN subtitle
            {
                field: 'definition_name',
                label: 'Definition',
                sortable: true,
                width: '200px',
                render: (value, row) => {
                    const fqn = row.form_qualified_name;
                    const fqnHtml = fqn
                        ? `<div class="small text-muted text-truncate" style="max-width: 180px;"
                                data-bs-toggle="tooltip" title="${escapeHtml(fqn)}">
                               ${escapeHtml(fqn)}
                           </div>`
                        : '';
                    return `<span class="d-flex flex-column">
                        <span class="d-flex align-items-center gap-1">
                            <i class="bi bi-easel text-muted"></i>
                            <strong class="session-title-link" role="button" data-session-id="${row.id}">
                                ${escapeHtml(value || row.definition_id || 'Unknown')}
                            </strong>
                        </span>
                        ${fqnHtml}
                    </span>`;
                },
            },
            // 2. Candidate — unchanged
            {
                field: 'owner_id',
                label: 'Candidate',
                sortable: true,
                width: '130px',
                render: value => `<span><i class="bi bi-person me-1"></i>${escapeHtml(value || 'Unknown')}</span>`,
            },
            // 3. Status — unchanged
            {
                field: 'status',
                label: 'Status',
                sortable: true,
                width: '100px',
                render: value => `<lcm-status-badge status="${value || 'unknown'}" icon pill></lcm-status-badge>`,
            },
            // 4. Worker — clickable cross-ref → WorkerDetailsModal
            {
                field: 'worker_name',
                label: 'Worker',
                sortable: true,
                width: '120px',
                render: (value, row) => {
                    if (!row.worker_id) return '<span class="text-muted">—</span>';
                    const displayName = value || row.worker_id.substring(0, 8) + '…';
                    return `
                        <a href="#" class="text-decoration-none open-worker-link"
                           data-worker-id="${row.worker_id}"
                           title="Open Worker ${escapeHtml(row.worker_id)}">
                            <i class="bi bi-hdd-rack me-1" style="font-size: 0.75em;"></i>
                            <code class="small">${escapeHtml(displayName)}</code>
                            <i class="bi bi-box-arrow-up-right" style="font-size: 0.6em;"></i>
                        </a>
                    `;
                },
            },
            // 5. Topology — nodes / links notation
            {
                field: 'node_count',
                label: 'Topology',
                sortable: true,
                width: '80px',
                render: (value, row) => {
                    const nodes = value ?? '—';
                    const links = row.link_count ?? '?';
                    if (nodes === '—') return '<span class="text-muted">—</span>';
                    return `
                        <span title="Nodes / Links" class="small">
                            <i class="bi bi-diagram-3 me-1 text-muted" style="font-size: 0.75em;"></i>
                            <strong>${nodes}</strong>N / <strong>${links}</strong>L
                        </span>
                    `;
                },
            },
            // 6. Timeslot — unified relative time with color coding + duration
            {
                field: 'timeslot_start',
                label: 'Timeslot',
                sortable: true,
                width: '150px',
                render: (value, row) => {
                    const start = value ? parseUTCDate(value) : null;
                    const end = row.timeslot_end ? parseUTCDate(row.timeslot_end) : null;
                    const now = new Date();

                    if (!start) return '<span class="text-muted">—</span>';

                    // Determine temporal context
                    let colorClass = 'text-muted'; // past
                    let icon = 'bi-clock-history';
                    if (end && end > now && start <= now) {
                        colorClass = 'text-success'; // current/active
                        icon = 'bi-clock-fill';
                    } else if (start > now) {
                        colorClass = 'text-primary'; // future
                        icon = 'bi-clock';
                    } else if (end && end < now) {
                        const minutesSinceEnd = (now - end) / 60000;
                        if (minutesSinceEnd < 30) {
                            colorClass = 'text-warning'; // recently ended
                            icon = 'bi-clock-history';
                        }
                    }

                    const relativeTime = getRelativeTime(value);
                    const duration = start && end ? formatDuration(end - start) : '';
                    const fullStart = this._formatDateTime(value);
                    const fullEnd = row.timeslot_end ? this._formatDateTime(row.timeslot_end) : '—';

                    return `
                        <span class="${colorClass}"
                              data-bs-toggle="tooltip" data-bs-placement="top"
                              data-bs-html="true"
                              title="${fullStart} → ${fullEnd}<br>Duration: ${duration || '—'}">
                            <i class="bi ${icon} me-1" style="font-size: 0.75em;"></i>
                            <span class="small">${relativeTime}</span>
                            ${duration ? `<span class="text-muted small ms-1">(${duration})</span>` : ''}
                        </span>
                    `;
                },
            },
            // 7. Form — truncated FQN with tooltip
            {
                field: 'form_qualified_name',
                label: 'Form',
                sortable: true,
                width: '160px',
                render: value => {
                    if (!value) return '<span class="text-muted">—</span>';
                    const parts = value.split(' ');
                    const short = parts.length > 3 ? '…' + parts.slice(-3).join(' ') : value;
                    return `
                        <span class="small text-truncate d-inline-block" style="max-width: 150px;"
                              data-bs-toggle="tooltip" data-bs-placement="top"
                              title="${escapeHtml(value)}">
                            ${escapeHtml(short)}
                        </span>
                    `;
                },
            },
            // 8. Pipeline — 5 dot-indicators (Upstream, Storage, POD, LDS, Score)
            {
                field: 'pipeline',
                label: 'Pipeline',
                width: '120px',
                render: (_, row) => {
                    const dot = (label, status, detail) => {
                        const colors = {
                            green: '#28a745',
                            amber: '#ffc107',
                            red: '#dc3545',
                            gray: '#adb5bd',
                        };
                        const color = colors[status] || colors.gray;
                        return `<span class="d-inline-block rounded-circle me-1"
                                      style="width: 10px; height: 10px; background: ${color};"
                                      data-bs-toggle="tooltip" data-bs-placement="top"
                                      data-bs-html="true"
                                      title="<strong>${label}</strong><br>${detail}">
                                </span>`;
                    };

                    const dots = [];

                    // 1. Upstream Source
                    const uSync = row.upstream_sync_status?.mosaic_source;
                    const uStatus = uSync?.status === 'synced' ? 'green' : uSync?.status === 'error' ? 'red' : uSync?.status ? 'amber' : 'gray';
                    const uVersion = uSync?.version ? `v${uSync.version}` : '—';
                    dots.push(dot('Upstream', uStatus, `${uSync?.status || 'unknown'} • ${uVersion}`));

                    // 2. Object Storage
                    const oSync = row.upstream_sync_status?.object_storage;
                    const oStatus = oSync?.status === 'synced' ? 'green' : oSync?.status === 'error' ? 'red' : oSync?.status ? 'amber' : 'gray';
                    dots.push(dot('Storage', oStatus, `${oSync?.status || 'unknown'}`));

                    // 3. POD (LabRecord)
                    const podStatus = row.lab_record_id ? 'green' : 'gray';
                    const podDetail = row.lab_record_id ? `${row.lab_record_id.substring(0, 8)}…` : 'No lab record';
                    dots.push(dot('POD', podStatus, podDetail));

                    // 4. LDS (UserSession)
                    const ldsStatus = row.user_session_id ? 'green' : 'gray';
                    const ldsDetail = row.user_session_id ? `${row.user_session_id.substring(0, 8)}…` : 'No user session';
                    dots.push(dot('LDS', ldsStatus, ldsDetail));

                    // 5. Score
                    const scoreStatus = row.grade_result === 'pass' ? 'green' : row.grade_result === 'fail' ? 'red' : 'gray';
                    const scoreDetail = row.grade_result || 'Not graded';
                    dots.push(dot('Score', scoreStatus, scoreDetail));

                    return `<span class="d-inline-flex align-items-center">${dots.join('')}</span>`;
                },
            },
            // 9. Actions — Observe / Sync / Terminate
            {
                field: 'actions',
                label: 'Actions',
                width: '100px',
                render: (_, row) => {
                    const st = (row.status || '').toLowerCase();
                    const isTerminal = st === 'terminated' || st === 'archived';
                    if (isTerminal) return '<span class="text-muted">—</span>';

                    // Observe button — only for RUNNING sessions (ADR-030 UX)
                    const observeBtn =
                        st === 'running'
                            ? `<button class="btn btn-outline-info btn-sm" data-action="observe-resources" data-id="${row.id}" title="Observe live CML resources">
                               <i class="bi bi-binoculars"></i>
                           </button>`
                            : '';

                    return `
                        <div class="btn-group btn-group-sm">
                            ${observeBtn}
                            <button class="btn btn-outline-primary btn-sm" data-action="requeue" data-id="${row.id}" title="Re-queue (sync)">
                                <i class="bi bi-arrow-repeat"></i>
                            </button>
                            <button class="btn btn-outline-danger btn-sm" data-action="terminate" data-id="${row.id}" title="Terminate">
                                <i class="bi bi-x-circle"></i>
                            </button>
                        </div>
                    `;
                },
            },
        ]);

        table.setBulkActions([
            { id: 'requeue', label: 'Sync Selected', icon: 'bi-arrow-repeat', variant: 'primary' },
            { id: 'terminate', label: 'Terminate Selected', icon: 'bi-x-circle', variant: 'danger' },
        ]);

        // Bulk action handler
        table.addEventListener('bulk-action', e => {
            const { actionId, selectedRows } = e.detail;
            if (actionId === 'terminate') {
                this._bulkTerminate(selectedRows);
            } else if (actionId === 'requeue') {
                this._bulkRequeue(selectedRows);
            }
        });

        // Row click → open detail modal
        table.addEventListener('row-click', e => {
            const { row } = e.detail;
            if (row?.id) {
                this._showSessionDetailModal(row.id);
            }
        });
    }

    _configureDefinitionsTable() {
        const table = this.querySelector('#sessions-definitions-table');
        if (!table) return;

        const isAdmin = this._isAdminOrManager();

        table.setColumns([
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
                render: (_, row) => {
                    const adminActions = isAdmin
                        ? `<button class="btn btn-outline-secondary btn-sm" data-action="edit" data-id="${row.id}" title="Edit">
                                <i class="bi bi-pencil"></i>
                            </button>
                            <button class="btn btn-outline-info btn-sm" data-action="sync" data-id="${row.id}" title="Sync content">
                                <i class="bi bi-arrow-repeat"></i>
                            </button>
                            <button class="btn btn-outline-danger btn-sm" data-action="delete" data-id="${row.id}" title="Delete">
                                <i class="bi bi-trash"></i>
                            </button>`
                        : '';
                    return `
                        <div class="btn-group btn-group-sm">
                            <button class="btn btn-outline-primary btn-sm" data-action="view-definition" data-id="${row.id}" title="View details">
                                <i class="bi bi-eye"></i>
                            </button>
                            <button class="btn btn-outline-success btn-sm" data-action="deploy" data-id="${row.id}" title="Create session from this definition">
                                <i class="bi bi-rocket"></i>
                            </button>
                            ${adminActions}
                        </div>
                    `;
                },
            },
        ]);

        if (isAdmin) {
            table.setBulkActions([
                { id: 'activate', label: 'Activate Selected', icon: 'bi-check-circle', variant: 'success' },
                { id: 'archive', label: 'Archive Selected', icon: 'bi-archive', variant: 'secondary' },
                { id: 'delete', label: 'Delete Selected', icon: 'bi-trash', variant: 'danger' },
            ]);
        }

        // Row click navigates to view
        table.addEventListener('row-click', e => {
            const row = e.detail?.row;
            if (row?.id) this._viewDefinition(row.id);
        });
    }

    _updateSessionsTable() {
        const table = this.querySelector('#sessions-lablets-table');
        if (!table) return;

        let data = [...this._sessions];

        // Client-side search
        if (this._filters.search) {
            const term = this._filters.search.toLowerCase();
            data = data.filter(
                s =>
                    (s.definition_name || '').toLowerCase().includes(term) ||
                    (s.owner_id || '').toLowerCase().includes(term) ||
                    (s.worker_name || '').toLowerCase().includes(term) ||
                    (s.status || '').toLowerCase().includes(term) ||
                    (s.id || '').toLowerCase().includes(term)
            );
        }

        table.setData(data);
    }

    _updateLoadingState() {
        const table = this.querySelector('#sessions-lablets-table');
        if (table) {
            if (this._isLoading) {
                table.setAttribute('loading', '');
            } else {
                table.removeAttribute('loading');
            }
        }
    }

    _updateMetricCards() {
        const s = this._stats;
        this._setMetricValue('metric-total', s.total);
        this._setMetricValue('metric-pending', s.pending + s.scheduled + s.worker_assigned);
        this._setMetricValue('metric-provisioning', s.instantiating + s.provisioning);
        this._setMetricValue('metric-ready', s.ready);
        this._setMetricValue('metric-running', s.running);
        this._setMetricValue('metric-terminated', s.terminated);

        // Remove loading state from all metric cards so values render
        this.querySelectorAll('lcm-metric-card[loading]').forEach(card => card.removeAttribute('loading'));
    }

    _setMetricValue(id, value) {
        const card = this.querySelector(`#${id}`);
        if (card) card.setAttribute('value', String(value));
    }

    // =========================================================================
    // Event Listeners
    // =========================================================================

    _setupEventListeners() {
        // Metrics toggle
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
        const tabView = this.querySelector('#sessions-tabs');
        if (tabView) {
            tabView.addEventListener('tab-change', e => {
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
                case 'create-session':
                    this._openCreateSessionModal();
                    break;
                case 'create-definition':
                    this._openCreateDefinitionModal();
                    break;
                case 'refresh':
                    this._handleRefresh();
                    break;
                case 'terminate':
                    if (id) this._terminateSession(id);
                    break;
                case 'requeue':
                    if (id) this._requeueSession(id);
                    break;
                case 'observe-resources':
                    if (id) this._observeResources(id);
                    break;
                case 'view-definition':
                    if (id) this._viewDefinition(id);
                    break;
                case 'edit':
                    if (id) this._editDefinition(id);
                    break;
                case 'deploy':
                    if (id) this._openCreateSessionModal(id);
                    break;
                case 'delete':
                    if (id) this._deleteDefinition(id);
                    break;
                case 'sync':
                    if (id) this._syncDefinition(id);
                    break;
            }
        });

        // Session title link click → open detail modal
        this.addEventListener('click', e => {
            const titleLink = e.target.closest('.session-title-link[data-session-id]');
            if (titleLink) {
                e.stopPropagation();
                this._showSessionDetailModal(titleLink.dataset.sessionId);
            }
        });

        // Worker cross-ref clicks → open WorkerDetailsModal
        this.addEventListener('click', e => {
            const workerLink = e.target.closest('.open-worker-link');
            if (workerLink) {
                e.preventDefault();
                e.stopPropagation();
                eventBus.emit('UI_OPEN_WORKER_DETAILS', {
                    workerId: workerLink.dataset.workerId,
                    region: workerLink.dataset.workerRegion || '',
                });
            }
        });

        // Lablets tab: search (debounced)
        const searchInput = this.querySelector('#lablets-search-input');
        let searchTimeout;
        searchInput?.addEventListener('input', e => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                this._filters.search = e.target.value;
                this._updateSessionsTable();
            }, 300);
        });

        // Lablets tab: status filter
        this.querySelector('#lablets-status-filter')?.addEventListener('change', e => {
            this._filters.status = e.target.value || null;
            this._loadSessions();
        });

        // Lablets tab: terminal toggle
        this.querySelector('#lablets-terminal-toggle')?.addEventListener('change', e => {
            this._filters.include_terminated = e.target.checked;
            this._loadSessions();
        });

        // Lablets tab: clear filters
        this.querySelector('#lablets-clear-filters')?.addEventListener('click', () => {
            this._clearFilters();
        });

        // Definitions tab: status filter
        const defStatusFilter = this.querySelector('#definition-table-status-filter');
        if (defStatusFilter) {
            defStatusFilter.addEventListener('change', e => this._filterDefinitionsByStatus(e.target.value));
        }

        // Definitions tab: search
        const defSearchInput = this.querySelector('#definition-table-search');
        if (defSearchInput) {
            let defSearchTimeout;
            defSearchInput.addEventListener('input', e => {
                clearTimeout(defSearchTimeout);
                defSearchTimeout = setTimeout(() => this._searchDefinitions(e.target.value), 300);
            });
        }
    }

    // =========================================================================
    // Filters
    // =========================================================================

    _clearFilters() {
        this._filters = { status: null, include_terminated: false, search: '' };
        const statusFilter = this.querySelector('#lablets-status-filter');
        const searchInput = this.querySelector('#lablets-search-input');
        const terminalToggle = this.querySelector('#lablets-terminal-toggle');
        if (statusFilter) statusFilter.value = '';
        if (searchInput) searchInput.value = '';
        if (terminalToggle) terminalToggle.checked = false;
        this._loadSessions();
    }

    _filterDefinitionsByStatus(status) {
        const t = this.querySelector('#sessions-definitions-table');
        if (t) t.setFilter('status', status);
    }

    _searchDefinitions(term) {
        const t = this.querySelector('#sessions-definitions-table');
        if (t) t.setSearch(term);
    }

    _handleRefresh() {
        if (this._activeTab === 'definitions') {
            this._refreshDefinitions();
        } else {
            this._loadSessions();
        }
    }

    // =========================================================================
    // Session Detail Modal
    // =========================================================================

    _showSessionDetailModal(sessionId) {
        eventBus.emit('UI_OPEN_SESSION_DETAILS', { sessionId });
    }

    // =========================================================================
    // Session Actions
    // =========================================================================

    async _requeueSession(sessionId) {
        try {
            await labletSessionsApi.requeueLabletSession(sessionId, 'Manual sync from Sessions page');
            showToast('Session re-queued for reconciliation', 'success');
            await this._loadSessions();
        } catch (error) {
            console.error('[SessionsPage] Failed to requeue session:', error);
            showToast(`Failed to sync session: ${error.message}`, 'error');
        }
    }

    /**
     * Request resource observation for a RUNNING session (ADR-030 UX).
     * Calls the existing API, shows spinner feedback on button, then toast.
     */
    async _observeResources(sessionId) {
        const btn = this.querySelector(`[data-action="observe-resources"][data-id="${sessionId}"]`);

        try {
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
            }

            await labletSessionsApi.requestResourceObservation(sessionId);
            showToast('Resource observation requested — results will appear shortly.', 'info');
        } catch (error) {
            console.error('[SessionsPage] Observe resources failed:', error);
            showToast(`Observation failed: ${error.message}`, 'error');
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="bi bi-binoculars"></i>';
            }
        }
    }

    async _bulkRequeue(selectedRows) {
        if (!selectedRows || selectedRows.length === 0) return;

        const requeueable = selectedRows.filter(r => {
            const st = (r.status || '').toLowerCase();
            return st !== 'terminated' && st !== 'archived';
        });

        if (requeueable.length === 0) {
            showToast('No sessions eligible for sync.', 'warning');
            return;
        }

        if (!(await showConfirmAsync('Re-queue Sessions', `Re-queue ${requeueable.length} selected session(s) for reconciliation?`, { actionLabel: 'Re-queue', actionClass: 'btn-warning' }))) return;

        try {
            const ids = requeueable.map(r => r.id);
            const result = await labletSessionsApi.bulkRequeueLabletSessions(ids, 'Bulk sync from Sessions page');
            const successCount = result?.results?.filter(r => r.success)?.length ?? requeueable.length;
            const failCount = result?.results?.filter(r => !r.success)?.length ?? 0;

            if (successCount > 0) {
                showToast(`${successCount} session(s) re-queued successfully.`, 'success');
            }
            if (failCount > 0) {
                showToast(`${failCount} session(s) failed to re-queue.`, 'error');
            }
        } catch (error) {
            console.error('[SessionsPage] Bulk requeue failed:', error);
            showToast(`Bulk sync failed: ${error.message}`, 'error');
        }

        await this._loadSessions();
    }

    async _terminateSession(sessionId) {
        if (!(await showConfirmAsync('Terminate Session', 'Are you sure you want to terminate this lablet session?', { actionLabel: 'Terminate', actionClass: 'btn-danger' }))) return;

        try {
            await labletSessionsApi.terminateLabletSession(sessionId, 'Terminated from Sessions page');
            showToast('Session terminated successfully', 'success');
            await this._loadSessions();
        } catch (error) {
            console.error('[SessionsPage] Failed to terminate session:', error);
            showToast(`Failed to terminate: ${error.message}`, 'error');
        }
    }

    async _bulkTerminate(selectedRows) {
        if (!selectedRows || selectedRows.length === 0) return;

        const terminableRows = selectedRows.filter(r => {
            const st = (r.status || '').toLowerCase();
            return st !== 'terminated' && st !== 'terminating';
        });

        if (terminableRows.length === 0) {
            showToast('No sessions eligible for termination.', 'warning');
            return;
        }

        if (!(await showConfirmAsync('Bulk Terminate', `Terminate ${terminableRows.length} selected session(s)?`, { actionLabel: 'Terminate All', actionClass: 'btn-danger' }))) return;

        let successCount = 0;
        let failCount = 0;

        for (const row of terminableRows) {
            try {
                await labletSessionsApi.terminateLabletSession(row.id, 'Bulk terminated from Sessions page');
                successCount++;
            } catch (error) {
                console.error(`[SessionsPage] Failed to terminate session ${row.id}:`, error);
                failCount++;
            }
        }

        if (successCount > 0) {
            showToast(`${successCount} session(s) terminated successfully.`, 'success');
        }
        if (failCount > 0) {
            showToast(`${failCount} session(s) failed to terminate.`, 'error');
        }

        await this._loadSessions();
    }

    // =========================================================================
    // Modal Actions (Create Session, Create/Edit Definition, Delete Definition)
    // =========================================================================

    _openCreateSessionModal(preselectedDefinitionId = null) {
        const modal = document.getElementById('createLabletSessionModal');
        if (!modal) {
            console.warn('[SessionsPage] createLabletSessionModal not found');
            return;
        }

        // Populate definitions dropdown before showing
        this._populateDefinitionDropdown(preselectedDefinitionId);

        // Set default start time to now + 2 minutes
        const startInput = document.getElementById('instanceTimeslotStart');
        if (startInput) {
            const defaultStart = new Date(Date.now() + 2 * 60 * 1000);
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
            console.error('[SessionsPage] Failed to load definitions for dropdown:', error);
            select.innerHTML = '<option value="">Failed to load definitions</option>';
        }
    }

    _openCreateDefinitionModal() {
        const modal = document.getElementById('createLabletDefinitionModal');
        if (!modal) return;
        bootstrap.Modal.getOrCreateInstance(modal).show();
    }

    // =========================================================================
    // Definition CRUD Actions
    // =========================================================================

    async _syncDefinition(definitionId) {
        try {
            await labletDefinitionsApi.syncLabletDefinition(definitionId);
            showToast('Sync requested — content will be synchronized shortly.', 'success');
            this._refreshDefinitions();
        } catch (error) {
            console.error('[SessionsPage] Failed to sync definition:', error);
            showToast(`Sync failed: ${error.message}`, 'error');
        }
    }

    async _viewDefinition(definitionId) {
        try {
            const def = await labletDefinitionsApi.getLabletDefinition(definitionId);
            const modal = document.getElementById('labletDefinitionDetailsModal');
            const content = document.getElementById('labletDefinitionDetailsContent');
            if (!modal || !content) return;

            content.innerHTML = renderDefinitionDetailsHtml(def, this._formatDateTime.bind(this));
            mountDefinitionContentViewer(content, def);

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
            console.error('[SessionsPage] Failed to load definition:', error);
            showToast(`Failed to load definition: ${error.message}`, 'error');
        }
    }

    async _editDefinition(definitionId) {
        if (!this._isAdminOrManager()) {
            showToast('Only administrators can edit definitions.', 'warning');
            return;
        }

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

            const nestedVirt = document.getElementById('defNestedVirt');
            if (nestedVirt) nestedVirt.checked = def.resource_requirements?.nested_virt ?? true;

            const affinity = def.license_affinity || [];
            ['Personal', 'Enterprise', 'Evaluation'].forEach(lic => {
                const cb = document.getElementById(`defLicense${lic}`);
                if (cb) cb.checked = affinity.includes(lic.toLowerCase());
            });

            // Auto-expand resource toggle if definition has non-default resources (Phase 1 — ADR-030 UX)
            const hasNonDefaultResources =
                (def.resource_requirements?.cpu_cores && def.resource_requirements.cpu_cores !== 2) ||
                (def.resource_requirements?.memory_gb && def.resource_requirements.memory_gb !== 4) ||
                (def.resource_requirements?.storage_gb && def.resource_requirements.storage_gb !== 20) ||
                (def.node_count && def.node_count !== 1) ||
                def.resource_requirements?.nested_virt === false;

            // Populate port definitions for edit mode (Phase 3 — ADR-030 UX)
            const ports = def.port_template?.ports || def.port_definitions || [];
            populatePortDefinitions(ports);

            const hasNonDefaultResourcesOrPorts = hasNonDefaultResources || ports.length > 0;

            const resourceToggle = document.getElementById('defResourceToggle');
            const collapseEl = document.getElementById('resourceRequirementsCollapse');
            const defaultsHint = document.getElementById('resourceDefaultsHint');

            if (hasNonDefaultResourcesOrPorts && resourceToggle && collapseEl) {
                resourceToggle.checked = true;
                const bsCollapse = bootstrap.Collapse.getOrCreateInstance(collapseEl);
                bsCollapse.show();
                if (defaultsHint) defaultsHint.style.display = 'none';
            }

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
            console.error('[SessionsPage] Failed to load definition for editing:', error);
            showToast(`Failed to load definition: ${error.message}`, 'error');
        }
    }

    async _deleteDefinition(definitionId) {
        if (!this._isAdminOrManager()) {
            showToast('Only administrators can delete definitions.', 'warning');
            return;
        }

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
                    <p class="text-muted small">Existing sessions using this definition will not be affected, but no new sessions can be created from it.</p>
                `;
            }

            const confirmBtn = confirmModal.querySelector('.modal-footer .btn-danger') || confirmModal.querySelector('.modal-footer .btn-primary');
            if (confirmBtn) {
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

    // =========================================================================
    // Utilities
    // =========================================================================

    _setFormValue(id, value) {
        const el = document.getElementById(id);
        if (el && value !== undefined && value !== null) el.value = value;
    }

    _initTooltips() {
        this.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => {
            bootstrap.Tooltip.getOrCreateInstance(el);
        });
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
}

// Register custom element
if (!customElements.get('sessions-page')) {
    customElements.define('sessions-page', SessionsPage);
}

export default SessionsPage;
