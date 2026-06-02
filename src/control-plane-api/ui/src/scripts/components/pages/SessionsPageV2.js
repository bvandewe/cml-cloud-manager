/**
 * SessionsPageV2 — Store-driven Sessions management page
 *
 * Migration target for SessionsPage (Phase M3).
 * Replaces inline EventBus/direct-API calls with:
 *   - StateStore sessions + definitions slices (reactive, SSE-driven updates)
 *   - StoreConnectedPage lifecycle (connectSlice for reactivity)
 *   - Action creators for all API operations
 *
 * Preserves all existing features:
 *   - Dual tab layout: Lablets (sessions table) + Definitions (definitions table)
 *   - Collapsible summary metric tiles (localStorage persisted)
 *   - Multi-select with bulk operations (Requeue, Terminate)
 *   - Session detail modal (click row → modal)
 *   - Definition CRUD (view, edit, sync, delete, create)
 *   - Real-time SSE updates (via store slice subscriptions — no manual SSE wiring)
 *   - Client-side search + server-side status filters
 *   - Worker cross-reference links → WorkerDetailsModal
 *
 * @module components/pages/SessionsPageV2
 */

import { StoreConnectedPage } from '../../bridge/StoreConnectedPage.js';
import { store } from '../../app/store.js';
import { selectAllSessions, selectSessionsListLoading, createSessionsActions, selectAllDefinitions, selectDefinitionsListLoading, createDefinitionsActions } from '../../app/index.js';
import * as labletDefinitionsApi from '../../api/lablet-definitions.js';
import { eventBus, LcmEventTypes } from '../../app/eventBus.js';
import { showToast } from '../../ui/notifications.js';
import { showConfirmAsync } from '../modals.js';
import { getRelativeTime, parseUTCDate, formatDuration } from '../../utils/dates.js';
import { escapeHtml } from '../escape.js';
import { renderDefinitionDetailsHtml, mountDefinitionContentViewer, mountPortPreferenceHandlers } from '../shared/definition-details-renderer.js';
import { populatePortDefinitions } from '../../ui/lablet-modals.js';
import '../core/LcmTabView.js';
import '../core/LcmActionBar.js';
import '../core/LcmMetricCard.js';
import '../core/LcmDataTable.js';
import '../core/LcmStatusBadge.js';
import '../modals/SessionDetailsModal.js';

const STORAGE_KEY_METRICS = 'lcm.sessionsV2.metricsCollapsed';

export class SessionsPageV2 extends StoreConnectedPage {
    static get observedAttributes() {
        return ['active-tab'];
    }

    constructor() {
        super();
        this._activeTab = 'lablets';
        this._metricsCollapsed = localStorage.getItem(STORAGE_KEY_METRICS) === 'true';
        this._clientSearchTerm = '';
        this._selectedStatus = null;
        this._includeTerminated = false;
        this._sessionsReloadTimer = null;
        /** @type {ReturnType<typeof createDefinitionsActions>|null} */
        this._definitionsActions = null;
        /** @type {Array} Cached sessions for metric recalculation on tab switch */
        this._lastSessions = [];
        /** @type {Array} Cached definitions for metric recalculation on tab switch */
        this._lastDefinitions = [];
    }

    // =========================================================================
    // StoreConnectedPage Overrides
    // =========================================================================

    getStoreInstance() {
        return store;
    }

    getActionCreators(storeInstance) {
        return createSessionsActions(storeInstance);
    }

    subscribeToStore() {
        // React to sessions list changes → update table + metric cards
        this.connectSlice('sessions', selectAllSessions, sessions => {
            this._lastSessions = sessions || [];
            this._updateSessionsView(sessions);
            if (this._activeTab === 'lablets') {
                this._updateSessionMetricCards(sessions);
            }
        });

        // React to sessions loading state → show/hide spinner
        this.connectSlice('sessions', selectSessionsListLoading, loading => {
            this._updateLoadingState(loading);
        });

        // React to definitions list changes → update definitions table + metric cards
        this.connectSlice('definitions', selectAllDefinitions, definitions => {
            this._lastDefinitions = definitions || [];
            this._updateDefinitionsView(definitions);
            if (this._activeTab === 'definitions') {
                this._updateDefinitionMetricCards(definitions);
            }
        });

        // React to definitions loading state
        this.connectSlice('definitions', selectDefinitionsListLoading, loading => {
            this._updateDefinitionsLoadingState(loading);
        });
    }

    loadInitialData() {
        // Create definitions actions (secondary slice, like templates in WorkersPageV2)
        this._definitionsActions = createDefinitionsActions(this.getStoreInstance());

        // Re-render with correct role context
        this.render();
        this._bindInteractions();
        this._configureDataTables();

        // Load sessions from API into store
        this._loadSessionsWithFilters();

        // Load definitions from API into store
        this._definitionsActions.loadDefinitions();
    }

    // =========================================================================
    // SSE Event Listeners (supplements store-driven updates)
    // =========================================================================

