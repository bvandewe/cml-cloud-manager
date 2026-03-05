/**
 * LabletSessionCard Component — Phase 7J
 *
 * Self-contained lablet session card with:
 * - Reactive updates via EventBus
 * - Manual action buttons for state transitions (AD-P7-06)
 * - Encapsulated rendering
 * - No global state dependencies
 *
 * Replaces LabletInstanceCard.js (Phase 7 entity model migration).
 *
 * Usage:
 *   <lablet-session-card session-id="abc123"></lablet-session-card>
 */

import { BaseComponent } from '../core/BaseComponent.js';
import { EventTypes } from '../core/EventBus.js';
import { showConfirmAsync } from './modals.js';
import { escapeHtml } from './escape.js';
import { getLabletSessionStatusBadgeClass, getLabletSessionStatusIcon } from './status-badges.js';
import { formatDateWithRelative, formatDuration } from '../utils/dates.js';
import * as bootstrap from 'bootstrap';

/**
 * Manual action button definitions per session status (AD-P7-06).
 * Maps session status → available actions with button config.
 */
const SESSION_ACTIONS = {
    ready: [
        { action: 'transition', target: 'RUNNING', label: 'Start Session', icon: 'bi-play-fill', btnClass: 'btn-outline-success' },
        { action: 'terminate', label: 'Terminate', icon: 'bi-x-circle', btnClass: 'btn-outline-danger' },
    ],
    running: [
        { action: 'transition', target: 'COLLECTING', label: 'Finish Session', icon: 'bi-stop-fill', btnClass: 'btn-outline-warning' },
        { action: 'terminate', label: 'Terminate', icon: 'bi-x-circle', btnClass: 'btn-outline-danger' },
    ],
    collecting: [
        { action: 'transition', target: 'GRADING', label: 'Start Grading', icon: 'bi-clipboard-check', btnClass: 'btn-outline-info' },
        { action: 'transition', target: 'STOPPING', label: 'Skip Grading', icon: 'bi-skip-forward', btnClass: 'btn-outline-secondary' },
    ],
    grading: [
        { action: 'transition', target: 'STOPPING', label: 'Complete Grading', icon: 'bi-check-circle', btnClass: 'btn-outline-success' },
        { action: 'terminate', label: 'Terminate', icon: 'bi-x-circle', btnClass: 'btn-outline-danger' },
    ],
    stopped: [{ action: 'transition', target: 'ARCHIVED', label: 'Archive', icon: 'bi-archive', btnClass: 'btn-outline-secondary' }],
};

export class LabletSessionCard extends BaseComponent {
    static get observedAttributes() {
        return ['session-id', 'compact', 'data'];
    }

    constructor() {
        super();
    }

    onAttributeChange(name, oldValue, newValue) {
        if (name === 'data' && newValue && newValue !== oldValue) {
            try {
                const session = JSON.parse(newValue);
                this.setState({ session });
            } catch (e) {
                console.error('LabletSessionCard: Invalid data attribute', e);
            }
        }
    }

    onMount() {
        const sessionId = this.getAttr('session-id');
        if (!sessionId) {
            console.error('LabletSessionCard: session-id attribute is required');
            return;
        }

        // Check for initial data
        const dataAttr = this.getAttr('data');
        if (dataAttr) {
            try {
                const session = JSON.parse(dataAttr);
                this.setState({ session });
            } catch (e) {
                console.error('LabletSessionCard: Invalid initial data', e);
            }
        }

        // Subscribe to session updates
        this.subscribe(EventTypes.LABLET_SESSION_SNAPSHOT, data => {
            const id = data.id || data.session_id;
            if (id === sessionId) {
                this.setState({ session: data });
            }
        });

        this.subscribe(EventTypes.LABLET_SESSION_STATUS_CHANGED, data => {
            if (data.session_id === sessionId || data.id === sessionId) {
                this.setState(prevState => ({
                    session: {
                        ...prevState.session,
                        status: data.status || data.new_status,
                        updated_at: data.updated_at,
                    },
                }));
            }
        });

        this.subscribe(EventTypes.LABLET_SESSION_UPDATED, data => {
            if (data.id === sessionId || data.session_id === sessionId) {
                this.setState(prevState => ({
                    session: { ...prevState.session, ...data },
                }));
            }
        });

        this.subscribe(EventTypes.LABLET_SESSION_DELETED, data => {
            if (data.session_id === sessionId || data.id === sessionId) {
                this.remove();
            }
        });

        this.subscribe(EventTypes.LABLET_SESSION_TERMINATED, data => {
            if (data.session_id === sessionId || data.id === sessionId) {
                this.setState(prevState => ({
                    session: {
                        ...prevState.session,
                        status: 'terminated',
                        terminated_at: data.terminated_at,
                    },
                }));
            }
        });
    }

