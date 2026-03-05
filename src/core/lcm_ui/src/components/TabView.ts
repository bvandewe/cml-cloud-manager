/**
 * TabView - Tabbed Navigation Web Component
 *
 * A flexible tabbed navigation component supporting pill, underline, and button variants.
 * Integrates with EventBus for inter-component communication and supports persistence.
 *
 *
 * @example
 * ```html
 * <ui-tab-view variant="pills" persist-key="main-tabs">
 *   <ui-tab id="tab1" label="Overview" icon="bi-house" active></ui-tab>
 *   <ui-tab id="tab2" label="Settings" icon="bi-gear"></ui-tab>
 * </ui-tab-view>
 *
 * <div slot="tab1">Content for Tab 1</div>
 * <div slot="tab2">Content for Tab 2</div>
 * ```
 *
 * Events:
 *   - 'tab-change': { tabId, previousTabId }
 *
 * @module components
 */

import { BaseComponent } from './BaseComponent.js';
import type { TabDefinition } from './index.js';

/**
 * Tab variant styles
 */
export type TabVariant = 'pills' | 'underline' | 'tabs' | 'buttons';

/**
 * Tab position options
 */
export type TabPosition = 'top' | 'bottom' | 'left' | 'right';

/**
 * Tab change event detail
 */
export interface TabChangeEventDetail {
    tabId: string;
    previousTabId: string | null;
}

/**
 * Tab Item Web Component
 */
export class Tab extends HTMLElement {
    static get observedAttributes(): string[] {
        return ['label', 'icon', 'active', 'disabled', 'badge', 'badge-color'];
    }

    private _button: HTMLButtonElement | null = null;

    constructor() {
        super();
    }

    connectedCallback(): void {
        this.render();
    }

    attributeChangedCallback(_name: string, oldValue: string | null, newValue: string | null): void {
        if (oldValue !== newValue) {
            this.render();
        }
    }

    get tabId(): string {
        return this.id || this.getAttribute('tab-id') || '';
    }

    get label(): string {
        return this.getAttribute('label') || '';
    }

    get icon(): string {
        return this.getAttribute('icon') || '';
    }

    get isActive(): boolean {
        return this.hasAttribute('active');
    }

    set isActive(value: boolean) {
        if (value) {
            this.setAttribute('active', '');
        } else {
            this.removeAttribute('active');
        }
    }

    get isDisabled(): boolean {
        return this.hasAttribute('disabled');
    }

    get badge(): string | null {
        return this.getAttribute('badge');
    }

    get badgeColor(): string {
        return this.getAttribute('badge-color') || 'secondary';
    }

    private render(): void {
        const tabView = this.closest('ui-tab-view') as TabView | null;
        const variant = tabView?.variant || 'pills';

        const iconHtml = this.icon ? `<i class="${this.icon} me-1"></i>` : '';
        const badgeHtml = this.badge ? `<span class="badge bg-${this.badgeColor} ms-1">${this.badge}</span>` : '';

        let buttonClass = 'nav-link';
        if (variant === 'pills') {
            buttonClass = 'nav-link';
        } else if (variant === 'underline' || variant === 'tabs') {
            buttonClass = 'nav-link border-0';
        } else if (variant === 'buttons') {
            buttonClass = 'btn btn-outline-secondary';
        }

        if (this.isActive) {
            buttonClass += ' active';
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
        this._button?.addEventListener('click', () => this.handleClick());
    }

    private handleClick(): void {
        if (this.isDisabled) return;

        const tabView = this.closest('ui-tab-view') as TabView | null;
        if (tabView) {
            tabView.setActiveTab(this.tabId);
        }
    }
}

/**
 * TabView Container Web Component
 */
export class TabView extends BaseComponent {
    static get observedAttributes(): string[] {
        return ['variant', 'position', 'persist-key', 'fill', 'justified'];
    }

    private _activeTabId: string | null = null;
    private _contentSlots: Map<string, HTMLElement> = new Map();
    private _tabs: TabDefinition[] = [];

    constructor() {
        super();
    }

    protected override onMount(): void {
        this.render();
        this.initializeTabs();
        this.restorePersistedTab();
    }

    protected override onAttributeChange(): void {
        if (this._mounted) {
            this.render();
        }
    }

    // ===================== Getters =====================

    get variant(): TabVariant {
        const v = this.getAttribute('variant');
        if (v === 'pills' || v === 'underline' || v === 'tabs' || v === 'buttons') {
            return v;
        }
        return 'pills';
    }

    get position(): TabPosition {
        const p = this.getAttribute('position');
        if (p === 'top' || p === 'bottom' || p === 'left' || p === 'right') {
            return p;
        }
        return 'top';
    }

    get persistKey(): string | null {
        return this.getAttribute('persist-key');
    }

    get isFill(): boolean {
        return this.getBoolAttr('fill');
    }

    get isJustified(): boolean {
        return this.getBoolAttr('justified');
    }

    get activeTabId(): string | null {
        return this._activeTabId;
    }

    // ===================== Public API =====================

    /**
     * Set the active tab by ID
     */
    setActiveTab(tabId: string): void {
        if (tabId === this._activeTabId) return;

        const previousTabId = this._activeTabId;
        this._activeTabId = tabId;

        // Update tab states
        this.updateTabStates();

        // Show/hide content
        this.updateContentVisibility();

        // Persist if configured
        if (this.persistKey) {
            try {
                sessionStorage.setItem(`tab:${this.persistKey}`, tabId);
            } catch (e) {
                console.warn('[TabView] Failed to persist tab state:', e);
            }
        }

        // Emit DOM event
        const detail: TabChangeEventDetail = {
            tabId,
            previousTabId,
        };
        this.emitDOMEvent('tab-change', detail);

        // Emit to EventBus
        this.emit('ui:tab-change', detail);
    }

