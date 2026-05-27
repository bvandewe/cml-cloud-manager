// worker-monitoring.js
// Worker-specific monitoring tab logic

import { escapeHtml } from '../components/escape.js';
import { formatDate, getRelativeTime } from '../utils/dates.js';
import { isAdmin } from '../utils/roles.js';
import { enableIdleDetection, disableIdleDetection } from '../api/workers.js';
import { showToast } from './notifications.js';
import { showConfirm } from '../components/modals.js';

/**
 * Helper to format date with full timestamp and relative time tooltip
 * @param {string} dateString - ISO date string
 * @returns {string} HTML with formatted timestamp and info icon with relative time tooltip
 */
function formatDateWithRelative(dateString) {
    if (!dateString) return '<span class="text-muted">Never</span>';
    try {
        const date = new Date(dateString);
        const formatted = formatDate(dateString);
        const relative = getRelativeTime(date);
        const uniqueId = `date-tooltip-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

        return `${formatted} <i class="bi bi-info-circle text-muted date-tooltip-icon"
                data-bs-toggle="tooltip"
                data-bs-placement="top"
                data-bs-title="${relative}"
                data-tooltip-id="${uniqueId}"
                style="cursor: help;"></i>`;
    } catch (e) {
        return dateString;
    }
}

/**
 * Render the monitoring tab with worker-specific monitoring data
 * @param {Object} worker - Worker object with monitoring fields
 */
export function renderMonitoringTab(worker) {
    console.log('[worker-monitoring] renderMonitoringTab called with:', {
        worker_type: typeof worker,
        worker_truthy: !!worker,
        has_id: worker?.id,
        has_name: worker?.name,
        worker_keys: worker ? Object.keys(worker).length : 0,
    });

    const monitoringContent = document.getElementById('worker-details-monitoring');
    if (!monitoringContent) {
        console.warn('[worker-monitoring] #worker-details-monitoring element not found');
        return;
    }

    if (!worker) {
        monitoringContent.innerHTML = `
            <div class="alert alert-warning">
                <i class="bi bi-exclamation-triangle"></i> Worker data not available
            </div>`;
        return;
    }

    // Format all date fields upfront
    const lastActivity = formatDateWithRelative(worker.last_activity_at);
    const lastCheck = formatDateWithRelative(worker.last_activity_check_at);
    const nextCheck = formatDateWithRelative(worker.next_idle_check_at);
    const targetPause = formatDateWithRelative(worker.target_pause_at);
    const lastPaused = formatDateWithRelative(worker.last_paused_at);
    const lastResumed = formatDateWithRelative(worker.last_resumed_at);
    const nextRefresh = formatDateWithRelative(worker.next_refresh_at);
    const cmlLastSynced = formatDateWithRelative(worker.cml_last_synced_at);
    const cloudwatchLast = formatDateWithRelative(worker.cloudwatch_last_collected_at);

    // Build monitoring settings section
    let html = '<div class="row g-4">';

    // ADR-041: WebSocket Connection Status Card
    const wsConnected = worker.ws_connected === true;
    const lastWsUpdate = worker.last_ws_update_at;
    const isLive = wsConnected && lastWsUpdate && Date.now() - new Date(lastWsUpdate).getTime() < 15000;

    html += `
        <div class="col-12 mb-2">
            <div class="d-flex align-items-center gap-2">
                <span class="d-inline-flex align-items-center gap-1">
                    <span class="rounded-circle d-inline-block" style="width: 10px; height: 10px; background-color: ${wsConnected ? '#198754' : '#ffc107'};" title="${wsConnected ? 'WebSocket connected' : 'Polling fallback'}"></span>
                    <small class="text-muted">${wsConnected ? 'WebSocket' : 'Polling'}</small>
                </span>
                ${isLive ? '<span class="badge bg-success bg-opacity-75"><i class="bi bi-broadcast"></i> Live</span>' : ''}
            </div>
        </div>`;

    // Idle Detection Settings Card
    html += `
        <div class="col-md-6">
            <div class="card h-100">
                <div class="card-header bg-body-tertiary">
                    <h6 class="mb-0"><i class="bi bi-activity"></i> Idle Detection</h6>
                </div>
                <div class="card-body">
                    <dl class="row mb-0">
                        <dt class="col-sm-6">Status:</dt>
                        <dd class="col-sm-6">
                            <span class="badge ${worker.is_idle_detection_enabled ? 'bg-success' : 'bg-secondary'}">
                                ${worker.is_idle_detection_enabled ? 'Enabled' : 'Disabled'}
                            </span>
                        </dd>`;

    // Admin-only toggle control
    if (isAdmin()) {
        html += `
                        <dt class="col-sm-6">Control:</dt>
                        <dd class="col-sm-6">
                            <div class="form-check form-switch">
                                <input class="form-check-input" type="checkbox" role="switch"
                                       id="idle-detection-toggle"
                                       ${worker.is_idle_detection_enabled ? 'checked' : ''}
                                       data-worker-id="${worker.id}"
                                       data-region="${worker.aws_region}">
                                <label class="form-check-label" for="idle-detection-toggle">
                                    <small class="text-muted">Toggle idle detection</small>
                                </label>
                            </div>
                        </dd>`;
    }

    html += `
                        <dt class="col-sm-6">Last Activity:</dt>
                        <dd class="col-sm-6">
                            ${lastActivity}
                        </dd>

                        <dt class="col-sm-6">Last Check:</dt>
                        <dd class="col-sm-6">
                            ${lastCheck}
                        </dd>

                        <dt class="col-sm-6">Next Check:</dt>
                        <dd class="col-sm-6">
                            ${nextCheck}
                        </dd>

                        <dt class="col-sm-6">Target Pause:</dt>
                        <dd class="col-sm-6">
                            ${targetPause}
                        </dd>
                    </dl>
                </div>
            </div>
        </div>`;

    // Pause/Resume History Card
    html += `
        <div class="col-md-6">
            <div class="card h-100">
                <div class="card-header bg-info text-white">
                    <h6 class="mb-0"><i class="bi bi-pause-circle"></i> Pause/Resume History</h6>
                </div>
                <div class="card-body">
                    <dl class="row mb-0">
                        <dt class="col-sm-6">Auto Pauses:</dt>
                        <dd class="col-sm-6"><strong>${worker.auto_pause_count || 0}</strong></dd>

                        <dt class="col-sm-6">Manual Pauses:</dt>
                        <dd class="col-sm-6"><strong>${worker.manual_pause_count || 0}</strong></dd>

                        <dt class="col-sm-6">Auto Resumes:</dt>
                        <dd class="col-sm-6"><strong>${worker.auto_resume_count || 0}</strong></dd>

                        <dt class="col-sm-6">Manual Resumes:</dt>
                        <dd class="col-sm-6"><strong>${worker.manual_resume_count || 0}</strong></dd>

                        <dt class="col-sm-6">Last Paused:</dt>
                        <dd class="col-sm-6">
                            ${lastPaused}
                        </dd>

                        <dt class="col-sm-6">Last Resumed:</dt>
                        <dd class="col-sm-6">
                            ${lastResumed}
                        </dd>
                    </dl>
                </div>
            </div>
        </div>`;

    html += '</div>'; // Close row

    // Last Pause Details Section
    if (worker.last_paused_at) {
        html += `
            <div class="card mt-4">
                <div class="card-header">
                    <h6 class="mb-0"><i class="bi bi-info-circle"></i> Last Pause Details</h6>
                </div>
                <div class="card-body">
                    <dl class="row mb-0">
                        <dt class="col-sm-3">Paused At:</dt>
                        <dd class="col-sm-3">${lastPaused}</dd>

                        <dt class="col-sm-3">Paused By:</dt>
                        <dd class="col-sm-3">${escapeHtml(worker.paused_by || 'Unknown')}</dd>

                        <dt class="col-sm-3">Reason:</dt>
                        <dd class="col-sm-3">
                            <span class="badge ${worker.pause_reason === 'idle_timeout' ? 'bg-warning' : worker.pause_reason === 'manual' ? 'bg-primary' : 'bg-secondary'}">
                                ${escapeHtml(worker.pause_reason || 'Unknown')}
                            </span>
                        </dd>
                    </dl>
                </div>
            </div>`;
    }

    // Metrics Refresh Timing Section
    html += `
        <div class="card mt-4">
            <div class="card-header">
                <h6 class="mb-0"><i class="bi bi-clock-history"></i> Metrics Collection</h6>
            </div>
            <div class="card-body">
                <dl class="row mb-0">
                    <dt class="col-sm-3">Poll Interval:</dt>
                    <dd class="col-sm-3">${worker.poll_interval ? `${worker.poll_interval}s` : '<span class="text-muted">Not set</span>'}</dd>

                    <dt class="col-sm-3">Next Refresh:</dt>
                    <dd class="col-sm-3">
                        ${nextRefresh}
                    </dd>

                    <dt class="col-sm-3">CML Last Synced:</dt>
                    <dd class="col-sm-3">
                        ${cmlLastSynced}
                    </dd>

                    <dt class="col-sm-3">CloudWatch Last:</dt>
                    <dd class="col-sm-3">
                        ${cloudwatchLast}
                    </dd>
                </dl>
            </div>
        </div>`;

    // Resource Utilization Chart (admin-only)
    if (isAdmin()) {
        const cmlCpu = worker.cml_system_info?.cpu_utilization ?? worker.metrics?.system_info?.cpu_utilization;

        html += `
        <div class="card mt-4">
            <div class="card-header">
                <h6 class="mb-0"><i class="bi bi-graph-up"></i> Recent Resource Utilization</h6>
            </div>
            <div class="card-body">
                <div class="row">
                    <div class="col-md-4">
                        <div class="text-center mb-3">
                            <h6 class="text-muted small">CPU Utilization</h6>
                            <div class="display-6 ${getCpuUtilizationColor(worker)}">
                                ${formatUtilization(worker.cloudwatch_cpu_utilization)}
                            </div>
                            <small class="text-muted">CloudWatch</small>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="text-center mb-3">
                            <h6 class="text-muted small">Memory Utilization</h6>
                            <div class="display-6 ${getMemoryUtilizationColor(worker)}">
                                ${formatUtilization(worker.cloudwatch_memory_utilization)}
                            </div>
                            <small class="text-muted">CloudWatch</small>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="text-center mb-3">
                            <h6 class="text-muted small">CML CPU</h6>
                            <div class="display-6 ${getCpuUtilizationColor({ cloudwatch_cpu_utilization: cmlCpu })}">
                                ${formatUtilization(cmlCpu)}
                            </div>
                            <small class="text-muted">CML Native</small>
                        </div>
                    </div>
                </div>
                <div class="alert alert-info mt-3">
                    <i class="bi bi-info-circle"></i>
                    <strong>Note:</strong> Resource utilization data is collected from CloudWatch and CML native telemetry.
                    ${!worker.cloudwatch_detailed_monitoring_enabled ? '<span class="text-warning">CloudWatch detailed monitoring is disabled - metrics may be delayed.</span>' : 'CloudWatch detailed monitoring is enabled for real-time metrics.'}
                </div>
            </div>
        </div>`;
    }

    monitoringContent.innerHTML = html;

    // Attach event listeners
    if (isAdmin()) {
        attachIdleDetectionToggleHandler(worker);
    }

    // Initialize tooltips for date info icons
    import('../utils/dates.js').then(({ initializeDateTooltips }) => {
        initializeDateTooltips();
    });
}

/**
 * Format utilization percentage
 * @param {number|null} value - Utilization value (0-100)
 * @returns {string} Formatted percentage
 */
function formatUtilization(value) {
    if (value === null || value === undefined) {
        return '<span class="text-muted">N/A</span>';
    }
    return `${value.toFixed(1)}%`;
}

/**
 * Get color class for CPU utilization
 * @param {Object} worker - Worker object
 * @returns {string} Bootstrap color class
 */
function getCpuUtilizationColor(worker) {
    const cpu = worker.cpu_utilization ?? worker.cloudwatch_cpu_utilization;
    if (cpu === null || cpu === undefined) return 'text-muted';
    if (cpu > 80) return 'text-danger';
    if (cpu > 60) return 'text-warning';
    return 'text-success';
}

/**
 * Get color class for memory utilization
 * @param {Object} worker - Worker object
 * @returns {string} Bootstrap color class
 */
function getMemoryUtilizationColor(worker) {
    const mem = worker.memory_utilization ?? worker.cloudwatch_memory_utilization;
    if (mem === null || mem === undefined) return 'text-muted';
    if (mem > 90) return 'text-danger';
    if (mem > 75) return 'text-warning';
    return 'text-success';
}

/**
 * Attach event handler for idle detection toggle
 * @param {Object} worker - Worker object
 */
function attachIdleDetectionToggleHandler(worker) {
    const toggle = document.getElementById('idle-detection-toggle');
    if (!toggle) return;

    toggle.addEventListener('change', async e => {
        const isEnabled = e.target.checked;
        const workerId = worker.id;
        const region = worker.aws_region;

        // Prevent the toggle from changing until confirmed
        e.preventDefault();
        toggle.checked = !isEnabled;

        // Show confirmation modal
        const action = isEnabled ? 'enable' : 'disable';
        const title = `${action === 'enable' ? 'Enable' : 'Disable'} Idle Detection`;
        const message = `Are you sure you want to ${action} idle detection for worker <strong>${escapeHtml(worker.name || workerId)}</strong>?`;
        const detailsHtml = isEnabled ? '<small>When enabled, the worker will be automatically paused after a period of inactivity.</small>' : '<small>When disabled, the worker will not be automatically paused when idle.</small>';

        showConfirm(
            title,
            message,
            async () => {
                // Disable toggle during request
                toggle.disabled = true;

                try {
                    let result;
                    if (isEnabled) {
                        console.log(`[worker-monitoring] Enabling idle detection for worker ${workerId}`);
                        result = await enableIdleDetection(region, workerId);
                    } else {
                        console.log(`[worker-monitoring] Disabling idle detection for worker ${workerId}`);
                        result = await disableIdleDetection(region, workerId);
                    }

                    console.log('[worker-monitoring] Idle detection toggle result:', result);

                    // Update toggle to reflect successful change
                    toggle.checked = isEnabled;

                    showToast(result.message || `Idle detection ${isEnabled ? 'enabled' : 'disabled'} successfully`, 'success');

                    // Monitoring tab will be reloaded automatically via SSE WORKER_SNAPSHOT event
                } catch (error) {
                    console.error('[worker-monitoring] Failed to toggle idle detection:', error);
                    showToast(`Failed to ${action} idle detection: ${error.message}`, 'error');
                    // Keep toggle in original state (already reverted)
                } finally {
                    toggle.disabled = false;
                }
            },
            {
                actionLabel: action === 'enable' ? 'Enable' : 'Disable',
                actionClass: isEnabled ? 'btn-success' : 'btn-warning',
                iconClass: 'bi bi-moon-stars-fill text-info me-2',
                detailsHtml: detailsHtml,
                dismissOnAction: true,
            }
        );
    });
}
