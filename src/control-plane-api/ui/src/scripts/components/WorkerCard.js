/**
 * WorkerCard Component
 *
 * Self-contained worker card with:
 * - Reactive updates via EventBus
 * - Encapsulated rendering
 * - No global state dependencies
 *
 * Usage:
 *   <worker-card worker-id="abc123"></worker-card>
 */

import { BaseComponent } from '../core/BaseComponent.js';
import { EventTypes } from '../core/EventBus.js';
import { escapeHtml } from './escape.js';
import { getStatusBadgeClass, getCpuProgressClass, getMemoryProgressClass } from './status-badges.js';
import { formatDateWithRelative } from '../utils/dates.js';
import * as bootstrap from 'bootstrap';

export class WorkerCard extends BaseComponent {
    static get observedAttributes() {
        return ['worker-id', 'compact', 'data'];
    }

    constructor() {
        super();
        // Use Light DOM for better Bootstrap integration
    }

    onAttributeChange(name, oldValue, newValue) {
        if (name === 'data' && newValue && newValue !== oldValue) {
            try {
                const worker = JSON.parse(newValue);
                this.setState({ worker });
            } catch (e) {
                console.error('WorkerCard: Invalid data attribute', e);
            }
        }
    }

    onMount() {
        const workerId = this.getAttr('worker-id');
        if (!workerId) {
            console.error('WorkerCard: worker-id attribute is required');
            return;
        }

        // Check for initial data
        const dataAttr = this.getAttr('data');
        if (dataAttr) {
            try {
                const worker = JSON.parse(dataAttr);
                this.setState({ worker });
            } catch (e) {
                console.error('WorkerCard: Invalid initial data', e);
            }
        }

        // Subscribe to worker updates
        this.subscribe(EventTypes.WORKER_SNAPSHOT, data => {
            const id = data.id || data.worker_id;
            if (id === workerId) {
                // Normalize worker data to ensure consistent field names
                const normalizedWorker = {
                    id: id,
                    worker_id: id,
                    name: data.name,
                    aws_region: data.aws_region || data.region,
                    region: data.region || data.aws_region,
                    status: data.status,
                    service_status: data.service_status,
                    instance_type: data.instance_type,
                    license_status: data.license_status,
                    updated_at: data.updated_at,
                    ...data, // Keep all other fields
                };
                this.setState({ worker: normalizedWorker });
            }
        });

        this.subscribe(EventTypes.WORKER_STATUS_CHANGED, data => {
            if (data.worker_id === workerId) {
                this.setState(prevState => ({
                    worker: {
                        ...prevState.worker,
                        status: data.new_status,
                        updated_at: data.updated_at,
                    },
                }));
            }
        });

        this.subscribe(EventTypes.WORKER_METRICS_UPDATED, data => {
            if (data.worker_id === workerId) {
                this.setState(prevState => ({
                    worker: {
                        ...prevState.worker,
                        cpu_utilization: data.cpu_utilization,
                        memory_utilization: data.memory_utilization,
                        disk_utilization: data.disk_utilization,
                        // Also update CloudWatch fields if present
                        cloudwatch_cpu_utilization: data.cloudwatch_cpu_utilization,
                        cloudwatch_memory_utilization: data.cloudwatch_memory_utilization,
                        cloudwatch_storage_utilization: data.cloudwatch_storage_utilization,
                        cloudwatch_last_collected_at: data.cloudwatch_last_collected_at,
                        updated_at: data.updated_at || new Date().toISOString(),
                    },
                }));
            }
        });

        this.subscribe(EventTypes.WORKER_DELETED, data => {
            if (data.worker_id === workerId) {
                this.remove(); // Self-destruct when worker deleted
            }
        });

        this.subscribe(EventTypes.WORKER_IDLE_DETECTION_TOGGLED, data => {
            if (data.worker_id === workerId) {
                this.setState(prevState => ({
                    worker: {
                        ...prevState.worker,
                        is_idle_detection_enabled: data.is_enabled,
                    },
                }));
            }
        });

        // ADR-041: WebSocket connection status updates
        this.subscribe(EventTypes.WORKER_WS_CONNECTED, data => {
            if (data.worker_id === workerId) {
                this.setState(prevState => ({
                    worker: { ...prevState.worker, ws_connected: true },
                }));
            }
        });

        this.subscribe(EventTypes.WORKER_WS_DISCONNECTED, data => {
            if (data.worker_id === workerId) {
                this.setState(prevState => ({
                    worker: { ...prevState.worker, ws_connected: false },
                }));
            }
        });

        // Initial render
        this.loadWorkerData();
    }

