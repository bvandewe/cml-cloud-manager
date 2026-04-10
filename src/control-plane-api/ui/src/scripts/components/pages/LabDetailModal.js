/**
 * LabDetailModal — Phase 10 (P10-2)
 *
 * Full-featured modal for viewing and managing a single LabRecord.
 * Architecture ref: §9.4 Lab Detail Modal.
 *
 * Tabs:
 *   - Overview: identity, status, worker, resources
 *   - Ports: allocated port mappings grouped by node (ADR-032)
 *   - Linked Lablets: lablet instance bindings
 *   - Runs: active/historical runs
 *   - Topology: node/link tables from discovery
 *   - Revisions: revision history
 *
 * Actions: Start, Stop, Wipe, Clone, Export, Archive, Delete
 *
 * Usage:
 *   <lab-detail-modal id="lab-detail-modal"></lab-detail-modal>
 *   modal.open(labRecordId);
 *
 * @module components/pages/LabDetailModal
 */

import { BaseComponent } from '../../core/BaseComponent.js';
import { eventBus, EventTypes } from '../../core/EventBus.js';
import * as labRecordsApi from '../../api/lab-records.js';
import { showToast } from '../../ui/notifications.js';
import { showConfirm, showConfirmAsync } from '../modals.js';
import { escapeHtml } from '../escape.js';
import { formatDateWithRelative } from '../../utils/dates.js';
import { getWorker } from '../../store/workerStore.js';
import * as bootstrap from 'bootstrap';

const STATUS_ACTIONS = {
    start: { label: 'Start', icon: 'bi-play-fill', variant: 'success', confirm: false, allowed: ['stopped', 'imported', 'discovered', 'wiped', 'defined'] },
    stop: { label: 'Stop', icon: 'bi-stop-fill', variant: 'warning', confirm: true, allowed: ['booted', 'converging', 'converged'] },
    wipe: { label: 'Wipe', icon: 'bi-eraser-fill', variant: 'warning', confirm: true, allowed: ['booted', 'converged', 'stopped', 'error', 'imported'] },
    clone: { label: 'Clone', icon: 'bi-files', variant: 'primary', confirm: false, allowed: ['booted', 'converged', 'stopped', 'imported', 'discovered', 'defined'] },
    export: { label: 'Export', icon: 'bi-download', variant: 'outline-primary', confirm: false, allowed: ['booted', 'converged', 'stopped', 'imported', 'discovered', 'defined', 'wiped'] },
    archive: { label: 'Archive', icon: 'bi-archive-fill', variant: 'secondary', confirm: true, allowed: ['stopped', 'wiped', 'error'] },
    delete: { label: 'Delete', icon: 'bi-trash-fill', variant: 'danger', confirm: true, allowed: ['stopped', 'wiped', 'defined', 'imported', 'error', 'archived'] },
};

export class LabDetailModal extends BaseComponent {
    constructor() {
        super();
        this._modalInstance = null;
        this._labRecordId = null;
        this._labRecord = null;
        this._topology = null;
        this._revisions = null;
        this._linkedLablets = null;
        this._runs = null;
        this._activeTab = 'overview';
        this._isLoading = false;
    }

    onMount() {
        this.innerHTML = this._renderModal();
        this._setupModal();
        this._setupEventSubscriptions();
    }

    _setupModal() {
        const modalEl = this.querySelector('#labDetailModal');
        if (modalEl) {
            this._modalInstance = new bootstrap.Modal(modalEl);

            // Cleanup on hide
            modalEl.addEventListener('hidden.bs.modal', () => {
                this._labRecordId = null;
                this._labRecord = null;
                this._topology = null;
                this._revisions = null;
                this._linkedLablets = null;
                this._runs = null;
                this._activeTab = 'overview';
            });
        }
    }

