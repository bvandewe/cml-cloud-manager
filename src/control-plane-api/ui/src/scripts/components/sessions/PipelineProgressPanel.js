/**
 * PipelineProgressPanel — Sprint G (G4)
 *
 * Lifecycle-first pipeline observability component for LabletSession detail view.
 *
 * Design principles:
 * - Lifecycle rail is the HERO — as prominent as timeslot info
 * - Active pipeline steps shown inline with real-time SSE updates
 * - Execution history behind collapsible toggle (advanced)
 * - Intuitive visual language: step pills with status colors + icons
 *
 * Data shape (pipeline_progress on LabletSession):
 *   { "instantiate": { "step_name": { status, order, result_data, error } }, ... }
 *
 * SSE events consumed:
 *   - LABLET_SESSION_PIPELINE_PROGRESS (bulk progress update)
 *   - PIPELINE_STEP_STARTED / COMPLETED / FAILED (granular per-step)
 *   - PIPELINE_COMPLETED (pipeline terminal event)
 *
 * Usage:
 *   <pipeline-progress-panel></pipeline-progress-panel>
 *   // then: element.setSession(sessionObject)
 *
 * @module components/sessions/PipelineProgressPanel
 */

import { BaseComponent } from '../../core/BaseComponent.js';
import { EventTypes } from '../../core/EventBus.js';
import { getPipelineProgress, listPipelineExecutions } from '../../api/lablet-sessions.js';
import '../core/LcmStatusBadge.js';

// ==============================================================================
// Constants
// ==============================================================================

/**
 * Ordered lifecycle phases for the visual rail.
 * Matches LabletSessionStatus enum in lcm_core.
 */
const LIFECYCLE_PHASES = [
    { key: 'pending', label: 'Pending', icon: 'bi-hourglass-split' },
    { key: 'scheduled', label: 'Scheduled', icon: 'bi-calendar-check' },
    { key: 'instantiating', label: 'Instantiating', icon: 'bi-lightning-charge' },
    { key: 'ready', label: 'Ready', icon: 'bi-check-circle' },
    { key: 'running', label: 'Running', icon: 'bi-play-circle-fill' },
    { key: 'collecting', label: 'Collecting', icon: 'bi-collection' },
    { key: 'grading', label: 'Grading', icon: 'bi-pencil-square' },
    { key: 'stopping', label: 'Stopping', icon: 'bi-pause-circle-fill' },
    { key: 'stopped', label: 'Stopped', icon: 'bi-stop-circle-fill' },
    { key: 'archived', label: 'Archived', icon: 'bi-archive' },
];

/**
 * Map lifecycle phases to their associated pipeline (if any).
 * Not every phase runs a pipeline — only certain phases do.
 */
const PHASE_PIPELINE_MAP = {
    instantiating: 'instantiate',
    collecting: 'collect_evidence',
    grading: 'compute_grading',
    stopping: 'teardown',
};

/**
 * Step status → visual styling
 */
const STEP_STATUS_CONFIG = {
    pending: { color: 'secondary', icon: 'bi-circle', label: 'Pending', bgClass: 'bg-light text-secondary' },
    in_progress: { color: 'primary', icon: 'bi-arrow-repeat spin-slow', label: 'Running', bgClass: 'bg-primary bg-opacity-10 text-primary' },
    completed: { color: 'success', icon: 'bi-check-circle-fill', label: 'Done', bgClass: 'bg-success bg-opacity-10 text-success' },
    failed: { color: 'danger', icon: 'bi-exclamation-circle-fill', label: 'Failed', bgClass: 'bg-danger bg-opacity-10 text-danger' },
    skipped: { color: 'warning', icon: 'bi-skip-forward-fill', label: 'Skipped', bgClass: 'bg-warning bg-opacity-10 text-warning' },
};

// ==============================================================================
// Component
// ==============================================================================

export class PipelineProgressPanel extends BaseComponent {
    constructor() {
        super();
        this._session = null;
        this._pipelineProgress = {};
        this._executionHistory = [];
        this._historyVisible = false;
        this._historyLoaded = false;
        this._expandedPipeline = null; // which pipeline detail is expanded
    }