    async loadWorkerData() {
        const workerId = this.getAttr('worker-id');
        // In real implementation, fetch from store or API
        // For now, we'll wait for EventBus updates
        this.render();
    }

    render() {
        const { worker } = this.getState();
        const isCompact = this.getBoolAttr('compact');

        if (!worker) {
            this.innerHTML = this.renderLoading();
            return;
        }

        this.innerHTML = this.html`
            ${this.renderStyles()}
            ${isCompact ? this.renderCompactCard(worker) : this.renderFullCard(worker)}
        `;

        this.attachEventListeners();
        this.initTooltips();
    }

    initTooltips() {
        const tooltips = this.querySelectorAll('[data-bs-toggle="tooltip"]');
        tooltips.forEach(el => {
            // Dispose existing if any (though innerHTML replacement usually handles this)
            const existing = bootstrap.Tooltip.getInstance(el);
            if (existing) existing.dispose();
            new bootstrap.Tooltip(el);
        });
    }

    renderStyles() {
        // Minimal custom styles that don't conflict with Bootstrap
        // Most styling should come from global Bootstrap classes
        return `
            <style>
                worker-card {
                    display: block;
                    height: 100%;
                }
                worker-card .card {
                    cursor: pointer;
                    transition: box-shadow 0.2s, transform 0.2s;
                }
                worker-card .card:hover {
                    box-shadow: 0 4px 8px rgba(0,0,0,0.1);
                    transform: translateY(-2px);
                }
                /* Custom metric row helper */
                worker-card .metric-row {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    margin-bottom: 0.5rem;
                }
            </style>
        `;
    }

    renderLoading() {
        return `
            ${this.renderStyles()}
            <div class="card">
                <div class="card-body" style="text-align: center; padding: 2rem;">
                    <div class="spinner" style="border: 3px solid #f3f3f3; border-top: 3px solid #0d6efd; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 0 auto;"></div>
                    <p style="margin-top: 1rem; color: #6c757d;">Loading worker...</p>
                </div>
            </div>
            <style>
                @keyframes spin {
                    0% { transform: rotate(0deg); }
                    100% { transform: rotate(360deg); }
                }
            </style>
        `;
    }

