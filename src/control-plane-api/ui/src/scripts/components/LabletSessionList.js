/**
 * LabletSessionList Component — Phase 7J
 *
 * Container component that manages a list of LabletSessionCard components.
 * Handles filtering, pagination, and real-time updates.
 *
 * Replaces LabletInstanceList.js (Phase 7 entity model migration).
 *
 * Usage:
 *   <lablet-session-list filter-status="running"></lablet-session-list>
 */

import { BaseComponent } from '../core/BaseComponent.js';
import { EventTypes } from '../core/EventBus.js';
import { listLabletSessions, getSessionStatistics } from '../api/lablet-sessions.js';
import { escapeHtml } from './escape.js';
import './LabletSessionCard.js';

export class LabletSessionList extends BaseComponent {
    static get observedAttributes() {
        return ['filter-status', 'filter-worker', 'filter-owner', 'filter-definition', 'compact', 'limit'];
    }

    constructor() {
        super();
        this._state = {
            sessions: [],
            loading: true,
            error: null,
            filters: {},
            stats: null,
        };
    }

    onAttributeChange(name, oldValue, newValue) {
        this.loadSessions();
    }

    async onMount() {
        await this.loadSessions();

        this.subscribe(EventTypes.LABLET_SESSION_CREATED, data => {
            this.addSession(data);
        });

        this.subscribe(EventTypes.LABLET_SESSION_DELETED, data => {
            this.removeSession(data.session_id || data.id);
        });

        this.subscribe(EventTypes.LABLET_SESSION_TERMINATED, data => {
            this.updateSession(data.session_id || data.id, { status: 'terminated' });
        });

        this.subscribe(EventTypes.LABLET_SESSIONS_REFRESH_COMPLETED, () => {
            this.loadSessions();
        });

        // Periodic refresh (every 30 seconds)
        this._refreshInterval = setInterval(() => this.loadSessions(true), 30000);
    }

    onUnmount() {
        if (this._refreshInterval) {
            clearInterval(this._refreshInterval);
        }
    }

    async loadSessions(silent = false) {
        if (!silent) {
            this.setState({ loading: true, error: null });
        }

        try {
            const filters = this.getFilters();
            const [sessions, stats] = await Promise.all([listLabletSessions(filters), getSessionStatistics()]);

            this.setState({
                sessions: sessions,
                stats: stats,
                loading: false,
                error: null,
            });
        } catch (error) {
            console.error('Failed to load lablet sessions:', error);
            this.setState({
                loading: false,
                error: error.message,
            });
        }
    }

    getFilters() {
        return {
            status: this.getAttribute('filter-status') || null,
            worker_id: this.getAttribute('filter-worker') || null,
            owner_id: this.getAttribute('filter-owner') || null,
            definition_id: this.getAttribute('filter-definition') || null,
            include_terminated: this.getAttribute('include-terminated') === 'true',
            limit: parseInt(this.getAttribute('limit') || '100', 10),
        };
    }

    addSession(session) {
        this.setState(prevState => ({
            sessions: [session, ...prevState.sessions],
        }));
    }

    removeSession(sessionId) {
        this.setState(prevState => ({
            sessions: prevState.sessions.filter(s => s.id !== sessionId),
        }));
    }

    updateSession(sessionId, updates) {
        this.setState(prevState => ({
            sessions: prevState.sessions.map(s => (s.id === sessionId ? { ...s, ...updates } : s)),
        }));
    }

    render() {
        const { sessions, loading, error, stats } = this._state;
        const isCompact = this.hasAttribute('compact');

        let content;

        if (loading && sessions.length === 0) {
            content = this.renderLoading();
        } else if (error) {
            content = this.renderError(error);
        } else if (sessions.length === 0) {
            content = this.renderEmpty();
        } else {
            content = this.renderSessions(sessions, isCompact);
        }

        this.innerHTML = `
            ${stats ? this.renderStats(stats) : ''}
            ${this.renderFilters()}
            <div class="lablet-session-list-content">
                ${content}
            </div>
        `;

        this.setupEventHandlers();
    }

