/**
 * LeaderCard Web Component
 * Fetches and displays leader election info and stats from /api/info endpoint
 * Shows leadership status, instance info, and reconciliation statistics
 */
class LeaderCard extends HTMLElement {
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
        this.fetchInfo();

        // Set up auto-refresh
        const interval = parseInt(this.getAttribute('refresh-interval')) || 30000;
        this.refreshInterval = setInterval(() => this.fetchInfo(), interval);
    }

    disconnectedCallback() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
        }
    }

    async fetchInfo() {
        try {
            const response = await fetch('/api/info');
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const data = await response.json();
            this.renderLeaderInfo(data);
        } catch (error) {
            this.renderError(error.message);
        }
    }

    render() {
        const themeColor = this.getAttribute('theme-color') || '#667eea';

        this.shadowRoot.innerHTML = `
            <style>
                :host {
                    display: block;
                    margin-top: 1rem;
                }
                .leader-card {
                    background: white;
                    border-radius: 12px;
                    padding: 1.25rem;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                    border-left: 4px solid ${themeColor};
                }
                .card-header {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    margin-bottom: 1rem;
                }
                .card-title {
                    font-size: 1rem;
                    font-weight: 600;
                    color: #333;
                    display: flex;
                    align-items: center;
                    gap: 0.5rem;
                }
                .leader-badge {
                    display: inline-flex;
                    align-items: center;
                    gap: 0.25rem;
                    padding: 0.25rem 0.6rem;
                    font-size: 0.75rem;
                    font-weight: 600;
                    border-radius: 20px;
                }
                .leader-badge.leader {
                    background: linear-gradient(135deg, #fbbf24, #f59e0b);
                    color: #78350f;
                }
                .leader-badge.follower {
                    background: #e5e7eb;
                    color: #4b5563;
                }
                .leader-badge.running {
                    background: #dcfce7;
                    color: #15803d;
                }
                .leader-badge.stopped {
                    background: #fee2e2;
                    color: #dc2626;
                }
                .stats-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
                    gap: 0.75rem;
                }
                .stat-item {
                    padding: 0.75rem;
                    background: #f8f9fa;
                    border-radius: 8px;
                    text-align: center;
                }
                .stat-value {
                    font-size: 1.5rem;
                    font-weight: 700;
                    color: #212529;
                }
                .stat-value.success {
                    color: #15803d;
                }
                .stat-value.error {
                    color: #dc2626;
                }
                .stat-value.pending {
                    color: #f59e0b;
                }
                .stat-value.info {
                    color: ${themeColor};
                }
                .stat-label {
                    font-size: 0.7rem;
                    text-transform: uppercase;
                    color: #6c757d;
                    letter-spacing: 0.5px;
                    margin-top: 0.25rem;
                }
                .instance-info {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 1rem;
                    margin-bottom: 1rem;
                    padding: 0.75rem;
                    background: #f8f9fa;
                    border-radius: 8px;
                }
                .instance-item {
                    flex: 1;
                    min-width: 200px;
                }
                .instance-label {
                    font-size: 0.7rem;
                    text-transform: uppercase;
                    color: #6c757d;
                    letter-spacing: 0.5px;
                }
                .instance-value {
                    font-size: 0.85rem;
                    font-family: 'Monaco', 'Menlo', monospace;
                    color: #212529;
                    word-break: break-all;
                }
                .section-title {
                    font-size: 0.75rem;
                    font-weight: 600;
                    text-transform: uppercase;
                    color: #6c757d;
                    letter-spacing: 0.5px;
                    margin: 1rem 0 0.5rem 0;
                    padding-bottom: 0.25rem;
                    border-bottom: 1px solid #e9ecef;
                }
                .loading {
                    display: flex;
                    align-items: center;
                    gap: 0.5rem;
                    color: #6c757d;
                    padding: 1rem 0;
                }
                .spinner {
                    width: 18px;
                    height: 18px;
                    border: 2px solid #e9ecef;
                    border-top-color: ${themeColor};
                    border-radius: 50%;
                    animation: spin 1s linear infinite;
                }
                @keyframes spin {
                    to { transform: rotate(360deg); }
                }
                .error {
                    color: #dc3545;
                    padding: 0.75rem;
                    background: #fee2e2;
                    border-radius: 8px;
                    font-size: 0.85rem;
                }
                .last-update {
                    font-size: 0.7rem;
                    color: #6c757d;
                    text-align: right;
                    margin-top: 0.75rem;
                }
                .no-leader-data {
                    color: #6c757d;
                    font-style: italic;
                    padding: 1rem;
                    text-align: center;
                }
            </style>
            <div class="leader-card">
                <div class="card-header">
                    <span class="card-title">👑 Leader Election & Stats</span>
                </div>
                <div id="content">
                    <div class="loading">
                        <div class="spinner"></div>
                        <span>Loading leader info...</span>
                    </div>
                </div>
            </div>
        `;
    }

    renderLeaderInfo(data) {
        const content = this.shadowRoot.getElementById('content');
        const extra = data.extra || {};
        const stats = extra.stats || {};

        // Check if leader data is available
        if (!extra.leader && !extra.instance_id && !Object.keys(stats).length) {
            content.innerHTML = `
                <div class="no-leader-data">
                    No leader election data available for this service.
                </div>
            `;
            return;
        }

        const isLeader = extra.leader === true || stats.is_leader === true;
        const isRunning = stats.running === true;
        const instanceId = extra.instance_id || stats.instance_id || 'N/A';
        const leaderId = extra.leader_id || stats.current_leader_id || 'N/A';
        const serviceName = stats.service_name || data.name || 'Unknown';

        // Format last reconcile time
        let lastReconcileFormatted = 'Never';
        if (stats.last_reconcile_time) {
            const date = new Date(stats.last_reconcile_time * 1000);
            lastReconcileFormatted = date.toLocaleTimeString();
        }

        content.innerHTML = `
            <!-- Status Badges -->
            <div style="display: flex; gap: 0.5rem; margin-bottom: 1rem;">
                <span class="leader-badge ${isLeader ? 'leader' : 'follower'}">
                    ${isLeader ? '👑 Leader' : '👤 Follower'}
                </span>
                <span class="leader-badge ${isRunning ? 'running' : 'stopped'}">
                    ${isRunning ? '🟢 Running' : '🔴 Stopped'}
                </span>
            </div>

            <!-- Instance Info -->
            <div class="instance-info">
                <div class="instance-item">
                    <div class="instance-label">Instance ID</div>
                    <div class="instance-value">${instanceId}</div>
                </div>
                <div class="instance-item">
                    <div class="instance-label">Current Leader</div>
                    <div class="instance-value">${leaderId}</div>
                </div>
            </div>

            <!-- Statistics Section -->
            <div class="section-title">Reconciliation Statistics</div>
            <div class="stats-grid">
                <div class="stat-item">
                    <div class="stat-value success">${stats.total_reconciled || 0}</div>
                    <div class="stat-label">Reconciled</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value error">${stats.total_failed || 0}</div>
                    <div class="stat-label">Failed</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value pending">${stats.pending_retries || 0}</div>
                    <div class="stat-label">Pending</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value info">${stats.in_progress || 0}</div>
                    <div class="stat-label">In Progress</div>
                </div>
            </div>

            ${this.renderServiceSpecificStats(stats)}

            <div class="last-update">
                Last reconcile: ${lastReconcileFormatted}
            </div>
        `;
    }

    renderServiceSpecificStats(stats) {
        // Check for service-specific statistics
        const hasPlacementStats = stats.successful_placements !== undefined || stats.failed_placements !== undefined || stats.scale_up_requests !== undefined;

        if (!hasPlacementStats) {
            return '';
        }

        return `
            <div class="section-title">Placement Statistics</div>
            <div class="stats-grid">
                <div class="stat-item">
                    <div class="stat-value success">${stats.successful_placements || 0}</div>
                    <div class="stat-label">Successful</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value error">${stats.failed_placements || 0}</div>
                    <div class="stat-label">Failed</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value info">${stats.scale_up_requests || 0}</div>
                    <div class="stat-label">Scale Up</div>
                </div>
            </div>
        `;
    }

    renderError(message) {
        const content = this.shadowRoot.getElementById('content');
        content.innerHTML = `
            <div class="error">
                <strong>Error:</strong> ${message}
            </div>
        `;
    }
}

customElements.define('leader-card', LeaderCard);
