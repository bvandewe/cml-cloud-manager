/**
 * InfoCard Web Component
 * Fetches and displays service info from /api/info endpoint
 * Also updates the header version badge
 */
class InfoCard extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
    }

    static get observedAttributes() {
        return ['theme-color'];
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
            this.updateHeaderBadge(data);
        } catch (error) {
            this.renderError(error.message);
        }
    }

    updateHeaderBadge(data) {
        // Update the version badge in the header
        const imageTag = data.image_tag || data.version || 'unknown';
        const versionBadge = document.getElementById('version-badge');
        if (versionBadge) {
            versionBadge.textContent = imageTag;
        }
    }

    render() {
        const themeColor = this.getAttribute('theme-color') || '#667eea';

        this.shadowRoot.innerHTML = `
            <style>
                :host {
                    display: block;
                }
                .info-card {
                    background: white;
                    border-radius: 12px;
                    padding: 1.25rem;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                    border-left: 4px solid ${themeColor};
                }
                .info-header {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    margin-bottom: 1rem;
                }
                .info-title {
                    font-size: 1rem;
                    font-weight: 600;
                    color: #333;
                }
                .info-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                    gap: 0.75rem;
                }
                .info-item {
                    padding: 0.75rem;
                    background: #f8f9fa;
                    border-radius: 8px;
                }
                .info-label {
                    font-size: 0.7rem;
                    text-transform: uppercase;
                    color: #6c757d;
                    margin-bottom: 0.25rem;
                    letter-spacing: 0.5px;
                }
                .info-value {
                    font-size: 0.9rem;
                    font-weight: 500;
                    color: #212529;
                    word-break: break-all;
                }
                .info-value.monospace {
                    font-family: 'Monaco', 'Menlo', monospace;
                    font-size: 0.8rem;
                }
                .tag-badge {
                    display: inline-block;
                    padding: 0.2rem 0.5rem;
                    font-size: 0.75rem;
                    font-weight: 600;
                    border-radius: 4px;
                    background: ${themeColor};
                    color: white;
                }
                .leader-badge {
                    display: inline-flex;
                    align-items: center;
                    gap: 0.25rem;
                    padding: 0.2rem 0.5rem;
                    font-size: 0.75rem;
                    font-weight: 600;
                    border-radius: 4px;
                }
                .leader-badge.yes {
                    background: #dcfce7;
                    color: #15803d;
                }
                .leader-badge.no {
                    background: #f3f4f6;
                    color: #6b7280;
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
                .section-title {
                    font-size: 0.75rem;
                    font-weight: 600;
                    color: #6b7280;
                    text-transform: uppercase;
                    margin-top: 1rem;
                    margin-bottom: 0.5rem;
                    letter-spacing: 0.5px;
                }
            </style>
            <div class="info-card">
                <div class="info-header">
                    <div class="info-title">📊 Service Information</div>
                </div>
                <div class="info-content">
                    <div class="loading">
                        <div class="spinner"></div>
                        <span>Loading service info...</span>
                    </div>
                </div>
            </div>
        `;
    }

    renderInfo(data) {
        const content = this.shadowRoot.querySelector('.info-content');
        const themeColor = this.getAttribute('theme-color') || '#667eea';

        // Extract data
        const name = data.name || 'Unknown';
        const version = data.version || 'N/A';
        const imageTag = data.image_tag || 'latest';
        const description = data.description || '';
        const runtime = data.runtime || {};
        const extra = data.extra || {};
        const build = data.build || {};

        content.innerHTML = `
            <div class="info-grid">
                <div class="info-item">
                    <div class="info-label">Service Name</div>
                    <div class="info-value">${name}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Version</div>
                    <div class="info-value">${version}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Image Tag</div>
                    <div class="info-value"><span class="tag-badge">${imageTag}</span></div>
                </div>
                <div class="info-item">
                    <div class="info-label">Environment</div>
                    <div class="info-value">${runtime.environment || 'N/A'}</div>
                </div>
                ${
                    extra.leader !== undefined
                        ? `
                <div class="info-item">
                    <div class="info-label">Leader Status</div>
                    <div class="info-value">
                        <span class="leader-badge ${extra.leader ? 'yes' : 'no'}">
                            ${extra.leader ? '✓ Leader' : '○ Follower'}
                        </span>
                    </div>
                </div>
                `
                        : ''
                }
                ${
                    extra.instance_id
                        ? `
                <div class="info-item">
                    <div class="info-label">Instance ID</div>
                    <div class="info-value monospace">${extra.instance_id.substring(0, 16)}...</div>
                </div>
                `
                        : ''
                }
            </div>

            <div class="section-title">Runtime</div>
            <div class="info-grid">
                <div class="info-item">
                    <div class="info-label">Hostname</div>
                    <div class="info-value monospace">${runtime.hostname || 'N/A'}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Python Version</div>
                    <div class="info-value">${runtime.python_version || 'N/A'}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Uptime</div>
                    <div class="info-value">${this.formatUptime(runtime.uptime_seconds)}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Started</div>
                    <div class="info-value">${runtime.start_time ? new Date(runtime.start_time).toLocaleString() : 'N/A'}</div>
                </div>
            </div>
        `;
    }

    formatUptime(seconds) {
        if (!seconds) return 'N/A';

        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = Math.floor(seconds % 60);

        if (hours > 0) {
            return `${hours}h ${minutes}m ${secs}s`;
        } else if (minutes > 0) {
            return `${minutes}m ${secs}s`;
        }
        return `${secs}s`;
    }

    renderError(message) {
        const content = this.shadowRoot.querySelector('.info-content');
        content.innerHTML = `<div class="error">Failed to load service info: ${message}</div>`;
    }
}

customElements.define('info-card', InfoCard);