    _setupPageEventListeners() {
        // Session lifecycle events → already handled by store via SSE adapter
        // Definition lifecycle events → already handled by store via SSE adapter

        // UI_SESSION_CREATED: emitted by lablet-modals.js after successful create.
        // AD-SSE-RACE-001: The full session DTO is now upserted into the store
        // directly from the HTTP 201 response (lablet-modals.js), so no immediate
        // reload is needed. A deferred refresh (3s) enriches any server-computed
        // fields that may have been updated by the scheduling pipeline, without
        // racing against the PENDING→SCHEDULED→INSTANTIATING SSE transitions
        // that complete in ~1-1.5s.
        this.subscribe(LcmEventTypes.UI_SESSION_CREATED, () => {
            this._scheduleSessionsReload(1200);
        });

        const revalidateSessionState = () => {
            this._scheduleSessionsReload();
        };

        [
            LcmEventTypes.LABLET_SESSION_CREATED,
            LcmEventTypes.LABLET_SESSION_UPDATED,
            LcmEventTypes.LABLET_SESSION_STATUS_CHANGED,
            LcmEventTypes.LABLET_SESSION_PIPELINE_PROGRESS,
            LcmEventTypes.LABLET_SESSION_DESIRED_STATUS_CHANGED,
            LcmEventTypes.LABLET_SESSION_SCORE_RECORDED,
            LcmEventTypes.LABLET_SESSION_TIMESLOT_EXTENDED,
            LcmEventTypes.LABLET_SESSION_PORTS_RELEASED,
            LcmEventTypes.LABLET_SESSION_TERMINATED,
            LcmEventTypes.LABLET_SESSION_DELETED,
            LcmEventTypes.PIPELINE_STEP_COMPLETED,
            LcmEventTypes.PIPELINE_STEP_FAILED,
            LcmEventTypes.PIPELINE_COMPLETED,
        ].forEach(eventType => {
            this.subscribe(eventType, revalidateSessionState);
        });

        // Definition sync lifecycle → refresh the details modal if it's currently
        // open for the affected definition. The store/data-table update is handled
        // by sseAdapter → definitions slice → connectSlice. This subscription
        // covers the *modal* which renders a one-time HTML snapshot.
        this.subscribe(LcmEventTypes.LABLET_DEFINITION_CONTENT_SYNCED, data => {
            this._refreshDefinitionDetailsModal(data?.definition_id);
        });
        this.subscribe(LcmEventTypes.LABLET_DEFINITION_SYNC_REQUESTED, data => {
            this._refreshDefinitionDetailsModal(data?.definition_id);
        });
    }

    // =========================================================================
    // Session Actions
    // =========================================================================

    async _requeueSession(sessionId) {
        try {
            await this.actions.requeueSession(sessionId, 'Manual sync from Sessions page');
            showToast('Session re-queued for reconciliation', 'success');
        } catch (error) {
            console.error('[SessionsPageV2] Failed to requeue session:', error);
            showToast(`Failed to sync session: ${error.message}`, 'danger');
        }
    }

    async _terminateSession(sessionId) {
        const confirmed = await showConfirmAsync('Terminate Session', 'Are you sure you want to terminate this lablet session?', { actionLabel: 'Terminate', actionClass: 'btn-danger' });
        if (!confirmed) return;

        try {
            await this.actions.terminateSession(sessionId, 'Terminated from Sessions page');
            showToast('Session terminated successfully', 'success');
            // Reload to get fresh state (removeSession already dispatched by action)
            this._loadSessionsWithFilters();
        } catch (error) {
            console.error('[SessionsPageV2] Failed to terminate session:', error);
            showToast(`Failed to terminate: ${error.message}`, 'danger');
        }
    }

