/**
 * DataTable - Interactive Data Table Web Component
 *
 * A full-featured data table with filtering, sorting, pagination, row selection,
 * and bulk actions. Supports both static data and API-driven data sources.
 *
 * @example
 * ```html
 * <ui-data-table
 *   id="workers-table"
 *   page-size="25"
 *   selectable>
 * </ui-data-table>
 * ```
 *
 * Configure via JavaScript:
 * ```typescript
 * const table = document.getElementById('workers-table') as DataTable;
 * table.setColumns([
 *   { key: 'name', label: 'Name', sortable: true },
 *   { key: 'status', label: 'Status', render: (val) => `<ui-status-badge status="${val}">` },
 * ]);
 * table.setData(workers);
 * ```
 *
 * Events:
 *   - 'row-action': { action, row }
 *   - 'bulk-action': { action, selectedRows }
 *   - 'selection-change': { selectedIds }
 *   - 'row-click': { row }
 *   - 'sort-change': { field, direction }
 *   - 'page-change': { page, pageSize }
 *
 * @module components
 */

import { BaseComponent } from './BaseComponent.js';

/**
 * Column definition
 */
export interface ColumnDefinition<T = Record<string, unknown>> {
    /** Column key (property path) */
    key: string;
    /** Column header label */
    label: string;
    /** Whether column is sortable */
    sortable?: boolean;
    /** Whether column is filterable */
    filterable?: boolean;
    /** Custom cell renderer */
    render?: (value: unknown, row: T, index: number) => string;
    /** Column width (CSS value) */
    width?: string;
    /** Column alignment */
    align?: 'left' | 'center' | 'right';
    /** Column type for default formatting */
    type?: 'string' | 'number' | 'date' | 'datetime' | 'boolean';
    /** Whether column is hidden */
    hidden?: boolean;
    /** CSS class for cells */
    className?: string;
}

/**
 * Row action definition
 */
export interface RowAction {
    /** Action identifier */
    id: string;
    /** Button icon class */
    icon?: string;
    /** Button label */
    label?: string;
    /** Tooltip text */
    title?: string;
    /** Button variant */
    variant?: string;
    /** Condition function to show/hide action */
    condition?: (row: Record<string, unknown>) => boolean;
}

/**
 * Bulk action definition
 */
export interface BulkAction {
    /** Action identifier */
    id: string;
    /** Button label */
    label: string;
    /** Button icon class */
    icon?: string;
    /** Button variant */
    variant?: string;
    /** Whether to show confirmation dialog */
    confirm?: boolean;
    /** Confirmation message */
    confirmMessage?: string;
}

/**
 * Sort direction
 */
export type SortDirection = 'asc' | 'desc';

/**
 * Pagination info
 */
export interface PaginationInfo {
    currentPage: number;
    pageSize: number;
    totalItems: number;
    totalPages: number;
}

/**
 * Row click event detail
 */
export interface RowClickEventDetail {
    row: Record<string, unknown>;
    index: number;
}

/**
 * Row action event detail
 */
export interface RowActionEventDetail {
    action: string;
    row: Record<string, unknown>;
}

/**
 * Bulk action event detail
 */
export interface BulkActionEventDetail {
    action: string;
    selectedRows: Record<string, unknown>[];
}

/**
 * Selection change event detail
 */
export interface SelectionChangeEventDetail {
    selectedIds: Set<string>;
    selectedRows: Record<string, unknown>[];
}

/**
 * Sort change event detail
 */
export interface SortChangeEventDetail {
    field: string;
    direction: SortDirection;
}

/**
 * Page change event detail
 */
export interface PageChangeEventDetail {
    page: number;
    pageSize: number;
}

/**
 * DataTable Web Component
 */
export class DataTable<T extends Record<string, unknown> = Record<string, unknown>> extends BaseComponent {
    static get observedAttributes(): string[] {
        return ['page-size', 'selectable', 'loading', 'empty-message', 'id-field', 'striped', 'hover', 'bordered', 'compact'];
    }

    // Data state
    private _data: T[] = [];
    private _filteredData: T[] = [];
    private _columns: ColumnDefinition<T>[] = [];
    private _bulkActions: BulkAction[] = [];
    private _rowActions: RowAction[] = [];

