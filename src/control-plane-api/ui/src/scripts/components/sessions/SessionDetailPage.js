/**
 * SessionDetailPage — Phase 7J
 *
 * Detail view for a single LabletSession.
 * Shows session summary, state transition actions (AD-P7-06),
 * and child entity info (UserSession, GradingSession, ScoreReport).
 *
 * Phase 7J: Migrated from LabletInstance+LabletRecordRun to LabletSession.
 * Manual action buttons replace CloudEvent automation (deferred per AD-P7-06).
 *
 * Usage:
 *   <session-detail-page></session-detail-page>
 *   // then: element.loadSession(sessionId)
 *
 * @module components/sessions/SessionDetailPage
 */

import { BaseComponent } from '../../core/BaseComponent.js';
import { EventTypes } from '../../core/EventBus.js';
import * as bootstrap from 'bootstrap';
import * as sessionsApi from '../../api/sessions.js';
import { transitionLabletSession, terminateLabletSession, requestResourceObservation } from '../../api/lablet-sessions.js';
import { previewPlacement } from '../../api/scheduler.js';
import { showToast } from '../../ui/notifications.js';
import { showConfirmAsync } from '../modals.js';
import { showPlacementPreviewModal } from '../PlacementPreviewModal.js';
import '../core/LcmStatusBadge.js';

export class SessionDetailPage extends BaseComponent {
    constructor() {
        super();
        this._session = null;
        this._isLoading = false;
    }

    onMount() {
        this.render();

        // Subscribe to real-time updates for the displayed session
        this.subscribe(EventTypes.LABLET_SESSION_STATUS_CHANGED, data => {
            if (this._session && (data.session_id === this._session.id || data.id === this._session.id)) {
                this._session = {
                    ...this._session,
                    status: data.status || data.new_status,
                    updated_at: data.updated_at,
                };
                this.render();
            }
        });

        this.subscribe(EventTypes.LABLET_SESSION_SNAPSHOT, data => {
            if (this._session && data.id === this._session.id) {
                this._session = { ...this._session, ...data };
                this.render();
            }
        });
    }

    /**
     * Load and display a session by ID
     * @param {string} sessionId - LabletInstance ID
     */
    async loadSession(sessionId) {
        this._isLoading = true;
        this.render();

        try {
            const detail = await sessionsApi.getSessionDetail(sessionId);
            this._session = detail;
        } catch (error) {
            console.error('[SessionDetailPage] Failed to load session:', error);
            showToast(`Failed to load session: ${error.message}`, 'error');
            this._session = null;
        } finally {
            this._isLoading = false;
            this.render();
        }
    }

    render() {
        if (this._isLoading) {
            this.innerHTML = `
                <div class="d-flex justify-content-center align-items-center py-5">
                    <div class="spinner-border text-primary" role="status">
                        <span class="visually-hidden">Loading session...</span>
                    </div>
                </div>
            `;
            return;
        }

        if (!this._session) {
            this.innerHTML = `
                <div class="text-center text-muted py-5">
                    <i class="bi bi-exclamation-circle fs-1 d-block mb-2"></i>
                    <p>No session selected</p>
                    <button class="btn btn-outline-primary" id="back-to-sessions">
                        <i class="bi bi-arrow-left me-1"></i>Back to Sessions
                    </button>
                </div>
            `;
            this.querySelector('#back-to-sessions')?.addEventListener('click', () => {
                this.dispatchEvent('session-back');
            });
            return;
        }

        const session = this._session;
        const status = (session.status || 'unknown').toLowerCase();
        const definitionName = session.definition_name || session.definition_id || 'Unknown';

        this.innerHTML = `
            <div class="session-detail-page">
                <!-- Header with back button -->
                <div class="d-flex justify-content-between align-items-center mb-4">
                    <div class="d-flex align-items-center gap-3">
                        <button class="btn btn-outline-secondary btn-sm" id="back-to-sessions">
                            <i class="bi bi-arrow-left me-1"></i>Back
                        </button>
                        <div>
                            <h4 class="mb-0 d-flex align-items-center gap-2">
                                <i class="bi bi-easel"></i>
                                ${this._escapeHtml(definitionName)}
                                <lcm-status-badge status="${status}" icon pill></lcm-status-badge>
                            </h4>
                            <small class="text-muted">
                                Session ID: <code>${(session.id || '').substring(0, 12)}…</code>
                                ${session.owner_id ? ` • Owner: ${this._escapeHtml(session.owner_id)}` : ''}
                            </small>
                        </div>
                    </div>
                    <button class="btn btn-outline-secondary btn-sm" id="refresh-session">
                        <i class="bi bi-arrow-clockwise me-1"></i>Refresh
                    </button>
                </div>

                <!-- Session Summary -->
                ${this._renderSessionSummary(session)}

                <!-- Manual Action Buttons (AD-P7-06) -->
                ${this._renderActionButtons(session)}

                <!-- Resource Observations (ADR-030) -->
                ${this._renderObservationPanel(session)}

                <!-- Child Entities -->
                ${this._renderChildEntities(session)}
            </div>
        `;

        this._bindInteractions();
    }

