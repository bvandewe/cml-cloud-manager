/**
 * Service Links Web Component
 * Displays quick navigation links to service endpoints
 */
class ServiceLinks extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
    }

    connectedCallback() {
        this.render();
    }

    render() {
        this.shadowRoot.innerHTML = `
            <style>
                :host {
                    display: block;
                }
                .links-card {
                    background: white;
                    border-radius: 12px;
                    padding: 1.5rem;
                    border: 1px solid #dee2e6;
                }
                .links-title {
                    font-size: 1.1rem;
                    font-weight: 600;
                    color: #212529;
                    margin-bottom: 1rem;
                }
                .links-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                    gap: 0.75rem;
                }
                .link-btn {
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 0.5rem;
                    padding: 0.75rem 1rem;
                    background: linear-gradient(135deg, #2ecc71 0%, #27ae60 100%);
                    color: white;
                    text-decoration: none;
                    border-radius: 8px;
                    font-weight: 500;
                    transition: all 0.2s ease;
                    box-shadow: 0 2px 4px rgba(46, 204, 113, 0.2);
                }
                .link-btn:hover {
                    transform: translateY(-2px);
                    box-shadow: 0 4px 8px rgba(46, 204, 113, 0.3);
                }
                .link-btn.secondary {
                    background: linear-gradient(135deg, #6c757d 0%, #495057 100%);
                    box-shadow: 0 2px 4px rgba(108, 117, 125, 0.2);
                }
                .link-btn.secondary:hover {
                    box-shadow: 0 4px 8px rgba(108, 117, 125, 0.3);
                }
                .link-icon {
                    font-size: 1.1rem;
                }
            </style>
            <div class="links-card">
                <div class="links-title">🔗 Quick Links</div>
                <div class="links-grid">
                    <a href="/api/docs" class="link-btn" target="_blank">
                        <span class="link-icon">📚</span>
                        <span>API Docs</span>
                    </a>
                    <a href="/api/info" class="link-btn secondary" target="_blank">
                        <span class="link-icon">ℹ️</span>
                        <span>Info</span>
                    </a>
                </div>
            </div>
        `;
    }
}

customElements.define('service-links', ServiceLinks);