    // Selection state
    private _selectedIds: Set<string> = new Set();

    // Pagination state
    private _currentPage: number = 1;
    private _pageSize: number = 25;
    private _totalItems: number = 0;

    // Sorting state
    private _sortField: string | null = null;
    private _sortDirection: SortDirection = 'asc';

    // Filter state
    private _filters: Record<string, unknown> = {};
    private _searchTerm: string = '';

    // Loading state
    private _isLoading: boolean = false;

    constructor() {
        super();
    }

    protected override onMount(): void {
        this._pageSize = this.getNumberAttr('page-size', 25);
        this.render();
    }

    protected override onAttributeChange(name: string): void {
        if (name === 'page-size') {
            this._pageSize = this.getNumberAttr('page-size', 25);
            this._currentPage = 1;
            this.applyFiltersAndSort();
        } else if (name === 'loading') {
            this._isLoading = this.getBoolAttr('loading');
            if (this._mounted) this.render();
        }
    }

    // ===================== Getters =====================

    get isSelectable(): boolean {
        return this.getBoolAttr('selectable');
    }

    get isLoading(): boolean {
        return this._isLoading || this.getBoolAttr('loading');
    }

    get emptyMessage(): string {
        return this.getAttr('empty-message', 'No data available');
    }

    get idField(): string {
        return this.getAttr('id-field', 'id');
    }

    get isStriped(): boolean {
        return this.getBoolAttr('striped');
    }

    get isHover(): boolean {
        return this.getBoolAttr('hover');
    }

    get isBordered(): boolean {
        return this.getBoolAttr('bordered');
    }

    get isCompact(): boolean {
        return this.getBoolAttr('compact');
    }

    get pagination(): PaginationInfo {
        return {
            currentPage: this._currentPage,
            pageSize: this._pageSize,
            totalItems: this._totalItems,
            totalPages: Math.ceil(this._totalItems / this._pageSize),
        };
    }

    get selectedRows(): T[] {
        return this._data.filter(row => this._selectedIds.has(this.getRowId(row)));
    }

    // ===================== Public API =====================

    /**
     * Set column configuration
     */
    setColumns(columns: ColumnDefinition<T>[]): void {
        this._columns = columns;
        if (this._mounted) this.render();
    }

    /**
     * Set bulk action buttons
     */
    setBulkActions(actions: BulkAction[]): void {
        this._bulkActions = actions;
        if (this._mounted) this.render();
    }

    /**
     * Set row action buttons
     */
    setRowActions(actions: RowAction[]): void {
        this._rowActions = actions;
        if (this._mounted) this.render();
    }

    /**
     * Set data directly
     */
    setData(data: T[]): void {
        this._data = data || [];
        this.applyFiltersAndSort();
    }

    /**
     * Add a single row
     */
    addRow(row: T): void {
        this._data.push(row);
        this.applyFiltersAndSort();
    }

    /**
     * Update a row by ID
     */
    updateRow(id: string, updates: Partial<T>): void {
        const index = this._data.findIndex(row => this.getRowId(row) === id);
        if (index !== -1) {
            this._data[index] = { ...this._data[index], ...updates } as T;
            this.applyFiltersAndSort();
        }
    }

    /**
     * Remove a row by ID
     */
    removeRow(id: string): void {
        this._data = this._data.filter(row => this.getRowId(row) !== id);
        this._selectedIds.delete(id);
        this.applyFiltersAndSort();
    }

    /**
     * Clear all data
     */
    clearData(): void {
        this._data = [];
        this._filteredData = [];
        this._selectedIds.clear();
        this._currentPage = 1;
        if (this._mounted) this.render();
    }

    /**
     * Set search term
     */
    setSearch(term: string): void {
        this._searchTerm = term;
        this._currentPage = 1;
        this.applyFiltersAndSort();
    }

    /**
     * Set filters
     */
    setFilters(filters: Record<string, unknown>): void {
        this._filters = filters;
        this._currentPage = 1;
        this.applyFiltersAndSort();
    }

    /**
     * Set sort field and direction
     */
    setSort(field: string, direction: SortDirection = 'asc'): void {
        this._sortField = field;
        this._sortDirection = direction;
        this.applyFiltersAndSort();
    }

