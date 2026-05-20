/**
 * SessionDetailsModal Component
 *
 * Full-featured modal with horizontal tabs: Overview, Pipeline, Reports, Resources
 * Displays lablet session details with lazy-loaded tab content and SSE reactivity.
 *
 * Usage:
 *   <session-details-modal></session-details-modal>
 *
 * Open via EventBus:
 *   eventBus.emit('UI_OPEN_SESSION_DETAILS', { sessionId: 'abc123' });
 *
 * Phase 3: Structural shell with 4-tab navigation, SSE reactivity, footer actions.
 * Phase 4: Rich Overview tab with Identity/Assignment, Timeslot, Lifecycle Timeline, Grade Result.
 * Pipeline, Reports, Resources tabs are placeholder stubs for Phases 5–7.
 */

import { BaseComponent } from '../../core/BaseComponent.js';
import { eventBus, EventTypes } from '../../core/EventBus.js';
import * as bootstrap from 'bootstrap';
import * as labletSessionsApi from '../../api/lablet-sessions.js';
import * as labletDefinitionsApi from '../../api/lablet-definitions.js';
import { escapeHtml } from '../escape.js';
import { showToast } from '../../ui/notifications.js';
import { showConfirmAsync } from '../modals.js';
import { previewPlacement } from '../../api/scheduler.js';
import { showPlacementPreviewModal } from '../PlacementPreviewModal.js';
import { getRelativeTime, parseUTCDate, formatDuration } from '../../utils/dates.js';
import { renderDefinitionDetailsHtml, mountDefinitionContentViewer } from '../shared/definition-details-renderer.js';

export class SessionDetailsModal extends BaseComponent {
    constructor() {
        super();
        this.modalInstance = null;
        this.currentSessionId = null;
        this.currentSession = null;
        this._reloadTimer = null;
        this._tabCache = {
            overview: null,
            pipeline: null,
            reports: null,
            resources: null,
        };
        this._activePipelineSubTab = null;
    }

    // =========================================================================
    // Lifecycle
    // =========================================================================

    onMount() {
        // Subscribe to open modal event (raw string, not in EventTypes)
        this.subscribe('UI_OPEN_SESSION_DETAILS', ({ sessionId }) => {
            this.openModal(sessionId);
        });

        // SSE: refresh active tab when this session is updated
        this.subscribe(EventTypes.LABLET_SESSION_UPDATED, data => {
            const id = data.id || data.session_id;
            if (id === this.currentSessionId) {
                this.currentSession = { ...this.currentSession, ...data };
                this.refreshCurrentTab();
                this._scheduleReloadFromBackend();
            }
        });

        this.subscribe(EventTypes.LABLET_SESSION_STATUS_CHANGED, data => {
            const id = data.id || data.session_id;
            if (id === this.currentSessionId) {
                this.currentSession = {
                    ...this.currentSession,
                    status: data.new_status || data.status,
                    updated_at: data.updated_at || new Date().toISOString(),
                };
                this.refreshCurrentTab();
                this._scheduleReloadFromBackend();
            }
        });

        // SSE: live pipeline progress — merge into session and refresh pipeline tab (ADR-034 Sprint E)
        this.subscribe(EventTypes.LABLET_SESSION_PIPELINE_PROGRESS, data => {
            const id = data.session_id || data.id;
            if (id !== this.currentSessionId) return;
            const pName = data.pipeline_name;
            if (!pName) return;
            const merged = { ...(this.currentSession?.pipeline_progress || {}) };
            merged[pName] = data.progress || {};
            this.currentSession = { ...this.currentSession, pipeline_progress: merged };
            // Invalidate pipeline cache and refresh if pipeline tab is active
            this._tabCache.pipeline = null;
            const activeTab = this.$('[data-tab].active');
            if (activeTab?.dataset.tab === 'pipeline') {
                this._renderPipelineTab();
            }
            this._scheduleReloadFromBackend(250);
        });

        // SSE: desired_status changed — update session and refresh overview (ADR-034 Sprint E)
        this.subscribe(EventTypes.LABLET_SESSION_DESIRED_STATUS_CHANGED, data => {
            const id = data.session_id || data.id;
            if (id !== this.currentSessionId) return;
            this.currentSession = {
                ...this.currentSession,
                desired_status: data.new_desired_status,
            };
            this._tabCache.overview = null;
            const activeTab = this.$('[data-tab].active');
            if (activeTab?.dataset.tab === 'overview') {
                this._renderOverviewTab();
            }
            this._scheduleReloadFromBackend();
        });

        // SSE: lab bound/unbound — update lab_record_id on this session and refresh overview
        this.subscribe(EventTypes.LAB_RECORD_BOUND, data => {
            const sessionId = data.lablet_session_id;
            if (sessionId !== this.currentSessionId) return;
            const labRecordId = data.lab_record_id || data.id;
            this.currentSession = {
                ...this.currentSession,
                lab_record_id: labRecordId,
                cml_lab_id: data.lab_id || this.currentSession?.cml_lab_id,
            };
            this._tabCache.overview = null;
            const activeTab = this.$('[data-tab].active');
            if (activeTab?.dataset.tab === 'overview') {
                this._renderOverviewTab();
            }
            this._scheduleReloadFromBackend();
        });

        this.subscribe(EventTypes.LAB_RECORD_UNBOUND, data => {
            const sessionId = data.lablet_session_id;
            if (sessionId !== this.currentSessionId) return;
            this.currentSession = {
                ...this.currentSession,
                lab_record_id: null,
            };
            this._tabCache.overview = null;
            const activeTab = this.$('[data-tab].active');
            if (activeTab?.dataset.tab === 'overview') {
                this._renderOverviewTab();
            }
            this._scheduleReloadFromBackend();
        });

        this.render();
    }

    disconnectedCallback() {
        if (this._reloadTimer) {
            clearTimeout(this._reloadTimer);
            this._reloadTimer = null;
        }
        super.disconnectedCallback();
    }

    // =========================================================================
    // Render — static modal shell
    // =========================================================================

