/**
 * LcmGrafanaPanel - Grafana Panel Embed Web Component
 *
 * Embeds a Grafana panel via iframe with support for time ranges,
 * variables, theming, and responsive sizing.
 *
 * Usage:
 *   <lcm-grafana-panel
 *     grafana-url="http://localhost:3000"
 *     dashboard-uid="worker-metrics"
 *     panel-id="1"
 *     from="now-1h"
 *     to="now"
 *     refresh="30s"
 *     height="300"
 *     variables='{"worker_id":"worker-1"}'
 *   ></lcm-grafana-panel>
 *
 * Attributes:
 *   - grafana-url: Base URL of Grafana instance (default: /grafana)
 *   - dashboard-uid: UID of the dashboard containing the panel
 *   - panel-id: ID of the panel to embed
 *   - from: Start time (default: now-1h)
 *   - to: End time (default: now)
 *   - refresh: Auto-refresh interval (e.g., 5s, 1m, 5m)
 *   - height: Panel height in pixels (default: 300)
 *   - variables: JSON object of Grafana template variables
 *   - theme: light|dark|auto (default: auto - follows page theme)
 *   - kiosk: true to hide panel header (default: true)
 *
 * Events:
 *   - 'panel-load': Fired when iframe loads
 *   - 'panel-error': Fired on load error
 *
 * @module components/core/LcmGrafanaPanel
 */

import { BaseComponent } from '../../core/BaseComponent.js';

export class LcmGrafanaPanel extends BaseComponent {
    static get observedAttributes() {
        return ['grafana-url', 'dashboard-uid', 'panel-id', 'from', 'to', 'refresh', 'height', 'variables', 'theme', 'kiosk', 'org-id'];
    }

    constructor() {
        super();
        this._isLoading = true;
        this._hasError = false;
        this._errorMessage = '';
    }

    onMount() {
        this.render();
        this._setupThemeObserver();
    }

    onUnmount() {
        if (this._themeObserver) {
            this._themeObserver.disconnect();
        }
    }

    onAttributeChange(name, oldValue, newValue) {
        if (oldValue !== newValue) {
            this.render();
        }
    }

    // ==================== Public API ====================

    /**
     * Reload the panel
     */
    reload() {
        const iframe = this.querySelector('iframe');
        if (iframe) {
            iframe.src = this._buildPanelUrl();
        }
    }

    /**
     * Update time range
     * @param {string} from - Start time
     * @param {string} to - End time
     */
    setTimeRange(from, to) {
        this.setAttribute('from', from);
        this.setAttribute('to', to);
    }

    /**
     * Update variables
     * @param {Object} variables - Template variables
     */
    setVariables(variables) {
        this.setAttribute('variables', JSON.stringify(variables));
    }

    // ==================== Private Methods ====================

    _buildPanelUrl() {
        const grafanaUrl = this.getAttribute('grafana-url') || '/grafana';
        const dashboardUid = this.getAttribute('dashboard-uid');
        const panelId = this.getAttribute('panel-id');
        const from = this.getAttribute('from') || 'now-1h';
        const to = this.getAttribute('to') || 'now';
        const refresh = this.getAttribute('refresh');
        const kiosk = this.getAttribute('kiosk') !== 'false';
        const orgId = this.getAttribute('org-id') || '1';

        // Determine theme
        let theme = this.getAttribute('theme') || 'auto';
        if (theme === 'auto') {
            theme = document.documentElement.getAttribute('data-bs-theme') || 'light';
        }

        // Build URL - Grafana embed URL format: /d-solo/{uid}/{slug}?panelId=...
        // The slug can be anything (it's for human readability), we use the UID
        const baseUrl = `${grafanaUrl}/d-solo/${dashboardUid}/${dashboardUid}`;
        const params = new URLSearchParams({
            orgId,
            panelId,
            from,
            to,
            theme,
        });

        if (refresh) {
            params.set('refresh', refresh);
        }

        if (kiosk) {
            params.set('kiosk', '');
        }

        // Add variables (prefixed with var-)
        try {
            const variables = JSON.parse(this.getAttribute('variables') || '{}');
            Object.entries(variables).forEach(([key, value]) => {
                params.set(`var-${key}`, value);
            });
        } catch (e) {
            console.warn('[LcmGrafanaPanel] Invalid variables JSON:', e);
        }

        return `${baseUrl}?${params.toString()}`;
    }