    render() {
        const session = this._state.session;
        if (!session) {
            this.innerHTML = this.renderLoading();
            return;
        }

        const isCompact = this.hasAttribute('compact');
        this.innerHTML = isCompact ? this.renderCompactCard(session) : this.renderFullCard(session);

        this.setupEventHandlers();
    }

    renderLoading() {
        return `
            <div class="card mb-3">
                <div class="card-body">
                    <div class="d-flex align-items-center">
                        <div class="spinner-border spinner-border-sm text-secondary me-2" role="status">
                            <span class="visually-hidden">Loading...</span>
                        </div>
                        <span class="text-muted">Loading session...</span>
                    </div>
                </div>
            </div>
        `;
    }

    renderFullCard(session) {
        const status = session.status || 'unknown';
        const statusBadgeClass = getLabletSessionStatusBadgeClass(status);
        const statusIcon = getLabletSessionStatusIcon(status);

        const definitionName = escapeHtml(session.definition_name || session.definition_id || 'Unknown');
        const ownerId = escapeHtml(session.owner_id || 'Unknown');
        const workerName = session.worker_id ? escapeHtml(session.worker_name || session.worker_id) : 'Not assigned';

        const timeslotStart = session.timeslot_start ? formatDateWithRelative(session.timeslot_start) : 'Not set';
        const timeslotEnd = session.timeslot_end ? formatDateWithRelative(session.timeslot_end) : 'Not set';

        const createdAt = session.created_at ? formatDateWithRelative(session.created_at) : 'Unknown';
        const updatedAt = session.updated_at ? formatDateWithRelative(session.updated_at) : 'Unknown';

        const progressHtml = this.renderProgressBar(session);
        const actionsHtml = this.renderActionButtons(session);

        return `
            <div class="card mb-3 shadow-sm lablet-session-card" data-session-id="${escapeHtml(session.id)}">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <div class="d-flex align-items-center">
                        <i class="${statusIcon} me-2 fs-5"></i>
                        <h6 class="mb-0 text-truncate" style="max-width: 200px;" title="${definitionName}">
                            ${definitionName}
                        </h6>
                    </div>
                    <span class="badge ${statusBadgeClass}">
                        ${escapeHtml(status.toUpperCase())}
                    </span>
                </div>
                <div class="card-body">
                    <div class="row mb-2">
                        <div class="col-6">
                            <small class="text-muted">Owner</small>
                            <div class="text-truncate" title="${ownerId}">
                                <i class="bi bi-person me-1"></i>${ownerId}
                            </div>
                        </div>
                        <div class="col-6">
                            <small class="text-muted">Worker</small>
                            <div class="text-truncate" title="${workerName}">
                                <i class="bi bi-server me-1"></i>${workerName}
                            </div>
                        </div>
                    </div>
                    <div class="row mb-2">
                        <div class="col-6">
                            <small class="text-muted">Start</small>
                            <div><i class="bi bi-calendar-event me-1"></i>${timeslotStart}</div>
                        </div>
                        <div class="col-6">
                            <small class="text-muted">End</small>
                            <div><i class="bi bi-calendar-x me-1"></i>${timeslotEnd}</div>
                        </div>
                    </div>
                    ${progressHtml}
                    ${
                        session.reservation_id
                            ? `
                        <div class="mb-2">
                            <small class="text-muted">Reservation ID</small>
                            <div class="text-truncate font-monospace small">
                                ${escapeHtml(session.reservation_id)}
                            </div>
                        </div>
                    `
                            : ''
                    }
                    ${session.user_session_id ? this.renderUserSession(session) : ''}
                </div>
                <div class="card-footer bg-transparent d-flex justify-content-between align-items-center">
                    <small class="text-muted" title="Updated: ${updatedAt}">
                        Created: ${createdAt}
                    </small>
                    <div class="btn-group btn-group-sm">
                        ${actionsHtml}
                    </div>
                </div>
            </div>
        `;
    }

