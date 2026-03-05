/**
 * LabletDefinitionCard Component
 *
 * Self-contained lablet definition card with:
 * - Reactive updates via EventBus
 * - Encapsulated rendering
 * - No global state dependencies
 *
 * Usage:
 *   <lablet-definition-card definition-id="abc123"></lablet-definition-card>
 */

import { BaseComponent } from '../core/BaseComponent.js';
import { EventTypes } from '../core/EventBus.js';
import { escapeHtml } from './escape.js';
import { getLabletDefinitionStatusBadgeClass } from './status-badges.js';
import { formatDateWithRelative } from '../utils/dates.js';
import * as bootstrap from 'bootstrap';

export class LabletDefinitionCard extends BaseComponent {
    static get observedAttributes() {
        return ['definition-id', 'compact', 'data'];
    }

    constructor() {
        super();
    }

    onAttributeChange(name, oldValue, newValue) {
        if (name === 'data' && newValue && newValue !== oldValue) {
            try {
                const definition = JSON.parse(newValue);
                this.setState({ definition });
            } catch (e) {
                console.error('LabletDefinitionCard: Invalid data attribute', e);
            }
        }
    }

    onMount() {
        const definitionId = this.getAttr('definition-id');
        if (!definitionId) {
            console.error('LabletDefinitionCard: definition-id attribute is required');
            return;
        }

        // Check for initial data
        const dataAttr = this.getAttr('data');
        if (dataAttr) {
            try {
                const definition = JSON.parse(dataAttr);
                this.setState({ definition });
            } catch (e) {
                console.error('LabletDefinitionCard: Invalid initial data', e);
            }
        }

        // Subscribe to definition updates
        this.subscribe(EventTypes.LABLET_DEFINITION_UPDATED, data => {
            const id = data.id || data.definition_id;
            if (id === definitionId) {
                this.setState(prevState => ({
                    definition: { ...prevState.definition, ...data },
                }));
            }
        });

        this.subscribe(EventTypes.LABLET_DEFINITION_DELETED, data => {
            if (data.definition_id === definitionId) {
                this.remove();
            }
        });
    }

