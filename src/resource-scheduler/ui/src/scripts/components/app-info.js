/**
 * AppInfo Web Component
 * Fetches and displays service info from /api/info endpoint
 */
class AppInfo extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
    }

    connectedCallback() {
        this.render();
        this.fetchInfo();
    }

    async fetchInfo() {
        try {
            const response = await fetch('/api/info');
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const data = await response.json();
            this.renderInfo(data);
        } catch (error) {
            this.renderError(error.message);
        }
    }

    render() {
        this.shadowRoot.innerHTML = `
            <style>
                :host {
                    display: block;
                }
                .info-card {
                    background: white;
                    border-radius: 8px;
                    padding: 1.5rem;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                }
                .info-title {
                    font-size: 1.25rem;
                    font-weight: 600;
                    margin-bottom: 1rem;
                    color: #333;
                }
                .info-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                    gap: 1rem;
                }
                .info-item {
                    padding: 0.75rem;
                    background: #f8f9fa;
                    border-radius: 6px;
                }
                .info-label {
                    font-size: 0.75rem;
                    text-transform: uppercase;
                    color: #6c757d;
                    margin-bottom: 0.25rem;
                }
                .info-value {
                    font-size: 1rem;
                    font-weight: 500;
                    color: #212529;
                }
                .loading {
                    display: flex;
                    align-items: center;
                    gap: 0.5rem;
                    color: #6c757d;
                }
                .spinner {
                    width: 20px;
                    height: 20px;
                    border: 2px solid #e9ecef;
                    border-top-color: #667eea;
                    border-radius: 50%;
                    animation: spin 1s linear infinite;
                }
                @keyframes spin {
                    to { transform: rotate(360deg); }
                }
                .error {
                    color: #dc3545;
                    padding: 1rem;
                    background: #f8d7da;
                    border-radius: 6px;
                }
                .badge {
                    display: inline-block;
                    padding: 0.25rem 0.5rem;
                    font-size: 0.75rem;
                    font-weight: 600;
                    border-radius: 4px;
                    background: #667eea;
                    color: white;
                }
            </style>
            <div class="info-card">
                <div class="info-title">📊 Service Information</div>
                <div class="loading">
                    <div class="spinner"></div>
                    <span>Loading service info...</span>
                </div>
            </div>
        `;
    }

    renderInfo(data) {
        const infoCard = this.shadowRoot.querySelector('.info-card');
        infoCard.innerHTML = `
            <div class="info-title">📊 Service Information</div>
            <div class="info-grid">
                <div class="info-item">
                    <div class="info-label">Service Name</div>
                    <div class="info-value">${data.service?.name || data.name || 'N/A'}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Version</div>
                    <div class="info-value">${data.service?.version || data.version || 'N/A'}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Status</div>
                    <div class="info-value"><span class="badge">${data.status || 'running'}</span></div>
                </div>
                <div class="info-item">
                    <div class="info-label">Timestamp</div>
                    <div class="info-value">${data.timestamp ? new Date(data.timestamp).toLocaleString() : new Date().toLocaleString()}</div>
                </div>
                ${
                    data.leader !== undefined
                        ? `
                <div class="info-item">
                    <div class="info-label">Leader</div>
                    <div class="info-value">${data.leader ? '✅ Yes' : '❌ No'}</div>
                </div>
                `
                        : ''
                }
                ${
                    data.instance_id
                        ? `
                <div class="info-item">
                    <div class="info-label">Instance ID</div>
                    <div class="info-value" style="font-size: 0.85rem; word-break: break-all;">${data.instance_id}</div>
                </div>
                `
                        : ''
                }
            </div>
        `;
    }

    renderError(message) {
        const infoCard = this.shadowRoot.querySelector('.info-card');
        infoCard.innerHTML = `
            <div class="info-title">📊 Service Information</div>
            <div class="error">
                <strong>Error:</strong> ${message}
            </div>
        `;
    }
}

customElements.define('app-info', AppInfo);
