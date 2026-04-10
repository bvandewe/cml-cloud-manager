/**
 * SessionsOverview Web Component
 * Fetches and displays lablet sessions from /admin/sessions-overview endpoint.
 * Shows session table with pipeline handler states and status badges.
 */
class SessionsOverview extends HTMLElement {
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
            const response = await fetch('/api/admin/sessions-overview');
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
                .sessions-card {
                    background: white; border-radius: 12px; padding: 1.25rem;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                    border-left: 4px solid ${themeColor};
                }
                .card-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; }
                .card-title { font-size: 1rem; font-weight: 600; color: #333; }
                .summary-bar { display: flex; gap: 0.75rem; flex-wrap: wrap; margin-bottom: 1rem; }
                .summary-badge {
                    display: inline-flex; align-items: center; gap: 0.25rem;
                    padding: 0.3rem 0.6rem; border-radius: 20px;
                    font-size: 0.75rem; font-weight: 600;
                }
                .summary-badge.total { background: #e5e7eb; color: #374151; }
                .summary-badge.running { background: #dcfce7; color: #15803d; }
                .summary-badge.pending { background: #dbeafe; color: #1d4ed8; }
                .summary-badge.scheduled { background: #ede9fe; color: #6d28d9; }
                .summary-badge.instantiating { background: #e0f2fe; color: #0369a1; }
                .summary-badge.collecting { background: #fef3c7; color: #92400e; }
                .summary-badge.grading { background: #fce7f3; color: #be185d; }
                .summary-badge.stopping { background: #ffedd5; color: #c2410c; }
                .summary-badge.stopped { background: #f3f4f6; color: #6b7280; }
                .summary-badge.terminated { background: #fee2e2; color: #dc2626; }
                .summary-badge.archived { background: #f3f4f6; color: #6b7280; }
                .summary-badge.other { background: #f3f4f6; color: #6b7280; }
                .summary-badge.handlers { background: #fef3c7; color: #92400e; }
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
                .status-pending { background: #dbeafe; color: #1d4ed8; }
                .status-scheduled { background: #ede9fe; color: #6d28d9; }
                .status-instantiating { background: #e0f2fe; color: #0369a1; }
                .status-collecting { background: #fef3c7; color: #92400e; }
                .status-grading { background: #fce7f3; color: #be185d; }
                .status-stopping { background: #ffedd5; color: #c2410c; }
                .status-stopped { background: #f3f4f6; color: #6b7280; }
                .status-terminated { background: #fee2e2; color: #dc2626; }
                .status-archived { background: #f3f4f6; color: #6b7280; }
                .status-expired { background: #fee2e2; color: #dc2626; }
                .status-unknown { background: #f3f4f6; color: #6b7280; }
                .pipeline-badge {
                    display: inline-block; padding: 0.1rem 0.4rem;
                    border-radius: 4px; font-size: 0.65rem; font-weight: 500;
                }
                .pipeline-running { background: #dbeafe; color: #1d4ed8; }
                .pipeline-completed { background: #dcfce7; color: #15803d; }
                .pipeline-failed { background: #fee2e2; color: #dc2626; }
                .pipeline-crashed { background: #fee2e2; color: #dc2626; }
                .pipeline-pending { background: #f3f4f6; color: #6b7280; }
                .mono { font-family: 'Monaco', 'Menlo', monospace; font-size: 0.75rem; }
                .truncate { max-width: 100px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
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
            <div class="sessions-card">
                <div class="card-header">
                    <span class="card-title">🎛️ Lablet Sessions</span>
                </div>
                <div id="content">
                    <div class="loading"><div class="spinner"></div><span>Loading sessions data...</span></div>
                </div>
            </div>
        `;
    }

    renderData(data) {
        const content = this.shadowRoot.getElementById('content');
        const sessions = data.sessions || [];
        const statusCounts = data.status_counts || {};
        const pipelineHandlers = data.pipeline_handlers || {};
        const activeHandlers = data.active_handlers || 0;

        if (sessions.length === 0) {
            content.innerHTML = '<div class="empty">No sessions found</div>';
            return;
        }

        // Summary badges
        const knownStatuses = ['running', 'pending', 'scheduled', 'instantiating', 'collecting', 'grading', 'stopping', 'stopped', 'terminated', 'archived'];
        let summaryHtml = `<div class="summary-bar">
            <span class="summary-badge total">Total: ${data.total || sessions.length}</span>
            <span class="summary-badge handlers">🔧 Active Handlers: ${activeHandlers}</span>`;
        for (const [status, count] of Object.entries(statusCounts)) {
            const cls = knownStatuses.includes(status) ? status : 'other';
            summaryHtml += `<span class="summary-badge ${cls}">${status}: ${count}</span>`;
        }
        summaryHtml += '</div>';

        // Filter to non-terminal sessions first, then terminal
        const activeStatuses = ['pending', 'scheduled', 'instantiating', 'running', 'collecting', 'grading', 'stopping'];
        const sortedSessions = [...sessions].sort((a, b) => {
            const aActive = activeStatuses.includes(a.status) ? 0 : 1;
            const bActive = activeStatuses.includes(b.status) ? 0 : 1;
            return aActive - bActive;
        });

        let tableHtml = `
            <table>
                <thead>
                    <tr>
                        <th>Session ID</th>
                        <th>Status</th>
                        <th>Definition</th>
                        <th>Worker</th>
                        <th>Pipeline</th>
                    </tr>
                </thead>
                <tbody>`;

        // Show max 50 rows
        const displaySessions = sortedSessions.slice(0, 50);
        for (const s of displaySessions) {
            const sid = s.id || s.session_id || '';
            const status = s.status || 'unknown';
            const defName = s.definition_name || s.definition_id?.substring(0, 12) || '—';
            const workerId = s.worker_id ? s.worker_id.substring(0, 12) + '…' : '—';

            // Pipeline handler info
            const handlers = pipelineHandlers[sid] || [];
            let pipelineHtml = '—';
            if (handlers.length > 0) {
                pipelineHtml = handlers
                    .map(h => {
                        const st = h.result_status || 'unknown';
                        const cls = `pipeline-${st}`;
                        return `<span class="pipeline-badge ${cls}">${h.pipeline_name}: ${st}</span>`;
                    })
                    .join(' ');
            }

            tableHtml += `
                <tr>
                    <td class="mono truncate" title="${sid}">${sid.substring(0, 12)}…</td>
                    <td><span class="status-badge status-${status}">${status}</span></td>
                    <td class="truncate" title="${defName}">${defName}</td>
                    <td class="mono">${workerId}</td>
                    <td>${pipelineHtml}</td>
                </tr>`;
        }

        if (sessions.length > 50) {
            tableHtml += `<tr><td colspan="5" style="text-align:center;color:#6b7280;font-style:italic">… and ${sessions.length - 50} more</td></tr>`;
        }

        tableHtml += '</tbody></table>';
        content.innerHTML = summaryHtml + tableHtml + `<div class="last-update">Updated: ${new Date().toLocaleTimeString()}</div>`;
    }

    renderError(message) {
        const content = this.shadowRoot.getElementById('content');
        content.innerHTML = `<div class="error">Failed to load sessions data: ${message}</div>`;
    }
}

customElements.define('sessions-overview', SessionsOverview);
