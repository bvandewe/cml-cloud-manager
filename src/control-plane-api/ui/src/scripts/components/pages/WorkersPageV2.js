/**
 * WorkersPageV2 — Store-driven Workers management page
 *
 * Migration target for WorkersPage (Phase M2).
 * Replaces inline column definitions + LcmDataTable + direct API calls with:
 *   - Column registry (workerColumns.js) with SchemaColumn format
 *   - ui-data-table (from @neuroglia/ui-core) with component cell rendering
 *   - StateStore workers slice (reactive, SSE-driven updates)
 *   - Direct worker-card rendering from store data (no WorkerList wrapper)
 *
 * Preserves all existing features:
 *   - Dual view modes: Card grid + Table view with toggle
 *   - Collapsible fleet capacity panel (CPU, memory, storage, nodes)
 *   - Filterable data table (status, region, search)
 *   - Worker actions: Start, Stop, Terminate with confirm dialogs
 *   - Real-time SSE updates (via store slice subscriptions)
 *   - Worker detail modal on row/card click
 *   - Templates tab (admin-only) — store-driven via templatesSlice
 *
 * @module components/pages/WorkersPageV2
 */

import { StoreConnectedPage } from '../../bridge/StoreConnectedPage.js';
import { store } from '../../app/store.js';
import {
    selectAllWorkers,
    selectFleetCapacity,
    selectWorkersListLoading,
    selectWorkerStatusSummary,
    createWorkersActions,
    selectAllTemplates,
    selectTemplatesListLoading,
    createTemplatesActions,
    selectAllLabRecords,
    createLabRecordsActions,
} from '../../app/index.js';
import { eventBus, EventTypes } from '../../app/eventBus.js';
import { WORKER_COLUMNS, WORKER_DEFAULT_COLUMNS } from '../../columns/workerColumns.js';
import { showToast } from '../../ui/notifications.js';
import { showConfirmAsync } from '../modals.js';
import '../core/LcmTabView.js';
import '../core/LcmActionBar.js';
import '../core/LcmMetricCard.js';
import '../WorkerCard.js';
import '../WorkerDetailsModal.js';
import './LabDetailModal.js';

const STORAGE_KEY_CAPACITY = 'lcm.workers.capacityCollapsed';
const STORAGE_KEY_VIEW_MODE = 'lcm.workers.viewMode';
const TABLE_STORAGE_KEY = 'lcm.workers.table';

/**
 * Row actions for the instances data table.
 */
const ROW_ACTIONS = [
    {
        id: 'view',
        label: 'Details',
        icon: 'bi-eye',
        variant: 'outline-primary',
    },
    {
        id: 'start',
        label: 'Start',
        icon: 'bi-play',
        variant: 'outline-success',
        condition: row => {
            const st = (row.status || '').toLowerCase();
            return st !== 'running' && st !== 'pending' && st !== 'terminated';
        },
    },
    {
        id: 'stop',
        label: 'Stop',
        icon: 'bi-stop',
        variant: 'outline-warning',
        condition: row => {
            const st = (row.status || '').toLowerCase();
            return st === 'running';
        },
    },
    {
        id: 'terminate',
        label: 'Terminate',
        icon: 'bi-trash',
        variant: 'outline-danger',
        condition: row => {
            const st = (row.status || '').toLowerCase();
            return st !== 'terminated';
        },
    },
];

export class WorkersPageV2 extends StoreConnectedPage {
    static get observedAttributes() {
        return ['active-tab', 'view-mode'];
    }

    constructor() {
        super();
        this._activeTab = 'instances';
        this._viewMode = null; // Set during initialize based on role
        this._capacityCollapsed = localStorage.getItem(STORAGE_KEY_CAPACITY) !== 'false';
        this._clientSearchTerm = '';
        this._selectedRegion = null;
        this._selectedStatus = null;
        this._totalInstances = 0; // Loaded async for fleet panel
        /** @type {ReturnType<typeof createTemplatesActions>|null} */
        this._templateActions = null;
    }

    // =========================================================================
    // StoreConnectedPage Overrides
    // =========================================================================

    getStoreInstance() {
        return store;
    }

    getActionCreators(storeInstance) {
        return createWorkersActions(storeInstance);
    }

    subscribeToStore() {
        // React to workers list changes → update table + cards
        this.connectSlice('workers', selectAllWorkers, workers => {
            this._updateInstancesView(workers);
        });

        // React to fleet capacity changes → update capacity panel
        this.connectSlice('workers', selectFleetCapacity, fleet => {
            this._updateFleetCapacityPanel(fleet);
        });

        // React to loading state → show/hide spinner
        this.connectSlice('workers', selectWorkersListLoading, loading => {
            this._updateLoadingState(loading);
        });

        // React to status summary → update metric tiles
        this.connectSlice('workers', selectWorkerStatusSummary, summary => {
            this._updateStatusSummary(summary);
        });

        // React to templates list changes → update templates table
        this.connectSlice('templates', selectAllTemplates, templates => {
            this._updateTemplatesView(templates);
        });

        // React to templates loading state
        this.connectSlice('templates', selectTemplatesListLoading, loading => {
            const table = this.querySelector('#worker-templates-table-v2');
            if (table) {
                if (loading) {
                    table.setAttribute('loading', '');
                } else {
                    table.removeAttribute('loading');
                }
            }
        });

        // React to lab records changes → update lab_records_count on workers table
        this.connectSlice('labRecords', selectAllLabRecords, () => {
            // Re-derive workers view to include updated lab record counts
            const workers = selectAllWorkers(store.getState());
            this._updateInstancesView(workers);
        });
    }