    onMount() {
        this.render();

        // Subscribe to real-time pipeline progress updates
        this.subscribe(EventTypes.LABLET_SESSION_PIPELINE_PROGRESS, data => {
            const sessionId = data.session_id || data.id;
            if (!this._session || this._session.id !== sessionId) return;
            // Merge incoming progress
            if (data.pipeline_name && data.progress) {
                this._pipelineProgress = { ...this._pipelineProgress };
                this._pipelineProgress[data.pipeline_name] = data.progress;
            }
            this.render();
        });

        // Subscribe to granular step events for immediate visual feedback
        const stepEvents = [
            EventTypes.PIPELINE_STEP_STARTED,
            EventTypes.PIPELINE_STEP_COMPLETED,
            EventTypes.PIPELINE_STEP_FAILED,
        ];
        stepEvents.forEach(eventType => {
            this.subscribe(eventType, data => {
                const sessionId = data.session_id || data.aggregate_id;
                if (!this._session || this._session.id !== sessionId) return;
                // The sseAdapter already updates the store; re-read pipeline_progress
                this._refreshProgressFromStore();
                this.render();
            });
        });

        // Subscribe to pipeline completion for terminal update
        this.subscribe(EventTypes.PIPELINE_COMPLETED, data => {
            const sessionId = data.session_id || data.aggregate_id;
            if (!this._session || this._session.id !== sessionId) return;
            this._refreshProgressFromStore();
            // Invalidate history cache so next toggle re-fetches
            this._historyLoaded = false;
            this.render();
        });

        // Subscribe to session status changes to update lifecycle rail
        this.subscribe(EventTypes.LABLET_SESSION_STATUS_CHANGED, data => {
            if (!this._session) return;
            if (data.session_id === this._session.id || data.id === this._session.id) {
                this._session = {
                    ...this._session,
                    status: data.status || data.new_status,
                };
                this.render();
            }
        });

        // Subscribe to session snapshots (full refresh)
        this.subscribe(EventTypes.LABLET_SESSION_SNAPSHOT, data => {
            if (!this._session || data.id !== this._session.id) return;
            this._session = { ...this._session, ...data };
            this._pipelineProgress = data.pipeline_progress || this._pipelineProgress;
            this.render();
        });
    }

    /**
     * Set the session to display pipeline progress for.
     * @param {Object} session - LabletSession object with pipeline_progress
     */
    setSession(session) {
        this._session = session;
        this._pipelineProgress = session?.pipeline_progress || {};
        this._executionHistory = [];
        this._historyLoaded = false;
        this._expandedPipeline = this._detectActivePipeline();
        this.render();
    }

    /**
     * Refresh pipeline_progress from the session (called when SSE updates arrive).
     */
    _refreshProgressFromStore() {
        if (!this._session) return;
        // The sseAdapter merges progress into the lablets store; we re-read
        // from the session's pipeline_progress (which SessionDetailPage keeps in sync)
        // For now, rely on render() being called by the parent after store update.
    }

    /**
     * Detect which pipeline is currently active (has in_progress steps).
     */
    _detectActivePipeline() {
        for (const [pipelineName, steps] of Object.entries(this._pipelineProgress)) {
            const stepValues = Object.values(steps || {});
            if (stepValues.some(s => s.status === 'in_progress' || s.status === 'pending')) {
                return pipelineName;
            }
        }
        // Fallback: most recent pipeline
        const names = Object.keys(this._pipelineProgress);
        return names.length > 0 ? names[names.length - 1] : null;
    }

    // ==========================================================================
    // Rendering
    // ==========================================================================

    render() {
        if (!this._session) {
            this.innerHTML = '';
            return;
        }

        const status = (this._session.status || 'unknown').toLowerCase();
        const hasPipelines = Object.keys(this._pipelineProgress).length > 0;

        this.innerHTML = `
            <div class="pipeline-progress-panel">
                <!-- Lifecycle Rail — HERO element -->
                ${this._renderLifecycleRail(status)}

                <!-- Active Pipeline Steps -->
                ${hasPipelines ? this._renderPipelineSection() : this._renderNoPipelines(status)}

                <!-- Execution History (collapsible) -->
                ${hasPipelines ? this._renderHistoryToggle() : ''}
            </div>
        `;

        this._bindInteractions();
        this._injectStyles();
    }

