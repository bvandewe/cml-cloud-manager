/**
 * SystemPage - System Administration Page Component
 *
 * Provides a tabbed interface for system administration:
 * - Monitoring: Health checks, SSE status, worker monitoring status
 * - Settings: System configuration (admin only)
 *
 * Uses LcmTabView for sub-navigation.
 *
 * @module components/pages/SystemPage
 */

import { BaseComponent } from '../../core/BaseComponent.js';
import { eventBus, EventTypes } from '../../core/EventBus.js';
import '../core/LcmTabView.js';
import '../core/LcmStatusBadge.js';

export class SystemPage extends BaseComponent {
    static get observedAttributes() {
        return ['active-tab'];
    }

    constructor() {
        super();
        this._currentUser = null;
        this._activeTab = 'monitoring';
        this._systemHealth = null;
        this._schedulerStatus = null;
        this._workerMonitoring = null;
        this._settings = null;
        this._isLoading = true;
        this._refreshInterval = null;
    }

    /**
     * Initialize the page with user context
     * @param {Object} user - Current user object with roles
     */
    initialize(user) {
        this._currentUser = user;
        this.render();
        this._setupEventListeners();
        this._loadData();

        // Auto-refresh monitoring data every 30 seconds
        this._refreshInterval = setInterval(() => {
            if (this._activeTab === 'monitoring') {
                this._loadMonitoringData();
            }
        }, 30000);
    }

    onMount() {
        // Initial render with loading state
        this.innerHTML = this._renderLoading();
    }

    onUnmount() {
        if (this._refreshInterval) {
            clearInterval(this._refreshInterval);
            this._refreshInterval = null;
        }
    }