    loadInitialData() {
        // Set default view mode based on role (admin=table, user=cards)
        const savedViewMode = localStorage.getItem(STORAGE_KEY_VIEW_MODE);
        this._viewMode = savedViewMode || (this.isAdminOrManager() ? 'table' : 'cards');
        // Re-render with correct view mode now that we know the role
        this.render();
        this._bindInteractions();
        this._configureDataTable();

        // Load workers from API into store
        this.actions.loadWorkers(this._selectedRegion);

        // Load lab records into store (for lab_records_count enrichment)
        this._labRecordsActions = createLabRecordsActions(this.getStoreInstance());
        this._labRecordsActions.loadLabRecords();

        // Load templates into store if admin
        if (this.isAdminOrManager()) {
            this._templateActions = createTemplatesActions(this.getStoreInstance());
            this._templateActions.loadTemplates();
        }

        // Load instance count async for fleet panel
        this._loadInstanceCount();
    }

    // =========================================================================
    // SSE Event Listeners (supplements store-driven updates)
    // =========================================================================

    _setupPageEventListeners() {
        // Worker status changes → already handled by store subscription via SSE adapter
        // Worker snapshot → already handled by store subscription via SSE adapter

        // Worker terminated → refresh list (SSE adapter removes from store,
        // but we also need to update fleet capacity)
        this.subscribe(EventTypes.WORKER_TERMINATED, () => {
            // Store already updated via sseAdapter dispatch
        });

        // Workers refresh completed (bulk refresh)
        this.subscribe(EventTypes.WORKERS_REFRESH_COMPLETED, () => {
            // Data already updated in store
        });
    }

    // =========================================================================
    // Worker Actions (user interactions from table row actions)
    // =========================================================================

    async _handleWorkerAction(action, worker) {
        if (!worker || !worker.id) return;

        switch (action) {
            case 'view':
                this._openWorkerDetails(worker);
                break;

            case 'start':
                try {
                    await this.actions.startWorker(worker.id);
                    showToast(`Starting worker "${worker.name}"...`, 'success');
                } catch (err) {
                    console.error('[WorkersPageV2] Failed to start worker:', err);
                    showToast(`Failed to start worker: ${err.message}`, 'danger');
                }
                break;

            case 'stop':
                try {
                    await this.actions.stopWorker(worker.id);
                    showToast(`Stopping worker "${worker.name}"...`, 'success');
                } catch (err) {
                    console.error('[WorkersPageV2] Failed to stop worker:', err);
                    showToast(`Failed to stop worker: ${err.message}`, 'danger');
                }
                break;

            case 'terminate': {
                const confirmed = await showConfirmAsync('Terminate Worker', `Are you sure you want to terminate worker "${worker.name}"? This cannot be undone.`, { actionLabel: 'Terminate', actionClass: 'btn-danger' });
                if (!confirmed) return;
                try {
                    await this.actions.terminateWorker(worker.id);
                    showToast(`Worker "${worker.name}" terminated.`, 'warning');
                } catch (err) {
                    console.error('[WorkersPageV2] Failed to terminate worker:', err);
                    showToast(`Failed to terminate worker: ${err.message}`, 'danger');
                }
                break;
            }

            default:
                console.warn('[WorkersPageV2] Unknown worker action:', action);
        }
    }

    _openWorkerDetails(worker) {
        const region = worker.aws_region || worker.region || 'us-east-1';
        eventBus.emit('UI_OPEN_WORKER_DETAILS', {
            workerId: worker.id,
            region: region,
        });
    }

    // =========================================================================
    // Template Actions (store-driven via templatesSlice)
    // =========================================================================

    /**
     * Update the templates table from store data.
     * Called reactively via connectSlice subscription.
     */
    _updateTemplatesView(templates) {
        const table = this.querySelector('#worker-templates-table-v2');
        if (table) {
            table.setData(Array.isArray(templates) ? templates : []);
        }
    }

    async _handleTemplateAction(action, template) {
        if (!this._templateActions) return;

        switch (action) {
            case 'view-template':
                this._openTemplateModal(template, 'view');
                break;

            case 'edit-template':
                this._openTemplateModal(template, 'edit');
                break;

            case 'deploy-template':
                this._deployFromTemplate(template);
                break;

            case 'enable-template':
                try {
                    await this._templateActions.enableTemplate(template.id);
                    showToast(`Template "${template.name}" enabled.`, 'success');
                } catch (err) {
                    console.error('[WorkersPageV2] Failed to enable template:', err);
                    showToast(`Failed to enable template: ${err.message}`, 'danger');
                }
                break;

            case 'disable-template': {
                const confirmed = await showConfirmAsync('Disable Template', `Disable template "${template.name}"? It will no longer be available for worker provisioning.`, { actionLabel: 'Disable', actionClass: 'btn-warning' });
                if (!confirmed) return;
                try {
                    await this._templateActions.disableTemplate(template.id);
                    showToast(`Template "${template.name}" disabled.`, 'warning');
                } catch (err) {
                    console.error('[WorkersPageV2] Failed to disable template:', err);
                    showToast(`Failed to disable template: ${err.message}`, 'danger');
                }
                break;
            }

            case 'delete-template': {
                const confirmed = await showConfirmAsync('Delete Template', `Are you sure you want to delete template "${template.name}"? This action cannot be undone.`, { actionLabel: 'Delete', actionClass: 'btn-danger' });
                if (!confirmed) return;
                try {
                    await this._templateActions.deleteTemplate(template.id);
                    showToast(`Template "${template.name}" deleted.`, 'warning');
                } catch (err) {
                    console.error('[WorkersPageV2] Failed to delete template:', err);
                    showToast(`Failed to delete template: ${err.message}`, 'danger');
                }
                break;
            }

            default:
                console.warn('[WorkersPageV2] Unknown template action:', action);
        }
    }

