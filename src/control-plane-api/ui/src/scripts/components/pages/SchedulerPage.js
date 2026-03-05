/**
 * SchedulerPage - Resource Scheduler Dashboard Component
 *
 * Provides visibility into the resource-scheduler service:
 * - Leader election status (which instance is leading)
 * - Scheduling statistics (cycles, decisions, retries, scale-ups)
 * - Pending lablet placements from CPA
 * - Manual reconciliation trigger
 * - Scheduling policy info
 *
 * Embedded as a tab in SystemPage or accessed standalone.
 *
 * @module components/pages/SchedulerPage
 */

import { BaseComponent } from '../../core/BaseComponent.js';
import { eventBus, EventTypes } from '../../core/EventBus.js';
import { showConfirmAsync } from '../modals.js';
import '../core/LcmMetricCard.js';
import '../core/LcmStatusBadge.js';

export class SchedulerPage extends BaseComponent {
    constructor() {
        super();
        this._currentUser = null;
        this._isLoading = true;
        this._leaderStatus = null;
        this._stats = null;
        this._pendingInstances = [];
        this._refreshInterval = null;
        this._error = null;
    }

    /**
     * Initialize the scheduler page with user context
     * @param {Object} user - Current user object with roles
     */
    initialize(user) {
        this._currentUser = user;
        this._loadData();

        // Auto-refresh every 15 seconds
        this._refreshInterval = setInterval(() => this._loadData(), 15000);
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

    /**
     * Check if user has admin role
     */
    _isAdmin() {
        if (!this._currentUser?.roles) return false;
        const adminRoles = ['admin', 'lcm-admin'];
        return this._currentUser.roles.some(role => adminRoles.includes(role.toLowerCase()));
    }

    /**
     * Load scheduler data from APIs
     */
    async _loadData() {
        try {
            // Load leader status and stats from resource-scheduler
            const schedulerApi = await import('../../api/scheduler.js');

            const [leaderResult, statsResult] = await Promise.allSettled([schedulerApi.getLeaderStatus(), schedulerApi.getSchedulerStats()]);

            this._leaderStatus = leaderResult.status === 'fulfilled' ? leaderResult.value : null;
            this._stats = statsResult.status === 'fulfilled' ? statsResult.value : null;

            // Load pending instances from CPA
            try {
                const { listLabletSessions } = await import('../../api/lablet-sessions.js');
                const pending = await listLabletSessions({ status: 'pending', include_terminated: false });
                const scheduled = await listLabletSessions({ status: 'scheduled', include_terminated: false });
                this._pendingInstances = [...pending, ...scheduled];
            } catch {
                this._pendingInstances = [];
            }

            this._error = null;
            this._isLoading = false;
            this.render();
        } catch (error) {
            console.error('[SchedulerPage] Failed to load data:', error);
            this._error = error.message;
            this._isLoading = false;
            this.render();
        }
    }

    render() {
        const isAdmin = this._isAdmin();

        this.innerHTML = `
            <div class="scheduler-page">
                <!-- Page Header -->
                <div class="page-header d-flex justify-content-between align-items-center mb-4">
                    <div>
                        <h2 class="mb-1">
                            <i class="bi bi-diagram-3 me-2"></i>Resource Scheduler
                        </h2>
                        <p class="text-muted mb-0">Scheduling service status, placement decisions, and leader election</p>
                    </div>
                    <div class="d-flex gap-2">
                        ${
                            isAdmin
                                ? `
                        <button class="btn btn-warning" id="trigger-reconcile-btn" title="Trigger immediate reconciliation">
                            <i class="bi bi-lightning me-1"></i>Trigger Reconcile
                        </button>
                        `
                                : ''
                        }
                        <button class="btn btn-outline-secondary" id="refresh-scheduler-btn">
                            <i class="bi bi-arrow-clockwise me-1"></i>Refresh
                        </button>
                    </div>
                </div>

                ${this._error ? this._renderError() : ''}

                <!-- Leader Status Card -->
                ${this._renderLeaderStatus()}

                <!-- Stats Cards -->
                ${this._renderStatsCards()}

                <!-- Pending Placements -->
                ${this._renderPendingPlacements()}

                <!-- Scheduling Policy -->
                ${this._renderSchedulingPolicy()}
            </div>
        `;

        this._setupListeners();
    }

    _renderLoading() {
        return `
            <div class="d-flex justify-content-center align-items-center" style="min-height: 200px;">
                <div class="spinner-border text-primary" role="status">
                    <span class="visually-hidden">Loading scheduler data...</span>
                </div>
            </div>
        `;
    }

    _renderError() {
        return `
            <div class="alert alert-warning alert-dismissible fade show mb-4" role="alert">
                <i class="bi bi-exclamation-triangle me-2"></i>
                <strong>Scheduler Unavailable:</strong> ${this._error}
                <br><small class="text-muted">The resource-scheduler service may not be running or accessible.</small>
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            </div>
        `;
    }

    _renderLeaderStatus() {
        const ls = this._leaderStatus;

        if (!ls) {
            return `
                <div class="card mb-4">
                    <div class="card-header bg-white py-2">
                        <span class="fw-medium"><i class="bi bi-shield-check me-2"></i>Leader Election</span>
                    </div>
                    <div class="card-body text-center text-muted py-4">
                        <i class="bi bi-cloud-slash fs-3 mb-2"></i>
                        <p class="mb-0">Leader status unavailable</p>
                    </div>
                </div>
            `;
        }

        return `
            <div class="card mb-4">
                <div class="card-header bg-white py-2 d-flex justify-content-between align-items-center">
                    <span class="fw-medium"><i class="bi bi-shield-check me-2"></i>Leader Election</span>
                    <lcm-status-badge status="${ls.is_leader ? 'healthy' : 'standby'}"></lcm-status-badge>
                </div>
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-4">
                            <div class="mb-3">
                                <div class="small text-muted">This Instance</div>
                                <div class="fw-medium font-monospace">${ls.instance_id || 'N/A'}</div>
                            </div>
                        </div>
                        <div class="col-md-4">
                            <div class="mb-3">
                                <div class="small text-muted">Current Leader</div>
                                <div class="fw-medium font-monospace">${ls.current_leader_id || 'N/A'}</div>
                            </div>
                        </div>
                        <div class="col-md-4">
                            <div class="mb-3">
                                <div class="small text-muted">Role</div>
                                <div>
                                    ${ls.is_leader ? '<span class="badge bg-success"><i class="bi bi-star-fill me-1"></i>Leader</span>' : '<span class="badge bg-secondary"><i class="bi bi-clock me-1"></i>Follower</span>'}
                                </div>
                            </div>
                        </div>
                    </div>
                    ${
                        this._isAdmin() && ls.is_leader
                            ? `
                    <div class="mt-2">
                        <button class="btn btn-sm btn-outline-danger" id="resign-leadership-btn">
                            <i class="bi bi-box-arrow-right me-1"></i>Resign Leadership
                        </button>
                    </div>
                    `
                            : ''
                    }
                </div>
            </div>
        `;
    }

    _renderStatsCards() {
        const s = this._stats || {};

        return `
            <div class="row g-3 mb-4">
                <div class="col-12">
                    <h5 class="text-muted mb-3"><i class="bi bi-graph-up me-2"></i>Scheduling Statistics</h5>
                </div>
                <div class="col-6 col-md-3">
                    <lcm-metric-card
                        title="Total Cycles"
                        value="${s.total_cycles ?? '—'}"
                        icon="bi-arrow-repeat"
                        color="primary"
                        ${this._isLoading ? 'loading' : ''}>
                    </lcm-metric-card>
                </div>
                <div class="col-6 col-md-3">
                    <lcm-metric-card
                        title="Decisions Made"
                        value="${s.total_decisions ?? '—'}"
                        icon="bi-check2-all"
                        color="success"
                        ${this._isLoading ? 'loading' : ''}>
                    </lcm-metric-card>
                </div>
                <div class="col-6 col-md-3">
                    <lcm-metric-card
                        title="Retries"
                        value="${s.total_retries ?? '—'}"
                        icon="bi-arrow-counterclockwise"
                        color="warning"
                        ${this._isLoading ? 'loading' : ''}>
                    </lcm-metric-card>
                </div>
                <div class="col-6 col-md-3">
                    <lcm-metric-card
                        title="Scale-Up Requests"
                        value="${s.total_scale_ups ?? '—'}"
                        icon="bi-arrow-up-circle"
                        color="info"
                        ${this._isLoading ? 'loading' : ''}>
                    </lcm-metric-card>
                </div>
            </div>

            <!-- Detailed Stats -->
            ${this._stats ? this._renderDetailedStats() : ''}
        `;
    }

    _renderDetailedStats() {
        const s = this._stats;
        const keys = Object.keys(s).filter(k => !['total_cycles', 'total_decisions', 'total_retries', 'total_scale_ups'].includes(k));

        if (keys.length === 0) return '';

        return `
            <div class="card mb-4">
                <div class="card-header bg-white py-2">
                    <span class="fw-medium"><i class="bi bi-list-columns me-2"></i>Detailed Statistics</span>
                </div>
                <div class="card-body p-0">
                    <div class="table-responsive">
                        <table class="table table-sm mb-0">
                            <thead class="table-light">
                                <tr>
                                    <th>Metric</th>
                                    <th>Value</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${keys
                                    .map(
                                        k => `
                                    <tr>
                                        <td class="text-muted">${this._formatStatKey(k)}</td>
                                        <td class="font-monospace">${this._formatStatValue(s[k])}</td>
                                    </tr>
                                `
                                    )
                                    .join('')}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        `;
    }

    _renderPendingPlacements() {
        return `
            <div class="card mb-4">
                <div class="card-header bg-white py-2 d-flex justify-content-between align-items-center">
                    <span class="fw-medium">
                        <i class="bi bi-hourglass-split me-2"></i>Pending / Queued Placements
                        <span class="badge bg-secondary ms-2">${this._pendingInstances.length}</span>
                    </span>
                </div>
                <div class="card-body p-0">
                    ${
                        this._pendingInstances.length === 0
                            ? `
                        <div class="text-center text-muted py-4">
                            <i class="bi bi-check-circle fs-3 mb-2"></i>
                            <p class="mb-0">No pending placements — all instances are placed.</p>
                        </div>
                    `
                            : `
                        <div class="table-responsive">
                            <table class="table table-hover mb-0">
                                <thead class="table-light">
                                    <tr>
                                        <th>Instance</th>
                                        <th>Definition</th>
                                        <th>Status</th>
                                        <th>Owner</th>
                                        <th>Created</th>
                                        <th>Timeslot</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${this._pendingInstances
                                        .map(
                                            inst => `
                                        <tr>
                                            <td>
                                                <span class="font-monospace small" title="${inst.id}">
                                                    ${inst.id ? inst.id.substring(0, 12) + '...' : 'N/A'}
                                                </span>
                                            </td>
                                            <td>${inst.definition_name || inst.definition_id || '—'}</td>
                                            <td><lcm-status-badge status="${inst.status}"></lcm-status-badge></td>
                                            <td>${inst.owner_id || '—'}</td>
                                            <td class="small">${this._formatDateTime(inst.created_at)}</td>
                                            <td class="small">${this._formatDateTime(inst.timeslot_start)}</td>
                                        </tr>
                                    `
                                        )
                                        .join('')}
                                </tbody>
                            </table>
                        </div>
                    `
                    }
                </div>
            </div>
        `;
    }

    _renderSchedulingPolicy() {
        return `
            <div class="card mb-4">
                <div class="card-header bg-white py-2">
                    <span class="fw-medium"><i class="bi bi-gear me-2"></i>Scheduling Policy</span>
                </div>
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-6">
                            <h6 class="text-muted mb-3">Placement Strategy</h6>
                            <ul class="list-unstyled">
                                <li class="mb-2">
                                    <i class="bi bi-check-circle text-success me-2"></i>
                                    <strong>Bin Packing:</strong> Prefer workers with highest utilization
                                </li>
                                <li class="mb-2">
                                    <i class="bi bi-check-circle text-success me-2"></i>
                                    <strong>Capacity Check:</strong> Validate CPU, memory, storage, nodes
                                </li>
                                <li class="mb-2">
                                    <i class="bi bi-check-circle text-success me-2"></i>
                                    <strong>License Affinity:</strong> Match licensed content to licensed workers
                                </li>
                                <li class="mb-2">
                                    <i class="bi bi-check-circle text-success me-2"></i>
                                    <strong>Port Availability:</strong> Check port ranges for device access
                                </li>
                            </ul>
                        </div>
                        <div class="col-md-6">
                            <h6 class="text-muted mb-3">Auto-Scaling Rules</h6>
                            <ul class="list-unstyled">
                                <li class="mb-2">
                                    <i class="bi bi-arrow-up-circle text-primary me-2"></i>
                                    <strong>Scale Up:</strong> No eligible workers → request new worker from cheapest template
                                </li>
                                <li class="mb-2">
                                    <i class="bi bi-arrow-down-circle text-warning me-2"></i>
                                    <strong>Scale Down:</strong> Idle worker with no instances → drain → stop EC2
                                </li>
                                <li class="mb-2">
                                    <i class="bi bi-arrow-counterclockwise text-info me-2"></i>
                                    <strong>Retry Policy:</strong> Exponential backoff, escalation after 5 failures
                                </li>
                                <li class="mb-2">
                                    <i class="bi bi-shield-check text-success me-2"></i>
                                    <strong>Safety Guards:</strong> Min/max workers, cooldown periods
                                </li>
                            </ul>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    _setupListeners() {
        // Refresh button
        const refreshBtn = this.querySelector('#refresh-scheduler-btn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => this._loadData());
        }

        // Trigger reconcile
        const triggerBtn = this.querySelector('#trigger-reconcile-btn');
        if (triggerBtn) {
            triggerBtn.addEventListener('click', () => this._triggerReconcile());
        }

        // Resign leadership
        const resignBtn = this.querySelector('#resign-leadership-btn');
        if (resignBtn) {
            resignBtn.addEventListener('click', () => this._resignLeadership());
        }
    }

    async _triggerReconcile() {
        try {
            const { triggerReconcile } = await import('../../api/scheduler.js');
            const result = await triggerReconcile();

            const { showToast } = await import('../../ui/notifications.js');
            showToast('Reconciliation triggered successfully', 'success');

            // Refresh data after short delay
            setTimeout(() => this._loadData(), 2000);
        } catch (error) {
            console.error('[SchedulerPage] Failed to trigger reconcile:', error);
            const { showToast } = await import('../../ui/notifications.js');
            showToast(`Failed to trigger reconcile: ${error.message}`, 'error');
        }
    }

    async _resignLeadership() {
        if (!(await showConfirmAsync('Resign Leadership', 'Are you sure you want to resign leadership? Another instance will take over.', { actionLabel: 'Resign', actionClass: 'btn-warning' }))) return;

        try {
            const { resignLeadership } = await import('../../api/scheduler.js');
            await resignLeadership();

            const { showToast } = await import('../../ui/notifications.js');
            showToast('Leadership resigned successfully', 'success');

            // Refresh data
            setTimeout(() => this._loadData(), 2000);
        } catch (error) {
            console.error('[SchedulerPage] Failed to resign leadership:', error);
            const { showToast } = await import('../../ui/notifications.js');
            showToast(`Failed to resign: ${error.message}`, 'error');
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

    _formatStatKey(key) {
        return key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    }

    _formatStatValue(val) {
        if (val === null || val === undefined) return '—';
        if (typeof val === 'number') {
            return val.toLocaleString();
        }
        if (typeof val === 'object') {
            return JSON.stringify(val, null, 2);
        }
        return String(val);
    }
}

// Register the component
customElements.define('scheduler-page', SchedulerPage);

export default SchedulerPage;