    _setupThemeObserver() {
        // Watch for theme changes on document
        this._themeObserver = new MutationObserver(mutations => {
            mutations.forEach(mutation => {
                if (mutation.type === 'attributes' && mutation.attributeName === 'data-bs-theme') {
                    if (this.getAttribute('theme') === 'auto') {
                        this.render();
                    }
                }
            });
        });

        this._themeObserver.observe(document.documentElement, {
            attributes: true,
            attributeFilter: ['data-bs-theme'],
        });
    }

    _handleLoad() {
        this._isLoading = false;
        this._hasError = false;
        this.dispatchEvent(new CustomEvent('panel-load', { bubbles: true }));
        this._updateLoadingState();
    }

    _handleError() {
        this._isLoading = false;
        this._hasError = true;
        this._errorMessage = 'Failed to load Grafana panel';
        this.dispatchEvent(
            new CustomEvent('panel-error', {
                detail: { message: this._errorMessage },
                bubbles: true,
            })
        );
        this._updateLoadingState();
    }

    _updateLoadingState() {
        const loader = this.querySelector('.lcm-grafana-loader');
        const error = this.querySelector('.lcm-grafana-error');
        const iframe = this.querySelector('iframe');

        if (loader) {
            loader.style.display = this._isLoading ? 'flex' : 'none';
        }
        if (error) {
            error.style.display = this._hasError ? 'flex' : 'none';
        }
        if (iframe) {
            iframe.style.display = this._isLoading || this._hasError ? 'none' : 'block';
        }
    }

    // ==================== Rendering ====================

    render() {
        const dashboardUid = this.getAttribute('dashboard-uid');
        const panelId = this.getAttribute('panel-id');
        const height = this.getAttribute('height') || '300';

        if (!dashboardUid || !panelId) {
            this.innerHTML = `
                <div class="lcm-grafana-panel alert alert-warning d-flex align-items-center"
                     style="height: ${height}px;">
                    <i class="bi bi-exclamation-triangle me-2"></i>
                    Missing dashboard-uid or panel-id attribute
                </div>
            `;
            return;
        }

        const panelUrl = this._buildPanelUrl();

        this.innerHTML = `
            <style>
                .lcm-grafana-panel {
                    position: relative;
                    width: 100%;
                    border-radius: 0.375rem;
                    overflow: hidden;
                    background-color: var(--bs-body-bg);
                }
                .lcm-grafana-panel iframe {
                    border: none;
                    width: 100%;
                    height: 100%;
                }
                .lcm-grafana-loader,
                .lcm-grafana-error {
                    position: absolute;
                    top: 0;
                    left: 0;
                    right: 0;
                    bottom: 0;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    flex-direction: column;
                    gap: 0.5rem;
                    background-color: var(--bs-body-bg);
                }
                .lcm-grafana-error {
                    color: var(--bs-danger);
                }
                .lcm-grafana-unavailable {
                    opacity: 0.7;
                }
            </style>
            <div class="lcm-grafana-panel border" style="height: ${height}px;">
                <div class="lcm-grafana-loader">
                    <div class="spinner-border text-primary" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                    <small class="text-muted">Loading Grafana panel...</small>
                </div>
                <div class="lcm-grafana-error" style="display: none;">
                    <i class="bi bi-exclamation-circle fs-1"></i>
                    <span>Grafana panel unavailable</span>
                    <button class="btn btn-outline-secondary btn-sm lcm-grafana-retry">
                        <i class="bi bi-arrow-clockwise me-1"></i>Retry
                    </button>
                </div>
                <iframe
                    src="${panelUrl}"
                    style="display: none;"
                    loading="lazy"
                    sandbox="allow-scripts allow-same-origin"
                    title="Grafana Panel"
                ></iframe>
            </div>
        `;

        this._bindEvents();
    }