    _deployFromTemplate(template) {
        const createModal = document.getElementById('createWorkerModal');
        if (!createModal) {
            console.warn('[WorkersPageV2] createWorkerModal not found in DOM');
            return;
        }

        // Prepopulate form fields from template
        const nameInput = createModal.querySelector('[name="name"], #worker-name');
        const instanceTypeSelect = createModal.querySelector('[name="instance_type"], #worker-instance-type');
        const amiNameInput = createModal.querySelector('[name="ami_name"], #worker-ami-name');

        if (nameInput) nameInput.value = `${template.name}-worker`;
        if (instanceTypeSelect) instanceTypeSelect.value = template.instance_type || '';
        if (amiNameInput) amiNameInput.value = template.ami_name_pattern || '';

        import('bootstrap').then(bootstrap => {
            new bootstrap.Modal(createModal).show();
        });
    }

    _openTemplateModal(template, mode = 'view') {
        if (!document.getElementById('workerTemplateModalV2')) {
            this._injectTemplateModal();
        }
        const modal = document.getElementById('workerTemplateModalV2');
        if (!modal) return;

        const isEdit = mode === 'edit';
        const title = modal.querySelector('.modal-title');
        if (title) title.textContent = isEdit ? `Edit Template: ${template.name}` : `Template: ${template.name}`;

        this._populateTemplateModal(modal, template, isEdit);

        import('bootstrap').then(bootstrap => {
            new bootstrap.Modal(modal).show();
        });
    }

    _injectTemplateModal() {
        const html = `
        <div class="modal fade" id="workerTemplateModalV2" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Worker Template</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <form id="templateFormV2">
                            <div class="row g-3">
                                <div class="col-md-6">
                                    <label class="form-label">Name</label>
                                    <input type="text" class="form-control" name="name" readonly>
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label">Instance Type</label>
                                    <select class="form-select" name="instance_type">
                                        <option value="t3.micro">t3.micro</option>
                                        <option value="t3.small">t3.small</option>
                                        <option value="t3.medium">t3.medium</option>
                                        <option value="t3.large">t3.large</option>
                                        <option value="m5zn.metal">m5zn.metal</option>
                                    </select>
                                </div>
                                <div class="col-12">
                                    <label class="form-label">Description</label>
                                    <textarea class="form-control" name="description" rows="2"></textarea>
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label">AMI Name Pattern</label>
                                    <input type="text" class="form-control" name="ami_name_pattern">
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label">Cost/hr (USD)</label>
                                    <input type="number" class="form-control" name="cost_per_hour_usd" step="0.01" min="0">
                                </div>
                                <div class="col-md-3">
                                    <label class="form-label">CPU Cores</label>
                                    <input type="number" class="form-control" name="cpu_cores" min="1">
                                </div>
                                <div class="col-md-3">
                                    <label class="form-label">Memory (GB)</label>
                                    <input type="number" class="form-control" name="memory_gb" min="1">
                                </div>
                                <div class="col-md-3">
                                    <label class="form-label">Storage (GB)</label>
                                    <input type="number" class="form-control" name="storage_gb" min="10">
                                </div>
                                <div class="col-md-3">
                                    <label class="form-label">Max Nodes</label>
                                    <input type="number" class="form-control" name="max_nodes" min="1">
                                </div>
                            </div>
                        </form>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                        <button type="button" class="btn btn-primary" id="templateSaveBtnV2" style="display:none;">Save Changes</button>
                    </div>
                </div>
            </div>
        </div>
        `;
        document.body.insertAdjacentHTML('beforeend', html);

        document.getElementById('templateSaveBtnV2')?.addEventListener('click', () => this._saveTemplate());
    }

    _populateTemplateModal(modal, template, isEdit) {
        const form = modal.querySelector('#templateFormV2');
        if (!form) return;

        form.querySelector('[name="name"]').value = template.name || '';
        form.querySelector('[name="description"]').value = template.description || '';
        form.querySelector('[name="instance_type"]').value = template.instance_type || '';
        form.querySelector('[name="ami_name_pattern"]').value = template.ami_name_pattern || '';
        form.querySelector('[name="cost_per_hour_usd"]').value = template.cost_per_hour_usd || 0;
        form.querySelector('[name="cpu_cores"]').value = template.capacity?.cpu_cores || '';
        form.querySelector('[name="memory_gb"]').value = template.capacity?.memory_gb || '';
        form.querySelector('[name="storage_gb"]').value = template.capacity?.storage_gb || '';
        form.querySelector('[name="max_nodes"]').value = template.capacity?.max_nodes || '';

        form.querySelectorAll('input:not([name="name"]), textarea, select').forEach(el => {
            el.disabled = !isEdit;
        });

        const saveBtn = modal.querySelector('#templateSaveBtnV2');
        if (saveBtn) {
            saveBtn.style.display = isEdit ? '' : 'none';
            saveBtn.dataset.templateId = template.id;
        }
    }

