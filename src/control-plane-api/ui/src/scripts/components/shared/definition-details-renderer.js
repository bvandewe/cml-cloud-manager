/**
 * Shared rendering utilities for Lablet Definition details modal.
 *
 * Used by both LabletsPage and SessionsPage to render the definition
 * details modal with content synchronization status, per-service sync
 * cards, logs accordion, and content viewer.
 *
 * @module components/shared/definition-details-renderer
 */

import { apiRequest } from '../../api/client.js';
import '../core/LcmCodeViewer.js';

/**
 * Render the full definition details HTML for the modal body.
 * Uses a tabbed layout: Overview | Content Sync | Definition Content
 * @param {Object} def - The full LabletDefinitionDto
 * @param {Function} formatDateTime - Datetime formatting function
 * @returns {string} HTML string
 */
export function renderDefinitionDetailsHtml(def, formatDateTime) {
    const uss = def.upstream_sync_status || {};
    const bucketUrl = buildObjectStorageUrl(def);
    const hasContent = def.cml_yaml_content || def.devices_json || def.content_xml_content || def.user_visible_devices?.length;

    return `
        <!-- Tab Navigation -->
        <ul class="nav nav-tabs mb-3" id="defDetailTabs" role="tablist">
            <li class="nav-item" role="presentation">
                <button class="nav-link active" id="defTab-overview-btn" data-bs-toggle="tab"
                    data-bs-target="#defTab-overview" type="button" role="tab"
                    aria-controls="defTab-overview" aria-selected="true">
                    <i class="bi bi-info-circle me-1"></i>Overview
                </button>
            </li>
            <li class="nav-item" role="presentation">
                <button class="nav-link" id="defTab-sync-btn" data-bs-toggle="tab"
                    data-bs-target="#defTab-sync" type="button" role="tab"
                    aria-controls="defTab-sync" aria-selected="false">
                    <i class="bi bi-cloud-download me-1"></i>Content Sync
                    <lcm-status-badge status="${def.sync_status || 'none'}" class="ms-1"></lcm-status-badge>
                </button>
            </li>
            ${
                hasContent
                    ? `
            <li class="nav-item" role="presentation">
                <button class="nav-link" id="defTab-content-btn" data-bs-toggle="tab"
                    data-bs-target="#defTab-content" type="button" role="tab"
                    aria-controls="defTab-content" aria-selected="false">
                    <i class="bi bi-file-earmark-code me-1"></i>Definition Content
                </button>
            </li>
            `
                    : ''
            }
        </ul>

        <!-- Tab Content -->
        <div class="tab-content" id="defDetailTabContent">
            <!-- ═══ OVERVIEW TAB ═══ -->
            <div class="tab-pane fade show active" id="defTab-overview" role="tabpanel" aria-labelledby="defTab-overview-btn">
                <div class="row g-2">
                    <div class="col-md-6">
                        <div class="section-title"><i class="bi bi-info-circle me-1"></i>Basic Information</div>
                        <dl class="row mb-0 dl-compact">
                            <dt class="col-sm-4">Name</dt><dd class="col-sm-8">${def.name || '—'}</dd>
                            <dt class="col-sm-4">Version</dt><dd class="col-sm-8">${def.version || '—'}</dd>
                            <dt class="col-sm-4">Status</dt><dd class="col-sm-8"><lcm-status-badge status="${def.status || 'unknown'}"></lcm-status-badge></dd>
                            <dt class="col-sm-4">Form QN</dt><dd class="col-sm-8">${def.form_qualified_name || '—'}</dd>
                            <dt class="col-sm-4">Bucket Name</dt>
                            <dd class="col-sm-8">${bucketUrl ? `<a href="${bucketUrl}" target="_blank" rel="noopener" class="text-decoration-none font-monospace" title="Browse in RustFS Console"><code>${_escapeAttr(def.bucket_name)}</code> <i class="bi bi-box-arrow-up-right small"></i></a>` : `<code>${_escapeAttr(def.bucket_name || '—')}</code>`}</dd>
                        </dl>
                    </div>
                    <div class="col-md-6">
                        <div class="section-title"><i class="bi bi-cpu me-1"></i>Resource Requirements ${_renderResourceSourceBadge(def)}</div>
                        <dl class="row mb-0 dl-compact">
                            <dt class="col-sm-4">CPU Cores</dt><dd class="col-sm-8">${def.resource_requirements?.cpu_cores ?? '—'}</dd>
                            <dt class="col-sm-4">Memory</dt><dd class="col-sm-8">${def.resource_requirements?.memory_gb ?? '—'} GB</dd>
                            <dt class="col-sm-4">Storage</dt><dd class="col-sm-8">${def.resource_requirements?.storage_gb ?? '—'} GB</dd>
                            <dt class="col-sm-4">Nodes</dt><dd class="col-sm-8">${def.node_count ?? '—'}</dd>
                            <dt class="col-sm-4">Links</dt><dd class="col-sm-8">${def.port_template?.port_count ?? '—'}</dd>
                            <dt class="col-sm-4">Nested Virt</dt><dd class="col-sm-8">${def.resource_requirements?.nested_virt ? '<i class="bi bi-check-circle text-success"></i> Yes' : '<i class="bi bi-x-circle text-muted"></i> No'}</dd>
                        </dl>
                        ${_renderResourceDefaultsNote(def)}
                    </div>
                </div>

                <div class="row g-2 mt-1">
                    <div class="col-md-6">
                        <div class="section-title"><i class="bi bi-clock me-1"></i>Lifecycle</div>
                        <dl class="row mb-0 dl-compact">
                            <dt class="col-sm-5">Max Duration</dt><dd class="col-sm-7">${def.max_duration_minutes ?? '—'} min</dd>
                            <dt class="col-sm-5">Warm Pool</dt><dd class="col-sm-7">${def.warm_pool_depth ?? 0}</dd>
                            <dt class="col-sm-5">Boot Lead Time</dt><dd class="col-sm-7">${def.boot_lead_time_minutes != null ? def.boot_lead_time_minutes + ' min' : '<span class="text-muted">Global default</span>'}</dd>
                            <dt class="col-sm-5">License</dt><dd class="col-sm-7">${(def.license_affinity || []).join(', ') || '—'}</dd>
                        </dl>
                    </div>
                    <div class="col-md-6">
                        ${_renderPortDefinitionsTable(def)}
                    </div>
                </div>

                <!-- Devices from content.xml -->
                ${_renderDevicesTable(def)}
                ${_renderPortConflictsWarning(def)}
            </div>

            <!-- ═══ CONTENT SYNC TAB ═══ -->
            <div class="tab-pane fade" id="defTab-sync" role="tabpanel" aria-labelledby="defTab-sync-btn">
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <div class="section-title mb-0"><i class="bi bi-cloud-download me-1"></i>Content Synchronization</div>
                    <div>
                        <lcm-status-badge status="${def.sync_status || 'none'}" title="Overall Sync Status"></lcm-status-badge>
                        ${def.last_synced_at ? `<small class="text-muted ms-2">Last synced: ${formatDateTime(def.last_synced_at)}</small>` : ''}
                    </div>
                </div>

                <!-- Upstream metadata summary -->
                <div class="row mb-3">
                    <div class="col-md-6">
                        <dl class="row mb-0 dl-compact">
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
                        <dl class="row mb-0 dl-compact">
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

            <!-- ═══ DEFINITION CONTENT TAB ═══ -->
            ${
                hasContent
                    ? `
            <div class="tab-pane fade" id="defTab-content" role="tabpanel" aria-labelledby="defTab-content-btn">
                <div id="definition-content-viewer"></div>
            </div>
            `
                    : ''
            }
        </div>

        <!-- Footer metadata -->
        <div class="mt-3 pt-2 border-top">
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
    if (!def.cml_yaml_content && !def.devices_json && !def.content_xml_content && !def.user_visible_devices?.length) return;

    const viewerContainer = container.querySelector('#definition-content-viewer');
    if (!viewerContainer) return;

    // Defer mounting until the content tab is shown (hidden tabs have 0 dimensions)
    const contentTab = container.querySelector('#defTab-content-btn');
    if (contentTab) {
        let mounted = false;
        contentTab.addEventListener('shown.bs.tab', () => {
            if (!mounted) {
                mounted = true;
                _doMountContentViewer(viewerContainer, def);
            }
        });
    } else {
        // Fallback: mount immediately if tabs not found
        _doMountContentViewer(viewerContainer, def);
    }
}

/**
 * Mount event handlers for port preference save button (AD-LDS-002 Phase 3).
 * Call after innerHTML is set on the modal body.
 * @param {HTMLElement} container - The modal body container
 */
export function mountPortPreferenceHandlers(container) {
    const saveBtn = container.querySelector('.port-pref-save-btn');
    if (!saveBtn) return;

    saveBtn.addEventListener('click', async () => {
        const definitionId = saveBtn.dataset.definitionId;
        const statusEl = container.querySelector('.port-pref-status');
        const selects = container.querySelectorAll('.port-pref-select');

        // Collect preferences from dropdowns
        const preferences = {};
        selects.forEach(sel => {
            const device = sel.dataset.device;
            const selectedOption = sel.options[sel.selectedIndex];
            // Only store preference if it's NOT the auto-resolved default
            // (auto options have text ending with "(auto)")
            if (selectedOption && !selectedOption.textContent.endsWith('(auto)')) {
                preferences[device] = sel.value;
            }
        });

        saveBtn.disabled = true;
        if (statusEl) statusEl.textContent = 'Saving...';

        try {
            await apiRequest(`/api/lablet-definitions/${encodeURIComponent(definitionId)}/port-preferences`, {
                method: 'PATCH',
                body: JSON.stringify({ lds_port_preferences: preferences }),
            });
            if (statusEl) {
                statusEl.innerHTML = '<span class="text-success"><i class="bi bi-check-circle me-1"></i>Saved</span>';
                setTimeout(() => {
                    statusEl.textContent = '';
                }, 3000);
            }
        } catch (err) {
            if (statusEl) {
                statusEl.innerHTML = `<span class="text-danger"><i class="bi bi-exclamation-circle me-1"></i>${err.message}</span>`;
            }
        } finally {
            saveBtn.disabled = false;
        }
    });
}

function _doMountContentViewer(viewerContainer, def) {
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

    // Reconstruct content.xml from raw content or user_visible_devices
    if (def.content_xml_content) {
        files.push({
            name: 'content.xml',
            content: def.content_xml_content,
            language: 'xml',
        });
    } else if (def.user_visible_devices && def.user_visible_devices.length > 0) {
        // Fallback: reconstruct from extracted device data
        const contentXml = _reconstructContentXml(def);
        files.push({
            name: 'content.xml',
            content: contentXml,
            language: 'xml',
        });
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
 * Render a badge indicating whether resource requirements are configured or at defaults.
 * @param {Object} def - The full LabletDefinitionDto
 * @returns {string} HTML badge string
 */
function _renderResourceSourceBadge(def) {
    const rr = def.resource_requirements;
    if (!rr) return '';

    const isDefault = (rr.cpu_cores === 2 || !rr.cpu_cores) && (rr.memory_gb === 4 || !rr.memory_gb) && (rr.storage_gb === 20 || !rr.storage_gb);

    if (isDefault) {
        return '<span class="badge bg-warning text-dark badge-sm ms-1" title="Using system defaults — run a session observation to refine"><i class="bi bi-exclamation-triangle me-1"></i>Defaults</span>';
    }
    return '<span class="badge bg-info text-dark badge-sm ms-1" title="Resource values were explicitly configured"><i class="bi bi-pencil-square me-1"></i>Configured</span>';
}

/**
 * Render port definitions table in definition details (Phase 3 — ADR-030 UX).
 * Max 8 rows visible, then vertical scrollbar kicks in.
 */
function _renderPortDefinitionsTable(def) {
    const ports = def.port_template?.ports || def.port_definitions || [];
    if (ports.length === 0) return '';

    const portRows = ports
        .map(p => {
            const appProto = _inferAppProtocol(p.name);
            const protoLabel = appProto.label;
            const protoIcon = appProto.icon;
            return `
        <tr>
            <td class="font-monospace small py-1">${_escapeAttr(p.name || '—')}</td>
            <td class="text-center py-1" title="${_escapeAttr(p.protocol || 'tcp').toUpperCase()}"><i class="bi ${protoIcon} me-1 small"></i>${protoLabel}</td>
            <td class="text-center py-1">${p.port || '—'}</td>
        </tr>
    `;
        })
        .join('');

    return `
        <div class="section-title">
            <i class="bi bi-plug me-1"></i>Port Definitions
            <span class="badge bg-secondary ms-1">${ports.length}</span>
        </div>
        <div class="table-responsive" style="max-height: 200px; overflow-y: auto;">
            <table class="table table-sm table-bordered mb-0" style="font-size: 0.8rem;">
                <thead class="table-light" style="position: sticky; top: 0; z-index: 1;">
                    <tr>
                        <th class="py-1">Name</th>
                        <th class="text-center py-1">Service</th>
                        <th class="text-center py-1">Port</th>
                    </tr>
                </thead>
                <tbody>${portRows}</tbody>
            </table>
        </div>
    `;
}

/**
 * Render devices table from user_visible_devices (extracted from content.xml).
 * Shows device labels, access modes, and categories.
 */
function _renderDevicesTable(def) {
    const devices = def.user_visible_devices;
    if (!devices || devices.length === 0) return '';

    const accessModeIcons = {
        web: { icon: 'bi-globe', label: 'Web' },
        terminal: { icon: 'bi-terminal', label: 'Terminal' },
        vnc: { icon: 'bi-display', label: 'VNC' },
        ssh: { icon: 'bi-key', label: 'SSH' },
    };

    const deviceRows = devices
        .map(d => {
            const mode = accessModeIcons[d.user_access_mode] || { icon: 'bi-box', label: d.user_access_mode || '—' };
            return `
            <tr>
                <td class="font-monospace small py-1">${_escapeAttr(d.device_label || '—')}</td>
                <td class="py-1">${_escapeAttr(d.category || '—')}</td>
                <td class="text-center py-1"><i class="bi ${mode.icon} me-1 small"></i>${mode.label}</td>
            </tr>`;
        })
        .join('');

    return `
        <div class="row g-3 mt-2">
            <div class="col-md-6">
                <div class="section-title"><i class="bi bi-pc-display me-1"></i>Devices <span class="badge bg-secondary ms-1">${devices.length}</span></div>
                <div class="table-responsive" style="max-height: 200px; overflow-y: auto;">
                    <table class="table table-sm table-bordered mb-0" style="font-size: 0.8rem;">
                        <thead class="table-light" style="position: sticky; top: 0; z-index: 1;">
                            <tr>
                                <th class="py-1">Device Label</th>
                                <th class="py-1">Category</th>
                                <th class="text-center py-1">Access Mode</th>
                            </tr>
                        </thead>
                        <tbody>${deviceRows}</tbody>
                    </table>
                </div>
            </div>
        </div>
    `;
}

/**
 * Render a warning alert when multi-port device conflicts are detected (AD-LDS-002).
 * Shows which devices have multiple ports and which port was auto-resolved.
 */
function _renderPortConflictsWarning(def) {
    const conflicts = def.port_conflicts;
    if (!conflicts || conflicts.length === 0) return '';

    const preferences = def.lds_port_preferences || {};

    const conflictRows = conflicts
        .map(c => {
            const deviceLabel = c.device_label || '';
            const availablePorts = c.available_ports || [];
            const currentPref = preferences[deviceLabel];
            const resolvedPort = currentPref || c.resolved_port || '—';
            const isOverridden = currentPref && currentPref !== c.resolved_port;

            // Build dropdown options
            const options = availablePorts
                .map(p => {
                    const selected = p === resolvedPort ? 'selected' : '';
                    const isDefault = p === c.resolved_port;
                    const label = isDefault ? `${_escapeAttr(p)} (auto)` : _escapeAttr(p);
                    return `<option value="${_escapeAttr(p)}" ${selected}>${label}</option>`;
                })
                .join('');

            const resolvedBadge = isOverridden ? `<span class="badge bg-info text-dark">override</span>` : `<span class="badge bg-secondary">auto</span>`;

            return `
            <tr>
                <td class="font-monospace small py-1">${_escapeAttr(deviceLabel)}</td>
                <td class="small py-1">
                    <select class="form-select form-select-sm port-pref-select"
                            data-device="${_escapeAttr(deviceLabel)}"
                            style="font-size: 0.75rem; padding: 0.15rem 1.5rem 0.15rem 0.4rem; height: auto;">
                        ${options}
                    </select>
                </td>
                <td class="small py-1">${resolvedBadge}</td>
            </tr>`;
        })
        .join('');

    return `
        <div class="row g-3 mt-2">
            <div class="col-12">
                <div class="alert alert-warning py-2 px-3 mb-0 small">
                    <i class="bi bi-exclamation-triangle-fill me-1"></i>
                    <strong>Port Conflicts (${conflicts.length})</strong> — These devices have multiple CML port annotations.
                    Select a preferred port per device, or leave on <em>(auto)</em> for protocol-priority resolution.
                    <div class="table-responsive mt-2" style="max-height: 200px; overflow-y: auto;">
                        <table class="table table-sm table-bordered mb-0 bg-white" style="font-size: 0.78rem;">
                            <thead class="table-light" style="position: sticky; top: 0; z-index: 1;">
                                <tr>
                                    <th class="py-1">Device</th>
                                    <th class="py-1">Preferred Port</th>
                                    <th class="py-1">Mode</th>
                                </tr>
                            </thead>
                            <tbody>${conflictRows}</tbody>
                        </table>
                    </div>
                    <div class="mt-2 text-end">
                        <button class="btn btn-sm btn-outline-primary port-pref-save-btn"
                                data-definition-id="${_escapeAttr(def.id)}"
                                title="Save port preferences">
                            <i class="bi bi-check-lg me-1"></i>Save Preferences
                        </button>
                        <span class="port-pref-status ms-2 small"></span>
                    </div>
                </div>
            </div>
        </div>
    `;
}

/**
 * Reconstruct a representative content.xml from user_visible_devices data.
 * This is an approximation since we only store the extracted device elements.
 */
function _reconstructContentXml(def) {
    const devices = def.user_visible_devices || [];
    const deviceElements = devices
        .map(d => {
            const attrs = [];
            if (d.category) attrs.push(`category="${_escapeAttr(d.category)}"`);
            if (d.device_label) attrs.push(`device_label="${_escapeAttr(d.device_label)}"`);
            if (d.user_access_mode) attrs.push(`user_access_mode="${_escapeAttr(d.user_access_mode)}"`);
            return `        <device ${attrs.join(' ')}/>`;
        })
        .join('\n');

    return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<lab_content version="3">
    <title>${_escapeAttr(def.name || 'Lablet')}</title>
    <device>
${deviceElements}
    </device>
</lab_content>`;
}

