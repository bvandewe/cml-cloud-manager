/**
 * ColumnPicker - Column Visibility Manager
 *
 * Dropdown panel with checkboxes grouped by category.
 * Supports presets, reset-to-default, and localStorage persistence.
 *
 * @example
 * ```html
 * <ui-column-picker table-id="workers-table"></ui-column-picker>
 * ```
 *
 * Configure via JavaScript:
 * ```typescript
 * const picker = document.querySelector('ui-column-picker');
 * picker.setColumns(WORKER_COLUMNS, WORKER_DEFAULT_COLUMNS);
 * picker.addEventListener('columns-changed', (e) => console.log(e.detail.visibleColumns));
 * ```
 *
 * @module components
 */

import { BaseComponent } from './BaseComponent.js';
import type { SchemaColumn, ColumnPreset } from '../types/columns.js';

/** localStorage key prefix for column visibility */
const STORAGE_PREFIX = 'lcm.columns.';

/** localStorage key prefix for column presets */
const PRESET_PREFIX = 'lcm.columns.presets.';

/**
 * Column changed event detail
 */
export interface ColumnsChangedEventDetail {
    /** Column fields currently visible */
    visibleColumns: string[];
    /** All column fields */
    allColumns: string[];
    /** Table identifier */
    tableId: string;
}

/**
 * ColumnPicker Web Component
 *
 * Renders a dropdown panel with categorized column checkboxes.
 * Emits 'columns-changed' event when visibility changes.
 */
export class ColumnPicker extends BaseComponent {
    static get observedAttributes(): string[] {
        return ['table-id'];
    }

    private _columns: Record<string, SchemaColumn> = {};
    private _defaultColumns: string[] = [];
    private _visibleColumns: Set<string> = new Set();
    private _open: boolean = false;

    constructor() {
        super();
    }

    protected override onMount(): void {
        this.loadPersistedVisibility();
        this.render();
        // Close on outside click
        this._onDocumentClick = this._onDocumentClick.bind(this);
        document.addEventListener('click', this._onDocumentClick);
    }

    protected override onUnmount(): void {
        document.removeEventListener('click', this._onDocumentClick);
    }

    // ── Attribute Accessors ──

    get tableId(): string {
        return this.getAttr('table-id', '');
    }

    /** Currently visible column fields */
    get visibleColumns(): string[] {
        return Array.from(this._visibleColumns);
    }

    // ── Public API ──

    /**
     * Set columns configuration.
     * @param columns - Column registry (field → SchemaColumn)
     * @param defaultColumns - Default visible column fields
     */
    setColumns(columns: Record<string, SchemaColumn>, defaultColumns: string[]): void {
        this._columns = columns;
        this._defaultColumns = defaultColumns;
        this.loadPersistedVisibility();
        if (this._mounted) this.render();
    }

    /** Get columns grouped by category */
    getColumnsByCategory(): Record<string, Array<{ field: string; column: SchemaColumn }>> {
        const groups: Record<string, Array<{ field: string; column: SchemaColumn }>> = {};
        for (const [field, col] of Object.entries(this._columns)) {
            const category = col.category || 'other';
            if (!groups[category]) groups[category] = [];
            groups[category]!.push({ field, column: col });
        }
        return groups;
    }

    /** Check if a column is visible */
    isColumnVisible(field: string): boolean {
        return this._visibleColumns.has(field);
    }

    /** Toggle a column's visibility */
    toggleColumn(field: string): void {
        if (this._visibleColumns.has(field)) {
            this._visibleColumns.delete(field);
        } else {
            this._visibleColumns.add(field);
        }
        this.persistVisibility();
        this.emitChange();
        if (this._mounted) this.render();
    }

    /** Reset to default column set */
    resetToDefault(): void {
        this._visibleColumns = new Set(this._defaultColumns);
        this.persistVisibility();
        this.emitChange();
        if (this._mounted) this.render();
    }

    /** Save current config as a preset */
    savePreset(name: string): void {
        const presets = this.loadPresets();
        presets.push({ name, columns: Array.from(this._visibleColumns) });
        this.savePresets(presets);
    }

    /** Load a preset */
    loadPreset(name: string): void {
        const presets = this.loadPresets();
        const preset = presets.find(p => p.name === name);
        if (preset) {
            this._visibleColumns = new Set(preset.columns);
            this.persistVisibility();
            this.emitChange();
            if (this._mounted) this.render();
        }
    }

    /** Delete a preset */
    deletePreset(name: string): void {
        const presets = this.loadPresets().filter(p => p.name !== name);
        this.savePresets(presets);
        if (this._mounted) this.render();
    }

    // ── Private ──

    private _onDocumentClick(e: Event): void {
        if (!this.contains(e.target as Node) && this._open) {
            this._open = false;
            if (this._mounted) this.render();
        }
    }

    private get storageKey(): string {
        return `${STORAGE_PREFIX}${this.tableId}`;
    }

    private get presetKey(): string {
        return `${PRESET_PREFIX}${this.tableId}`;
    }