    async _saveTemplate() {
        const modal = document.getElementById('workerTemplateModalV2');
        if (!modal) return;

        const form = modal.querySelector('#templateFormV2');
        const templateId = modal.querySelector('#templateSaveBtnV2')?.dataset.templateId;
        if (!form || !templateId) return;

        const updateData = {
            description: form.querySelector('[name="description"]').value,
            instance_type: form.querySelector('[name="instance_type"]').value,
            ami_name_pattern: form.querySelector('[name="ami_name_pattern"]').value,
            cost_per_hour_usd: parseFloat(form.querySelector('[name="cost_per_hour_usd"]').value) || 0,
            cpu_cores: parseInt(form.querySelector('[name="cpu_cores"]').value) || undefined,
            memory_gb: parseInt(form.querySelector('[name="memory_gb"]').value) || undefined,
            storage_gb: parseInt(form.querySelector('[name="storage_gb"]').value) || undefined,
            max_nodes: parseInt(form.querySelector('[name="max_nodes"]').value) || undefined,
        };

        try {
            await this._templateActions.updateTemplate(templateId, updateData);
            showToast('Template updated successfully.', 'success');
            import('bootstrap').then(bootstrap => {
                bootstrap.Modal.getInstance(modal)?.hide();
            });
        } catch (err) {
            console.error('[WorkersPageV2] Failed to save template:', err);
            showToast(`Failed to save template: ${err.message}`, 'danger');
        }
    }

    // =========================================================================
    // Data Table (Instances)
    // =========================================================================

    _configureDataTable() {
        const table = this.querySelector('#worker-instances-table-v2');
        if (!table) return;

        // Configure schema-driven columns with defaults
        table.setSchemaColumns(WORKER_COLUMNS, WORKER_DEFAULT_COLUMNS);

        // Add row actions
        table.setRowActions(ROW_ACTIONS);

        // Handle row actions
        table.addEventListener('row-action', e => {
            const { action, row } = e.detail;
            this._handleWorkerAction(action, row);
        });

        // Handle row click → open worker details modal
        table.addEventListener('row-click', e => {
            const { row } = e.detail;
            if (row?.id) {
                this._openWorkerDetails(row);
            }
        });
    }

    _updateInstancesView(workers) {
        let data = Array.isArray(workers) ? [...workers] : [];

        // Enrich workers with lab_records_count from labRecords store slice
        const labRecords = selectAllLabRecords(store.getState());
        const countByWorker = {};
        labRecords.forEach(lr => {
            if (lr.worker_id) {
                countByWorker[lr.worker_id] = (countByWorker[lr.worker_id] || 0) + 1;
            }
        });
        data = data.map(w => ({
            ...w,
            lab_records_count: countByWorker[w.id] || 0,
        }));

        // Apply client-side filters
        data = this._applyClientFilters(data);

        // Update table view
        const table = this.querySelector('#worker-instances-table-v2');
        if (table) {
            table.setData(data);
        }

        // Update card view
        this._renderCards(data);
    }

    _applyClientFilters(workers) {
        let data = workers;

        // Region filter
        if (this._selectedRegion) {
            data = data.filter(w => (w.aws_region || w.region) === this._selectedRegion);
        }

        // Status filter
        if (this._selectedStatus) {
            data = data.filter(w => (w.status || '').toLowerCase() === this._selectedStatus.toLowerCase());
        }

        // Search filter
        if (this._clientSearchTerm) {
            const term = this._clientSearchTerm.toLowerCase();
            data = data.filter(
                w =>
                    (w.name || '').toLowerCase().includes(term) ||
                    (w.aws_region || w.region || '').toLowerCase().includes(term) ||
                    (w.status || '').toLowerCase().includes(term) ||
                    (w.instance_type || '').toLowerCase().includes(term) ||
                    (w.id || '').toLowerCase().includes(term)
            );
        }

        return data;
    }

    /**
     * Render worker-card elements directly from store data (Option B — no WorkerList).
     * Only renders into the card grid container; does nothing if table view is active.
     */
    _renderCards(workers) {
        const container = this.querySelector('#worker-cards-grid-v2');
        if (!container) return;

        if (!workers || workers.length === 0) {
            container.innerHTML = `
                <div class="text-center text-muted py-5">
                    <i class="bi bi-server fs-1 d-block mb-2"></i>
                    <p>No workers found.</p>
                </div>
            `;
            return;
        }

        // Build a map of existing cards for efficient reconciliation
        const existingCards = new Map();
        container.querySelectorAll('worker-card').forEach(card => {
            existingCards.set(card.getAttribute('worker-id'), card);
        });

        const workerIds = new Set(workers.map(w => w.id));

        // Remove cards for workers no longer in the list
        existingCards.forEach((card, id) => {
            if (!workerIds.has(id)) {
                card.closest('.col')?.remove() || card.remove();
            }
        });

        // Add or update cards
        workers.forEach(worker => {
            const existingCard = existingCards.get(worker.id);
            if (existingCard) {
                // Update data attribute — card's internal EventBus subscriptions
                // handle real-time updates, but this ensures the latest snapshot
                existingCard.setAttribute('data', JSON.stringify(worker));
            } else {
                // Create new card wrapper
                const col = document.createElement('div');
                col.className = 'col-md-6 col-xl-4';
                col.innerHTML = `<worker-card worker-id="${worker.id}" data='${JSON.stringify(worker).replace(/'/g, '&#39;')}'></worker-card>`;
                container.appendChild(col);
            }
        });
    }

    _updateLoadingState(isLoading) {
        const table = this.querySelector('#worker-instances-table-v2');
        if (table) {
            if (isLoading) {
                table.setAttribute('loading', '');
            } else {
                table.removeAttribute('loading');
            }
        }

        // Show/hide loading indicator on card view
        const cardSpinner = this.querySelector('#worker-cards-spinner-v2');
        if (cardSpinner) {
            cardSpinner.style.display = isLoading ? '' : 'none';
        }
    }

    // =========================================================================
    // Fleet Capacity Panel
    // =========================================================================