/**
 * Infer the application-level protocol from a CML port definition name.
 *
 * CML port names follow the convention: {node_label}_{protocol} where
 * protocol is the CML annotation (serial, vnc, ssh, telnet, http, https).
 * Additional heuristics handle PAT-style names (e.g., "pat_22" → SSH).
 *
 * @param {string} portName - Port definition name (e.g., "rtr01_serial", "workstation_vnc")
 * @returns {{ label: string, icon: string }} Display label and Bootstrap icon
 */
function _inferAppProtocol(portName) {
    if (!portName) return { label: 'TCP', icon: 'bi-hdd-network' };
    const name = portName.toLowerCase();

    // Direct suffix matches from CML annotations
    if (name.endsWith('_serial') || name.endsWith('_telnet')) {
        return { label: 'Telnet', icon: 'bi-terminal' };
    }
    if (name.endsWith('_vnc')) {
        return { label: 'VNC', icon: 'bi-display' };
    }
    if (name.endsWith('_ssh')) {
        return { label: 'SSH', icon: 'bi-key' };
    }
    if (name.endsWith('_https')) {
        return { label: 'HTTPS', icon: 'bi-lock' };
    }
    if (name.endsWith('_http')) {
        return { label: 'HTTP', icon: 'bi-globe' };
    }
    if (name.endsWith('_rdp')) {
        return { label: 'RDP', icon: 'bi-pc-display' };
    }

    // PAT-style heuristics: pat_22 → SSH, pat_443 → HTTPS, pat_80 → HTTP, etc.
    const patMatch = name.match(/pat_(\d+)$/);
    if (patMatch) {
        const port = parseInt(patMatch[1], 10);
        if (port === 22) return { label: 'SSH', icon: 'bi-key' };
        if (port === 23) return { label: 'Telnet', icon: 'bi-terminal' };
        if (port === 80) return { label: 'HTTP', icon: 'bi-globe' };
        if (port === 443) return { label: 'HTTPS', icon: 'bi-lock' };
        if (port === 3389) return { label: 'RDP', icon: 'bi-pc-display' };
        if (port === 5900 || port === 5901) return { label: 'VNC', icon: 'bi-display' };
        return { label: `TCP/${port}`, icon: 'bi-hdd-network' };
    }

    // Fallback: generic TCP
    return { label: 'TCP', icon: 'bi-hdd-network' };
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