    _setupEventSubscriptions() {
        this.subscribe(EventTypes.LAB_RECORD_STATUS_UPDATED, data => {
            const id = data.lab_record_id || data.id;
            if (id === this._labRecordId && this._labRecord) {
                this._labRecord = { ...this._labRecord, status: data.status, updated_at: data.updated_at || new Date().toISOString() };
                // Invalidate runs cache — status transitions may indicate run start/end
                this._runs = null;
                this._renderActiveTab();
                this._renderFooterActions();
            }
        });

        this.subscribe(EventTypes.LAB_RECORD_SNAPSHOT, data => {
            if (data.id === this._labRecordId) {
                this._labRecord = data;
                this._renderActiveTab();
                this._renderFooterActions();
            }
        });

        this.subscribe(EventTypes.LAB_RECORD_TOPOLOGY_UPDATED, data => {
            const id = data.lab_record_id || data.id;
            if (id === this._labRecordId) {
                this._topology = null; // Force reload on next tab switch
                if (this._activeTab === 'topology') this._loadTopologyTab();
            }
        });

        this.subscribe(EventTypes.LAB_RECORD_DELETED, data => {
            const id = data.lab_record_id || data.id;
            if (id === this._labRecordId) {
                this.close();
                showToast('Lab record has been deleted', 'info');
            }
        });

        // Action lifecycle events (AD-023) — show pending state & refresh on completion
        this.subscribe(EventTypes.LAB_RECORD_ACTION_QUEUED, data => {
            const id = data.lab_record_id || data.id;
            if (id === this._labRecordId && this._labRecord) {
                this._labRecord = { ...this._labRecord, pending_action: data.action };
                this._renderFooterActions();
            }
        });

        this.subscribe(EventTypes.LAB_RECORD_ACTION_COMPLETED, data => {
            const id = data.lab_record_id || data.id;
            if (id === this._labRecordId && this._labRecord) {
                this._labRecord = { ...this._labRecord, pending_action: null };
                this._renderFooterActions();
                // Full refresh to pick up new status + state
                this.open(this._labRecordId);
            }
        });

        this.subscribe(EventTypes.LAB_RECORD_ACTION_FAILED, data => {
            const id = data.lab_record_id || data.id;
            if (id === this._labRecordId && this._labRecord) {
                this._labRecord = { ...this._labRecord, pending_action: null };
                this._renderFooterActions();
                showToast(`Action failed: ${data.error_message || 'Unknown error'}`, 'error');
            }
        });
    }

    // ===========================================================================
    // Public API
    // ===========================================================================

    async open(labRecordId) {
        if (!labRecordId) return;
        this._labRecordId = labRecordId;
        this._activeTab = 'overview';
        this._isLoading = true;

        // Reset cached data
        this._topology = null;
        this._revisions = null;
        this._linkedLablets = null;
        this._runs = null;

        // Show modal immediately with loading state
        if (this._modalInstance) this._modalInstance.show();
        this._renderBody();

        // Load lab record
        try {
            this._labRecord = await labRecordsApi.getLabRecord(labRecordId);
            this._isLoading = false;
            this._renderBody();
            this._renderFooterActions();
        } catch (error) {
            this._isLoading = false;
            console.error('[LabDetailModal] Failed to load lab record:', error);
            this._renderError(error.message);
        }
    }

    close() {
        if (this._modalInstance) this._modalInstance.hide();
    }

    // ===========================================================================
    // Rendering
    // ===========================================================================

