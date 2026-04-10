/**
 * SchedulingOverview Web Component
 * Fetches and displays scheduling data from /admin/scheduling-overview endpoint.
 * Shows pending/scheduled sessions, retry counts, and capacity cache info.
 */
class SchedulingOverview extends HTMLElement {
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
            const response = await fetch('/api/admin/scheduling-overview');
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            this.renderData(data);
        } catch (error) {
            this.renderError(error.message);
        }
    }

    render() {
        const themeColor = this.getAttribute('theme-color') || '#667eea';

        this.shadowRoot.innerHTML = `
            <style>
                :host { display: block; }
                .sched-card {
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
                .summary-bar { display: flex; gap: 0.75rem; flex-wrap: wrap; margin-bottom: 1rem; }
                .summary-badge {
                    display: inline-flex; align-items: center; gap: 0.25rem;
                    padding: 0.3rem 0.6rem; border-radius: 20px;
                    font-size: 0.75rem; font-weight: 600;
                }
                .summary-badge.pending { background: #dbeafe; color: #1d4ed8; }
                .summary-badge.scheduled { background: #ede9fe; color: #6d28d9; }
                .summary-badge.retries { background: #fef3c7; color: #92400e; }
                .summary-badge.maxed { background: #fee2e2; color: #dc2626; }
                .summary-badge.capacity { background: #dcfce7; color: #15803d; }
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
                .status-pending { background: #dbeafe; color: #1d4ed8; }
                .status-scheduled { background: #ede9fe; color: #6d28d9; }
                .mono { font-family: 'Monaco', 'Menlo', monospace; font-size: 0.75rem; }
                .truncate { max-width: 100px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
                .retry-badge {
                    display: inline-block; padding: 0.1rem 0.4rem;
                    border-radius: 4px; font-size: 0.65rem; font-weight: 500;
                }
                .retry-ok { background: #dcfce7; color: #15803d; }
                .retry-warn { background: #fef3c7; color: #92400e; }
                .retry-max { background: #fee2e2; color: #dc2626; }
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
                .empty { color: #6c757d; font-style: italic; padding: 1.5rem; text-align: center; }
                .last-update { font-size: 0.7rem; color: #6c757d; text-align: right; margin-top: 0.75rem; }
            </style>
            <div class="sched-card">
                <div class="card-header">
                    <span class="card-title">📅 Scheduling Overview</span>
                </div>
                <div id="content">
                    <div class="loading"><div class="spinner"></div><span>Loading scheduling data...</span></div>
                </div>
            </div>
        `;
    }

    renderData(data) {
        const content = this.shadowRoot.getElementById('content');
        const pending = data.pending_sessions || { total: 0, sessions: [] };
        const scheduled = data.scheduled_sessions || { total: 0, sessions: [] };
        const retries = data.retry_counts || {};
        const capacity = data.capacity_cache || {};

        let html = '';

        // Summary badges
        html += `<div class="summary-bar">
            <span class="summary-badge pending">⏳ Pending: ${pending.total}</span>
            <span class="summary-badge scheduled">📋 Scheduled: ${scheduled.total}</span>
            <span class="summary-badge retries">🔄 Retries Tracked: ${retries.total_tracked || 0}</span>
            <span class="summary-badge maxed">⚠ At Max: ${retries.sessions_at_max || 0}</span>
            <span class="summary-badge capacity">📊 Capacity Entries: ${capacity.total_cached || 0}</span>
        </div>`;

        // Pending Sessions Table
        html += '<div class="section-title">Pending Sessions</div>';
        if (pending.sessions.length === 0) {
            html += '<div class="empty">No pending sessions — all sessions are placed</div>';
        } else {
            html += this.renderSessionTable(pending.sessions, 'pending', retries.retries || {});
        }

        // Scheduled Sessions Table
        html += '<div class="section-title">Scheduled Sessions (Awaiting Instantiation)</div>';
        if (scheduled.sessions.length === 0) {
            html += '<div class="empty">No scheduled sessions</div>';
        } else {
            html += this.renderSessionTable(scheduled.sessions, 'scheduled', retries.retries || {});
        }

        html += `<div class="last-update">Updated: ${new Date().toLocaleTimeString()}</div>`;
        content.innerHTML = html;
    }

    renderSessionTable(sessions, statusType, retries) {
        let html = `
            <table>
                <thead>
                    <tr>
                        <th>Session ID</th>
                        <th>Status</th>
                        <th>Definition</th>
                        <th>Worker</th>
                        <th>Retries</th>
                    </tr>
                </thead>
                <tbody>`;

        const displaySessions = sessions.slice(0, 30);
        for (const s of displaySessions) {
            const sid = s.id || s.session_id || '';
            const status = s.status || statusType;
            const defName = s.definition_name || s.definition_id?.substring(0, 12) || '—';
            const workerId = s.worker_id ? s.worker_id.substring(0, 12) + '…' : '—';
            const retryCount = retries[sid] || 0;

            let retryHtml;
            if (retryCount === 0) {
                retryHtml = '<span class="retry-badge retry-ok">0</span>';
            } else if (retryCount >= 5) {
                retryHtml = `<span class="retry-badge retry-max">${retryCount} (max)</span>`;
            } else {
                retryHtml = `<span class="retry-badge retry-warn">${retryCount}</span>`;
            }

            html += `
                <tr>
                    <td class="mono truncate" title="${sid}">${sid.substring(0, 12)}…</td>
                    <td><span class="status-badge status-${status}">${status}</span></td>
                    <td class="truncate" title="${defName}">${defName}</td>
                    <td class="mono">${workerId}</td>
                    <td>${retryHtml}</td>
                </tr>`;
        }

        if (sessions.length > 30) {
            html += `<tr><td colspan="5" style="text-align:center;color:#6b7280;font-style:italic">… and ${sessions.length - 30} more</td></tr>`;
        }

        html += '</tbody></table>';
        return html;
    }

    renderError(message) {
        const content = this.shadowRoot.getElementById('content');
        content.innerHTML = `<div class="error">Failed to load scheduling data: ${message}</div>`;
    }
}

customElements.define('scheduling-overview', SchedulingOverview);
