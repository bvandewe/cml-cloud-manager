/**
 * ActionBar - Toolbar Web Component
 *
 * A flexible toolbar component for action buttons, filters, and dropdowns.
 * Integrates with EventBus for action events.
 *
 * @example
 * ```html
 * <ui-action-bar>
 *   <ui-action-button label="Create" icon="bi-plus" variant="primary"></ui-action-button>
 *   <ui-action-button label="Refresh" icon="bi-arrow-clockwise"></ui-action-button>
 *   <ui-filter-chip key="status" value="running" label="Status: Running" removable></ui-filter-chip>
 *   <ui-dropdown-action label="More" icon="bi-three-dots">
 *     <ui-action-button label="Export" icon="bi-download"></ui-action-button>
 *     <ui-action-button label="Import" icon="bi-upload"></ui-action-button>
 *   </ui-dropdown-action>
 * </ui-action-bar>
 * ```
 *
 * Events:
 *   - 'action': { actionId, data }
 *   - 'filter-remove': { key, value }
 *
 * @module components
 */

import { BaseComponent } from './BaseComponent.js';

/**
 * Action button click event detail
 */
export interface ActionEventDetail {
    actionId: string;
    data?: unknown;
}

/**
 * Filter remove event detail
 */
export interface FilterRemoveEventDetail {
    key: string;
    value: string;
}

/**
 * Button variant types
 */
export type ButtonVariant = 'primary' | 'secondary' | 'success' | 'danger' | 'warning' | 'info' | 'light' | 'dark' | 'link' | 'outline-primary' | 'outline-secondary' | 'outline-success' | 'outline-danger' | 'outline-warning' | 'outline-info';

/**
 * ActionButton Web Component
 */
export class ActionButton extends BaseComponent {
    static get observedAttributes(): string[] {
        return ['action-id', 'label', 'icon', 'variant', 'size', 'disabled', 'loading', 'tooltip'];
    }

    constructor() {
        super();
    }

    protected override onMount(): void {
        this.render();
    }

    protected override onAttributeChange(): void {
        if (this._mounted) {
            this.render();
        }
    }

    // ===================== Getters =====================

    get actionId(): string {
        return this.getAttr('action-id', this.id || '');
    }

    get label(): string {
        return this.getAttr('label', '');
    }

    get icon(): string {
        return this.getAttr('icon', '');
    }

    get variant(): ButtonVariant {
        return this.getAttr('variant', 'secondary') as ButtonVariant;
    }

    get buttonSize(): string {
        return this.getAttr('size', '');
    }

    get isDisabled(): boolean {
        return this.getBoolAttr('disabled');
    }

    get isLoading(): boolean {
        return this.getBoolAttr('loading');
    }

    get tooltip(): string {
        return this.getAttr('tooltip', '');
    }

    // ===================== Public API =====================

    /**
     * Set loading state
     */
    setLoading(loading: boolean): void {
        if (loading) {
            this.setAttribute('loading', '');
        } else {
            this.removeAttribute('loading');
        }
    }

    /**
     * Enable/disable the button
     */
    setDisabled(disabled: boolean): void {
        if (disabled) {
            this.setAttribute('disabled', '');
        } else {
            this.removeAttribute('disabled');
        }
    }

    // ===================== Rendering =====================

    override render(): void {
        const iconHtml = this.icon ? `<i class="${this.icon}${this.label ? ' me-1' : ''}"></i>` : '';

        const loadingHtml = this.isLoading ? `<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>` : '';

        let sizeClass = '';
        if (this.buttonSize === 'sm') sizeClass = 'btn-sm';
        else if (this.buttonSize === 'lg') sizeClass = 'btn-lg';

        const tooltipAttrs = this.tooltip ? `title="${this.tooltip}" data-bs-toggle="tooltip"` : '';

        this.innerHTML = `
      <button
        type="button"
        class="btn btn-${this.variant} ${sizeClass}"
        ${this.isDisabled || this.isLoading ? 'disabled' : ''}
        ${tooltipAttrs}>
        ${this.isLoading ? loadingHtml : iconHtml}${this.label}
      </button>
    `;

        const button = this.$('button');
        button?.addEventListener('click', e => this.handleClick(e));
    }

    private handleClick(e: Event): void {
        if (this.isDisabled || this.isLoading) return;

        e.preventDefault();

        const detail: ActionEventDetail = {
            actionId: this.actionId,
            data: this.getJsonAttr('data'),
        };

        this.emitDOMEvent('action', detail);
        this.emit('ui:action', detail);
    }
}

/**
 * FilterChip Web Component - Displays active filter as removable chip
 */
export class FilterChip extends BaseComponent {
    static get observedAttributes(): string[] {
        return ['key', 'value', 'label', 'removable', 'color'];
    }

    constructor() {
        super();
    }

    protected override onMount(): void {
        this.render();
    }

    protected override onAttributeChange(): void {
        if (this._mounted) {
            this.render();
        }
    }

    // ===================== Getters =====================

    get filterKey(): string {
        return this.getAttr('key', '');
    }

    get filterValue(): string {
        return this.getAttr('value', '');
    }

    get label(): string {
        return this.getAttr('label', `${this.filterKey}: ${this.filterValue}`);
    }

    get isRemovable(): boolean {
        return this.getBoolAttr('removable');
    }

    get color(): string {
        return this.getAttr('color', 'secondary');
    }

    // ===================== Rendering =====================

