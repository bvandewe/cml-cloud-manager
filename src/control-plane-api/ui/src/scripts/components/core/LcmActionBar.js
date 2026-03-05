/**
 * LcmActionBar - Action Bar Web Component
 *
 * A horizontal toolbar for actions, filters, and search that sits above data tables
 * or content sections. Supports primary actions, dropdown actions, and filter chips.
 *
 * Usage:
 *   <lcm-action-bar>
 *     <lcm-action-bar-primary>
 *       <button class="btn btn-primary"><i class="bi bi-plus"></i> New Worker</button>
 *     </lcm-action-bar-primary>
 *     <lcm-action-bar-filters>
 *       <lcm-filter-chip field="status" value="running">Running</lcm-filter-chip>
 *     </lcm-action-bar-filters>
 *   </lcm-action-bar>
 *
 * Events:
 *   - 'filter-clear': When all filters are cleared
 *   - 'filter-remove': { field, value } when a filter chip is removed
 *
 * @module components/core/LcmActionBar
 */

import { BaseComponent } from '../../core/BaseComponent.js';

export class LcmActionBar extends BaseComponent {
    static get observedAttributes() {
        return ['sticky', 'variant'];
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

    render() {
        const isSticky = this.hasAttribute('sticky');
        const variant = this.getAttribute('variant') || 'default'; // default, compact

        const stickyClass = isSticky ? 'sticky-top bg-body pt-2 pb-2' : '';
        const compactClass = variant === 'compact' ? 'py-2' : 'py-3';

        // Preserve slotted content
        const primarySlot = this.querySelector('lcm-action-bar-primary');
        const filtersSlot = this.querySelector('lcm-action-bar-filters');
        const secondarySlot = this.querySelector('lcm-action-bar-secondary');

        this.innerHTML = `
            <div class="lcm-action-bar d-flex justify-content-between align-items-center flex-wrap gap-2 ${stickyClass} ${compactClass}">
                <div class="d-flex align-items-center gap-2 flex-wrap">
                    <div class="lcm-action-bar-primary"></div>
                    <div class="lcm-action-bar-filters d-flex align-items-center gap-1 flex-wrap"></div>
                </div>
                <div class="lcm-action-bar-secondary d-flex align-items-center gap-2"></div>
            </div>
        `;

        // Move slotted content
        if (primarySlot) {
            this.querySelector('.lcm-action-bar-primary').replaceWith(primarySlot);
        }
        if (filtersSlot) {
            this.querySelector('.lcm-action-bar-filters').replaceWith(filtersSlot);
        }
        if (secondarySlot) {
            this.querySelector('.lcm-action-bar-secondary').replaceWith(secondarySlot);
        }
    }
}

/**
 * LcmFilterChip - Filter Chip Web Component
 *
 * A removable chip that displays an active filter value.
 *
 * Usage:
 *   <lcm-filter-chip field="status" value="running" color="success">
 *     Status: Running
 *   </lcm-filter-chip>
 */
export class LcmFilterChip extends BaseComponent {
    static get observedAttributes() {
        return ['field', 'value', 'color', 'removable'];
    }

    constructor() {
        super();
    }

    onMount() {
        this.render();
        this._bindEvents();
    }

    onAttributeChange() {
        this.render();
        this._bindEvents();
    }

    render() {
        const color = this.getAttribute('color') || 'secondary';
        const isRemovable = this.getAttribute('removable') !== 'false';
        const label = this.textContent.trim() || this.getAttribute('value') || '';

        // Save original text
        if (!this._originalLabel) {
            this._originalLabel = label;
        }

        this.innerHTML = `
            <span class="badge bg-${color} bg-opacity-25 text-${color} d-inline-flex align-items-center gap-1 px-2 py-1">
                <span class="lcm-chip-label">${this._originalLabel}</span>
                ${
                    isRemovable
                        ? `
                    <button type="button" class="btn-close btn-close-sm lcm-chip-remove"
                            aria-label="Remove filter"
                            style="font-size: 0.5em;"></button>
                `
                        : ''
                }
            </span>
        `;
    }