    renderStats(stats) {
        return `
            <div class="row mb-4">
                <div class="col-md-2">
                    <div class="card stats-card bg-primary text-white">
                        <div class="card-body py-2 px-3">
                            <div class="d-flex justify-content-between align-items-center">
                                <div>
                                    <small class="card-subtitle">Total</small>
                                    <h4 class="card-title mb-0">${stats.total}</h4>
                                </div>
                                <i class="bi bi-collection fs-3 opacity-50"></i>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-2">
                    <div class="card stats-card bg-info text-white">
                        <div class="card-body py-2 px-3">
                            <div class="d-flex justify-content-between align-items-center">
                                <div>
                                    <small class="card-subtitle">Scheduled</small>
                                    <h4 class="card-title mb-0">${stats.scheduled || 0}</h4>
                                </div>
                                <i class="bi bi-calendar-check fs-3 opacity-50"></i>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-2">
                    <div class="card stats-card bg-warning text-dark">
                        <div class="card-body py-2 px-3">
                            <div class="d-flex justify-content-between align-items-center">
                                <div>
                                    <small class="card-subtitle">Instantiating</small>
                                    <h4 class="card-title mb-0">${stats.instantiating || 0}</h4>
                                </div>
                                <i class="bi bi-gear-wide-connected fs-3 opacity-50"></i>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-2">
                    <div class="card stats-card bg-success text-white">
                        <div class="card-body py-2 px-3">
                            <div class="d-flex justify-content-between align-items-center">
                                <div>
                                    <small class="card-subtitle">Running</small>
                                    <h4 class="card-title mb-0">${stats.running || 0}</h4>
                                </div>
                                <i class="bi bi-play-circle-fill fs-3 opacity-50"></i>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-2">
                    <div class="card stats-card bg-secondary text-white">
                        <div class="card-body py-2 px-3">
                            <div class="d-flex justify-content-between align-items-center">
                                <div>
                                    <small class="card-subtitle">Pending</small>
                                    <h4 class="card-title mb-0">${stats.pending || 0}</h4>
                                </div>
                                <i class="bi bi-hourglass fs-3 opacity-50"></i>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-2">
                    <div class="card stats-card bg-dark text-white">
                        <div class="card-body py-2 px-3">
                            <div class="d-flex justify-content-between align-items-center">
                                <div>
                                    <small class="card-subtitle">Completed</small>
                                    <h4 class="card-title mb-0">${(stats.stopped || 0) + (stats.archived || 0)}</h4>
                                </div>
                                <i class="bi bi-check-circle-fill fs-3 opacity-50"></i>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    renderFilters() {
        const currentStatus = this.getAttribute('filter-status') || '';

        return `
            <div class="card mb-3">
                <div class="card-body py-2">
                    <div class="row g-2 align-items-center">
                        <div class="col-auto">
                            <label class="form-label mb-0 small">Status:</label>
                        </div>
                        <div class="col-md-2">
                            <select class="form-select form-select-sm" id="session-status-filter">
                                <option value="">All</option>
                                <option value="pending" ${currentStatus === 'pending' ? 'selected' : ''}>Pending</option>
                                <option value="scheduled" ${currentStatus === 'scheduled' ? 'selected' : ''}>Scheduled</option>
                                <option value="instantiating" ${currentStatus === 'instantiating' ? 'selected' : ''}>Instantiating</option>
                                <option value="ready" ${currentStatus === 'ready' ? 'selected' : ''}>Ready</option>
                                <option value="running" ${currentStatus === 'running' ? 'selected' : ''}>Running</option>
                                <option value="collecting" ${currentStatus === 'collecting' ? 'selected' : ''}>Collecting</option>
                                <option value="grading" ${currentStatus === 'grading' ? 'selected' : ''}>Grading</option>
                                <option value="stopping" ${currentStatus === 'stopping' ? 'selected' : ''}>Stopping</option>
                                <option value="stopped" ${currentStatus === 'stopped' ? 'selected' : ''}>Stopped</option>
                                <option value="archived" ${currentStatus === 'archived' ? 'selected' : ''}>Archived</option>
                                <option value="terminated" ${currentStatus === 'terminated' ? 'selected' : ''}>Terminated</option>
                            </select>
                        </div>
                        <div class="col-auto">
                            <div class="form-check">
                                <input type="checkbox" class="form-check-input" id="include-terminated-check"
                                       ${this.getAttribute('include-terminated') === 'true' ? 'checked' : ''}>
                                <label class="form-check-label small" for="include-terminated-check">
                                    Include Terminated
                                </label>
                            </div>
                        </div>
                        <div class="col-auto ms-auto">
                            <button class="btn btn-sm btn-outline-secondary" id="refresh-sessions-btn">
                                <i class="bi bi-arrow-clockwise"></i> Refresh
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    renderLoading() {
        return `
            <div class="d-flex justify-content-center align-items-center py-5">
                <div class="spinner-border text-primary" role="status">
                    <span class="visually-hidden">Loading sessions...</span>
                </div>
                <span class="ms-3 text-muted">Loading lablet sessions...</span>
            </div>
        `;
    }

    renderError(error) {
        return `
            <div class="alert alert-danger d-flex align-items-center" role="alert">
                <i class="bi bi-exclamation-triangle-fill me-2"></i>
                <div>
                    <strong>Error loading sessions:</strong> ${escapeHtml(error)}
                    <button class="btn btn-sm btn-outline-danger ms-3" id="retry-load-btn">
                        <i class="bi bi-arrow-clockwise"></i> Retry
                    </button>
                </div>
            </div>
        `;
    }

    renderEmpty() {
        return `
            <div class="text-center py-5">
                <i class="bi bi-inbox text-muted" style="font-size: 3rem;"></i>
                <h5 class="text-muted mt-3">No Lablet Sessions</h5>
                <p class="text-muted">
                    No sessions match your current filters.
                </p>
            </div>
        `;
    }

    renderSessions(sessions, isCompact) {
        const cards = sessions
            .map(session => {
                const dataAttr = escapeHtml(JSON.stringify(session));
                const compact = isCompact ? 'compact' : '';
                return `<lablet-session-card
                        session-id="${escapeHtml(session.id)}"
                        data='${dataAttr}'
                        ${compact}>
                    </lablet-session-card>`;
            })
            .join('');

        return isCompact
            ? `<div class="lablet-sessions-compact">${cards}</div>`
            : `<div class="row row-cols-1 row-cols-md-2 row-cols-xl-3 g-3">${cards
                  .split('</lablet-session-card>')
                  .filter(Boolean)
                  .map(c => `<div class="col">${c}</lablet-session-card></div>`)
                  .join('')}</div>`;
    }

    setupEventHandlers() {
        const statusFilter = this.querySelector('#session-status-filter');
        if (statusFilter) {
            statusFilter.addEventListener('change', e => {
                this.setAttribute('filter-status', e.target.value);
                this.loadSessions();
            });
        }

        const terminatedCheck = this.querySelector('#include-terminated-check');
        if (terminatedCheck) {
            terminatedCheck.addEventListener('change', e => {
                this.setAttribute('include-terminated', e.target.checked ? 'true' : 'false');
                this.loadSessions();
            });
        }

        const refreshBtn = this.querySelector('#refresh-sessions-btn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => this.loadSessions());
        }

        const retryBtn = this.querySelector('#retry-load-btn');
        if (retryBtn) {
            retryBtn.addEventListener('click', () => this.loadSessions());
        }
    }
}

// Register the custom element
customElements.define('lablet-session-list', LabletSessionList);
