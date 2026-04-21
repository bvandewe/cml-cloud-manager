/**
 * OverviewPage - Dashboard Page Component
 *
 * Provides an overview dashboard with:
 * - Aggregate metrics cards (workers, lablets, utilization)
 * - Grafana panels for trend visualization
 * - Quick action buttons
 * - Recent activity summary
 *
 * Uses LcmMetricCard for metrics and LcmGrafanaPanel for charts.
 *
 * @module components/pages/OverviewPage
 */

import { BaseComponent } from '../../core/BaseComponent.js';
import { eventBus, EventTypes } from '../../core/EventBus.js';
import * as labletDefinitionsApi from '../../api/lablet-definitions.js';
import '../core/LcmMetricCard.js';
import '../core/LcmGrafanaPanel.js';
import '../core/LcmTabView.js';
import '../core/LcmStatusBadge.js';

export class OverviewPage extends BaseComponent {
    static get observedAttributes() {
        return ['time-range'];
    }

    constructor() {
        super();
        this._currentUser = null;
        this._timeRange = 'today'; // today, week, month
        this._metrics = {
            totalWorkers: 0,
            runningWorkers: 0,
            stoppedWorkers: 0,
            totalLablets: 0,
            runningLablets: 0,
            scheduledLablets: 0,
            avgCpuUtilization: 0,
            avgMemoryUtilization: 0,
        };
        this._recentActivity = [];
        this._isLoading = true;
        this._refreshInterval = null;
    }

    /**
     * Initialize the page with user context
     * @param {Object} user - Current user object with roles
     */
    initialize(user) {
        this._currentUser = user;
        this.render();
        this._setupEventListeners();
        this._loadMetrics();

        // Auto-refresh metrics every 60 seconds
        this._refreshInterval = setInterval(() => this._loadMetrics(), 60000);
    }

    onMount() {
        // Initial render with loading state
        this.innerHTML = this._renderLoading();

        // Subscribe to real-time events for metric updates
        this._setupSSESubscriptions();
    }

    onUnmount() {
        // Clear refresh interval
        if (this._refreshInterval) {
            clearInterval(this._refreshInterval);
            this._refreshInterval = null;
        }
    }