    _bindEvents() {
        const removeBtn = this.querySelector('.lcm-chip-remove');
        removeBtn?.addEventListener('click', e => {
            e.stopPropagation();
            this.dispatchEvent(
                new CustomEvent('filter-remove', {
                    detail: {
                        field: this.getAttribute('field'),
                        value: this.getAttribute('value'),
                    },
                    bubbles: true,
                })
            );
            this.remove();
        });
    }
}

/**
 * LcmDropdownAction - Dropdown Action Button
 *
 * A button with dropdown menu for additional actions.
 *
 * Usage:
 *   <lcm-dropdown-action label="Actions" icon="bi-three-dots-vertical">
 *     <lcm-dropdown-item action="export" icon="bi-download">Export</lcm-dropdown-item>
 *     <lcm-dropdown-divider></lcm-dropdown-divider>
 *     <lcm-dropdown-item action="delete" icon="bi-trash" variant="danger">Delete</lcm-dropdown-item>
 *   </lcm-dropdown-action>
 */
export class LcmDropdownAction extends BaseComponent {
    static get observedAttributes() {
        return ['label', 'icon', 'variant', 'size'];
    }

    constructor() {
        super();
        this._items = [];
    }

    onMount() {
        // Collect items before render
        this._items = Array.from(this.querySelectorAll('lcm-dropdown-item, lcm-dropdown-divider'));
        this.render();
    }

    onAttributeChange() {
        this.render();
    }

    render() {
        const label = this.getAttribute('label');
        const icon = this.getAttribute('icon') || 'bi-three-dots-vertical';
        const variant = this.getAttribute('variant') || 'outline-secondary';
        const size = this.getAttribute('size') || 'sm';

        const buttonContent = label ? `${icon ? `<i class="${icon} me-1"></i>` : ''}${label}` : `<i class="${icon}"></i>`;

        const items = this._items
            .map(item => {
                if (item.tagName === 'LCM-DROPDOWN-DIVIDER') {
                    return '<li><hr class="dropdown-divider"></li>';
                }

                const itemIcon = item.getAttribute('icon');
                const itemVariant = item.getAttribute('variant');
                const itemAction = item.getAttribute('action');
                const itemLabel = item.textContent.trim();
                const colorClass = itemVariant === 'danger' ? 'text-danger' : '';

                return `
                <li>
                    <button class="dropdown-item ${colorClass} lcm-dropdown-action-item" data-action="${itemAction}">
                        ${itemIcon ? `<i class="${itemIcon} me-2"></i>` : ''}${itemLabel}
                    </button>
                </li>
            `;
            })
            .join('');

        this.innerHTML = `
            <div class="dropdown">
                <button class="btn btn-${variant} btn-${size} dropdown-toggle"
                        type="button"
                        data-bs-toggle="dropdown"
                        aria-expanded="false">
                    ${buttonContent}
                </button>
                <ul class="dropdown-menu dropdown-menu-end">
                    ${items}
                </ul>
            </div>
        `;

        this._bindEvents();
    }

    _bindEvents() {
        this.querySelectorAll('.lcm-dropdown-action-item').forEach(item => {
            item.addEventListener('click', () => {
                const action = item.dataset.action;
                this.dispatchEvent(
                    new CustomEvent('action', {
                        detail: { action },
                        bubbles: true,
                    })
                );
            });
        });
    }
}

// Register custom elements
if (!customElements.get('lcm-action-bar')) {
    customElements.define('lcm-action-bar', LcmActionBar);
}

if (!customElements.get('lcm-filter-chip')) {
    customElements.define('lcm-filter-chip', LcmFilterChip);
}

if (!customElements.get('lcm-dropdown-action')) {
    customElements.define('lcm-dropdown-action', LcmDropdownAction);
}

export default LcmActionBar;
