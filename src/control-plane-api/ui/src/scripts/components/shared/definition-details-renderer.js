/**
 * Shared rendering utilities for Lablet Definition details modal.
 *
 * Used by both LabletsPage and SessionsPage to render the definition
 * details modal with content synchronization status, per-service sync
 * cards, logs accordion, and content viewer.
 *
 * @module components/shared/definition-details-renderer
 */

import '../core/LcmCodeViewer.js';

/**
 * Render the full definition details HTML for the modal body.
 * @param {Object} def - The full LabletDefinitionDto
 * @param {Function} formatDateTime - Datetime formatting function
 * @returns {string} HTML string
 */
export function renderDefinitionDetailsHtml(def, formatDateTime) {
    const uss = def.upstream_sync_status || {};

    return `
        <!-- Basic Information + Resource Requirements -->
        <div class="row g-3">
            <div class="col-md-6">
                <h6 class="text-muted mb-2"><i class="bi bi-info-circle me-1"></i>Basic Information</h6>
                <dl class="row mb-0">
                    <dt class="col-sm-4">Name</dt><dd class="col-sm-8">${def.name || '—'}</dd>
                    <dt class="col-sm-4">Version</dt><dd class="col-sm-8">${def.version || '—'}</dd>
                    <dt class="col-sm-4">Status</dt><dd class="col-sm-8"><lcm-status-badge status="${def.status || 'unknown'}"></lcm-status-badge></dd>
                    <dt class="col-sm-4">Form QN</dt><dd class="col-sm-8">${def.form_qualified_name || '—'}</dd>
                    <dt class="col-sm-4">Bucket Name</dt><dd class="col-sm-8"><code>${def.bucket_name || '—'}</code></dd>
                </dl>
            </div>
            <div class="col-md-6">
                <h6 class="text-muted mb-2"><i class="bi bi-cpu me-1"></i>Resource Requirements</h6>
                <dl class="row mb-0">
                    <dt class="col-sm-4">CPU Cores</dt><dd class="col-sm-8">${def.resource_requirements?.cpu_cores ?? '—'}</dd>
                    <dt class="col-sm-4">Memory</dt><dd class="col-sm-8">${def.resource_requirements?.memory_gb ?? '—'} GB</dd>
                    <dt class="col-sm-4">Storage</dt><dd class="col-sm-8">${def.resource_requirements?.storage_gb ?? '—'} GB</dd>
                    <dt class="col-sm-4">Nodes</dt><dd class="col-sm-8">${def.node_count ?? '—'}</dd>
                    <dt class="col-sm-4">Links</dt><dd class="col-sm-8">${def.port_template?.port_count ?? '—'}</dd>
                    <dt class="col-sm-4">Nested Virt</dt><dd class="col-sm-8">${def.resource_requirements?.nested_virt ? '<i class="bi bi-check-circle text-success"></i> Yes' : '<i class="bi bi-x-circle text-muted"></i> No'}</dd>
                </dl>
                ${_renderResourceDefaultsNote(def)}
                ${_renderPortDefinitionsTable(def)}
                <h6 class="text-muted mb-2 mt-3"><i class="bi bi-clock me-1"></i>Lifecycle</h6>
                <dl class="row mb-0">
                    <dt class="col-sm-5">Max Duration</dt><dd class="col-sm-7">${def.max_duration_minutes ?? '—'} min</dd>
                    <dt class="col-sm-5">Warm Pool</dt><dd class="col-sm-7">${def.warm_pool_depth ?? 0}</dd>
                    <dt class="col-sm-5">Boot Lead Time</dt><dd class="col-sm-7">${def.boot_lead_time_minutes != null ? def.boot_lead_time_minutes + ' min' : '<span class="text-muted">Global default</span>'}</dd>
                    <dt class="col-sm-5">License</dt><dd class="col-sm-7">${(def.license_affinity || []).join(', ') || '—'}</dd>
                </dl>
            </div>
        </div>

        <hr class="my-3">

        <!-- Content Synchronization Section -->
        <div class="row g-3">
            <div class="col-12">
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <h6 class="text-muted mb-0"><i class="bi bi-cloud-download me-1"></i>Content Synchronization</h6>
                    <div>
                        <lcm-status-badge status="${def.sync_status || 'none'}" title="Overall Sync Status"></lcm-status-badge>
                        ${def.last_synced_at ? `<small class="text-muted ms-2">Last synced: ${formatDateTime(def.last_synced_at)}</small>` : ''}
                    </div>
                </div>

                <!-- Upstream metadata summary -->
                <div class="row mb-3">
                    <div class="col-md-6">
                        <dl class="row mb-0 small">
                            <dt class="col-sm-5">Content Hash</dt>
                            <dd class="col-sm-7">
                                ${def.content_package_hash ? `<code class="small user-select-all" title="${def.content_package_hash}">${def.content_package_hash}</code>` : '—'}
                            </dd>
                            <dt class="col-sm-5">Upstream Version</dt>
                            <dd class="col-sm-7">${def.upstream_version || '—'}</dd>
                            <dt class="col-sm-5">Date Published</dt>
                            <dd class="col-sm-7">${def.upstream_date_published ? formatDateTime(def.upstream_date_published) : '—'}</dd>
                        </dl>
                    </div>
                    <div class="col-md-6">
                        <dl class="row mb-0 small">
                            <dt class="col-sm-5">Mosaic Instance</dt>
                            <dd class="col-sm-7">${def.upstream_instance_name || '—'}</dd>
                            <dt class="col-sm-5">Session Package</dt>
                            <dd class="col-sm-7">${def.user_session_package_name || '—'}</dd>
                            <dt class="col-sm-5">Session Type</dt>
                            <dd class="col-sm-7">${def.user_session_type || '—'}</dd>
                        </dl>
                    </div>
                </div>

                <!-- Per-service sync status cards -->
                <div class="row g-2 mb-3">
                    ${renderServiceSyncCard('mosaic_source', 'Upstream Source', 'bi-cloud-arrow-up', uss.mosaic_source, def)}
                    ${renderServiceSyncCard('object_storage', 'Object Storage', 'bi-bucket', uss.object_storage, def)}
                    ${renderServiceSyncCard('lds', 'LDS Backend', 'bi-server', uss.lds, def)}
                    ${renderServiceSyncCard('grading_engine', 'Grading Engine', 'bi-mortarboard', uss.grading_engine, def)}
                    ${renderServiceSyncCard('environment_resolver', 'Env Resolver', 'bi-diagram-3', uss.environment_resolver, def)}
                </div>

                <!-- Per-service sync logs accordion -->
                ${renderSyncLogsAccordion(uss, formatDateTime)}
            </div>
        </div>

        <!-- Content Viewer Section -->
        ${
            def.cml_yaml_content || def.devices_json
                ? `
        <hr class="my-3">
        <div class="row g-3">
            <div class="col-12">
                <h6 class="text-muted mb-2"><i class="bi bi-file-earmark-code me-1"></i>Definition Content</h6>
                <div id="definition-content-viewer"></div>
            </div>
        </div>
        `
                : ''
        }

        <!-- Footer metadata -->
        <div class="mt-3 pt-3 border-top">
            <small class="text-muted">
                ID: <code class="user-select-all">${def.id || '—'}</code>
                ${def.created_at ? ` | Created: ${formatDateTime(def.created_at)}` : ''}
                ${def.updated_at ? ` | Updated: ${formatDateTime(def.updated_at)}` : ''}
            </small>
        </div>
    `;
}