    /**
     * Get all tab elements
     */
    getTabs(): Tab[] {
        return Array.from(this.querySelectorAll('ui-tab')) as Tab[];
    }

    /**
     * Define tabs programmatically
     */
    setTabs(tabs: TabDefinition[]): void {
        this._tabs = tabs;
        this.render();
        this.initializeTabs();
    }

    /**
     * Add a badge to a tab
     */
    setTabBadge(tabId: string, badge: string | null, color?: string): void {
        const tab = this.querySelector(`ui-tab[id="${tabId}"], ui-tab[tab-id="${tabId}"]`) as Tab | null;
        if (tab) {
            if (badge === null) {
                tab.removeAttribute('badge');
            } else {
                tab.setAttribute('badge', badge);
                if (color) {
                    tab.setAttribute('badge-color', color);
                }
            }
        }
    }

    /**
     * Enable/disable a tab
     */
    setTabDisabled(tabId: string, disabled: boolean): void {
        const tab = this.querySelector(`ui-tab[id="${tabId}"], ui-tab[tab-id="${tabId}"]`) as Tab | null;
        if (tab) {
            if (disabled) {
                tab.setAttribute('disabled', '');
            } else {
                tab.removeAttribute('disabled');
            }
        }
    }

    // ===================== Private Methods =====================

    private initializeTabs(): void {
        const tabs = this.getTabs();
        if (tabs.length === 0) return;

        // Find initially active tab or use first
        let activeTab = tabs.find(t => t.isActive);
        if (!activeTab) {
            activeTab = tabs.find(t => !t.isDisabled);
            if (activeTab) {
                activeTab.isActive = true;
            }
        }

        if (activeTab) {
            this._activeTabId = activeTab.tabId;
        }

        // Index content slots
        this.indexContentSlots();
        this.updateContentVisibility();
    }

    private indexContentSlots(): void {
        this._contentSlots.clear();

        // Look for slotted content
        const tabs = this.getTabs();
        for (const tab of tabs) {
            const tabId = tab.tabId;
            // Look for content with slot attribute or data-tab attribute
            const content = this.querySelector(`[slot="${tabId}"], [data-tab="${tabId}"]`) as HTMLElement | null;
            if (content) {
                this._contentSlots.set(tabId, content);
            }
        }
    }

    private updateTabStates(): void {
        const tabs = this.getTabs();
        for (const tab of tabs) {
            tab.isActive = tab.tabId === this._activeTabId;
        }
    }

    private updateContentVisibility(): void {
        for (const [tabId, content] of this._contentSlots) {
            if (tabId === this._activeTabId) {
                content.style.display = '';
                content.removeAttribute('hidden');
            } else {
                content.style.display = 'none';
                content.setAttribute('hidden', '');
            }
        }
    }

    private restorePersistedTab(): void {
        if (!this.persistKey) return;

        try {
            const savedTabId = sessionStorage.getItem(`tab:${this.persistKey}`);
            if (savedTabId) {
                const tab = this.querySelector(`ui-tab[id="${savedTabId}"], ui-tab[tab-id="${savedTabId}"]`) as Tab | null;
                if (tab && !tab.isDisabled) {
                    this.setActiveTab(savedTabId);
                }
            }
        } catch (e) {
            console.warn('[TabView] Failed to restore persisted tab:', e);
        }
    }

    override render(): void {
        // Build nav class
        let navClass = 'nav';
        if (this.variant === 'pills') {
            navClass += ' nav-pills';
        } else if (this.variant === 'tabs' || this.variant === 'underline') {
            navClass += ' nav-tabs';
        } else if (this.variant === 'buttons') {
            navClass += ' gap-2';
        }

        if (this.isFill) {
            navClass += ' nav-fill';
        }
        if (this.isJustified) {
            navClass += ' nav-justified';
        }

        // Render programmatic tabs if defined
        if (this._tabs.length > 0) {
            const tabsHtml = this._tabs
                .map(
                    t => `
        <ui-tab
          id="${t.id}"
          label="${t.label}"
          ${t.icon ? `icon="${t.icon}"` : ''}
          ${t.disabled ? 'disabled' : ''}
          ${t.id === this._activeTabId ? 'active' : ''}>
        </ui-tab>
      `
                )
                .join('');

            // Find existing nav or create wrapper
            let nav = this.$('.nav') as HTMLElement | null;
            if (!nav) {
                // Wrap existing content
                const existingContent = this.innerHTML;
                this.innerHTML = `
          <ul class="${navClass}" role="tablist">
            ${tabsHtml}
          </ul>
          <div class="tab-content mt-3">
            ${existingContent}
          </div>
        `;
            }
        } else {
            // Just update nav classes on existing nav element
            const nav = this.$('ul.nav, .nav') as HTMLElement | null;
            if (nav) {
                nav.className = navClass;
                nav.setAttribute('role', 'tablist');
            }
        }
    }
}

// Register custom elements
if (!customElements.get('ui-tab')) {
    customElements.define('ui-tab', Tab);
}

if (!customElements.get('ui-tab-view')) {
    customElements.define('ui-tab-view', TabView);
}

export default TabView;
