/**
 * PlacementPreviewModal — AD-SCHED-001/002
 *
 * Bootstrap 5 modal showing the enriched placement preview result:
 * - Decision summary (assign / scale_up / wait)
 * - Ranked candidate list with bin-packing scores
 * - Per-worker rejection breakdown
 * - Utilization forecast (before/after) on selected worker
 * - "Run" button to execute real scheduling
 *
 * @module components/PlacementPreviewModal
 */

import * as bootstrap from 'bootstrap';
import { showToast } from '../ui/notifications.js';
import { triggerReconcile } from '../api/scheduler.js';

/** @type {HTMLElement|null} Cached modal DOM element */
let _modalEl = null;

/**
 * Ensure the modal DOM element exists (create once, reuse).
 * @returns {HTMLElement}
 */
function _ensureModalElement() {
    if (_modalEl && document.body.contains(_modalEl)) return _modalEl;

    _modalEl = document.createElement('div');
    _modalEl.className = 'modal fade';
    _modalEl.id = 'placementPreviewModal';
    _modalEl.tabIndex = -1;
    _modalEl.setAttribute('aria-labelledby', 'placementPreviewModalLabel');
    _modalEl.setAttribute('aria-hidden', 'true');
    _modalEl.innerHTML = `
        <div class="modal-dialog modal-lg modal-dialog-scrollable">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title" id="placementPreviewModalLabel">
                        <i class="bi bi-cpu me-2"></i>Placement Preview
                    </h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                </div>
                <div class="modal-body" id="placementPreviewBody">
                    <!-- Populated dynamically -->
                </div>
                <div class="modal-footer" id="placementPreviewFooter">
                    <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Close</button>
                </div>
            </div>
        </div>
    `;
    document.body.appendChild(_modalEl);
    return _modalEl;
}

/**
 * Render the decision badge based on action type.
 * @param {Object} decision
 * @returns {string} HTML
 */
function _renderDecisionBadge(decision) {
    const badges = {
        assign: { cls: 'bg-success', icon: 'bi-check-circle', label: 'Worker Found' },
        scale_up: { cls: 'bg-warning text-dark', icon: 'bi-arrow-up-circle', label: 'Scale Up Required' },
        wait: { cls: 'bg-info', icon: 'bi-hourglass-split', label: 'Wait (retry)' },
    };
    const b = badges[decision.action] || badges.wait;
    return `<span class="badge ${b.cls} fs-6"><i class="bi ${b.icon} me-1"></i>${b.label}</span>`;
}

/**
 * Render the decision summary card.
 * @param {Object} result - Full preview result
 * @returns {string} HTML
 */
function _renderDecisionSummary(result) {
    const d = result.decision;
    return `
        <div class="card shadow-sm mb-3">
            <div class="card-body">
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <h6 class="mb-0">Decision</h6>
                    ${_renderDecisionBadge(d)}
                </div>
                <p class="mb-1 text-muted small">${_escapeHtml(d.reason)}</p>
                ${d.worker_id ? `<div class="small"><strong>Worker:</strong> <code>${d.worker_id.substring(0, 12)}…</code></div>` : ''}
                ${d.worker_template ? `<div class="small"><strong>Template:</strong> ${_escapeHtml(d.worker_template)}</div>` : ''}
                <div class="small text-muted mt-1">
                    Definition: <strong>${_escapeHtml(result.definition_name)}</strong>
                    • ${result.total_workers_evaluated} worker(s) evaluated
                </div>
            </div>
        </div>
    `;
}

/**
 * Render utilization forecast progress bars.
 * @param {Object|null} forecast
 * @returns {string} HTML
 */