    _renderModal() {
        return `
            <div class="modal fade" id="labDetailModal" tabindex="-1" aria-labelledby="labDetailModalTitle" aria-hidden="true">
                <div class="modal-dialog modal-xl">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title" id="labDetailModalTitle">
                                <i class="bi bi-flask me-2"></i>Lab Details
                            </h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                        </div>
                        <div class="modal-body" id="labDetailModalBody">
                            ${this._renderLoadingSpinner()}
                        </div>
                        <div class="modal-footer" id="labDetailModalFooter">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    _renderBody() {
        const body = this.querySelector('#labDetailModalBody');
        if (!body) return;

        if (this._isLoading) {
            body.innerHTML = this._renderLoadingSpinner();
            return;
        }

        if (!this._labRecord) {
            body.innerHTML = '<div class="alert alert-warning">Lab record not found.</div>';
            return;
        }

        // Update modal title
        const titleEl = this.querySelector('#labDetailModalTitle');
        if (titleEl) {
            const title = escapeHtml(this._labRecord.title || 'Untitled Lab');
            const status = this._labRecord.status || 'unknown';
            titleEl.innerHTML = `<i class="bi bi-flask me-2"></i>${title} <lcm-status-badge status="${escapeHtml(status)}" icon pill class="ms-2"></lcm-status-badge>`;
        }

        body.innerHTML = `
            <!-- Navigation Tabs -->
            <ul class="nav nav-tabs mb-3" id="labDetailTabs" role="tablist">
                <li class="nav-item" role="presentation">
                    <button class="nav-link ${this._activeTab === 'overview' ? 'active' : ''}"
                        data-lab-tab="overview" type="button">
                        <i class="bi bi-info-circle me-1"></i>Overview
                    </button>
                </li>
                <li class="nav-item" role="presentation">
                    <button class="nav-link ${this._activeTab === 'ports' ? 'active' : ''}"
                        data-lab-tab="ports" type="button">
                        <i class="bi bi-plug me-1"></i>Ports
                        ${this._labRecord?.allocated_ports && Object.keys(this._labRecord.allocated_ports).length > 0
                            ? `<span class="badge bg-primary rounded-pill ms-1">${Object.keys(this._labRecord.allocated_ports).length}</span>`
                            : ''}
                    </button>
                </li>
                <li class="nav-item" role="presentation">
                    <button class="nav-link ${this._activeTab === 'linkedLablets' ? 'active' : ''}"
                        data-lab-tab="linkedLablets" type="button">
                        <i class="bi bi-link-45deg me-1"></i>Linked Lablets
                    </button>
                </li>
                <li class="nav-item" role="presentation">
                    <button class="nav-link ${this._activeTab === 'runs' ? 'active' : ''}"
                        data-lab-tab="runs" type="button">
                        <i class="bi bi-play-circle me-1"></i>Runs
                    </button>
                </li>
                <li class="nav-item" role="presentation">
                    <button class="nav-link ${this._activeTab === 'topology' ? 'active' : ''}"
                        data-lab-tab="topology" type="button">
                        <i class="bi bi-diagram-3 me-1"></i>Topology
                    </button>
                </li>
                <li class="nav-item" role="presentation">
                    <button class="nav-link ${this._activeTab === 'revisions' ? 'active' : ''}"
                        data-lab-tab="revisions" type="button">
                        <i class="bi bi-clock-history me-1"></i>Revisions
                    </button>
                </li>
            </ul>

            <!-- Tab Content -->
            <div class="tab-content" id="labDetailTabContent">
                <div id="lab-tab-panel"></div>
            </div>
        `;

        this._bindTabListeners();
        this._renderActiveTab();
    }

    _bindTabListeners() {
        this.querySelectorAll('[data-lab-tab]').forEach(btn => {
            btn.addEventListener('click', e => {
                e.preventDefault();
                const tab = btn.dataset.labTab;
                this._switchTab(tab);
            });
        });
    }

    _switchTab(tabName) {
        this._activeTab = tabName;

        // Update tab button states
        this.querySelectorAll('[data-lab-tab]').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.labTab === tabName);
        });

        this._renderActiveTab();
    }

    _renderActiveTab() {
        const panel = this.querySelector('#lab-tab-panel');
        if (!panel) return;

        switch (this._activeTab) {
            case 'overview':
                panel.innerHTML = this._renderOverviewTab();
                this._bindOverviewCrossLinks();
                break;
            case 'ports':
                panel.innerHTML = this._renderPortsTab();
                break;
            case 'linkedLablets':
                this._loadLinkedLabletsTab();
                break;
            case 'runs':
                this._loadRunsTab();
                break;
            case 'topology':
                this._loadTopologyTab();
                break;
            case 'revisions':
                this._loadRevisionsTab();
                break;
        }
    }

    // ===========================================================================
    // Overview Tab
    // ===========================================================================

    _renderOverviewTab() {
        const lr = this._labRecord;
        if (!lr) return '';

        const created = lr.created_at ? formatDateWithRelative(lr.created_at) : '—';
        const updated = lr.updated_at ? formatDateWithRelative(lr.updated_at) : '—';

        return `
            <div class="row g-4">
                <!-- Lab Identity -->
                <div class="col-md-6">
                    <div class="card h-100">
                        <div class="card-header"><i class="bi bi-tag me-1"></i> Identity</div>
                        <div class="card-body">
                            <table class="table table-sm table-borderless mb-0">
                                <tr>
                                    <th class="text-muted" style="width: 35%;">ID</th>
                                    <td><code class="small">${escapeHtml(lr.id || '')}</code></td>
                                </tr>
                                <tr>
                                    <th class="text-muted">Title</th>
                                    <td>${escapeHtml(lr.title || 'Untitled')}</td>
                                </tr>
                                <tr>
                                    <th class="text-muted">Description</th>
                                    <td>${escapeHtml(lr.description || '—')}</td>
                                </tr>
                                <tr>
                                    <th class="text-muted">Source</th>
                                    <td>
                                        <span class="badge bg-light text-dark">
                                            <i class="bi ${lr.source === 'discovery' ? 'bi-search' : lr.source === 'import' ? 'bi-box-arrow-in-down' : 'bi-pencil'} me-1"></i>
                                            ${escapeHtml(lr.source || 'unknown')}
                                        </span>
                                    </td>
                                </tr>
                                <tr>
                                    <th class="text-muted">CML Lab ID</th>
                                    <td>${(() => {
                                        if (!lr.lab_id) return '—';
                                        const shortLabId = lr.lab_id.split('-')[0];
                                        const workerIp = lr.worker_ip;
                                        if (workerIp) {
                                            return `<a href="https://${escapeHtml(workerIp)}/lab/${escapeHtml(lr.lab_id)}" target="_blank" class="text-decoration-none" title="Open lab in CML UI: ${escapeHtml(lr.lab_id)}"><code class="small">${escapeHtml(shortLabId)}</code> <i class="bi bi-box-arrow-up-right" style="font-size: 0.7em;"></i></a>`;
                                        }
                                        return `<code class="small" title="${escapeHtml(lr.lab_id)}">${escapeHtml(shortLabId)}</code>`;
                                    })()}</td>
                                </tr>
                                <tr>
                                    <th class="text-muted">Notes</th>
                                    <td>${escapeHtml(lr.notes || '—')}</td>
                                </tr>
                            </table>
                        </div>
                    </div>
                </div>

                <!-- Lab Status & Worker -->
                <div class="col-md-6">
                    <div class="card h-100">
                        <div class="card-header"><i class="bi bi-activity me-1"></i> Status & Worker</div>
                        <div class="card-body">
                            <table class="table table-sm table-borderless mb-0">
                                <tr>
                                    <th class="text-muted" style="width: 35%;">Status</th>
                                    <td><lcm-status-badge status="${escapeHtml(lr.status || 'unknown')}" icon pill></lcm-status-badge></td>
                                </tr>
                                <tr>
                                    <th class="text-muted">Worker</th>
                                    <td>${escapeHtml(lr.worker_name || lr.worker_id || '—')}</td>
                                </tr>
                                <tr>
                                    <th class="text-muted">Worker ID</th>
                                    <td>${(() => {
                                        if (!lr.worker_id) return '—';
                                        const shortId = lr.worker_id.split('-')[0];
                                        return `<a href="#" class="open-worker-link text-decoration-none" data-worker-id="${escapeHtml(lr.worker_id)}" title="Open Worker ${escapeHtml(lr.worker_id)}"><code class="small">${escapeHtml(shortId)}</code> <i class="bi bi-box-arrow-up-right" style="font-size: 0.7em;"></i></a>`;
                                    })()}</td>
                                </tr>
                                <tr>
                                    <th class="text-muted">Worker IP</th>
                                    <td>${(() => {
                                        if (!lr.worker_ip) return '—';
                                        return `<a href="https://${escapeHtml(lr.worker_ip)}" target="_blank" class="text-decoration-none" title="Open worker HTTPS endpoint"><code class="small">${escapeHtml(lr.worker_ip)}</code> <i class="bi bi-box-arrow-up-right" style="font-size: 0.7em;"></i></a>`;
                                    })()}</td>
                                </tr>
                                <tr>
                                    <th class="text-muted">Created</th>
                                    <td>${created}</td>
                                </tr>
                                <tr>
                                    <th class="text-muted">Updated</th>
                                    <td>${updated}</td>
                                </tr>
                            </table>
                        </div>
                    </div>
                </div>

                <!-- Resource Summary -->
                <div class="col-12">
                    <div class="card">
                        <div class="card-header"><i class="bi bi-cpu me-1"></i> Resources</div>
                        <div class="card-body">
                            <div class="row text-center">
                                <div class="col">
                                    <div class="fs-3 fw-bold text-primary">${lr.node_count ?? '—'}</div>
                                    <small class="text-muted">Nodes</small>
                                </div>
                                <div class="col">
                                    <div class="fs-3 fw-bold text-primary">${lr.link_count ?? '—'}</div>
                                    <small class="text-muted">Links</small>
                                </div>
                                <div class="col">
                                    <div class="fs-3 fw-bold text-info">${lr.revision ?? '—'}</div>
                                    <small class="text-muted">Revision</small>
                                </div>
                                <div class="col">
                                    <div class="fs-3 fw-bold text-info">${lr.binding_count ?? 0}</div>
                                    <small class="text-muted">Bindings</small>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    /**
     * Bind click handlers for cross-links in the Overview tab.
     * - Worker ID link → closes this modal, opens WorkerDetailsModal
     */
    _bindOverviewCrossLinks() {
        this.querySelectorAll('.open-worker-link').forEach(link => {
            link.addEventListener('click', e => {
                e.preventDefault();
                const workerId = link.dataset.workerId;
                if (!workerId) return;
                // Look up worker region from in-memory store
                const worker = getWorker(workerId);
                const region = worker?.aws_region || link.dataset.workerRegion || '';
                // Close lab detail modal first, then open worker details modal
                this.close();
                setTimeout(() => {
                    eventBus.emit('UI_OPEN_WORKER_DETAILS', { workerId, region });
                }, 300);
            });
        });
    }

    // ===========================================================================
    // Ports Tab (ADR-032)
    // ===========================================================================

    _renderPortsTab() {
        const lr = this._labRecord;
        if (!lr) return '';

        const ports = lr.allocated_ports;
        const hasPorts = ports && typeof ports === 'object' && Object.keys(ports).length > 0;

        if (!hasPorts) {
            return `
                <div class="text-center text-muted py-4">
                    <i class="bi bi-plug fs-1 d-block mb-2"></i>
                    <p>No ports allocated for this lab record.</p>
                    <small class="text-muted">
                        Ports are allocated during session instantiation when the
                        associated definition includes a port template.
                    </small>
                </div>
            `;
        }

        // Group ports by node label (port names follow "{node_label}_{protocol}" convention)
        const byNode = {};
        for (const [portName, portNumber] of Object.entries(ports)) {
            const parts = portName.split('_');
            const protocol = parts.pop();
            const nodeLabel = parts.join('_');
            if (!byNode[nodeLabel]) byNode[nodeLabel] = [];
            byNode[nodeLabel].push({ protocol, portNumber, portName });
        }

        const nodeCards = Object.entries(byNode)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([nodeLabel, nodePorts]) => {
                const rows = nodePorts
                    .sort((a, b) => a.protocol.localeCompare(b.protocol))
                    .map(p => `
                        <tr>
                            <td>
                                <span class="badge bg-light text-dark">
                                    <i class="bi ${p.protocol === 'vnc' ? 'bi-display' : p.protocol === 'serial' ? 'bi-terminal' : 'bi-ethernet'} me-1"></i>
                                    ${escapeHtml(p.protocol)}
                                </span>
                            </td>
                            <td>
                                <code class="fs-6">${p.portNumber}</code>
                            </td>
                            <td>
                                <code class="small text-muted">${escapeHtml(p.portName)}</code>
                            </td>
                        </tr>
                    `)
                    .join('');

                return `
                    <div class="col-md-6 col-lg-4">
                        <div class="card h-100">
                            <div class="card-header py-2">
                                <i class="bi bi-hdd me-1"></i>
                                <strong>${escapeHtml(nodeLabel)}</strong>
                                <span class="badge bg-secondary float-end">${nodePorts.length}</span>
                            </div>
                            <div class="card-body p-0">
                                <table class="table table-sm table-hover mb-0">
                                    <thead>
                                        <tr>
                                            <th style="width: 35%;">Protocol</th>
                                            <th style="width: 25%;">Port</th>
                                            <th>Key</th>
                                        </tr>
                                    </thead>
                                    <tbody>${rows}</tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                `;
            })
            .join('');

        const totalPorts = Object.keys(ports).length;
        const totalNodes = Object.keys(byNode).length;

        return `
            <div class="d-flex align-items-center mb-3">
                <h6 class="mb-0">
                    <i class="bi bi-plug me-1"></i> Allocated Ports
                </h6>
                <span class="badge bg-primary ms-2">${totalPorts} ports</span>
                <span class="badge bg-secondary ms-1">${totalNodes} nodes</span>
            </div>
            <div class="row g-3">
                ${nodeCards}
            </div>
        `;
    }

