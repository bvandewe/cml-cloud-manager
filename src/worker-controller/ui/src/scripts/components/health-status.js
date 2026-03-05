/**
 * HealthStatus Web Component
 * Fetches and displays service health and readiness from /api/health and /api/ready endpoints
 */
class HealthStatus extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
        this.refreshInterval = null;
    }

    connectedCallback() {
        this.render();
        this.fetchStatus();
        // Auto-refresh every 30 seconds
        this.refreshInterval = setInterval(() => this.fetchStatus(), 30000);
    }

    disconnectedCallback() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
        }
    }

    async fetchStatus() {
        const [healthResult, readyResult] = await Promise.allSettled([this.fetchEndpoint('/api/health'), this.fetchEndpoint('/api/ready')]);

        this.renderStatus(healthResult.status === 'fulfilled' ? healthResult.value : { error: healthResult.reason?.message || 'Failed' }, readyResult.status === 'fulfilled' ? readyResult.value : { error: readyResult.reason?.message || 'Failed' });
    }

    async fetchEndpoint(url) {
        const response = await fetch(url);
        const data = await response.json();
        return { ...data, status_code: response.status, ok: response.ok };
    }

    render() {
        const themeColor = this.getAttribute('theme-color') || '#667eea';

        this.shadowRoot.innerHTML = `
            <style>
                :host {
                    display: block;
                }
                .status-container {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                    gap: 1.5rem;
                }
                .status-card {
                    background: white;
                    border-radius: 12px;
                    padding: 1.5rem;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                    border-left: 4px solid ${themeColor};
                }
                .status-card.healthy {
                    border-left-color: #22c55e;
                }
                .status-card.unhealthy {
                    border-left-color: #ef4444;
                }
                .status-card.loading {
                    border-left-color: ${themeColor};
                }
                .status-header {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    margin-bottom: 1rem;
                }
                .status-title {
                    font-size: 1.1rem;
                    font-weight: 600;
                    color: #333;
                    display: flex;
                    align-items: center;
                    gap: 0.5rem;
                }
                .status-badge {
                    display: inline-flex;
                    align-items: center;
                    gap: 0.25rem;
                    padding: 0.25rem 0.75rem;
                    border-radius: 9999px;
                    font-size: 0.75rem;
                    font-weight: 600;
                    text-transform: uppercase;
                }
                .status-badge.healthy {
                    background: #dcfce7;
                    color: #15803d;
                }
                .status-badge.unhealthy {
                    background: #fee2e2;
                    color: #dc2626;
                }
                .status-badge.loading {
                    background: #e0e7ff;
                    color: #4338ca;
                }
                .status-details {
                    font-family: 'Monaco', 'Menlo', monospace;
                    font-size: 0.85rem;
                    background: #f8f9fa;
                    border-radius: 8px;
                    padding: 1rem;
                    max-height: 200px;
                    overflow-y: auto;
                }
                .status-details pre {
                    margin: 0;
                    white-space: pre-wrap;
                    word-break: break-all;
                }
                .status-message {
                    color: #6b7280;
                    font-size: 0.9rem;
                    margin-bottom: 0.5rem;
                }
                .refresh-btn {
                    background: none;
                    border: 1px solid #ddd;
                    border-radius: 6px;
                    padding: 0.25rem 0.5rem;
                    cursor: pointer;
                    font-size: 0.8rem;
                    color: #666;
                    transition: all 0.2s;
                }
                .refresh-btn:hover {
                    background: #f3f4f6;
                    border-color: #bbb;
                }
                .spinner {
                    display: inline-block;
                    width: 16px;
                    height: 16px;
                    border: 2px solid #e5e7eb;
                    border-top-color: ${themeColor};
                    border-radius: 50%;
                    animation: spin 1s linear infinite;
                }
                @keyframes spin {
                    to { transform: rotate(360deg); }
                }
                .timestamp {
                    font-size: 0.75rem;
                    color: #9ca3af;
                    margin-top: 0.75rem;
                }
            </style>
            <div class="status-container">
                <div class="status-card loading" id="health-card">
                    <div class="status-header">
                        <span class="status-title">❤️ Health Check</span>
                        <span class="status-badge loading"><span class="spinner"></span> Loading</span>
                    </div>
                    <div class="status-message">Fetching /api/health...</div>
                </div>
                <div class="status-card loading" id="ready-card">
                    <div class="status-header">
                        <span class="status-title">✅ Readiness Check</span>
                        <span class="status-badge loading"><span class="spinner"></span> Loading</span>
                    </div>
                    <div class="status-message">Fetching /api/ready...</div>
                </div>
            </div>
        `;
    }

    renderStatus(health, ready) {
        const healthCard = this.shadowRoot.getElementById('health-card');
        const readyCard = this.shadowRoot.getElementById('ready-card');

        healthCard.outerHTML = this.renderCard('Health Check', '❤️', '/api/health', health);
        readyCard.outerHTML = this.renderCard('Readiness Check', '✅', '/api/ready', ready);
    }

    renderCard(title, emoji, endpoint, data) {
        const isHealthy = data.ok !== false && !data.error;
        const statusClass = isHealthy ? 'healthy' : 'unhealthy';
        const statusText = isHealthy ? 'Healthy' : 'Unhealthy';
        const statusIcon = isHealthy ? '●' : '●';

        // Format the response data
        const displayData = data.error ? { error: data.error } : { ...data };
        delete displayData.ok;
        delete displayData.status_code;

        return `
            <div class="status-card ${statusClass}">
                <div class="status-header">
                    <span class="status-title">${emoji} ${title}</span>
                    <span class="status-badge ${statusClass}">${statusIcon} ${statusText}</span>
                </div>
                <div class="status-message">${endpoint} → HTTP ${data.status_code || 'ERR'}</div>
                <div class="status-details">
                    <pre>${JSON.stringify(displayData, null, 2)}</pre>
                </div>
                <div class="timestamp">Last updated: ${new Date().toLocaleTimeString()}</div>
            </div>
        `;
    }
}

customElements.define('health-status', HealthStatus);
