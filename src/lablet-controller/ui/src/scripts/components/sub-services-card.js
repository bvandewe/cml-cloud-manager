/**
 * SubServicesCard Web Component
 * Fetches and displays sub-service health from /admin/sub-services endpoint.
 * Shows health cards for Lab Discovery, Lab Record Reconciler, Content Sync, Timeslot Watcher.
 */
class SubServicesCard extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
        this.refreshInterval = null;
    }

    static get observedAttributes() {
        return ['theme-color', 'refresh-interval'];
    }

    connectedCallback() {
        this.render();
        this.fetchData();

        const interval = parseInt(this.getAttribute('refresh-interval')) || 30000;
        this.refreshInterval = setInterval(() => this.fetchData(), interval);
    }

    disconnectedCallback() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
        }
    }

    async fetchData() {
        try {
            const response = await fetch('/api/admin/sub-services');
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            this.renderData(data);
        } catch (error) {
            this.renderError(error.message);
        }
    }

    render() {
        const themeColor = this.getAttribute('theme-color') || '#2ecc71';

        this.shadowRoot.innerHTML = `
            <style>
                :host { display: block; }
                .services-card {
                    background: white; border-radius: 12px; padding: 1.25rem;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                    border-left: 4px solid ${themeColor};
                }
                .card-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; }
                .card-title { font-size: 1rem; font-weight: 600; color: #333; }
                .services-grid {
                    display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
                    gap: 1rem;
                }
                .service-box {
                    border: 1px solid #e5e7eb; border-radius: 8px; padding: 1rem;
                    background: #fafafa;
                }
                .service-header {
                    display: flex; align-items: center; justify-content: space-between;
                    margin-bottom: 0.75rem;
                }
                .service-name { font-size: 0.85rem; font-weight: 600; color: #333; }
                .service-status {
                    display: inline-flex; align-items: center; gap: 0.25rem;
                    padding: 0.15rem 0.5rem; border-radius: 9999px;
                    font-size: 0.7rem; font-weight: 600;
                }
                .service-status.running { background: #dcfce7; color: #15803d; }
                .service-status.stopped { background: #fee2e2; color: #dc2626; }
                .service-status.disabled { background: #f3f4f6; color: #6b7280; }
                .mini-stats {
                    display: grid; grid-template-columns: repeat(auto-fit, minmax(70px, 1fr));
                    gap: 0.5rem;
                }
                .mini-stat { text-align: center; }
                .mini-value { font-size: 1.1rem; font-weight: 700; color: #212529; }
                .mini-value.success { color: #15803d; }
                .mini-value.error { color: #dc2626; }
                .mini-value.info { color: ${themeColor}; }
                .mini-value.warning { color: #f59e0b; }
                .mini-label { font-size: 0.6rem; text-transform: uppercase; color: #6c757d; }
                .service-meta {
                    margin-top: 0.5rem; font-size: 0.7rem; color: #6b7280;
                    border-top: 1px solid #e5e7eb; padding-top: 0.5rem;
                }
                .service-error { color: #dc2626; font-size: 0.7rem; margin-top: 0.25rem; }
                .loading {
                    display: flex; align-items: center; gap: 0.5rem;
                    color: #6c757d; padding: 1rem 0;
                }
                .spinner {
                    width: 18px; height: 18px; border: 2px solid #e9ecef;
                    border-top-color: ${themeColor}; border-radius: 50%;
                    animation: spin 1s linear infinite;
                }
                @keyframes spin { to { transform: rotate(360deg); } }
                .error-msg { color: #dc3545; padding: 0.75rem; background: #fee2e2; border-radius: 8px; font-size: 0.85rem; }
                .last-update { font-size: 0.7rem; color: #6c757d; text-align: right; margin-top: 0.75rem; }
            </style>
            <div class="services-card">
                <div class="card-header">
                    <span class="card-title">🔧 Sub-Services Health</span>
                </div>
                <div id="content">
                    <div class="loading"><div class="spinner"></div><span>Loading sub-services...</span></div>
                </div>
            </div>
        `;
    }

    renderData(data) {
        const content = this.shadowRoot.getElementById('content');
        let html = '<div class="services-grid">';

        // Lab Discovery
        if (data.lab_discovery) {
            html += this.renderServiceBox(
                '🔍 Lab Discovery',
                data.lab_discovery,
                [
                    { key: 'discovery_runs', label: 'Runs', cls: 'info' },
                    { key: 'total_labs_synced', label: 'Synced', cls: 'success' },
                    { key: 'total_labs_discovered', label: 'Found', cls: 'info' },
                    { key: 'total_labs_updated', label: 'Updated', cls: 'info' },
                    { key: 'total_labs_orphaned', label: 'Orphaned', cls: 'warning' },
                    { key: 'total_ports_registered', label: 'Ports', cls: 'info' },
                ],
                'last_run_at'
            );
        }

        // Lab Record Reconciler
        if (data.lab_record_reconciler) {
            html += this.renderServiceBox('📋 Lab Records', data.lab_record_reconciler, [
                { key: 'actions_received', label: 'Received', cls: 'info' },
                { key: 'actions_succeeded', label: 'Success', cls: 'success' },
                { key: 'actions_failed', label: 'Failed', cls: 'error' },
                { key: 'actions_skipped', label: 'Skipped', cls: 'warning' },
                { key: 'cached_workers', label: 'Cached', cls: 'info' },
            ]);
        }

        // Content Sync
        if (data.content_sync) {
            html += this.renderServiceBox(
                '📦 Content Sync',
                data.content_sync,
                [
                    { key: 'syncs_received', label: 'Received', cls: 'info' },
                    { key: 'syncs_succeeded', label: 'Success', cls: 'success' },
                    { key: 'syncs_failed', label: 'Failed', cls: 'error' },
                ],
                'last_sync_at'
            );
        }

        // Timeslot Watcher
        if (data.timeslot_watcher) {
            html += this.renderServiceBox(
                '⏰ Timeslot Watcher',
                data.timeslot_watcher,
                [
                    { key: 'scan_count', label: 'Scans', cls: 'info' },
                    { key: 'triggers_approaching', label: 'Approaching', cls: 'warning' },
                    { key: 'triggers_past_end', label: 'Past End', cls: 'error' },
                    { key: 'tracked_approaching', label: 'Tracked ↑', cls: 'info' },
                    { key: 'tracked_past_end', label: 'Tracked ↓', cls: 'info' },
                ],
                'last_scan_at'
            );
        }

        html += '</div>';
        html += `<div class="last-update">Updated: ${new Date().toLocaleTimeString()}</div>`;
        content.innerHTML = html;
    }

    renderServiceBox(name, svc, statDefs, timeKey) {
        if (svc.message === 'Not configured') {
            return `
                <div class="service-box">
                    <div class="service-header">
                        <span class="service-name">${name}</span>
                        <span class="service-status disabled">Not Configured</span>
                    </div>
                </div>`;
        }

        const isRunning = svc.running === true;
        const isEnabled = svc.enabled !== false;
        const statusCls = !isEnabled ? 'disabled' : isRunning ? 'running' : 'stopped';
        const statusLabel = !isEnabled ? 'Disabled' : isRunning ? '● Running' : '○ Stopped';

        let statsHtml = '<div class="mini-stats">';
        for (const def of statDefs) {
            const val = svc[def.key] ?? 0;
            statsHtml += `<div class="mini-stat"><div class="mini-value ${def.cls}">${val}</div><div class="mini-label">${def.label}</div></div>`;
        }
        statsHtml += '</div>';

        let metaHtml = '';
        if (timeKey && svc[timeKey]) {
            const t = new Date(svc[timeKey]);
            metaHtml = `<div class="service-meta">Last: ${t.toLocaleTimeString()}</div>`;
        }
        if (svc.last_error) {
            metaHtml += `<div class="service-error">⚠ ${svc.last_error}</div>`;
        }

        return `
            <div class="service-box">
                <div class="service-header">
                    <span class="service-name">${name}</span>
                    <span class="service-status ${statusCls}">${statusLabel}</span>
                </div>
                ${statsHtml}
                ${metaHtml}
            </div>`;
    }

    renderError(message) {
        const content = this.shadowRoot.getElementById('content');
        content.innerHTML = `<div class="error-msg">Failed to load sub-services data: ${message}</div>`;
    }
}

customElements.define('sub-services-card', SubServicesCard);