    // ===========================================================================
    // Topology Tab
    // ===========================================================================

    async _loadTopologyTab() {
        const panel = this.querySelector('#lab-tab-panel');
        if (!panel) return;

        if (this._topology) {
            panel.innerHTML = this._renderTopologyContent(this._topology);
            return;
        }

        panel.innerHTML = this._renderLoadingSpinner();

        try {
            this._topology = await labRecordsApi.getLabRecordTopology(this._labRecordId);
            panel.innerHTML = this._renderTopologyContent(this._topology);
        } catch (error) {
            panel.innerHTML = `<div class="alert alert-warning">Failed to load topology: ${escapeHtml(error.message)}</div>`;
        }
    }

    _renderTopologyContent(topology) {
        if (!topology) return '<div class="text-muted text-center py-4">No topology data available.</div>';

        const nodes = topology.nodes || [];
        const links = topology.links || [];

        let nodesHtml = '';
        if (nodes.length === 0) {
            nodesHtml = '<p class="text-muted">No nodes defined.</p>';
        } else {
            nodesHtml = `
                <div class="table-responsive">
                    <table class="table table-sm table-hover">
                        <thead>
                            <tr>
                                <th>Label</th>
                                <th>Definition</th>
                                <th>Tags</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${nodes
                                .map(n => {
                                    const tags = n.tags
                                        ? Object.entries(n.tags)
                                              .map(([k, v]) => `${escapeHtml(k)}=${escapeHtml(v)}`)
                                              .join(', ')
                                        : '—';
                                    return `
                                <tr>
                                    <td><i class="bi bi-hdd me-1 text-muted"></i>${escapeHtml(n.label || '—')}</td>
                                    <td><code class="small">${escapeHtml(n.node_definition || '—')}</code></td>
                                    <td><span class="small text-muted">${tags}</span></td>
                                </tr>
                            `;
                                })
                                .join('')}
                        </tbody>
                    </table>
                </div>
            `;
        }

        let linksHtml = '';
        if (links.length === 0) {
            linksHtml = '<p class="text-muted">No links defined.</p>';
        } else {
            linksHtml = `
                <div class="table-responsive">
                    <table class="table table-sm table-hover">
                        <thead>
                            <tr>
                                <th>Label</th>
                                <th>Source</th>
                                <th>Target</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${links
                                .map(
                                    l => `
                                <tr>
                                    <td><i class="bi bi-arrow-left-right me-1 text-muted"></i>${escapeHtml(l.label || '—')}</td>
                                    <td>${escapeHtml(l.source_node || '—')} <span class="text-muted small">${escapeHtml(l.source_interface || '')}</span></td>
                                    <td>${escapeHtml(l.target_node || '—')} <span class="text-muted small">${escapeHtml(l.target_interface || '')}</span></td>
                                </tr>
                            `
                                )
                                .join('')}
                        </tbody>
                    </table>
                </div>
            `;
        }

        return `
            <div class="row g-3">
                <div class="col-12">
                    <h6><i class="bi bi-hdd-stack me-1"></i> Nodes (${nodes.length})</h6>
                    ${nodesHtml}
                </div>
                <div class="col-12">
                    <h6><i class="bi bi-arrow-left-right me-1"></i> Links (${links.length})</h6>
                    ${linksHtml}
                </div>
            </div>
        `;
    }