/**
 * Mount the code viewer for definition content (call after innerHTML is set).
 * @param {HTMLElement} container - The modal body container
 * @param {Object} def - The full LabletDefinitionDto
 */
export function mountDefinitionContentViewer(container, def) {
    if (!def.cml_yaml_content && !def.devices_json) return;

    const viewerContainer = container.querySelector('#definition-content-viewer');
    if (!viewerContainer) return;

    const viewer = document.createElement('lcm-code-viewer');
    const files = [];

    if (def.cml_yaml_content) {
        files.push({
            name: def.cml_yaml_path || 'cml.yaml',
            content: def.cml_yaml_content,
            language: 'yaml',
        });
    }

    if (def.devices_json) {
        try {
            const parsed = JSON.parse(def.devices_json);
            files.push({
                name: 'devices.json',
                content: JSON.stringify(parsed, null, 2),
                language: 'json',
            });
        } catch {
            files.push({
                name: 'devices.json',
                content: def.devices_json,
                language: 'json',
            });
        }
    }

    if (files.length) {
        viewer.setFiles(files);
        viewerContainer.appendChild(viewer);
    }
}

// =========================================================================
// Internal rendering helpers
// =========================================================================

/**
 * Render a "Using defaults" note when resources are at default values (Phase 1 — ADR-030 UX).
 */
