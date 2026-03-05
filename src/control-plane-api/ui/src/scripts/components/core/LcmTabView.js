/**
 * LcmTabView - Tabbed Container Web Component
 *
 * A flexible tabbed navigation component supporting pill, underline, and button variants.
 * Integrates with EventBus for inter-component communication.
 *
 * Usage:
 *   <lcm-tab-view variant="pills" position="nav">
 *     <lcm-tab id="tab1" label="Tab 1" icon="bi-house" active></lcm-tab>
 *     <lcm-tab id="tab2" label="Tab 2" icon="bi-gear"></lcm-tab>
 *   </lcm-tab-view>
 *
 * Events:
 *   - 'tab-change': Fired when active tab changes { tabId, previousTabId }
 *
 * @module components/core/LcmTabView
 */

import { BaseComponent } from '../../core/BaseComponent.js';
import { EventTypes, eventBus } from '../../core/EventBus.js';

/**
 * Tab item within a tab view
 */
export class LcmTab extends HTMLElement {
    static get observedAttributes() {
        return ['label', 'icon', 'active', 'disabled', 'badge'];
    }

    constructor() {
        super();
        this._button = null;
    }

    connectedCallback() {
        this.render();
    }

    attributeChangedCallback(name, oldValue, newValue) {
        if (oldValue !== newValue) {
            this.render();
        }
    }

    get tabId() {
        return this.id || this.getAttribute('tab-id');
    }

    get label() {
        return this.getAttribute('label') || '';
    }

    get icon() {
        return this.getAttribute('icon') || '';
    }

    get isActive() {
        return this.hasAttribute('active');
    }

    set isActive(value) {
        if (value) {
            this.setAttribute('active', '');
        } else {
            this.removeAttribute('active');
        }
    }

    get isDisabled() {
        return this.hasAttribute('disabled');
    }

    get badge() {
        return this.getAttribute('badge');
    }

    render() {
        const tabView = this.closest('lcm-tab-view');
        const variant = tabView?.getAttribute('variant') || 'pills';

        const iconHtml = this.icon ? `<i class="${this.icon} me-1"></i>` : '';
        const badgeHtml = this.badge ? `<span class="badge bg-secondary ms-1">${this.badge}</span>` : '';

        let buttonClass = 'nav-link';
        if (variant === 'pills') {
            buttonClass = 'nav-link';
        } else if (variant === 'underline') {
            buttonClass = 'nav-link border-0';
        } else if (variant === 'buttons') {
            buttonClass = 'btn btn-outline-secondary';
        }

        if (this.isActive) {
            buttonClass += variant === 'buttons' ? ' active' : ' active';
        }
        if (this.isDisabled) {
            buttonClass += ' disabled';
        }

        this.innerHTML = `
            <li class="nav-item">
                <button class="${buttonClass}"
                        type="button"
                        role="tab"
                        aria-selected="${this.isActive}"
                        ${this.isDisabled ? 'disabled' : ''}>
                    ${iconHtml}${this.label}${badgeHtml}
                </button>
            </li>
        `;

        this._button = this.querySelector('button');
        this._button?.addEventListener('click', () => this._handleClick());
    }

    _handleClick() {
        if (this.isDisabled) return;

        const tabView = this.closest('lcm-tab-view');
        if (tabView) {
            tabView.setActiveTab(this.tabId);
        }
    }
}

/**
 * Tab view container
 */
export class LcmTabView extends BaseComponent {
    static get observedAttributes() {
        return ['variant', 'position', 'persist-key'];
    }

    constructor() {
        super();
        this._activeTabId = null;
        this._contentSlots = new Map(); // tabId -> content element
    }

    onMount() {
        this.render();
        this._initializeTabs();
        this._restorePersistedTab();
    }

    onAttributeChange(name, oldValue, newValue) {
        this.render();
    }

    get variant() {
        return this.getAttribute('variant') || 'pills';
    }

    get position() {
        return this.getAttribute('position') || 'content';
    }

    get persistKey() {
        return this.getAttribute('persist-key');
    }

    get activeTabId() {
        return this._activeTabId;
    }

    /**
     * Get all tab elements
     */
    getTabs() {
        return Array.from(this.querySelectorAll('lcm-tab'));
    }

    /**
     * Set the active tab by ID
     * @param {string} tabId - The tab ID to activate
     */
    setActiveTab(tabId) {
        const previousTabId = this._activeTabId;
        if (previousTabId === tabId) return;

        // Update tab states
        this.getTabs().forEach(tab => {
            tab.isActive = tab.tabId === tabId;
        });

        this._activeTabId = tabId;

        // Update content visibility
        this._updateContentVisibility();

        // Persist if configured
        if (this.persistKey) {
            localStorage.setItem(`lcm-tab-${this.persistKey}`, tabId);
        }

        // Emit event
        this.emit('tab-change', { tabId, previousTabId });

        // Also emit on EventBus for global listeners
        eventBus.emit(EventTypes.UI_TAB_CHANGED, {
            tabViewId: this.id,
            tabId,
            previousTabId,
        });
    }

    /**
     * Register content element for a tab
     * @param {string} tabId - Tab ID
     * @param {HTMLElement} element - Content element
     */
    registerContent(tabId, element) {
        this._contentSlots.set(tabId, element);
        this._updateContentVisibility();
    }

    render() {
        // Get existing tabs
        const tabs = this.getTabs();

        // Build nav class based on variant
        let navClass = 'nav';
        if (this.variant === 'pills') {
            navClass += ' nav-pills';
        } else if (this.variant === 'underline') {
            navClass += ' nav-underline';
        } else if (this.variant === 'buttons') {
            navClass += ' btn-group';
        }

        if (this.position === 'nav') {
            navClass += ' navbar-nav flex-row';
        }

        // Wrap tabs in nav
        const existingNav = this.querySelector('.lcm-tab-nav');
        if (!existingNav) {
            const nav = document.createElement('ul');
            nav.className = `lcm-tab-nav ${navClass}`;
            nav.setAttribute('role', 'tablist');

            // Move tabs into nav
            tabs.forEach(tab => nav.appendChild(tab));
            this.insertBefore(nav, this.firstChild);
        } else {
            existingNav.className = `lcm-tab-nav ${navClass}`;
        }
    }

    _initializeTabs() {
        const tabs = this.getTabs();
        const activeTab = tabs.find(t => t.isActive) || tabs[0];
        if (activeTab) {
            this._activeTabId = activeTab.tabId;
        }
    }

    _restorePersistedTab() {
        if (!this.persistKey) return;

        const savedTabId = localStorage.getItem(`lcm-tab-${this.persistKey}`);
        if (savedTabId) {
            const tab = this.getTabs().find(t => t.tabId === savedTabId);
            if (tab && !tab.isDisabled) {
                this.setActiveTab(savedTabId);
            }
        }
    }

    _updateContentVisibility() {
        this._contentSlots.forEach((element, tabId) => {
            if (tabId === this._activeTabId) {
                element.style.display = '';
                element.classList.add('active');
            } else {
                element.style.display = 'none';
                element.classList.remove('active');
            }
        });
    }
}

// Register custom elements
if (!customElements.get('lcm-tab')) {
    customElements.define('lcm-tab', LcmTab);
}

if (!customElements.get('lcm-tab-view')) {
    customElements.define('lcm-tab-view', LcmTabView);
}

export default LcmTabView;