function _renderUtilizationForecast(forecast) {
    if (!forecast) return '';

    const metrics = [
        { label: 'CPU', before: forecast.cpu_percent_before, after: forecast.cpu_percent_after, icon: 'bi-cpu' },
        { label: 'Memory', before: forecast.memory_percent_before, after: forecast.memory_percent_after, icon: 'bi-memory' },
        { label: 'Storage', before: forecast.storage_percent_before, after: forecast.storage_percent_after, icon: 'bi-hdd' },
    ];

    const bars = metrics
        .map(m => {
            const barColor = m.after > 90 ? 'bg-danger' : m.after > 70 ? 'bg-warning' : 'bg-success';
            return `
            <div class="mb-2">
                <div class="d-flex justify-content-between small">
                    <span><i class="bi ${m.icon} me-1"></i>${m.label}</span>
                    <span>${m.before.toFixed(1)}% → <strong>${m.after.toFixed(1)}%</strong></span>
                </div>
                <div class="progress" style="height: 8px;">
                    <div class="progress-bar bg-secondary" style="width: ${m.before}%" title="Current"></div>
                    <div class="progress-bar ${barColor} progress-bar-striped" style="width: ${Math.max(0, m.after - m.before)}%" title="After placement"></div>
                </div>
            </div>
        `;
        })
        .join('');

    return `
        <div class="card shadow-sm mb-3">
            <div class="card-header bg-white py-2">
                <h6 class="mb-0"><i class="bi bi-graph-up me-1"></i>Utilization Forecast — ${_escapeHtml(forecast.worker_name)}</h6>
            </div>
            <div class="card-body py-2">
                ${bars}
                <div class="small text-muted mt-1">
                    Sessions: ${forecast.session_count_before} → <strong>${forecast.session_count_after}</strong>
                </div>
            </div>
        </div>
    `;
}

/**
 * Render candidates table (ranked by score).
 * @param {Array} candidates
 * @returns {string} HTML
 */
function _renderCandidates(candidates) {
    if (!candidates || candidates.length === 0) return '';

    const rows = candidates
        .map((c, i) => {
            const rank = i + 1;
            const badge = rank === 1 ? '<span class="badge bg-success ms-1">selected</span>' : '';
            return `
            <tr${rank === 1 ? ' class="table-success"' : ''}>
                <td class="text-center">${rank}</td>
                <td>${_escapeHtml(c.worker_name)}${badge}</td>
                <td class="text-end"><strong>${c.score.toFixed(4)}</strong></td>
                <td class="text-end">${(c.cpu_utilization * 100).toFixed(1)}%</td>
                <td class="text-end">${(c.memory_utilization * 100).toFixed(1)}%</td>
                <td class="text-center">${c.session_count}</td>
                <td class="text-end">${c.locality_bonus > 0 ? '+' + (c.locality_bonus * 100).toFixed(1) + '%' : '—'}</td>
            </tr>
        `;
        })
        .join('');

    return `
        <div class="card shadow-sm mb-3">
            <div class="card-header bg-white py-2">
                <h6 class="mb-0"><i class="bi bi-bar-chart me-1"></i>Candidate Workers (${candidates.length})</h6>
            </div>
            <div class="card-body p-0">
                <div class="table-responsive">
                    <table class="table table-sm table-hover mb-0">
                        <thead class="table-light">
                            <tr>
                                <th class="text-center" style="width:40px">#</th>
                                <th>Worker</th>
                                <th class="text-end">Score</th>
                                <th class="text-end">CPU%</th>
                                <th class="text-end">Mem%</th>
                                <th class="text-center">Sessions</th>
                                <th class="text-end">Locality</th>
                            </tr>
                        </thead>
                        <tbody>${rows}</tbody>
                    </table>
                </div>
            </div>
        </div>
    `;
}

/**
 * Render rejection breakdown.
 * @param {Array} rejections
 * @returns {string} HTML
 */