function _renderResourceDefaultsNote(def) {
    const isDefault =
        (def.resource_requirements?.cpu_cores === 2 || !def.resource_requirements?.cpu_cores) &&
        (def.resource_requirements?.memory_gb === 4 || !def.resource_requirements?.memory_gb) &&
        (def.resource_requirements?.storage_gb === 20 || !def.resource_requirements?.storage_gb);

    return isDefault
        ? `<div class="small text-muted mt-1">
             <i class="bi bi-info-circle me-1"></i>Using defaults — can be refined after session observation.
           </div>`
        : '';
}

/**
 * Render port definitions table in definition details (Phase 3 — ADR-030 UX).
 */
function _renderPortDefinitionsTable(def) {
    const ports = def.port_template?.ports || def.port_definitions || [];
    if (ports.length === 0) return '';

    const portRows = ports
        .map(
            p => `
        <tr>
            <td class="font-monospace">${_escapeAttr(p.name || '—')}</td>
            <td class="text-center text-uppercase">${_escapeAttr(p.protocol || 'tcp')}</td>
            <td class="text-center">${p.port || '—'}</td>
        </tr>
    `
        )
        .join('');

    return `
        <h6 class="text-muted mb-2 mt-3">
            <i class="bi bi-plug me-1"></i>Port Definitions
            <span class="badge bg-secondary ms-1">${ports.length}</span>
        </h6>
        <div class="table-responsive">
            <table class="table table-sm table-bordered mb-0">
                <thead class="table-light">
                    <tr>
                        <th>Name</th>
                        <th class="text-center">Protocol</th>
                        <th class="text-center">Port</th>
                    </tr>
                </thead>
                <tbody>${portRows}</tbody>
            </table>
        </div>
    `;
}

function buildObjectStorageUrl(def) {
    if (!def.bucket_name) return '';
    const minioConsoleUrl = (window.APP_CONFIG?.minioConsoleUrl || 'http://localhost:9001').replace(/\/$/, '');
    return `${minioConsoleUrl}/rustfs/console/browser/${def.bucket_name}`;
}

/**
 * Build a fallback Mosaic authoring URL from upstream_sync_status metadata.
 * Template: https://{instance}/app/module/{moduleId}/formset/{formSetId}/form/{formId}
 * @param {Object} def - The full LabletDefinitionDto
 * @returns {string} URL or empty string
 */
function buildMosaicSourceUrl(def) {
    const uss = def.upstream_sync_status?.mosaic_source;
    if (!uss) return '';
    const moduleId = uss.module_id;
    const formSetId = uss.form_set_id;
    const formId = uss.form_id;
    const instanceName = uss.instance_name || def.upstream_instance_name;
    if (!moduleId || !formSetId || !formId || !instanceName) return '';
    const base = instanceName.startsWith('http') ? instanceName : `https://${instanceName}`;
    return `${base.replace(/\/$/, '')}/app/module/${moduleId}/formset/${formSetId}/form/${formId}`;
}