    renderFullCard(worker) {
        const statusClass = getStatusBadgeClass(worker.status);
        const cpuClass = getCpuProgressClass(worker.cpu_utilization);
        const memClass = getMemoryProgressClass(worker.memory_utilization);
        const diskClass = getMemoryProgressClass(worker.disk_utilization); // Reuse memory colors

        // Determine header class based on overall status
        // Contextual colors with subtle background for better contrast/readability
        let headerClass = 'bg-secondary-subtle text-secondary-emphasis'; // default/stopped
        const s = (worker.status || '').toLowerCase();

        if (s === 'running') {
            headerClass = 'bg-success-subtle text-success-emphasis';
        } else if (s === 'pending' || s === 'stopping' || s === 'shutting-down') {
            headerClass = 'bg-warning-subtle text-warning-emphasis';
        } else if (s === 'terminated' || s === 'error' || s === 'failed') {
            headerClass = 'bg-danger-subtle text-danger-emphasis';
        }

        const licenseStatus = worker.license_status || 'unknown';
        // Check nested registration status if available
        const registrationStatus = worker.cml_license_info?.registration?.status;
        const isLicensed = licenseStatus === 'registered' || registrationStatus === 'COMPLETED' || registrationStatus === 'REGISTERED';

        // Status icon mapping
        let statusIcon = 'bi-question-circle-fill';
        if (s === 'running') statusIcon = 'bi-play-circle-fill';
        else if (s === 'stopped') statusIcon = 'bi-stop-circle-fill';
        else if (s === 'pending') statusIcon = 'bi-hourglass-split';
        else if (s === 'stopping' || s === 'shutting-down') statusIcon = 'bi-power';
        else if (s === 'terminated') statusIcon = 'bi-x-circle-fill';

        return `
            <div class="card" data-action="open-details">
                <div class="card-header ${headerClass}">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <strong>${escapeHtml(worker.name)}</strong>
                        <div style="display: flex; gap: 0.25rem; align-items: center;">
                            ${worker.ws_connected ? '<span class="rounded-circle d-inline-block" style="width: 8px; height: 8px; background-color: #198754;" data-bs-toggle="tooltip" title="WebSocket connected (Live)"></span>' : ''}
                            ${
                                isLicensed
                                    ? '<span class="badge bg-success" data-bs-toggle="tooltip" title="Licensed"><i class="bi bi-key-fill"></i></span>'
                                    : '<span class="badge bg-warning" data-bs-toggle="tooltip" title="Unlicensed"><i class="bi bi-key"></i></span>'
                            }
                            ${
                                worker.is_idle_detection_enabled
                                    ? '<span class="badge bg-success" data-bs-toggle="tooltip" title="Idle Detection Enabled"><i class="bi bi-moon-stars-fill"></i></span>'
                                    : '<span class="badge bg-secondary" data-bs-toggle="tooltip" title="Idle Detection Disabled"><i class="bi bi-moon-stars"></i></span>'
                            }
                            <span class="badge ${statusClass}" data-bs-toggle="tooltip" title="${escapeHtml(worker.status)}">
                                <i class="bi ${statusIcon}"></i>
                            </span>
                        </div>
                    </div>
                </div>
                <div class="card-body">
                    <div class="metric-row">
                        <span class="text-muted">Region</span>
                        <span>${escapeHtml(worker.aws_region)}</span>
                    </div>
                    <div class="metric-row">
                        <span class="text-muted">Instance Type</span>
                        <span>${escapeHtml(worker.instance_type || 'N/A')}</span>
                    </div>

                    <!-- Resource Utilization in a single row -->
                    <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.75rem; margin-top: 0.75rem;">
                        <div>
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.25rem;">
                                <span class="text-muted" style="font-size: 0.75rem;">CPU</span>
                                <span style="font-size: 0.75rem;">${worker.cpu_utilization ? worker.cpu_utilization.toFixed(1) : '0'}%</span>
                            </div>
                            <div class="progress">
                                <div class="progress-bar progress-bar-${cpuClass}" style="width: ${worker.cpu_utilization || 0}%"></div>
                            </div>
                        </div>
                        <div>
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.25rem;">
                                <span class="text-muted" style="font-size: 0.75rem;">Memory</span>
                                <span style="font-size: 0.75rem;">${worker.memory_utilization ? worker.memory_utilization.toFixed(1) : '0'}%</span>
                            </div>
                            <div class="progress">
                                <div class="progress-bar progress-bar-${memClass}" style="width: ${worker.memory_utilization || 0}%"></div>
                            </div>
                        </div>
                        <div>
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.25rem;">
                                <span class="text-muted" style="font-size: 0.75rem;">Disk</span>
                                <span style="font-size: 0.75rem;">${worker.disk_utilization ? worker.disk_utilization.toFixed(1) : '0'}%</span>
                            </div>
                            <div class="progress">
                                <div class="progress-bar progress-bar-${diskClass}" style="width: ${worker.disk_utilization || 0}%"></div>
                            </div>
                        </div>
                    </div>

                    <div style="margin-top: 1rem; font-size: 0.75rem; color: #6c757d;">
                        Updated: ${formatDateWithRelative(worker.updated_at)}
                    </div>
                </div>
            </div>
        `;
    }

    renderCompactCard(worker) {
        const statusClass = getStatusBadgeClass(worker.status);

        // Status icon mapping
        let statusIcon = 'bi-question-circle-fill';
        const s = (worker.status || '').toLowerCase();
        if (s === 'running') statusIcon = 'bi-play-circle-fill';
        else if (s === 'stopped') statusIcon = 'bi-stop-circle-fill';
        else if (s === 'pending') statusIcon = 'bi-hourglass-split';
        else if (s === 'stopping' || s === 'shutting-down') statusIcon = 'bi-power';
        else if (s === 'terminated') statusIcon = 'bi-x-circle-fill';

        return `
            <div class="card" data-action="open-details" style="padding: 0.75rem;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <strong>${escapeHtml(worker.name)}</strong>
                        <div class="text-muted" style="font-size: 0.75rem;">
                            ${escapeHtml(worker.aws_region)}
                        </div>
                    </div>
                    <span class="badge ${statusClass}" data-bs-toggle="tooltip" title="${escapeHtml(worker.status)}">
                        <i class="bi ${statusIcon}"></i>
                    </span>
                </div>
            </div>
        `;
    }

    attachEventListeners() {
        const card = this.querySelector('[data-action="open-details"]');
        if (card) {
            card.addEventListener('click', () => {
                const worker = this.getState().worker;
                if (!worker) {
                    console.error('[WorkerCard] No worker data available for click');
                    return;
                }
                if (!worker.id || !worker.aws_region) {
                    console.error('[WorkerCard] Worker missing id or region:', worker);
                    return;
                }
                console.log('[WorkerCard] Emitting UI_OPEN_WORKER_DETAILS:', {
                    workerId: worker.id,
                    region: worker.aws_region,
                });
                this.emit('UI_OPEN_WORKER_DETAILS', {
                    workerId: worker.id,
                    region: worker.aws_region,
                });
            });
        }
    }
}

// Register custom element
customElements.define('worker-card', WorkerCard);

export default WorkerCard;