    _bindEvents() {
        const iframe = this.querySelector('iframe');
        if (iframe) {
            iframe.addEventListener('load', () => this._handleLoad());
            iframe.addEventListener('error', () => this._handleError());

            // Fallback timeout for load detection
            setTimeout(() => {
                if (this._isLoading) {
                    // Check if iframe loaded by trying to access contentWindow
                    try {
                        // This will throw if cross-origin, which is fine (means it loaded)
                        const _ = iframe.contentWindow.location.href;
                        this._handleLoad();
                    } catch (e) {
                        // Cross-origin - assume loaded
                        this._handleLoad();
                    }
                }
            }, 5000);
        }

        const retryBtn = this.querySelector('.lcm-grafana-retry');
        retryBtn?.addEventListener('click', () => {
            this._isLoading = true;
            this._hasError = false;
            this._updateLoadingState();
            this.reload();
        });
    }
}

/**
 * LcmGrafanaDashboard - Full Grafana Dashboard Embed
 *
 * Embeds an entire Grafana dashboard. Use when you want to show
 * multiple panels with Grafana's native layout.
 *
 * Usage:
 *   <lcm-grafana-dashboard
 *     grafana-url="/grafana"
 *     dashboard-uid="worker-overview"
 *     height="600"
 *   ></lcm-grafana-dashboard>
 */
export class LcmGrafanaDashboard extends BaseComponent {
    static get observedAttributes() {
        return ['grafana-url', 'dashboard-uid', 'from', 'to', 'refresh', 'height', 'variables', 'theme'];
    }

    constructor() {
        super();
    }

    onMount() {
        this.render();
    }

    onAttributeChange() {
        this.render();
    }

    _buildDashboardUrl() {
        const grafanaUrl = this.getAttribute('grafana-url') || '/grafana';
        const dashboardUid = this.getAttribute('dashboard-uid');
        const from = this.getAttribute('from') || 'now-1h';
        const to = this.getAttribute('to') || 'now';
        const refresh = this.getAttribute('refresh');

        let theme = this.getAttribute('theme') || 'auto';
        if (theme === 'auto') {
            theme = document.documentElement.getAttribute('data-bs-theme') || 'light';
        }

        const params = new URLSearchParams({
            from,
            to,
            theme,
            kiosk: '',
        });

        if (refresh) {
            params.set('refresh', refresh);
        }

        // Add variables
        try {
            const variables = JSON.parse(this.getAttribute('variables') || '{}');
            Object.entries(variables).forEach(([key, value]) => {
                params.set(`var-${key}`, value);
            });
        } catch (e) {
            console.warn('[LcmGrafanaDashboard] Invalid variables JSON:', e);
        }

        return `${grafanaUrl}/d/${dashboardUid}?${params.toString()}`;
    }

    render() {
        const dashboardUid = this.getAttribute('dashboard-uid');
        const height = this.getAttribute('height') || '600';

        if (!dashboardUid) {
            this.innerHTML = `
                <div class="alert alert-warning">
                    Missing dashboard-uid attribute
                </div>
            `;
            return;
        }

        const dashboardUrl = this._buildDashboardUrl();

        this.innerHTML = `
            <div class="lcm-grafana-dashboard border rounded overflow-hidden" style="height: ${height}px;">
                <iframe
                    src="${dashboardUrl}"
                    style="border: none; width: 100%; height: 100%;"
                    loading="lazy"
                    sandbox="allow-scripts allow-same-origin"
                    title="Grafana Dashboard"
                ></iframe>
            </div>
        `;
    }
}

// Register custom elements
if (!customElements.get('lcm-grafana-panel')) {
    customElements.define('lcm-grafana-panel', LcmGrafanaPanel);
}

if (!customElements.get('lcm-grafana-dashboard')) {
    customElements.define('lcm-grafana-dashboard', LcmGrafanaDashboard);
}

export default LcmGrafanaPanel;