    renderCompactCard(session) {
        const status = session.status || 'unknown';
        const statusBadgeClass = getLabletSessionStatusBadgeClass(status);
        const statusIcon = getLabletSessionStatusIcon(status);
        const definitionName = escapeHtml(session.definition_name || session.definition_id || 'Unknown');

        return `
            <div class="card mb-2 lablet-session-card-compact" data-session-id="${escapeHtml(session.id)}">
                <div class="card-body py-2 px-3">
                    <div class="d-flex justify-content-between align-items-center">
                        <div class="d-flex align-items-center">
                            <i class="${statusIcon} me-2"></i>
                            <span class="text-truncate" style="max-width: 150px;">${definitionName}</span>
                        </div>
                        <span class="badge ${statusBadgeClass} badge-sm">
                            ${escapeHtml(status)}
                        </span>
                    </div>
                </div>
            </div>
        `;
    }

    renderProgressBar(session) {
        if (!session.timeslot_start || !session.timeslot_end) return '';
        const activeStatuses = ['running', 'ready', 'collecting', 'grading'];
        if (!activeStatuses.includes((session.status || '').toLowerCase())) {
            return '';
        }

        const start = new Date(session.timeslot_start).getTime();
        const end = new Date(session.timeslot_end).getTime();
        const now = Date.now();

        const totalDuration = end - start;
        const elapsed = now - start;
        const progress = Math.min(100, Math.max(0, (elapsed / totalDuration) * 100));

        const remaining = end - now;
        const remainingText = remaining > 0 ? formatDuration(remaining) : 'Expired';

        const progressClass = progress > 90 ? 'bg-danger' : progress > 75 ? 'bg-warning' : 'bg-success';

        return `
            <div class="mb-2">
                <div class="d-flex justify-content-between small mb-1">
                    <span>Time Progress</span>
                    <span class="text-muted">${remainingText} remaining</span>
                </div>
                <div class="progress" style="height: 8px;">
                    <div class="progress-bar ${progressClass}" role="progressbar"
                         style="width: ${progress}%"
                         aria-valuenow="${progress}" aria-valuemin="0" aria-valuemax="100">
                    </div>
                </div>
            </div>
        `;
    }

    /**
     * Render UserSession info (child entity from Phase 7).
     * Shows CML lab connection info when available.
     */
    renderUserSession(session) {
        return `
            <div class="mb-2">
                <small class="text-muted d-block mb-1">
                    <i class="bi bi-person-badge me-1"></i>User Session
                </small>
                ${
                    session.cml_lab_id
                        ? `
                    <span class="badge bg-light text-dark border me-1">
                        <i class="bi bi-hdd-network me-1"></i>Lab: ${escapeHtml(session.cml_lab_id)}
                    </span>
                `
                        : ''
                }
                ${
                    session.user_session_id
                        ? `
                    <span class="font-monospace small text-muted">
                        ${escapeHtml(session.user_session_id.substring(0, 12))}…
                    </span>
                `
                        : ''
                }
            </div>
        `;
    }

    /**
     * Render action buttons based on current session status (AD-P7-06).
     * Buttons are defined in SESSION_ACTIONS map above.
     */
    renderActionButtons(session) {
        const status = (session.status || '').toLowerCase();
        const buttons = [];

        // View details button — always available
        buttons.push(`
            <button class="btn btn-outline-primary btn-sm" data-action="view" title="View Details">
                <i class="bi bi-eye"></i>
            </button>
        `);

        // Observe Resources button — RUNNING sessions only (ADR-030 UX)
        if (status === 'running') {
            buttons.push(`
                <button class="btn btn-outline-info btn-sm" data-action="observe-resources"
                        title="Observe live CML resources">
                    <i class="bi bi-binoculars"></i>
                </button>
            `);
        }

        // Status-specific action buttons (AD-P7-06)
        const actions = SESSION_ACTIONS[status] || [];
        for (const action of actions) {
            if (action.action === 'terminate') {
                buttons.push(`
                    <button class="btn ${action.btnClass} btn-sm" data-action="terminate" title="${action.label}">
                        <i class="${action.icon}"></i>
                    </button>
                `);
            } else if (action.action === 'transition') {
                buttons.push(`
                    <button class="btn ${action.btnClass} btn-sm" data-action="transition" data-target="${action.target}" title="${action.label}">
                        <i class="${action.icon}"></i> <span class="d-none d-lg-inline">${action.label}</span>
                    </button>
                `);
            }
        }

        // Terminate fallback — for non-terminal states not explicitly covered
        const terminalStates = ['terminated', 'archived', 'stopped'];
        if (!terminalStates.includes(status) && !actions.some(a => a.action === 'terminate')) {
            buttons.push(`
                <button class="btn btn-outline-danger btn-sm" data-action="terminate" title="Terminate">
                    <i class="bi bi-x-circle"></i>
                </button>
            `);
        }

        return buttons.join('');
    }

