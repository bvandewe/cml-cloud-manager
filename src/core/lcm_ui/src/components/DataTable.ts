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
import type { ExpandableRowConfig, SchemaColumn } from '../types/columns.js';
import { resolveAttrValue } from '../types/columns.js';

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

    // ── Schema-driven extensions (B1) ──

    /** Alias for key (used in column registries) */
    field?: string;
    /** Column group name for two-level headers */
    group?: string;
    /** Default visibility (true = shown by default). Inverse of hidden. */
    visible?: boolean;
    /** Pin column to left or right edge */
    pinned?: 'left' | 'right';
    /** Allow column resize (future) */
    resizable?: boolean;
    /** Tooltip text on column header */
    description?: string;
    /** Category for column picker grouping */
    category?: string;
    /** Custom element tag to render the cell content */
    component?: string;
    /** Attribute mapping for the component (see SchemaColumn docs) */
    componentAttrs?: Record<string, string | boolean>;
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
        return ['page-size', 'selectable', 'loading', 'empty-message', 'id-field', 'striped', 'hover', 'bordered', 'compact', 'table-id', 'show-column-picker'];
    }

    // Data state
    private _data: T[] = [];
    private _filteredData: T[] = [];
    private _columns: ColumnDefinition<T>[] = [];
    private _bulkActions: BulkAction[] = [];
    private _rowActions: RowAction[] = [];

    // Column visibility state (B2)
    private _columnVisibility: Map<string, boolean> = new Map();
    private _defaultVisibleColumns: string[] = [];

    // Expandable row state (B4)
    private _expandedRowIds: Set<string> = new Set();
    private _expandableConfig: ExpandableRowConfig<T> | null = null;

    // Column groups (B5)
    private _columnGroups: Map<string, string[]> = new Map();

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
        this.loadColumnVisibility();
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

    // ── Schema-driven column API (B1/B2) ──

    /**
     * Set schema-driven column configuration with default visibility.
     * Accepts a record of SchemaColumn definitions keyed by column ID.
     */
    setSchemaColumns(columns: Record<string, SchemaColumn<T>>, defaults?: string[]): void {
        this._columns = Object.entries(columns).map(([key, col]) => ({
            ...col,
            key: col.field || key,
        }));

        if (defaults) {
            this._defaultVisibleColumns = defaults;
            for (const col of this._columns) {
                const colKey = col.field || col.key;
                if (!this._columnVisibility.has(colKey)) {
                    this._columnVisibility.set(colKey, defaults.includes(colKey));
                }
            }
        }

        this._columnGroups.clear();
        for (const col of this._columns) {
            if (col.group) {
                const existing = this._columnGroups.get(col.group) || [];
                existing.push(col.field || col.key);
                this._columnGroups.set(col.group, existing);
            }
        }

        if (this._mounted) this.render();
    }

    /**
     * Set visibility for a single column.
     */
    setColumnVisibility(columnKey: string, visible: boolean): void {
        this._columnVisibility.set(columnKey, visible);
        this.saveColumnVisibility();
        if (this._mounted) this.render();
    }

    /**
     * Set visibility for multiple columns at once.
     */
    setColumnsVisibility(visibility: Record<string, boolean>): void {
        for (const [key, visible] of Object.entries(visibility)) {
            this._columnVisibility.set(key, visible);
        }
        this.saveColumnVisibility();
        if (this._mounted) this.render();
    }

    /**
     * Reset column visibility to defaults.
     */
    resetColumnVisibility(): void {
        this._columnVisibility.clear();
        if (this._defaultVisibleColumns.length > 0) {
            for (const col of this._columns) {
                const key = col.field || col.key;
                this._columnVisibility.set(key, this._defaultVisibleColumns.includes(key));
            }
        }
        this.saveColumnVisibility();
        if (this._mounted) this.render();
    }

    // ── Expandable rows API (B4) ──

    /**
     * Configure expandable row detail rendering.
     */
    setExpandableConfig(config: ExpandableRowConfig<T>): void {
        this._expandableConfig = config;
        if (this._mounted) this.render();
    }

    /**
     * Toggle expansion of a specific row.
     */
    toggleRowExpand(rowId: string): void {
        if (this._expandedRowIds.has(rowId)) {
            this._expandedRowIds.delete(rowId);
        } else {
            this._expandedRowIds.add(rowId);
        }
        if (this._mounted) this.render();
    }

    /**
     * Collapse all expanded rows.
     */
    collapseAllRows(): void {
        this._expandedRowIds.clear();
        if (this._mounted) this.render();
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

    // ── Column visibility helpers (B2/B6) ──

    /**
     * Get columns that should be visible, respecting visibility map and column config.
     */
    private getVisibleColumns(): ColumnDefinition<T>[] {
        return this._columns.filter(col => {
            const key = col.field || col.key;
            if (this._columnVisibility.has(key)) {
                return this._columnVisibility.get(key);
            }
            if (col.visible !== undefined) return col.visible;
            if (col.hidden !== undefined) return !col.hidden;
            return true;
        });
    }

    private get tableId(): string {
        return this.getAttr('table-id', '');
    }

    private get showColumnPicker(): boolean {
        return this.getBoolAttr('show-column-picker');
    }

    /**
     * Total column count including utility columns (select, expand, actions).
     */
    private getTotalColumnCount(): number {
        return this.getVisibleColumns().length + (this.isSelectable ? 1 : 0) + (this._rowActions.length > 0 ? 1 : 0) + (this._expandableConfig ? 1 : 0);
    }

    private loadColumnVisibility(): void {
        if (!this.tableId) return;
        try {
            const stored = localStorage.getItem(`lcm.columns.${this.tableId}`);
            if (stored) {
                const visibility = JSON.parse(stored) as Record<string, boolean>;
                this._columnVisibility = new Map(Object.entries(visibility));
            }
        } catch {
            /* ignore corrupted localStorage data */
        }
    }

    private saveColumnVisibility(): void {
        if (!this.tableId) return;
        const obj: Record<string, boolean> = {};
        this._columnVisibility.forEach((v, k) => {
            obj[k] = v;
        });
        localStorage.setItem(`lcm.columns.${this.tableId}`, JSON.stringify(obj));
    }

    // ── Component cell rendering (B3) ──

    /**
     * Render cell content: custom render function > component element > formatted value.
     */
    private renderCellContent(col: ColumnDefinition<T>, value: unknown, row: T, index: number): string {
        if (col.render) {
            return col.render(value, row, index);
        }
        if (col.component) {
            return this.renderComponentCell(col, row);
        }
        return this.formatValue(value, col);
    }

    /**
     * Render a custom element for a cell using component + componentAttrs.
     */
    private renderComponentCell(col: ColumnDefinition<T>, row: T): string {
        const tag = col.component!;
        const attrParts: string[] = [];

        if (col.componentAttrs) {
            for (const [attrName, attrValue] of Object.entries(col.componentAttrs)) {
                const resolved = resolveAttrValue(attrValue, row as Record<string, unknown>);
                if (typeof resolved === 'boolean') {
                    if (resolved) attrParts.push(attrName);
                } else if (resolved !== null && resolved !== undefined) {
                    attrParts.push(`${attrName}="${String(resolved).replace(/"/g, '&quot;')}"`);
                }
            }
        }

        return `<${tag} ${attrParts.join(' ')}></${tag}>`;
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
        const cols = this.getVisibleColumns();

        // Expand column header (B4)
        const expandCol = this._expandableConfig ? `<th class="table-expand-col" style="width: 30px;" aria-label="Expand"></th>` : '';

        const selectAllCheckbox = this.isSelectable
            ? `<th class="table-select-col" style="width: 40px;">
           <input type="checkbox" class="form-check-input select-all"
                  ${this._filteredData.length > 0 && this._filteredData.every(r => this._selectedIds.has(this.getRowId(r))) ? 'checked' : ''}>
         </th>`
            : '';

        const actionsCol = this._rowActions.length > 0 ? `<th class="table-actions-col text-end">Actions</th>` : '';

        const headers = cols
            .map(col => {
                const colKey = col.field || col.key;
                const sortable = col.sortable ? 'sortable' : '';
                const sorted = this._sortField === colKey;
                const sortIcon = sorted ? (this._sortDirection === 'asc' ? 'bi-sort-up' : 'bi-sort-down') : 'bi-chevron-expand';
                const sortBtn = col.sortable ? `<i class="${sortIcon} ms-1 opacity-50"></i>` : '';
                const width = col.width ? `style="width: ${col.width}"` : '';
                const tooltip = col.description ? `title="${col.description}"` : '';

                return `
        <th class="${sortable} ${sorted ? 'table-sorted' : ''}" ${width} ${tooltip} data-key="${colKey}">
          ${col.label}${sortBtn}
        </th>
      `;
            })
            .join('');

        // Column group header row (B5)
        const groupHeaderRow = this.renderGroupHeaders(cols);

        return `
      <thead class="table-light">
        ${groupHeaderRow}
        <tr>
          ${expandCol}
          ${selectAllCheckbox}
          ${headers}
          ${actionsCol}
        </tr>
      </thead>
    `;
    }

    /**
     * Render column group header row (B5).
     * Returns empty string if no columns have groups defined.
     */
    private renderGroupHeaders(cols: ColumnDefinition<T>[]): string {
        const hasGroups = cols.some(c => c.group);
        if (!hasGroups) return '';

        const groups: { name: string; colspan: number }[] = [];
        let currentGroup = '';
        let currentSpan = 0;

        for (const col of cols) {
            const group = col.group || '';
            if (group === currentGroup) {
                currentSpan++;
            } else {
                if (currentSpan > 0) {
                    groups.push({ name: currentGroup, colspan: currentSpan });
                }
                currentGroup = group;
                currentSpan = 1;
            }
        }
        if (currentSpan > 0) {
            groups.push({ name: currentGroup, colspan: currentSpan });
        }

        const expandPlaceholder = this._expandableConfig ? '<th></th>' : '';
        const selectPlaceholder = this.isSelectable ? '<th></th>' : '';
        const actionsPlaceholder = this._rowActions.length > 0 ? '<th></th>' : '';

        const groupCells = groups.map(g => (g.name ? `<th colspan="${g.colspan}" class="text-center border-bottom-0 fw-semibold text-muted small">${g.name}</th>` : `<th colspan="${g.colspan}" class="border-bottom-0"></th>`)).join('');

        return `
        <tr class="table-group-header">
            ${expandPlaceholder}
            ${selectPlaceholder}
            ${groupCells}
            ${actionsPlaceholder}
        </tr>`;
    }

    private renderBody(): string {
        if (this._isLoading) {
            const colCount = this.getTotalColumnCount();

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
            const colCount = this.getTotalColumnCount();

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

        const cols = this.getVisibleColumns();

        const rows = pageData
            .map((row, index) => {
                const rowId = this.getRowId(row);
                const isSelected = this._selectedIds.has(rowId);
                const isExpanded = this._expandedRowIds.has(rowId);

                // Expand toggle cell (B4)
                const expandCell = this._expandableConfig
                    ? `<td class="table-expand-col">
             <button class="btn btn-link btn-sm p-0 row-expand" data-id="${rowId}"
                     aria-label="${isExpanded ? 'Collapse' : 'Expand'} row details"
                     aria-expanded="${isExpanded}">
               <i class="bi-chevron-${isExpanded ? 'down' : 'right'}"></i>
             </button>
           </td>`
                    : '';

                const selectCell = this.isSelectable
                    ? `<td class="table-select-col">
             <input type="checkbox" class="form-check-input row-select" data-id="${rowId}" ${isSelected ? 'checked' : ''}>
           </td>`
                    : '';

                const cells = cols
                    .map(col => {
                        const colKey = (col.field || col.key) as string;
                        const value = this.getNestedValue(row, colKey);
                        const content = this.renderCellContent(col, value, row, start + index);
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
                       const tooltip = a.title || a.label || a.id;
                       const variant = a.variant || 'outline-secondary';
                       return `<button class="btn btn-${variant} row-action p-1" data-action="${a.id}" data-id="${rowId}" title="${tooltip}">${icon}</button>`;
                   })
                   .join('')}
             </div>
           </td>`
                        : '';

                // Main data row
                const mainRow = `
        <tr class="${isSelected ? 'table-primary' : ''}" data-id="${rowId}">
          ${expandCell}
          ${selectCell}
          ${cells}
          ${actionsCell}
        </tr>`;

                // Expandable detail row (B4)
                const detailRow =
                    this._expandableConfig && isExpanded
                        ? `<tr class="table-detail-row" data-detail-for="${rowId}">
             <td colspan="${this.getTotalColumnCount()}" class="p-0">
               <div class="p-3 bg-light border-top">${this._expandableConfig.renderDetail(row)}</div>
             </td>
           </tr>`
                        : '';

                return mainRow + detailRow;
            })
            .join('');

        return `<tbody>${rows}</tbody>`;
    }

    private renderPagination(): string {
        const totalPages = Math.ceil(this._totalItems / this._pageSize);

        // Always show a footer with item count
        if (totalPages <= 1) {
            if (this._totalItems === 0) return '';
            return `
      <div class="d-flex justify-content-between align-items-center mt-2 px-2">
        <div class="text-muted small">
          ${this._totalItems} ${this._totalItems === 1 ? 'entry' : 'entries'}
        </div>
      </div>
    `;
        }

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

        // Column picker toolbar (B2)
        const columnPickerHtml =
            this.showColumnPicker && this.tableId
                ? `<div class="d-flex justify-content-end mb-2">
                <ui-column-picker table-id="${this.tableId}"></ui-column-picker>
              </div>`
                : '';

        this.innerHTML = `
      ${this.renderBulkActions()}
      ${columnPickerHtml}
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

        // Expand toggle buttons (B4)
        const expandBtns = this.$$('.row-expand');
        for (const btn of expandBtns) {
            btn.addEventListener('click', e => {
                e.stopPropagation();
                const id = (btn as HTMLElement).dataset.id;
                if (id) this.toggleRowExpand(id);
            });
        }

        // Column picker integration (B2)
        const picker = this.$('ui-column-picker');
        if (picker) {
            picker.addEventListener('columns-changed', ((e: CustomEvent) => {
                const visibility = e.detail?.visibility as Record<string, boolean> | undefined;
                if (visibility) {
                    this.setColumnsVisibility(visibility);
                }
            }) as EventListener);

            // Provide column definitions to the picker
            const pickerEl = picker as HTMLElement & { setColumns?: (cols: ColumnDefinition<T>[], defaults?: string[]) => void };
            if (typeof pickerEl.setColumns === 'function') {
                pickerEl.setColumns(this._columns, this._defaultVisibleColumns);
            }
        }
    }
}

// Register custom element
if (!customElements.get('ui-data-table')) {
    customElements.define('ui-data-table', DataTable);
}

export default DataTable;