    /**
     * Render the lifecycle phase rail — a horizontal stepper showing progress
     * through the session lifecycle.
     */
    _renderLifecycleRail(currentStatus) {
        const currentIndex = LIFECYCLE_PHASES.findIndex(p => p.key === currentStatus);
        const isTerminal = ['terminated', 'expired'].includes(currentStatus);

        const phases = LIFECYCLE_PHASES.map((phase, idx) => {
            let stateClass = 'phase-future';
            let dotClass = 'bg-light border text-muted';
            let labelClass = 'text-muted';
            let iconExtra = '';

            if (isTerminal) {
                // Everything is dimmed for terminal states
                stateClass = 'phase-terminal';
                dotClass = 'bg-light border text-muted';
            } else if (idx < currentIndex) {
                // Completed phases
                stateClass = 'phase-completed';
                dotClass = 'bg-success text-white border-0';
                labelClass = 'text-success';
            } else if (idx === currentIndex) {
                // Current phase
                stateClass = 'phase-current';
                dotClass = 'bg-primary text-white border-0 shadow-sm';
                labelClass = 'text-primary fw-semibold';
                iconExtra = PHASE_PIPELINE_MAP[phase.key] ? ' pulse-dot' : '';
            }

            // Connector line between phases
            const connectorHtml = idx < LIFECYCLE_PHASES.length - 1
                ? `<div class="phase-connector ${idx < currentIndex ? 'connector-done' : 'connector-pending'}"></div>`
                : '';

            // Pipeline indicator dot for phases that have an associated pipeline
            const hasPipeline = PHASE_PIPELINE_MAP[phase.key];
            const pipelineIndicator = hasPipeline && !isTerminal
                ? `<div class="pipeline-indicator" title="Runs ${hasPipeline} pipeline"><i class="bi bi-lightning-charge-fill small"></i></div>`
                : '';

            return `
                <div class="phase-step ${stateClass}" data-phase="${phase.key}">
                    <div class="phase-dot ${dotClass}${iconExtra}">
                        <i class="${phase.icon}"></i>
                    </div>
                    <div class="phase-label ${labelClass}">${phase.label}</div>
                    ${pipelineIndicator}
                    ${connectorHtml}
                </div>
            `;
        }).join('');

        // Terminal badge
        const terminalBadge = isTerminal
            ? `<div class="d-flex align-items-center ms-3">
                   <lcm-status-badge status="${currentStatus}" icon pill></lcm-status-badge>
               </div>`
            : '';

        return `
            <div class="lifecycle-rail-container mb-3">
                <div class="d-flex align-items-center mb-2">
                    <h6 class="mb-0 text-muted small text-uppercase">
                        <i class="bi bi-arrow-right-circle me-1"></i>Lifecycle
                    </h6>
                    ${terminalBadge}
                </div>
                <div class="lifecycle-rail d-flex align-items-start">
                    ${phases}
                </div>
            </div>
        `;
    }

    /**
     * Render the pipeline section — tabs for each pipeline + step pills.
     */
    _renderPipelineSection() {
        const pipelineNames = Object.keys(this._pipelineProgress);
        const activePipeline = this._expandedPipeline || pipelineNames[0];

        // Pipeline tabs
        const tabs = pipelineNames.map(name => {
            const steps = Object.values(this._pipelineProgress[name] || {});
            const summary = this._computeSummary(steps);
            const isActive = name === activePipeline;
            const tabClass = isActive ? 'btn-primary' : 'btn-outline-secondary';
            const statusIcon = this._getPipelineStatusIcon(summary);

            return `
                <button class="btn btn-sm ${tabClass} pipeline-tab" data-pipeline="${this._escapeHtml(name)}">
                    ${statusIcon}
                    ${this._formatPipelineName(name)}
                    <span class="badge bg-white bg-opacity-25 text-dark ms-1">${summary.completed}/${summary.total}</span>
                </button>
            `;
        }).join('');

        // Active pipeline step pills
        const stepsHtml = this._renderStepPills(activePipeline);

        return `
            <div class="pipeline-section mb-3">
                <div class="d-flex align-items-center gap-2 mb-2 flex-wrap">
                    <span class="small text-muted text-uppercase fw-semibold">
                        <i class="bi bi-lightning-charge me-1"></i>Pipelines
                    </span>
                    <div class="d-flex gap-1 flex-wrap">${tabs}</div>
                </div>
                <div class="pipeline-steps-container" id="pipeline-steps">
                    ${stepsHtml}
                </div>
            </div>
        `;
    }

