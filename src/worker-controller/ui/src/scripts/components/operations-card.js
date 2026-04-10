/**
 * OperationsCard Web Component
 * Fetches and displays operational overview from /admin/operations endpoint.
 * Shows discovery stats, metrics collection, scale-down, and resource state summary.
 */
class OperationsCard extends HTMLElement {
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
            const response = await fetch('/api/admin/operations');
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            this.renderData(data);
        } catch (error) {
            this.renderError(error.message);
        }
    }

    render() {
        const themeColor = this.getAttribute('theme-color') || '#f39c12';

        this.shadowRoot.innerHTML = `
            <style>
                :host { display: block; }
                .ops-card {
                    background: white; border-radius: 12px; padding: 1.25rem;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                    border-left: 4px solid ${themeColor};
                }
                .card-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; }
                .card-title { font-size: 1rem; font-weight: 600; color: #333; }
                .section-title {
                    font-size: 0.75rem; font-weight: 600; text-transform: uppercase;
                    color: #6c757d; letter-spacing: 0.5px; margin: 1rem 0 0.5rem 0;
                    padding-bottom: 0.25rem; border-bottom: 1px solid #e9ecef;
                }
                .stats-grid {
                    display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
                    gap: 0.75rem;
                }
                .stat-item { padding: 0.75rem; background: #f8f9fa; border-radius: 8px; text-align: center; }
                .stat-value { font-size: 1.5rem; font-weight: 700; color: #212529; }
                .stat-value.success { color: #15803d; }
                .stat-value.error { color: #dc2626; }
                .stat-value.info { color: ${themeColor}; }
                .stat-value.warning { color: #f59e0b; }
                .stat-label {
                    font-size: 0.7rem; text-transform: uppercase; color: #6c757d;
                    letter-spacing: 0.5px; margin-top: 0.25rem;
                }
                .discovery-status {
                    display: flex; align-items: center; gap: 0.5rem;
                    padding: 0.5rem 0.75rem; background: #f8f9fa; border-radius: 8px;
                    margin-bottom: 0.75rem;
                }
                .dot { width: 8px; height: 8px; border-radius: 50%; }
                .dot.running { background: #22c55e; }
                .dot.stopped { background: #ef4444; }
                .dot.disabled { background: #9ca3af; }
                .meta { font-size: 0.75rem; color: #6b7280; }
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
                .error { color: #dc3545; padding: 0.75rem; background: #fee2e2; border-radius: 8px; font-size: 0.85rem; }
                .last-update { font-size: 0.7rem; color: #6c757d; text-align: right; margin-top: 0.75rem; }
            </style>
            <div class="ops-card">
                <div class="card-header">
                    <span class="card-title">⚙️ Operations Overview</span>
                </div>
                <div id="content">
                    <div class="loading"><div class="spinner"></div><span>Loading operations data...</span></div>
                </div>
            </div>
        `;
    }

    renderData(data) {
        const content = this.shadowRoot.getElementById('content');
        const stats = data.stats || {};
        const discovery = data.discovery || {};
        const resSummary = data.resource_states_summary || {};

        let html = '';

        // Discovery section
        const discEnabled = discovery.enabled !== false;
        const discRunning = discovery.running === true;
        const dotClass = !discEnabled ? 'disabled' : discRunning ? 'running' : 'stopped';
        const discLabel = !discEnabled ? 'Disabled' : discRunning ? 'Running' : 'Idle';

        html += `
            <div class="section-title">Worker Discovery</div>
            <div class="discovery-status">
                <span class="dot ${dotClass}"></span>
                <span>${discLabel}</span>
                ${discovery.last_run_at ? `<span class="meta">Last: ${new Date(discovery.last_run_at).toLocaleTimeString()}</span>` : ''}
                ${discovery.last_error ? `<span class="meta" style="color:#dc2626">Error: ${discovery.last_error}</span>` : ''}
            </div>
            <div class="stats-grid">
                <div class="stat-item"><div class="stat-value info">${discovery.runs || 0}</div><div class="stat-label">Runs</div></div>
                <div class="stat-item"><div class="stat-value success">${discovery.total_discovered || 0}</div><div class="stat-label">Discovered</div></div>
                <div class="stat-item"><div class="stat-value success">${discovery.total_imported || 0}</div><div class="stat-label">Imported</div></div>
                <div class="stat-item"><div class="stat-value warning">${discovery.total_orphans_terminated || 0}</div><div class="stat-label">Orphans</div></div>
            </div>`;

        // Lifecycle counters
        html += `
            <div class="section-title">Lifecycle Operations</div>
            <div class="stats-grid">
                <div class="stat-item"><div class="stat-value success">${stats.provisioned_count || 0}</div><div class="stat-label">Provisioned</div></div>
                <div class="stat-item"><div class="stat-value success">${stats.started_count || 0}</div><div class="stat-label">Started</div></div>
                <div class="stat-item"><div class="stat-value warning">${stats.stopped_count || 0}</div><div class="stat-label">Stopped</div></div>
                <div class="stat-item"><div class="stat-value error">${stats.terminated_count || 0}</div><div class="stat-label">Terminated</div></div>
            </div>`;

        // Scale & Metrics
        html += `
            <div class="section-title">Scale & Metrics</div>
            <div class="stats-grid">
                <div class="stat-item"><div class="stat-value info">${stats.metrics_collected_count || 0}</div><div class="stat-label">Metrics</div></div>
                <div class="stat-item"><div class="stat-value info">${stats.activity_checks_count || 0}</div><div class="stat-label">Activity Checks</div></div>
                <div class="stat-item"><div class="stat-value warning">${stats.auto_pauses_triggered_count || 0}</div><div class="stat-label">Auto-Pauses</div></div>
                <div class="stat-item"><div class="stat-value warning">${stats.scale_down_count || 0}</div><div class="stat-label">Scale Downs</div></div>
            </div>`;

        // License Operations
        html += `
            <div class="section-title">License Operations</div>
            <div class="stats-grid">
                <div class="stat-item"><div class="stat-value success">${stats.license_registrations_count || 0}</div><div class="stat-label">Registrations</div></div>
                <div class="stat-item"><div class="stat-value info">${stats.license_deregistrations_count || 0}</div><div class="stat-label">Deregistrations</div></div>
            </div>`;

        // Resource states summary
        html += `
            <div class="section-title">Resource States</div>
            <div class="stats-grid">
                <div class="stat-item"><div class="stat-value info">${resSummary.total || 0}</div><div class="stat-label">Total</div></div>
                <div class="stat-item"><div class="stat-value success">${resSummary.healthy || 0}</div><div class="stat-label">Healthy</div></div>
                <div class="stat-item"><div class="stat-value warning">${resSummary.in_progress || 0}</div><div class="stat-label">In Progress</div></div>
                <div class="stat-item"><div class="stat-value error">${resSummary.failed || 0}</div><div class="stat-label">Failed</div></div>
            </div>`;

        html += `<div class="last-update">Updated: ${new Date().toLocaleTimeString()}</div>`;

        content.innerHTML = html;
    }

    renderError(message) {
        const content = this.shadowRoot.getElementById('content');
        content.innerHTML = `<div class="error">Failed to load operations data: ${message}</div>`;
    }
}

customElements.define('operations-card', OperationsCard);