    setupEventHandlers() {
        const session = this._state.session;
        if (!session) return;

        // View details
        const viewBtn = this.querySelector('[data-action="view"]');
        if (viewBtn) {
            viewBtn.addEventListener('click', () => {
                this.emit(EventTypes.UI_MODAL_OPENED, {
                    modal: 'lablet-session-details',
                    session_id: session.id,
                    session: session,
                });
            });
        }

        // Observe Resources button (ADR-030 UX)
        const observeBtn = this.querySelector('[data-action="observe-resources"]');
        if (observeBtn) {
            observeBtn.addEventListener('click', async () => {
                try {
                    observeBtn.disabled = true;
                    observeBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

                    const { requestResourceObservation } = await import('../api/lablet-sessions.js');
                    await requestResourceObservation(session.id);

                    const { showToast } = await import('../ui/notifications.js');
                    showToast('Resource observation requested — results will appear shortly.', 'info');
                } catch (error) {
                    console.error('Failed to observe resources:', error);
                    const { showToast } = await import('../ui/notifications.js');
                    showToast(`Observation failed: ${error.message}`, 'error');
                } finally {
                    observeBtn.disabled = false;
                    observeBtn.innerHTML = '<i class="bi bi-binoculars"></i>';
                }
            });
        }

        // Transition buttons (AD-P7-06)
        this.querySelectorAll('[data-action="transition"]').forEach(btn => {
            btn.addEventListener('click', async () => {
                const targetStatus = btn.dataset.target;
                const label = btn.title || targetStatus;

                try {
                    btn.disabled = true;
                    const originalHtml = btn.innerHTML;
                    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

                    const { transitionLabletSession } = await import('../api/lablet-sessions.js');
                    await transitionLabletSession(session.id, targetStatus, `User action: ${label}`);

                    this.emit(EventTypes.LABLET_SESSION_STATUS_CHANGED, {
                        session_id: session.id,
                        status: targetStatus.toLowerCase(),
                    });
                } catch (error) {
                    console.error(`Failed to transition session to ${targetStatus}:`, error);
                    const { showToast } = await import('../ui/notifications.js');
                    showToast(`Failed to ${label}: ${error.message}`, 'error');
                } finally {
                    btn.disabled = false;
                    // Re-render to update available actions
                    this.render();
                }
            });
        });

        // Terminate
        const terminateBtn = this.querySelector('[data-action="terminate"]');
        if (terminateBtn) {
            terminateBtn.addEventListener('click', async () => {
                const confirmed = await showConfirmAsync('Terminate Session', `Are you sure you want to terminate session "${session.definition_name || session.id}"?`, { actionLabel: 'Terminate', actionClass: 'btn-danger' });
                if (!confirmed) return;

                try {
                    terminateBtn.disabled = true;
                    terminateBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

                    const { terminateLabletSession } = await import('../api/lablet-sessions.js');
                    await terminateLabletSession(session.id, 'User requested termination');

                    this.emit(EventTypes.LABLET_SESSION_TERMINATED, { session_id: session.id });
                } catch (error) {
                    console.error('Failed to terminate session:', error);
                    const { showToast } = await import('../ui/notifications.js');
                    showToast(`Failed to terminate: ${error.message}`, 'error');
                } finally {
                    terminateBtn.disabled = false;
                    terminateBtn.innerHTML = '<i class="bi bi-x-circle"></i>';
                }
            });
        }
    }

    // Utility methods
    getAttr(name) {
        return this.getAttribute(name);
    }

    hasAttribute(name) {
        return super.hasAttribute(name);
    }
}

// Register the custom element
customElements.define('lablet-session-card', LabletSessionCard);