    onAttributeChange(name, oldValue, newValue) {
        if (name === 'time-range' && oldValue !== newValue) {
            this._timeRange = newValue;
            this._loadMetrics();
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
     * Setup SSE event subscriptions for real-time updates
     */
    _setupSSESubscriptions() {
        // Worker events
        this.subscribe(EventTypes.WORKER_CREATED, () => this._incrementMetric('totalWorkers'));
        this.subscribe(EventTypes.WORKER_IMPORTED, () => this._incrementMetric('totalWorkers'));
        this.subscribe(EventTypes.WORKER_TERMINATED, () => this._decrementMetric('totalWorkers'));
        this.subscribe(EventTypes.WORKER_STATUS_CHANGED, data => this._handleWorkerStatusChange(data));

        // Lablet events
        this.subscribe(EventTypes.LABLET_SESSION_CREATED, () => this._incrementMetric('totalLablets'));
        this.subscribe(EventTypes.LABLET_SESSION_TERMINATED, () => this._decrementMetric('totalLablets'));
        this.subscribe(EventTypes.LABLET_SESSION_STATUS_CHANGED, data => this._handleLabletStatusChange(data));

        // Bulk refresh events
        this.subscribe(EventTypes.WORKERS_REFRESH_COMPLETED, () => this._loadMetrics());
        this.subscribe(EventTypes.LABLET_SESSIONS_REFRESH_COMPLETED, () => this._loadMetrics());
    }

    _incrementMetric(key) {
        this._metrics[key] = (this._metrics[key] || 0) + 1;
        this._updateMetricCard(key);
    }

    _decrementMetric(key) {
        this._metrics[key] = Math.max(0, (this._metrics[key] || 0) - 1);
        this._updateMetricCard(key);
    }

    _handleWorkerStatusChange(data) {
        const { old_status, new_status } = data;

        // Update running/stopped counts
        if (old_status === 'running' && new_status !== 'running') {
            this._decrementMetric('runningWorkers');
            if (new_status === 'stopped') this._incrementMetric('stoppedWorkers');
        } else if (new_status === 'running' && old_status !== 'running') {
            this._incrementMetric('runningWorkers');
            if (old_status === 'stopped') this._decrementMetric('stoppedWorkers');
        }
    }

    _handleLabletStatusChange(data) {
        const { old_status, new_status } = data;

        // Update running/scheduled counts
        if (new_status === 'running' && old_status !== 'running') {
            this._incrementMetric('runningLablets');
        } else if (old_status === 'running' && new_status !== 'running') {
            this._decrementMetric('runningLablets');
        }

        if (new_status === 'scheduled' && old_status !== 'scheduled') {
            this._incrementMetric('scheduledLablets');
        } else if (old_status === 'scheduled' && new_status !== 'scheduled') {
            this._decrementMetric('scheduledLablets');
        }
    }

    _updateMetricCard(key) {
        // Map metric keys to card IDs
        const cardMap = {
            totalWorkers: 'metric-total-workers',
            runningWorkers: 'metric-running-workers',
            stoppedWorkers: 'metric-stopped-workers',
            totalLablets: 'metric-total-lablets',
            runningLablets: 'metric-running-lablets',
            scheduledLablets: 'metric-scheduled-lablets',
            avgCpuUtilization: 'metric-avg-cpu',
            avgMemoryUtilization: 'metric-avg-memory',
        };

        const cardId = cardMap[key];
        if (cardId) {
            const card = this.querySelector(`#${cardId}`);
            if (card && card.setValue) {
                const value = key.includes('Utilization') ? `${this._metrics[key].toFixed(1)}%` : this._metrics[key];
                card.setValue(value);
            }
        }
    }

    /**
     * Load metrics from API
     */
    async _loadMetrics() {
        try {
            // Import API modules
            const { listWorkers } = await import('../../api/workers.js');
            const { listLabletSessions } = await import('../../api/lablet-sessions.js');

            // Fetch workers (all regions combined - use us-east-1 as default)
            // TODO: Aggregate across all regions
            const workers = await listWorkers('us-east-1', null, false);

            // Count worker statuses
            let running = 0,
                stopped = 0,
                totalCpu = 0,
                totalMem = 0,
                metricsCount = 0;

            workers.forEach(w => {
                if (w.status === 'running') running++;
                else if (w.status === 'stopped') stopped++;

                if (w.cpu_utilization !== undefined && w.cpu_utilization !== null) {
                    totalCpu += w.cpu_utilization;
                    metricsCount++;
                }
                if (w.memory_utilization !== undefined && w.memory_utilization !== null) {
                    totalMem += w.memory_utilization;
                }
            });

            this._metrics.totalWorkers = workers.length;
            this._metrics.runningWorkers = running;
            this._metrics.stoppedWorkers = stopped;
            this._metrics.avgCpuUtilization = metricsCount > 0 ? totalCpu / metricsCount : 0;
            this._metrics.avgMemoryUtilization = metricsCount > 0 ? totalMem / metricsCount : 0;

            // Fetch lablet sessions
            const lablets = await listLabletSessions({ include_terminated: false });

            let labRunning = 0,
                labScheduled = 0;
            lablets.forEach(l => {
                if (l.status === 'running' || l.status === 'RUNNING') labRunning++;
                else if (l.status === 'scheduled' || l.status === 'SCHEDULED') labScheduled++;
            });

            this._metrics.totalLablets = lablets.length;
            this._metrics.runningLablets = labRunning;
            this._metrics.scheduledLablets = labScheduled;

            this._isLoading = false;
            this.render();
        } catch (error) {
            console.error('[OverviewPage] Failed to load metrics:', error);
            this._isLoading = false;
            this.render();
        }
    }

    render() {
        const isAdmin = this._isAdminOrManager();
        const grafanaUrl = window.APP_CONFIG?.grafanaUrl || '/grafana';
        const prometheusAvailable = window.APP_CONFIG?.prometheusEnabled !== false;

        this.innerHTML = `
            <div class="overview-page">
                <!-- Page Header -->
                <div class="page-header d-flex justify-content-between align-items-center mb-4">
                    <div>
                        <h2 class="mb-1">
                            <i class="bi bi-speedometer2 me-2"></i>Overview
                        </h2>
                        <p class="text-muted mb-0">System dashboard and metrics</p>
                    </div>
                    <div class="d-flex gap-2 align-items-center">
                        <!-- Time Range Selector (affects trend charts only) -->
                        <small class="text-muted d-none d-md-inline" title="Time range applies to trend charts only">
                            <i class="bi bi-graph-up me-1"></i>Trends:
                        </small>
                        <lcm-tab-view id="time-range-tabs" variant="pills" persist-key="overview-timerange">
                            <lcm-tab id="today" label="Today" ${this._timeRange === 'today' ? 'active' : ''}></lcm-tab>
                            <lcm-tab id="week" label="This Week" ${this._timeRange === 'week' ? 'active' : ''}></lcm-tab>
                            <lcm-tab id="month" label="This Month" ${this._timeRange === 'month' ? 'active' : ''}></lcm-tab>
                        </lcm-tab-view>

                        <button class="btn btn-outline-secondary" id="refresh-dashboard">
                            <i class="bi bi-arrow-clockwise me-1"></i>Refresh
                        </button>
                    </div>
                </div>

                <!-- Quick Actions (Admin only) -->
                ${
                    isAdmin
                        ? `
                <div class="quick-actions mb-4">
                    <div class="d-flex gap-2">
                        <button class="btn btn-primary" data-action="create-worker">
                            <i class="bi bi-plus-circle me-1"></i>New Worker
                        </button>
                        <button class="btn btn-outline-primary" data-action="create-lablet">
                            <i class="bi bi-plus-circle me-1"></i>New Lablet
                        </button>
                        <button class="btn btn-outline-secondary" data-action="import-worker">
                            <i class="bi bi-cloud-download me-1"></i>Import Worker
                        </button>
                    </div>
                </div>
                `
                        : ''
                }

                <!-- Metrics Cards Row 1: Workers -->
                <div class="row g-3 mb-4">
                    <div class="col-12">
                        <h5 class="text-muted mb-3"><i class="bi bi-server me-2"></i>Workers</h5>
                    </div>
                    <div class="col-6 col-md-3">
                        <lcm-metric-card
                            id="metric-total-workers"
                            title="Total Workers"
                            value="${this._metrics.totalWorkers}"
                            icon="bi-server"
                            color="primary"
                            link="#workers"
                            ${this._isLoading ? 'loading' : ''}>
                        </lcm-metric-card>
                    </div>
                    <div class="col-6 col-md-3">
                        <lcm-metric-card
                            id="metric-running-workers"
                            title="Running"
                            value="${this._metrics.runningWorkers}"
                            icon="bi-play-circle"
                            color="success"
                            link="#workers?status=running"
                            ${this._isLoading ? 'loading' : ''}>
                        </lcm-metric-card>
                    </div>
                    <div class="col-6 col-md-3">
                        <lcm-metric-card
                            id="metric-stopped-workers"
                            title="Stopped"
                            value="${this._metrics.stoppedWorkers}"
                            icon="bi-stop-circle"
                            color="warning"
                            link="#workers?status=stopped"
                            ${this._isLoading ? 'loading' : ''}>
                        </lcm-metric-card>
                    </div>
                    <div class="col-6 col-md-3">
                        <lcm-metric-card
                            id="metric-avg-cpu"
                            title="Avg CPU"
                            value="${this._metrics.avgCpuUtilization.toFixed(1)}%"
                            icon="bi-cpu"
                            color="info"
                            ${this._isLoading ? 'loading' : ''}>
                        </lcm-metric-card>
                    </div>
                </div>

                <!-- Metrics Cards Row 2: Lablets -->
                <div class="row g-3 mb-4">
                    <div class="col-12">
                        <h5 class="text-muted mb-3"><i class="bi bi-collection me-2"></i>Lablets</h5>
                    </div>
                    <div class="col-6 col-md-3">
                        <lcm-metric-card
                            id="metric-total-lablets"
                            title="Total Instances"
                            value="${this._metrics.totalLablets}"
                            icon="bi-collection"
                            color="primary"
                            link="#lablets"
                            ${this._isLoading ? 'loading' : ''}>
                        </lcm-metric-card>
                    </div>
                    <div class="col-6 col-md-3">
                        <lcm-metric-card
                            id="metric-running-lablets"
                            title="Running"
                            value="${this._metrics.runningLablets}"
                            icon="bi-play-circle"
                            color="success"
                            link="#lablets?status=running"
                            ${this._isLoading ? 'loading' : ''}>
                        </lcm-metric-card>
                    </div>
                    <div class="col-6 col-md-3">
                        <lcm-metric-card
                            id="metric-scheduled-lablets"
                            title="Scheduled"
                            value="${this._metrics.scheduledLablets}"
                            icon="bi-calendar-check"
                            color="info"
                            link="#lablets?status=scheduled"
                            ${this._isLoading ? 'loading' : ''}>
                        </lcm-metric-card>
                    </div>
                    <div class="col-6 col-md-3">
                        <lcm-metric-card
                            id="metric-avg-memory"
                            title="Avg Memory"
                            value="${this._metrics.avgMemoryUtilization.toFixed(1)}%"
                            icon="bi-memory"
                            color="info"
                            ${this._isLoading ? 'loading' : ''}>
                        </lcm-metric-card>
                    </div>
                </div>

                <!-- Grafana Panels (if available) -->
                ${this._renderGrafanaPanels(grafanaUrl)}

                <!-- System Status -->
                <div class="row g-3 mb-4">
                    <div class="col-12">
                        <h5 class="text-muted mb-3"><i class="bi bi-heart-pulse me-2"></i>System Status</h5>
                    </div>
                    <div class="col-12">
                        <div class="card">
                            <div class="card-body py-3">
                                <div class="d-flex flex-wrap justify-content-around gap-3">
                                    <a href="/" target="_blank" class="text-center text-decoration-none" style="min-width: 80px;" title="Open Control Plane UI">
                                        <lcm-status-badge status="healthy"></lcm-status-badge>
                                        <div class="small text-muted mt-1">Control Plane</div>
                                    </a>
                                    <a href="http://localhost:8083/" target="_blank" class="text-center text-decoration-none" style="min-width: 80px;" title="Open Worker Controller UI">
                                        <lcm-status-badge id="svc-worker-controller" status="unknown"></lcm-status-badge>
                                        <div class="small text-muted mt-1">Worker Ctrl</div>
                                    </a>
                                    <a href="http://localhost:8082/" target="_blank" class="text-center text-decoration-none" style="min-width: 80px;" title="Open Lablet Controller UI">
                                        <lcm-status-badge id="svc-lablet-controller" status="unknown"></lcm-status-badge>
                                        <div class="small text-muted mt-1">Lablet Ctrl</div>
                                    </a>
                                    <a href="http://localhost:8081/" target="_blank" class="text-center text-decoration-none" style="min-width: 80px;" title="Open Resource Scheduler UI">
                                        <lcm-status-badge id="svc-resource-scheduler" status="unknown"></lcm-status-badge>
                                        <div class="small text-muted mt-1">Scheduler</div>
                                    </a>
                                    <a href="${prometheusAvailable ? window.APP_CONFIG?.grafanaUrl || 'http://localhost:3000' : '#'}" target="_blank" class="text-center text-decoration-none" style="min-width: 80px;" title="Open Grafana Dashboard">
                                        <lcm-status-badge status="${prometheusAvailable ? 'healthy' : 'unavailable'}"></lcm-status-badge>
                                        <div class="small text-muted mt-1">Prometheus</div>
                                    </a>
                                    <div class="text-center" style="min-width: 80px;">
                                        <lcm-status-badge id="sse-status" status="unknown"></lcm-status-badge>
                                        <div class="small text-muted mt-1">SSE</div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;

        this._setupEventListeners();
        this._updateSSEStatus();
        this._checkServiceHealth();
    }

    _renderGrafanaPanels(grafanaUrl) {
        // Only render if Grafana is configured
        if (!grafanaUrl || grafanaUrl === 'disabled') {
            return `
                <div class="row g-3 mb-4">
                    <div class="col-12">
                        <h5 class="text-muted mb-3"><i class="bi bi-graph-up me-2"></i>Trends</h5>
                    </div>
                    <div class="col-12">
                        <div class="card">
                            <div class="card-body text-center text-muted py-5">
                                <i class="bi bi-graph-up fs-1 mb-3"></i>
                                <p>Grafana is not configured. Enable Grafana to see trend charts.</p>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }

        const timeFrom = this._getGrafanaTimeFrom();

        // Available dashboards and panels:
        // - cml-custom-metrics: Panel 3 = Worker Resource Utilization, Panel 4 = Worker Labs Count
        // - host-metrics: Panel 1 = CPU Usage, Panel 2 = Memory Usage
        // - app-metrics: Panel 1 = Request Rate, Panel 2 = Error Rate, Panel 3 = Latency (P95)

        return `
            <div class="row g-3 mb-4">
                <div class="col-12">
                    <h5 class="text-muted mb-3"><i class="bi bi-graph-up me-2"></i>Trends</h5>
                </div>
                <div class="col-md-6">
                    <div class="card">
                        <div class="card-header bg-white py-2">
                            <span class="fw-medium">Worker Resource Utilization</span>
                        </div>
                        <div class="card-body p-0">
                            <lcm-grafana-panel
                                grafana-url="${grafanaUrl}"
                                dashboard-uid="cml-custom-metrics"
                                panel-id="3"
                                from="${timeFrom}"
                                to="now"
                                height="250"
                                refresh="1m">
                            </lcm-grafana-panel>
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="card">
                        <div class="card-header bg-white py-2">
                            <span class="fw-medium">Worker Labs Count</span>
                        </div>
                        <div class="card-body p-0">
                            <lcm-grafana-panel
                                grafana-url="${grafanaUrl}"
                                dashboard-uid="cml-custom-metrics"
                                panel-id="4"
                                from="${timeFrom}"
                                to="now"
                                height="250"
                                refresh="1m">
                            </lcm-grafana-panel>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    _getGrafanaTimeFrom() {
        switch (this._timeRange) {
            case 'week':
                return 'now-7d';
            case 'month':
                return 'now-30d';
            case 'today':
            default:
                return 'now-24h';
        }
    }

    _renderLoading() {
        return `
            <div class="d-flex justify-content-center align-items-center" style="min-height: 400px;">
                <div class="text-center">
                    <div class="spinner-border text-primary mb-3" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                    <p class="text-muted">Loading dashboard...</p>
                </div>
            </div>
        `;
    }

    _setupEventListeners() {
        // Refresh button
        const refreshBtn = this.querySelector('#refresh-dashboard');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => this._loadMetrics());
        }

        // Time range tabs
        const timeRangeTabs = this.querySelector('#time-range-tabs');
        if (timeRangeTabs) {
            timeRangeTabs.addEventListener('tab-change', e => {
                this._timeRange = e.detail.tabId;
                // Reload Grafana panels with new time range
                this.querySelectorAll('lcm-grafana-panel').forEach(panel => {
                    panel.setTimeRange(this._getGrafanaTimeFrom(), 'now');
                });
            });
        }

        // Quick action buttons
        this.querySelectorAll('[data-action]').forEach(btn => {
            btn.addEventListener('click', e => {
                const action = e.currentTarget.dataset.action;
                this._handleAction(action);
            });
        });

        // SSE connection status updates
        this.subscribe(EventTypes.SSE_CONNECTED, () => this._updateSSEStatus('healthy'));
        this.subscribe(EventTypes.SSE_DISCONNECTED, () => this._updateSSEStatus('disconnected'));
        this.subscribe(EventTypes.SSE_ERROR, () => this._updateSSEStatus('error'));
    }

    _updateSSEStatus(status) {
        const badge = this.querySelector('#sse-status');
        if (badge) {
            // Check current SSE status if not provided
            if (!status) {
                // LcmSSEAdapter is connected globally; rely on EventBus events for status
                status = 'unknown';
            }
            badge.setAttribute('status', status);
        }
    }

    /**
     * Check health of microservice controllers via the aggregated system health endpoint.
     * Falls back to direct checks if controller URLs are configured.
     */
    async _checkServiceHealth() {
        const badgeMap = {
            worker_controller: this.querySelector('#svc-worker-controller'),
            lablet_controller: this.querySelector('#svc-lablet-controller'),
            resource_scheduler: this.querySelector('#svc-resource-scheduler'),
        };

        try {
            // Use CPA's server-side /api/system/health which checks controllers internally (no CORS)
            const response = await fetch('/api/system/health', {
                credentials: 'include',
                signal: AbortSignal.timeout(10000),
            });

            if (!response.ok) {
                // If system health endpoint fails, mark all as unavailable
                Object.values(badgeMap).forEach(badge => badge?.setAttribute('status', 'unavailable'));
                return;
            }

            const data = await response.json();
            const components = data.components || {};

            // Update controller badges from server-side health check results
            for (const [key, badge] of Object.entries(badgeMap)) {
                if (!badge) continue;
                const component = components[key];
                if (component) {
                    badge.setAttribute('status', component.status === 'healthy' ? 'healthy' : component.status || 'unavailable');
                } else {
                    badge.setAttribute('status', 'unavailable');
                }
            }
        } catch (err) {
            console.warn('[OverviewPage] System health check failed:', err);
            Object.values(badgeMap).forEach(badge => badge?.setAttribute('status', 'unavailable'));
        }
    }

    async _handleAction(action) {
        // Dynamically import bootstrap for modal handling
        const bootstrap = await import('bootstrap');

        switch (action) {
            case 'create-worker': {
                const modal = document.getElementById('createWorkerModal');
                if (modal) {
                    new bootstrap.Modal(modal).show();
                } else {
                    console.warn('[OverviewPage] createWorkerModal not found');
                }
                break;
            }
            case 'create-lablet': {
                const modal = document.getElementById('createLabletSessionModal');
                if (modal) {
                    await this._populateDefinitionDropdown();
                    this._setDefaultSessionFormValues();
                    bootstrap.Modal.getOrCreateInstance(modal).show();
                } else {
                    console.warn('[OverviewPage] createLabletSessionModal not found');
                }
                break;
            }
            case 'import-worker': {
                const modal = document.getElementById('importWorkerModal');
                if (modal) {
                    new bootstrap.Modal(modal).show();
                } else {
                    console.warn('[OverviewPage] importWorkerModal not found');
                }
                break;
            }
            default:
                console.warn('[OverviewPage] Unknown action:', action);
        }
    }

    /**
     * Populate the definitions dropdown in the create session modal.
     */
    async _populateDefinitionDropdown() {
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
        } catch (error) {
            console.error('[OverviewPage] Failed to load definitions:', error);
        }
    }

    /**
     * Set default values for the create session form fields.
     */
    _setDefaultSessionFormValues() {
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
    }
}

// Register the component
customElements.define('overview-page', OverviewPage);

export default OverviewPage;
