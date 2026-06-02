/**
 * WorkerDetailsModal Component
 *
 * Full-featured modal with horizontal tabs: AWS, CML, Labs, Monitoring, Events
 * Handles license registration, lab operations, and worker details
 *
 * Usage:
 *   <worker-details-modal></worker-details-modal>
 *
 * Open via EventBus:
 *   EventBus.emit('UI_OPEN_WORKER_DETAILS', { workerId: 'abc123', region: 'us-east-1' });
 */

import { BaseComponent } from '../core/BaseComponent.js';
import eventBus, { EventTypes } from '../core/EventBus.js';
import * as bootstrap from 'bootstrap';
import { escapeHtml } from './escape.js';
import { renderWorkerOverview } from './workerOverview.js';
import { isAdmin, isAdminOrManager } from '../utils/roles.js';
import { formatDateWithRelative, initializeDateTooltips, parseUTCDate } from '../utils/dates.js';
import { showToast } from '../ui/notifications.js';
import { showConfirm } from './modals.js';
import { showDeleteModal, showLicenseModal } from '../ui/worker-modals.js';
import { renderLicenseRegistration, renderLicenseAuthorization, renderLicenseFeatures, renderLicenseTransport } from './workerLicensePanel.js';
import { renderMonitoringTab } from '../ui/worker-monitoring.js';

export class WorkerDetailsModal extends BaseComponent {
    constructor() {
        super();
        this.modalInstance = null;
        this.currentWorkerId = null;
        this.currentRegion = null;
        this.currentWorker = null;
        this.lastRefreshedAt = null;
        this.timerInterval = null;
        this.tabs = {
            aws: null,
            cml: null,
            labs: null,
            monitoring: null,
            events: null,
        };
    }

    onMount() {
        // Subscribe to open modal event
        this.subscribe('UI_OPEN_WORKER_DETAILS', ({ workerId, region }) => {
            this.openModal(workerId, region);
        });

        // Subscribe to worker updates
        this.subscribe(EventTypes.WORKER_SNAPSHOT, data => {
            const id = data.id || data.worker_id;
            console.log('[WorkerDetailsModal] WORKER_SNAPSHOT event received:', {
                event_id: id,
                current_id: this.currentWorkerId,
                has_data: !!data,
                data_keys: data ? Object.keys(data) : [],
            });
            if (id === this.currentWorkerId) {
                console.log('[WorkerDetailsModal] Received snapshot update for current worker');
                this.currentWorker = data;
                console.log('[WorkerDetailsModal] Updated currentWorker:', {
                    has_currentWorker: !!this.currentWorker,
                    id: this.currentWorker?.id,
                    name: this.currentWorker?.name,
                });
                this.refreshCurrentTab();
            }
        });

        this.subscribe(EventTypes.WORKER_DELETED, data => {
            const id = data.id || data.worker_id;
            if (id === this.currentWorkerId) {
                this.closeModal();
                showToast('Worker has been deleted', 'info');
            }
        });

        this.subscribe(EventTypes.WORKER_STATUS_CHANGED, data => {
            const id = data.id || data.worker_id;
            if (id === this.currentWorkerId) {
                console.log('[WorkerDetailsModal] Received status update for current worker');
                this.currentWorker = {
                    ...this.currentWorker,
                    status: data.new_status,
                    updated_at: data.updated_at,
                };
                this.refreshCurrentTab();
            }
        });

        this.subscribe(EventTypes.WORKER_METRICS_UPDATED, data => {
            const id = data.id || data.worker_id;
            if (id === this.currentWorkerId) {
                console.log('[WorkerDetailsModal] Received metrics update for current worker');
                this.currentWorker = {
                    ...this.currentWorker,
                    cpu_utilization: data.cpu_utilization,
                    memory_utilization: data.memory_utilization,
                    disk_utilization: data.disk_utilization,
                    cloudwatch_cpu_utilization: data.cloudwatch_cpu_utilization,
                    cloudwatch_memory_utilization: data.cloudwatch_memory_utilization,
                    cloudwatch_storage_utilization: data.cloudwatch_storage_utilization,
                    cloudwatch_last_collected_at: data.cloudwatch_last_collected_at,
                    updated_at: data.updated_at || new Date().toISOString(),
                };
                this.refreshCurrentTab();
            }
        });

        this.subscribe(EventTypes.WORKER_IDLE_DETECTION_TOGGLED, data => {
            const id = data.id || data.worker_id;
            if (id === this.currentWorkerId) {
                console.log('[WorkerDetailsModal] Received idle detection toggle for current worker');
                this.currentWorker = {
                    ...this.currentWorker,
                    is_idle_detection_enabled: data.is_enabled,
                    updated_at: data.toggled_at || new Date().toISOString(),
                };
                this.refreshCurrentTab();
            }
        });

        // Lab Record events — refresh Labs tab when lab status changes or actions complete
        this.subscribe(EventTypes.LAB_RECORD_STATUS_UPDATED, data => {
            if (this.currentWorkerId && this.tabs.labs !== null) {
                this.loadLabsTab();
            }
        });

        this.subscribe(EventTypes.LAB_RECORD_ACTION_QUEUED, data => {
            if (this.currentWorkerId && this.tabs.labs !== null) {
                this.loadLabsTab();
            }
        });

        this.subscribe(EventTypes.LAB_RECORD_ACTION_COMPLETED, data => {
            if (this.currentWorkerId && this.tabs.labs !== null) {
                this.loadLabsTab();
            }
        });

        this.subscribe(EventTypes.LAB_RECORD_ACTION_FAILED, data => {
            if (this.currentWorkerId && this.tabs.labs !== null) {
                this.loadLabsTab();
            }
        });

        this.render();
    }