    // ===========================================================================
    // Revisions Tab
    // ===========================================================================

    async _loadRevisionsTab() {
        const panel = this.querySelector('#lab-tab-panel');
        if (!panel) return;

        if (this._revisions) {
            panel.innerHTML = this._renderRevisionsContent(this._revisions);
            return;
        }

        panel.innerHTML = this._renderLoadingSpinner();

        try {
            this._revisions = await labRecordsApi.getLabRecordRevisions(this._labRecordId);
            panel.innerHTML = this._renderRevisionsContent(this._revisions);
        } catch (error) {
            panel.innerHTML = `<div class="alert alert-warning">Failed to load revisions: ${escapeHtml(error.message)}</div>`;
        }
    }

    _renderRevisionsContent(revisions) {
        const list = Array.isArray(revisions) ? revisions : revisions?.revisions || [];

        if (list.length === 0) {
            return '<div class="text-center text-muted py-4"><i class="bi bi-clock-history fs-1 d-block mb-2"></i>No revisions recorded yet.</div>';
        }

        return `
            <div class="table-responsive">
                <table class="table table-sm table-hover">
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>Timestamp</th>
                            <th>Changes</th>
                            <th>Source</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${list
                            .map(
                                (r, i) => `
                            <tr>
                                <td><span class="badge bg-light text-dark">${r.revision || list.length - i}</span></td>
                                <td>${r.timestamp ? formatDateWithRelative(r.timestamp) : '—'}</td>
                                <td>${escapeHtml(r.summary || r.changes || '—')}</td>
                                <td>${escapeHtml(r.source || '—')}</td>
                            </tr>
                        `
                            )
                            .join('')}
                    </tbody>
                </table>
            </div>
        `;
    }