    /**
     * Request resource observation for a RUNNING session (ADR-030 UX).
     * Shows spinner feedback on button, then toast.
     */
    async _observeResources(sessionId) {
        const btn = this.querySelector(`[data-action="observe-resources"][data-id="${sessionId}"]`);

        try {
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
            }

            await this.actions.observeResources(sessionId);
            showToast('Resource observation requested — results will appear shortly.', 'info');
        } catch (error) {
            console.error('[SessionsPageV2] Observe resources failed:', error);
            showToast(`Observation failed: ${error.message}`, 'danger');
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
            return st !== 'terminated' && st !== 'archived' && st !== 'expired';
        });

        if (requeueable.length === 0) {
            showToast('No sessions eligible for sync.', 'warning');
            return;
        }

        const confirmed = await showConfirmAsync('Re-queue Sessions', `Re-queue ${requeueable.length} selected session(s) for reconciliation?`, { actionLabel: 'Re-queue', actionClass: 'btn-warning' });
        if (!confirmed) return;

        try {
            const ids = requeueable.map(r => r.id);
            const result = await this.actions.bulkRequeue(ids, 'Bulk sync from Sessions page');
            const successCount = result?.results?.filter(r => r.success)?.length ?? requeueable.length;
            const failCount = result?.results?.filter(r => !r.success)?.length ?? 0;

            if (successCount > 0) {
                showToast(`${successCount} session(s) re-queued successfully.`, 'success');
            }
            if (failCount > 0) {
                showToast(`${failCount} session(s) failed to re-queue.`, 'danger');
            }
        } catch (error) {
            console.error('[SessionsPageV2] Bulk requeue failed:', error);
            showToast(`Bulk sync failed: ${error.message}`, 'danger');
        }
    }

    async _bulkTerminate(selectedRows) {
        if (!selectedRows || selectedRows.length === 0) return;

        const terminableRows = selectedRows.filter(r => {
            const st = (r.status || '').toLowerCase();
            return st !== 'terminated' && st !== 'archived' && st !== 'expired';
        });

        if (terminableRows.length === 0) {
            showToast('No sessions eligible for termination.', 'warning');
            return;
        }

        const confirmed = await showConfirmAsync('Bulk Terminate', `Terminate ${terminableRows.length} selected session(s)?`, { actionLabel: 'Terminate All', actionClass: 'btn-danger' });
        if (!confirmed) return;

        let successCount = 0;
        let failCount = 0;

        for (const row of terminableRows) {
            try {
                await this.actions.terminateSession(row.id, 'Bulk terminated from Sessions page');
                successCount++;
            } catch (error) {
                console.error(`[SessionsPageV2] Failed to terminate session ${row.id}:`, error);
                failCount++;
            }
        }

        if (successCount > 0) {
            showToast(`${successCount} session(s) terminated successfully.`, 'success');
        }
        if (failCount > 0) {
            showToast(`${failCount} session(s) failed to terminate.`, 'danger');
        }

        // Reload fresh state
        this._loadSessionsWithFilters();
    }

    // =========================================================================
    // Definition Actions
    // =========================================================================

    async _viewDefinition(definitionId) {
        if (!this._definitionsActions) return;

        try {
            const def = await this._definitionsActions.loadDefinitionDetail(definitionId);
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

            const { Modal } = await import('bootstrap');
            Modal.getOrCreateInstance(modal).show();
        } catch (error) {
            console.error('[SessionsPageV2] Failed to load definition:', error);
            showToast(`Failed to load definition: ${error.message}`, 'danger');
        }
    }

    async _editDefinition(definitionId) {
        if (!this.isAdminOrManager()) {
            showToast('Only administrators can edit definitions.', 'warning');
            return;
        }
        if (!this._definitionsActions) return;

        try {
            const def = await this._definitionsActions.loadDefinitionDetail(definitionId);
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

            // Auto-expand resource toggle if definition has non-default resources
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
                const { Collapse } = await import('bootstrap');
                const bsCollapse = Collapse.getOrCreateInstance(collapseEl);
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

            const { Modal } = await import('bootstrap');
            Modal.getOrCreateInstance(modal).show();
        } catch (error) {
            console.error('[SessionsPageV2] Failed to load definition for editing:', error);
            showToast(`Failed to load definition: ${error.message}`, 'danger');
        }
    }

    async _syncDefinition(definitionId) {
        if (!this._definitionsActions) return;

        try {
            await this._definitionsActions.syncDefinition(definitionId);
            showToast('Sync requested — content will be synchronized shortly.', 'success');
        } catch (error) {
            console.error('[SessionsPageV2] Failed to sync definition:', error);
            showToast(`Sync failed: ${error.message}`, 'danger');
        }
    }

    /**
     * Refresh the definition details modal if it is currently open and
     * displaying the given definition. Called when SSE sync lifecycle
     * events arrive (sync_requested, content_synced).
     *
     * @param {string|undefined} definitionId
     */
    async _refreshDefinitionDetailsModal(definitionId) {
        if (!definitionId) return;

        const modal = document.getElementById('labletDefinitionDetailsModal');
        if (!modal || !modal.classList.contains('show')) return;

        // Check that the open modal is for *this* definition
        const syncBtn = document.getElementById('syncDefinitionFromDetailBtn');
        if (syncBtn?.dataset.definitionId !== definitionId) return;

        // Re-fetch + re-render (modal stays open; Bootstrap show() is a no-op
        // when already visible, and innerHTML replacement updates content in-place).
        try {
            await this._viewDefinition(definitionId);
            console.log(`[SessionsPageV2] Refreshed definition details modal for ${definitionId}`);
        } catch (err) {
            console.warn('[SessionsPageV2] Failed to refresh definition modal:', err);
        }
    }

    async _deleteDefinition(definitionId) {
        if (!this.isAdminOrManager()) {
            showToast('Only administrators can delete definitions.', 'warning');
            return;
        }
        if (!this._definitionsActions) return;

        const confirmed = await showConfirmAsync(
            'Delete Definition',
            `<div class="alert alert-warning">
                <i class="bi bi-exclamation-triangle me-2"></i>
                <strong>Warning:</strong> This action cannot be undone.
            </div>
            <p>Are you sure you want to delete this lablet definition?</p>
            <p class="text-muted small">Existing sessions using this definition will not be affected, but no new sessions can be created from it.</p>`,
            { actionLabel: 'Delete', actionClass: 'btn-danger', html: true }
        );
        if (!confirmed) return;

        try {
            await this._definitionsActions.deleteDefinition(definitionId);
            showToast('Definition deleted successfully', 'success');
        } catch (error) {
            console.error('[SessionsPageV2] Failed to delete definition:', error);
            showToast(`Failed to delete: ${error.message}`, 'danger');
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
        const table = this.querySelector('#sessions-lablets-table-v2');
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
            // 2. Candidate
            {
                field: 'owner_id',
                label: 'Candidate',
                sortable: true,
                width: '130px',
                render: value => `<span><i class="bi bi-person me-1"></i>${escapeHtml(value || 'Unknown')}</span>`,
            },
            // 3. Status
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
            // 6. Timeslot — relative time with color coding + duration
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
                    const isTerminal = st === 'terminated' || st === 'archived' || st === 'expired';
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
        const table = this.querySelector('#sessions-definitions-table-v2');
        if (!table) return;

        const isAdmin = this.isAdminOrManager();

        table.setColumns([
            { field: 'name', label: 'Name', sortable: true },
            {
                field: 'form_qualified_name',
                label: 'Form QN',
                sortable: true,
                render: val => (val ? `<span class="text-truncate d-inline-block" style="max-width: 200px;" title="${val}">${val}</span>` : '<span class="text-muted">—</span>'),
            },
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

    // =========================================================================
    // Store-Driven View Updates
    // =========================================================================

    /**
     * Update sessions table from store data.
     * Called reactively via connectSlice subscription.
     */
    _updateSessionsView(sessions) {
        let data = Array.isArray(sessions) ? [...sessions] : [];

        // Apply client-side filters
        data = this._applyClientFilters(data);

        const table = this.querySelector('#sessions-lablets-table-v2');
        if (table) {
            table.setData(data);
        }

        // Update active session count in tab label
        const activeCount = (sessions || []).filter(s => {
            const st = (s.status || '').toLowerCase();
            return st !== 'terminated' && st !== 'terminating';
        }).length;
        const tabView = this.querySelector('#sessions-tabs-v2');
        if (tabView) {
            const labletsTab = tabView.querySelector('#lablets');
            if (labletsTab) {
                labletsTab.setAttribute('label', `Lablets (${activeCount})`);
            }
        }

        this._initTooltips();
    }

    /**
     * Update definitions table from store data.
     * Called reactively via connectSlice subscription.
     */
    _updateDefinitionsView(definitions) {
        const table = this.querySelector('#sessions-definitions-table-v2');
        if (table) {
            table.setData(Array.isArray(definitions) ? definitions : []);
        }
    }

    _updateLoadingState(isLoading) {
        const table = this.querySelector('#sessions-lablets-table-v2');
        if (table) {
            if (isLoading) {
                table.setAttribute('loading', '');
            } else {
                table.removeAttribute('loading');
            }
        }
    }

    _updateDefinitionsLoadingState(isLoading) {
        const table = this.querySelector('#sessions-definitions-table-v2');
        if (table) {
            if (isLoading) {
                table.setAttribute('loading', '');
            } else {
                table.removeAttribute('loading');
            }
        }
    }

    // =========================================================================
    // Metrics Panel
    // =========================================================================

    /**
     * Update metric cards with session statistics (Lablets tab context).
     * Configures card labels, icons, colors, and values for session lifecycle.
     */
    _updateSessionMetricCards(sessions) {
        // Canonical LabletSessionStatus enum (12 states)
        const stats = {
            total: 0,
            pending: 0,
            scheduled: 0,
            instantiating: 0,
            ready: 0,
            running: 0,
            collecting: 0,
            grading: 0,
            stopping: 0,
            stopped: 0,
            archived: 0,
            terminated: 0,
            expired: 0,
        };

        (sessions || []).forEach(s => {
            stats.total++;
            const status = (s.status || '').toLowerCase();
            if (status in stats) stats[status]++;
        });

        // Set card identities for session context
        this._setMetricCardConfig('metric-total-v2', 'Total', 'bi-calendar-check', 'primary');
        this._setMetricCardConfig('metric-pending-v2', 'Pending', 'bi-hourglass-split', 'warning');
        this._setMetricCardConfig('metric-provisioning-v2', 'Instantiating', 'bi-cloud-arrow-up', 'info');
        this._setMetricCardConfig('metric-ready-v2', 'Ready', 'bi-check-circle', 'success');
        this._setMetricCardConfig('metric-running-v2', 'Active', 'bi-play-circle', 'success');
        this._setMetricCardConfig('metric-terminated-v2', 'Terminal', 'bi-x-circle', 'secondary');

        // Set values
        this._setMetricValue('metric-total-v2', stats.total);
        this._setMetricValue('metric-pending-v2', stats.pending + stats.scheduled);
        this._setMetricValue('metric-provisioning-v2', stats.instantiating);
        this._setMetricValue('metric-ready-v2', stats.ready);
        this._setMetricValue('metric-running-v2', stats.running + stats.collecting + stats.grading);
        this._setMetricValue('metric-terminated-v2', stats.terminated + stats.expired + stats.archived);

        // Remove loading state from all metric cards
        this.querySelectorAll('lcm-metric-card[loading]').forEach(card => card.removeAttribute('loading'));
    }

    /**
     * Update metric cards with definition statistics (Definitions tab context).
     * Configures card labels, icons, colors, and values for definition lifecycle.
     *
     * Definition statuses: pending_sync, active, deprecated, archived
     * Sync statuses: sync_requested, success, failed, null
     */
    _updateDefinitionMetricCards(definitions) {
        const stats = {
            total: 0,
            active: 0,
            pending_sync: 0,
            sync_success: 0,
            sync_failed: 0,
            deprecated: 0,
        };

        (definitions || []).forEach(d => {
            stats.total++;
            const status = (d.status || '').toLowerCase();
            const syncStatus = (d.sync_status || '').toLowerCase();

            if (status === 'active') stats.active++;
            else if (status === 'pending_sync') stats.pending_sync++;
            else if (status === 'deprecated') stats.deprecated++;

            if (syncStatus === 'success') stats.sync_success++;
            else if (syncStatus === 'failed') stats.sync_failed++;
        });

        // Reconfigure card identities for definition context
        this._setMetricCardConfig('metric-total-v2', 'Total', 'bi-file-earmark-code', 'primary');
        this._setMetricCardConfig('metric-pending-v2', 'Pending Sync', 'bi-arrow-repeat', 'warning');
        this._setMetricCardConfig('metric-provisioning-v2', 'Active', 'bi-check-circle-fill', 'success');
        this._setMetricCardConfig('metric-ready-v2', 'Synced', 'bi-cloud-check', 'success');
        this._setMetricCardConfig('metric-running-v2', 'Sync Failed', 'bi-exclamation-triangle', 'danger');
        this._setMetricCardConfig('metric-terminated-v2', 'Deprecated', 'bi-archive', 'secondary');

        // Set values
        this._setMetricValue('metric-total-v2', stats.total);
        this._setMetricValue('metric-pending-v2', stats.pending_sync);
        this._setMetricValue('metric-provisioning-v2', stats.active);
        this._setMetricValue('metric-ready-v2', stats.sync_success);
        this._setMetricValue('metric-running-v2', stats.sync_failed);
        this._setMetricValue('metric-terminated-v2', stats.deprecated);

        // Remove loading state from all metric cards
        this.querySelectorAll('lcm-metric-card[loading]').forEach(card => card.removeAttribute('loading'));
    }

    /**
     * Configure a metric card's identity (title, icon, color).
     * Used to switch card context between sessions and definitions tabs.
     */
    _setMetricCardConfig(id, title, icon, color) {
        const card = this.querySelector(`#${id}`);
        if (!card) return;
        card.setAttribute('title', title);
        card.setAttribute('icon', icon);
        card.setAttribute('color', color);
    }

    _setMetricValue(id, value) {
        const card = this.querySelector(`#${id}`);
        if (card) card.setAttribute('value', String(value));
    }

    // =========================================================================
    // Rendering
    // =========================================================================

    render() {
        this.innerHTML = `
            <div class="sessions-page">
                <!-- Page Header with Action Bar -->
                <div class="page-header d-flex justify-content-between align-items-center mb-4">
                    <div>
                        <h2 class="mb-1"><i class="bi bi-easel me-2"></i>Sessions</h2>
                        <p class="text-muted mb-0">Manage lab sessions, reservations, and definitions</p>
                    </div>
                    <lcm-action-bar id="sessions-action-bar-v2">
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
                    <div class="d-flex align-items-center mb-2" role="button" id="metrics-toggle-v2">
                        <span class="fw-medium text-muted small text-uppercase me-2">
                            <i class="bi bi-bar-chart-line me-1"></i>Summary
                        </span>
                        <hr class="flex-grow-1 my-0">
                        <i class="bi bi-chevron-${this._metricsCollapsed ? 'down' : 'up'} ms-2 text-muted" id="metrics-chevron-v2"></i>
                    </div>
                    <div id="metrics-panel-v2" class="${this._metricsCollapsed ? 'd-none' : ''}">
                        <div class="row g-3">
                            <div class="col-6 col-lg-2">
                                <lcm-metric-card id="metric-total-v2" title="Total" value="0"
                                    icon="bi-calendar-check" color="primary" loading></lcm-metric-card>
                            </div>
                            <div class="col-6 col-lg-2" data-bs-toggle="tooltip" data-bs-placement="bottom"
                                 title="pending + scheduled">
                                <lcm-metric-card id="metric-pending-v2" title="Pending" value="0"
                                    icon="bi-hourglass-split" color="warning" loading></lcm-metric-card>
                            </div>
                            <div class="col-6 col-lg-2">
                                <lcm-metric-card id="metric-provisioning-v2" title="Instantiating" value="0"
                                    icon="bi-cloud-arrow-up" color="info" loading></lcm-metric-card>
                            </div>
                            <div class="col-6 col-lg-2">
                                <lcm-metric-card id="metric-ready-v2" title="Ready" value="0"
                                    icon="bi-check-circle" color="success" loading></lcm-metric-card>
                            </div>
                            <div class="col-6 col-lg-2" data-bs-toggle="tooltip" data-bs-placement="bottom"
                                 title="running + collecting + grading">
                                <lcm-metric-card id="metric-running-v2" title="Active" value="0"
                                    icon="bi-play-circle" color="success" loading></lcm-metric-card>
                            </div>
                            <div class="col-6 col-lg-2" data-bs-toggle="tooltip" data-bs-placement="bottom"
                                 title="terminated + expired + archived">
                                <lcm-metric-card id="metric-terminated-v2" title="Terminal" value="0"
                                    icon="bi-x-circle" color="secondary" loading></lcm-metric-card>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Sub-tabs -->
                <lcm-tab-view id="sessions-tabs-v2" variant="underline" persist-key="sessions-tab">
                    <lcm-tab id="lablets" label="Lablets (0)" icon="bi-collection" ${this._activeTab === 'lablets' ? 'active' : ''}></lcm-tab>
                    <lcm-tab id="definitions" label="Definitions" icon="bi-file-earmark-code" ${this._activeTab === 'definitions' ? 'active' : ''}></lcm-tab>
                </lcm-tab-view>

                <!-- Tab Content -->
                <div class="tab-content mt-4">
                    <div id="sessions-lablets-content-v2" class="tab-pane ${this._activeTab === 'lablets' ? 'active' : ''}"
                         ${this._activeTab !== 'lablets' ? 'style="display: none;"' : ''}>
                        ${this._renderLabletsTab()}
                    </div>
                    <div id="sessions-definitions-content-v2" class="tab-pane ${this._activeTab === 'definitions' ? 'active' : ''}"
                         ${this._activeTab !== 'definitions' ? 'style="display: none;"' : ''}>
                        ${this._renderDefinitionsTab()}
                    </div>
                </div>

                <!-- Session Details Modal (via EventBus) -->
                <session-details-modal></session-details-modal>
            </div>
        `;

        this._registerTabContent();
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
                            <input type="text" class="form-control" id="lablets-search-input-v2"
                                placeholder="Search sessions..." value="${this._clientSearchTerm || ''}">
                        </div>
                        <select class="form-select form-select-sm" id="lablets-status-filter-v2" style="width: 160px;">
                            <option value="">All Statuses</option>
                            <option value="pending" ${this._selectedStatus === 'pending' ? 'selected' : ''}>Pending</option>
                            <option value="scheduled" ${this._selectedStatus === 'scheduled' ? 'selected' : ''}>Scheduled</option>
                            <option value="instantiating" ${this._selectedStatus === 'instantiating' ? 'selected' : ''}>Instantiating</option>
                            <option value="ready" ${this._selectedStatus === 'ready' ? 'selected' : ''}>Ready</option>
                            <option value="running" ${this._selectedStatus === 'running' ? 'selected' : ''}>Running</option>
                            <option value="collecting" ${this._selectedStatus === 'collecting' ? 'selected' : ''}>Collecting</option>
                            <option value="grading" ${this._selectedStatus === 'grading' ? 'selected' : ''}>Grading</option>
                            <option value="stopping" ${this._selectedStatus === 'stopping' ? 'selected' : ''}>Stopping</option>
                            <option value="stopped" ${this._selectedStatus === 'stopped' ? 'selected' : ''}>Stopped</option>
                            <option value="archived" ${this._selectedStatus === 'archived' ? 'selected' : ''}>Archived</option>
                            <option value="terminated" ${this._selectedStatus === 'terminated' ? 'selected' : ''}>Terminated</option>
                            <option value="expired" ${this._selectedStatus === 'expired' ? 'selected' : ''}>Expired</option>
                        </select>
                        <div class="form-check form-switch ms-1" style="white-space: nowrap;">
                            <input class="form-check-input" type="checkbox" id="lablets-terminal-toggle-v2"
                                ${this._includeTerminated ? 'checked' : ''}>
                            <label class="form-check-label small" for="lablets-terminal-toggle-v2">Incl. Terminal</label>
                        </div>
                        <button class="btn btn-sm btn-outline-secondary" id="lablets-clear-filters-v2" title="Clear all filters">
                            <i class="bi bi-x-lg"></i>
                        </button>
                    </div>
                </div>
                <div class="card-body p-0">
                    <lcm-data-table id="sessions-lablets-table-v2"
                        page-size="25"
                        selectable
                        no-toolbar
                        panel-mode
                        empty-message="No lablet sessions found. Create your first lablet to get started."
                        loading>
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
                        <select class="form-select form-select-sm" id="definition-table-status-filter-v2" style="width: auto;">
                            <option value="">All Statuses</option>
                            <option value="active">Active</option>
                            <option value="pending_sync">Pending Sync</option>
                            <option value="draft">Draft</option>
                            <option value="archived">Archived</option>
                        </select>
                        <div class="input-group input-group-sm" style="width: 200px;">
                            <span class="input-group-text bg-white"><i class="bi bi-search"></i></span>
                            <input type="search" class="form-control" placeholder="Search..." id="definition-table-search-v2">
                        </div>
                    </div>
                </div>
                <div class="card-body p-0">
                    <lcm-data-table
                        id="sessions-definitions-table-v2"
                        page-size="25"
                        selectable
                        no-toolbar
                        panel-mode
                        empty-message="No lablet definitions found. Create your first definition to get started."
                        loading>
                    </lcm-data-table>
                </div>
            </div>
        `;
    }

    // =========================================================================
    // Tab Management
    // =========================================================================

    _registerTabContent() {
        const tabView = this.querySelector('#sessions-tabs-v2');
        if (!tabView) return;

        const contents = {
            lablets: this.querySelector('#sessions-lablets-content-v2'),
            definitions: this.querySelector('#sessions-definitions-content-v2'),
        };

        Object.entries(contents).forEach(([id, el]) => {
            if (el) tabView.registerContent(id, el);
        });
    }

    _onTabChange({ tabId }) {
        this._activeTab = tabId;

        // Switch metric cards to match the active tab context
        if (tabId === 'definitions') {
            this._updateDefinitionMetricCards(this._lastDefinitions);
            if (this._definitionsActions) {
                this._definitionsActions.loadDefinitions();
            }
        } else if (tabId === 'lablets') {
            this._updateSessionMetricCards(this._lastSessions);
            this._loadSessionsWithFilters();
        }
    }

    // =========================================================================
    // Event Binding
    // =========================================================================

    _bindInteractions() {
        // Tab change
        const tabView = this.querySelector('#sessions-tabs-v2');
        if (tabView) {
            tabView.addEventListener('tab-change', e => {
                this._onTabChange(e.detail);
            });
        }

        // Metrics toggle
        const metricsToggle = this.querySelector('#metrics-toggle-v2');
        if (metricsToggle) {
            metricsToggle.addEventListener('click', () => {
                this._metricsCollapsed = !this._metricsCollapsed;
                localStorage.setItem(STORAGE_KEY_METRICS, this._metricsCollapsed);

                const panel = this.querySelector('#metrics-panel-v2');
                const chevron = this.querySelector('#metrics-chevron-v2');
                if (panel) panel.classList.toggle('d-none', this._metricsCollapsed);
                if (chevron) {
                    chevron.classList.toggle('bi-chevron-down', this._metricsCollapsed);
                    chevron.classList.toggle('bi-chevron-up', !this._metricsCollapsed);
                }
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
        // (row-click guard excludes [role="button"] elements, so title links need their own handler)
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

        // Table filters
        this._bindTableFilters();
    }

    _bindTableFilters() {
        // Lablets tab: search (debounced, client-side)
        const searchInput = this.querySelector('#lablets-search-input-v2');
        let searchTimeout;
        searchInput?.addEventListener('input', e => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                this._clientSearchTerm = e.target.value;
                const sessions = selectAllSessions(this.getStoreState());
                this._updateSessionsView(sessions);
            }, 300);
        });

        // Lablets tab: status filter (server-side → API reload)
        this.querySelector('#lablets-status-filter-v2')?.addEventListener('change', e => {
            this._selectedStatus = e.target.value || null;
            this._loadSessionsWithFilters();
        });

        // Lablets tab: include terminated toggle (server-side → API reload)
        this.querySelector('#lablets-terminal-toggle-v2')?.addEventListener('change', e => {
            this._includeTerminated = e.target.checked;
            this._loadSessionsWithFilters();
        });

        // Lablets tab: clear filters
        this.querySelector('#lablets-clear-filters-v2')?.addEventListener('click', () => {
            this._clearFilters();
        });

        // Definitions tab: status filter (client-side via table)
        const defStatusFilter = this.querySelector('#definition-table-status-filter-v2');
        if (defStatusFilter) {
            defStatusFilter.addEventListener('change', e => {
                const table = this.querySelector('#sessions-definitions-table-v2');
                if (table) table.setFilter('status', e.target.value);
            });
        }

        // Definitions tab: search (client-side via table)
        const defSearchInput = this.querySelector('#definition-table-search-v2');
        if (defSearchInput) {
            let defSearchTimeout;
            defSearchInput.addEventListener('input', e => {
                clearTimeout(defSearchTimeout);
                defSearchTimeout = setTimeout(() => {
                    const table = this.querySelector('#sessions-definitions-table-v2');
                    if (table) table.setSearch(e.target.value);
                }, 300);
            });
        }
    }

    // =========================================================================
    // Filters
    // =========================================================================

    /**
     * Apply client-side search filter to sessions data.
     * Server-side filters (status, include_terminated) are applied via API call.
     */
    _applyClientFilters(sessions) {
        let data = sessions;

        if (this._clientSearchTerm) {
            const term = this._clientSearchTerm.toLowerCase();
            data = data.filter(
                s =>
                    (s.definition_name || '').toLowerCase().includes(term) ||
                    (s.owner_id || '').toLowerCase().includes(term) ||
                    (s.worker_name || '').toLowerCase().includes(term) ||
                    (s.status || '').toLowerCase().includes(term) ||
                    (s.id || '').toLowerCase().includes(term)
            );
        }

        return data;
    }

    _clearFilters() {
        this._selectedStatus = null;
        this._includeTerminated = false;
        this._clientSearchTerm = '';

        const statusFilter = this.querySelector('#lablets-status-filter-v2');
        const searchInput = this.querySelector('#lablets-search-input-v2');
        const terminalToggle = this.querySelector('#lablets-terminal-toggle-v2');
        if (statusFilter) statusFilter.value = '';
        if (searchInput) searchInput.value = '';
        if (terminalToggle) terminalToggle.checked = false;

        this._loadSessionsWithFilters({ replace: true });
    }

    /**
     * Load sessions from API with current filter state.
     */
    _loadSessionsWithFilters(options = {}) {
        const filters = {};
        if (this._selectedStatus) filters.status = this._selectedStatus;
        if (this._includeTerminated) filters.include_terminal = true;
        return this.actions.loadSessions(filters, options);
    }

    _scheduleSessionsReload(delay = 500) {
        if (this._sessionsReloadTimer) {
            clearTimeout(this._sessionsReloadTimer);
        }

        this._sessionsReloadTimer = setTimeout(() => {
            this._sessionsReloadTimer = null;
            this._loadSessionsWithFilters();
        }, delay);
    }

    _handleRefresh() {
        if (this._activeTab === 'definitions' && this._definitionsActions) {
            this._definitionsActions.loadDefinitions();
        } else {
            this._loadSessionsWithFilters({ replace: true });
        }
    }

    onUnmount() {
        if (this._sessionsReloadTimer) {
            clearTimeout(this._sessionsReloadTimer);
            this._sessionsReloadTimer = null;
        }
        super.onUnmount();
    }

    // =========================================================================
    // Modal Actions
    // =========================================================================

    /**
     * Open the create session modal, optionally pre-selecting a definition.
     */
    async _openCreateSessionModal(preselectedDefinitionId = null) {
        const modal = document.getElementById('createLabletSessionModal');
        if (!modal) {
            console.warn('[SessionsPageV2] createLabletSessionModal not found');
            return;
        }

        // Populate definitions dropdown (API call ensures only active definitions)
        await this._populateDefinitionDropdown(preselectedDefinitionId);

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

        const { Modal } = await import('bootstrap');
        Modal.getOrCreateInstance(modal).show();
    }

    /**
     * Populate the definition dropdown in the create session modal.
     * Only active definitions (successfully synced) are eligible for session creation.
     */
    async _populateDefinitionDropdown(preselectedId = null) {
        const select = document.getElementById('instanceDefinitionId');
        if (!select) return;

        try {
            const definitions = await labletDefinitionsApi.listLabletDefinitions({ status: 'active' });

            select.innerHTML = '<option value="">Select a definition...</option>';

            definitions.forEach(def => {
                const option = document.createElement('option');
                option.value = def.id;
                option.textContent = `${def.name} v${def.version || '?'} (${def.node_count || 0} nodes, ${def.cpu_cores || def.resource_requirements?.cpu_cores || 0} CPU, ${def.memory_gb || def.resource_requirements?.memory_gb || 0} GB RAM)`;
                option.dataset.name = def.name;
                option.dataset.version = def.version || '';
                option.dataset.cpu = def.cpu_cores || def.resource_requirements?.cpu_cores || 0;
                option.dataset.memory = def.memory_gb || def.resource_requirements?.memory_gb || 0;
                option.dataset.nodes = def.node_count || 0;
                select.appendChild(option);
            });

            if (preselectedId) {
                select.value = preselectedId;
                select.dispatchEvent(new Event('change'));
            }
        } catch (error) {
            console.error('[SessionsPageV2] Failed to load definitions:', error);
            select.innerHTML = '<option value="">Failed to load definitions</option>';
        }
    }

    async _openCreateDefinitionModal() {
        const modal = document.getElementById('createLabletDefinitionModal');
        if (!modal) return;
        const { Modal } = await import('bootstrap');
        Modal.getOrCreateInstance(modal).show();
    }

    _showSessionDetailModal(sessionId) {
        eventBus.emit('UI_OPEN_SESSION_DETAILS', { sessionId });
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
            import('bootstrap').then(({ Tooltip }) => {
                Tooltip.getOrCreateInstance(el);
            });
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
if (!customElements.get('sessions-page-v2')) {
    customElements.define('sessions-page-v2', SessionsPageV2);
}

export default SessionsPageV2;