    override render(): void {
        const removeBtn = this.isRemovable ? `<button type="button" class="btn-close btn-close-white ms-2" aria-label="Remove"></button>` : '';

        this.innerHTML = `
      <span class="badge bg-${this.color} d-inline-flex align-items-center">
        ${this.label}
        ${removeBtn}
      </span>
    `;

        if (this.isRemovable) {
            const closeBtn = this.$('.btn-close');
            closeBtn?.addEventListener('click', () => this.handleRemove());
        }
    }

    private handleRemove(): void {
        const detail: FilterRemoveEventDetail = {
            key: this.filterKey,
            value: this.filterValue,
        };

        this.emitDOMEvent('filter-remove', detail);
        this.emit('ui:filter-remove', detail);
        this.remove();
    }
}

/**
 * DropdownAction Web Component - Dropdown menu with action buttons
 */
export class DropdownAction extends BaseComponent {
    static get observedAttributes(): string[] {
        return ['label', 'icon', 'variant', 'size', 'align'];
    }

    constructor() {
        super();
    }

    protected override onMount(): void {
        this.render();
    }

    protected override onAttributeChange(): void {
        if (this._mounted) {
            this.render();
        }
    }

    // ===================== Getters =====================

    get label(): string {
        return this.getAttr('label', '');
    }

    get icon(): string {
        return this.getAttr('icon', 'bi-three-dots-vertical');
    }

    get variant(): ButtonVariant {
        return this.getAttr('variant', 'secondary') as ButtonVariant;
    }

    get dropdownSize(): string {
        return this.getAttr('size', '');
    }

    get align(): string {
        return this.getAttr('align', 'end');
    }

    // ===================== Rendering =====================

    override render(): void {
        const iconHtml = this.icon ? `<i class="${this.icon}${this.label ? ' me-1' : ''}"></i>` : '';

        let sizeClass = '';
        if (this.dropdownSize === 'sm') sizeClass = 'btn-sm';
        else if (this.dropdownSize === 'lg') sizeClass = 'btn-lg';

        // Get slotted content (action items)
        const slottedContent = Array.from(this.querySelectorAll('ui-action-button'));
        const menuItems = slottedContent
            .map(item => {
                const btn = item as ActionButton;
                const icon = btn.getAttribute('icon');
                const label = btn.getAttribute('label') || '';
                const actionId = btn.getAttribute('action-id') || btn.id || '';
                const disabled = btn.hasAttribute('disabled');
                const divider = btn.hasAttribute('divider-before');

                const iconHtml = icon ? `<i class="${icon} me-2"></i>` : '';
                const dividerHtml = divider ? '<li><hr class="dropdown-divider"></li>' : '';

                return `
        ${dividerHtml}
        <li>
          <button class="dropdown-item ${disabled ? 'disabled' : ''}"
                  type="button"
                  data-action-id="${actionId}"
                  ${disabled ? 'disabled' : ''}>
            ${iconHtml}${label}
          </button>
        </li>
      `;
            })
            .join('');

        this.innerHTML = `
      <div class="dropdown">
        <button class="btn btn-${this.variant} ${sizeClass} dropdown-toggle"
                type="button"
                data-bs-toggle="dropdown"
                aria-expanded="false">
          ${iconHtml}${this.label}
        </button>
        <ul class="dropdown-menu dropdown-menu-${this.align}">
          ${menuItems}
        </ul>
      </div>
    `;

        // Bind click events to menu items
        const items = this.$$('.dropdown-item');
        for (const item of items) {
            item.addEventListener('click', e => {
                const actionId = (e.currentTarget as HTMLElement).dataset.actionId;
                if (actionId) {
                    const detail: ActionEventDetail = { actionId };
                    this.emitDOMEvent('action', detail);
                    this.emit('ui:action', detail);
                }
            });
        }
    }
}

/**
 * ActionBar Container Web Component
 */
export class ActionBar extends BaseComponent {
    static get observedAttributes(): string[] {
        return ['justify', 'gap', 'wrap'];
    }

    constructor() {
        super();
    }

    protected override onMount(): void {
        this.render();
    }

    protected override onAttributeChange(): void {
        if (this._mounted) {
            this.render();
        }
    }

    // ===================== Getters =====================

    get justify(): string {
        return this.getAttr('justify', 'start');
    }

    get gap(): string {
        return this.getAttr('gap', '2');
    }

    get shouldWrap(): boolean {
        return this.getBoolAttr('wrap');
    }

    // ===================== Rendering =====================

    override render(): void {
        const justifyClass = `justify-content-${this.justify}`;
        const wrapClass = this.shouldWrap ? 'flex-wrap' : 'flex-nowrap';

        // Wrap existing content
        const content = this.innerHTML;
        this.innerHTML = `
      <div class="action-bar d-flex align-items-center gap-${this.gap} ${justifyClass} ${wrapClass}">
        ${content}
      </div>
    `;

        // Re-render after first render to avoid losing slotted content
        // We only wrap once
    }
}

// Register custom elements
if (!customElements.get('ui-action-button')) {
    customElements.define('ui-action-button', ActionButton);
}

if (!customElements.get('ui-filter-chip')) {
    customElements.define('ui-filter-chip', FilterChip);
}

if (!customElements.get('ui-dropdown-action')) {
    customElements.define('ui-dropdown-action', DropdownAction);
}

if (!customElements.get('ui-action-bar')) {
    customElements.define('ui-action-bar', ActionBar);
}