    // ===========================================================================
    // Linked Lablets Tab
    // ===========================================================================

    async _loadLinkedLabletsTab() {
        const panel = this.querySelector('#lab-tab-panel');
        if (!panel) return;

        if (this._linkedLablets) {
            panel.innerHTML = this._renderLinkedLabletsContent(this._linkedLablets);
            this._bindUnbindHandlers();
            return;
        }

        panel.innerHTML = this._renderLoadingSpinner();

        try {
            this._linkedLablets = await labRecordsApi.getLabRecordBindings(this._labRecordId);
            panel.innerHTML = this._renderLinkedLabletsContent(this._linkedLablets);
            this._bindUnbindHandlers();
        } catch (error) {
            panel.innerHTML = `<div class="alert alert-warning">Failed to load linked lablets: ${escapeHtml(error.message)}</div>`;
        }
    }

    _renderLinkedLabletsContent(bindings) {
        const bindingList = Array.isArray(bindings) ? bindings : bindings?.items || [];

        if (bindingList.length === 0) {
            return '<div class="text-center text-muted py-4"><i class="bi bi-link-45deg fs-1 d-block mb-2"></i>No lablet bindings yet.</div>';
        }

        return `
            <div class="table-responsive">
                <table class="table table-sm table-hover">
                    <thead>
                        <tr>
                            <th>Instance ID</th>
                            <th>Role</th>
                            <th>Bound At</th>
                            <th>Status</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody>
                        ${bindingList
                            .map(
                                b => `
                            <tr>
                                <td><code class="small">${escapeHtml(b.instance_id || b.lablet_instance_id || '—')}</code></td>
                                <td>${escapeHtml(b.role || '—')}</td>
                                <td>${b.bound_at ? formatDateWithRelative(b.bound_at) : '—'}</td>
                                <td><lcm-status-badge status="${escapeHtml(b.status || 'active')}" pill></lcm-status-badge></td>
                                <td>
                                    <button class="btn btn-sm btn-outline-danger unbind-btn"
                                        data-instance-id="${escapeHtml(b.instance_id || b.lablet_instance_id || '')}"
                                        title="Unbind">
                                        <i class="bi bi-x-lg"></i>
                                    </button>
                                </td>
                            </tr>
                        `
                            )
                            .join('')}
                    </tbody>
                </table>
            </div>
        `;
    }