    _updateFleetCapacityPanel(fleet) {
        if (!fleet) return;

        const cpuPct = fleet.totalCpuCores > 0 ? ((fleet.usedCpuCores / fleet.totalCpuCores) * 100).toFixed(1) : 0;
        const memPct = fleet.totalMemoryGb > 0 ? ((fleet.usedMemoryGb / fleet.totalMemoryGb) * 100).toFixed(1) : 0;
        const storagePct = fleet.totalStorageGb > 0 ? ((fleet.usedStorageGb / fleet.totalStorageGb) * 100).toFixed(1) : 0;
        const nodePct = fleet.totalMaxNodes > 0 ? ((fleet.usedNodes / fleet.totalMaxNodes) * 100).toFixed(1) : 0;

        // Update metric cards
        this._setMetricValue('metric-workers-v2', `${fleet.runningWorkers} / ${fleet.totalWorkers}`);
        this._setMetricValue('metric-instances-v2', String(this._totalInstances));
        this._setMetricAttr('metric-cpu-v2', 'value', `${cpuPct}%`);
        this._setMetricAttr('metric-cpu-v2', 'subtitle', `${fleet.usedCpuCores} / ${fleet.totalCpuCores} cores`);
        this._setMetricAttr('metric-cpu-v2', 'color', this._getUtilizationColor(cpuPct));
        this._setMetricAttr('metric-mem-v2', 'value', `${memPct}%`);
        this._setMetricAttr('metric-mem-v2', 'subtitle', `${fleet.usedMemoryGb} / ${fleet.totalMemoryGb} GB`);
        this._setMetricAttr('metric-mem-v2', 'color', this._getUtilizationColor(memPct));

        // Update capacity badge
        const badge = this.querySelector('#capacity-toggle-v2 .badge');
        if (badge) {
            badge.textContent = `${fleet.runningWorkers} / ${fleet.totalWorkers} RUNNING`;
        }

        // Update progress bars
        this._updateProgressBar('cpu-bar-v2', cpuPct, fleet.usedCpuCores, fleet.totalCpuCores, 'cores');
        this._updateProgressBar('mem-bar-v2', memPct, fleet.usedMemoryGb, fleet.totalMemoryGb, 'GB');
        this._updateProgressBar('storage-bar-v2', storagePct, fleet.usedStorageGb, fleet.totalStorageGb, 'GB');
        this._updateProgressBar('nodes-bar-v2', nodePct, fleet.usedNodes, fleet.totalMaxNodes, 'nodes');
    }

    _updateProgressBar(id, pct, used, total, unit) {
        const container = this.querySelector(`#${id}`);
        if (!container) return;

        const bar = container.querySelector('.progress-bar');
        const label = container.querySelector('.bar-label');
        if (bar) {
            bar.style.width = `${pct}%`;
            bar.className = `progress-bar ${this._getBarColorClass(pct)}`;
        }
        if (label) {
            label.textContent = `${used} / ${total} ${unit} (${pct}%)`;
        }
    }

    _updateStatusSummary(summary) {
        // Status summary can be used for filtering badge counts, etc.
        // Currently the fleet capacity panel handles the main display.
    }

    _setMetricValue(id, value) {
        const card = this.querySelector(`#${id}`);
        if (card) card.setAttribute('value', String(value ?? 0));
    }

    _setMetricAttr(id, attr, value) {
        const card = this.querySelector(`#${id}`);
        if (card) card.setAttribute(attr, String(value ?? ''));
    }

    async _loadInstanceCount() {
        try {
            const { listLabletSessions } = await import('../../api/lablet-sessions.js');
            const instances = await listLabletSessions({ include_terminated: false });
            this._totalInstances = instances.length;
            this._setMetricValue('metric-instances-v2', String(this._totalInstances));
        } catch (error) {
            console.warn('[WorkersPageV2] Failed to load instance count:', error);
        }
    }

    // =========================================================================
    // View Mode Toggle
    // =========================================================================