    private loadPersistedVisibility(): void {
        if (!this.tableId) {
            this._visibleColumns = new Set(this._defaultColumns);
            return;
        }

        const stored = localStorage.getItem(this.storageKey);
        if (stored) {
            try {
                this._visibleColumns = new Set(JSON.parse(stored) as string[]);
                return;
            } catch {
                // Fall through to defaults
            }
        }
        this._visibleColumns = new Set(this._defaultColumns);
    }

    private persistVisibility(): void {
        if (!this.tableId) return;
        localStorage.setItem(this.storageKey, JSON.stringify(Array.from(this._visibleColumns)));
    }

    private loadPresets(): ColumnPreset[] {
        if (!this.tableId) return [];
        const stored = localStorage.getItem(this.presetKey);
        if (!stored) return [];
        try {
            return JSON.parse(stored) as ColumnPreset[];
        } catch {
            return [];
        }
    }

    private savePresets(presets: ColumnPreset[]): void {
        if (!this.tableId) return;
        localStorage.setItem(this.presetKey, JSON.stringify(presets));
    }

    private emitChange(): void {
        this.emitDOMEvent<ColumnsChangedEventDetail>('columns-changed', {
            visibleColumns: Array.from(this._visibleColumns),
            allColumns: Object.keys(this._columns),
            tableId: this.tableId,
        });
    }

    private formatCategory(category: string): string {
        return category.charAt(0).toUpperCase() + category.slice(1);
    }

    // ── Rendering ──

    override render(): void {
        const groups = this.getColumnsByCategory();
        const presets = this.loadPresets();
        const hasColumns = Object.keys(this._columns).length > 0;

        if (!hasColumns) {
            this.innerHTML = '';
            return;
        }

        const categorySections = Object.entries(groups)
            .map(([category, cols]) => {
                const checkboxes = cols
                    .map(
                        ({ field, column }) => `
                    <div class="form-check form-check-sm">
                        <input class="form-check-input column-checkbox" type="checkbox" id="col-${this.tableId}-${field}"
                               data-field="${field}" ${this._visibleColumns.has(field) ? 'checked' : ''}
                               aria-label="Toggle ${column.label} column">
                        <label class="form-check-label small" for="col-${this.tableId}-${field}"
                               ${column.description ? `title="${column.description}"` : ''}>
                            ${column.label}
                        </label>
                    </div>
                `
                    )
                    .join('');

                return `
                    <div class="mb-2">
                        <div class="fw-semibold small text-muted mb-1">${this.formatCategory(category)}</div>
                        ${checkboxes}
                    </div>
                `;
            })
            .join('');

        const presetSection =
            presets.length > 0
                ? `
                <div class="border-top pt-2 mt-2">
                    <div class="fw-semibold small text-muted mb-1">Presets</div>
                    ${presets.map(p => `<button class="btn btn-sm btn-outline-secondary me-1 mb-1 preset-load" data-preset="${p.name}">${p.name}</button>`).join('')}
                </div>
            `
                : '';

        const dropdownClass = this._open ? 'show' : '';

        this.innerHTML = `
            <div class="dropdown d-inline-block">
                <button class="btn btn-sm btn-outline-secondary dropdown-toggle column-picker-toggle"
                        type="button" aria-expanded="${this._open}" aria-label="Configure visible columns">
                    <i class="bi-gear me-1" aria-hidden="true"></i>Columns
                </button>
                <div class="dropdown-menu p-3 ${dropdownClass}" style="min-width: 260px; max-height: 400px; overflow-y: auto;">
                    ${categorySections}
                    ${presetSection}
                    <div class="border-top pt-2 mt-2 d-flex gap-2">
                        <button class="btn btn-sm btn-outline-secondary reset-btn" aria-label="Reset to default columns">
                            Reset to Default
                        </button>
                    </div>
                </div>
            </div>
        `;

        this.bindEvents();
    }

    private bindEvents(): void {
        // Toggle dropdown
        const toggleBtn = this.$('.column-picker-toggle');
        toggleBtn?.addEventListener('click', e => {
            e.stopPropagation();
            this._open = !this._open;
            this.render();
        });

        // Prevent dropdown close on inner click
        const menu = this.$('.dropdown-menu');
        menu?.addEventListener('click', e => e.stopPropagation());

        // Column checkboxes
        for (const checkbox of this.$$('.column-checkbox')) {
            checkbox.addEventListener('change', () => {
                const field = (checkbox as HTMLElement).dataset['field'];
                if (field) this.toggleColumn(field);
            });
        }

        // Reset button
        const resetBtn = this.$('.reset-btn');
        resetBtn?.addEventListener('click', () => this.resetToDefault());

        // Preset buttons
        for (const presetBtn of this.$$('.preset-load')) {
            presetBtn.addEventListener('click', () => {
                const name = (presetBtn as HTMLElement).dataset['preset'];
                if (name) this.loadPreset(name);
            });
        }
    }
}

// Register the custom element
if (!customElements.get('ui-column-picker')) {
    customElements.define('ui-column-picker', ColumnPicker);
}

export default ColumnPicker;