    /**
     * Render step pills for a given pipeline — the detailed step-by-step view.
     */
    _renderStepPills(pipelineName) {
        const steps = this._pipelineProgress[pipelineName];
        if (!steps || Object.keys(steps).length === 0) {
            return `<div class="text-muted small py-2"><i class="bi bi-info-circle me-1"></i>No steps reported yet.</div>`;
        }

        // Sort steps by order (if available), then by name
        const sortedSteps = Object.entries(steps).sort(([, a], [, b]) => {
            const orderA = a.order ?? 999;
            const orderB = b.order ?? 999;
            return orderA - orderB;
        });

        const pills = sortedSteps.map(([stepName, stepData]) => {
            const status = stepData.status || 'pending';
            const config = STEP_STATUS_CONFIG[status] || STEP_STATUS_CONFIG.pending;
            const displayName = this._formatStepName(stepName);

            // Tooltip with details
            let tooltip = `${displayName}: ${config.label}`;
            if (stepData.error) tooltip += ` — ${stepData.error}`;
            if (stepData.skip_reason) tooltip += ` — ${stepData.skip_reason}`;

            return `
                <div class="step-pill ${config.bgClass} rounded px-2 py-1 d-flex align-items-center gap-1"
                     title="${this._escapeHtml(tooltip)}"
                     data-step="${this._escapeHtml(stepName)}"
                     data-status="${status}">
                    <i class="${config.icon} small"></i>
                    <span class="small">${this._escapeHtml(displayName)}</span>
                </div>
            `;
        }).join('');

        // Summary bar
        const allSteps = sortedSteps.map(([, s]) => s);
        const summary = this._computeSummary(allSteps);

        return `
            <div class="d-flex flex-wrap gap-2 mb-2">${pills}</div>
            ${this._renderProgressBar(summary)}
        `;
    }

    /**
     * Render a compact progress bar for pipeline step completion.
     */
    _renderProgressBar(summary) {
        if (summary.total === 0) return '';
        const pct = Math.round((summary.completed / summary.total) * 100);
        const failPct = Math.round((summary.failed / summary.total) * 100);
        const skipPct = Math.round((summary.skipped / summary.total) * 100);
        const progressPct = Math.round((summary.in_progress / summary.total) * 100);

        return `
            <div class="progress mb-1" style="height: 6px;">
                <div class="progress-bar bg-success" style="width: ${pct}%" title="${summary.completed} completed"></div>
                <div class="progress-bar bg-primary progress-bar-striped progress-bar-animated" style="width: ${progressPct}%" title="${summary.in_progress} in progress"></div>
                <div class="progress-bar bg-danger" style="width: ${failPct}%" title="${summary.failed} failed"></div>
                <div class="progress-bar bg-warning" style="width: ${skipPct}%" title="${summary.skipped} skipped"></div>
            </div>
            <div class="d-flex justify-content-between">
                <small class="text-muted">${pct}% complete</small>
                <small class="text-muted">
                    ${summary.completed}✓
                    ${summary.failed > 0 ? ` ${summary.failed}✗` : ''}
                    ${summary.skipped > 0 ? ` ${summary.skipped}⟳` : ''}
                    ${summary.in_progress > 0 ? ` ${summary.in_progress}⟳` : ''}
                     / ${summary.total}
                </small>
            </div>
        `;
    }

    /**
     * Render when no pipelines have reported progress yet.
     */
    _renderNoPipelines(status) {
        const activePhases = ['instantiating', 'collecting', 'grading', 'stopping'];
        if (activePhases.includes(status)) {
            return `
                <div class="text-muted small py-2 d-flex align-items-center gap-2">
                    <span class="spinner-border spinner-border-sm"></span>
                    Waiting for pipeline progress…
                </div>
            `;
        }
        return '';
    }

    /**
     * Render the execution history toggle and content.
     */
    _renderHistoryToggle() {
        const chevron = this._historyVisible ? 'bi-chevron-up' : 'bi-chevron-down';
        const historyContent = this._historyVisible
            ? this._renderExecutionHistory()
            : '';

        return `
            <div class="history-section mt-2">
                <button class="btn btn-link btn-sm text-muted text-decoration-none p-0" id="toggle-history">
                    <i class="${chevron} me-1"></i>
                    <small>Execution History</small>
                </button>
                <div id="history-content" class="${this._historyVisible ? '' : 'd-none'}">
                    ${historyContent}
                </div>
            </div>
        `;
    }