    render() {
        this.innerHTML = `
            <div class="modal fade" id="workerDetailsModalV2" tabindex="-1">
                <div class="modal-dialog modal-xl">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">
                                <i class="bi bi-info-circle"></i> Worker Details
                            </h5>
                            <div class="d-flex align-items-center gap-3 ms-auto">
                                <small class="text-muted" id="metrics-last-refreshed">
                                    <i class="bi bi-clock-history"></i> <span class="last-refreshed-time">--</span>
                                </small>
                                <small class="text-muted" id="metrics-refresh-timer">
                                    <i class="bi bi-arrow-clockwise"></i> <span id="metrics-countdown">--:--</span>
                                </small>
                                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                            </div>
                        </div>
                        <div class="modal-body">
                            <!-- Navigation Tabs -->
                            <ul class="nav nav-tabs mb-3" id="workerDetailsTabs" role="tablist">
                                <li class="nav-item" role="presentation">
                                    <button class="nav-link active" id="aws-tab-btn" data-tab="aws" type="button">
                                        <i class="bi bi-hdd-stack"></i> Runtime
                                    </button>
                                </li>
                                <li class="nav-item" role="presentation">
                                    <button class="nav-link" id="cml-tab-btn" data-tab="cml" type="button">
                                        <i class="bi bi-diagram-3"></i> CML
                                    </button>
                                </li>
                                <li class="nav-item" role="presentation">
                                    <button class="nav-link" id="labs-tab-btn" data-tab="labs" type="button">
                                        <i class="bi bi-folder2-open"></i> Labs
                                    </button>
                                </li>
                                <li class="nav-item admin-manager-only-tab" role="presentation" style="display: none;">
                                    <button class="nav-link" id="monitoring-tab-btn" data-tab="monitoring" type="button">
                                        <i class="bi bi-activity"></i> Monitoring
                                    </button>
                                </li>
                                <li class="nav-item admin-only-tab" role="presentation" style="display: none;">
                                    <button class="nav-link" id="events-tab-btn" data-tab="events" type="button">
                                        <i class="bi bi-bell"></i> Events
                                    </button>
                                </li>
                            </ul>

                            <!-- Tab Content -->
                            <div class="tab-content" id="workerDetailsTabContent">
                                <!-- AWS Tab -->
                                <div class="tab-pane fade show active" id="aws-panel" role="tabpanel">
                                    <div id="worker-details-aws">
                                        <div class="text-center py-5">
                                            <div class="spinner-border" role="status"></div>
                                            <p class="mt-3 text-muted">Loading worker details...</p>
                                        </div>
                                    </div>
                                </div>

                                <!-- CML Tab -->
                                <div class="tab-pane fade" id="cml-panel" role="tabpanel">
                                    <div id="worker-details-cml">
                                        <div class="text-center py-5 text-muted">
                                            <i class="bi bi-diagram-3 fs-1 d-block mb-3"></i>
                                            <p>CML application details will appear here</p>
                                        </div>
                                    </div>
                                </div>

                                <!-- Labs Tab -->
                                <div class="tab-pane fade" id="labs-panel" role="tabpanel">
                                    <div id="worker-details-labs">
                                        <div class="text-center py-5 text-muted">
                                            <i class="bi bi-folder2-open fs-1 d-block mb-3"></i>
                                            <p>Lab details will appear here</p>
                                        </div>
                                    </div>
                                </div>

                                <!-- Monitoring Tab -->
                                <div class="tab-pane fade" id="monitoring-panel" role="tabpanel">
                                    <div id="worker-details-monitoring">
                                        <div class="text-center py-5 text-muted">
                                            <i class="bi bi-activity fs-1 d-block mb-3"></i>
                                            <p>Worker monitoring status will appear here</p>
                                        </div>
                                    </div>
                                </div>

                                <!-- Events Tab -->
                                <div class="tab-pane fade" id="events-panel" role="tabpanel">
                                    <div id="worker-details-events">
                                        <div class="text-center py-5 text-muted">
                                            <i class="bi bi-bell fs-1 d-block mb-3"></i>
                                            <p>Events will appear here</p>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <div class="me-auto d-flex gap-2">
                                <button type="button" class="btn btn-danger admin-only" id="delete-worker-from-details-btn"
                                    style="display: none;" title="Delete Worker">
                                    <i class="bi bi-trash"></i> Delete Worker
                                </button>
                                <button type="button" class="btn btn-warning admin-only" id="stop-worker-btn"
                                    style="display: none;" title="Stop Worker">
                                    <i class="bi bi-stop-fill"></i> Stop Worker
                                </button>
                                <button type="button" class="btn btn-success admin-only" id="start-worker-btn"
                                    style="display: none;" title="Start Worker">
                                    <i class="bi bi-play-fill"></i> Start Worker
                                </button>
                                <input type="file" id="lab-upload-input" accept=".yaml,.yml" style="display: none;">
                                <button type="button" class="btn btn-primary" id="upload-lab-btn" style="display: none;">
                                    <i class="bi bi-upload"></i> Import Lab
                                </button>
                            </div>
                            <button type="button" class="btn btn-primary" id="refresh-worker-details">
                                <i class="bi bi-arrow-clockwise"></i> Refresh
                            </button>
                            <button type="button" class="btn btn-outline-warning" id="sync-worker-state-btn"
                                title="Force full state reconciliation (EC2 + CML re-read, status alignment, lab recovery)">
                                <i class="bi bi-arrow-repeat"></i> Sync
                            </button>
                            <button type="button" class="btn btn-outline-info" id="discover-labs-btn"
                                style="display: none;" title="Trigger targeted lab discovery for this worker">
                                <i class="bi bi-search"></i> Discover Labs
                            </button>
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        this.setupEventListeners();
    }

    setupEventListeners() {
        const modalEl = this.$('#workerDetailsModalV2');
        if (!modalEl) return;

        // Initialize Bootstrap modal
        this.modalInstance = new bootstrap.Modal(modalEl);

        // Tab click handlers
        this.$$('[data-tab]').forEach(btn => {
            btn.addEventListener('click', e => {
                e.preventDefault();
                const tab = btn.dataset.tab;
                this.switchTab(tab);
            });
        });

        // Refresh button
        const refreshBtn = this.$('#refresh-worker-details');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => this.refreshWorkerData());
        }

        // Sync button (AD-043)
        const syncBtn = this.$('#sync-worker-state-btn');
        if (syncBtn) {
            syncBtn.addEventListener('click', () => this.handleSyncWorker());
        }

        // Discover Labs button
        const discoverLabsBtn = this.$('#discover-labs-btn');
        if (discoverLabsBtn) {
            discoverLabsBtn.addEventListener('click', () => this.handleDiscoverLabs());
        }

        // Delete button
        const deleteBtn = this.$('#delete-worker-from-details-btn');
        if (deleteBtn) {
            deleteBtn.addEventListener('click', () => this.handleDeleteWorker());
        }

        // Start button
        const startBtn = this.$('#start-worker-btn');
        if (startBtn) {
            startBtn.addEventListener('click', () => this.handleStartWorker());
        }

        // Stop button
        const stopBtn = this.$('#stop-worker-btn');
        if (stopBtn) {
            stopBtn.addEventListener('click', () => this.handleStopWorker());
        }

        // Import Lab button
        const uploadBtn = this.$('#upload-lab-btn');
        const uploadInput = this.$('#lab-upload-input');
        if (uploadBtn && uploadInput) {
            uploadBtn.addEventListener('click', () => uploadInput.click());
            uploadInput.addEventListener('change', e => this.handleLabFileSelected(e));
        }

        // Modal lifecycle events
        modalEl.addEventListener('hidden.bs.modal', () => {
            this.currentWorkerId = null;
            this.currentRegion = null;
            this.currentWorker = null;
            this.stopTimer();
        });
    }

    async openModal(workerId, region) {
        console.log('[WorkerDetailsModal] Opening for worker:', workerId, region);

        this.currentWorkerId = workerId;
        this.currentRegion = region;

        // Show modal
        if (this.modalInstance) {
            this.modalInstance.show();
        }

        // Apply RBAC visibility
        this.applyRBAC();

        // Load worker data first, then switch to AWS tab
        await this.loadWorkerData();
        this.switchTab('aws');
    }

    closeModal() {
        if (this.modalInstance) {
            this.modalInstance.hide();
        }
    }

    applyRBAC() {
        const modalEl = this.$('#workerDetailsModalV2');
        if (!modalEl) return;

        const adminTabs = modalEl.querySelectorAll('.admin-only-tab');
        const adminManagerTabs = modalEl.querySelectorAll('.admin-manager-only-tab');
        const adminButtons = modalEl.querySelectorAll('.admin-only');

        if (isAdmin()) {
            adminTabs.forEach(t => (t.style.display = 'block'));
            adminManagerTabs.forEach(t => (t.style.display = 'block'));
            adminButtons.forEach(b => (b.style.display = ''));
        } else if (isAdminOrManager()) {
            adminManagerTabs.forEach(t => (t.style.display = 'block'));
            adminTabs.forEach(t => (t.style.display = 'none'));
            adminButtons.forEach(b => (b.style.display = 'none'));
        } else {
            adminTabs.forEach(t => (t.style.display = 'none'));
            adminManagerTabs.forEach(t => (t.style.display = 'none'));
            adminButtons.forEach(b => (b.style.display = 'none'));
        }
    }

    switchTab(tabName) {
        // Update tab buttons
        this.$$('[data-tab]').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.tab === tabName);
        });

        // Update tab panels
        this.$('#aws-panel')?.classList.toggle('show', tabName === 'aws');
        this.$('#aws-panel')?.classList.toggle('active', tabName === 'aws');
        this.$('#cml-panel')?.classList.toggle('show', tabName === 'cml');
        this.$('#cml-panel')?.classList.toggle('active', tabName === 'cml');
        this.$('#labs-panel')?.classList.toggle('show', tabName === 'labs');
        this.$('#labs-panel')?.classList.toggle('active', tabName === 'labs');
        this.$('#monitoring-panel')?.classList.toggle('show', tabName === 'monitoring');
        this.$('#monitoring-panel')?.classList.toggle('active', tabName === 'monitoring');
        this.$('#events-panel')?.classList.toggle('show', tabName === 'events');
        this.$('#events-panel')?.classList.toggle('active', tabName === 'events');

        // Load tab content
        this.loadTabContent(tabName);
        this.updateFooterButtons();
    }

    async loadWorkerData() {
        if (!this.currentWorkerId || !this.currentRegion) return;

        const maxRetries = 3;
        let attempt = 0;

        while (attempt < maxRetries) {
            try {
                const { getWorkerDetails } = await import('../api/workers.js');
                this.currentWorker = await getWorkerDetails(this.currentRegion, this.currentWorkerId);
                this.refreshCurrentTab();
                return; // Success, exit
            } catch (error) {
                attempt++;
                console.error(`[WorkerDetailsModal] Failed to load worker (attempt ${attempt}/${maxRetries}):`, error);

                if (attempt >= maxRetries) {
                    showToast(`Failed to load worker after ${maxRetries} attempts: ${error.message}`, 'error');
                } else {
                    // Wait before retry (exponential backoff)
                    await new Promise(resolve => setTimeout(resolve, 500 * attempt));
                }
            }
        }
    }

    async refreshWorkerData() {
        await this.loadWorkerData();
        showToast('Worker data refreshed', 'success');
    }

    async handleSyncWorker() {
        const btn = this.$('#sync-worker-state-btn');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="bi bi-hourglass-split"></i> Syncing...';
        }
        try {
            const { requestWorkerSync } = await import('../api/workers.js');
            await requestWorkerSync(this.currentRegion, this.currentWorkerId);
            showToast('Sync requested — worker state will be reconciled shortly', 'success');
            // Refresh data after a brief delay to reflect reconciled state
            setTimeout(() => this.loadWorkerData(), 3000);
        } catch (error) {
            showToast(`Failed to request sync: ${error.message}`, 'error');
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="bi bi-arrow-repeat"></i> Sync';
            }
        }
    }

    async handleDiscoverLabs() {
        const btn = this.$('#discover-labs-btn');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="bi bi-hourglass-split"></i> Discovering...';
        }
        try {
            const { triggerLabDiscovery } = await import('../api/workers.js');
            await triggerLabDiscovery(this.currentRegion, this.currentWorkerId);
            showToast('Lab discovery triggered — labs will appear shortly', 'success');
            // Refresh labs tab after a brief delay to allow discovery to complete
            setTimeout(() => this.loadLabsTab(), 3000);
        } catch (error) {
            showToast(`Failed to trigger discovery: ${error.message}`, 'error');
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="bi bi-search"></i> Discover Labs';
            }
        }
    }

    refreshCurrentTab() {
        this.updateModalHeader();
        this.updateFooterButtons();
        const activeTab = this.$('[data-tab].active');
        if (activeTab) {
            this.loadTabContent(activeTab.dataset.tab);
        }
    }

    updateFooterButtons() {
        if (!this.currentWorker) return;
        const w = this.currentWorker;
        const isAdminUser = isAdmin();
        const activeTab = this.$('[data-tab].active')?.dataset.tab;

        const startBtn = this.$('#start-worker-btn');
        const stopBtn = this.$('#stop-worker-btn');
        const deleteBtn = this.$('#delete-worker-from-details-btn');
        const importLabBtn = this.$('#upload-lab-btn');
        const discoverLabsBtn = this.$('#discover-labs-btn');

        if (startBtn) startBtn.style.display = isAdminUser && w.status === 'stopped' ? '' : 'none';
        if (stopBtn) stopBtn.style.display = isAdminUser && w.status === 'running' ? '' : 'none';
        if (deleteBtn) deleteBtn.style.display = isAdminUser ? '' : 'none';

        // Show import button only on Labs tab
        if (importLabBtn) importLabBtn.style.display = activeTab === 'labs' ? '' : 'none';

        // Show discover labs button only when worker is running
        if (discoverLabsBtn) discoverLabsBtn.style.display = w.status === 'running' ? '' : 'none';
    }

    updateModalHeader() {
        const titleEl = this.$('.modal-title');
        if (titleEl && this.currentWorker) {
            const httpsEndpoint = this.currentWorker.https_endpoint;
            const awsNameTag = this.currentWorker.aws_tags?.Name;
            const displayName = escapeHtml(awsNameTag || this.currentWorker.name || 'Unknown Worker');

            if (httpsEndpoint) {
                titleEl.innerHTML = `<i class="bi bi-info-circle"></i> Worker: <a href="${httpsEndpoint}" target="_blank" class="text-decoration-none text-reset" title="Open Worker in new tab">${displayName} <i class="bi bi-box-arrow-up-right small ms-1" style="font-size: 0.7em;"></i></a>`;
            } else {
                titleEl.innerHTML = `<i class="bi bi-info-circle"></i> Worker: ${displayName}`;
            }
        }
    }

    async loadTabContent(tabName) {
        switch (tabName) {
            case 'aws':
                await this.loadAWSTab();
                break;
            case 'cml':
                await this.loadCMLTab();
                break;
            case 'labs':
                await this.loadLabsTab();
                break;
            case 'monitoring':
                await this.loadMonitoringTab();
                break;
            case 'events':
                await this.loadEventsTab();
                break;
        }
    }

    async loadAWSTab() {
        const container = this.$('#worker-details-aws');
        if (!container || !this.currentWorker) return;

        try {
            container.innerHTML = renderWorkerOverview(this.currentWorker);
            // Initialize tooltips for timestamp icons
            setTimeout(() => initializeDateTooltips(), 100);
        } catch (error) {
            console.error('[WorkerDetailsModal] Failed to render AWS tab:', error);
            container.innerHTML = `<div class="alert alert-danger">Failed to load AWS details: ${escapeHtml(error.message)}</div>`;
        }
    }

    async loadCMLTab() {
        const container = this.$('#worker-details-cml');
        if (!container || !this.currentWorker) return;

        const w = this.currentWorker;
        const sysInfo = w.cml_system_info || w.system_info || {};
        const sysStats = w.system_stats || {};
        // Handle both API field names (cml_*) and potential legacy/mapped names
        const license = w.cml_license_info || w.license_info || {};
        const health = w.cml_system_health || w.system_health || {};
        const hasLicense = w.license_status === 'registered' || license.registration_status === 'COMPLETED';

        // Extract stats for Resource Utilization
        const computesInfo = sysInfo.computes || {};
        let stats = {};
        const computeKeys = Object.keys(computesInfo);
        if (computeKeys.length > 0) {
            const firstKey = computeKeys[0];
            stats = computesInfo[firstKey].stats || {};
        }

        // Helper to format bytes
        const formatBytes = bytes => {
            if (bytes === undefined || bytes === null) return 'N/A';
            const b = parseFloat(bytes);
            if (isNaN(b)) return 'N/A';
            if (b === 0) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
            const i = Math.floor(Math.log(b) / Math.log(k));
            return parseFloat((b / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
        };

        // Use top-level utilization from API response (calculated by backend)
        const cpuVal = w.cpu_utilization ?? 0;
        const memVal = w.memory_utilization ?? 0;
        const diskVal = w.disk_utilization ?? w.storage_utilization ?? 0;

        // Extract details from sysInfo (preferred) or fallback to compute stats
        const cpuCores = sysInfo.cpu_count ?? stats.cpu?.count ?? 'N/A';
        const cpuLoad = stats.cpu?.load ? stats.cpu.load.map(v => parseFloat(v).toFixed(1) + '%').join(', ') : 'N/A';

        const memTotal = sysInfo.memory_total ?? stats.memory?.total;
        const memFree = sysInfo.memory_free ?? stats.memory?.free;

        const diskTotal = sysInfo.disk_total ?? stats.disk?.total;
        const diskFree = sysInfo.disk_free ?? stats.disk?.free;

        // Compute nodes are in system health, with utilization from system info
        const computesDict = health.computes || {};
        // Convert dict to array, merging health data with per-node stats from system_info
        const compute = Object.entries(computesDict).map(([key, val]) => {
            // Get per-node utilization from system_info.computes (stats data)
            const nodeStats = computesInfo[key]?.stats || {};
            const cpuPct = nodeStats.cpu?.percent ?? 0;
            const memPct = nodeStats.memory?.total && nodeStats.memory?.used ? ((nodeStats.memory.used / nodeStats.memory.total) * 100).toFixed(0) : 0;
            const diskPct = nodeStats.disk?.total && nodeStats.disk?.used ? ((nodeStats.disk.used / nodeStats.disk.total) * 100).toFixed(0) : 0;
            return {
                name: val.hostname || key,
                valid: val.valid,
                // Map CML health fields to display field names
                is_registered: val.lld_connected ?? false,
                is_connected: val.lld_synced ?? false,
                is_ready: val.admission_state === 'READY',
                cpu_usage: typeof cpuPct === 'number' ? cpuPct.toFixed(0) : cpuPct,
                memory_usage: memPct,
                disk_usage: diskPct,
            };
        });

        // Helper for badges
        const renderBadge = (condition, trueText = 'Yes', falseText = 'No') => {
            return `<span class="badge bg-${condition ? 'success' : 'danger'}"><i class="bi bi-${condition ? 'check-circle' : 'x-circle'}"></i> ${condition ? trueText : falseText}</span>`;
        };

        const renderCheck = condition => {
            return `<span class="text-${condition ? 'success' : 'danger'}"><i class="bi bi-${condition ? 'check-circle-fill' : 'x-circle-fill'}"></i> ${condition ? 'Yes' : 'No'}</span>`;
        };

        // Extract node counts
        let runningNodes = 0;
        let totalNodes = 0;

        if (sysInfo) {
            if (sysInfo.running_nodes !== undefined && sysInfo.running_nodes !== null && sysInfo.total_nodes !== undefined && sysInfo.total_nodes !== null) {
                runningNodes = sysInfo.running_nodes;
                totalNodes = sysInfo.total_nodes;
            } else if (sysInfo.computes) {
                const computes = sysInfo.computes;
                for (const key in computes) {
                    const domInfo = computes[key]?.stats?.dominfo;
                    if (domInfo) {
                        runningNodes += domInfo.running_nodes || 0;
                        totalNodes += domInfo.total_nodes || 0;
                    }
                }
            }
        }
        const nodesDisplay = totalNodes > 0 ? `<strong>${runningNodes}</strong> / ${totalNodes}` : '—';

        // Helper for progress bars with details
        const renderProgressWithDetails = (val, label, details = []) => {
            const v = parseFloat(val) || 0;
            const vRounded = Math.round(v);
            let color = 'success';
            if (v > 70) color = 'warning';
            if (v > 90) color = 'danger';

            const detailsHtml = details
                .map(
                    d => `
                <div class="d-flex justify-content-between small text-muted mt-1">
                    <span>${d.label}</span>
                    <span class="fw-bold">${d.value}</span>
                </div>
            `
                )
                .join('');

            return `
                <div class="col-md-4">
                    <div class="mb-2">
                        <div class="d-flex justify-content-between small mb-1">
                            <span class="fw-bold"><i class="bi bi-${label === 'CPU' ? 'cpu' : label === 'Memory' ? 'memory' : 'hdd'}"></i> ${label}</span>
                            <span class="fw-bold">${vRounded}%</span>
                        </div>
                        <div class="progress" style="height: 8px;">
                            <div class="progress-bar bg-${color}" role="progressbar" style="width: ${v}%" aria-valuenow="${v}" aria-valuemin="0" aria-valuemax="100"></div>
                        </div>
                        <div class="mt-2 border-top pt-2">
                            ${detailsHtml}
                        </div>
                    </div>
                </div>
            `;
        };

        try {
            container.innerHTML = `
            <div class="row g-3">
                <!-- System Information -->
                <div class="col-md-4">
                    <div class="card h-100">
                        <div class="card-header bg-light">
                            <h6 class="mb-0"><i class="bi bi-info-circle"></i> System Information</h6>
                        </div>
                        <div class="card-body">
                            <table class="table table-sm table-borderless mb-0">
                                <tr><td class="text-muted">Version:</td><td><strong>${escapeHtml(w.cml_version || 'N/A')}</strong></td></tr>
                                <tr><td class="text-muted">Ready State:</td><td>${renderBadge(w.cml_ready, 'READY', 'NOT READY')}</td></tr>
                                <tr><td class="text-muted">Uptime:</td><td>${sysStats.uptime || 'Unknown'}</td></tr>
                                <tr><td class="text-muted">Active Nodes: <i class="bi bi-info-circle text-muted" data-bs-toggle="tooltip" title="Count excludes external connector nodes"></i></td><td>${nodesDisplay}</td></tr>
                                <tr><td class="text-muted">Last Synced:</td><td>${w.cml_last_synced_at ? formatDateWithRelative(w.cml_last_synced_at) : 'N/A'} <i class="bi bi-info-circle text-muted" title="Last time data was synced from CML"></i></td></tr>
                            </table>
                        </div>
                    </div>
                </div>

                <!-- License & Edition -->
                <div class="col-md-4">
                    <div class="card h-100">
                        <div class="card-header bg-light d-flex justify-content-between align-items-center">
                            <h6 class="mb-0"><i class="bi bi-key"></i> License & Edition</h6>
                            <div class="btn-group btn-group-sm">
                                <button class="btn btn-outline-primary py-0" id="btn-license-details">Details</button>
                                ${isAdminOrManager() ? `<button class="btn btn-outline-success py-0" id="btn-register-license" ${hasLicense ? 'style="display:none"' : ''}>Register</button>` : ''}
                                ${isAdminOrManager() ? `<button class="btn btn-outline-danger py-0" id="btn-deregister-license" ${!hasLicense ? 'style="display:none"' : ''}>Deregister</button>` : ''}
                            </div>
                        </div>
                        <div class="card-body">
                            <table class="table table-sm table-borderless mb-0">
                                <tr><td class="text-muted">Licensed:</td><td>${renderBadge(w.license_status === 'registered' || w.cml_license_info?.registration_status === 'COMPLETED', 'YES', 'NO')}</td></tr>
                                <tr><td class="text-muted">Edition:</td><td><span class="badge bg-primary">${escapeHtml(license.product_license?.active || license.product || (license.is_enterprise ? 'CML_Enterprise' : 'UNKNOWN'))}</span></td></tr>
                                <tr><td class="text-muted">Smart Account:</td><td><strong>${escapeHtml(license.smart_account || license.registration?.smart_account || 'N/A')}</strong></td></tr>
                                <tr><td class="text-muted">Virtual Account:</td><td><strong>${escapeHtml(license.virtual_account || license.registration?.virtual_account || 'N/A')}</strong></td></tr>
                                <tr><td class="text-muted">Reg. Expires:</td><td>${license.expires || license.registration?.expires || 'N/A'}</td></tr>
                                <tr><td class="text-muted">Auth Status:</td><td>${license.authorization_status || license.authorization?.status || 'N/A'}</td></tr>
                            </table>
                        </div>
                    </div>
                </div>

                <!-- System Health -->
                <div class="col-md-4">
                    <div class="card h-100">
                        <div class="card-header bg-light">
                            <h6 class="mb-0"><i class="bi bi-heart-pulse"></i> System Health</h6>
                        </div>
                        <div class="card-body">
                             <table class="table table-sm table-borderless mb-0">
                                <tr><td class="text-muted">Overall Status:</td><td>${renderBadge(health.valid !== false, 'VALID', 'INVALID')}</td></tr>
                                <tr><td class="text-muted">Service Status:</td><td><span class="badge bg-${w.service_status === 'available' ? 'success' : 'warning'}">${w.service_status}</span></td></tr>
                                <tr><td class="text-muted">HTTPS Endpoint:</td><td>${(() => {
                                    const endpoint = w.https_endpoint;
                                    const fallbackUrl = w.public_ip ? `https://${w.public_ip}` : null;
                                    const displayUrl = endpoint || fallbackUrl;
                                    if (displayUrl) {
                                        const label = endpoint ? escapeHtml(endpoint) : `${escapeHtml(fallbackUrl)} <span class="badge bg-warning text-dark ms-1" style="font-size: 0.7em;">via Public IP</span>`;
                                        return `<a href="${escapeHtml(displayUrl)}" target="_blank" class="text-decoration-none">${label}</a>`;
                                    }
                                    return 'N/A';
                                })()}</td></tr>
                            </table>
                        </div>
                    </div>
                </div>

                <!-- Resource Utilization -->
                <div class="col-md-12">
                    <div class="card">
                        <div class="card-header bg-light d-flex justify-content-between align-items-center">
                            <h6 class="mb-0"><i class="bi bi-speedometer2"></i> Resource Utilization</h6>
                            ${w.cml_last_synced_at ? `<small class="text-muted"><i class="bi bi-clock-history"></i> Synced: ${formatDateWithRelative(w.cml_last_synced_at)}</small>` : ''}
                        </div>
                        <div class="card-body">
                            <div class="row">
                                ${renderProgressWithDetails(cpuVal, 'CPU', [
                                    { label: 'Cores', value: cpuCores },
                                    { label: 'Load <i class="bi bi-info-circle text-muted" data-bs-toggle="tooltip" title="Load Avg: 1 min, 5 min, 15 min"></i>', value: cpuLoad },
                                ])}
                                ${renderProgressWithDetails(memVal, 'Memory', [
                                    { label: 'Total', value: formatBytes(memTotal) },
                                    { label: 'Free', value: formatBytes(memFree) },
                                ])}
                                ${renderProgressWithDetails(diskVal, 'Disk', [
                                    { label: 'Total', value: formatBytes(diskTotal) },
                                    { label: 'Free', value: formatBytes(diskFree) },
                                ])}
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Controller Status -->
                <div class="col-md-12">
                    <div class="card">
                        <div class="card-header bg-light">
                            <h6 class="mb-0"><i class="bi bi-cpu"></i> Controller Status</h6>
                        </div>
                        <div class="card-body">
                            <div class="row">
                                <div class="col-md-3">
                                    <div class="d-flex justify-content-between">
                                        <span class="text-muted">Status:</span>
                                        ${renderBadge(health.controller?.valid !== false, 'VALID', 'INVALID')}
                                    </div>
                                </div>
                                <div class="col-md-3">
                                    <div class="d-flex justify-content-between">
                                        <span class="text-muted">Core Connected:</span>
                                        ${renderCheck(health.controller?.core_connected)}
                                    </div>
                                </div>
                                <div class="col-md-3">
                                    <div class="d-flex justify-content-between">
                                        <span class="text-muted">Nodes Loaded:</span>
                                        ${renderCheck(health.controller?.nodes_loaded)}
                                    </div>
                                </div>
                                <div class="col-md-3">
                                    <div class="d-flex justify-content-between">
                                        <span class="text-muted">Images Loaded:</span>
                                        ${renderCheck(health.controller?.images_loaded)}
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Compute Nodes -->
                <div class="col-md-12">
                    <div class="card">
                        <div class="card-header bg-light">
                            <h6 class="mb-0"><i class="bi bi-server"></i> Compute Nodes</h6>
                        </div>
                        <div class="card-body">
                            ${
                                compute.length > 0
                                    ? `
                                <div class="table-responsive">
                                    <table class="table table-sm table-hover align-middle mb-0">
                                        <thead>
                                            <tr>
                                                <th>Node</th>
                                                <th>Status</th>
                                                <th>Registered</th>
                                                <th>Connected</th>
                                                <th>Ready</th>
                                                <th>CPU</th>
                                                <th>Memory</th>
                                                <th>Disk</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            ${compute
                                                .map(
                                                    c => `
                                                <tr>
                                                    <td><strong>${escapeHtml(c.name)}</strong></td>
                                                    <td>${renderBadge(c.valid !== false, 'VALID', 'INVALID')}</td>
                                                    <td>${renderCheck(c.is_registered)}</td>
                                                    <td>${renderCheck(c.is_connected)}</td>
                                                    <td>${renderCheck(c.is_ready)}</td>
                                                    <td>${c.cpu_usage || 0}%</td>
                                                    <td>${c.memory_usage || 0}%</td>
                                                    <td>${c.disk_usage || 0}%</td>
                                                </tr>
                                            `
                                                )
                                                .join('')}
                                        </tbody>
                                    </table>
                                </div>
                            `
                                    : '<div class="alert alert-info mb-0">No compute nodes found.</div>'
                            }
                        </div>
                    </div>
                </div>
            </div>
            `;

            // Attach event listeners
            this.$('#btn-license-details')?.addEventListener('click', () => this.openLicenseDetailsModal());

            this.$('#btn-register-license')?.addEventListener('click', () => {
                showLicenseModal(this.currentWorkerId, this.currentRegion, this.currentWorker.name, hasLicense);
            });

            this.$('#btn-deregister-license')?.addEventListener('click', () => {
                showLicenseModal(this.currentWorkerId, this.currentRegion, this.currentWorker.name, hasLicense);
            });

            // Initialize tooltips
            const tooltipTriggerList = container.querySelectorAll('[data-bs-toggle="tooltip"]');
            [...tooltipTriggerList].map(tooltipTriggerEl => new bootstrap.Tooltip(tooltipTriggerEl));
        } catch (error) {
            console.error('[WorkerDetailsModal] Failed to render CML tab:', error);
            container.innerHTML = `<div class="alert alert-danger">Failed to load CML details: ${escapeHtml(error.message)}</div>`;
        }
    }

    async loadLicenseTab() {
        const container = this.$('#worker-details-license');
        if (!container || !this.currentWorker) return;

        const w = this.currentWorker;
        // Handle both API field names (cml_*) and potential legacy/mapped names
        const license = w.cml_license_info || w.license_info || {};
        const hasLicense = w.license_status === 'registered' || license.registration_status === 'COMPLETED';

        try {
            container.innerHTML = `
                <div class="row g-3">
                    <div class="col-12 d-flex justify-content-end mb-2">
                        <button class="btn btn-primary me-2" id="btn-register-license" ${hasLicense ? 'style="display:none"' : ''}>
                            <i class="bi bi-key"></i> Register License
                        </button>
                        <button class="btn btn-outline-danger" id="btn-deregister-license" ${!hasLicense ? 'style="display:none"' : ''}>
                            <i class="bi bi-x-circle"></i> Deregister License
                        </button>
                    </div>

                    <!-- Registration -->
                    <div class="col-md-6">
                        <h6 class="border-bottom pb-2 mb-3">Registration</h6>
                        ${renderLicenseRegistration(license.registration || {})}
                    </div>

                    <!-- Authorization -->
                    <div class="col-md-6">
                        <h6 class="border-bottom pb-2 mb-3">Authorization</h6>
                        ${renderLicenseAuthorization(license.authorization || {})}
                    </div>

                    <!-- Features -->
                    <div class="col-12">
                        <h6 class="border-bottom pb-2 mb-3">Features</h6>
                        ${renderLicenseFeatures(license.features || [])}
                    </div>

                    <!-- Transport -->
                    <div class="col-12">
                        <h6 class="border-bottom pb-2 mb-3">Transport & UDI</h6>
                        ${renderLicenseTransport(license.transport || {}, license.udi || {})}
                    </div>
                </div>
            `;

            // Attach event listeners
            this.$('#btn-register-license')?.addEventListener('click', () => {
                showLicenseModal(this.currentWorkerId, this.currentRegion, this.currentWorker.name, hasLicense);
            });

            this.$('#btn-deregister-license')?.addEventListener('click', () => {
                // We can reuse showLicenseModal which handles deregister button visibility,
                // or directly trigger the deregister confirmation if we want to be specific.
                // The legacy showLicenseModal opens the register modal which has a deregister button.
                // But here we have a direct deregister button.
                // Let's use the showLicenseModal for consistency as it sets up the form.
                showLicenseModal(this.currentWorkerId, this.currentRegion, this.currentWorker.name, hasLicense);
            });
        } catch (error) {
            console.error('[WorkerDetailsModal] Failed to render License tab:', error);
            container.innerHTML = `<div class="alert alert-danger">Failed to load License details: ${escapeHtml(error.message)}</div>`;
        }
    }

    async loadLabsTab() {
        const container = this.$('#worker-details-labs');
        if (!container) return;

        try {
            const { listLabRecords, getLabRecordBindings } = await import('../api/lab-records.js');
            const labs = await listLabRecords({ worker_id: this.currentWorkerId });

            if (!labs || labs.length === 0) {
                container.innerHTML = `
                    <div class="text-center py-5 text-muted">
                        <i class="bi bi-folder2-open fs-1 d-block mb-3"></i>
                        <p>No labs found on this worker</p>
                    </div>
                `;
                this.updateLabsTabBadge([]);
                this.bindLabsTabActions();
                return;
            }

            // Fetch bindings for each LabRecord
            let bindingsMap = {}; // lab_record_id → { lab_record_id, bindings[] }
            try {
                const bindingPromises = labs.map(lab =>
                    getLabRecordBindings(lab.id)
                        .then(result => {
                            bindingsMap[lab.id] = {
                                lab_record_id: lab.id,
                                status: lab.status,
                                bindings: result.bindings || [],
                            };
                        })
                        .catch(err => {
                            console.warn(`[WorkerDetailsModal] Failed to fetch bindings for lab record ${lab.id}:`, err);
                            bindingsMap[lab.id] = { lab_record_id: lab.id, status: lab.status, bindings: [] };
                        })
                );
                await Promise.all(bindingPromises);
            } catch (bindingError) {
                console.warn('[WorkerDetailsModal] Failed to fetch lab record bindings (non-fatal):', bindingError);
            }

            container.innerHTML = `
                <div class="accordion" id="labsAccordion">
                    ${labs
                        .map((lab, index) => {
                            const id = `lab-${index}`;
                            // Prefer lab.status (authoritative LabRecordStatus enum) over lab.state (raw CML string)
                            const state = lab.status || lab.state || 'unknown';
                            const isRunning = ['started', 'booted', 'queued', 'starting', 'paused'].includes(state.toLowerCase());
                            const isStopped = ['stopped', 'wiped', 'defined', 'defined_on_core', 'imported', 'discovered'].includes(state.toLowerCase());
                            const isClean = lab.is_clean === true;
                            const isAvailable = isClean && isStopped && !lab.active_lablet_session_id;
                            const bindingInfo = bindingsMap[lab.id];
                            const pendingAction = lab.pending_action;

                            return `
                            <div class="accordion-item">
                                <h2 class="accordion-header" id="heading-${id}">
                                    <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#collapse-${id}" aria-expanded="false" aria-controls="collapse-${id}">
                                        <div class="d-flex align-items-center w-100 me-3">
                                            <span class="fw-bold me-3">${escapeHtml(lab.title)}</span>
                                            <span class="badge ${this.getLabStateBadgeClass(state)} me-auto">${state}</span>
                                            ${isAvailable ? '<span class="badge bg-success bg-opacity-25 text-success me-2" title="Clean lab — ready for assignment"><i class="bi bi-check-circle-fill"></i> Available</span>' : ''}
                                            ${!isClean && isStopped ? '<span class="badge bg-secondary bg-opacity-25 text-secondary me-2" title="Previously used — requires wipe before reassignment"><i class="bi bi-recycle"></i> Used</span>' : ''}
                                            ${pendingAction ? `<span class="badge bg-warning text-dark me-2" title="Pending action: ${pendingAction}"><i class="bi bi-hourglass-split"></i> ${pendingAction}</span>` : ''}
                                            ${bindingInfo && bindingInfo.bindings.length > 0 ? `<span class="badge bg-info me-2" title="Bound to ${bindingInfo.bindings.length} lablet instance(s)"><i class="bi bi-link-45deg"></i> ${bindingInfo.bindings.length}</span>` : ''}
                                            <span class="small text-muted me-3"><i class="bi bi-pc-display"></i> ${lab.node_count || 0} Nodes</span>
                                            <span class="small text-muted"><i class="bi bi-link"></i> ${lab.link_count || 0} Links</span>
                                        </div>
                                    </button>
                                </h2>
                                <div id="collapse-${id}" class="accordion-collapse collapse" aria-labelledby="heading-${id}" data-bs-parent="#labsAccordion">
                                    <div class="accordion-body">
                                        <div class="row g-3">
                                            <div class="col-md-6">
                                                <h6 class="border-bottom pb-2">Lab Information</h6>
                                                <table class="table table-sm table-borderless mb-3">
                                                    <tr><td class="text-muted" width="30%">Lab ID:</td><td><code>${lab.lab_id || lab.id}</code></td></tr>
                                                    <tr><td class="text-muted">Owner:</td><td>${escapeHtml(lab.owner_username || 'Unknown')}</td></tr>
                                                    <tr><td class="text-muted">Created:</td><td>${formatDateWithRelative(lab.created)}</td></tr>
                                                </table>
                                            </div>
                                            <div class="col-md-6">
                                                <h6 class="border-bottom pb-2">Actions</h6>
                                                <div class="d-flex gap-2 flex-wrap">
                                                    <button class="btn btn-sm btn-success lab-action" data-action="start" data-lab-id="${lab.id}" ${isRunning || pendingAction ? 'disabled' : ''}><i class="bi bi-play-fill"></i> Start</button>
                                                    <button class="btn btn-sm btn-warning lab-action" data-action="stop" data-lab-id="${lab.id}" ${!isRunning || pendingAction ? 'disabled' : ''}><i class="bi bi-stop-fill"></i> Stop</button>
                                                    <button class="btn btn-sm btn-danger lab-action" data-action="wipe" data-lab-id="${lab.id}" ${pendingAction ? 'disabled' : ''}><i class="bi bi-eraser"></i> Wipe</button>
                                                    <button class="btn btn-sm btn-outline-primary lab-action" data-action="export" data-lab-id="${lab.id}"><i class="bi bi-download"></i> Export</button>
                                                    <button class="btn btn-sm btn-outline-danger lab-action" data-action="delete" data-lab-id="${lab.id}" ${pendingAction ? 'disabled' : ''}><i class="bi bi-trash"></i> Delete</button>
                                                </div>
                                            </div>
                                            ${this.renderLabBindings(bindingInfo)}
                                            <div class="col-12">
                                                <h6 class="border-bottom pb-2">Description</h6>
                                                <div class="bg-light p-2 rounded small">${escapeHtml(lab.description || 'No description')}</div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        `;
                        })
                        .join('')}
                </div>
            `;

            this.bindLabsTabActions();
            // Initialize tooltips for timestamp icons
            setTimeout(() => initializeDateTooltips(), 100);

            // Update Labs tab badge with running/total count
            this.updateLabsTabBadge(labs);
        } catch (error) {
            console.error('[WorkerDetailsModal] Failed to load labs:', error);
            container.innerHTML = `<div class="alert alert-danger">Failed to load labs: ${escapeHtml(error.message)}</div>`;
        }
    }

    /**
     * Update the Labs tab button with a badge showing running/total count.
     * @param {Array} labs - Array of lab records
     */
    updateLabsTabBadge(labs) {
        const tabBtn = this.$('#labs-tab-btn');
        if (!tabBtn) return;

        const total = labs.length;
        const running = labs.filter(lab => {
            const state = (lab.status || lab.state || '').toLowerCase();
            return ['started', 'booted', 'queued', 'starting', 'paused'].includes(state);
        }).length;

        if (total === 0) {
            tabBtn.innerHTML = `<i class="bi bi-folder2-open"></i> Labs`;
        } else {
            const badgeClass = running > 0 ? 'bg-success' : 'bg-secondary';
            tabBtn.innerHTML = `<i class="bi bi-folder2-open"></i> Labs <span class="badge ${badgeClass} ms-1">${running}/${total}</span>`;
        }
    }

    /**
     * Render the Lablet Bindings section for a lab (Phase 11: P11-22).
     * Shows which LabletInstances are currently bound to this lab via LabletLabBinding.
     * @param {Object|undefined} bindingInfo - { lab_record_id, status, bindings[] }
     * @returns {string} HTML for the bindings section
     */
    renderLabBindings(bindingInfo) {
        if (!bindingInfo) {
            return `
                <div class="col-12">
                    <h6 class="border-bottom pb-2"><i class="bi bi-link-45deg me-1"></i>Lablet Bindings</h6>
                    <div class="text-muted small"><i class="bi bi-info-circle me-1"></i>No LabRecord tracked for this lab</div>
                </div>
            `;
        }

        const { bindings, lab_record_id, status } = bindingInfo;
        const activeBindings = bindings.filter(b => b.is_active);
        const releasedBindings = bindings.filter(b => !b.is_active);

        if (bindings.length === 0) {
            const shortRecordId = lab_record_id ? lab_record_id.split('-')[0] : '—';
            return `
                <div class="col-12">
                    <h6 class="border-bottom pb-2"><i class="bi bi-link-45deg me-1"></i>Lablet Bindings</h6>
                    <div class="d-flex align-items-center justify-content-between">
                        <span class="text-muted small">No active lablet bindings</span>
                        <span class="badge bg-secondary-subtle text-secondary-emphasis small">
                            Record: <a href="#" class="open-lab-record-link text-decoration-none" data-lab-record-id="${escapeHtml(lab_record_id)}" title="Open Lab Record ${escapeHtml(lab_record_id)}">
                                <code class="small">${escapeHtml(shortRecordId)}</code> <i class="bi bi-box-arrow-up-right" style="font-size: 0.7em;"></i>
                            </a>
                        </span>
                    </div>
                </div>
            `;
        }

        const renderBinding = binding => {
            const isActive = binding.is_active;
            const statusClass = isActive ? 'bg-success' : 'bg-secondary';
            const statusLabel = isActive ? 'Active' : 'Released';
            const roleClass = binding.role === 'primary' ? 'bg-primary-subtle text-primary-emphasis' : 'bg-secondary-subtle text-secondary-emphasis';
            const sessionId = binding.lablet_instance_id || binding.lablet_session_id || '';
            const displayLabel = binding.definition_name ? `${escapeHtml(binding.definition_name)}` : escapeHtml(sessionId);

            return `
                <div class="d-flex align-items-center justify-content-between py-1 ${isActive ? '' : 'opacity-50'}">
                    <div class="d-flex align-items-center gap-2">
                        <span class="badge ${statusClass} badge-sm">${statusLabel}</span>
                        <span class="badge ${roleClass}">${escapeHtml(binding.role || 'primary')}</span>
                        <a href="#" class="text-decoration-none xref-session" data-session-id="${escapeHtml(sessionId)}" title="${escapeHtml(sessionId)}">
                            <i class="bi bi-grid-3x3-gap me-1"></i>${displayLabel} <i class="bi bi-box-arrow-up-right small"></i>
                        </a>
                    </div>
                    <small class="text-muted">
                        ${binding.bound_at ? formatDateWithRelative(binding.bound_at) : ''}
                        ${binding.released_at ? ` → ${formatDateWithRelative(binding.released_at)}` : ''}
                    </small>
                </div>
            `;
        };

        return `
            <div class="col-12">
                <h6 class="border-bottom pb-2">
                    <i class="bi bi-link-45deg me-1"></i>Lablet Bindings
                    <span class="badge bg-info ms-2">${activeBindings.length} active</span>
                    ${releasedBindings.length > 0 ? `<span class="badge bg-secondary ms-1">${releasedBindings.length} released</span>` : ''}
                </h6>
                <div class="list-group list-group-flush small">
                    ${activeBindings.map(renderBinding).join('')}
                    ${
                        releasedBindings.length > 0
                            ? `
                        <details class="mt-1">
                            <summary class="text-muted small cursor-pointer">Show ${releasedBindings.length} released binding(s)</summary>
                            ${releasedBindings.map(renderBinding).join('')}
                        </details>
                    `
                            : ''
                    }
                </div>
                <div class="mt-1">
                    <span class="badge bg-secondary-subtle text-secondary-emphasis small">
                        Record: <a href="#" class="open-lab-record-link text-decoration-none" data-lab-record-id="${escapeHtml(lab_record_id)}" title="Open Lab Record ${escapeHtml(lab_record_id)}">
                            <code class="small">${escapeHtml(lab_record_id ? lab_record_id.split('-')[0] : '—')}</code> <i class="bi bi-box-arrow-up-right" style="font-size: 0.7em;"></i>
                        </a>
                    </span>
                </div>
            </div>
        `;
    }

    getLabStateBadgeClass(state) {
        switch (state?.toLowerCase()) {
            case 'booted':
            case 'started': // Legacy CML raw state
                return 'bg-success';
            case 'starting':
            case 'queued':
            case 'stopping':
            case 'wiping':
            case 'importing':
            case 'deleting':
                return 'bg-warning text-dark';
            case 'stopped':
                return 'bg-secondary';
            case 'defined':
            case 'defined_on_core':
            case 'wiped':
            case 'discovered':
                return 'bg-info';
            case 'paused':
                return 'bg-info text-dark';
            case 'error':
            case 'orphaned':
                return 'bg-danger';
            case 'deleted':
            case 'archived':
                return 'bg-dark';
            default:
                return 'bg-warning text-dark';
        }
    }

    bindLabsTabActions() {
        this.$$('.lab-action').forEach(btn => {
            btn.addEventListener('click', async e => {
                const action = btn.dataset.action;
                const labId = btn.dataset.labId;
                await this.handleLabAction(action, labId);
            });
        });

        // Cross-link: open LabDetailModal when clicking a Record badge
        this.$$('.open-lab-record-link').forEach(link => {
            link.addEventListener('click', e => {
                e.preventDefault();
                const labRecordId = link.dataset.labRecordId;
                if (!labRecordId) return;
                // Close worker modal first, then open lab record modal
                this.closeModal();
                setTimeout(() => {
                    const labModal = document.querySelector('lab-detail-modal');
                    if (labModal) {
                        labModal.open(labRecordId);
                    } else {
                        console.warn('[WorkerDetailsModal] lab-detail-modal element not found in DOM');
                        showToast('Lab detail modal not available on this page', 'warning');
                    }
                }, 300);
            });
        });

        // Cross-link: open SessionDetailsModal when clicking a session link
        this.$$('.xref-session').forEach(link => {
            link.addEventListener('click', e => {
                e.preventDefault();
                const sessionId = link.dataset.sessionId;
                if (!sessionId) return;
                this.closeModal();
                setTimeout(() => {
                    eventBus.emit('UI_OPEN_SESSION_DETAILS', { sessionId });
                }, 300);
            });
        });
    }

    async handleLabFileSelected(event) {
        const file = event.target.files[0];
        if (!file) return;

        try {
            const { importLabRecord } = await import('../api/lab-records.js');

            await importLabRecord(this.currentWorkerId, file);
            showToast('Lab imported successfully', 'success');
            this.loadLabsTab(); // Refresh labs list
        } catch (error) {
            console.error('[WorkerDetailsModal] Failed to import lab:', error);
            showToast(`Failed to import lab: ${error.message}`, 'error');
        }
    }

    async handleLabAction(action, labRecordId) {
        try {
            const { startLabRecord, stopLabRecord, wipeLabRecord, deleteLabRecord, exportLabRecord } = await import('../api/lab-records.js');

            switch (action) {
                case 'start':
                    await startLabRecord(labRecordId);
                    showToast('Lab start queued', 'success');
                    break;
                case 'stop':
                    await stopLabRecord(labRecordId);
                    showToast('Lab stop queued', 'success');
                    break;
                case 'wipe': {
                    const confirmWipe = await showConfirm('Wipe Lab', 'This will reset the lab to initial state. Continue?', () => {});
                    if (confirmWipe) {
                        await wipeLabRecord(labRecordId);
                        showToast('Lab wipe queued', 'success');
                    }
                    break;
                }
                case 'delete': {
                    const confirmDelete = await showConfirm('Delete Lab', 'This will permanently delete the lab. Continue?', () => {});
                    if (confirmDelete) {
                        await deleteLabRecord(labRecordId);
                        showToast('Lab delete queued', 'success');
                    }
                    break;
                }
                case 'export': {
                    const labData = await exportLabRecord(labRecordId);
                    const blob = new Blob([labData], { type: 'application/x-yaml' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `lab-${labRecordId}.yaml`;
                    a.click();
                    URL.revokeObjectURL(url);
                    showToast('Lab exported', 'success');
                    break;
                }
            }

            // Refresh labs list after action
            if (action !== 'export') {
                this.loadLabsTab();
            }
        } catch (error) {
            console.error(`[WorkerDetailsModal] Failed to ${action} lab:`, error);
            showToast(`Failed to ${action} lab: ${error.message}`, 'error');
        }
    }

    async loadMonitoringTab() {
        const container = this.$('#worker-details-monitoring');
        if (!container) return;

        console.log('[WorkerDetailsModal] loadMonitoringTab called:', {
            has_currentWorker: !!this.currentWorker,
            currentWorkerId: this.currentWorkerId,
            worker_data: this.currentWorker
                ? {
                      id: this.currentWorker.id,
                      name: this.currentWorker.name,
                      is_idle_detection_enabled: this.currentWorker.is_idle_detection_enabled,
                  }
                : null,
        });

        if (!this.currentWorker) {
            container.innerHTML = `
                <div class="alert alert-warning">
                    <i class="bi bi-exclamation-triangle"></i> Worker data not available
                </div>
            `;
            return;
        }

        // Call the monitoring tab renderer directly (imported at top of file)
        try {
            renderMonitoringTab(this.currentWorker);
        } catch (error) {
            console.error('[WorkerDetailsModal] Failed to load monitoring tab:', error);
            container.innerHTML = `
                <div class="alert alert-danger">
                    Failed to load monitoring tab: ${escapeHtml(error.message)}
                </div>
            `;
        }
    }

    async loadEventsTab() {
        const container = this.$('#worker-details-events');
        if (!container) return;

        container.innerHTML = `
            <div class="text-center py-5 text-muted">
                <i class="bi bi-bell fs-1 d-block mb-3"></i>
                <p>Events tab - Coming soon</p>
            </div>
        `;
    }

    async handleStartWorker() {
        // Use showConfirm with a callback, NOT as a promise that returns boolean
        showConfirm(
            'Start Worker',
            `Start worker ${this.currentWorker?.name || this.currentWorkerId}?`,
            async () => {
                try {
                    const { startWorker } = await import('../api/workers.js');
                    const { upsertWorkerSnapshot } = await import('../store/workerStore.js');

                    // Optimistic update
                    try {
                        upsertWorkerSnapshot({
                            id: this.currentWorkerId,
                            status: 'pending',
                            start_initiated_at: new Date().toISOString(),
                        });
                    } catch (e) {
                        console.warn('[WorkerDetailsModal] Optimistic update failed', e);
                    }

                    await startWorker(this.currentRegion, this.currentWorkerId);
                    showToast('Worker start initiated', 'success');
                } catch (error) {
                    console.error('[WorkerDetailsModal] Failed to start worker:', error);
                    showToast(`Failed to start worker: ${error.message}`, 'error');
                    // Revert optimistic update if needed (refresh)
                    if (window.workersApp && typeof window.workersApp.refreshWorkers === 'function') {
                        window.workersApp.refreshWorkers();
                    }
                }
            },
            {
                actionLabel: 'Start Worker',
                actionClass: 'btn-success',
                iconClass: 'bi bi-play-fill text-success me-2',
            }
        );
    }

    async handleStopWorker() {
        // Use showConfirm with a callback, NOT as a promise that returns boolean
        showConfirm(
            'Stop Worker',
            `Stop worker ${this.currentWorker?.name || this.currentWorkerId}?`,
            async () => {
                try {
                    const { stopWorker } = await import('../api/workers.js');
                    const { upsertWorkerSnapshot } = await import('../store/workerStore.js');

                    // Optimistic update
                    try {
                        upsertWorkerSnapshot({
                            id: this.currentWorkerId,
                            status: 'stopping',
                            stop_initiated_at: new Date().toISOString(),
                        });
                    } catch (e) {
                        console.warn('[WorkerDetailsModal] Optimistic update failed', e);
                    }

                    await stopWorker(this.currentRegion, this.currentWorkerId);
                    showToast('Worker stop initiated', 'success');
                } catch (error) {
                    console.error('[WorkerDetailsModal] Failed to stop worker:', error);
                    showToast(`Failed to stop worker: ${error.message}`, 'error');
                    // Revert optimistic update if needed (refresh)
                    if (window.workersApp && typeof window.workersApp.refreshWorkers === 'function') {
                        window.workersApp.refreshWorkers();
                    }
                }
            },
            {
                actionLabel: 'Stop Worker',
                actionClass: 'btn-warning',
                iconClass: 'bi bi-stop-fill text-warning me-2',
            }
        );
    }

    async handleDeleteWorker() {
        // Use the shared delete modal which supports optional EC2 termination
        showDeleteModal(this.currentWorkerId, this.currentRegion, this.currentWorker?.name || this.currentWorkerId);

        // Close details modal so the delete modal is visible
        this.closeModal();
    }

    async handleDeregisterLicense() {
        const confirmed = await showConfirm('Deregister License', `Remove license from worker ${this.currentWorker?.name || this.currentWorkerId}?`, () => {});

        if (confirmed) {
            try {
                const { deregisterLicense } = await import('../api/workers.js');
                await deregisterLicense(this.currentRegion, this.currentWorkerId);
                showToast('License deregistration initiated', 'success');
                this.loadCMLTab(); // Refresh CML tab
            } catch (error) {
                console.error('[WorkerDetailsModal] Failed to deregister license:', error);
                showToast(`Failed to deregister license: ${error.message}`, 'error');
            }
        }
    }

    openLicenseDetailsModal() {
        if (!this.currentWorker) return;

        const licenseData = this.currentWorker.cml_license_info;
        if (!licenseData) {
            showToast('No license information available', 'warning');
            return;
        }

        const licenseModalElement = document.getElementById('licenseDetailsModal');
        if (!licenseModalElement) {
            showToast('License modal missing', 'error');
            return;
        }

        const registrationContent = document.getElementById('license-registration-content');
        const authorizationContent = document.getElementById('license-authorization-content');
        const featuresContent = document.getElementById('license-features-content');
        const transportContent = document.getElementById('license-transport-content');

        if (!registrationContent || !authorizationContent || !featuresContent || !transportContent) {
            showToast('License modal content missing', 'error');
            return;
        }

        registrationContent.innerHTML = renderLicenseRegistration(licenseData.registration || {});
        authorizationContent.innerHTML = renderLicenseAuthorization(licenseData.authorization || {});
        featuresContent.innerHTML = renderLicenseFeatures(licenseData.features || []);
        transportContent.innerHTML = renderLicenseTransport(licenseData.transport || {}, licenseData.udi || {});

        // Ensure z-index is higher than worker details modal
        licenseModalElement.style.zIndex = '1060'; // Bootstrap default is 1055 for modal

        const modal = new bootstrap.Modal(licenseModalElement);
        modal.show();
    }

    getActiveTab() {
        const activeBtn = this.querySelector('.nav-link.active');
        return activeBtn ? activeBtn.dataset.tab : 'aws';
    }

    updateRefreshTimer(updatedAt) {
        if (!updatedAt) return;

        try {
            this.lastRefreshedAt = parseUTCDate(updatedAt);
            if (isNaN(this.lastRefreshedAt.getTime())) {
                console.warn('[WorkerDetailsModal] Invalid date received:', updatedAt);
                return;
            }

            this.updateTimerDisplay();
            this.startTimer();
        } catch (e) {
            console.error('[WorkerDetailsModal] Error updating timer:', e);
        }
    }

    startTimer() {
        this.stopTimer();
        this.timerInterval = setInterval(() => this.updateTimerDisplay(), 1000);
    }

    stopTimer() {
        if (this.timerInterval) {
            clearInterval(this.timerInterval);
            this.timerInterval = null;
        }
    }

    updateTimerDisplay() {
        if (!this.lastRefreshedAt) return;

        const now = new Date();
        const diffMs = now - this.lastRefreshedAt;
        const diffSec = Math.floor(diffMs / 1000);

        // Update last refreshed text
        const timeEl = this.querySelector('.last-refreshed-time');
        if (timeEl) {
            let timeText = 'just now';
            if (diffSec >= 3600) {
                const hours = Math.floor(diffSec / 3600);
                timeText = `${hours}h ago`;
            } else if (diffSec >= 60) {
                const mins = Math.floor(diffSec / 60);
                timeText = `${mins}m ago`;
            } else if (diffSec > 5) {
                timeText = `${diffSec}s ago`;
            }
            timeEl.textContent = timeText;
            timeEl.title = this.lastRefreshedAt.toLocaleString();
        }

        // Update countdown
        // Assuming 5 minute refresh interval (300 seconds)
        const refreshIntervalMs = 300000;
        const nextRefresh = new Date(this.lastRefreshedAt.getTime() + refreshIntervalMs);
        const remainingMs = nextRefresh - now;

        const countdownEl = this.querySelector('#metrics-countdown');
        if (countdownEl) {
            if (remainingMs <= 0) {
                countdownEl.textContent = 'Due now';
            } else {
                const remainingSec = Math.ceil(remainingMs / 1000);
                const mins = Math.floor(remainingSec / 60);
                const secs = remainingSec % 60;
                countdownEl.textContent = `${mins}:${secs.toString().padStart(2, '0')}`;
            }
        }
    }

    formatMemory(kb) {
        if (!kb && kb !== 0) return '-';
        if (typeof kb === 'string') return kb;
        // Assume KB input
        if (kb > 1024 * 1024) {
            return (kb / 1024 / 1024).toFixed(1) + ' GB';
        } else if (kb > 1024) {
            return (kb / 1024).toFixed(1) + ' MB';
        }
        return kb + ' KB';
    }

    formatDisk(bytes) {
        if (!bytes && bytes !== 0) return '-';
        if (typeof bytes === 'string') return bytes;
        // Assume Bytes input (CML API usually returns bytes for disk)
        // Wait, CMLMetrics says size_kb. Let's assume KB to be safe or check API.
        // CMLSystemStats says all_disk_total.
        // Let's assume KB for consistency with memory if unsure, or Bytes.
        // Standard CML API often uses Bytes for disk.

        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }

    disconnectedCallback() {
        super.disconnectedCallback();
        this.stopTimer();
    }
}

// Register custom element
customElements.define('worker-details-modal', WorkerDetailsModal);