    _bindUnbindHandlers() {
        requestAnimationFrame(() => {
            this.querySelectorAll('.unbind-btn').forEach(btn => {
                btn.addEventListener('click', async () => {
                    const instanceId = btn.dataset.instanceId;
                    if (!instanceId) return;
                    const confirmed = await showConfirmAsync('Unbind Lablet', `Unbind lablet instance ${instanceId} from this lab?`, { actionLabel: 'Unbind', actionClass: 'btn-warning' });
                    if (!confirmed) return;
                    try {
                        await labRecordsApi.unbindLabFromLablet(this._labRecordId, instanceId, 'Manual unbind from UI');
                        showToast('Unbind initiated', 'info');
                        this._linkedLablets = null; // Force reload
                        this._loadLinkedLabletsTab();
                    } catch (err) {
                        showToast(`Unbind failed: ${err.message}`, 'error');
                    }
                });
            });
        });
    }

    // ===========================================================================
    // Runs Tab
    // ===========================================================================

    async _loadRunsTab() {
        const panel = this.querySelector('#lab-tab-panel');
        if (!panel) return;

        if (this._runs) {
            panel.innerHTML = this._renderRunsContent(this._runs);
            return;
        }

        panel.innerHTML = this._renderLoadingSpinner();

        try {
            this._runs = await labRecordsApi.getLabRecordRuns(this._labRecordId);
            panel.innerHTML = this._renderRunsContent(this._runs);
        } catch (error) {
            panel.innerHTML = `<div class="alert alert-warning">Failed to load runs: ${escapeHtml(error.message)}</div>`;
        }
    }

    _renderRunsContent(response) {
        const runList = Array.isArray(response) ? response : response?.runs || [];
        const runCount = response?.run_count ?? runList.length;
        const status = (this._labRecord?.status || '').toLowerCase();
        const isRunning = ['booted', 'converging', 'converged', 'starting', 'queued'].includes(status);

        const runningBanner = isRunning
            ? `<div class="alert alert-success d-flex align-items-center mb-3">
                   <i class="bi bi-play-circle-fill fs-5 me-2"></i>
                   <div>
                       <strong>Lab is currently running</strong>
                       <span class="text-muted ms-2">(status: <lcm-status-badge status="${escapeHtml(status)}" pill></lcm-status-badge>)</span>
                   </div>
               </div>`
            : '';

        if (runList.length === 0) {
            return `${runningBanner}<div class="text-center text-muted py-4"><i class="bi bi-play-circle fs-1 d-block mb-2"></i>No runs recorded yet.</div>`;
        }

        return `
            ${runningBanner}
            <h6 class="d-flex align-items-center mb-3">
                <i class="bi bi-play-circle me-2"></i>Run History
                <span class="badge bg-secondary ms-2">${runCount}</span>
            </h6>
            <div class="table-responsive">
                <table class="table table-sm table-hover align-middle">
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>Started</th>
                            <th>Duration</th>
                            <th>Started By</th>
                            <th>Stop Reason</th>
                            <th>Final State</th>
                            <th>Session</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${runList
                            .map((r, i) => {
                                const isActive = !r.stopped_at;
                                const rowClass = isActive ? 'table-success' : '';
                                const duration = this._formatRunDuration(r);
                                const runNum = runCount - i;
                                return `
                            <tr class="${rowClass}">
                                <td><span class="badge bg-light text-dark">${runNum}</span></td>
                                <td>${r.started_at ? formatDateWithRelative(r.started_at) : '—'}</td>
                                <td>
                                    ${isActive ? '<span class="badge bg-success"><i class="bi bi-play-fill me-1"></i>Running</span>' : `<span class="text-muted small">${duration}</span>`}
                                </td>
                                <td><span class="small">${escapeHtml(r.started_by || '—')}</span></td>
                                <td><span class="small">${escapeHtml(r.stop_reason || '—')}</span></td>
                                <td>${r.final_state ? `<lcm-status-badge status="${escapeHtml(r.final_state)}" pill></lcm-status-badge>` : '—'}</td>
                                <td>${r.lablet_session_id ? `<code class="small" title="${escapeHtml(r.lablet_session_id)}">${escapeHtml(r.lablet_session_id.substring(0, 8))}…</code>` : '<span class="text-muted small">—</span>'}</td>
                            </tr>
                        `;
                            })
                            .join('')}
                    </tbody>
                </table>
            </div>
        `;
    }

    /**
     * Format run duration from a LabRunRecord dict.
     * Uses duration_seconds if available, otherwise calculates from timestamps.
     */
    _formatRunDuration(run) {
        let seconds = run.duration_seconds;
        if (seconds == null && run.started_at && run.stopped_at) {
            seconds = Math.round((new Date(run.stopped_at) - new Date(run.started_at)) / 1000);
        }
        if (seconds == null || seconds < 0) return '—';

        if (seconds < 60) return `${seconds}s`;
        const mins = Math.floor(seconds / 60);
        const secs = seconds % 60;
        if (mins < 60) return `${mins}m ${secs}s`;
        const hrs = Math.floor(mins / 60);
        const remMins = mins % 60;
        if (hrs < 24) return `${hrs}h ${remMins}m`;
        const days = Math.floor(hrs / 24);
        const remHrs = hrs % 24;
        return `${days}d ${remHrs}h`;
    }

