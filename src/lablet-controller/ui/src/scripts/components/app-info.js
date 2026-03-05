/**
 * App Info Web Component
 * Fetches and displays service information from /api/info endpoint
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
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
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
                    background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
                    border-radius: 12px;
                    padding: 1.5rem;
                    border: 1px solid #dee2e6;
                }
                .info-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                    gap: 1rem;
                }
                .info-item {
                    background: white;
                    padding: 1rem;
                    border-radius: 8px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.05);
                }
                .info-label {
                    font-size: 0.75rem;
                    color: #6c757d;
                    text-transform: uppercase;
                    letter-spacing: 0.05em;
                    margin-bottom: 0.25rem;
                }
                .info-value {
                    font-size: 1rem;
                    font-weight: 600;
                    color: #212529;
                    word-break: break-all;
                }
                .info-value.version {
                    color: #2ecc71;
                }
                .loading {
                    text-align: center;
                    padding: 2rem;
                    color: #6c757d;
                }
                .error {
                    background: #fee2e2;
                    color: #dc2626;
                    padding: 1rem;
                    border-radius: 8px;
                    text-align: center;
                }
                .spinner {
                    width: 2rem;
                    height: 2rem;
                    border: 3px solid #e9ecef;
                    border-top-color: #2ecc71;
                    border-radius: 50%;
                    animation: spin 1s linear infinite;
                }
                @keyframes spin {
                    to { transform: rotate(360deg); }
                }
            </style>
            <div class="info-card">
                <div class="loading">
                    <div class="spinner" style="margin: 0 auto 1rem;"></div>
                    Loading service info...
                </div>
            </div>
        `;
    }

    renderInfo(data) {
        const card = this.shadowRoot.querySelector('.info-card');
        card.innerHTML = `
            <div class="info-grid">
                <div class="info-item">
                    <div class="info-label">Service Name</div>
                    <div class="info-value">${data.name || 'N/A'}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Version</div>
                    <div class="info-value version">${data.version || 'N/A'}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Description</div>
                    <div class="info-value">${data.description || 'N/A'}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Environment</div>
                    <div class="info-value">${data.environment || 'N/A'}</div>
                </div>
                ${
                    data.uptime
                        ? `
                <div class="info-item">
                    <div class="info-label">Uptime</div>
                    <div class="info-value">${data.uptime}</div>
                </div>
                `
                        : ''
                }
                ${
                    data.started_at
                        ? `
                <div class="info-item">
                    <div class="info-label">Started At</div>
                    <div class="info-value">${new Date(data.started_at).toLocaleString()}</div>
                </div>
                `
                        : ''
                }
            </div>
        `;
    }

    renderError(message) {
        const card = this.shadowRoot.querySelector('.info-card');
        card.innerHTML = `
            <div class="error">
                <strong>Failed to load service info:</strong> ${message}
            </div>
        `;
    }
}

customElements.define('app-info', AppInfo);