    /**
     * Go to page
     */
    goToPage(page: number): void {
        const maxPage = Math.ceil(this._totalItems / this._pageSize);
        this._currentPage = Math.max(1, Math.min(page, maxPage));
        if (this._mounted) this.render();

        this.emitDOMEvent<PageChangeEventDetail>('page-change', {
            page: this._currentPage,
            pageSize: this._pageSize,
        });
    }

    /**
     * Set page size
     */
    setPageSize(size: number): void {
        this._pageSize = size;
        this._currentPage = 1;
        this.applyFiltersAndSort();
    }

    /**
     * Select a row
     */
    selectRow(id: string): void {
        this._selectedIds.add(id);
        this.emitSelectionChange();
        if (this._mounted) this.render();
    }

    /**
     * Deselect a row
     */
    deselectRow(id: string): void {
        this._selectedIds.delete(id);
        this.emitSelectionChange();
        if (this._mounted) this.render();
    }

    /**
     * Toggle row selection
     */
    toggleRowSelection(id: string): void {
        if (this._selectedIds.has(id)) {
            this._selectedIds.delete(id);
        } else {
            this._selectedIds.add(id);
        }
        this.emitSelectionChange();
        if (this._mounted) this.render();
    }

    /**
     * Select all rows
     */
    selectAll(): void {
        for (const row of this._filteredData) {
            this._selectedIds.add(this.getRowId(row));
        }
        this.emitSelectionChange();
        if (this._mounted) this.render();
    }

    /**
     * Deselect all rows
     */
    deselectAll(): void {
        this._selectedIds.clear();
        this.emitSelectionChange();
        if (this._mounted) this.render();
    }

    /**
     * Toggle select all
     */
    toggleSelectAll(): void {
        const allSelected = this._filteredData.every(row => this._selectedIds.has(this.getRowId(row)));

        if (allSelected) {
            this.deselectAll();
        } else {
            this.selectAll();
        }
    }

    /**
     * Set loading state
     */
    setLoading(loading: boolean): void {
        this._isLoading = loading;
        if (this._mounted) this.render();
    }

    /**
     * Refresh the table
     */
    refresh(): void {
        this.applyFiltersAndSort();
    }

    // ===================== Private Methods =====================

    private getRowId(row: T): string {
        return String(row[this.idField] ?? '');
    }

    private getNestedValue(obj: T, path: string): unknown {
        return path.split('.').reduce<unknown>((o, k) => {
            if (o && typeof o === 'object' && k in (o as Record<string, unknown>)) {
                return (o as Record<string, unknown>)[k];
            }
            return undefined;
        }, obj as unknown);
    }

    private applyFiltersAndSort(): void {
        let filtered = [...this._data];

        // Apply search
        if (this._searchTerm) {
            const term = this._searchTerm.toLowerCase();
            filtered = filtered.filter(row =>
                this._columns.some(col => {
                    if (col.filterable === false) return false;
                    const val = this.getNestedValue(row, col.key);
                    return String(val).toLowerCase().includes(term);
                })
            );
        }

        // Apply filters
        for (const [key, value] of Object.entries(this._filters)) {
            if (value !== undefined && value !== null && value !== '') {
                filtered = filtered.filter(row => {
                    const rowVal = this.getNestedValue(row, key);
                    return rowVal === value;
                });
            }
        }

        // Apply sort
        if (this._sortField) {
            const field = this._sortField;
            const dir = this._sortDirection === 'asc' ? 1 : -1;

            filtered.sort((a, b) => {
                const aVal = this.getNestedValue(a, field);
                const bVal = this.getNestedValue(b, field);

                if (aVal === bVal) return 0;
                if (aVal === null || aVal === undefined) return 1;
                if (bVal === null || bVal === undefined) return -1;

                if (typeof aVal === 'string' && typeof bVal === 'string') {
                    return aVal.localeCompare(bVal) * dir;
                }

                return ((aVal as number) < (bVal as number) ? -1 : 1) * dir;
            });
        }

        this._filteredData = filtered;
        this._totalItems = filtered.length;

        if (this._mounted) this.render();
    }