    _setViewMode(mode) {
        this._viewMode = mode;
        localStorage.setItem(STORAGE_KEY_VIEW_MODE, mode);

        // Update button states
        this.querySelectorAll('[data-view]').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.view === mode);
        });

        // Toggle visibility of card/table containers
        const cardsContainer = this.querySelector('#worker-cards-container-v2');
        const tableContainer = this.querySelector('#worker-table-container-v2');

        if (cardsContainer) cardsContainer.style.display = mode === 'cards' ? '' : 'none';
        if (tableContainer) tableContainer.style.display = mode === 'table' ? '' : 'none';

        // If switching to a view, refresh its content from current store data
        const workers = selectAllWorkers(this.getStoreState());
        const filtered = this._applyClientFilters(workers);

        if (mode === 'cards') {
            this._renderCards(filtered);
        } else {
            const table = this.querySelector('#worker-instances-table-v2');
            if (table) table.setData(filtered);
        }
    }

    // =========================================================================
    // Rendering
    // =========================================================================

    render() {
        const isAdmin = this.isAdminOrManager();
        const capacityCollapsed = this._capacityCollapsed;
        const viewMode = this._viewMode || 'table';

        this.innerHTML = `
            <div class="workers-page">
                <!-- Page Header with Action Bar -->
                <div class="page-header d-flex justify-content-between align-items-center mb-4">
                    <div>
                        <h2 class="mb-1">
                            <i class="bi bi-server me-2"></i>Workers
                        </h2>
                        <p class="text-muted mb-0">Manage CML worker instances and templates</p>
                    </div>
                    <lcm-action-bar id="workers-action-bar-v2">
                        <lcm-action-bar-primary>
                            ${
                                isAdmin
                                    ? `
                            <button class="btn btn-primary" data-action="create">
                                <i class="bi bi-plus-circle me-1"></i>New Worker
                            </button>
                            <button class="btn btn-outline-primary" data-action="create-template">
                                <i class="bi bi-file-earmark-plus me-1"></i>New Template
                            </button>
                            `
                                    : ''
                            }
                        </lcm-action-bar-primary>
                        <lcm-action-bar-secondary>
                            <button class="btn btn-outline-secondary" data-action="refresh">
                                <i class="bi bi-arrow-clockwise me-1"></i>Refresh
                            </button>
                        </lcm-action-bar-secondary>
                    </lcm-action-bar>
                </div>

                <!-- Sub-tabs with View Toggle -->
                <div class="d-flex justify-content-between align-items-center">
                    <lcm-tab-view id="workers-tabs-v2" variant="underline" persist-key="workers-tab">
                        <lcm-tab id="instances" label="Instances" icon="bi-server" active></lcm-tab>
                        ${isAdmin ? '<lcm-tab id="templates" label="Templates" icon="bi-file-code"></lcm-tab>' : ''}
                    </lcm-tab-view>

                    <!-- View Toggle (right side) - only for Instances tab -->
                    <div class="btn-group btn-group-sm" role="group" aria-label="View mode" id="view-toggle-group-v2">
                        <button type="button" class="btn btn-outline-secondary ${viewMode === 'cards' ? 'active' : ''}"
                                data-view="cards" title="Card view">
                            <i class="bi bi-grid-3x2-gap"></i>
                        </button>
                        <button type="button" class="btn btn-outline-secondary ${viewMode === 'table' ? 'active' : ''}"
                                data-view="table" title="Table view">
                            <i class="bi bi-list-ul"></i>
                        </button>
                    </div>
                </div>

                <!-- Tab Content -->
                <div class="tab-content mt-4">
                    <!-- Instances Tab -->
                    <div id="workers-instances-content-v2" class="tab-pane active">
                        ${this._renderInstancesTab(capacityCollapsed, viewMode)}
                    </div>

                    <!-- Templates Tab (Admin only) -->
                    ${
                        isAdmin
                            ? `
                    <div id="workers-templates-content-v2" class="tab-pane" style="display: none;">
                        ${this._renderTemplatesTab()}
                    </div>
                    `
                            : ''
                    }
                </div>

                <!-- Worker Details Modal (subscribes to UI_OPEN_WORKER_DETAILS via EventBus) -->
                <worker-details-modal></worker-details-modal>

                <!-- Lab Detail Modal (for cross-links from worker Labs tab) -->
                <lab-detail-modal id="lab-detail-modal-v2"></lab-detail-modal>
            </div>
        `;

        // Register content with tab view
        this._registerTabContent();
    }

    _renderInstancesTab(capacityCollapsed, viewMode) {
        return `
            <!-- Fleet Capacity Overview (Collapsible) -->
            <div class="mb-4">
                <button class="btn btn-sm btn-link text-decoration-none p-0 mb-2"
                    id="capacity-toggle-v2" type="button">
                    <i class="bi bi-${capacityCollapsed ? 'chevron-right' : 'chevron-down'} me-1"></i>
                    Fleet Capacity
                    <span class="badge bg-primary ms-2">0 / 0 RUNNING</span>
                </button>
                <div id="capacity-panel-body-v2" class="${capacityCollapsed ? 'd-none' : ''}">
                    <!-- Metric Tiles -->
                    <div class="row g-3 mb-4">
                        <div class="col-6 col-md-3">
                            <lcm-metric-card id="metric-workers-v2"
                                title="Workers" value="0 / 0" subtitle="running / total"
                                icon="bi-server" color="primary">
                            </lcm-metric-card>
                        </div>
                        <div class="col-6 col-md-3">
                            <lcm-metric-card id="metric-instances-v2"
                                title="Active Instances" value="0"
                                icon="bi-collection" color="info">
                            </lcm-metric-card>
                        </div>
                        <div class="col-6 col-md-3">
                            <lcm-metric-card id="metric-cpu-v2"
                                title="CPU Allocated" value="0%"
                                subtitle="0 / 0 cores" icon="bi-cpu" color="success">
                            </lcm-metric-card>
                        </div>
                        <div class="col-6 col-md-3">
                            <lcm-metric-card id="metric-mem-v2"
                                title="Memory Allocated" value="0%"
                                subtitle="0 / 0 GB" icon="bi-memory" color="success">
                            </lcm-metric-card>
                        </div>
                    </div>

                    <!-- Resource Allocation Progress Bars -->
                    ${this._renderUtilizationBarHtml('CPU Cores', 'cpu-bar-v2')}
                    ${this._renderUtilizationBarHtml('Memory', 'mem-bar-v2')}
                    ${this._renderUtilizationBarHtml('Storage', 'storage-bar-v2')}
                    ${this._renderUtilizationBarHtml('Nodes', 'nodes-bar-v2')}
                </div>
            </div>

            <!-- Instances Content: Card View -->
            <div id="worker-cards-container-v2" style="display: ${viewMode === 'cards' ? '' : 'none'};">
                <div id="worker-cards-spinner-v2" class="text-center py-3" style="display: none;">
                    <div class="spinner-border spinner-border-sm text-primary" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                </div>
                <div id="worker-cards-grid-v2" class="row g-3">
                    <!-- worker-card elements rendered from store data -->
                </div>
            </div>

            <!-- Instances Content: Table View -->
            <div id="worker-table-container-v2" style="display: ${viewMode === 'table' ? '' : 'none'};">
                <div class="card shadow-sm no-hover-lift">
                    <div class="card-header d-flex align-items-center bg-white py-2 gap-2">
                        <span class="fw-medium text-muted small">Instances</span>
                        <div class="d-flex align-items-center gap-2 ms-auto">
                            <div class="input-group input-group-sm" style="width: 250px;">
                                <span class="input-group-text bg-white"><i class="bi bi-search"></i></span>
                                <input type="search" class="form-control" placeholder="Search instances..." id="worker-table-search-v2">
                            </div>
                            <select class="form-select form-select-sm" id="worker-table-region-filter-v2" style="width: 200px;">
                                <option value="">All Regions</option>
                                <option value="us-east-1">US East (N. Virginia)</option>
                                <option value="us-west-1">US West (N. California)</option>
                                <option value="us-west-2">US West (Oregon)</option>
                                <option value="eu-west-1">EU (Ireland)</option>
                                <option value="eu-central-1">EU (Frankfurt)</option>
                                <option value="ap-northeast-1">Asia Pacific (Tokyo)</option>
                                <option value="ap-southeast-1">Asia Pacific (Singapore)</option>
                            </select>
                            <select class="form-select form-select-sm" id="worker-table-status-filter-v2" style="width: 160px;">
                                <option value="">All Statuses</option>
                                <option value="running">Running</option>
                                <option value="stopped">Stopped</option>
                                <option value="pending">Pending</option>
                                <option value="stopping">Stopping</option>
                                <option value="terminated">Terminated</option>
                                <option value="error">Error</option>
                            </select>
                        </div>
                    </div>
                    <div class="card-body p-0">
                        <ui-data-table id="worker-instances-table-v2"
                            page-size="25"
                            no-toolbar
                            column-picker
                            storage-key="${TABLE_STORAGE_KEY}"
                            empty-message="No workers found. Workers appear here when created or imported."
                            loading>
                        </ui-data-table>
                    </div>
                </div>
            </div>
        `;
    }

    _renderUtilizationBarHtml(label, id) {
        return `
            <div class="mb-3" id="${id}">
                <div class="d-flex justify-content-between align-items-center mb-1">
                    <span class="fw-medium small">${label}</span>
                    <span class="small text-muted bar-label">0 / 0 (0%)</span>
                </div>
                <div class="progress" style="height: 10px;">
                    <div class="progress-bar bg-success" role="progressbar"
                         style="width: 0%"
                         aria-valuenow="0" aria-valuemin="0" aria-valuemax="100">
                    </div>
                </div>
            </div>
        `;
    }

    _renderTemplatesTab() {
        return `
            <div class="card shadow-sm no-hover-lift">
                <div class="card-header d-flex align-items-center bg-white py-2 gap-2">
                    <span class="fw-medium text-muted small">Templates</span>
                    <div class="d-flex align-items-center gap-2 ms-auto">
                        <div class="input-group input-group-sm" style="width: 250px;">
                            <span class="input-group-text bg-white"><i class="bi bi-search"></i></span>
                            <input type="search" class="form-control" placeholder="Search templates..." id="template-table-search-v2">
                        </div>
                        <select class="form-select form-select-sm" id="template-table-status-filter-v2" style="width: 160px;">
                            <option value="">All Statuses</option>
                            <option value="enabled">Enabled</option>
                            <option value="disabled">Disabled</option>
                        </select>
                    </div>
                </div>
                <div class="card-body p-0">
                    <lcm-data-table
                        id="worker-templates-table-v2"
                        page-size="25"
                        selectable
                        panel-mode
                        empty-message="No worker templates found.">
                    </lcm-data-table>
                </div>
            </div>
        `;
    }

    // =========================================================================
    // Tab Management
    // =========================================================================

    _registerTabContent() {
        const tabView = this.querySelector('#workers-tabs-v2');
        if (!tabView) return;

        const instancesContent = this.querySelector('#workers-instances-content-v2');
        const templatesContent = this.querySelector('#workers-templates-content-v2');

        if (instancesContent) tabView.registerContent('instances', instancesContent);
        if (templatesContent) tabView.registerContent('templates', templatesContent);
    }

    // =========================================================================
    // Event Binding
    // =========================================================================

    _bindInteractions() {
        // Tab change
        const tabView = this.querySelector('#workers-tabs-v2');
        if (tabView) {
            tabView.addEventListener('tab-change', e => {
                this._activeTab = e.detail.tabId;
                this._onTabChange(e.detail);
            });
        }

        // Action bar
        const actionBar = this.querySelector('#workers-action-bar-v2');
        if (actionBar) {
            actionBar.addEventListener('click', e => {
                const action = e.target.closest('[data-action]')?.dataset.action;
                if (action) this._handlePageAction(action);
            });
        }

        // View toggle
        this.querySelectorAll('[data-view]').forEach(btn => {
            btn.addEventListener('click', e => {
                this._setViewMode(e.currentTarget.dataset.view);
            });
        });

        // Capacity panel toggle
        this.querySelector('#capacity-toggle-v2')?.addEventListener('click', () => {
            this._capacityCollapsed = !this._capacityCollapsed;
            localStorage.setItem(STORAGE_KEY_CAPACITY, String(this._capacityCollapsed));
            const panel = this.querySelector('#capacity-panel-body-v2');
            const icon = this.querySelector('#capacity-toggle-v2 i');
            if (panel) panel.classList.toggle('d-none', this._capacityCollapsed);
            if (icon) {
                icon.className = `bi bi-${this._capacityCollapsed ? 'chevron-right' : 'chevron-down'} me-1`;
            }
        });

        // Table filters
        this._bindTableFilters();

        // Template table events
        this._configureTemplatesTable();
    }

    _bindTableFilters() {
        // Search (debounced)
        const searchInput = this.querySelector('#worker-table-search-v2');
        let searchTimeout;
        searchInput?.addEventListener('input', e => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                this._clientSearchTerm = e.target.value;
                const workers = selectAllWorkers(this.getStoreState());
                this._updateInstancesView(workers);
            }, 300);
        });

        // Region filter (client-side)
        this.querySelector('#worker-table-region-filter-v2')?.addEventListener('change', e => {
            this._selectedRegion = e.target.value || null;
            const workers = selectAllWorkers(this.getStoreState());
            this._updateInstancesView(workers);
        });

        // Status filter (client-side)
        this.querySelector('#worker-table-status-filter-v2')?.addEventListener('change', e => {
            this._selectedStatus = e.target.value || null;
            const workers = selectAllWorkers(this.getStoreState());
            this._updateInstancesView(workers);
        });
    }

    _configureTemplatesTable() {
        const templatesTable = this.querySelector('#worker-templates-table-v2');
        if (!templatesTable) return;

        templatesTable.setColumns([
            { field: 'name', label: 'Name', sortable: true },
            { field: 'description', label: 'Description' },
            { field: 'instance_type', label: 'Instance Type', sortable: true },
            {
                field: 'capacity',
                label: 'Capacity',
                render: val => {
                    if (!val) return '-';
                    return `${val.cpu_cores} CPU, ${val.memory_gb}GB RAM`;
                },
            },
            {
                field: 'cost_per_hour_usd',
                label: 'Cost/hr',
                sortable: true,
                render: val => (val ? `$${val.toFixed(2)}` : '-'),
            },
            {
                field: 'enabled',
                label: 'Status',
                sortable: true,
                render: val => (val ? '<span class="badge bg-success">Enabled</span>' : '<span class="badge bg-secondary">Disabled</span>'),
            },
            { field: 'updated_at', label: 'Updated', sortable: true, type: 'datetime' },
            {
                field: 'actions',
                label: 'Actions',
                render: (_, row) => {
                    const toggleBtn = row.enabled
                        ? `<button class="btn btn-sm btn-outline-warning lcm-row-action p-1" data-action="disable-template" data-row-id="${row.id}" title="Disable template">
                            <i class="bi bi-pause-circle"></i>
                        </button>`
                        : `<button class="btn btn-sm btn-outline-success lcm-row-action p-1" data-action="enable-template" data-row-id="${row.id}" title="Enable template">
                            <i class="bi bi-play-circle"></i>
                        </button>`;
                    return `
                        <div class="btn-group btn-group-sm">
                            <button class="btn btn-sm btn-outline-success lcm-row-action p-1" data-action="deploy-template" data-row-id="${row.id}" title="Create worker from template">
                                <i class="bi bi-rocket"></i>
                            </button>
                            <button class="btn btn-sm btn-outline-primary lcm-row-action p-1" data-action="view-template" data-row-id="${row.id}" title="View template">
                                <i class="bi bi-eye"></i>
                            </button>
                            <button class="btn btn-sm btn-outline-secondary lcm-row-action p-1" data-action="edit-template" data-row-id="${row.id}" title="Edit template">
                                <i class="bi bi-pencil"></i>
                            </button>
                            ${toggleBtn}
                            <button class="btn btn-sm btn-outline-danger lcm-row-action p-1" data-action="delete-template" data-row-id="${row.id}" title="Delete template">
                                <i class="bi bi-trash"></i>
                            </button>
                        </div>
                    `;
                },
            },
        ]);

        // Row click → view details
        templatesTable.addEventListener('row-click', e => {
            const row = e.detail?.row;
            if (row) this._openTemplateModal(row, 'view');
        });

        // Row action buttons
        templatesTable.addEventListener('row-action', e => {
            const { action, row } = e.detail || {};
            if (action && row) this._handleTemplateAction(action, row);
        });

        // Template search
        const searchInput = this.querySelector('#template-table-search-v2');
        let searchTimeout;
        searchInput?.addEventListener('input', e => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                templatesTable.setSearch(e.target.value);
            }, 300);
        });

        // Template status filter
        this.querySelector('#template-table-status-filter-v2')?.addEventListener('change', e => {
            const status = e.target.value;
            if (status === 'enabled') {
                templatesTable.setFilter('enabled', true);
            } else if (status === 'disabled') {
                templatesTable.setFilter('enabled', false);
            } else {
                templatesTable.setFilter('enabled', '');
            }
        });
    }

    _onTabChange({ tabId }) {
        // Show/hide view toggle (only relevant for instances tab)
        const viewToggle = this.querySelector('#view-toggle-group-v2');
        if (viewToggle) {
            viewToggle.style.display = tabId === 'instances' ? '' : 'none';
        }

        if (tabId === 'instances') {
            this.actions.loadWorkers(this._selectedRegion);
        } else if (tabId === 'templates' && this._templateActions) {
            this._templateActions.loadTemplates();
        }
    }

    _handlePageAction(action) {
        switch (action) {
            case 'create': {
                const createModal = document.getElementById('createWorkerModal');
                if (createModal) {
                    import('bootstrap').then(bootstrap => {
                        new bootstrap.Modal(createModal).show();
                    });
                }
                break;
            }

            case 'create-template': {
                const createTemplateModal = document.getElementById('createWorkerTemplateModal');
                if (createTemplateModal) {
                    import('bootstrap').then(bootstrap => {
                        new bootstrap.Modal(createTemplateModal).show();
                    });
                }
                break;
            }

            case 'refresh':
                if (this._activeTab === 'instances') {
                    this.actions.loadWorkers(this._selectedRegion);
                } else if (this._templateActions) {
                    this._templateActions.loadTemplates();
                }
                break;
        }
    }

    // =========================================================================
    // Utility Helpers
    // =========================================================================

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
}

// Register custom element
if (!customElements.get('workers-page-v2')) {
    customElements.define('workers-page-v2', WorkersPageV2);
}

export default WorkersPageV2;