    // ===========================================================================
    // Footer Actions
    // ===========================================================================

    _renderFooterActions() {
        const footer = this.querySelector('#labDetailModalFooter');
        if (!footer || !this._labRecord) return;

        const status = (this._labRecord.status || '').toLowerCase();
        const pendingAction = this._labRecord.pending_action;
        const actionButtons = Object.entries(STATUS_ACTIONS)
            .filter(([, cfg]) => cfg.allowed.includes(status))
            .map(
                ([action, cfg]) => `
                <button class="btn btn-${cfg.variant} btn-sm lab-action-btn" data-action="${action}" ${pendingAction ? 'disabled' : ''}>
                    <i class="bi ${cfg.icon} me-1"></i>${cfg.label}
                </button>
            `
            )
            .join('');

        const pendingBadge = pendingAction ? `<span class="badge bg-warning text-dark me-2"><i class="bi bi-hourglass-split me-1"></i>${pendingAction}…</span>` : '';

        footer.innerHTML = `
            <div class="me-auto d-flex align-items-center gap-2">
                ${pendingBadge}
                ${actionButtons}
            </div>
            <button type="button" class="btn btn-outline-primary btn-sm" id="lab-detail-refresh-btn">
                <i class="bi bi-arrow-clockwise me-1"></i>Refresh
            </button>
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
        `;

        // Bind action buttons
        footer.querySelectorAll('.lab-action-btn').forEach(btn => {
            btn.addEventListener('click', () => this._executeAction(btn.dataset.action));
        });

        footer.querySelector('#lab-detail-refresh-btn')?.addEventListener('click', () => {
            this._topology = null;
            this._revisions = null;
            this._linkedLablets = null;
            this._runs = null;
            this.open(this._labRecordId);
        });
    }

    async _executeAction(action) {
        const cfg = STATUS_ACTIONS[action];
        if (!cfg) return;

        if (cfg.confirm) {
            const labTitle = this._labRecord?.title || this._labRecordId;
            const variantMap = { danger: 'btn-danger', warning: 'btn-warning', secondary: 'btn-secondary' };
            showConfirm(`${cfg.label} Lab`, `Are you sure you want to <strong>${action}</strong> &ldquo;${escapeHtml(labTitle)}&rdquo;?`, () => this._performAction(action), {
                actionLabel: cfg.label,
                actionClass: variantMap[cfg.variant] || 'btn-danger',
                iconClass: `bi ${cfg.icon} text-warning me-2`,
            });
            return;
        }

        await this._performAction(action);
    }

    async _performAction(action) {
        try {
            switch (action) {
                case 'start':
                    await labRecordsApi.startLabRecord(this._labRecordId);
                    showToast(`Start queued`, 'info');
                    break;
                case 'stop':
                    await labRecordsApi.stopLabRecord(this._labRecordId);
                    showToast(`Stop queued`, 'info');
                    break;
                case 'wipe':
                    await labRecordsApi.wipeLabRecord(this._labRecordId);
                    showToast(`Wipe queued`, 'info');
                    break;
                case 'delete':
                    await labRecordsApi.deleteLabRecord(this._labRecordId);
                    showToast(`Delete queued`, 'warning');
                    this.close();
                    break;
                case 'clone':
                    await labRecordsApi.cloneLabRecord(this._labRecordId);
                    showToast(`Clone initiated`, 'info');
                    break;
                case 'export': {
                    const yaml = await labRecordsApi.exportLabRecord(this._labRecordId);
                    const blob = new Blob([yaml], { type: 'text/yaml' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `${this._labRecord?.title || 'lab'}.yaml`;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    URL.revokeObjectURL(url);
                    showToast(`Exported`, 'success');
                    break;
                }
                case 'archive':
                    await labRecordsApi.archiveLabRecord(this._labRecordId);
                    showToast(`Archive initiated`, 'info');
                    break;
            }
        } catch (error) {
            showToast(`${action} failed: ${error.message}`, 'error');
        }
    }

    // ===========================================================================
    // Helpers
    // ===========================================================================

    _renderLoadingSpinner() {
        return `
            <div class="d-flex justify-content-center align-items-center py-5">
                <div class="spinner-border text-primary" role="status">
                    <span class="visually-hidden">Loading...</span>
                </div>
            </div>
        `;
    }

    _renderError(message) {
        const body = this.querySelector('#labDetailModalBody');
        if (body) {
            body.innerHTML = `<div class="alert alert-danger"><i class="bi bi-exclamation-triangle me-2"></i>${escapeHtml(message)}</div>`;
        }
    }
}

if (!customElements.get('lab-detail-modal')) {
    customElements.define('lab-detail-modal', LabDetailModal);
}

export default LabDetailModal;