    /**
     * Render the execution history table.
     */
    _renderExecutionHistory() {
        if (!this._historyLoaded) {
            return `
                <div class="text-center py-2">
                    <span class="spinner-border spinner-border-sm text-muted"></span>
                    <small class="text-muted ms-1">Loading history…</small>
                </div>
            `;
        }

        if (this._executionHistory.length === 0) {
            return `<div class="text-muted small py-2"><i class="bi bi-clock-history me-1"></i>No execution records yet.</div>`;
        }

        const rows = this._executionHistory.map(exec => {
            const started = exec.started_at ? this._formatDate(exec.started_at) : '—';
            const duration = exec.duration_seconds != null
                ? `${Math.round(exec.duration_seconds)}s`
                : '—';
            const statusColor = exec.status === 'completed' ? 'success'
                : exec.status === 'failed' ? 'danger'
                : exec.status === 'running' ? 'primary'
                : 'secondary';

            return `
                <tr>
                    <td class="small">${this._escapeHtml(this._formatPipelineName(exec.pipeline_name))}</td>
                    <td class="text-center"><span class="badge bg-${statusColor}">${exec.status}</span></td>
                    <td class="text-center small">#${exec.attempt || 1}</td>
                    <td class="small">${started}</td>
                    <td class="text-center small">${duration}</td>
                    <td class="text-center small">${exec.steps_completed || 0}/${exec.steps_total || 0}</td>
                    <td class="small text-truncate" style="max-width: 150px;" title="${this._escapeHtml(exec.error || '')}">${exec.error ? this._escapeHtml(exec.error) : '—'}</td>
                </tr>
            `;
        }).join('');

        return `
            <div class="table-responsive mt-2">
                <table class="table table-sm table-bordered mb-0">
                    <thead class="table-light">
                        <tr>
                            <th>Pipeline</th>
                            <th class="text-center">Status</th>
                            <th class="text-center">Attempt</th>
                            <th>Started</th>
                            <th class="text-center">Duration</th>
                            <th class="text-center">Steps</th>
                            <th>Error</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        `;
    }

    // ==========================================================================
    // Interactions
    // ==========================================================================