    private emitSelectionChange(): void {
        const detail: SelectionChangeEventDetail = {
            selectedIds: new Set(this._selectedIds),
            selectedRows: this.selectedRows,
        };
        this.emitDOMEvent('selection-change', detail);
        this.emit('ui:table-selection-change', detail);
    }

    private handleSort(field: string): void {
        if (this._sortField === field) {
            this._sortDirection = this._sortDirection === 'asc' ? 'desc' : 'asc';
        } else {
            this._sortField = field;
            this._sortDirection = 'asc';
        }

        this.applyFiltersAndSort();

        this.emitDOMEvent<SortChangeEventDetail>('sort-change', {
            field: this._sortField,
            direction: this._sortDirection,
        });
    }

    private handleRowClick(row: T, index: number): void {
        this.emitDOMEvent<RowClickEventDetail>('row-click', { row, index });
        this.emit('ui:table-row-click', { row, index });
    }

    private handleRowAction(action: string, row: T): void {
        this.emitDOMEvent<RowActionEventDetail>('row-action', { action, row });
        this.emit('ui:table-row-action', { action, row });
    }

    private handleBulkAction(action: BulkAction): void {
        const detail: BulkActionEventDetail = {
            action: action.id,
            selectedRows: this.selectedRows,
        };
        this.emitDOMEvent('bulk-action', detail);
        this.emit('ui:table-bulk-action', detail);
    }

    // ===================== Rendering =====================

    private formatValue(value: unknown, column: ColumnDefinition<T>): string {
        if (value === null || value === undefined) return '-';

        switch (column.type) {
            case 'date':
                return new Date(value as string).toLocaleDateString();
            case 'datetime':
                return new Date(value as string).toLocaleString();
            case 'boolean':
                return value ? 'Yes' : 'No';
            case 'number':
                return Number(value).toLocaleString();
            default:
                return String(value);
        }
    }

    private renderHeader(): string {
        const cols = this._columns.filter(c => !c.hidden);

        const selectAllCheckbox = this.isSelectable
            ? `<th class="table-select-col" style="width: 40px;">
           <input type="checkbox" class="form-check-input select-all"
                  ${this._filteredData.length > 0 && this._filteredData.every(r => this._selectedIds.has(this.getRowId(r))) ? 'checked' : ''}>
         </th>`
            : '';

        const actionsCol = this._rowActions.length > 0 ? `<th class="table-actions-col text-end">Actions</th>` : '';

        const headers = cols
            .map(col => {
                const sortable = col.sortable ? 'sortable' : '';
                const sorted = this._sortField === col.key;
                const sortIcon = sorted ? (this._sortDirection === 'asc' ? 'bi-sort-up' : 'bi-sort-down') : 'bi-chevron-expand';
                const sortBtn = col.sortable ? `<i class="${sortIcon} ms-1 opacity-50"></i>` : '';
                const width = col.width ? `style="width: ${col.width}"` : '';

                return `
        <th class="${sortable} ${sorted ? 'table-sorted' : ''}" ${width} data-key="${col.key}">
          ${col.label}${sortBtn}
        </th>
      `;
            })
            .join('');

        return `
      <thead class="table-light">
        <tr>
          ${selectAllCheckbox}
          ${headers}
          ${actionsCol}
        </tr>
      </thead>
    `;
    }

