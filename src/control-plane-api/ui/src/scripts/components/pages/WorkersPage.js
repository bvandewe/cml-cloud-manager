/**
 * WorkersPage - Page-level Component for Workers Management
 *
 * Provides a tabbed interface for Workers with sub-tabs:
 * - Instances: View and manage CML worker instances
 * - Templates: Manage worker launch templates (Admin only)
 *
 * Uses LcmTabView for sub-navigation and LcmDataTable for table views.
 *
 * @module components/pages/WorkersPage
 */

import { BaseComponent } from '../../core/BaseComponent.js';
import { eventBus, EventTypes } from '../../core/EventBus.js';
import * as workerTemplatesApi from '../../api/worker-templates.js';
import { showConfirmAsync } from '../modals.js';
import '../core/LcmTabView.js';
import '../core/LcmDataTable.js';
import '../core/LcmActionBar.js';
import '../core/LcmStatusBadge.js';
import '../core/LcmMetricCard.js';
import '../WorkerCard.js';
import '../WorkerList.js';
import '../WorkerDetailsModal.js';
import './LabDetailModal.js';

export class WorkersPage extends BaseComponent {
    static get observedAttributes() {
        return ['active-tab', 'view-mode'];
    }

    constructor() {
        super();
        this._currentUser = null;
        this._activeTab = 'instances';
        this._viewMode = null; // Will be set based on user role
        this._selectedRegion = null; // null = all regions (default)
        this._workersCache = []; // Cache loaded workers for view switching
        this._capacityCollapsed = true;
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
     * Initialize the page with user context
     * @param {Object} user - Current user object with roles
     */
    initialize(user) {
        console.log('[WorkersPage] initialize() called with user:', user?.preferred_username || user?.email || 'unknown');
        this._currentUser = user;
        // Set default view mode based on user role: table for admin, cards for non-admin
        this._viewMode = this._isAdminOrManager() ? 'table' : 'cards';
        console.log('[WorkersPage] isAdmin:', this._isAdminOrManager(), 'viewMode:', this._viewMode);
        this.render();
        this._setupEventListeners();
        this._configureDataTables();

        // Load initial data after DOM is ready
        requestAnimationFrame(() => {
            console.log('[WorkersPage] Loading initial data...');
            this._refreshInstances();
            if (this._isAdminOrManager()) {
                this._refreshTemplates();
            }
        });

        console.log('[WorkersPage] initialization complete');
    }

    onMount() {
        // Initial render with loading state
        this.innerHTML = this._renderLoading();
    }

    onAttributeChange(name, oldValue, newValue) {
        switch (name) {
            case 'active-tab':
                this._activeTab = newValue;
                this._updateTabContent();
                break;
            case 'view-mode':
                this._viewMode = newValue;
                this._updateViewMode();
                break;
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

    render() {
        const isAdmin = this._isAdminOrManager();

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
                    <lcm-action-bar id="workers-action-bar">
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
                    <lcm-tab-view id="workers-tabs" variant="underline" persist-key="workers-tab">
                        <lcm-tab id="instances" label="Instances" icon="bi-server" active></lcm-tab>
                        ${isAdmin ? `<lcm-tab id="templates" label="Templates" icon="bi-file-code"></lcm-tab>` : ''}
                    </lcm-tab-view>

                    <!-- View Toggle (right side) - only for Instances tab -->
                    <div class="btn-group btn-group-sm" role="group" aria-label="View mode" id="view-toggle-group">
                        <button type="button" class="btn btn-outline-secondary ${this._viewMode === 'cards' ? 'active' : ''}"
                                data-view="cards" title="Card view">
                            <i class="bi bi-grid-3x2-gap"></i>
                        </button>
                        <button type="button" class="btn btn-outline-secondary ${this._viewMode === 'table' ? 'active' : ''}"
                                data-view="table" title="Table view">
                            <i class="bi bi-list-ul"></i>
                        </button>
                    </div>
                </div>

                <!-- Tab Content -->
                <div class="tab-content mt-4">
                    <!-- Instances Tab -->
                    <div id="workers-instances-content" class="tab-pane active">
                        ${this._renderInstancesTab()}
                    </div>

                    <!-- Templates Tab (Admin only) -->
                    ${
                        isAdmin
                            ? `
                    <div id="workers-templates-content" class="tab-pane" style="display: none;">
                        ${this._renderTemplatesTab()}
                    </div>
                    `
                            : ''
                    }
                </div>

                <!-- Worker Details Modal (custom element subscribes to UI_OPEN_WORKER_DETAILS via EventBus) -->
                <worker-details-modal></worker-details-modal>

                <!-- Lab Detail Modal (for cross-links from worker Labs tab → lab record details) -->
                <lab-detail-modal id="lab-detail-modal"></lab-detail-modal>
            </div>
        `;

        // Register content with tab view
        this._registerTabContent();
    }

    _renderLoading() {
        return `
            <div class="d-flex justify-content-center align-items-center" style="min-height: 200px;">
                <div class="spinner-border text-primary" role="status">
                    <span class="visually-hidden">Loading...</span>
                </div>
            </div>
        `;
    }

    _renderInstancesTab() {
        const f = this._fleet;
        const cpuPct = f.totalCpuCores > 0 ? ((f.usedCpuCores / f.totalCpuCores) * 100).toFixed(1) : 0;
        const memPct = f.totalMemoryGb > 0 ? ((f.usedMemoryGb / f.totalMemoryGb) * 100).toFixed(1) : 0;
        const storagePct = f.totalStorageGb > 0 ? ((f.usedStorageGb / f.totalStorageGb) * 100).toFixed(1) : 0;
        const nodePct = f.totalMaxNodes > 0 ? ((f.usedNodes / f.totalMaxNodes) * 100).toFixed(1) : 0;

        return `
            <!-- Capacity Overview (Collapsible) -->
            <div class="mb-4">
                <button class="btn btn-sm btn-link text-decoration-none p-0 mb-2"
                    id="capacity-toggle" type="button">
                    <i class="bi bi-${this._capacityCollapsed ? 'chevron-right' : 'chevron-down'} me-1"></i>
                    Fleet Capacity
                    <span class="badge bg-primary ms-2">${f.runningWorkers} / ${f.totalWorkers} RUNNING</span>
                </button>
                <div id="capacity-panel-body" class="${this._capacityCollapsed ? 'd-none' : ''}">
                    <!-- Metric Tiles -->
                    <div class="row g-3 mb-4">
                        <div class="col-6 col-md-3">
                            <lcm-metric-card
                                title="Workers"
                                value="${f.runningWorkers} / ${f.totalWorkers}"
                                subtitle="running / total"
                                icon="bi-server"
                                color="primary">
                            </lcm-metric-card>
                        </div>
                        <div class="col-6 col-md-3">
                            <lcm-metric-card
                                title="Active Instances"
                                value="${f.totalInstances}"
                                icon="bi-collection"
                                color="info">
                            </lcm-metric-card>
                        </div>
                        <div class="col-6 col-md-3">
                            <lcm-metric-card
                                title="CPU Allocated"
                                value="${cpuPct}%"
                                subtitle="${f.usedCpuCores} / ${f.totalCpuCores} cores"
                                icon="bi-cpu"
                                color="${this._getUtilizationColor(cpuPct)}">
                            </lcm-metric-card>
                        </div>
                        <div class="col-6 col-md-3">
                            <lcm-metric-card
                                title="Memory Allocated"
                                value="${memPct}%"
                                subtitle="${f.usedMemoryGb} / ${f.totalMemoryGb} GB"
                                icon="bi-memory"
                                color="${this._getUtilizationColor(memPct)}">
                            </lcm-metric-card>
                        </div>
                    </div>

                    <!-- Resource Allocation Progress Bars -->
                    ${this._renderUtilizationBar('CPU Cores', f.usedCpuCores, f.totalCpuCores, 'cores')}
                    ${this._renderUtilizationBar('Memory', f.usedMemoryGb, f.totalMemoryGb, 'GB')}
                    ${this._renderUtilizationBar('Storage', f.usedStorageGb, f.totalStorageGb, 'GB')}
                    ${this._renderUtilizationBar('Nodes', f.usedNodes, f.totalMaxNodes, 'nodes')}
                </div>
            </div>

            <!-- Instances Content - Cards or Table -->
            <div id="worker-instances-container">
                ${this._viewMode === 'table' ? this._renderInstancesTable() : this._renderInstancesCards()}
            </div>
        `;
    }

    _renderInstancesCards() {
        return `
            <worker-list
                id="worker-instances-list"
                view="cards">
            </worker-list>
        `;
    }

    _renderInstancesTable() {
        return `
            <div class="card shadow-sm no-hover-lift">
                <div class="card-header d-flex align-items-center bg-white py-2 gap-2">
                    <span class="fw-medium text-muted small">Instances</span>
                    <div class="d-flex align-items-center gap-2 ms-auto">
                        <div class="input-group input-group-sm" style="width: 250px;">
                            <span class="input-group-text bg-white"><i class="bi bi-search"></i></span>
                            <input type="search" class="form-control" placeholder="Search instances..." id="worker-table-search">
                        </div>
                        <select class="form-select form-select-sm" id="worker-table-region-filter" style="width: 200px;">
                            <option value="">All Regions</option>
                            <option value="us-east-1">US East (N. Virginia)</option>
                            <option value="us-west-1">US West (N. California)</option>
                            <option value="us-west-2">US West (Oregon)</option>
                            <option value="eu-west-1">EU (Ireland)</option>
                            <option value="eu-central-1">EU (Frankfurt)</option>
                            <option value="ap-northeast-1">Asia Pacific (Tokyo)</option>
                            <option value="ap-southeast-1">Asia Pacific (Singapore)</option>
                        </select>
                        <select class="form-select form-select-sm" id="worker-table-status-filter" style="width: 160px;">
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
                    <lcm-data-table
                        id="worker-instances-table"
                        page-size="25"
                        selectable
                        panel-mode
                        empty-message="Select a region to view workers, or no workers found for the selected region.">
                    </lcm-data-table>
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
                            <input type="search" class="form-control" placeholder="Search templates..." id="template-table-search">
                        </div>
                        <select class="form-select form-select-sm" id="template-table-status-filter" style="width: 160px;">
                            <option value="">All Statuses</option>
                            <option value="enabled">Enabled</option>
                            <option value="disabled">Disabled</option>
                        </select>
                    </div>
                </div>
                <div class="card-body p-0">
                    <lcm-data-table
                        id="worker-templates-table"
                        page-size="25"
                        selectable
                        panel-mode
                        empty-message="Worker templates feature coming soon.">
                    </lcm-data-table>
                </div>
            </div>
        `;
    }

    _registerTabContent() {
        const tabView = this.querySelector('#workers-tabs');
        if (!tabView) return;

        const instancesContent = this.querySelector('#workers-instances-content');
        const templatesContent = this.querySelector('#workers-templates-content');

        if (instancesContent) {
            tabView.registerContent('instances', instancesContent);
        }
        if (templatesContent) {
            tabView.registerContent('templates', templatesContent);
        }
    }

    _setupEventListeners() {
        // Tab change handling
        const tabView = this.querySelector('#workers-tabs');
        if (tabView) {
            tabView.addEventListener('tab-change', e => {
                this._activeTab = e.detail.tabId;
                this._onTabChange(e.detail);
            });
        }

        // Action bar handling
        const actionBar = this.querySelector('#workers-action-bar');
        if (actionBar) {
            actionBar.addEventListener('click', e => {
                const action = e.target.closest('[data-action]')?.dataset.action;
                if (action) {
                    this._handleAction(action);
                }
            });
        }

        // View toggle
        this.querySelectorAll('[data-view]').forEach(btn => {
            btn.addEventListener('click', e => {
                const view = e.currentTarget.dataset.view;
                this._setViewMode(view);
            });
        });

        // Table region filter (instances)
        const tableRegionFilter = this.querySelector('#worker-table-region-filter');
        if (tableRegionFilter) {
            // Sync dropdown with default region
            tableRegionFilter.value = this._selectedRegion || '';
            tableRegionFilter.addEventListener('change', e => {
                this._filterByRegion(e.target.value);
            });
        }

        // Table status filter (instances)
        const tableStatusFilter = this.querySelector('#worker-table-status-filter');
        if (tableStatusFilter) {
            tableStatusFilter.addEventListener('change', e => {
                this._filterByStatus(e.target.value);
            });
        }

        // Table search (instances)
        const tableSearchInput = this.querySelector('#worker-table-search');
        if (tableSearchInput) {
            tableSearchInput.addEventListener(
                'input',
                this._debounce(e => {
                    this._searchInstances(e.target.value);
                }, 300)
            );
        }

        // Template region filter
        const templateRegionFilter = this.querySelector('#template-table-region-filter');
        if (templateRegionFilter) {
            templateRegionFilter.addEventListener('change', e => {
                this._filterTemplatesByRegion(e.target.value);
            });
        }

        // Template status filter
        const templateStatusFilter = this.querySelector('#template-table-status-filter');
        if (templateStatusFilter) {
            templateStatusFilter.addEventListener('change', e => {
                this._filterTemplatesByStatus(e.target.value);
            });
        }

        // Template search
        const templateSearchInput = this.querySelector('#template-table-search');
        if (templateSearchInput) {
            templateSearchInput.addEventListener(
                'input',
                this._debounce(e => {
                    this._searchTemplates(e.target.value);
                }, 300)
            );
        }

        // Capacity panel collapse tracking
        this._setupCapacityPanelListeners();
    }

    _configureDataTables() {
        // Configure instances table columns
        const instancesTable = this.querySelector('#worker-instances-table');
        if (instancesTable) {
            instancesTable.setColumns([
                { field: 'name', label: 'Name', sortable: true },
                { field: 'aws_region', label: 'Region', sortable: true },
                {
                    field: 'status',
                    label: 'Status',
                    sortable: true,
                    render: val => `<lcm-status-badge status="${val}"></lcm-status-badge>`,
                },
                { field: 'instance_type', label: 'Instance Type', sortable: true },
                {
                    field: 'cpu_utilization',
                    label: 'CPU %',
                    sortable: true,
                    render: val => (val != null ? `${parseFloat(val).toFixed(1)}%` : '<span class="text-muted">&mdash;</span>'),
                },
                {
                    field: 'memory_utilization',
                    label: 'Memory %',
                    sortable: true,
                    render: val => (val != null ? `${parseFloat(val).toFixed(1)}%` : '<span class="text-muted">&mdash;</span>'),
                },
                {
                    field: 'active_labs_count',
                    label: 'Labs',
                    sortable: true,
                    render: (val, row) => {
                        const count = val ?? row.cml_labs_count ?? 0;
                        return count > 0 ? `<span class="badge bg-info">${count}</span>` : `<span class="text-muted">0</span>`;
                    },
                },
                { field: 'created_at', label: 'Created', sortable: true, type: 'datetime' },
                {
                    field: 'actions',
                    label: 'Actions',
                    render: (_, row) => `
                        <div class="btn-group btn-group-sm">
                            <button class="btn btn-sm btn-outline-primary lcm-row-action p-1" data-action="view" data-row-id="${row.id}" title="View details">
                                <i class="bi bi-eye"></i>
                            </button>
                            <button class="btn btn-sm btn-outline-success lcm-row-action p-1" data-action="start" data-row-id="${row.id}" title="Start worker"
                                    ${row.status === 'running' ? 'disabled' : ''}>
                                <i class="bi bi-play"></i>
                            </button>
                            <button class="btn btn-sm btn-outline-warning lcm-row-action p-1" data-action="stop" data-row-id="${row.id}" title="Stop worker"
                                    ${row.status !== 'running' ? 'disabled' : ''}>
                                <i class="bi bi-stop"></i>
                            </button>
                            <button class="btn btn-sm btn-outline-danger lcm-row-action p-1" data-action="terminate" data-row-id="${row.id}" title="Terminate worker">
                                <i class="bi bi-trash"></i>
                            </button>
                        </div>
                    `,
                },
            ]);

            instancesTable.setBulkActions([
                { id: 'start', label: 'Start Selected', icon: 'bi-play', variant: 'success' },
                { id: 'stop', label: 'Stop Selected', icon: 'bi-stop', variant: 'warning' },
                { id: 'terminate', label: 'Terminate Selected', icon: 'bi-trash', variant: 'danger' },
            ]);

            // Enable row click to open worker details modal
            instancesTable.addEventListener('row-click', e => {
                const row = e.detail?.row;
                if (row) {
                    this._showWorkerDetails(row);
                }
            });

            // Handle action button clicks (view, start, stop, terminate)
            instancesTable.addEventListener('row-action', e => {
                const { action, row } = e.detail || {};
                if (!action || !row) return;
                this._handleWorkerAction(action, row);
            });
        }

        // Configure templates table columns
        const templatesTable = this.querySelector('#worker-templates-table');
        if (templatesTable) {
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

            // Enable row click to open details
            templatesTable.addEventListener('row-click', e => {
                const row = e.detail?.row;
                if (row) {
                    this._showTemplateDetails(row);
                }
            });

            // Handle template action button clicks
            templatesTable.addEventListener('row-action', e => {
                const { action, row } = e.detail || {};
                if (!action || !row) return;
                this._handleTemplateAction(action, row);
            });
        }
    }

    _onTabChange({ tabId, previousTabId }) {
        console.log(`[WorkersPage] Tab changed from ${previousTabId} to ${tabId}`);

        // Emit page-level event
        eventBus.emit('workers.tab.changed', { tabId, previousTabId });

        // Load data for the new tab if needed
        if (tabId === 'instances') {
            this._refreshInstances();
        } else if (tabId === 'templates') {
            this._refreshTemplates();
        }
    }

    _handleAction(action) {
        console.log(`[WorkersPage] Action triggered: ${action}`);

        switch (action) {
            case 'create':
                // Open create worker modal
                const createModal = document.getElementById('createWorkerModal');
                if (createModal) {
                    import('bootstrap').then(bootstrap => {
                        new bootstrap.Modal(createModal).show();
                    });
                }
                break;

            case 'create-template':
                // Open create template modal
                const createTemplateModal = document.getElementById('createWorkerTemplateModal');
                if (createTemplateModal) {
                    import('bootstrap').then(bootstrap => {
                        new bootstrap.Modal(createTemplateModal).show();
                    });
                }
                break;

            case 'refresh':
                if (this._activeTab === 'instances') {
                    this._refreshInstances();
                } else {
                    this._refreshTemplates();
                }
                break;
        }
    }

    _setViewMode(mode) {
        this._viewMode = mode;

        // Update button states
        this.querySelectorAll('[data-view]').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.view === mode);
        });

        // Re-render instances container
        const container = this.querySelector('#worker-instances-container');
        if (container) {
            container.innerHTML = mode === 'table' ? this._renderInstancesTable() : this._renderInstancesCards();

            // Configure table and restore cached data if switching to table view
            if (mode === 'table') {
                setTimeout(() => {
                    this._configureDataTables();
                    // Restore cached workers data to the table
                    if (this._workersCache.length > 0) {
                        const instancesTable = this.querySelector('#worker-instances-table');
                        if (instancesTable) {
                            instancesTable.setData(this._workersCache);
                        }
                    }
                }, 0);
            } else {
                // For cards view, pass data to the worker-list component
                const workerList = this.querySelector('#worker-instances-list');
                if (workerList && this._workersCache.length > 0) {
                    workerList.setWorkers?.(this._workersCache);
                }
            }
        }
    }

    _updateViewMode() {
        const workerList = this.querySelector('#worker-instances-list');
        if (workerList) {
            workerList.setAttribute('view', this._viewMode);
        }
    }

    _filterByRegion(region) {
        console.log('[WorkersPage] _filterByRegion:', region || 'all');
        this._selectedRegion = region || null;

        const workerList = this.querySelector('#worker-instances-list');
        const instancesTable = this.querySelector('#worker-instances-table');

        if (workerList) {
            workerList.setAttribute('filter-region', region || '');
        }

        // For the table, load data from the appropriate API endpoint
        if (instancesTable) {
            this._loadWorkers(region);
        }
    }

    /**
     * Load workers from API - either all regions or a specific region
     * @param {string|null} region - AWS region code or null/empty for all regions
     */
    async _loadWorkers(region) {
        const instancesTable = this.querySelector('#worker-instances-table');
        const workerList = this.querySelector('#worker-instances-list');

        console.log('[WorkersPage] Loading workers for:', region || 'all regions');

        try {
            if (instancesTable) instancesTable.setAttribute('loading', '');

            // Use /api/workers/ for all regions, /api/workers/region/{region}/workers for specific region
            const url = region ? `/api/workers/region/${region}/workers` : '/api/workers/';

            const response = await fetch(url, {
                credentials: 'include',
                headers: { Accept: 'application/json' },
            });

            if (!response.ok) {
                throw new Error(`Failed to load workers: ${response.status}`);
            }

            const data = await response.json();
            const workers = Array.isArray(data) ? data : data.items || data.data || [];
            console.log('[WorkersPage] Loaded workers:', workers.length);

            // Cache the workers for view switching
            this._workersCache = workers;

            // Compute fleet capacity from workers and update the panel
            this._computeFleetCapacity();
            this._updateCapacityPanel();

            // Update both table and cards views with the data
            const updatedTable = this.querySelector('#worker-instances-table');
            const updatedList = this.querySelector('#worker-instances-list');
            if (updatedTable) updatedTable.setData(workers);
            if (updatedList) updatedList.setWorkers?.(workers);

            // Load instance count for capacity tiles (async, non-blocking)
            this._loadInstanceCount();
        } catch (error) {
            console.error('[WorkersPage] Error loading workers:', error);
            this._workersCache = [];
            const table = this.querySelector('#worker-instances-table');
            const list = this.querySelector('#worker-instances-list');
            if (table) table.setData([]);
            if (list) list.setWorkers?.([]);
        } finally {
            const table = this.querySelector('#worker-instances-table');
            if (table) table.removeAttribute('loading');
        }
    }

    _filterByStatus(status) {
        const workerList = this.querySelector('#worker-instances-list');
        const instancesTable = this.querySelector('#worker-instances-table');

        if (workerList) {
            workerList.setAttribute('filter-status', status);
        }
        if (instancesTable) {
            instancesTable.setFilter('status', status);
        }
    }

    _searchInstances(term) {
        const workerList = this.querySelector('#worker-instances-list');
        const instancesTable = this.querySelector('#worker-instances-table');

        if (workerList) {
            workerList.setAttribute('search', term);
        }
        if (instancesTable) {
            instancesTable.setSearch(term);
        }
    }

    _filterTemplatesByRegion(region) {
        const templatesTable = this.querySelector('#worker-templates-table');
        if (templatesTable) {
            templatesTable.setFilter('region', region);
        }
    }

    _filterTemplatesByStatus(status) {
        const templatesTable = this.querySelector('#worker-templates-table');
        if (templatesTable) {
            // Map 'enabled'/'disabled' dropdown values to the boolean `enabled` field
            if (status === 'enabled') {
                templatesTable.setFilter('enabled', true);
            } else if (status === 'disabled') {
                templatesTable.setFilter('enabled', false);
            } else {
                templatesTable.setFilter('enabled', '');
            }
        }
    }

    _searchTemplates(term) {
        const templatesTable = this.querySelector('#worker-templates-table');
        if (templatesTable) {
            templatesTable.setSearch(term);
        }
    }

    _refreshInstances() {
        const workerList = this.querySelector('#worker-instances-list');

        if (workerList && typeof workerList.refresh === 'function') {
            workerList.refresh();
        }

        // For table view, reload workers (all regions or selected region)
        this._loadWorkers(this._selectedRegion);

        eventBus.emit(EventTypes.WORKERS_REFRESH_COMPLETED);
    }

    async _refreshTemplates() {
        const templatesTable = this.querySelector('#worker-templates-table');
        if (templatesTable) {
            try {
                console.log('[WorkersPage] Loading worker templates from API...');
                const templates = await workerTemplatesApi.listWorkerTemplates();
                console.log('[WorkersPage] Loaded templates:', templates);
                templatesTable.setData(templates);
            } catch (error) {
                console.error('[WorkersPage] Failed to load templates:', error);
                templatesTable.setData([]);
            }
        }

        eventBus.emit(EventTypes.WORKER_TEMPLATES_REFRESH_COMPLETED);
    }

    _showTemplateDetails(template) {
        console.log('[WorkersPage] Show template details:', template);
        this._openTemplateModal(template, 'view');
    }

    _showWorkerDetails(worker) {
        console.log('[WorkersPage] Show worker details:', worker);
        const region = worker.aws_region || worker.region || 'us-east-1';
        // Emit event to open worker details modal
        eventBus.emit('UI_OPEN_WORKER_DETAILS', {
            workerId: worker.id,
            region: region,
        });
    }

    /**
     * Handle worker table row action buttons (view, start, stop, terminate)
     */
    async _handleWorkerAction(action, worker) {
        console.log(`[WorkersPage] Worker action: ${action} on worker ${worker.id}`);
        const region = worker.aws_region || worker.region || 'us-east-1';

        switch (action) {
            case 'view':
                this._showWorkerDetails(worker);
                break;

            case 'start':
                try {
                    const { startWorker } = await import('../../api/workers.js');
                    const { showToast } = await import('../../ui/notifications.js');
                    await startWorker(region, worker.id);
                    showToast(`Starting worker "${worker.name}"...`, 'success');
                    this._refreshInstances();
                } catch (err) {
                    console.error('[WorkersPage] Failed to start worker:', err);
                    const { showToast } = await import('../../ui/notifications.js');
                    showToast(`Failed to start worker: ${err.message}`, 'danger');
                }
                break;

            case 'stop':
                try {
                    const { stopWorker } = await import('../../api/workers.js');
                    const { showToast } = await import('../../ui/notifications.js');
                    await stopWorker(region, worker.id);
                    showToast(`Stopping worker "${worker.name}"...`, 'success');
                    this._refreshInstances();
                } catch (err) {
                    console.error('[WorkersPage] Failed to stop worker:', err);
                    const { showToast } = await import('../../ui/notifications.js');
                    showToast(`Failed to stop worker: ${err.message}`, 'danger');
                }
                break;

            case 'terminate':
                if (!(await showConfirmAsync('Terminate Worker', `Are you sure you want to terminate worker "${worker.name}"? This cannot be undone.`, { actionLabel: 'Terminate', actionClass: 'btn-danger' }))) {
                    return;
                }
                try {
                    const { deleteWorker } = await import('../../api/workers.js');
                    const { showToast } = await import('../../ui/notifications.js');
                    await deleteWorker(region, worker.id, true);
                    showToast(`Worker "${worker.name}" terminated.`, 'warning');
                    this._refreshInstances();
                } catch (err) {
                    console.error('[WorkersPage] Failed to terminate worker:', err);
                    const { showToast } = await import('../../ui/notifications.js');
                    showToast(`Failed to terminate worker: ${err.message}`, 'danger');
                }
                break;

            default:
                console.warn(`[WorkersPage] Unknown worker action: ${action}`);
        }
    }

    /**
     * Handle template table row action buttons
     */
    async _handleTemplateAction(action, template) {
        console.log(`[WorkersPage] Template action: ${action} on template ${template.id}`);
        const { showToast } = await import('../../ui/notifications.js');

        switch (action) {
            case 'view-template':
                this._showTemplateDetails(template);
                break;

            case 'edit-template':
                this._openTemplateModal(template, 'edit');
                break;

            case 'deploy-template':
                this._deployFromTemplate(template);
                break;

            case 'enable-template':
                try {
                    await workerTemplatesApi.enableWorkerTemplate(template.id);
                    showToast(`Template "${template.name}" enabled.`, 'success');
                    this._refreshTemplates();
                } catch (err) {
                    console.error('[WorkersPage] Failed to enable template:', err);
                    showToast(`Failed to enable template: ${err.message}`, 'danger');
                }
                break;

            case 'disable-template':
                if (!(await showConfirmAsync('Disable Template', `Disable template "${template.name}"? It will no longer be available for worker provisioning.`, { actionLabel: 'Disable', actionClass: 'btn-warning' }))) {
                    return;
                }
                try {
                    await workerTemplatesApi.disableWorkerTemplate(template.id);
                    showToast(`Template "${template.name}" disabled.`, 'warning');
                    this._refreshTemplates();
                } catch (err) {
                    console.error('[WorkersPage] Failed to disable template:', err);
                    showToast(`Failed to disable template: ${err.message}`, 'danger');
                }
                break;

            case 'delete-template':
                if (!(await showConfirmAsync('Delete Template', `Are you sure you want to delete template "${template.name}"? This action cannot be undone.`, { actionLabel: 'Delete', actionClass: 'btn-danger' }))) {
                    return;
                }
                try {
                    await workerTemplatesApi.deleteWorkerTemplate(template.id);
                    showToast(`Template "${template.name}" deleted.`, 'warning');
                    this._refreshTemplates();
                } catch (err) {
                    console.error('[WorkersPage] Failed to delete template:', err);
                    showToast(`Failed to delete template: ${err.message}`, 'danger');
                }
                break;

            default:
                console.warn(`[WorkersPage] Unknown template action: ${action}`);
        }
    }

    /**
     * Deploy a worker from template — prepopulates the "New Worker" modal
     * with the template's configuration values.
     */
    _deployFromTemplate(template) {
        console.log('[WorkersPage] Deploy from template:', template.name);
        const createModal = document.getElementById('createWorkerModal');
        if (!createModal) {
            console.warn('[WorkersPage] createWorkerModal not found in DOM');
            return;
        }

        // Prepopulate form fields from template
        const nameInput = createModal.querySelector('[name="name"], #worker-name');
        const instanceTypeSelect = createModal.querySelector('[name="instance_type"], #worker-instance-type');
        const amiNameInput = createModal.querySelector('[name="ami_name"], #worker-ami-name');

        if (nameInput) nameInput.value = `${template.name}-worker`;
        if (instanceTypeSelect) instanceTypeSelect.value = template.instance_type || '';
        if (amiNameInput) amiNameInput.value = template.ami_name_pattern || '';

        // Open the modal
        import('bootstrap').then(bootstrap => {
            new bootstrap.Modal(createModal).show();
        });
    }

    /**
     * Open the Worker Template detail/edit modal.
     * @param {Object} template - Template data
     * @param {string} mode - 'view' or 'edit'
     */
    _openTemplateModal(template, mode = 'view') {
        const modalEl = document.getElementById('workerTemplateModal');
        if (!modalEl) {
            // Dynamically inject modal into DOM on first use
            this._injectTemplateModal();
        }
        const modal = document.getElementById('workerTemplateModal');
        if (!modal) return;

        const isEdit = mode === 'edit';
        const title = modal.querySelector('.modal-title');
        if (title) title.textContent = isEdit ? `Edit Template: ${template.name}` : `Template: ${template.name}`;

        // Populate fields
        this._populateTemplateModal(modal, template, isEdit);

        import('bootstrap').then(bootstrap => {
            new bootstrap.Modal(modal).show();
        });
    }

    /**
     * Inject the Worker Template modal HTML into the DOM (once).
     */
    _injectTemplateModal() {
        const html = `
        <div class="modal fade" id="workerTemplateModal" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Worker Template</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <form id="templateForm">
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
                        <button type="button" class="btn btn-primary" id="templateSaveBtn" style="display:none;">Save Changes</button>
                    </div>
                </div>
            </div>
        </div>
        `;
        document.body.insertAdjacentHTML('beforeend', html);

        // Wire up save button
        document.getElementById('templateSaveBtn')?.addEventListener('click', () => this._saveTemplate());
    }

    /**
     * Populate the template modal with data.
     */
    _populateTemplateModal(modal, template, isEdit) {
        const form = modal.querySelector('#templateForm');
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

        // Toggle editability
        form.querySelectorAll('input:not([name="name"]), textarea, select').forEach(el => {
            el.disabled = !isEdit;
        });

        // Show/hide save button
        const saveBtn = modal.querySelector('#templateSaveBtn');
        if (saveBtn) {
            saveBtn.style.display = isEdit ? '' : 'none';
            saveBtn.dataset.templateId = template.id;
        }
    }

    /**
     * Save template changes from the modal form.
     */
    async _saveTemplate() {
        const modal = document.getElementById('workerTemplateModal');
        if (!modal) return;

        const form = modal.querySelector('#templateForm');
        const templateId = modal.querySelector('#templateSaveBtn')?.dataset.templateId;
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
            await workerTemplatesApi.updateWorkerTemplate(templateId, updateData);
            const { showToast } = await import('../../ui/notifications.js');
            showToast('Template updated successfully.', 'success');

            // Close modal and refresh
            import('bootstrap').then(bootstrap => {
                bootstrap.Modal.getInstance(modal)?.hide();
            });
            this._refreshTemplates();
        } catch (err) {
            console.error('[WorkersPage] Failed to save template:', err);
            const { showToast } = await import('../../ui/notifications.js');
            showToast(`Failed to save template: ${err.message}`, 'danger');
        }
    }

    _updateTabContent() {
        const tabView = this.querySelector('#workers-tabs');
        if (tabView) {
            tabView.setActiveTab(this._activeTab);
        }
    }

    // ---- Capacity Panel Methods ----

    /**
     * Compute fleet capacity from cached workers data
     */
    _computeFleetCapacity() {
        let totalCpu = 0,
            usedCpu = 0,
            totalMem = 0,
            usedMem = 0;
        let totalStorage = 0,
            usedStorage = 0,
            totalNodes = 0,
            usedNodes = 0;
        let running = 0;

        this._workersCache.forEach(w => {
            if (w.declared_capacity) {
                totalCpu += w.declared_capacity.cpu_cores || 0;
                totalMem += w.declared_capacity.memory_gb || 0;
                totalStorage += w.declared_capacity.storage_gb || 0;
                totalNodes += w.declared_capacity.max_nodes || 0;
            }
            if (w.allocated_capacity) {
                usedCpu += w.allocated_capacity.cpu_cores || 0;
                usedMem += w.allocated_capacity.memory_gb || 0;
                usedStorage += w.allocated_capacity.storage_gb || 0;
                usedNodes += w.allocated_capacity.max_nodes || 0;
            }
            if ((w.status || '').toLowerCase() === 'running') running++;
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
            totalWorkers: this._workersCache.length,
            totalInstances: 0, // Updated async below
        };
    }

    /**
     * Load active lablet instance count for the fleet panel
     */
    async _loadInstanceCount() {
        try {
            const { listLabletSessions } = await import('../../api/lablet-sessions.js');
            const instances = await listLabletSessions({ include_terminated: false });
            this._fleet.totalInstances = instances.length;
            this._updateCapacityPanel();
        } catch (error) {
            console.warn('[WorkersPage] Failed to load instance count:', error);
        }
    }

    /**
     * Update the capacity panel without full re-render.
     * Always re-renders the instances tab content so fleet data stays
     * current regardless of whether the capacity panel is collapsed.
     */
    _updateCapacityPanel() {
        const instancesContent = this.querySelector('#workers-instances-content');
        if (instancesContent) {
            instancesContent.innerHTML = this._renderInstancesTab();
            this._setupCapacityPanelListeners();
            this._configureDataTables();
            // Restore cached data
            if (this._workersCache.length > 0 && this._viewMode === 'table') {
                const instancesTable = this.querySelector('#worker-instances-table');
                if (instancesTable) instancesTable.setData(this._workersCache);
            }
        }
    }

    _setupCapacityPanelListeners() {
        this.querySelector('#capacity-toggle')?.addEventListener('click', () => {
            this._capacityCollapsed = !this._capacityCollapsed;
            const panel = this.querySelector('#capacity-panel-body');
            const icon = this.querySelector('#capacity-toggle i');
            if (panel) panel.classList.toggle('d-none', this._capacityCollapsed);
            if (icon) {
                icon.className = `bi bi-${this._capacityCollapsed ? 'chevron-right' : 'chevron-down'} me-1`;
            }
        });
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

    _debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }
}

// Register custom element
if (!customElements.get('workers-page')) {
    customElements.define('workers-page', WorkersPage);
}

export default WorkersPage;
