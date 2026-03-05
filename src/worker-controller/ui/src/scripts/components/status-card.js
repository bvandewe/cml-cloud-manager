/**
 * StatusCard Web Component
 * Displays health or ready status from /api/health or /api/ready endpoints
 */
class StatusCard extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
        this.refreshInterval = null;
    }

    static get observedAttributes() {
        return ['endpoint', 'title', 'theme-color', 'refresh-interval'];
    }

    connectedCallback() {
        this.render();
        this.fetchStatus();

        // Auto-refresh (default: 30 seconds)
        const interval = parseInt(this.getAttribute('refresh-interval') || '30000', 10);
        if (interval > 0) {
            this.refreshInterval = setInterval(() => this.fetchStatus(), interval);
        }
    }

    disconnectedCallback() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
        }
    }

    async fetchStatus() {
        const endpoint = this.getAttribute('endpoint') || '/api/health';
        const container = this.shadowRoot.querySelector('.status-content');

        try {
            const response = await fetch(endpoint);
            const data = await response.json();
            this.renderStatus(data, response.status, response.ok);
        } catch (error) {
            this.renderError(error.message);
        }
    }

    render() {
        const themeColor = this.getAttribute('theme-color') || '#667eea';
        const title = this.getAttribute('title') || 'Status';

        this.shadowRoot.innerHTML = `
            <style>
                :host {
                    display: block;
                }
                .status-card {
                    background: white;
                    border-radius: 12px;
                    padding: 1.25rem;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                    border-left: 4px solid ${themeColor};
                    transition: border-color 0.3s ease;
                }
                .status-card.healthy {
                    border-left-color: #22c55e;
                }
                .status-card.unhealthy {
                    border-left-color: #ef4444;
                }
                .status-header {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    margin-bottom: 1rem;
                }
                .status-title {
                    font-size: 1rem;
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
                    background: #e5e7eb;
                    color: #6b7280;
                }
                .status-content {
                    margin-top: 0.75rem;
                }
                .status-item {
                    display: flex;
                    justify-content: space-between;
                    padding: 0.5rem 0;
                    border-bottom: 1px solid #f3f4f6;
                }
                .status-item:last-child {
                    border-bottom: none;
                }
                .status-label {
                    font-size: 0.8rem;
                    color: #6b7280;
                }
                .status-value {
                    font-size: 0.8rem;
                    font-weight: 500;
                    color: #111827;
                    font-family: 'Monaco', 'Menlo', monospace;
                }
                .loading-spinner {
                    display: flex;
                    align-items: center;
                    gap: 0.5rem;
                    color: #6b7280;
                    font-size: 0.85rem;
                }
                .spinner {
                    width: 16px;
                    height: 16px;
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
                    font-size: 0.85rem;
                }
                .http-code {
                    font-size: 0.7rem;
                    padding: 0.15rem 0.4rem;
                    background: #f3f4f6;
                    border-radius: 4px;
                    font-family: monospace;
                }
            </style>
            <div class="status-card">
                <div class="status-header">
                    <div class="status-title">${title}</div>
                    <span class="status-badge loading">Loading...</span>
                </div>
                <div class="status-content">
                    <div class="loading-spinner">
                        <div class="spinner"></div>
                        <span>Fetching status...</span>
                    </div>
                </div>
            </div>
        `;
    }

    renderStatus(data, statusCode, isOk) {
        const card = this.shadowRoot.querySelector('.status-card');
        const badge = this.shadowRoot.querySelector('.status-badge');
        const content = this.shadowRoot.querySelector('.status-content');

        // Determine health status
        const isHealthy = isOk && (data.status === 'healthy' || data.status === 'ready');

        // Update card class
        card.classList.remove('healthy', 'unhealthy');
        card.classList.add(isHealthy ? 'healthy' : 'unhealthy');

        // Update badge
        badge.classList.remove('healthy', 'unhealthy', 'loading');
        badge.classList.add(isHealthy ? 'healthy' : 'unhealthy');
        badge.innerHTML = `
            <span>${isHealthy ? '●' : '○'}</span>
            <span>${data.status || (isHealthy ? 'OK' : 'Error')}</span>
        `;

        // Render content
        content.innerHTML = `
            <div class="status-item">
                <span class="status-label">HTTP Status</span>
                <span class="status-value"><span class="http-code">${statusCode}</span></span>
            </div>
            ${
                data.message
                    ? `
                <div class="status-item">
                    <span class="status-label">Message</span>
                    <span class="status-value">${data.message}</span>
                </div>
            `
                    : ''
            }
            ${
                data.timestamp
                    ? `
                <div class="status-item">
                    <span class="status-label">Timestamp</span>
                    <span class="status-value">${new Date(data.timestamp).toLocaleTimeString()}</span>
                </div>
            `
                    : ''
            }
        `;
    }

    renderError(message) {
        const card = this.shadowRoot.querySelector('.status-card');
        const badge = this.shadowRoot.querySelector('.status-badge');
        const content = this.shadowRoot.querySelector('.status-content');

        card.classList.remove('healthy');
        card.classList.add('unhealthy');

        badge.classList.remove('healthy', 'loading');
        badge.classList.add('unhealthy');
        badge.innerHTML = `<span>○</span><span>Error</span>`;

        content.innerHTML = `<div class="error">Failed to fetch: ${message}</div>`;
    }
}

customElements.define('status-card', StatusCard);