function renderServiceSyncCard(serviceKey, label, icon, svcStatus, def) {
    if (!svcStatus) {
        return `
            <div class="col">
                <div class="card border-0 bg-light h-100">
                    <div class="card-body py-2 px-3 text-center">
                        <i class="bi ${icon} text-muted"></i>
                        <div class="small text-muted">${label}</div>
                        <span class="badge bg-secondary">N/A</span>
                    </div>
                </div>
            </div>
        `;
    }

    const status = svcStatus.status || 'unknown';
    const badgeClass =
        {
            success: 'bg-success',
            failed: 'bg-danger',
            not_configured: 'bg-warning text-dark',
            unknown: 'bg-secondary',
        }[status] || 'bg-secondary';

    const syncedAt = svcStatus.synced_at ? _fmtShort(svcStatus.synced_at) : '';

    // Build a clickable link if URL is available
    let linkHtml = '';
    if (serviceKey === 'object_storage') {
        const consoleUrl = svcStatus.console_url || buildObjectStorageUrl(def);
        if (consoleUrl) {
            // Ensure the console URL uses the correct /rustfs/console/browser/ path
            const fixedUrl = consoleUrl.includes('/rustfs/console/browser/') ? consoleUrl : consoleUrl.replace(/\/browser\//, '/rustfs/console/browser/');
            linkHtml = `<a href="${fixedUrl}" target="_blank" rel="noopener" class="small text-decoration-none" title="Open in Object Storage Console"><i class="bi bi-box-arrow-up-right"></i> Browse</a>`;
        }
    } else if (serviceKey === 'mosaic_source') {
        const sourceUrl = svcStatus.source_url || buildMosaicSourceUrl(def);
        if (sourceUrl) {
            linkHtml = `<a href="${sourceUrl}" target="_blank" rel="noopener" class="small text-decoration-none" title="Open in Mosaic"><i class="bi bi-box-arrow-up-right"></i> Source</a>`;
        }
    }

    // Additional details per service
    let detailHtml = '';
    if (serviceKey === 'object_storage' && svcStatus.size_bytes) {
        const sizeKb = (svcStatus.size_bytes / 1024).toFixed(1);
        detailHtml = `<div class="small text-muted">${sizeKb} KB</div>`;
    } else if (serviceKey === 'lds' && svcStatus.version) {
        detailHtml = `<div class="small text-muted">v${svcStatus.version}</div>`;
    } else if (serviceKey === 'mosaic_source' && svcStatus.version) {
        detailHtml = `<div class="small text-muted">v${svcStatus.version}</div>`;
    } else if (svcStatus.error) {
        detailHtml = `<div class="small text-danger text-truncate" style="max-width: 120px;" title="${_escapeAttr(svcStatus.error)}">${_escapeAttr(svcStatus.error)}</div>`;
    }

    return `
        <div class="col">
            <div class="card border-0 bg-light h-100">
                <div class="card-body py-2 px-3 text-center">
                    <i class="bi ${icon} ${status === 'success' ? 'text-success' : status === 'failed' ? 'text-danger' : 'text-muted'}"></i>
                    <div class="small fw-medium">${label}</div>
                    <span class="badge ${badgeClass} badge-sm">${status.toUpperCase()}</span>
                    ${detailHtml}
                    ${syncedAt ? `<div class="small text-muted">${syncedAt}</div>` : ''}
                    ${linkHtml}
                </div>
            </div>
        </div>
    `;
}

function renderSyncLogsAccordion(uss, formatDateTime) {
    const services = Object.entries(uss).filter(([, svc]) => svc?.logs?.length);
    if (!services.length) return '';

    const serviceLabels = {
        environment_resolver: { label: 'Environment Resolver', icon: 'bi-diagram-3' },
        object_storage: { label: 'Object Storage', icon: 'bi-bucket' },
        lds: { label: 'LDS Backend', icon: 'bi-server' },
        grading_engine: { label: 'Grading Engine', icon: 'bi-mortarboard' },
        mosaic_source: { label: 'Upstream Source', icon: 'bi-cloud-arrow-up' },
    };

    const items = services
        .map(([key, svc]) => {
            const meta = serviceLabels[key] || { label: key, icon: 'bi-gear' };
            const statusBadge =
                svc.status === 'success'
                    ? '<span class="badge bg-success badge-sm ms-2">OK</span>'
                    : svc.status === 'failed'
                      ? '<span class="badge bg-danger badge-sm ms-2">FAIL</span>'
                      : '<span class="badge bg-secondary badge-sm ms-2">' + (svc.status || 'N/A').toUpperCase() + '</span>';

            const logsHtml = (svc.logs || [])
                .map(log => {
                    const isError = log.startsWith('ERROR');
                    return `<div class="${isError ? 'text-danger' : 'text-muted'}" style="font-family: monospace; font-size: 12px; padding: 1px 0;">
                    ${isError ? '<i class="bi bi-exclamation-circle me-1"></i>' : '<i class="bi bi-chevron-right me-1"></i>'}${_escapeAttr(log)}
                </div>`;
                })
                .join('');

            return `
            <div class="accordion-item">
                <h2 class="accordion-header" id="syncLogHead-${key}">
                    <button class="accordion-button collapsed py-2 small" type="button"
                        data-bs-toggle="collapse" data-bs-target="#syncLogBody-${key}"
                        aria-expanded="false" aria-controls="syncLogBody-${key}">
                        <i class="bi ${meta.icon} me-2"></i>${meta.label}${statusBadge}
                    </button>
                </h2>
                <div id="syncLogBody-${key}" class="accordion-collapse collapse"
                    aria-labelledby="syncLogHead-${key}" data-bs-parent="#syncLogsAccordion">
                    <div class="accordion-body py-2 px-3 bg-dark text-light" style="max-height: 200px; overflow-y: auto;">
                        ${logsHtml || '<span class="text-muted">No logs available</span>'}
                    </div>
                </div>
            </div>
        `;
        })
        .join('');

    return `
        <div class="mt-2">
            <small class="text-muted d-block mb-1">
                <i class="bi bi-journal-text me-1"></i>Sync Operation Logs
            </small>
            <div class="accordion accordion-flush" id="syncLogsAccordion">
                ${items}
            </div>
        </div>
    `;
}

function _fmtShort(isoString) {
    if (!isoString) return '';
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

function _escapeAttr(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