    _renderSessionSummary(session) {
        const timeslotStart = session.timeslot_start ? this._formatDate(session.timeslot_start) : 'Not set';
        const timeslotEnd = session.timeslot_end ? this._formatDate(session.timeslot_end) : 'Not set';
        const workerName = session.worker_name || session.worker_id || 'Not assigned';

        return `
            <div class="card shadow-sm mb-4">
                <div class="card-body">
                    <div class="row g-3">
                        <div class="col-md-3">
                            <div class="small text-muted mb-1">Worker</div>
                            <div><i class="bi bi-server me-1"></i>${this._escapeHtml(workerName)}</div>
                        </div>
                        <div class="col-md-3">
                            <div class="small text-muted mb-1">Timeslot Start</div>
                            <div><i class="bi bi-calendar-event me-1"></i>${timeslotStart}</div>
                        </div>
                        <div class="col-md-3">
                            <div class="small text-muted mb-1">Timeslot End</div>
                            <div><i class="bi bi-calendar-x me-1"></i>${timeslotEnd}</div>
                        </div>
                        <div class="col-md-3">
                            <div class="small text-muted mb-1">Reservation</div>
                            <div class="text-truncate small font-monospace" title="${session.reservation_id || 'N/A'}">
                                ${session.reservation_id ? session.reservation_id.substring(0, 8) + '…' : 'N/A'}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    /**
     * Render manual action buttons based on session status (AD-P7-06).
     * These replace CloudEvent-driven automation which is deferred.
     */
    _renderActionButtons(session) {
        const status = (session.status || '').toLowerCase();
        const actions = this._getAvailableActions(status);

        // Dry Run is available for any session with a definition_id (AD-SCHED-002)
        const showDryRun = !!session.definition_id;

        if (actions.length === 0 && !showDryRun) return '';

        const buttons = actions
            .map(a => {
                if (a.action === 'terminate') {
                    return `<button class="btn ${a.btnClass}" data-action="terminate" title="${a.label}">
                    <i class="${a.icon} me-1"></i>${a.label}
                </button>`;
                }
                return `<button class="btn ${a.btnClass}" data-action="transition" data-target="${a.target}" title="${a.label}">
                <i class="${a.icon} me-1"></i>${a.label}
            </button>`;
            })
            .join('');

        const dryRunButton = showDryRun
            ? `<button class="btn btn-outline-info" data-action="dry-run" title="Preview the Placement algorithm">
                <i class="bi bi-cpu me-1"></i>Dry Run
                <i class="bi bi-info-circle ms-1 small" data-bs-toggle="tooltip" data-bs-placement="top" title="Preview the Placement algorithm — shows candidate workers, rejection reasons, and resource utilization forecast without making any changes"></i>
            </button>`
            : '';

        return `
            <div class="card shadow-sm mb-4">
                <div class="card-header bg-white">
                    <h6 class="mb-0"><i class="bi bi-gear me-1"></i>Session Actions</h6>
                </div>
                <div class="card-body">
                    <div class="d-flex gap-2 flex-wrap">
                        ${buttons}
                        ${dryRunButton}
                    </div>
                </div>
            </div>
        `;
    }

    _getAvailableActions(status) {
        const actionMap = {
            ready: [
                { action: 'transition', target: 'RUNNING', label: 'Start Session', icon: 'bi-play-fill', btnClass: 'btn-success' },
                { action: 'terminate', label: 'Terminate', icon: 'bi-x-circle', btnClass: 'btn-outline-danger' },
            ],
            running: [
                { action: 'transition', target: 'COLLECTING', label: 'Finish Session', icon: 'bi-stop-fill', btnClass: 'btn-warning' },
                { action: 'terminate', label: 'Terminate', icon: 'bi-x-circle', btnClass: 'btn-outline-danger' },
            ],
            collecting: [
                { action: 'transition', target: 'GRADING', label: 'Start Grading', icon: 'bi-clipboard-check', btnClass: 'btn-info' },
                { action: 'transition', target: 'STOPPING', label: 'Skip Grading', icon: 'bi-skip-forward', btnClass: 'btn-outline-secondary' },
            ],
            grading: [
                { action: 'transition', target: 'STOPPING', label: 'Complete Grading', icon: 'bi-check-circle', btnClass: 'btn-success' },
                { action: 'terminate', label: 'Terminate', icon: 'bi-x-circle', btnClass: 'btn-outline-danger' },
            ],
            stopped: [{ action: 'transition', target: 'ARCHIVED', label: 'Archive', icon: 'bi-archive', btnClass: 'btn-outline-secondary' }],
        };
        return actionMap[status] || [];
    }

    /**
     * Render resource observation panel (ADR-030).
     * Shows observed resources, port comparison table, drift badge,
     * and "Observe Now" button for RUNNING sessions.
     */
    _renderObservationPanel(session) {
        const status = (session.status || '').toLowerCase();
        const canObserve = status === 'running';
        const hasObs = !!session.observed_resources;
        const driftDetected = session.port_drift_detected || false;
        const obsCount = session.observation_count || 0;

        // Port comparison table
        let portTableHtml = '';
        if (hasObs) {
            const allocated = session.allocated_ports || {};
            const observed = session.observed_ports || {};
            const allPorts = new Set([...Object.keys(allocated), ...Object.keys(observed)]);

            if (allPorts.size > 0) {
                const rows = [...allPorts]
                    .sort()
                    .map(name => {
                        const alloc = allocated[name];
                        const obs = observed[name];
                        let statusIcon = '✓';
                        let statusClass = 'text-success';
                        if (alloc == null) {
                            statusIcon = '⚠ ADD';
                            statusClass = 'text-warning fw-bold';
                        } else if (obs == null) {
                            statusIcon = '⚠ REM';
                            statusClass = 'text-danger fw-bold';
                        } else if (alloc !== obs) {
                            statusIcon = '⚠ CHG';
                            statusClass = 'text-warning fw-bold';
                        }
                        return `<tr>
                        <td class="font-monospace small">${this._escapeHtml(name)}</td>
                        <td class="text-center">${alloc != null ? alloc : '—'}</td>
                        <td class="text-center">${obs != null ? obs : '—'}</td>
                        <td class="text-center ${statusClass}">${statusIcon}</td>
                    </tr>`;
                    })
                    .join('');

                portTableHtml = `
                    <div class="mt-3">
                        <h6 class="small text-muted mb-2">Port Allocation Comparison
                            ${driftDetected ? '<span class="badge bg-warning text-dark ms-2">⚠️ Drift Detected</span>' : ''}
                        </h6>
                        <div class="table-responsive">
                            <table class="table table-sm table-bordered mb-0">
                                <thead class="table-light">
                                    <tr>
                                        <th>Port Name</th>
                                        <th class="text-center">Allocated</th>
                                        <th class="text-center">Observed</th>
                                        <th class="text-center">Status</th>
                                    </tr>
                                </thead>
                                <tbody>${rows}</tbody>
                            </table>
                        </div>
                    </div>
                `;
            }
        }

        // Observed resources summary
        let obsSummary = '';
        if (hasObs) {
            const obs = session.observed_resources;
            const nodeDefs = (obs.node_definitions_used || []).join(', ') || '—';
            const obsTime = session.observed_at ? this._formatDate(session.observed_at) : '—';

            obsSummary = `
                <div class="mb-2">
                    <small class="text-muted">
                        ${obsCount} observation${obsCount !== 1 ? 's' : ''} recorded • Last: ${obsTime}
                    </small>
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
                <div class="small text-muted mb-1">
                    <i class="bi bi-diagram-3 me-1"></i>Node defs: ${this._escapeHtml(nodeDefs)}
                </div>
            `;
        } else {
            obsSummary = `
                <div class="text-muted small py-2">
                    <i class="bi bi-eye-slash me-1"></i>No resource observations recorded yet.
                    ${canObserve ? 'Click "Observe Now" to capture live CML resources.' : ''}
                </div>
            `;
        }

        return `
            <div class="card shadow-sm mb-4">
                <div class="card-header bg-white d-flex justify-content-between align-items-center">
                    <h6 class="mb-0"><i class="bi bi-binoculars me-1"></i>Resource Observations</h6>
                    ${
                        canObserve
                            ? `
                        <button class="btn btn-outline-primary btn-sm" id="observe-now-btn">
                            <i class="bi bi-eye me-1"></i>Observe Now
                        </button>
                    `
                            : ''
                    }
                </div>
                <div class="card-body">
                    ${obsSummary}
                    ${portTableHtml}
                </div>
            </div>
        `;
    }

    /**
     * Render child entity info (UserSession, GradingSession, ScoreReport).
     */
    _renderChildEntities(session) {
        const sections = [];

        // UserSession info
        if (session.user_session_id || session.cml_lab_id) {
            sections.push(`
                <div class="card shadow-sm mb-3">
                    <div class="card-header bg-white">
                        <h6 class="mb-0"><i class="bi bi-person-badge me-1"></i>User Session</h6>
                    </div>
                    <div class="card-body">
                        <div class="row g-3">
                            ${
                                session.user_session_id
                                    ? `
                                <div class="col-md-6">
                                    <div class="small text-muted">Session ID</div>
                                    <div class="font-monospace small">${this._escapeHtml(session.user_session_id)}</div>
                                </div>
                            `
                                    : ''
                            }
                            ${
                                session.cml_lab_id
                                    ? `
                                <div class="col-md-6">
                                    <div class="small text-muted">CML Lab</div>
                                    <div><i class="bi bi-hdd-network me-1"></i>${this._escapeHtml(session.cml_lab_id)}</div>
                                </div>
                            `
                                    : ''
                            }
                        </div>
                    </div>
                </div>
            `);
        }

        // GradingSession info (placeholder for Phase 8)
        if (session.grading_session_id) {
            sections.push(`
                <div class="card shadow-sm mb-3">
                    <div class="card-header bg-white">
                        <h6 class="mb-0"><i class="bi bi-clipboard-check me-1"></i>Grading Session</h6>
                    </div>
                    <div class="card-body">
                        <div class="font-monospace small">${this._escapeHtml(session.grading_session_id)}</div>
                    </div>
                </div>
            `);
        }

        // ScoreReport info (placeholder for Phase 8)
        if (session.score != null) {
            sections.push(`
                <div class="card shadow-sm mb-3">
                    <div class="card-header bg-white">
                        <h6 class="mb-0"><i class="bi bi-trophy me-1"></i>Score Report</h6>
                    </div>
                    <div class="card-body">
                        <h3>${session.score}${session.max_score ? ` / ${session.max_score}` : ''}</h3>
                    </div>
                </div>
            `);
        }

        if (sections.length === 0) return '';

        return `
            <h5 class="mb-3"><i class="bi bi-diagram-3 me-1"></i>Session Details</h5>
            ${sections.join('')}
        `;
    }

    _bindInteractions() {
        this.querySelector('#back-to-sessions')?.addEventListener('click', () => {
            this.dispatchEvent('session-back');
        });

        this.querySelector('#refresh-session')?.addEventListener('click', () => {
            if (this._session?.id) {
                this.loadSession(this._session.id);
            }
        });

        // Transition buttons (AD-P7-06)
        this.querySelectorAll('[data-action="transition"]').forEach(btn => {
            btn.addEventListener('click', async () => {
                const targetStatus = btn.dataset.target;
                const label = btn.title || targetStatus;

                try {
                    btn.disabled = true;
                    const originalHtml = btn.innerHTML;
                    btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${label}`;

                    await transitionLabletSession(this._session.id, targetStatus, `User action: ${label}`);

                    showToast(`Session transitioned to ${targetStatus}`, 'success');
                    // Reload to get fresh state
                    await this.loadSession(this._session.id);
                } catch (error) {
                    console.error(`Failed to transition session to ${targetStatus}:`, error);
                    showToast(`Failed to ${label}: ${error.message}`, 'error');
                    btn.disabled = false;
                    btn.innerHTML = `<i class="${btn.querySelector('i')?.className || 'bi-arrow-right'} me-1"></i>${label}`;
                }
            });
        });

        // Dry Run button (AD-SCHED-002)
        this.querySelector('[data-action="dry-run"]')?.addEventListener('click', async () => {
            const btn = this.querySelector('[data-action="dry-run"]');
            if (!this._session?.definition_id) return;

            try {
                btn.disabled = true;
                btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Previewing…';

                const result = await previewPlacement({
                    definition_id: this._session.definition_id,
                    timeslot_start: this._session.timeslot_start || null,
                    timeslot_end: this._session.timeslot_end || null,
                });

                showPlacementPreviewModal(result, {
                    showRunButton: true,
                });
            } catch (error) {
                console.error('[SessionDetailPage] Dry run failed:', error);
                showToast(`Dry run failed: ${error.message}`, 'error');
            } finally {
                btn.disabled = false;
                btn.innerHTML = '<i class="bi bi-cpu me-1"></i>Dry Run <i class="bi bi-info-circle ms-1 small"></i>';
            }
        });

        // Initialize Bootstrap tooltips for info icons
        this.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => {
            new bootstrap.Tooltip(el);
        });

        // Observe Now button (ADR-030)
        this.querySelector('#observe-now-btn')?.addEventListener('click', async () => {
            const btn = this.querySelector('#observe-now-btn');
            if (!this._session?.id) return;

            try {
                btn.disabled = true;
                btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Observing…';

                await requestResourceObservation(this._session.id);

                showToast('Resource observation requested. Results will appear shortly.', 'info');
                // Reload after a short delay to pick up results
                setTimeout(() => this.loadSession(this._session.id), 3000);
            } catch (error) {
                console.error('[SessionDetailPage] Observe resources failed:', error);
                showToast(`Observation failed: ${error.message}`, 'error');
            } finally {
                btn.disabled = false;
                btn.innerHTML = '<i class="bi bi-eye me-1"></i>Observe Now';
            }
        });

        // Terminate button
        this.querySelector('[data-action="terminate"]')?.addEventListener('click', async () => {
            const btn = this.querySelector('[data-action="terminate"]');
            const confirmed = await showConfirmAsync('Terminate Session', `Are you sure you want to terminate session "${this._session.definition_name || this._session.id}"?`, { actionLabel: 'Terminate', actionClass: 'btn-danger' });
            if (!confirmed) return;

            try {
                btn.disabled = true;
                btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Terminating...';

                await terminateLabletSession(this._session.id, 'User requested termination');

                showToast('Session terminated', 'success');
                await this.loadSession(this._session.id);
            } catch (error) {
                console.error('Failed to terminate session:', error);
                showToast(`Failed to terminate: ${error.message}`, 'error');
                btn.disabled = false;
                btn.innerHTML = '<i class="bi bi-x-circle me-1"></i>Terminate';
            }
        });
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
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }
}

if (!customElements.get('session-detail-page')) {
    customElements.define('session-detail-page', SessionDetailPage);
}

export default SessionDetailPage;