    private renderBody(): string {
        if (this._isLoading) {
            const colCount = this._columns.filter(c => !c.hidden).length + (this.isSelectable ? 1 : 0) + (this._rowActions.length > 0 ? 1 : 0);

            return `
        <tbody>
          <tr>
            <td colspan="${colCount}" class="text-center py-5">
              <div class="spinner-border text-primary" role="status">
                <span class="visually-hidden">Loading...</span>
              </div>
            </td>
          </tr>
        </tbody>
      `;
        }

        // Pagination
        const start = (this._currentPage - 1) * this._pageSize;
        const pageData = this._filteredData.slice(start, start + this._pageSize);

        if (pageData.length === 0) {
            const colCount = this._columns.filter(c => !c.hidden).length + (this.isSelectable ? 1 : 0) + (this._rowActions.length > 0 ? 1 : 0);

            return `
        <tbody>
          <tr>
            <td colspan="${colCount}" class="text-center py-5 text-muted">
              <i class="bi-inbox fs-1 d-block mb-2 opacity-50"></i>
              ${this.emptyMessage}
            </td>
          </tr>
        </tbody>
      `;
        }

        const cols = this._columns.filter(c => !c.hidden);

        const rows = pageData
            .map((row, index) => {
                const rowId = this.getRowId(row);
                const isSelected = this._selectedIds.has(rowId);

                const selectCell = this.isSelectable
                    ? `<td class="table-select-col">
             <input type="checkbox" class="form-check-input row-select" data-id="${rowId}" ${isSelected ? 'checked' : ''}>
           </td>`
                    : '';

                const cells = cols
                    .map(col => {
                        const value = this.getNestedValue(row, col.key);
                        const content = col.render ? col.render(value, row, start + index) : this.formatValue(value, col);
                        const align = col.align ? `text-${col.align}` : '';
                        const className = col.className || '';

                        return `<td class="${align} ${className}">${content}</td>`;
                    })
                    .join('');

                const actionsCell =
                    this._rowActions.length > 0
                        ? `<td class="table-actions-col text-end">
             <div class="btn-group btn-group-sm">
               ${this._rowActions
                   .filter(a => !a.condition || a.condition(row))
                   .map(a => {
                       const icon = a.icon ? `<i class="${a.icon}"></i>` : '';
                       const label = a.label || '';
                       const title = a.title ? `title="${a.title}"` : '';
                       const variant = a.variant || 'outline-secondary';
                       return `<button class="btn btn-${variant} row-action" data-action="${a.id}" data-id="${rowId}" ${title}>${icon}${label}</button>`;
                   })
                   .join('')}
             </div>
           </td>`
                        : '';

                return `
        <tr class="${isSelected ? 'table-primary' : ''}" data-id="${rowId}">
          ${selectCell}
          ${cells}
          ${actionsCell}
        </tr>
      `;
            })
            .join('');

        return `<tbody>${rows}</tbody>`;
    }

    private renderPagination(): string {
        const totalPages = Math.ceil(this._totalItems / this._pageSize);
        if (totalPages <= 1) return '';

        const start = (this._currentPage - 1) * this._pageSize + 1;
        const end = Math.min(this._currentPage * this._pageSize, this._totalItems);

        const pages: string[] = [];

        // First page
        pages.push(`
      <li class="page-item ${this._currentPage === 1 ? 'disabled' : ''}">
        <button class="page-link" data-page="1" ${this._currentPage === 1 ? 'disabled' : ''}>
          <i class="bi-chevron-double-left"></i>
        </button>
      </li>
    `);

        // Previous
        pages.push(`
      <li class="page-item ${this._currentPage === 1 ? 'disabled' : ''}">
        <button class="page-link" data-page="${this._currentPage - 1}" ${this._currentPage === 1 ? 'disabled' : ''}>
          <i class="bi-chevron-left"></i>
        </button>
      </li>
    `);

        // Page numbers (show up to 5)
        const startPage = Math.max(1, this._currentPage - 2);
        const endPage = Math.min(totalPages, startPage + 4);

        for (let i = startPage; i <= endPage; i++) {
            pages.push(`
        <li class="page-item ${i === this._currentPage ? 'active' : ''}">
          <button class="page-link" data-page="${i}">${i}</button>
        </li>
      `);
        }

        // Next
        pages.push(`
      <li class="page-item ${this._currentPage === totalPages ? 'disabled' : ''}">
        <button class="page-link" data-page="${this._currentPage + 1}" ${this._currentPage === totalPages ? 'disabled' : ''}>
          <i class="bi-chevron-right"></i>
        </button>
      </li>
    `);

        // Last page
        pages.push(`
      <li class="page-item ${this._currentPage === totalPages ? 'disabled' : ''}">
        <button class="page-link" data-page="${totalPages}" ${this._currentPage === totalPages ? 'disabled' : ''}>
          <i class="bi-chevron-double-right"></i>
        </button>
      </li>
    `);

        return `
      <div class="d-flex justify-content-between align-items-center mt-3">
        <div class="text-muted small">
          Showing ${start} to ${end} of ${this._totalItems} entries
        </div>
        <nav>
          <ul class="pagination pagination-sm mb-0">
            ${pages.join('')}
          </ul>
        </nav>
      </div>
    `;
    }

