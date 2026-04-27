/**
 * CapacityDashboard - Fleet Capacity Overview Component
 *
 * Provides a cross-fleet capacity dashboard showing:
 * - Total vs used CPU, memory, storage across all workers
 * - Per-worker capacity utilization bars
 * - Capacity allocation breakdown (lablet instances per worker)
 * - Resource availability trends (via Grafana panels)
 *
 * Designed to be embedded in the OverviewPage or used standalone.
 *
 * @module components/pages/CapacityDashboard
 */

import { BaseComponent } from '../../core/BaseComponent.js';
import { eventBus, EventTypes } from '../../core/EventBus.js';
import '../core/LcmMetricCard.js';
import '../core/LcmStatusBadge.js';
import '../core/LcmGrafanaPanel.js';

export class CapacityDashboard extends BaseComponent {
    static get observedAttributes() {
        return ['time-range'];
    }

    constructor() {
        super();
        this._currentUser = null;
        this._isLoading = true;
        this._refreshInterval = null;
        this._workers = [];
        this._fleet = {
            totalCpuCores: 0,
            usedCpuCores: 0,
            totalMemoryGb: 0,
            usedMemoryGb: 0,
            totalStorageGb: 0,
            usedStorageGb: 0,
            totalMaxNodes: 0,
            usedNodes: 0,
            runningWorkers: 0,
            totalWorkers: 0,
            totalInstances: 0,
        };
    }