    render() {
        const definition = this._state.definition;
        if (!definition) {
            this.innerHTML = this.renderLoading();
            return;
        }

        const isCompact = this.hasAttribute('compact');
        this.innerHTML = isCompact ? this.renderCompactCard(definition) : this.renderFullCard(definition);

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
                        <span class="text-muted">Loading definition...</span>
                    </div>
                </div>
            </div>
        `;
    }

    renderFullCard(definition) {
        const status = definition.status || 'active';
        const statusBadgeClass = getLabletDefinitionStatusBadgeClass(status);

        const name = escapeHtml(definition.name || 'Unknown');
        const version = escapeHtml(definition.version || '1.0.0');
        const cpuCores = definition.cpu_cores || 0;
        const memoryGb = definition.memory_gb || 0;
        const storageGb = definition.storage_gb || 0;
        const nodeCount = definition.node_count || 0;
        const maxDuration = definition.max_duration_minutes || 60;

        const createdAt = definition.created_at ? formatDateWithRelative(definition.created_at) : 'Unknown';

        // License affinity badges
        const licenseAffinityHtml = this.renderLicenseAffinity(definition.license_affinity);

        // Port definitions
        const portDefinitionsHtml = this.renderPortDefinitions(definition.port_definitions);

        // Observation indicator (ADR-030)
        let obsIndicatorHtml = '';
        if (definition.has_observations) {
            obsIndicatorHtml = definition.has_port_drift ? '<span class="badge bg-warning text-dark" title="Port drift detected">⚠️ Drift</span>' : '<span class="badge bg-info" title="Has observations">🔍 Observed</span>';
        }

        return `
            <div class="card mb-3 shadow-sm lablet-definition-card" data-definition-id="${escapeHtml(definition.id)}">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <div class="d-flex align-items-center">
                        <i class="bi bi-file-earmark-code me-2 fs-5"></i>
                        <div>
                            <h6 class="mb-0">${name}</h6>
                            <small class="text-muted">v${version}</small>
                        </div>
                    </div>
                    <div class="d-flex gap-1">
                        <span class="badge ${statusBadgeClass}">
                            ${escapeHtml(status.toUpperCase())}
                        </span>
                        ${definition.sync_status ? `<lcm-status-badge status="${escapeHtml(definition.sync_status)}" title="Sync: ${escapeHtml(definition.sync_status)}"></lcm-status-badge>` : ''}
                        ${obsIndicatorHtml}
                    </div>
                </div>
                <div class="card-body">
                    ${
                        definition.form_qualified_name
                            ? `
                    <div class="mb-3">
                        <small class="text-muted d-block">Form Qualified Name</small>
                        <span class="fw-medium">${escapeHtml(definition.form_qualified_name)}</span>
                    </div>
                    `
                            : ''
                    }
                    <!-- Resource Requirements -->
                    <div class="row mb-3">
                        <div class="col-3 text-center">
                            <div class="bg-light rounded p-2">
                                <i class="bi bi-cpu fs-4 text-primary"></i>
                                <div class="small text-muted mt-1">CPU</div>
                                <div class="fw-bold">${cpuCores}</div>
                            </div>
                        </div>
                        <div class="col-3 text-center">
                            <div class="bg-light rounded p-2">
                                <i class="bi bi-memory fs-4 text-success"></i>
                                <div class="small text-muted mt-1">Memory</div>
                                <div class="fw-bold">${memoryGb}GB</div>
                            </div>
                        </div>
                        <div class="col-3 text-center">
                            <div class="bg-light rounded p-2">
                                <i class="bi bi-hdd fs-4 text-info"></i>
                                <div class="small text-muted mt-1">Storage</div>
                                <div class="fw-bold">${storageGb}GB</div>
                            </div>
                        </div>
                        <div class="col-3 text-center">
                            <div class="bg-light rounded p-2">
                                <i class="bi bi-diagram-3 fs-4 text-warning"></i>
                                <div class="small text-muted mt-1">Nodes</div>
                                <div class="fw-bold">${nodeCount}</div>
                            </div>
                        </div>
                    </div>

                    <!-- Additional Info -->
                    <div class="row mb-2">
                        <div class="col-4">
                            <small class="text-muted">Max Duration</small>
                            <div><i class="bi bi-clock me-1"></i>${maxDuration} minutes</div>
                        </div>
                        <div class="col-4">
                            <small class="text-muted">Warm Pool</small>
                            <div><i class="bi bi-archive me-1"></i>${definition.warm_pool_depth || 0} instances</div>
                        </div>
                        <div class="col-4">
                            <small class="text-muted">Boot Lead</small>
                            <div><i class="bi bi-hourglass-split me-1"></i>${definition.boot_lead_time_minutes != null ? definition.boot_lead_time_minutes + ' min' : 'Default'}</div>
                        </div>
                    </div>

                    ${
                        definition.nested_virt
                            ? `
                        <div class="mb-2">
                            <span class="badge bg-info">
                                <i class="bi bi-layers"></i> Nested Virtualization Required
                            </span>
                        </div>
                    `
                            : ''
                    }

                    ${licenseAffinityHtml}
                    ${portDefinitionsHtml}

                    <!-- Resource Observations (ADR-030) -->
                    <div id="observation-panel-${escapeHtml(definition.id)}" class="observation-panel mt-2"></div>
                </div>
                <div class="card-footer bg-transparent d-flex justify-content-between align-items-center">
                    <div>
                        <small class="text-muted d-block">Created: ${createdAt}</small>
                        ${definition.last_synced_at ? `<small class="text-muted">Synced: ${formatDateWithRelative(definition.last_synced_at)}</small>` : ''}
                    </div>
                    <div class="btn-group btn-group-sm">
                        <button class="btn btn-outline-primary btn-sm" data-action="view" title="View Details">
                            <i class="bi bi-eye"></i>
                        </button>
                        <button class="btn btn-outline-secondary btn-sm" data-action="observations" title="View Observations">
                            <i class="bi bi-binoculars"></i>
                        </button>
                        <button class="btn btn-outline-info btn-sm" data-action="sync" title="Sync from Source">
                            <i class="bi bi-arrow-repeat"></i>
                        </button>
                        <button class="btn btn-outline-success btn-sm" data-action="create-instance" title="Create Instance">
                            <i class="bi bi-plus-circle"></i>
                        </button>
                    </div>
                </div>
            </div>
        `;
    }

    renderCompactCard(definition) {
        const status = definition.status || 'active';
        const statusBadgeClass = getLabletDefinitionStatusBadgeClass(status);
        const name = escapeHtml(definition.name || 'Unknown');
        const version = escapeHtml(definition.version || '1.0.0');

        // Observation indicator (ADR-030): 🔍 = has observations, ⚠️ = drift, ➖ = none
        let obsIndicator = '<span title="No observations">➖</span>';
        if (definition.has_observations) {
            obsIndicator = definition.has_port_drift ? '<span title="Port drift detected">⚠️</span>' : '<span title="Has observations">🔍</span>';
        }

        return `
            <div class="card mb-2 lablet-definition-card-compact" data-definition-id="${escapeHtml(definition.id)}">
                <div class="card-body py-2 px-3">
                    <div class="d-flex justify-content-between align-items-center">
                        <div class="d-flex align-items-center">
                            <i class="bi bi-file-earmark-code me-2"></i>
                            <span class="text-truncate" style="max-width: 150px;">${name}</span>
                            <small class="text-muted ms-2">v${version}</small>
                            <span class="ms-2">${obsIndicator}</span>
                        </div>
                        <span class="badge ${statusBadgeClass} badge-sm">
                            ${escapeHtml(status)}
                        </span>
                    </div>
                </div>
            </div>
        `;
    }

    renderLicenseAffinity(licenseAffinity) {
        if (!licenseAffinity || licenseAffinity.length === 0) return '';

        const badges = licenseAffinity
            .map(license => {
                const colorClass =
                    {
                        personal: 'bg-secondary',
                        enterprise: 'bg-primary',
                        evaluation: 'bg-warning text-dark',
                    }[license.toLowerCase()] || 'bg-secondary';

                return `<span class="badge ${colorClass} me-1">${escapeHtml(license)}</span>`;
            })
            .join('');

        return `
            <div class="mb-2">
                <small class="text-muted d-block mb-1">License Affinity</small>
                <div>${badges}</div>
            </div>
        `;
    }

    renderPortDefinitions(portDefinitions) {
        if (!portDefinitions || portDefinitions.length === 0) return '';

        const portBadges = portDefinitions
            .map(
                port => `
            <span class="badge bg-light text-dark border me-1 mb-1">
                <i class="bi bi-plug me-1"></i>${escapeHtml(port.name)} (${port.protocol || 'tcp'})
            </span>
        `
            )
            .join('');

        return `
            <div class="mb-2">
                <small class="text-muted d-block mb-1">Port Definitions</small>
                <div>${portBadges}</div>
            </div>
        `;
    }

    setupEventHandlers() {
        const definition = this._state.definition;
        if (!definition) return;

        // View details
        const viewBtn = this.querySelector('[data-action="view"]');
        if (viewBtn) {
            viewBtn.addEventListener('click', () => {
                this.emit(EventTypes.UI_MODAL_OPENED, {
                    modal: 'lablet-definition-details',
                    definition_id: definition.id,
                    definition: definition,
                });
            });
        }

        // Sync
        const syncBtn = this.querySelector('[data-action="sync"]');
        if (syncBtn) {
            syncBtn.addEventListener('click', async () => {
                try {
                    syncBtn.disabled = true;
                    syncBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

                    const { syncLabletDefinition } = await import('../api/lablet-definitions.js');
                    await syncLabletDefinition(definition.id);

                    const { showToast } = await import('../ui/notifications.js');
                    showToast('Definition synced successfully', 'success');

                    this.emit(EventTypes.LABLET_DEFINITIONS_REFRESH_COMPLETED);
                } catch (error) {
                    console.error('Failed to sync definition:', error);
                    const { showToast } = await import('../ui/notifications.js');
                    showToast(`Failed to sync: ${error.message}`, 'error');
                } finally {
                    syncBtn.disabled = false;
                    syncBtn.innerHTML = '<i class="bi bi-arrow-repeat"></i>';
                }
            });
        }

        // Create instance
        const createInstanceBtn = this.querySelector('[data-action="create-instance"]');
        if (createInstanceBtn) {
            createInstanceBtn.addEventListener('click', () => {
                this.emit(EventTypes.UI_MODAL_OPENED, {
                    modal: 'create-lablet-instance',
                    definition_id: definition.id,
                    definition: definition,
                });
            });
        }

        // View observations (ADR-030)
        const obsBtn = this.querySelector('[data-action="observations"]');
        if (obsBtn) {
            obsBtn.addEventListener('click', async () => {
                const panel = this.querySelector(`#observation-panel-${definition.id}`);
                if (!panel) return;

                // Toggle: hide if already showing
                if (panel.innerHTML.trim()) {
                    panel.innerHTML = '';
                    return;
                }

                try {
                    obsBtn.disabled = true;
                    obsBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

                    const { getDefinitionResourceObservations } = await import('../api/lablet-definitions.js');
                    const data = await getDefinitionResourceObservations(definition.id);
                    panel.innerHTML = this._renderObservationsPanel(data, definition);
                    this._bindObservationActions(panel, definition);
                } catch (error) {
                    console.error('Failed to load observations:', error);
                    panel.innerHTML = `<div class="alert alert-danger py-2 small mt-2">Failed to load observations: ${escapeHtml(error.message)}</div>`;
                } finally {
                    obsBtn.disabled = false;
                    obsBtn.innerHTML = '<i class="bi bi-binoculars"></i>';
                }
            });
        }
    }

    /**
     * Render aggregated observations panel (ADR-030).
     * Shows resource comparison (configured vs max/avg/latest) and session history.
     */
    _renderObservationsPanel(data, definition) {
        if (!data || data.observation_count === 0) {
            return `
                <div class="border rounded p-3 mt-2 bg-light">
                    <div class="text-muted small text-center">
                        <i class="bi bi-eye-slash me-1"></i>No resource observations yet.
                        <br>Observations are recorded when sessions run on CML.
                    </div>
                </div>
            `;
        }

        const agg = data.aggregate;
        const cpuConf = definition.cpu_cores || 0;
        const memConf = definition.memory_gb || 0;
        const nodeConf = definition.node_count || 0;

        // Convert memory from MB to GB for comparison
        const memMaxGb = agg.memory_mb?.max != null ? Math.round((agg.memory_mb.max / 1024) * 10) / 10 : '—';
        const memAvgGb = agg.memory_mb?.avg != null ? Math.round((agg.memory_mb.avg / 1024) * 10) / 10 : '—';
        const memLatGb = agg.memory_mb?.latest != null ? Math.round((agg.memory_mb.latest / 1024) * 10) / 10 : '—';

        const sessionRows = (data.sessions || [])
            .map(
                s => `
            <tr>
                <td class="font-monospace small">${escapeHtml((s.session_id || '').substring(0, 8))}…</td>
                <td class="text-center small">${s.observed_at ? new Date(s.observed_at).toLocaleDateString() : '—'}</td>
                <td class="text-center">${s.total_cpu_cores ?? '—'}</td>
                <td class="text-center">${s.total_memory_mb != null ? Math.round((s.total_memory_mb / 1024) * 10) / 10 : '—'}</td>
                <td class="text-center">${s.actual_node_count ?? '—'}</td>
                <td class="text-center">${s.port_drift_detected ? '⚠️' : '✓'}</td>
            </tr>
        `
            )
            .join('');

        return `
            <div class="border rounded p-3 mt-2">
                <h6 class="small fw-bold mb-2">
                    <i class="bi bi-binoculars me-1"></i>Observed Resources
                    <span class="badge bg-secondary ms-1">${data.observation_count} session${data.observation_count !== 1 ? 's' : ''}</span>
                    ${agg.port_drift_sessions > 0 ? `<span class="badge bg-warning text-dark ms-1">⚠️ ${agg.port_drift_sessions} drift</span>` : ''}
                </h6>
                <div class="table-responsive">
                    <table class="table table-sm table-bordered mb-2">
                        <thead class="table-light">
                            <tr>
                                <th>Resource</th>
                                <th class="text-center">Configured</th>
                                <th class="text-center">Max</th>
                                <th class="text-center">Avg</th>
                                <th class="text-center">Latest</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr>
                                <td>CPU cores</td>
                                <td class="text-center">${cpuConf}</td>
                                <td class="text-center fw-bold">${agg.cpu_cores?.max ?? '—'}</td>
                                <td class="text-center">${agg.cpu_cores?.avg != null ? Math.round(agg.cpu_cores.avg * 10) / 10 : '—'}</td>
                                <td class="text-center">${agg.cpu_cores?.latest ?? '—'}</td>
                            </tr>
                            <tr>
                                <td>Memory (GB)</td>
                                <td class="text-center">${memConf}</td>
                                <td class="text-center fw-bold">${memMaxGb}</td>
                                <td class="text-center">${memAvgGb}</td>
                                <td class="text-center">${memLatGb}</td>
                            </tr>
                            <tr>
                                <td>Node count</td>
                                <td class="text-center">${nodeConf}</td>
                                <td class="text-center fw-bold">${agg.node_count?.max ?? '—'}</td>
                                <td class="text-center">${agg.node_count?.avg != null ? Math.round(agg.node_count.avg * 10) / 10 : '—'}</td>
                                <td class="text-center">${agg.node_count?.latest ?? '—'}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
                <div class="d-flex gap-1 mb-2">
                    <button class="btn btn-outline-primary btn-sm" data-obs-action="apply-max" title="Pre-fill edit with max observed values">
                        <i class="bi bi-clipboard me-1"></i>Apply Max
                    </button>
                    <button class="btn btn-outline-secondary btn-sm" data-obs-action="apply-latest" title="Pre-fill edit with latest observed values">
                        <i class="bi bi-clipboard me-1"></i>Apply Latest
                    </button>
                </div>
                ${
                    sessionRows
                        ? `
                <details class="mt-1">
                    <summary class="small text-muted" style="cursor:pointer">Session History</summary>
                    <div class="table-responsive mt-1">
                        <table class="table table-sm mb-0">
                            <thead class="table-light">
                                <tr>
                                    <th>Session</th>
                                    <th class="text-center">Date</th>
                                    <th class="text-center">CPU</th>
                                    <th class="text-center">Mem</th>
                                    <th class="text-center">Nodes</th>
                                    <th class="text-center">Drift</th>
                                </tr>
                            </thead>
                            <tbody>${sessionRows}</tbody>
                        </table>
                    </div>
                </details>
                `
                        : ''
                }
            </div>
        `;
    }

    /**
     * Bind observation "Apply" button actions (ADR-030).
     * Opens the edit modal pre-filled with observed values.
     */
    _bindObservationActions(panel, definition) {
        panel.querySelector('[data-obs-action="apply-max"]')?.addEventListener('click', async () => {
            const { getDefinitionResourceObservations } = await import('../api/lablet-definitions.js');
            try {
                const data = await getDefinitionResourceObservations(definition.id);
                if (data?.aggregate) {
                    const agg = data.aggregate;
                    this.emit(EventTypes.UI_MODAL_OPENED, {
                        modal: 'edit-lablet-definition',
                        definition_id: definition.id,
                        prefill: {
                            cpu_cores: agg.cpu_cores?.max != null ? Math.ceil(agg.cpu_cores.max) : undefined,
                            memory_gb: agg.memory_mb?.max != null ? Math.ceil(agg.memory_mb.max / 1024) : undefined,
                            node_count: agg.node_count?.max ?? undefined,
                        },
                    });
                }
            } catch (e) {
                const { showToast } = await import('../ui/notifications.js');
                showToast(`Failed to apply: ${e.message}`, 'error');
            }
        });

        panel.querySelector('[data-obs-action="apply-latest"]')?.addEventListener('click', async () => {
            const { getDefinitionResourceObservations } = await import('../api/lablet-definitions.js');
            try {
                const data = await getDefinitionResourceObservations(definition.id);
                if (data?.aggregate) {
                    const agg = data.aggregate;
                    this.emit(EventTypes.UI_MODAL_OPENED, {
                        modal: 'edit-lablet-definition',
                        definition_id: definition.id,
                        prefill: {
                            cpu_cores: agg.cpu_cores?.latest != null ? Math.ceil(agg.cpu_cores.latest) : undefined,
                            memory_gb: agg.memory_mb?.latest != null ? Math.ceil(agg.memory_mb.latest / 1024) : undefined,
                            node_count: agg.node_count?.latest ?? undefined,
                        },
                    });
                }
            } catch (e) {
                const { showToast } = await import('../ui/notifications.js');
                showToast(`Failed to apply: ${e.message}`, 'error');
            }
        });
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
customElements.define('lablet-definition-card', LabletDefinitionCard);
