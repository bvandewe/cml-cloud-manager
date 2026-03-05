/**
 * ServiceLinks Web Component
 * Displays quick links to service endpoints
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
        const themeColor = this.getAttribute('theme-color') || '#667eea';

        this.shadowRoot.innerHTML = `
            <style>
                :host {
                    display: block;
                }
                .links-card {
                    background: white;
                    border-radius: 8px;
                    padding: 1.5rem;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                }
                .links-title {
                    font-size: 1.25rem;
                    font-weight: 600;
                    margin-bottom: 1rem;
                    color: #333;
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
                    border: none;
                    border-radius: 6px;
                    font-size: 0.9rem;
                    font-weight: 500;
                    text-decoration: none;
                    cursor: pointer;
                    transition: all 0.2s ease;
                }
                .link-btn.primary {
                    background: ${themeColor};
                    color: white;
                }
                .link-btn.primary:hover {
                    filter: brightness(1.1);
                    transform: translateY(-1px);
                }
                .link-btn.secondary {
                    background: #f8f9fa;
                    color: #495057;
                    border: 1px solid #dee2e6;
                }
                .link-btn.secondary:hover {
                    background: #e9ecef;
                    transform: translateY(-1px);
                }
                .emoji {
                    font-size: 1.1rem;
                }
            </style>
            <div class="links-card">
                <div class="links-title">🔗 Quick Links</div>
                <div class="links-grid">
                    <a href="/api/docs" class="link-btn primary">
                        <span class="emoji">📚</span>
                        <span>API Docs</span>
                    </a>
                    <a href="/api/info" class="link-btn secondary" target="_blank">
                        <span class="emoji">ℹ️</span>
                        <span>Info</span>
                    </a>
                </div>
            </div>
        `;
    }
}

customElements.define('service-links', ServiceLinks);