    /**
     * Initialize the dashboard with user context
     * @param {Object} user - Current user object with roles
     */
    initialize(user) {
        this._currentUser = user;
        this._loadData();
        this._setupSSESubscriptions();

        // Auto-refresh every 60 seconds
        this._refreshInterval = setInterval(() => this._loadData(), 60000);
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
     * Setup SSE subscriptions for real-time updates
     */
    _setupSSESubscriptions() {
        this.subscribe(EventTypes.WORKER_STATUS_CHANGED, () => this._loadData());
        this.subscribe(EventTypes.WORKER_CREATED, () => this._loadData());
        this.subscribe(EventTypes.WORKER_TERMINATED, () => this._loadData());
        this.subscribe(EventTypes.WORKERS_REFRESH_COMPLETED, () => this._loadData());
        this.subscribe(EventTypes.LABLET_SESSION_STATUS_CHANGED, () => this._loadData());
    }

    /**
     * Load fleet capacity data from API
     */
    async _loadData() {
        try {
            const { listWorkers } = await import('../../api/workers.js');
            const { listLabletSessions } = await import('../../api/lablet-sessions.js');

            // Fetch all workers across regions
            const workers = await listWorkers('us-east-1', null, false);
            const instances = await listLabletSessions({ include_terminated: false });

            this._workers = workers;

            // Aggregate fleet capacity (only running workers contribute)
            let totalCpu = 0,
                usedCpu = 0,
                totalMem = 0,
                usedMem = 0,
                totalStorage = 0,
                usedStorage = 0,
                totalNodes = 0,
                usedNodes = 0,
                running = 0;

            workers.forEach(w => {
                const isRunning = (w.status || '').toLowerCase() === 'running';
                if (isRunning) running++;

                // Only running workers contribute to fleet capacity
                if (isRunning && w.declared_capacity) {
                    totalCpu += w.declared_capacity.cpu_cores || 0;
                    totalMem += w.declared_capacity.memory_gb || 0;
                    totalStorage += w.declared_capacity.storage_gb || 0;
                    totalNodes += w.declared_capacity.max_nodes || 0;
                }
                if (isRunning && w.allocated_capacity) {
                    usedCpu += w.allocated_capacity.cpu_cores || 0;
                    usedMem += w.allocated_capacity.memory_gb || 0;
                    usedStorage += w.allocated_capacity.storage_gb || 0;
                    usedNodes += w.allocated_capacity.max_nodes || 0;
                }
            });

            this._fleet = {
                totalCpuCores: totalCpu,
                usedCpuCores: usedCpu,
                totalMemoryGb: totalMem,
                usedMemoryGb: usedMem,
                totalStorageGb: totalStorage,
                usedStorageGb: usedStorage,
                totalMaxNodes: totalNodes,
                usedNodes: usedNodes,
                runningWorkers: running,
                totalWorkers: workers.length,
                totalInstances: instances.length,
            };

            this._isLoading = false;
            this.render();
        } catch (error) {
            console.error('[CapacityDashboard] Failed to load data:', error);
            this._isLoading = false;
            this.render();
        }
    }

    render() {
        const f = this._fleet;
        const cpuPct = f.totalCpuCores > 0 ? ((f.usedCpuCores / f.totalCpuCores) * 100).toFixed(1) : 0;
        const memPct = f.totalMemoryGb > 0 ? ((f.usedMemoryGb / f.totalMemoryGb) * 100).toFixed(1) : 0;
        const storagePct = f.totalStorageGb > 0 ? ((f.usedStorageGb / f.totalStorageGb) * 100).toFixed(1) : 0;
        const nodePct = f.totalMaxNodes > 0 ? ((f.usedNodes / f.totalMaxNodes) * 100).toFixed(1) : 0;

        this.innerHTML = `
            <div class="capacity-dashboard">
                <!-- Fleet Summary Cards -->
                <div class="row g-3 mb-4">
                    <div class="col-12">
                        <h5 class="text-muted mb-3"><i class="bi bi-bar-chart me-2"></i>Fleet Capacity Overview</h5>
                    </div>
                    <div class="col-6 col-md-3">
                        <lcm-metric-card
                            title="Workers"
                            value="${f.runningWorkers} / ${f.totalWorkers}"
                            subtitle="running / total"
                            icon="bi-server"
                            color="primary"
                            ${this._isLoading ? 'loading' : ''}>
                        </lcm-metric-card>
                    </div>
                    <div class="col-6 col-md-3">
                        <lcm-metric-card
                            title="Active Instances"
                            value="${f.totalInstances}"
                            icon="bi-collection"
                            color="info"
                            ${this._isLoading ? 'loading' : ''}>
                        </lcm-metric-card>
                    </div>
                    <div class="col-6 col-md-3">
                        <lcm-metric-card
                            title="CPU Allocated"
                            value="${cpuPct}%"
                            subtitle="${f.usedCpuCores} / ${f.totalCpuCores} cores"
                            icon="bi-cpu"
                            color="${this._getUtilizationColor(cpuPct)}"
                            ${this._isLoading ? 'loading' : ''}>
                        </lcm-metric-card>
                    </div>
                    <div class="col-6 col-md-3">
                        <lcm-metric-card
                            title="Memory Allocated"
                            value="${memPct}%"
                            subtitle="${f.usedMemoryGb} / ${f.totalMemoryGb} GB"
                            icon="bi-memory"
                            color="${this._getUtilizationColor(memPct)}"
                            ${this._isLoading ? 'loading' : ''}>
                        </lcm-metric-card>
                    </div>
                </div>

                <!-- Utilization Bars -->
                <div class="card mb-4">
                    <div class="card-header bg-white py-2">
                        <span class="fw-medium"><i class="bi bi-bar-chart-line me-2"></i>Resource Allocation</span>
                    </div>
                    <div class="card-body">
                        ${this._renderUtilizationBar('CPU Cores', f.usedCpuCores, f.totalCpuCores, 'cores')}
                        ${this._renderUtilizationBar('Memory', f.usedMemoryGb, f.totalMemoryGb, 'GB')}
                        ${this._renderUtilizationBar('Storage', f.usedStorageGb, f.totalStorageGb, 'GB')}
                        ${this._renderUtilizationBar('Nodes', f.usedNodes, f.totalMaxNodes, 'nodes')}
                    </div>
                </div>

                <!-- Per-Worker Breakdown -->
                <div class="card mb-4">
                    <div class="card-header bg-white py-2 d-flex justify-content-between align-items-center">
                        <span class="fw-medium"><i class="bi bi-server me-2"></i>Per-Worker Capacity</span>
                        <button class="btn btn-sm btn-outline-secondary" id="refresh-capacity">
                            <i class="bi bi-arrow-clockwise me-1"></i>Refresh
                        </button>
                    </div>
                    <div class="card-body p-0">
                        ${this._renderWorkerBreakdown()}
                    </div>
                </div>
            </div>
        `;

        this._setupDashboardListeners();
    }

    _renderLoading() {
        return `
            <div class="d-flex justify-content-center align-items-center" style="min-height: 200px;">
                <div class="spinner-border text-primary" role="status">
                    <span class="visually-hidden">Loading capacity data...</span>
                </div>
            </div>
        `;
    }

    _renderUtilizationBar(label, used, total, unit) {
        const pct = total > 0 ? ((used / total) * 100).toFixed(1) : 0;
        const colorClass = this._getBarColorClass(pct);

        return `
            <div class="mb-3">
                <div class="d-flex justify-content-between align-items-center mb-1">
                    <span class="fw-medium small">${label}</span>
                    <span class="small text-muted">${used} / ${total} ${unit} (${pct}%)</span>
                </div>
                <div class="progress" style="height: 10px;">
                    <div class="progress-bar ${colorClass}" role="progressbar"
                         style="width: ${pct}%"
                         aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100">
                    </div>
                </div>
            </div>
        `;
    }

    _renderWorkerBreakdown() {
        if (this._workers.length === 0) {
            return `
                <div class="text-center text-muted py-4">
                    <i class="bi bi-server fs-3 mb-2"></i>
                    <p class="mb-0">No workers available</p>
                </div>
            `;
        }

        const rows = this._workers
            .map(w => {
                const dc = w.declared_capacity || {};
                const ac = w.allocated_capacity || {};
                const cpuPct = dc.cpu_cores > 0 ? (((ac.cpu_cores || 0) / dc.cpu_cores) * 100).toFixed(0) : 0;
                const memPct = dc.memory_gb > 0 ? (((ac.memory_gb || 0) / dc.memory_gb) * 100).toFixed(0) : 0;
                const storagePct = dc.storage_gb > 0 ? (((ac.storage_gb || 0) / dc.storage_gb) * 100).toFixed(0) : 0;
                const instanceCount = (w.assigned_instance_ids || []).length;

                return `
                    <tr>
                        <td>
                            <div class="fw-medium">${w.name || w.id || 'N/A'}</div>
                            <div class="small text-muted">${w.aws_region || ''}</div>
                        </td>
                        <td><lcm-status-badge status="${w.status}"></lcm-status-badge></td>
                        <td>
                            <div class="d-flex align-items-center gap-2">
                                <div class="progress flex-grow-1" style="height: 8px; min-width: 60px;">
                                    <div class="progress-bar ${this._getBarColorClass(cpuPct)}" style="width: ${cpuPct}%"></div>
                                </div>
                                <span class="small text-muted" style="min-width: 40px;">${cpuPct}%</span>
                            </div>
                        </td>
                        <td>
                            <div class="d-flex align-items-center gap-2">
                                <div class="progress flex-grow-1" style="height: 8px; min-width: 60px;">
                                    <div class="progress-bar ${this._getBarColorClass(memPct)}" style="width: ${memPct}%"></div>
                                </div>
                                <span class="small text-muted" style="min-width: 40px;">${memPct}%</span>
                            </div>
                        </td>
                        <td>
                            <div class="d-flex align-items-center gap-2">
                                <div class="progress flex-grow-1" style="height: 8px; min-width: 60px;">
                                    <div class="progress-bar ${this._getBarColorClass(storagePct)}" style="width: ${storagePct}%"></div>
                                </div>
                                <span class="small text-muted" style="min-width: 40px;">${storagePct}%</span>
                            </div>
                        </td>
                        <td>
                            <span class="badge ${instanceCount > 0 ? 'bg-info' : 'bg-light text-dark'}">${instanceCount}</span>
                        </td>
                    </tr>
                `;
            })
            .join('');

        return `
            <div class="table-responsive">
                <table class="table table-hover mb-0">
                    <thead class="table-light">
                        <tr>
                            <th>Worker</th>
                            <th>Status</th>
                            <th>CPU</th>
                            <th>Memory</th>
                            <th>Storage</th>
                            <th>Instances</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${rows}
                    </tbody>
                </table>
            </div>
        `;
    }

    _getUtilizationColor(pct) {
        const val = parseFloat(pct);
        if (val >= 90) return 'danger';
        if (val >= 70) return 'warning';
        if (val >= 40) return 'info';
        return 'success';
    }

    _getBarColorClass(pct) {
        const val = parseFloat(pct);
        if (val >= 90) return 'bg-danger';
        if (val >= 70) return 'bg-warning';
        if (val >= 40) return 'bg-info';
        return 'bg-success';
    }

    _setupDashboardListeners() {
        const refreshBtn = this.querySelector('#refresh-capacity');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => this._loadData());
        }
    }
}

// Register the component
customElements.define('capacity-dashboard', CapacityDashboard);

export default CapacityDashboard;