    private renderBulkActions(): string {
        if (this._bulkActions.length === 0 || this._selectedIds.size === 0) {
            return '';
        }

        const buttons = this._bulkActions
            .map(a => {
                const icon = a.icon ? `<i class="${a.icon} me-1"></i>` : '';
                const variant = a.variant || 'outline-secondary';
                return `
        <button class="btn btn-${variant} btn-sm bulk-action" data-action="${a.id}">
          ${icon}${a.label}
        </button>
      `;
            })
            .join('');

        return `
      <div class="bulk-actions d-flex align-items-center gap-2 mb-3 p-2 bg-light rounded">
        <span class="text-muted small">${this._selectedIds.size} selected</span>
        ${buttons}
        <button class="btn btn-outline-secondary btn-sm ms-auto" id="clear-selection">
          <i class="bi-x-lg me-1"></i>Clear
        </button>
      </div>
    `;
    }

    override render(): void {
        let tableClass = 'table';
        if (this.isStriped) tableClass += ' table-striped';
        if (this.isHover) tableClass += ' table-hover';
        if (this.isBordered) tableClass += ' table-bordered';
        if (this.isCompact) tableClass += ' table-sm';

        this.innerHTML = `
      ${this.renderBulkActions()}
      <div class="table-responsive">
        <table class="${tableClass}">
          ${this.renderHeader()}
          ${this.renderBody()}
        </table>
      </div>
      ${this.renderPagination()}
    `;

        this.bindTableEvents();
    }

    private bindTableEvents(): void {
        // Select all checkbox
        const selectAll = this.$('.select-all') as HTMLInputElement | null;
        selectAll?.addEventListener('change', () => this.toggleSelectAll());

        // Row select checkboxes
        const rowSelects = this.$$('.row-select') as HTMLInputElement[];
        for (const checkbox of rowSelects) {
            checkbox.addEventListener('change', () => {
                const id = checkbox.dataset.id;
                if (id) this.toggleRowSelection(id);
            });
        }

        // Row click
        const rows = this.$$('tbody tr[data-id]');
        for (const row of rows) {
            row.addEventListener('click', e => {
                // Ignore if clicking checkbox or action button
                const target = e.target as HTMLElement;
                if (target.closest('input, button')) return;

                const id = (row as HTMLElement).dataset.id;
                const rowData = this._data.find(r => this.getRowId(r) === id);
                const index = this._data.findIndex(r => this.getRowId(r) === id);
                if (rowData) this.handleRowClick(rowData, index);
            });
        }

        // Row actions
        const actionBtns = this.$$('.row-action');
        for (const btn of actionBtns) {
            btn.addEventListener('click', () => {
                const action = (btn as HTMLElement).dataset.action;
                const id = (btn as HTMLElement).dataset.id;
                const row = this._data.find(r => this.getRowId(r) === id);
                if (action && row) this.handleRowAction(action, row);
            });
        }

        // Bulk actions
        const bulkBtns = this.$$('.bulk-action');
        for (const btn of bulkBtns) {
            btn.addEventListener('click', () => {
                const actionId = (btn as HTMLElement).dataset.action;
                const action = this._bulkActions.find(a => a.id === actionId);
                if (action) this.handleBulkAction(action);
            });
        }

        // Clear selection
        const clearBtn = this.$('#clear-selection');
        clearBtn?.addEventListener('click', () => this.deselectAll());

        // Sortable headers
        const sortableHeaders = this.$$('th.sortable');
        for (const th of sortableHeaders) {
            th.addEventListener('click', () => {
                const key = (th as HTMLElement).dataset.key;
                if (key) this.handleSort(key);
            });
        }

        // Pagination
        const pageLinks = this.$$('.page-link[data-page]');
        for (const link of pageLinks) {
            link.addEventListener('click', () => {
                const page = parseInt((link as HTMLElement).dataset.page || '1', 10);
                this.goToPage(page);
            });
        }
    }
}

// Register custom element
if (!customElements.get('ui-data-table')) {
    customElements.define('ui-data-table', DataTable);
}

export default DataTable;