    _bindInteractions() {
        // Pipeline tab clicks
        this.querySelectorAll('.pipeline-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                this._expandedPipeline = tab.dataset.pipeline;
                this.render();
            });
        });

        // History toggle
        this.querySelector('#toggle-history')?.addEventListener('click', async () => {
            this._historyVisible = !this._historyVisible;
            if (this._historyVisible && !this._historyLoaded) {
                this.render(); // Show spinner
                await this._loadExecutionHistory();
                this.render(); // Show results
            } else {
                this.render();
            }
        });

        // Step pill clicks — show detail tooltip/popover (future enhancement)
        this.querySelectorAll('.step-pill[data-status="failed"]').forEach(pill => {
            pill.style.cursor = 'pointer';
            pill.addEventListener('click', () => {
                const stepName = pill.dataset.step;
                const pipelineName = this._expandedPipeline || Object.keys(this._pipelineProgress)[0];
                const stepData = this._pipelineProgress[pipelineName]?.[stepName];
                if (stepData?.error) {
                    // Flash error as toast for quick visibility
                    const { showToast } = window.__lcmUI || {};
                    if (showToast) {
                        showToast(`Step "${stepName}" error: ${stepData.error}`, 'error', 8000);
                    }
                }
            });
        });
    }

    /**
     * Load execution history from API.
     */
    async _loadExecutionHistory() {
        if (!this._session?.id) return;
        try {
            const data = await listPipelineExecutions(this._session.id, { limit: 20 });
            this._executionHistory = Array.isArray(data) ? data : data.items || [];
            this._historyLoaded = true;
        } catch (error) {
            console.error('[PipelineProgressPanel] Failed to load execution history:', error);
            this._executionHistory = [];
            this._historyLoaded = true;
        }
    }

    // ==========================================================================
    // Helpers
    // ==========================================================================

    /**
     * Compute summary counts from an array of step objects.
     */
    _computeSummary(steps) {
        const summary = { total: steps.length, completed: 0, failed: 0, skipped: 0, in_progress: 0, pending: 0 };
        for (const step of steps) {
            const s = step.status || 'pending';
            if (s in summary) summary[s]++;
        }
        summary.pending = summary.total - summary.completed - summary.failed - summary.skipped - summary.in_progress;
        return summary;
    }

    /**
     * Get a status icon for a pipeline based on its summary.
     */
    _getPipelineStatusIcon(summary) {
        if (summary.failed > 0) return '<i class="bi bi-exclamation-circle-fill text-danger me-1"></i>';
        if (summary.in_progress > 0) return '<i class="bi bi-arrow-repeat spin-slow me-1"></i>';
        if (summary.completed === summary.total && summary.total > 0) return '<i class="bi bi-check-circle-fill text-success me-1"></i>';
        return '<i class="bi bi-circle text-muted me-1"></i>';
    }

    /**
     * Format a pipeline_name into a human-readable label.
     * "instantiate" → "Instantiate", "collect_evidence" → "Collect Evidence"
     */
    _formatPipelineName(name) {
        if (!name) return 'Unknown';
        return name
            .replace(/_/g, ' ')
            .replace(/\b\w/g, c => c.toUpperCase());
    }

    /**
     * Format a step_name into a human-readable label.
     * "create_lab" → "Create Lab"
     */
    _formatStepName(name) {
        if (!name) return 'Unknown';
        return name
            .replace(/_/g, ' ')
            .replace(/\b\w/g, c => c.toUpperCase());
    }

    _formatDate(dateStr) {
        if (!dateStr) return '—';
        try {
            const date = new Date(dateStr);
            return date.toLocaleString(undefined, {
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
            });
        } catch {
            return dateStr;
        }
    }

    _escapeHtml(str) {
        if (str == null) return '';
        const div = document.createElement('div');
        div.textContent = String(str);
        return div.innerHTML;
    }

    /**
     * Inject component-scoped styles (idempotent).
     */
    _injectStyles() {
        if (document.getElementById('pipeline-progress-panel-styles')) return;
        const style = document.createElement('style');
        style.id = 'pipeline-progress-panel-styles';
        style.textContent = `
            .lifecycle-rail {
                overflow-x: auto;
                padding-bottom: 4px;
            }

            .phase-step {
                display: flex;
                flex-direction: column;
                align-items: center;
                position: relative;
                min-width: 64px;
                flex-shrink: 0;
            }

            .phase-dot {
                width: 32px;
                height: 32px;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 0.75rem;
                z-index: 1;
                transition: all 0.3s ease;
            }

            .phase-label {
                font-size: 0.65rem;
                margin-top: 4px;
                white-space: nowrap;
            }

            .phase-connector {
                position: absolute;
                top: 16px;
                left: calc(50% + 16px);
                width: calc(100% - 32px);
                height: 2px;
                z-index: 0;
            }

            .connector-done {
                background: var(--bs-success);
            }

            .connector-pending {
                background: var(--bs-border-color);
            }

            .pipeline-indicator {
                font-size: 0.55rem;
                color: var(--bs-primary);
                margin-top: 1px;
            }

            .pulse-dot {
                animation: pulse-ring 2s ease-in-out infinite;
            }

            @keyframes pulse-ring {
                0% { box-shadow: 0 0 0 0 rgba(var(--bs-primary-rgb), 0.4); }
                70% { box-shadow: 0 0 0 6px rgba(var(--bs-primary-rgb), 0); }
                100% { box-shadow: 0 0 0 0 rgba(var(--bs-primary-rgb), 0); }
            }

            .step-pill {
                cursor: default;
                transition: transform 0.15s ease;
                border: 1px solid transparent;
            }

            .step-pill:hover {
                transform: translateY(-1px);
                border-color: var(--bs-border-color);
            }

            .step-pill[data-status="failed"] {
                cursor: pointer;
            }
        `;
        document.head.appendChild(style);
    }
}

// Register custom element
if (!customElements.get('pipeline-progress-panel')) {
    customElements.define('pipeline-progress-panel', PipelineProgressPanel);
}

export default PipelineProgressPanel;
