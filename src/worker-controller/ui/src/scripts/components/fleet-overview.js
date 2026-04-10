/**
 * FleetOverview Web Component
 * Fetches and displays worker fleet from /admin/fleet endpoint.
 * Shows a sortable table of workers with status badges and reconciliation state.
 */
class FleetOverview extends HTMLElement {
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
            const response = await fetch('/api/admin/fleet');
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
                .fleet-card {
                    background: white; border-radius: 12px; padding: 1.25rem;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                    border-left: 4px solid ${themeColor};
                }
                .card-header {
                    display: flex; align-items: center; justify-content: space-between;
                    margin-bottom: 1rem;
                }
                .card-title { font-size: 1rem; font-weight: 600; color: #333; }
                .summary-bar {
                    display: flex; gap: 0.75rem; flex-wrap: wrap; margin-bottom: 1rem;
                }
                .summary-badge {
                    display: inline-flex; align-items: center; gap: 0.25rem;
                    padding: 0.3rem 0.6rem; border-radius: 20px;
                    font-size: 0.75rem; font-weight: 600;
                }
                .summary-badge.total { background: #e5e7eb; color: #374151; }
                .summary-badge.running { background: #dcfce7; color: #15803d; }
                .summary-badge.stopped { background: #fef3c7; color: #92400e; }
                .summary-badge.terminated { background: #fee2e2; color: #dc2626; }
                .summary-badge.pending { background: #dbeafe; color: #1d4ed8; }
                .summary-badge.provisioning { background: #ede9fe; color: #6d28d9; }
                .summary-badge.other { background: #f3f4f6; color: #6b7280; }
                table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
                thead th {
                    text-align: left; padding: 0.5rem 0.75rem;
                    border-bottom: 2px solid #e5e7eb; color: #6b7280;
                    font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.5px;
                }
                tbody td {
                    padding: 0.5rem 0.75rem; border-bottom: 1px solid #f3f4f6;
                    vertical-align: middle;
                }
                tbody tr:hover { background: #f9fafb; }
                .status-badge {
                    display: inline-block; padding: 0.15rem 0.5rem;
                    border-radius: 9999px; font-size: 0.7rem; font-weight: 600;
                    text-transform: uppercase;
                }
                .status-running { background: #dcfce7; color: #15803d; }
                .status-stopped { background: #fef3c7; color: #92400e; }
                .status-terminated { background: #fee2e2; color: #dc2626; }
                .status-pending { background: #dbeafe; color: #1d4ed8; }
                .status-provisioning { background: #ede9fe; color: #6d28d9; }
                .status-starting { background: #e0f2fe; color: #0369a1; }
                .status-stopping { background: #ffedd5; color: #c2410c; }
                .status-draining { background: #fef9c3; color: #a16207; }
                .status-unknown { background: #f3f4f6; color: #6b7280; }
                .mono { font-family: 'Monaco', 'Menlo', monospace; font-size: 0.75rem; }
                .truncate { max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
                .recon-badge {
                    display: inline-block; padding: 0.1rem 0.4rem;
                    border-radius: 4px; font-size: 0.65rem; font-weight: 500;
                }
                .recon-ok { background: #dcfce7; color: #15803d; }
                .recon-fail { background: #fee2e2; color: #dc2626; }
                .recon-progress { background: #dbeafe; color: #1d4ed8; }
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
                .empty { color: #6c757d; font-style: italic; padding: 2rem; text-align: center; }
                .last-update { font-size: 0.7rem; color: #6c757d; text-align: right; margin-top: 0.75rem; }
            </style>
            <div class="fleet-card">
                <div class="card-header">
                    <span class="card-title">🖥️ Worker Fleet</span>
                </div>
                <div id="content">
                    <div class="loading"><div class="spinner"></div><span>Loading fleet data...</span></div>
                </div>
            </div>
        `;
    }

    renderData(data) {
        const content = this.shadowRoot.getElementById('content');
        const workers = data.workers || [];
        const statusCounts = data.status_counts || {};
        const resourceStates = data.resource_states || {};

        if (workers.length === 0) {
            content.innerHTML = '<div class="empty">No workers found</div>';
            return;
        }

        // Status summary badges
        const knownStatuses = ['running', 'stopped', 'terminated', 'pending', 'provisioning'];
        let summaryHtml = `<div class="summary-bar">
            <span class="summary-badge total">Total: ${data.total || workers.length}</span>`;
        for (const [status, count] of Object.entries(statusCounts)) {
            const cls = knownStatuses.includes(status) ? status : 'other';
            summaryHtml += `<span class="summary-badge ${cls}">${status}: ${count}</span>`;
        }
        summaryHtml += '</div>';

        // Workers table
        let tableHtml = `
            <table>
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Status</th>
                        <th>Instance Type</th>
                        <th>Region</th>
                        <th>IP</th>
                        <th>Reconciliation</th>
                    </tr>
                </thead>
                <tbody>`;

        for (const w of workers) {
            const wid = w.id || w.worker_id || '';
            const name = w.name || wid.substring(0, 12) || '—';
            const status = w.status || 'unknown';
            const instanceType = w.instance_type || '—';
            const region = w.aws_region || '—';
            const ip = w.public_ip || w.private_ip || '—';
            const rs = resourceStates[wid];

            let reconHtml = '<span class="recon-badge recon-ok">✓</span>';
            if (rs) {
                if (rs.in_progress) {
                    reconHtml = '<span class="recon-badge recon-progress">⟳ In Progress</span>';
                } else if (rs.failure_count > 0) {
                    reconHtml = `<span class="recon-badge recon-fail">✗ ${rs.failure_count} failures</span>`;
                }
            }

            tableHtml += `
                <tr>
                    <td class="mono truncate" title="${wid}">${name}</td>
                    <td><span class="status-badge status-${status}">${status}</span></td>
                    <td>${instanceType}</td>
                    <td>${region}</td>
                    <td class="mono">${ip}</td>
                    <td>${reconHtml}</td>
                </tr>`;
        }

        tableHtml += '</tbody></table>';

        content.innerHTML = summaryHtml + tableHtml + `<div class="last-update">Updated: ${new Date().toLocaleTimeString()}</div>`;
    }

    renderError(message) {
        const content = this.shadowRoot.getElementById('content');
        content.innerHTML = `<div class="error">Failed to load fleet data: ${message}</div>`;
    }
}

customElements.define('fleet-overview', FleetOverview);