function _renderRejections(rejections) {
    if (!rejections || rejections.length === 0) return '';

    // Group by category
    const grouped = {};
    for (const r of rejections) {
        if (!grouped[r.reason_category]) grouped[r.reason_category] = [];
        grouped[r.reason_category].push(r);
    }

    const categoryIcons = {
        status: 'bi-power text-secondary',
        license: 'bi-key text-warning',
        capacity: 'bi-hdd-stack text-danger',
        ami: 'bi-box text-info',
        ports: 'bi-plug text-primary',
    };

    const sections = Object.entries(grouped)
        .map(([category, items]) => {
            const icon = categoryIcons[category] || 'bi-x-circle text-muted';
            const itemRows = items.map(r => `<li class="list-group-item py-1 small">${_escapeHtml(r.worker_name)}: ${_escapeHtml(r.reason_detail)}</li>`).join('');

            return `
            <div class="mb-2">
                <div class="d-flex align-items-center gap-1 mb-1">
                    <i class="bi ${icon}"></i>
                    <strong class="text-capitalize small">${category}</strong>
                    <span class="badge bg-secondary rounded-pill">${items.length}</span>
                </div>
                <ul class="list-group list-group-flush">${itemRows}</ul>
            </div>
        `;
        })
        .join('');

    return `
        <div class="card shadow-sm mb-3">
            <div class="card-header bg-white py-2">
                <h6 class="mb-0"><i class="bi bi-funnel me-1"></i>Rejected Workers (${rejections.length})</h6>
            </div>
            <div class="card-body py-2">${sections}</div>
        </div>
    `;
}

/**
 * Escape HTML entities.
 * @param {string} str
 * @returns {string}
 */
function _escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

/**
 * Show the placement preview modal with results.
 *
 * @param {Object} result - PlacementPreviewResult from the API
 * @param {Object} [options] - Display options
 * @param {boolean} [options.showRunButton=true] - Show "Run" button for real scheduling
 * @param {Function} [options.onRun] - Callback when "Run" is clicked
 */
export function showPlacementPreviewModal(result, options = {}) {
    const { showRunButton = true, onRun } = options;
    const modalEl = _ensureModalElement();
    const body = modalEl.querySelector('#placementPreviewBody');
    const footer = modalEl.querySelector('#placementPreviewFooter');

    // Update title with definition name
    const titleEl = modalEl.querySelector('#placementPreviewModalLabel');
    titleEl.innerHTML = `<i class="bi bi-cpu me-2"></i>Placement Preview — ${_escapeHtml(result.definition_name)}`;

    // Render body sections
    body.innerHTML = [_renderDecisionSummary(result), _renderUtilizationForecast(result.utilization_forecast), _renderCandidates(result.candidates), _renderRejections(result.rejections)].join('');

    // Render footer with optional Run button
    footer.innerHTML = `
        <small class="text-muted me-auto">
            <i class="bi bi-info-circle me-1"></i>Preview only — no changes applied
        </small>
        ${
            showRunButton
                ? `<button type="button" class="btn btn-primary" id="previewRunBtn">
                    <i class="bi bi-play-fill me-1"></i>Run
                </button>`
                : ''
        }
        <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Close</button>
    `;

    // Bind Run button
    if (showRunButton) {
        const runBtn = footer.querySelector('#previewRunBtn');
        runBtn?.addEventListener('click', async () => {
            runBtn.disabled = true;
            runBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Running…';
            try {
                if (onRun) {
                    await onRun();
                } else {
                    // Default: trigger reconciliation cycle
                    await triggerReconcile();
                    showToast('Scheduling triggered — reconciliation cycle started', 'success');
                }
                bootstrap.Modal.getInstance(modalEl)?.hide();
            } catch (err) {
                console.error('[PlacementPreviewModal] Run failed:', err);
                showToast(`Scheduling failed: ${err.message}`, 'error');
                runBtn.disabled = false;
                runBtn.innerHTML = '<i class="bi bi-play-fill me-1"></i>Run';
            }
        });
    }

    // Show modal
    const bsModal = bootstrap.Modal.getOrCreateInstance(modalEl);
    bsModal.show();
}