    onAttributeChange(name, oldValue, newValue) {
        if (name === 'active-tab' && oldValue !== newValue) {
            this._activeTab = newValue;
            this._updateTabContent();
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

    /**
     * Load all data based on active tab
     */
    async _loadData() {
        if (this._activeTab === 'monitoring') {
            await this._loadMonitoringData();
        } else if (this._activeTab === 'settings') {
            await this._loadSettings();
        }
    }

    /**
     * Load monitoring data from API
     */
    async _loadMonitoringData() {
        try {
            const { getSystemHealth, getSchedulerStatus, getWorkerMonitoringStatus } = await import('../../api/system.js');

            const [health, scheduler, monitoring] = await Promise.allSettled([getSystemHealth(), getSchedulerStatus(), getWorkerMonitoringStatus()]);

            this._systemHealth = health.status === 'fulfilled' ? health.value : null;
            this._schedulerStatus = scheduler.status === 'fulfilled' ? scheduler.value : null;
            this._workerMonitoring = monitoring.status === 'fulfilled' ? monitoring.value : null;

            this._isLoading = false;
            this._renderMonitoringTab();
        } catch (error) {
            console.error('[SystemPage] Failed to load monitoring data:', error);
            this._isLoading = false;
            this._renderMonitoringTab();
        }
    }

    /**
     * Load settings from API
     */
    async _loadSettings() {
        try {
            const { apiRequest } = await import('../../api/client.js');
            const response = await apiRequest('/api/settings');
            this._settings = await response.json();
            this._isLoading = false;
            this._renderSettingsTab();
        } catch (error) {
            console.error('[SystemPage] Failed to load settings:', error);
            this._isLoading = false;
            this._renderSettingsTab();
        }
    }

    render() {
        const isAdmin = this._isAdminOrManager();

        this.innerHTML = `
            <div class="system-page">
                <!-- Page Header -->
                <div class="page-header d-flex justify-content-between align-items-center mb-4">
                    <div>
                        <h2 class="mb-1">
                            <i class="bi bi-gear me-2"></i>System
                        </h2>
                        <p class="text-muted mb-0">System monitoring and configuration</p>
                    </div>
                    <div>
                        <button class="btn btn-outline-secondary" id="refresh-system">
                            <i class="bi bi-arrow-clockwise me-1"></i>Refresh
                        </button>
                    </div>
                </div>

                <!-- Sub-tabs -->
                <lcm-tab-view id="system-tabs" variant="underline" persist-key="system-tab">
                    <lcm-tab id="monitoring" label="Monitoring" icon="bi-heart-pulse" ${this._activeTab === 'monitoring' ? 'active' : ''}></lcm-tab>
                    ${isAdmin ? `<lcm-tab id="settings" label="Settings" icon="bi-sliders"></lcm-tab>` : ''}
                </lcm-tab-view>

                <!-- Tab Content -->
                <div class="tab-content mt-4">
                    <!-- Monitoring Tab -->
                    <div id="system-monitoring-content" class="tab-pane ${this._activeTab === 'monitoring' ? 'active' : ''}" ${this._activeTab !== 'monitoring' ? 'style="display: none;"' : ''}>
                        ${this._isLoading ? this._renderLoading() : this._renderMonitoringContent()}
                    </div>

                    <!-- Settings Tab (Admin only) -->
                    ${
                        isAdmin
                            ? `
                    <div id="system-settings-content" class="tab-pane ${this._activeTab === 'settings' ? 'active' : ''}" ${this._activeTab !== 'settings' ? 'style="display: none;"' : ''}>
                        ${this._isLoading ? this._renderLoading() : this._renderSettingsContent()}
                    </div>
                    `
                            : ''
                    }
                </div>
            </div>
        `;

        this._setupEventListeners();
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

    _renderMonitoringContent() {
        return `
            <!-- System Health -->
            <div class="card mb-4">
                <div class="card-header d-flex justify-content-between align-items-center bg-white py-2">
                    <span class="fw-medium"><i class="bi bi-heart-pulse me-2"></i>System Health</span>
                    <lcm-status-badge status="${this._systemHealth?.status || 'unknown'}"></lcm-status-badge>
                </div>
                <div class="card-body">
                    ${this._renderHealthComponents()}
                </div>
            </div>

            <!-- SSE Connection Status -->
            <div class="card mb-4">
                <div class="card-header d-flex justify-content-between align-items-center bg-white py-2">
                    <span class="fw-medium"><i class="bi bi-broadcast me-2"></i>SSE Connection</span>
                    <lcm-status-badge id="sse-connection-status" status="unknown"></lcm-status-badge>
                </div>
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-6">
                            <p class="mb-1"><strong>Endpoint:</strong> <code>/api/events/stream</code></p>
                        </div>
                        <div class="col-md-6">
                            <p class="mb-1"><strong>Status:</strong> <span id="sse-status-text">Checking...</span></p>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Worker Monitoring -->
            <div class="card mb-4">
                <div class="card-header bg-white py-2">
                    <span class="fw-medium"><i class="bi bi-server me-2"></i>Worker Monitoring</span>
                </div>
                <div class="card-body">
                    ${this._renderWorkerMonitoring()}
                </div>
            </div>

            <!-- Controller Status (ADR-011) -->
            <div class="card mb-4">
                <div class="card-header bg-white py-2">
                    <span class="fw-medium"><i class="bi bi-cpu me-2"></i>Background Controllers</span>
                </div>
                <div class="card-body">
                    ${this._renderControllerStatus()}
                </div>
            </div>
        `;
    }

    _renderHealthComponents() {
        const components = this._systemHealth?.components || {};

        if (Object.keys(components).length === 0) {
            return '<p class="text-muted mb-0">No component health data available</p>';
        }

        return `
            <div class="row g-3">
                ${Object.entries(components)
                    .map(
                        ([name, data]) => `
                    <div class="col-md-4">
                        <div class="d-flex align-items-center p-2 border rounded">
                            <lcm-status-badge status="${data.status || 'unknown'}" class="me-2"></lcm-status-badge>
                            <div>
                                <strong>${this._formatComponentName(name)}</strong>
                                ${data.message ? `<br><small class="text-muted">${data.message}</small>` : ''}
                            </div>
                        </div>
                    </div>
                `
                    )
                    .join('')}
            </div>
        `;
    }

    _formatComponentName(name) {
        return name
            .replace(/_/g, ' ')
            .replace(/\b\w/g, c => c.toUpperCase())
            .replace('Mongodb', 'MongoDB')
            .replace('Sse', 'SSE')
            .replace('Api', 'API');
    }

    _renderWorkerMonitoring() {
        if (!this._workerMonitoring) {
            return '<p class="text-muted mb-0">Worker monitoring data unavailable</p>';
        }

        const workers = this._workerMonitoring.workers || [];

        return `
            <div class="mb-3">
                <span class="badge bg-primary me-2">${this._workerMonitoring.monitored_workers || 0} workers monitored</span>
                <span class="text-muted">via ${this._workerMonitoring.monitoring_service || 'worker-controller'}</span>
            </div>
            ${
                workers.length > 0
                    ? `
            <div class="table-responsive">
                <table class="table table-sm table-hover mb-0">
                    <thead>
                        <tr>
                            <th>Worker</th>
                            <th>Status</th>
                            <th>Last Metrics</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${workers
                            .map(
                                w => `
                            <tr>
                                <td>${w.name || w.worker_id}</td>
                                <td><lcm-status-badge status="${w.status}"></lcm-status-badge></td>
                                <td>${w.last_metrics_at ? this._formatRelativeTime(w.last_metrics_at) : 'Never'}</td>
                            </tr>
                        `
                            )
                            .join('')}
                    </tbody>
                </table>
            </div>
            `
                    : '<p class="text-muted mb-0">No workers currently being monitored</p>'
            }
        `;
    }

    _renderControllerStatus() {
        const controllers = [
            {
                name: 'worker-controller',
                description: 'Worker discovery and reconciliation',
                icon: 'bi-server',
            },
            {
                name: 'lablet-controller',
                description: 'Lablet instance reconciliation',
                icon: 'bi-collection',
            },
            {
                name: 'resource-scheduler',
                description: 'Resource scheduling and placement',
                icon: 'bi-calendar-check',
            },
        ];

        return `
            <div class="row g-3">
                ${controllers
                    .map(
                        c => `
                    <div class="col-md-4">
                        <div class="d-flex align-items-start p-3 border rounded h-100">
                            <i class="${c.icon} fs-4 text-primary me-3"></i>
                            <div>
                                <strong>${c.name}</strong>
                                <br><small class="text-muted">${c.description}</small>
                            </div>
                        </div>
                    </div>
                `
                    )
                    .join('')}
            </div>
            <div class="mt-3">
                <small class="text-muted">
                    <i class="bi bi-info-circle me-1"></i>
                    Background jobs are executed by dedicated controllers per ADR-011.
                </small>
            </div>
        `;
    }

    _renderSettingsContent() {
        if (!this._settings) {
            return `
                <div class="alert alert-warning">
                    <i class="bi bi-exclamation-triangle me-2"></i>
                    Failed to load settings. Please try refreshing the page.
                </div>
            `;
        }

        return `
            <form id="settings-form">
                <!-- Worker Provisioning -->
                <div class="card mb-4">
                    <div class="card-header bg-white py-2">
                        <span class="fw-medium"><i class="bi bi-server me-2"></i>Worker Provisioning</span>
                    </div>
                    <div class="card-body">
                        <div class="row g-3">
                            <div class="col-md-6">
                                <label class="form-label">Default AMI Name</label>
                                <input type="text" class="form-control" name="ami_name_default"
                                    value="${this._settings.worker_provisioning?.ami_name_default || ''}"
                                    placeholder="e.g., cml-worker-*">
                                <small class="text-muted">AMI name pattern for worker instances</small>
                            </div>
                            <div class="col-md-6">
                                <label class="form-label">Instance Type</label>
                                <input type="text" class="form-control" name="instance_type"
                                    value="${this._settings.worker_provisioning?.instance_type || ''}"
                                    placeholder="e.g., m5zn.metal">
                            </div>
                            <div class="col-md-6">
                                <label class="form-label">Security Group IDs</label>
                                <input type="text" class="form-control" name="security_group_ids"
                                    value="${(this._settings.worker_provisioning?.security_group_ids || []).join(', ')}"
                                    placeholder="sg-xxx, sg-yyy">
                                <small class="text-muted">Comma-separated list</small>
                            </div>
                            <div class="col-md-6">
                                <label class="form-label">Subnet ID</label>
                                <input type="text" class="form-control" name="subnet_id"
                                    value="${this._settings.worker_provisioning?.subnet_id || ''}"
                                    placeholder="subnet-xxx">
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Monitoring & Idle Detection -->
                <div class="card mb-4">
                    <div class="card-header bg-white py-2">
                        <span class="fw-medium"><i class="bi bi-activity me-2"></i>Monitoring & Idle Detection</span>
                    </div>
                    <div class="card-body">
                        <div class="row g-3">
                            <div class="col-md-6">
                                <label class="form-label">Metrics Poll Interval (seconds)</label>
                                <input type="number" class="form-control" name="metrics_poll_interval"
                                    value="${this._settings.monitoring?.worker_metrics_poll_interval_seconds || 300}"
                                    min="60" max="3600">
                            </div>
                            <div class="col-md-6">
                                <label class="form-label">Idle Timeout (minutes)</label>
                                <input type="number" class="form-control" name="idle_timeout_minutes"
                                    value="${this._settings.idle_detection?.timeout_minutes || 60}"
                                    min="5" max="1440">
                            </div>
                            <div class="col-12">
                                <div class="form-check">
                                    <input type="checkbox" class="form-check-input" name="idle_detection_enabled" id="idle-detection-enabled"
                                        ${this._settings.idle_detection?.enabled ? 'checked' : ''}>
                                    <label class="form-check-label" for="idle-detection-enabled">
                                        Enable idle detection
                                    </label>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Discovery Settings -->
                <div class="card mb-4">
                    <div class="card-header bg-white py-2">
                        <span class="fw-medium"><i class="bi bi-search me-2"></i>Worker Discovery (ADR-012)</span>
                    </div>
                    <div class="card-body">
                        <div class="row g-3">
                            <div class="col-12">
                                <div class="form-check">
                                    <input type="checkbox" class="form-check-input" name="discovery_enabled" id="discovery-enabled"
                                        ${this._settings.discovery?.enabled !== false ? 'checked' : ''}>
                                    <label class="form-check-label" for="discovery-enabled">
                                        Enable automatic worker discovery
                                    </label>
                                </div>
                            </div>
                            <div class="col-md-6">
                                <label class="form-label">AMI Name Pattern</label>
                                <input type="text" class="form-control" name="discovery_ami_pattern"
                                    value="${this._settings.discovery?.ami_name_pattern || ''}"
                                    placeholder="e.g., cml-*">
                            </div>
                            <div class="col-md-6">
                                <label class="form-label">Scan Interval (seconds)</label>
                                <input type="number" class="form-control" name="discovery_scan_interval"
                                    value="${this._settings.discovery?.scan_interval_seconds || 300}"
                                    min="60" max="3600">
                            </div>
                            <div class="col-12">
                                <label class="form-label">Regions</label>
                                <select class="form-select" name="discovery_regions" id="discovery-regions" multiple size="4">
                                    ${this._renderRegionOptions()}
                                </select>
                                <small class="text-muted">Hold Ctrl/Cmd to select multiple regions</small>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Save Button -->
                <div class="d-flex justify-content-end">
                    <button type="submit" class="btn btn-primary" id="save-settings-btn">
                        <i class="bi bi-check-lg me-1"></i>Save Settings
                    </button>
                </div>
            </form>
        `;
    }

    _renderRegionOptions() {
        const regions = [
            { value: 'us-east-1', label: 'US East (N. Virginia)' },
            { value: 'us-east-2', label: 'US East (Ohio)' },
            { value: 'us-west-1', label: 'US West (N. California)' },
            { value: 'us-west-2', label: 'US West (Oregon)' },
            { value: 'eu-west-1', label: 'EU (Ireland)' },
            { value: 'eu-west-2', label: 'EU (London)' },
            { value: 'eu-central-1', label: 'EU (Frankfurt)' },
            { value: 'ap-northeast-1', label: 'Asia Pacific (Tokyo)' },
            { value: 'ap-southeast-1', label: 'Asia Pacific (Singapore)' },
            { value: 'ap-southeast-2', label: 'Asia Pacific (Sydney)' },
        ];

        const selectedRegions = this._settings?.discovery?.regions || [];

        return regions
            .map(
                r => `
            <option value="${r.value}" ${selectedRegions.includes(r.value) ? 'selected' : ''}>
                ${r.label}
            </option>
        `
            )
            .join('');
    }

    _formatRelativeTime(isoString) {
        if (!isoString) return 'Unknown';

        const date = new Date(isoString);
        const now = new Date();
        const diffMs = now - date;
        const diffSec = Math.floor(diffMs / 1000);
        const diffMin = Math.floor(diffSec / 60);
        const diffHour = Math.floor(diffMin / 60);

        if (diffSec < 60) return 'Just now';
        if (diffMin < 60) return `${diffMin}m ago`;
        if (diffHour < 24) return `${diffHour}h ago`;
        return date.toLocaleDateString();
    }

    _renderMonitoringTab() {
        const container = this.querySelector('#system-monitoring-content');
        if (container) {
            container.innerHTML = this._renderMonitoringContent();
            this._updateSSEStatus();
        }
    }

    _renderSettingsTab() {
        const container = this.querySelector('#system-settings-content');
        if (container) {
            container.innerHTML = this._renderSettingsContent();
            this._setupSettingsListeners();
        }
    }

    _updateTabContent() {
        // Hide all tabs
        this.querySelectorAll('.tab-pane').forEach(pane => {
            pane.style.display = 'none';
            pane.classList.remove('active');
        });

        // Show active tab
        const activePane = this.querySelector(`#system-${this._activeTab}-content`);
        if (activePane) {
            activePane.style.display = 'block';
            activePane.classList.add('active');
        }

        // Load data for the active tab
        this._loadData();
    }

    _setupEventListeners() {
        // Refresh button
        const refreshBtn = this.querySelector('#refresh-system');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => this._loadData());
        }

        // Tab changes
        const tabView = this.querySelector('#system-tabs');
        if (tabView) {
            tabView.addEventListener('tab-change', e => {
                this._activeTab = e.detail.tabId;
                this._updateTabContent();
            });
        }

        // SSE status updates
        this.subscribe(EventTypes.SSE_CONNECTED, () => this._updateSSEStatus('connected'));
        this.subscribe(EventTypes.SSE_DISCONNECTED, () => this._updateSSEStatus('disconnected'));
        this.subscribe(EventTypes.SSE_ERROR, () => this._updateSSEStatus('error'));

        // Setup settings form listeners if on settings tab
        if (this._activeTab === 'settings') {
            this._setupSettingsListeners();
        }
    }

    _setupSettingsListeners() {
        const form = this.querySelector('#settings-form');
        if (form) {
            form.addEventListener('submit', async e => {
                e.preventDefault();
                await this._saveSettings();
            });
        }
    }

    async _saveSettings() {
        const form = this.querySelector('#settings-form');
        if (!form) return;

        const formData = new FormData(form);

        // Get selected regions
        const regionsSelect = this.querySelector('#discovery-regions');
        const selectedRegions = regionsSelect ? Array.from(regionsSelect.selectedOptions).map(opt => opt.value) : [];

        const payload = {
            worker_provisioning: {
                ami_name_default: formData.get('ami_name_default'),
                instance_type: formData.get('instance_type'),
                security_group_ids: formData
                    .get('security_group_ids')
                    .split(',')
                    .map(s => s.trim())
                    .filter(s => s),
                subnet_id: formData.get('subnet_id') || null,
            },
            monitoring: {
                worker_metrics_poll_interval_seconds: parseInt(formData.get('metrics_poll_interval')),
            },
            idle_detection: {
                enabled: formData.get('idle_detection_enabled') === 'on',
                timeout_minutes: parseInt(formData.get('idle_timeout_minutes')),
            },
            discovery: {
                enabled: formData.get('discovery_enabled') === 'on',
                regions: selectedRegions,
                ami_name_pattern: formData.get('discovery_ami_pattern') || '',
                scan_interval_seconds: parseInt(formData.get('discovery_scan_interval')) || 300,
            },
        };

        try {
            const { apiRequest } = await import('../../api/client.js');
            await apiRequest('/api/settings', {
                method: 'PUT',
                body: JSON.stringify(payload),
            });

            // Show success message
            const { showToast } = await import('../../ui/notifications.js');
            showToast('Settings saved successfully', 'success');
        } catch (error) {
            console.error('[SystemPage] Failed to save settings:', error);
            const { showToast } = await import('../../ui/notifications.js');
            showToast('Failed to save settings: ' + error.message, 'error');
        }
    }

    _updateSSEStatus(status) {
        const badge = this.querySelector('#sse-connection-status');
        const text = this.querySelector('#sse-status-text');

        if (!status) {
            // LcmSSEAdapter is connected globally; rely on EventBus events for status
            status = 'disconnected';
        }

        if (badge) {
            const statusMap = {
                connected: 'healthy',
                disconnected: 'stopped',
                error: 'error',
            };
            badge.setAttribute('status', statusMap[status] || 'unknown');
        }

        if (text) {
            const textMap = {
                connected: 'Connected',
                disconnected: 'Disconnected',
                error: 'Error',
            };
            text.textContent = textMap[status] || 'Unknown';
        }
    }
}

// Register the component
customElements.define('system-page', SystemPage);

export default SystemPage;