    render() {
        this.innerHTML = `
            <div class="modal fade" id="sessionDetailsModalV2" tabindex="-1">
                <div class="modal-dialog modal-xl modal-dialog-scrollable">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title" id="session-modal-title">
                                <i class="bi bi-easel me-1"></i> Session Details
                            </h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                        </div>
                        <div class="modal-body">
                            <!-- Navigation Tabs -->
                            <ul class="nav nav-tabs mb-3" id="sessionDetailsTabs" role="tablist">
                                <li class="nav-item" role="presentation">
                                    <button class="nav-link active" data-tab="overview" type="button">
                                        <i class="bi bi-info-circle me-1"></i>Overview
                                    </button>
                                </li>
                                <li class="nav-item" role="presentation">
                                    <button class="nav-link" data-tab="pipeline" type="button">
                                        <i class="bi bi-arrow-repeat me-1"></i>Pipeline
                                    </button>
                                </li>
                                <li class="nav-item" role="presentation">
                                    <button class="nav-link" data-tab="reports" type="button">
                                        <i class="bi bi-clipboard-data me-1"></i>Reports
                                    </button>
                                </li>
                                <li class="nav-item" role="presentation">
                                    <button class="nav-link" data-tab="resources" type="button">
                                        <i class="bi bi-bar-chart-line me-1"></i>Resources
                                    </button>
                                </li>
                            </ul>

                            <!-- Tab Content -->
                            <div class="tab-content" id="sessionDetailsTabContent">
                                <div class="tab-pane fade show active" id="session-overview-panel" role="tabpanel">
                                    <div id="session-tab-overview">
                                        <div class="text-center py-5">
                                            <div class="spinner-border" role="status"></div>
                                            <p class="mt-3 text-muted">Loading session details…</p>
                                        </div>
                                    </div>
                                </div>
                                <div class="tab-pane fade" id="session-pipeline-panel" role="tabpanel">
                                    <div id="session-tab-pipeline">
                                        <p class="text-muted text-center py-4">Coming soon…</p>
                                    </div>
                                </div>
                                <div class="tab-pane fade" id="session-reports-panel" role="tabpanel">
                                    <div id="session-tab-reports">
                                        <p class="text-muted text-center py-4">Coming soon…</p>
                                    </div>
                                </div>
                                <div class="tab-pane fade" id="session-resources-panel" role="tabpanel">
                                    <div id="session-tab-resources">
                                        <p class="text-muted text-center py-4">Coming soon…</p>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div class="modal-footer" id="session-modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        this.setupEventListeners();
    }

    // =========================================================================
    // Event Listeners
    // =========================================================================

    setupEventListeners() {
        const modalEl = this.$('#sessionDetailsModalV2');
        if (!modalEl) return;

        // Initialize Bootstrap modal
        this.modalInstance = new bootstrap.Modal(modalEl);

        // Tab click handlers
        this.$$('[data-tab]').forEach(btn => {
            btn.addEventListener('click', e => {
                e.preventDefault();
                this.switchTab(btn.dataset.tab);
            });
        });

        // Modal cleanup on hide
        modalEl.addEventListener('hidden.bs.modal', () => {
            this.currentSessionId = null;
            this.currentSession = null;
            this._resetTabCache();
        });
    }

    // =========================================================================
    // Modal Open / Close
    // =========================================================================

    async openModal(sessionId) {
        this.currentSessionId = sessionId;
        this._resetTabCache();

        // Show modal immediately with spinner
        if (this.modalInstance) {
            this.modalInstance.show();
        }

        // Fetch session data
        await this._loadSessionData();

        // Activate the overview tab (eager-loaded)
        this.switchTab('overview');
    }

    closeModal() {
        if (this.modalInstance) {
            this.modalInstance.hide();
        }
    }

    // =========================================================================
    // Data Loading
    // =========================================================================

    async _loadSessionData() {
        if (!this.currentSessionId) return;

        try {
            this.currentSession = await labletSessionsApi.getLabletSession(this.currentSessionId);
            this._updateModalHeader();
            this._updateFooterButtons();
        } catch (error) {
            console.error('[SessionDetailsModal] Failed to load session:', error);
            showToast(`Failed to load session details: ${error.message}`, 'error');
        }
    }

    _scheduleReloadFromBackend(delay = 500) {
        if (!this.currentSessionId) return;

        if (this._reloadTimer) {
            clearTimeout(this._reloadTimer);
        }

        this._reloadTimer = setTimeout(() => {
            this._reloadTimer = null;
            this._reloadSessionDataFromBackend();
        }, delay);
    }

    async _reloadSessionDataFromBackend() {
        if (!this.currentSessionId) return;

        try {
            const latest = await labletSessionsApi.getLabletSession(this.currentSessionId);
            if (!latest) return;

            this.currentSession = latest;
            this._tabCache.overview = null;
            this._tabCache.pipeline = null;
            this._tabCache.reports = null;
            this._tabCache.resources = null;
            this.refreshCurrentTab();
        } catch (error) {
            console.warn('[SessionDetailsModal] Failed to refresh latest session state:', error);
        }
    }

    // =========================================================================
    // Tab Switching
    // =========================================================================

    switchTab(tabName) {
        // Update tab button active state
        this.$$('[data-tab]').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.tab === tabName);
        });

        // Update tab panel visibility
        const panels = ['overview', 'pipeline', 'reports', 'resources'];
        panels.forEach(panel => {
            const el = this.$(`#session-${panel}-panel`);
            if (el) {
                el.classList.toggle('show', panel === tabName);
                el.classList.toggle('active', panel === tabName);
            }
        });

        // Load tab content
        this._loadTabContent(tabName);
    }

    async _loadTabContent(tabName) {
        switch (tabName) {
            case 'overview':
                this._renderOverviewTab();
                break;
            case 'pipeline':
                this._renderPipelineTab();
                break;
            case 'reports':
                this._renderReportsTab();
                break;
            case 'resources':
                this._renderResourcesTab();
                break;
        }
    }

    refreshCurrentTab() {
        this._updateModalHeader();
        this._updateFooterButtons();
        // Invalidate pipeline cache so SSE updates re-render step progress
        this._tabCache.pipeline = null;
        const activeTab = this.$('[data-tab].active');
        if (activeTab) {
            this._loadTabContent(activeTab.dataset.tab);
        }
    }

    _resetTabCache() {
        this._tabCache = { overview: null, pipeline: null, reports: null, resources: null };
        this._activePipelineSubTab = null;
    }

    // =========================================================================
    // Modal Header & Footer
    // =========================================================================

    _updateModalHeader() {
        const titleEl = this.$('#session-modal-title');
        if (!titleEl || !this.currentSession) return;

        const s = this.currentSession;
        const defName = escapeHtml(s.definition_name || s.definition_id || 'Session');
        titleEl.innerHTML = `<i class="bi bi-easel me-1"></i> ${defName} <small class="text-muted ms-2">${escapeHtml(s.id || '')}</small>`;
    }

    _updateFooterButtons() {
        const footer = this.$('#session-modal-footer');
        if (!footer || !this.currentSession) return;

        const s = this.currentSession;
        const status = (s.status || '').toLowerCase();
        const isTerminal = ['terminated', 'archived'].includes(status);
        const isRunning = status === 'running';

        if (isTerminal) {
            footer.innerHTML = `<button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>`;
            return;
        }

        const observeBtn = isRunning
            ? `<button type="button" class="btn btn-outline-info btn-sm" id="session-modal-observe-btn" title="Observe live CML resources">
                   <i class="bi bi-binoculars me-1"></i>Observe
               </button>`
            : '';

        footer.innerHTML = `
            <div class="d-flex w-100 justify-content-between">
                <div class="btn-group btn-group-sm">
                    ${observeBtn}
                    <button type="button" class="btn btn-outline-info btn-sm" id="session-modal-dryrun-btn" title="Preview placement without scheduling">
                        <i class="bi bi-calculator me-1"></i>Dry Run
                    </button>
                    <button type="button" class="btn btn-outline-primary btn-sm" id="session-modal-requeue-btn" title="Re-queue for reconciliation">
                        <i class="bi bi-arrow-repeat me-1"></i>Sync
                    </button>
                    <button type="button" class="btn btn-outline-danger btn-sm" id="session-modal-terminate-btn" title="Terminate session">
                        <i class="bi bi-x-circle me-1"></i>Terminate
                    </button>
                </div>
                <button type="button" class="btn btn-secondary btn-sm" data-bs-dismiss="modal">Close</button>
            </div>
        `;

        // Attach action handlers
        this._attachFooterHandlers();
    }

    _attachFooterHandlers() {
        const s = this.currentSession;
        if (!s) return;

        // Sync (Requeue)
        this.$('#session-modal-requeue-btn')?.addEventListener('click', async () => {
            const confirmed = await showConfirmAsync('Re-queue Session', `Re-queue session <strong>${escapeHtml(s.id)}</strong> for reconciliation?`, { actionLabel: 'Sync', actionClass: 'btn-primary' });
            if (!confirmed) return;
            try {
                await labletSessionsApi.requeueLabletSession(s.id, 'Manual sync from session detail modal');
                showToast('Session re-queued for reconciliation', 'success');
                this.closeModal();
            } catch (err) {
                showToast(`Requeue failed: ${err.message}`, 'error');
            }
        });

        // Terminate
        this.$('#session-modal-terminate-btn')?.addEventListener('click', async () => {
            const confirmed = await showConfirmAsync('Terminate Session', `Are you sure you want to terminate session <strong>${escapeHtml(s.id)}</strong>?`, { actionLabel: 'Terminate', actionClass: 'btn-danger' });
            if (!confirmed) return;
            try {
                await labletSessionsApi.terminateLabletSession(s.id, 'Manual termination from session detail modal');
                showToast('Session terminated', 'success');
                this.closeModal();
            } catch (err) {
                showToast(`Termination failed: ${err.message}`, 'error');
            }
        });

        // Dry Run
        this.$('#session-modal-dryrun-btn')?.addEventListener('click', async () => {
            const btn = this.$('#session-modal-dryrun-btn');
            try {
                if (btn) {
                    btn.disabled = true;
                    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Running…';
                }
                const result = await previewPlacement({
                    definition_id: s.definition_id,
                    timeslot_start: s.timeslot_start,
                    timeslot_end: s.timeslot_end,
                });
                this.closeModal();
                showPlacementPreviewModal(result, { definitionName: s.definition_name || s.definition_id });
            } catch (err) {
                console.error('[SessionDetailsModal] Dry run failed:', err);
                showToast(`Dry run failed: ${err.message}`, 'error');
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = '<i class="bi bi-calculator me-1"></i>Dry Run';
                }
            }
        });

        // Observe Resources
        this.$('#session-modal-observe-btn')?.addEventListener('click', async () => {
            const btn = this.$('#session-modal-observe-btn');
            try {
                if (btn) {
                    btn.disabled = true;
                    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Observing…';
                }
                await labletSessionsApi.requestResourceObservation(s.id);
                showToast('Resource observation requested. Results will appear shortly.', 'info');
                // Re-open modal after delay to show updated results
                setTimeout(() => this.openModal(s.id), 3000);
            } catch (err) {
                showToast(`Observation failed: ${err.message}`, 'error');
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = '<i class="bi bi-binoculars me-1"></i>Observe';
                }
            }
        });
    }

    // =========================================================================
    // Tab: Overview (Phase 4 — rich layout with cross-references)
    // =========================================================================

    _renderOverviewTab() {
        const container = this.$('#session-tab-overview');
        if (!container || !this.currentSession) return;

        const s = this.currentSession;

        container.innerHTML = `
            <!-- Timeslot progress bar (primary attribute of TimedResource) -->
            ${this._renderTimeslotBar(s)}

            <!-- Lifecycle timeline (primary attribute of TimedResource) -->
            ${this._renderLifecycleTimeline(s)}

            <!-- Identity + Assignment cards -->
            <div class="row g-3 mb-3">
                <div class="col-md-6">${this._renderIdentitySection(s)}</div>
                <div class="col-md-6">${this._renderAssignmentSection(s)}</div>
            </div>

            <!-- Grade result -->
            ${this._renderGradeResult(s)}

            <!-- Observation summary (kept for Phase 7 migration) -->
            ${this._renderObservationSummary(s)}

            <!-- Footer metadata -->
            <div class="mt-3 pt-3 border-top">
                <small class="text-muted">
                    ID: <code class="user-select-all">${escapeHtml(s.id || '')}</code>
                </small>
            </div>
        `;

        // Attach cross-reference click handlers
        this._attachOverviewCrossRefHandlers(container);
    }

    // =========================================================================
    // Overview: Identity Section
    // =========================================================================

    _renderIdentitySection(s) {
        const defDisplay = escapeHtml(s.definition_name || s.definition_id || '—');
        const defLink = s.definition_id
            ? `<a href="#" class="text-decoration-none xref-definition" data-definition-id="${escapeHtml(s.definition_id)}" title="View definition details">${defDisplay} <i class="bi bi-box-arrow-up-right small"></i></a>`
            : defDisplay;

        return `
            <h6 class="text-muted mb-2"><i class="bi bi-person-badge me-1"></i>Identity</h6>
            <dl class="row mb-0">
                <dt class="col-sm-4">Definition</dt>
                <dd class="col-sm-8">${defLink}</dd>
                <dt class="col-sm-4">Version</dt>
                <dd class="col-sm-8">${escapeHtml(s.definition_version || '—')}</dd>
                <dt class="col-sm-4">Status</dt>
                <dd class="col-sm-8">
                    <lcm-status-badge status="${escapeHtml(s.status || '')}" icon pill></lcm-status-badge>
                    ${this._renderDesiredStatusBadge(s)}
                </dd>
                <dt class="col-sm-4">Owner</dt>
                <dd class="col-sm-8"><code class="small user-select-all">${escapeHtml(s.owner_id || '—')}</code></dd>
                <dt class="col-sm-4">Reservation</dt>
                <dd class="col-sm-8">${escapeHtml(s.reservation_id || '—')}</dd>
                <dt class="col-sm-4">Form</dt>
                <dd class="col-sm-8">${escapeHtml(s.form_qualified_name || '—')}</dd>
            </dl>
        `;
    }

    // =========================================================================
    // Overview: Assignment Section
    // =========================================================================

    _renderAssignmentSection(s) {
        const workerDisplay = escapeHtml(s.worker_name || s.worker_id || '—');
        const workerLink = s.worker_id
            ? `<a href="#" class="text-decoration-none xref-worker" data-worker-id="${escapeHtml(s.worker_id)}" data-worker-region="${escapeHtml(s.worker_region || '')}" title="View worker details">${workerDisplay} <i class="bi bi-box-arrow-up-right small"></i></a>`
            : workerDisplay;

        const labRecordDisplay = s.lab_record_id ? `${escapeHtml(s.lab_record_id.substring(0, 8))}…` : '—';
        const labRecordLabel = s.cml_lab_title ? `${escapeHtml(s.cml_lab_title)}` : labRecordDisplay;
        const labRecordStatusBadge = s.lab_record_status
            ? ` <span class="badge ${s.lab_record_status === 'STARTED' ? 'bg-success' : s.lab_record_status === 'STOPPED' ? 'bg-secondary' : s.lab_record_status === 'WIPED' ? 'bg-warning text-dark' : 'bg-info text-dark'} rounded-pill">${escapeHtml(s.lab_record_status)}</span>`
            : '';
        const labRecordLink = s.lab_record_id
            ? `<a href="#" class="text-decoration-none xref-lab-record" data-lab-record-id="${escapeHtml(s.lab_record_id)}" title="${escapeHtml(s.lab_record_id)}">${labRecordLabel} <i class="bi bi-box-arrow-up-right small"></i></a>${labRecordStatusBadge}`
            : labRecordDisplay;

        // CML Lab: prefer title over raw ID, with deep-link to CML endpoint
        let cmlLabDisplay = '—';
        if (s.cml_lab_id) {
            const cmlLabel = escapeHtml(s.cml_lab_title || s.cml_lab_id);
            if (s.worker_cml_endpoint) {
                const cmlUrl = `${s.worker_cml_endpoint.replace(/\/$/, '')}/lab/${encodeURIComponent(s.cml_lab_id)}`;
                cmlLabDisplay = `<a href="${escapeHtml(cmlUrl)}" target="_blank" rel="noopener" class="text-decoration-none" title="Open in CML (${escapeHtml(s.cml_lab_id)})">${cmlLabel} <i class="bi bi-box-arrow-up-right small"></i></a>`;
            } else {
                cmlLabDisplay = `<code class="small">${cmlLabel}</code>`;
            }
        }

        // Format observed_ports as "protocol:port" pairs
        const portsDisplay = this._formatPorts(s.observed_ports);

        // Port warning: when session has a lab bound but no ports allocated
        const status = (s.status || '').toLowerCase();
        const hasLab = !!s.lab_record_id || !!s.cml_lab_id;
        const hasPorts = s.allocated_ports && typeof s.allocated_ports === 'object' && Object.keys(s.allocated_ports).length > 0;
        const portWarningStatuses = ['ready', 'running', 'collecting', 'grading'];
        const showPortWarning = hasLab && !hasPorts && portWarningStatuses.includes(status);

        const portWarningInline = showPortWarning
            ? `<span class="text-warning-emphasis small d-block mt-1" title="No device will be available to the end-user via LDS. Ensure the lablet definition's cml.yml includes Tags for relevant nodes (e.g. serial:0, vnc:0).">
                   <i class="bi bi-exclamation-triangle-fill me-1"></i>No ports allocated
               </span>`
            : '';

        return `
            <h6 class="text-muted mb-2"><i class="bi bi-diagram-3 me-1"></i>Assignment</h6>
            <dl class="row mb-0">
                <dt class="col-sm-4">Worker</dt>
                <dd class="col-sm-8">${workerLink}</dd>
                <dt class="col-sm-4">CML Lab</dt>
                <dd class="col-sm-8">${cmlLabDisplay}</dd>
                <dt class="col-sm-4">Lab Record</dt>
                <dd class="col-sm-8">${labRecordLink}</dd>
                <dt class="col-sm-4">LDS Session</dt>
                <dd class="col-sm-8">${
                    s.lds_session_id
                        ? s.lds_login_url
                            ? `<a href="${escapeHtml(s.lds_login_url)}" target="_blank" rel="noopener" title="${escapeHtml(s.lds_session_id)}">${escapeHtml(s.lds_session_id.split('-')[0])}… <i class="bi bi-box-arrow-up-right small"></i></a>`
                            : `<code class="small">${escapeHtml(s.lds_session_id)}</code>`
                        : '—'
                }</dd>
                <dt class="col-sm-4">Ports</dt>
                <dd class="col-sm-8">${portsDisplay}${portWarningInline}</dd>
            </dl>
        `;
    }

    // =========================================================================
    // Overview: Timeslot Progress Bar
    // =========================================================================

    _renderTimeslotBar(s) {
        if (!s.timeslot_start || !s.timeslot_end) {
            return '';
        }

        const now = new Date();
        const start = parseUTCDate(s.timeslot_start);
        const end = parseUTCDate(s.timeslot_end);
        const totalMs = end - start;
        const elapsedMs = now - start;
        const remainingMs = end - now;

        // Clamp percentage between 0 and 100
        let pct = totalMs > 0 ? Math.round((elapsedMs / totalMs) * 100) : 0;
        pct = Math.max(0, Math.min(100, pct));

        const isExpired = remainingMs <= 0;
        const barClass = isExpired ? 'bg-danger' : pct > 80 ? 'bg-warning' : 'bg-info';

        const startFormatted = this._formatDateTime(s.timeslot_start);
        const endFormatted = this._formatDateTime(s.timeslot_end);
        const startRelative = getRelativeTime(start);
        const endRelative = getRelativeTime(end);
        const durationStr = formatDuration(totalMs);
        const remainingStr = isExpired ? 'Expired' : formatDuration(remainingMs);

        return `
            <div class="border rounded p-2 mb-3">
                <h6 class="text-muted mb-2"><i class="bi bi-clock-history me-1"></i>Timeslot</h6>
                <div class="progress mb-2" style="height: 8px;">
                    <div class="progress-bar ${barClass}" role="progressbar" style="width: ${pct}%"
                         aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100"></div>
                </div>
                <div class="d-flex justify-content-between small text-muted">
                    <span>Start: ${startFormatted} <span class="text-body-secondary">(${startRelative})</span></span>
                    <span>End: ${endFormatted} <span class="text-body-secondary">(${endRelative})</span></span>
                </div>
                <div class="d-flex justify-content-between small text-muted mt-1">
                    <span>Duration: <strong>${durationStr}</strong></span>
                    <span>Remaining: <strong class="${isExpired ? 'text-danger' : ''}">${remainingStr}</strong></span>
                </div>
            </div>
        `;
    }

    // =========================================================================
    // Overview: Lifecycle Timeline
    // =========================================================================

    /** Canonical lifecycle states in order */
    static LIFECYCLE_STATES = ['pending', 'scheduled', 'instantiating', 'ready', 'running', 'collecting', 'grading', 'stopping', 'stopped', 'archived'];

    _renderLifecycleTimeline(s) {
        const currentStatus = (s.status || '').toLowerCase();
        const history = s.state_history || [];

        // Build a map: state → transitioned_at (use the latest transition to each state)
        const stateTimestamps = {};
        for (const t of history) {
            const toState = (t.to_state || '').toLowerCase();
            stateTimestamps[toState] = t.transitioned_at;
        }

        // Determine which states have been reached
        const reachedStates = new Set(Object.keys(stateTimestamps));
        // Also include current status even if state_history is incomplete
        reachedStates.add(currentStatus);

        const states = SessionDetailsModal.LIFECYCLE_STATES;

        const steps = states
            .map(state => {
                const isCurrent = state === currentStatus;
                const isReached = reachedStates.has(state);
                const timestamp = stateTimestamps[state];

                let dotClass, dotChar;
                if (isCurrent) {
                    dotClass = 'lcm-timeline-dot--current';
                    dotChar = '◉';
                } else if (isReached) {
                    dotClass = 'lcm-timeline-dot--reached';
                    dotChar = '●';
                } else {
                    dotClass = 'lcm-timeline-dot--future';
                    dotChar = '○';
                }

                const label = state.charAt(0).toUpperCase() + state.slice(1);
                const timeLabel = timestamp ? getRelativeTime(timestamp) : '';

                return `
                <div class="lcm-timeline-step text-center" title="${label}${timestamp ? ' — ' + this._formatDateTime(timestamp) : ''}">
                    <span class="lcm-timeline-dot ${dotClass}">${dotChar}</span>
                    <div class="lcm-timeline-label small">${label}</div>
                    ${timeLabel ? `<div class="lcm-timeline-time text-muted" style="font-size: 0.65rem;">${timeLabel}</div>` : ''}
                </div>
            `;
            })
            .join('');

        // Handle terminated (special — reachable from any non-terminal state)
        const terminatedEntry = currentStatus === 'terminated' || reachedStates.has('terminated');
        const terminatedStep = terminatedEntry
            ? `<div class="lcm-timeline-step text-center" title="Terminated${stateTimestamps['terminated'] ? ' — ' + this._formatDateTime(stateTimestamps['terminated']) : ''}">
                   <span class="lcm-timeline-dot ${currentStatus === 'terminated' ? 'lcm-timeline-dot--current text-danger' : 'lcm-timeline-dot--reached text-danger'}">◉</span>
                   <div class="lcm-timeline-label small text-danger">Terminated</div>
                   ${stateTimestamps['terminated'] ? `<div class="lcm-timeline-time text-muted" style="font-size: 0.65rem;">${getRelativeTime(stateTimestamps['terminated'])}</div>` : ''}
               </div>`
            : '';

        // State history collapsible table
        const stateHistoryTable = this._renderStateHistoryTable(history);

        return `
            <div class="border rounded p-2 mb-3">
                <h6 class="text-muted mb-2"><i class="bi bi-signpost-split me-1"></i>Lifecycle</h6>
                <div class="lcm-timeline d-flex justify-content-between align-items-start flex-wrap gap-1 mb-2">
                    ${steps}
                    ${terminatedStep}
                </div>
                ${stateHistoryTable}
            </div>
            <style>
                .lcm-timeline-step { flex: 1; min-width: 60px; max-width: 90px; }
                .lcm-timeline-dot { font-size: 1rem; line-height: 1; }
                .lcm-timeline-dot--current { color: var(--bs-primary); font-weight: bold; }
                .lcm-timeline-dot--reached { color: var(--bs-success); }
                .lcm-timeline-dot--future { color: var(--bs-secondary); opacity: 0.4; }
                .lcm-timeline-label { font-size: 0.7rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
            </style>
        `;
    }

    // =========================================================================
    // Overview: State History Table (collapsible)
    // =========================================================================

    _renderStateHistoryTable(history) {
        if (!history || history.length === 0) {
            return '<div class="small text-muted">No state transitions recorded.</div>';
        }

        // Sort by transitioned_at ascending (oldest first)
        const sorted = [...history].sort((a, b) => {
            const ta = a.transitioned_at ? new Date(a.transitioned_at).getTime() : 0;
            const tb = b.transitioned_at ? new Date(b.transitioned_at).getTime() : 0;
            return ta - tb;
        });

        const collapseId = `state-history-collapse-${Date.now()}`;

        const rows = sorted
            .map(
                t => `
            <tr>
                <td class="small">${escapeHtml(t.from_state || '—')}</td>
                <td class="small"><strong>${escapeHtml(t.to_state || '—')}</strong></td>
                <td class="small text-muted">${t.transitioned_at ? this._formatDateTime(t.transitioned_at) : '—'}</td>
                <td class="small text-muted">${t.transitioned_at ? getRelativeTime(t.transitioned_at) : ''}</td>
                <td class="small">${escapeHtml(t.triggered_by || '—')}</td>
                <td class="small">${escapeHtml(t.reason || '')}</td>
            </tr>
        `
            )
            .join('');

        return `
            <div class="mt-1">
                <a class="small text-muted text-decoration-none" data-bs-toggle="collapse" href="#${collapseId}" role="button" aria-expanded="false">
                    <i class="bi bi-chevron-down me-1"></i>${sorted.length} transition${sorted.length !== 1 ? 's' : ''}
                </a>
                <div class="collapse" id="${collapseId}">
                    <div class="table-responsive mt-1">
                        <table class="table table-sm table-bordered mb-0" style="font-size: 0.8rem;">
                            <thead class="table-light">
                                <tr>
                                    <th>From</th>
                                    <th>To</th>
                                    <th>When</th>
                                    <th>Relative</th>
                                    <th>By</th>
                                    <th>Reason</th>
                                </tr>
                            </thead>
                            <tbody>${rows}</tbody>
                        </table>
                    </div>
                </div>
            </div>
        `;
    }

    // =========================================================================
    // Overview: Grade Result Badge
    // =========================================================================

    _renderGradeResult(s) {
        const grade = (s.grade_result || '').toUpperCase();
        if (!grade && !s.grade_result) {
            // Only show if session has passed grading phase or is terminal
            const status = (s.status || '').toLowerCase();
            const showPlaceholder = ['grading', 'stopping', 'stopped', 'archived', 'terminated'].includes(status);
            if (!showPlaceholder) return '';
        }

        let badgeHtml;
        if (grade === 'PASS') {
            badgeHtml = '<span class="badge bg-success"><i class="bi bi-check-circle me-1"></i>PASS</span>';
        } else if (grade === 'FAIL') {
            badgeHtml = '<span class="badge bg-danger"><i class="bi bi-x-circle me-1"></i>FAIL</span>';
        } else {
            badgeHtml = '<span class="badge bg-secondary"><i class="bi bi-dash-circle me-1"></i>Not graded</span>';
        }

        return `
            <div class="border rounded p-2 mb-3">
                <h6 class="text-muted mb-1"><i class="bi bi-mortarboard me-1"></i>Grade Result</h6>
                <div>${badgeHtml}</div>
            </div>
        `;
    }

    // =========================================================================
    // Overview: Cross-Reference Click Handlers
    // =========================================================================

    _attachOverviewCrossRefHandlers(container) {
        // Definition cross-ref → close self → open definition details modal
        container.querySelectorAll('.xref-definition').forEach(link => {
            link.addEventListener('click', e => {
                e.preventDefault();
                const defId = link.dataset.definitionId;
                if (!defId) return;
                this.closeModal();
                setTimeout(() => this._openDefinitionDetails(defId), 300);
            });
        });

        // Worker cross-ref → close self → open WorkerDetailsModal
        container.querySelectorAll('.xref-worker').forEach(link => {
            link.addEventListener('click', e => {
                e.preventDefault();
                const workerId = link.dataset.workerId;
                const region = link.dataset.workerRegion || '';
                if (!workerId) return;
                this.closeModal();
                setTimeout(() => {
                    eventBus.emit('UI_OPEN_WORKER_DETAILS', { workerId, region });
                }, 300);
            });
        });

        // Lab Record cross-ref → close self → open LabDetailModal
        container.querySelectorAll('.xref-lab-record').forEach(link => {
            link.addEventListener('click', e => {
                e.preventDefault();
                const labRecordId = link.dataset.labRecordId;
                if (!labRecordId) return;
                this.closeModal();
                setTimeout(() => {
                    const labModal = document.querySelector('lab-detail-modal');
                    if (labModal) labModal.open(labRecordId);
                }, 300);
            });
        });
    }

    // =========================================================================
    // Definition Details (cross-ref target)
    // =========================================================================

    async _openDefinitionDetails(definitionId) {
        try {
            const def = await labletDefinitionsApi.getLabletDefinition(definitionId);
            const modal = document.getElementById('labletDefinitionDetailsModal');
            const content = document.getElementById('labletDefinitionDetailsContent');
            if (!modal || !content) {
                showToast('Definition details modal not found in DOM', 'warning');
                return;
            }

            content.innerHTML = renderDefinitionDetailsHtml(def, this._formatDateTime.bind(this));
            mountDefinitionContentViewer(content, def);

            // Wire sync button if present
            const syncBtn = document.getElementById('syncDefinitionFromDetailBtn');
            if (syncBtn) {
                syncBtn.classList.remove('d-none');
                syncBtn.dataset.definitionId = def.id;
            }

            bootstrap.Modal.getOrCreateInstance(modal).show();
        } catch (error) {
            console.error('[SessionDetailsModal] Failed to load definition:', error);
            showToast(`Failed to load definition: ${error.message}`, 'error');
        }
    }

    // =========================================================================
    // Ports Formatter
    // =========================================================================

    _formatPorts(ports) {
        if (!ports || typeof ports !== 'object') return '<span class="text-muted">—</span>';
        const entries = Object.entries(ports);
        if (entries.length === 0) return '<span class="text-muted">—</span>';

        return entries.map(([proto, port]) => `<code class="small">${escapeHtml(proto)}:${port}</code>`).join(' ');
    }

    // =========================================================================
    // Tab: Pipeline (ADR-034 Sprint E — multi-pipeline sub-tabs)
    // =========================================================================

    /**
     * Default display names for pipeline types.
     * The UI prefers data-driven labels from the pipeline config when available,
     * falling back to these defaults for unknown pipeline names.
     */
    static PIPELINE_DISPLAY_NAMES = {
        instantiate: 'Instantiate',
        teardown: 'Release',
        collect_evidence: 'Collect Evidences',
        compute_grading: 'Compute Grading',
    };

    /** Canonical lifecycle ordering for pipeline sub-tabs (left → right = time). */
    static PIPELINE_ORDER = ['instantiate', 'teardown', 'collect_evidence', 'compute_grading'];

    /** Icons for each pipeline type. */
    static PIPELINE_ICONS = {
        instantiate: 'bi-play-circle',
        teardown: 'bi-stop-circle',
        collect_evidence: 'bi-collection',
        compute_grading: 'bi-mortarboard',
    };

    _renderPipelineTab() {
        const container = this.$('#session-tab-pipeline');
        if (!container || !this.currentSession) return;

        const s = this.currentSession;

        // Collect pipeline data from pipeline_progress (ADR-034)
        const pipelines = this._collectPipelineData(s);

        if (Object.keys(pipelines).length === 0) {
            // No pipeline data — show contextual empty state
            const status = (s.status || '').toLowerCase();
            const isPre = ['pending', 'scheduled'].includes(status);
            const isPost = ['ready', 'running', 'collecting', 'grading', 'stopping', 'stopped', 'archived', 'terminated'].includes(status);

            container.innerHTML = `
                <div class="text-center py-4">
                    <i class="bi bi-${isPre ? 'hourglass' : isPost ? 'check-circle text-success' : 'gear'} fs-3 mb-2 d-block"></i>
                    <p class="text-muted mb-0">
                        ${isPre ? 'Pipeline will start when session enters <strong>INSTANTIATING</strong>.' : isPost ? 'Pipeline completed — session is past instantiation.' : 'No pipeline data available for this session.'}
                    </p>
                </div>
            `;
            this._tabCache.pipeline = true;
            return;
        }

        // Sort pipeline names in lifecycle order
        const orderedNames = this._orderPipelineNames(Object.keys(pipelines));

        // Determine which sub-tab to show (prefer first in-progress, else first)
        const activePipeline = this._activePipelineSubTab || this._inferActivePipeline(orderedNames, pipelines) || orderedNames[0];

        // Render sub-tab navigation + content
        const subTabs = orderedNames
            .map(name => {
                const display = SessionDetailsModal.PIPELINE_DISPLAY_NAMES[name] || this._prettifyName(name);
                const icon = SessionDetailsModal.PIPELINE_ICONS[name] || 'bi-gear';
                const isActive = name === activePipeline;
                const pData = pipelines[name];
                const statusDot = this._pipelineStatusDot(pData);
                return `<li class="nav-item" role="presentation">
                <button class="nav-link${isActive ? ' active' : ''} py-1 px-2 small" data-pipeline-tab="${escapeHtml(name)}" type="button">
                    <i class="bi ${icon} me-1"></i>${escapeHtml(display)} ${statusDot}
                </button>
            </li>`;
            })
            .join('');

        const activeContent = this._renderSinglePipeline(activePipeline, pipelines[activePipeline]);

        container.innerHTML = `
            <ul class="nav nav-tabs nav-fill mb-3" role="tablist" id="pipeline-sub-tabs">
                ${subTabs}
            </ul>
            <div id="pipeline-sub-content">
                ${activeContent}
            </div>
        `;

        // Attach sub-tab click handlers
        container.querySelectorAll('[data-pipeline-tab]').forEach(btn => {
            btn.addEventListener('click', e => {
                e.preventDefault();
                this._activePipelineSubTab = btn.dataset.pipelineTab;
                this._tabCache.pipeline = null;
                this._renderPipelineTab();
            });
        });

        this._tabCache.pipeline = true;
    }

    /**
     * Collect pipeline data from pipeline_progress.
     * Returns { pipelineName: { format: 'generic', data: ... } }
     */
    _collectPipelineData(session) {
        const result = {};

        // pipeline_progress (ADR-034): { "instantiate": { step: {status, order}, ... }, ... }
        if (session.pipeline_progress && typeof session.pipeline_progress === 'object') {
            for (const [name, stepDict] of Object.entries(session.pipeline_progress)) {
                if (stepDict && typeof stepDict === 'object' && Object.keys(stepDict).length > 0) {
                    result[name] = { format: 'generic', data: stepDict };
                }
            }
        }

        return result;
    }

    /** Sort pipeline names in lifecycle order, unknown names appended at end. */
    _orderPipelineNames(names) {
        const order = SessionDetailsModal.PIPELINE_ORDER;
        const known = names.filter(n => order.includes(n)).sort((a, b) => order.indexOf(a) - order.indexOf(b));
        const unknown = names.filter(n => !order.includes(n)).sort();
        return [...known, ...unknown];
    }

    /** Infer which pipeline sub-tab to activate (prefer in-progress, else last with data). */
    _inferActivePipeline(orderedNames, pipelines) {
        // Find first pipeline with an in-progress step
        for (const name of orderedNames) {
            const p = pipelines[name];
            if (this._hasPipelineInProgressStep(p)) return name;
        }
        // Fall back to last pipeline with any completed/failed step (most recent activity)
        for (let i = orderedNames.length - 1; i >= 0; i--) {
            const name = orderedNames[i];
            const p = pipelines[name];
            if (this._hasPipelineActivity(p)) return name;
        }
        return null;
    }

    _hasPipelineInProgressStep(pipeline) {
        return Object.values(pipeline.data).some(s => s.status === 'in_progress');
    }

    _hasPipelineActivity(pipeline) {
        return Object.values(pipeline.data).some(s => s.status !== 'pending');
    }

    /** Render a small status dot for the pipeline sub-tab button. */
    _pipelineStatusDot(pipeline) {
        const steps = this._getPipelineSteps(pipeline);
        if (steps.length === 0) return '';
        const hasFailed = steps.some(s => s.status === 'failed');
        const allDone = steps.every(s => ['completed', 'skipped'].includes(s.status));
        const hasInProgress = steps.some(s => s.status === 'in_progress');
        if (hasFailed) return '<span class="badge bg-danger rounded-pill ms-1" style="font-size:0.55rem;">!</span>';
        if (allDone) return '<span class="badge bg-success rounded-pill ms-1" style="font-size:0.55rem;">✓</span>';
        if (hasInProgress) return '<span class="spinner-border spinner-border-sm ms-1" style="width:0.6rem;height:0.6rem;"></span>';
        return '';
    }

    /** Extract normalized step array. */
    _getPipelineSteps(pipeline) {
        // Generic format: dict of { step_name: { status, order, error?, result_data?, skip_reason? } }
        return Object.entries(pipeline.data)
            .map(([name, step]) => ({
                name,
                status: step.status || 'pending',
                error: step.error || step.skip_reason || null,
                result_data: step.result_data || null,
                completed_at: step.completed_at || null,
                attempt_count: step.attempt_count || 0,
                requires: step.requires || [],
                order: step.order ?? 999,
            }))
            .sort((a, b) => a.order - b.order);
    }

    /**
     * Render a single pipeline panel (progress bar + step list).
     */
    _renderSinglePipeline(pipelineName, pipeline) {
        const displayName = SessionDetailsModal.PIPELINE_DISPLAY_NAMES[pipelineName] || this._prettifyName(pipelineName);
        const icon = SessionDetailsModal.PIPELINE_ICONS[pipelineName] || 'bi-gear';
        const steps = this._getPipelineSteps(pipeline);

        if (steps.length === 0) {
            return `<div class="text-center py-3 text-muted"><i class="bi bi-hourglass me-1"></i>No steps recorded yet.</div>`;
        }

        // Summary stats
        const completed = steps.filter(s => s.status === 'completed').length;
        const skipped = steps.filter(s => s.status === 'skipped').length;
        const failed = steps.filter(s => s.status === 'failed').length;
        const inProgress = steps.filter(s => s.status === 'in_progress').length;
        const pending = steps.filter(s => s.status === 'pending').length;
        const total = steps.length;
        const donePct = total > 0 ? Math.round(((completed + skipped) / total) * 100) : 0;
        const barClass = failed > 0 ? 'bg-danger' : donePct === 100 ? 'bg-success' : 'bg-info';

        // Render step rows
        const stepRows = steps.map(step => this._renderPipelineStepRow(step)).join('');

        // Progress panel
        return `
            <div class="border rounded p-3">
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <h6 class="mb-0"><i class="bi ${icon} me-1"></i>${escapeHtml(displayName)}</h6>
                </div>
                <div class="progress mb-2" style="height: 6px;">
                    <div class="progress-bar ${barClass}" role="progressbar" style="width: ${donePct}%"
                         aria-valuenow="${donePct}" aria-valuemin="0" aria-valuemax="100"></div>
                </div>
                <div class="d-flex justify-content-between small text-muted mb-3">
                    <span>${completed} completed · ${skipped} skipped · ${failed} failed · ${inProgress} in progress · ${pending} pending</span>
                    <span>${donePct}%</span>
                </div>
                <div class="list-group list-group-flush">
                    ${stepRows}
                </div>
            </div>
        `;
    }

    /**
     * Render a single pipeline step row.
     * @param {object} step - Normalized step { name, status, error, result_data, completed_at, attempt_count, requires, order }
     * @returns {string} HTML
     */
    _renderPipelineStepRow(step) {
        const label = this._prettifyName(step.name);
        const isActive = step.status === 'in_progress';

        let icon, statusBadge;
        switch (step.status) {
            case 'completed':
                icon = '<i class="bi bi-check-circle-fill text-success me-2"></i>';
                statusBadge = '<span class="badge bg-success-subtle text-success">completed</span>';
                break;
            case 'failed':
                icon = '<i class="bi bi-x-circle-fill text-danger me-2"></i>';
                statusBadge = '<span class="badge bg-danger-subtle text-danger">failed</span>';
                break;
            case 'skipped':
                icon = '<i class="bi bi-skip-forward-fill text-secondary me-2"></i>';
                statusBadge = '<span class="badge bg-secondary-subtle text-secondary">skipped</span>';
                break;
            case 'in_progress':
                icon = '<span class="spinner-border spinner-border-sm text-primary me-2"></span>';
                statusBadge = '<span class="badge bg-primary-subtle text-primary">running</span>';
                break;
            case 'pending':
            default:
                icon = isActive ? '<span class="spinner-border spinner-border-sm text-primary me-2"></span>' : '<i class="bi bi-circle text-secondary me-2" style="opacity: 0.4;"></i>';
                statusBadge = isActive ? '<span class="badge bg-primary-subtle text-primary">running</span>' : '<span class="badge bg-light text-secondary">pending</span>';
                break;
        }

        // Timestamp
        const timeStr = step.completed_at ? `<span class="text-muted ms-2" style="font-size: 0.75rem;">${this._formatDateTime(step.completed_at)}</span>` : '';

        // Retry badge
        const retryBadge = step.attempt_count > 1 ? `<span class="badge bg-warning-subtle text-warning ms-1">retry ${step.attempt_count}</span>` : '';

        // Prerequisites
        const prereqs = step.requires.length > 0 ? `<span class="text-muted ms-2" style="font-size: 0.7rem;">requires: ${step.requires.map(r => escapeHtml(this._prettifyName(r))).join(', ')}</span>` : '';

        // Error detail
        const errorDetail = step.error ? `<div class="mt-1 small text-danger"><i class="bi bi-exclamation-triangle me-1"></i>${escapeHtml(step.error)}</div>` : '';

        // Result data summary
        const resultSummary = step.result_data && Object.keys(step.result_data).length > 0 ? this._renderStepResultData(step.result_data) : '';

        const activeClass = isActive ? 'list-group-item-primary' : step.status === 'failed' ? 'list-group-item-danger' : '';

        return `
            <div class="list-group-item ${activeClass} px-2 py-2">
                <div class="d-flex align-items-center justify-content-between">
                    <div class="d-flex align-items-center">
                        ${icon}
                        <span class="fw-semibold small">${escapeHtml(label)}</span>
                        ${prereqs}
                    </div>
                    <div class="d-flex align-items-center gap-1">
                        ${retryBadge}
                        ${statusBadge}
                        ${timeStr}
                    </div>
                </div>
                ${errorDetail}
                ${resultSummary}
            </div>
        `;
    }

    /**
     * Convert a snake_case step/pipeline name to a human-readable label.
     * Example: "content_sync" → "Content Sync", "lab_start" → "Lab Start"
     */
    _prettifyName(name) {
        if (!name) return '—';
        return name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    }

    /**
     * Render a desired_status badge (shown next to current status in Overview).
     * Only displayed when desired_status differs from current status.
     */
    _renderDesiredStatusBadge(session) {
        const desired = (session.desired_status || '').toLowerCase();
        const current = (session.status || '').toLowerCase();
        if (!desired || desired === current) return '';
        const icon = desired === 'terminated' ? 'bi-x-circle' : desired === 'stopped' ? 'bi-stop-circle' : 'bi-arrow-right-circle';
        return `<span class="badge bg-warning-subtle text-warning ms-2" title="Desired status — reconciliation target"><i class="bi ${icon} me-1"></i>→ ${escapeHtml(desired)}</span>`;
    }

    /**
     * Render step result_data as a compact key-value summary.
     * @param {object} data - Step result data dict
     * @returns {string} HTML
     */
    _renderStepResultData(data) {
        const entries = Object.entries(data);
        if (entries.length === 0) return '';

        const items = entries
            .slice(0, 5)
            .map(([k, v]) => {
                let display;
                if (typeof v === 'object' && v !== null) {
                    display = JSON.stringify(v).substring(0, 60);
                    if (JSON.stringify(v).length > 60) display += '…';
                } else {
                    display = String(v);
                }
                return `<span class="me-3"><span class="text-muted">${escapeHtml(k)}:</span> <code class="small">${escapeHtml(display)}</code></span>`;
            })
            .join('');

        const more = entries.length > 5 ? `<span class="text-muted">+${entries.length - 5} more</span>` : '';

        return `<div class="mt-1" style="font-size: 0.75rem;">${items}${more}</div>`;
    }

    // =========================================================================
    // Tab: Reports (Phase 6 stub)
    // =========================================================================

    _renderReportsTab() {
        const container = this.$('#session-tab-reports');
        if (!container) return;
        if (this._tabCache.reports) return; // already loaded
        container.innerHTML = `<p class="text-muted text-center py-4">Coming soon…</p>`;
        this._tabCache.reports = true;
    }

    // =========================================================================
    // Tab: Resources (Phase 7 stub)
    // =========================================================================

    _renderResourcesTab() {
        const container = this.$('#session-tab-resources');
        if (!container) return;
        if (this._tabCache.resources) return; // already loaded
        container.innerHTML = `<p class="text-muted text-center py-4">Coming soon…</p>`;
        this._tabCache.resources = true;
    }

    // =========================================================================
    // Observation Summary (migrated from SessionsPage)
    // =========================================================================

    _renderObservationSummary(session) {
        const canObserve = (session.status || '').toLowerCase() === 'running';
        const hasObs = !!session.observed_resources;

        if (hasObs) {
            const obs = session.observed_resources;
            const obsCount = session.observation_count || 0;
            const obsTime = session.observed_at ? this._formatDateTime(session.observed_at) : '—';
            const driftDetected = session.port_drift_detected || false;

            return `
                <hr class="my-3">
                <h6 class="text-muted mb-2">
                    <i class="bi bi-binoculars me-1"></i>Resource Observations
                    ${driftDetected ? '<span class="badge bg-warning text-dark ms-2">⚠️ Drift</span>' : ''}
                </h6>
                <div class="small text-muted mb-2">
                    ${obsCount} observation${obsCount !== 1 ? 's' : ''} • Last: ${obsTime}
                </div>
                <div class="row g-2 mb-2">
                    <div class="col-3 text-center">
                        <div class="bg-light rounded p-2">
                            <div class="small text-muted">CPU</div>
                            <div class="fw-bold">${obs.total_cpu_cores ?? '—'}</div>
                        </div>
                    </div>
                    <div class="col-3 text-center">
                        <div class="bg-light rounded p-2">
                            <div class="small text-muted">Memory</div>
                            <div class="fw-bold">${obs.total_memory_mb != null ? Math.round((obs.total_memory_mb / 1024) * 10) / 10 + ' GB' : '—'}</div>
                        </div>
                    </div>
                    <div class="col-3 text-center">
                        <div class="bg-light rounded p-2">
                            <div class="small text-muted">Nodes</div>
                            <div class="fw-bold">${obs.actual_node_count ?? '—'}</div>
                        </div>
                    </div>
                    <div class="col-3 text-center">
                        <div class="bg-light rounded p-2">
                            <div class="small text-muted">Ports</div>
                            <div class="fw-bold">${Object.keys(session.observed_ports || {}).length}</div>
                        </div>
                    </div>
                </div>
            `;
        } else if (canObserve) {
            return `
                <hr class="my-3">
                <div class="text-muted small">
                    <i class="bi bi-eye-slash me-1"></i>No resource observations yet.
                    Click "Observe" to capture live CML resources.
                </div>
            `;
        }
        return '';
    }

    // =========================================================================
    // Utilities
    // =========================================================================

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
if (!customElements.get('session-details-modal')) {
    customElements.define('session-details-modal', SessionDetailsModal);
}
