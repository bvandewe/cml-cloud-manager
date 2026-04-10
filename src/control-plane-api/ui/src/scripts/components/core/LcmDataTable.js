/**
 * LcmDataTable - Interactive Data Table Web Component
 *
 * A full-featured data table with filtering, sorting, pagination, row selection,
 * and bulk actions. Supports both static data and API-driven data sources.
 *
 * Usage:
 *   <lcm-data-table
 *     id="workers-table"
 *     data-source="/api/workers"
 *     page-size="25"
 *     selectable>
 *   </lcm-data-table>
 *
 * Configure columns and actions via JavaScript:
 *   const table = document.getElementById('workers-table');
 *   table.setColumns([...]);
 *   table.setBulkActions([...]);
 *
 * Events:
 *   - 'row-action': { action, row }
 *   - 'bulk-action': { action, selectedRows }
 *   - 'selection-change': { selectedIds }
 *   - 'row-click': { row }
 *
 * @module components/core/LcmDataTable
 */

import { BaseComponent } from '../../core/BaseComponent.js';
import { eventBus, EventTypes } from '../../core/EventBus.js';

export class LcmDataTable extends BaseComponent {
    static get observedAttributes() {
        return ['data-source', 'page-size', 'selectable', 'loading', 'empty-message', 'panel-mode', 'no-toolbar'];
    }

    constructor() {
        super();

        // Data state
        this._data = [];
        this._filteredData = [];
        this._columns = [];
        this._bulkActions = [];
        this._rowActions = [];

        // Selection state
        this._selectedIds = new Set();

        // Pagination state
        this._currentPage = 1;
        this._pageSize = 25;
        this._totalItems = 0;

        // Sorting state
        this._sortField = null;
        this._sortDirection = 'asc';

        // Filter state
        this._filters = {};
        this._searchTerm = '';

        // Loading state
        this._isLoading = false;

        // Debounce timer for search
        this._searchDebounce = null;

        // Delegated click handler (bound once, survives re-renders)
        this._delegatedClickHandler = this._onDelegatedClick.bind(this);
    }

    onMount() {
        this._pageSize = parseInt(this.getAttribute('page-size') || '25', 10);

        // Add delegated click handler once — survives innerHTML replacements
        this.addEventListener('click', this._delegatedClickHandler);

        this.render();

        // Load data if source provided
        const dataSource = this.getAttribute('data-source');
        if (dataSource) {
            this.loadData();
        }
    }

    onUnmount() {
        this.removeEventListener('click', this._delegatedClickHandler);
    }

    /**
     * Delegated click handler — catches all clicks inside the component.
     * Uses event delegation to handle action buttons, sort headers, pagination,
     * row clicks, and bulk actions without needing to re-bind after each render.
     */
    _onDelegatedClick(e) {
        const target = e.target;

        // Row action buttons (.lcm-row-action)
        const actionBtn = target.closest('.lcm-row-action');
        if (actionBtn && this.contains(actionBtn)) {
            e.stopPropagation();
            const rowId = actionBtn.dataset.rowId;
            const action = actionBtn.dataset.action;
            const row = this._data.find(r => String(this._getRowId(r)) === String(rowId));
            if (row) {
                this._handleRowAction(action, row);
            } else {
                console.warn(`[LcmDataTable#${this.id}] Row not found for rowId="${rowId}", action="${action}". Data has ${this._data.length} rows.`);
            }
            return;
        }

        // Sort headers
        const sortHeader = target.closest('[data-sort]');
        if (sortHeader && this.contains(sortHeader)) {
            this._handleSort(sortHeader.dataset.sort);
            return;
        }

        // Page buttons
        const pageBtn = target.closest('.lcm-page-btn');
        if (pageBtn && this.contains(pageBtn)) {
            const page = parseInt(pageBtn.dataset.page, 10);
            if (page >= 1 && page <= this._getTotalPages()) {
                this._handlePageChange(page);
            }
            return;
        }

        // Bulk action buttons
        const bulkBtn = target.closest('.lcm-bulk-action');
        if (bulkBtn && this.contains(bulkBtn)) {
            this._handleBulkAction(bulkBtn.dataset.action);
            return;
        }

        // Row click (but not on checkboxes, action buttons, [data-action], or interactive links [role="button"])
        const rowEl = target.closest('.lcm-row');
        if (rowEl && this.contains(rowEl)) {
            if (target.closest('.lcm-row-select') || target.closest('.lcm-row-action') || target.closest('[data-action]') || target.closest('[role="button"]') || target.closest('a[href]')) {
                return;
            }
            const rowId = rowEl.dataset.rowId;
            const rowData = this._data.find(r => String(this._getRowId(r)) === String(rowId));
            if (rowData) {
                this._handleRowClick(rowData);
            }
        }
    }

    onAttributeChange(name, oldValue, newValue) {
        if (name === 'page-size') {
            this._pageSize = parseInt(newValue || '25', 10);
            this._currentPage = 1;
            this._applyFiltersAndSort();
        } else if (name === 'loading') {
            this._isLoading = newValue !== null;
            this.render();
        }
    }

    // ==================== Public API ====================

    /**
     * Set column configuration
     * @param {Array} columns - Column definitions
     * Example: [
     *   { field: 'name', label: 'Name', sortable: true, width: '200px' },
     *   { field: 'status', label: 'Status', render: (val, row) => `<lcm-status-badge status="${val}">` },
     *   { field: 'created_at', label: 'Created', sortable: true, type: 'datetime' }
     * ]
     */
    setColumns(columns) {
        this._columns = columns;
        this.render();
    }

    /**
     * Set bulk action buttons
     * @param {Array} actions - Action definitions
     * Example: [
     *   { id: 'delete', label: 'Delete', icon: 'bi-trash', variant: 'danger', confirm: true },
     *   { id: 'start', label: 'Start', icon: 'bi-play', variant: 'success' }
     * ]
     */
    setBulkActions(actions) {
        this._bulkActions = actions;
        this.render();
    }

    /**
     * Set row action buttons (shown in each row)
     * @param {Array} actions - Action definitions
     * Example: [
     *   { id: 'edit', icon: 'bi-pencil', title: 'Edit' },
     *   { id: 'delete', icon: 'bi-trash', title: 'Delete', variant: 'danger' }
     * ]
     */
    setRowActions(actions) {
        this._rowActions = actions;
        this.render();
    }

    /**
     * Set data directly (instead of loading from API)
     * @param {Array} data - Array of row objects
     */
    setData(data) {
        this._data = data || [];
        this._applyFiltersAndSort();
    }

    /**
     * Add a single row to the table
     * @param {Object} row - Row data
     */
    addRow(row) {
        this._data.push(row);
        this._applyFiltersAndSort();
    }

    /**
     * Set a filter on a specific field
     * @param {string} field - Field name to filter
     * @param {string|Array} value - Filter value(s)
     */
    setFilter(field, value) {
        if (value === '' || value === undefined || value === null) {
            delete this._filters[field];
        } else {
            this._filters[field] = value;
        }
        this._currentPage = 1;
        this._applyFiltersAndSort();

        this.dispatchEvent(
            new CustomEvent('filter-change', {
                detail: { search: this._searchTerm, filters: this._filters },
                bubbles: true,
            })
        );
    }

    /**
     * Set search term for global text search
     * @param {string} term - Search term
     */
    setSearch(term) {
        this._searchTerm = term || '';
        this._currentPage = 1;
        this._applyFiltersAndSort();

        this.dispatchEvent(
            new CustomEvent('filter-change', {
                detail: { search: this._searchTerm, filters: this._filters },
                bubbles: true,
            })
        );
    }

    /**
     * Clear all filters and search
     */
    clearFilters() {
        this._filters = {};
        this._searchTerm = '';
        this._currentPage = 1;
        this._applyFiltersAndSort();
    }

    /**
     * Update a row by ID
     * @param {string} id - Row ID
     * @param {Object} updates - Fields to update
     */
    updateRow(id, updates) {
        const rowIndex = this._data.findIndex(r => this._getRowId(r) === id);
        if (rowIndex >= 0) {
            this._data[rowIndex] = { ...this._data[rowIndex], ...updates };
            this._applyFiltersAndSort();
        }
    }

    /**
     * Remove a row by ID
     * @param {string} id - Row ID
     */
    removeRow(id) {
        this._data = this._data.filter(r => this._getRowId(r) !== id);
        this._selectedIds.delete(id);
        this._applyFiltersAndSort();
    }

    /**
     * Get currently selected rows
     * @returns {Array} Selected row objects
     */
    getSelectedRows() {
        return this._data.filter(row => this._selectedIds.has(this._getRowId(row)));
    }

    /**
     * Clear all selections
     */
    clearSelection() {
        this._selectedIds.clear();
        this._emitSelectionChange();
        this.render();
    }

    /**
     * Reload data from source
     */
    async loadData() {
        const dataSource = this.getAttribute('data-source');
        if (!dataSource) return;

        this._isLoading = true;
        this.render();

        try {
            const response = await fetch(dataSource, {
                credentials: 'include',
                headers: { Accept: 'application/json' },
            });

            if (!response.ok) {
                throw new Error(`Failed to load data: ${response.status}`);
            }

            const data = await response.json();
            this._data = Array.isArray(data) ? data : data.items || data.data || [];
            this._applyFiltersAndSort();
        } catch (error) {
            console.error('[LcmDataTable] Load error:', error);
            this._data = [];
            this._filteredData = [];
        } finally {
            this._isLoading = false;
            this.render();
        }
    }

    // ==================== Private Methods ====================

    _getRowId(row) {
        const id = row.id || row._id || row.worker_id || row.instance_id || row.definition_id;
        return id != null ? String(id) : '';
    }

    _applyFiltersAndSort() {
        let data = [...this._data];

        // Apply search filter
        if (this._searchTerm) {
            const term = this._searchTerm.toLowerCase();
            data = data.filter(row => Object.values(row).some(val => String(val).toLowerCase().includes(term)));
        }

        // Apply column filters
        Object.entries(this._filters).forEach(([field, value]) => {
            if (value !== undefined && value !== '') {
                data = data.filter(row => {
                    const rowValue = row[field];
                    if (Array.isArray(value)) {
                        return value.includes(rowValue);
                    }
                    return String(rowValue).toLowerCase().includes(String(value).toLowerCase());
                });
            }
        });

        // Apply sorting
        if (this._sortField) {
            data.sort((a, b) => {
                let aVal = a[this._sortField];
                let bVal = b[this._sortField];

                // Handle null/undefined
                if (aVal == null) aVal = '';
                if (bVal == null) bVal = '';

                // Compare
                let result = 0;
                if (typeof aVal === 'number' && typeof bVal === 'number') {
                    result = aVal - bVal;
                } else {
                    result = String(aVal).localeCompare(String(bVal));
                }

                return this._sortDirection === 'desc' ? -result : result;
            });
        }

        this._filteredData = data;
        this._totalItems = data.length;

        // Reset to page 1 if current page is out of range
        const maxPage = Math.ceil(this._totalItems / this._pageSize) || 1;
        if (this._currentPage > maxPage) {
            this._currentPage = 1;
        }

        this.render();
    }

    _getPageData() {
        const start = (this._currentPage - 1) * this._pageSize;
        const end = start + this._pageSize;
        return this._filteredData.slice(start, end);
    }

    _getTotalPages() {
        return Math.ceil(this._totalItems / this._pageSize) || 1;
    }

    _handleSort(field) {
        if (this._sortField === field) {
            this._sortDirection = this._sortDirection === 'asc' ? 'desc' : 'asc';
        } else {
            this._sortField = field;
            this._sortDirection = 'asc';
        }
        this._applyFiltersAndSort();

        this.dispatchEvent(
            new CustomEvent('sort-change', {
                detail: { field: this._sortField, direction: this._sortDirection },
                bubbles: true,
            })
        );
    }

    _handleSearch(term) {
        clearTimeout(this._searchDebounce);
        this._searchDebounce = setTimeout(() => {
            this._searchTerm = term;
            this._currentPage = 1;
            this._applyFiltersAndSort();

            this.dispatchEvent(
                new CustomEvent('filter-change', {
                    detail: { search: term, filters: this._filters },
                    bubbles: true,
                })
            );
        }, 300);
    }

    _handlePageChange(page) {
        this._currentPage = page;
        this.render();

        this.dispatchEvent(
            new CustomEvent('page-change', {
                detail: { page, pageSize: this._pageSize },
                bubbles: true,
            })
        );
    }

    _handlePageSizeChange(size) {
        this._pageSize = size;
        this._currentPage = 1;
        this._applyFiltersAndSort();
    }

    _handleRowSelect(id, checked) {
        if (checked) {
            this._selectedIds.add(id);
        } else {
            this._selectedIds.delete(id);
        }
        this._emitSelectionChange();
        this.render();
    }

    _handleSelectAll(checked) {
        const pageData = this._getPageData();
        pageData.forEach(row => {
            const id = this._getRowId(row);
            if (checked) {
                this._selectedIds.add(id);
            } else {
                this._selectedIds.delete(id);
            }
        });
        this._emitSelectionChange();
        this.render();
    }

    _emitSelectionChange() {
        this.dispatchEvent(
            new CustomEvent('selection-change', {
                detail: { selectedIds: Array.from(this._selectedIds) },
                bubbles: true,
            })
        );
    }

    _handleRowAction(action, row) {
        this.dispatchEvent(
            new CustomEvent('row-action', {
                detail: { action, row },
                bubbles: true,
            })
        );
    }

    _handleBulkAction(action) {
        const selectedRows = this.getSelectedRows();
        this.dispatchEvent(
            new CustomEvent('bulk-action', {
                detail: { action, selectedRows },
                bubbles: true,
            })
        );
    }

    _handleRowClick(row) {
        this.dispatchEvent(
            new CustomEvent('row-click', {
                detail: { row },
                bubbles: true,
            })
        );
    }

    // ==================== Rendering ====================

    render() {
        const isSelectable = this.hasAttribute('selectable');
        const isPanelMode = this.hasAttribute('panel-mode');
        const noToolbar = this.hasAttribute('no-toolbar');
        const emptyMessage = this.getAttribute('empty-message') || 'No data available';

        this.innerHTML = `
            <div class="lcm-data-table-container">
                ${isPanelMode || noToolbar ? '' : this._renderToolbar()}
                <div class="table-responsive">
                    <table class="table table-hover table-striped align-middle mb-0">
                        ${this._renderHeader(isSelectable)}
                        ${this._renderBody(isSelectable, emptyMessage)}
                    </table>
                </div>
                ${this._renderPagination(isPanelMode)}
            </div>
        `;

        this._bindEvents();
    }

    _renderToolbar() {
        const hasSelection = this._selectedIds.size > 0;

        return `
            <div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
                <div class="d-flex align-items-center gap-2">
                    <!-- Search -->
                    <div class="input-group" style="width: 250px;">
                        <span class="input-group-text"><i class="bi bi-search"></i></span>
                        <input type="text"
                               class="form-control lcm-search-input"
                               placeholder="Search..."
                               value="${this._searchTerm}">
                    </div>

                    <!-- Bulk actions (shown when items selected) -->
                    ${hasSelection ? this._renderBulkActions() : ''}
                </div>

                <div class="d-flex align-items-center gap-2">
                    <!-- Selection info -->
                    ${hasSelection ? `<span class="text-muted">${this._selectedIds.size} selected</span>` : ''}

                    <!-- Refresh button -->
                    <button class="btn btn-outline-secondary btn-sm lcm-refresh-btn" title="Refresh">
                        <i class="bi bi-arrow-clockwise"></i>
                    </button>
                </div>
            </div>
        `;
    }

    _renderBulkActions() {
        if (this._bulkActions.length === 0) return '';

        const buttons = this._bulkActions
            .map(
                action => `
            <button class="btn btn-sm btn-${action.variant || 'outline-secondary'} lcm-bulk-action"
                    data-action="${action.id}"
                    title="${action.label}">
                ${action.icon ? `<i class="${action.icon} me-1"></i>` : ''}${action.label}
            </button>
        `
            )
            .join('');

        return `<div class="btn-group">${buttons}</div>`;
    }

    _renderHeader(isSelectable) {
        const headers = this._columns
            .map(col => {
                const sortIcon = this._sortField === col.field ? (this._sortDirection === 'asc' ? 'bi-sort-up' : 'bi-sort-down') : 'bi-arrow-down-up opacity-25';

                const sortable = col.sortable ? `class="sortable" role="button" data-sort="${col.field}"` : '';

                const width = col.width ? `style="width: ${col.width}"` : '';

                return `
                <th ${sortable} ${width}>
                    ${col.label}
                    ${col.sortable ? `<i class="${sortIcon} ms-1"></i>` : ''}
                </th>
            `;
            })
            .join('');

        const actionsHeader = this._rowActions.length > 0 ? '<th style="width: 100px;">Actions</th>' : '';

        const pageData = this._getPageData();
        const allSelected = pageData.length > 0 && pageData.every(r => this._selectedIds.has(this._getRowId(r)));

        return `
            <thead class="table-light">
                <tr>
                    ${
                        isSelectable
                            ? `
                        <th style="width: 40px;">
                            <input type="checkbox" class="form-check-input lcm-select-all" ${allSelected ? 'checked' : ''}>
                        </th>
                    `
                            : ''
                    }
                    ${headers}
                    ${actionsHeader}
                </tr>
            </thead>
        `;
    }

    _renderBody(isSelectable, emptyMessage) {
        if (this._isLoading) {
            return `
                <tbody>
                    <tr>
                        <td colspan="${this._columns.length + (isSelectable ? 1 : 0) + (this._rowActions.length > 0 ? 1 : 0)}"
                            class="text-center py-4">
                            <div class="spinner-border text-primary" role="status">
                                <span class="visually-hidden">Loading...</span>
                            </div>
                        </td>
                    </tr>
                </tbody>
            `;
        }

        const pageData = this._getPageData();

        if (pageData.length === 0) {
            return `
                <tbody>
                    <tr>
                        <td colspan="${this._columns.length + (isSelectable ? 1 : 0) + (this._rowActions.length > 0 ? 1 : 0)}"
                            class="text-center text-muted py-4">
                            <i class="bi bi-inbox fs-1 d-block mb-2"></i>
                            ${emptyMessage}
                        </td>
                    </tr>
                </tbody>
            `;
        }

        const rows = pageData
            .map(row => {
                const id = this._getRowId(row);
                const isSelected = this._selectedIds.has(id);

                const cells = this._columns
                    .map(col => {
                        const value = row[col.field];
                        let content = value;

                        // Custom render function
                        if (col.render) {
                            content = col.render(value, row);
                        } else if (col.type === 'datetime' && value) {
                            content = new Date(value).toLocaleString();
                        } else if (col.type === 'date' && value) {
                            content = new Date(value).toLocaleDateString();
                        } else if (col.type === 'boolean') {
                            content = value ? '<i class="bi bi-check-lg text-success"></i>' : '<i class="bi bi-x-lg text-danger"></i>';
                        } else if (value === null || value === undefined) {
                            content = '<span class="text-muted">—</span>';
                        }

                        return `<td>${content}</td>`;
                    })
                    .join('');

                const actions = this._rowActions.length > 0 ? `<td>${this._renderRowActions(row)}</td>` : '';

                return `
                <tr data-row-id="${id}" class="${isSelected ? 'table-primary' : ''} lcm-row">
                    ${
                        isSelectable
                            ? `
                        <td>
                            <input type="checkbox"
                                   class="form-check-input lcm-row-select"
                                   data-id="${id}"
                                   ${isSelected ? 'checked' : ''}>
                        </td>
                    `
                            : ''
                    }
                    ${cells}
                    ${actions}
                </tr>
            `;
            })
            .join('');

        return `<tbody>${rows}</tbody>`;
    }

    _renderRowActions(row) {
        return this._rowActions
            .map(action => {
                const variant = action.variant || 'link';
                const disabled = action.disabled?.(row) ? 'disabled' : '';

                return `
                <button class="btn btn-sm btn-${variant} lcm-row-action p-1"
                        data-action="${action.id}"
                        data-row-id="${this._getRowId(row)}"
                        title="${action.title || action.id}"
                        ${disabled}>
                    <i class="${action.icon}"></i>
                </button>
            `;
            })
            .join('');
    }

    _renderPagination(isPanelMode = false) {
        const totalPages = this._getTotalPages();
        const start = (this._currentPage - 1) * this._pageSize + 1;
        const end = Math.min(this._currentPage * this._pageSize, this._totalItems);

        if (this._totalItems === 0) {
            return '';
        }

        // Generate page numbers
        const pageNumbers = [];
        const maxVisiblePages = 5;
        let startPage = Math.max(1, this._currentPage - Math.floor(maxVisiblePages / 2));
        let endPage = Math.min(totalPages, startPage + maxVisiblePages - 1);

        if (endPage - startPage < maxVisiblePages - 1) {
            startPage = Math.max(1, endPage - maxVisiblePages + 1);
        }

        for (let i = startPage; i <= endPage; i++) {
            pageNumbers.push(i);
        }

        const pagesHtml = pageNumbers
            .map(
                num => `
            <li class="page-item ${num === this._currentPage ? 'active' : ''}">
                <button class="page-link lcm-page-btn" data-page="${num}">${num}</button>
            </li>
        `
            )
            .join('');

        const paginationContent = `
            <div class="d-flex justify-content-between align-items-center${isPanelMode ? '' : ' mt-3'}">
                <div class="d-flex align-items-center gap-2">
                    <span class="text-muted small">
                        Showing ${start}-${end} of ${this._totalItems}
                    </span>
                    <select class="form-select form-select-sm lcm-page-size" style="width: 5rem;">
                        <option value="10" ${this._pageSize === 10 ? 'selected' : ''}>10</option>
                        <option value="25" ${this._pageSize === 25 ? 'selected' : ''}>25</option>
                        <option value="50" ${this._pageSize === 50 ? 'selected' : ''}>50</option>
                        <option value="100" ${this._pageSize === 100 ? 'selected' : ''}>100</option>
                    </select>
                </div>
                <nav aria-label="Table pagination">
                    <ul class="pagination pagination-sm mb-0">
                        <li class="page-item ${this._currentPage === 1 ? 'disabled' : ''}">
                            <button class="page-link lcm-page-btn" data-page="1" ${this._currentPage === 1 ? 'disabled' : ''}>
                                &laquo;
                            </button>
                        </li>
                        ${pagesHtml}
                        <li class="page-item ${this._currentPage === totalPages ? 'disabled' : ''}">
                            <button class="page-link lcm-page-btn" data-page="${totalPages}" ${this._currentPage === totalPages ? 'disabled' : ''}>
                                &raquo;
                            </button>
                        </li>
                    </ul>
                </nav>
            </div>
        `;

        // Wrap in card-footer for panel mode
        if (isPanelMode) {
            return `<div class="card-footer bg-white py-2">${paginationContent}</div>`;
        }

        return paginationContent;
    }

    _bindEvents() {
        // Search input (change/input events — not delegatable via click)
        const searchInput = this.querySelector('.lcm-search-input');
        searchInput?.addEventListener('input', e => this._handleSearch(e.target.value));

        // Page size select (change event)
        const pageSizeSelect = this.querySelector('.lcm-page-size');
        pageSizeSelect?.addEventListener('change', e => this._handlePageSizeChange(parseInt(e.target.value, 10)));

        // Refresh button
        const refreshBtn = this.querySelector('.lcm-refresh-btn');
        refreshBtn?.addEventListener('click', () => this.loadData());

        // Select all checkbox (change event)
        const selectAll = this.querySelector('.lcm-select-all');
        selectAll?.addEventListener('change', e => this._handleSelectAll(e.target.checked));

        // Row checkboxes (change event)
        this.querySelectorAll('.lcm-row-select').forEach(checkbox => {
            checkbox.addEventListener('change', e => {
                this._handleRowSelect(e.target.dataset.id, e.target.checked);
            });
        });

        // Note: Sort headers, page buttons, row actions, bulk actions, and row clicks
        // are all handled via the delegated click handler (_onDelegatedClick) on the
        // component element itself. This ensures they work even after innerHTML updates.
    }
}

// Register custom element
if (!customElements.get('lcm-data-table')) {
    customElements.define('lcm-data-table', LcmDataTable);
}

export default LcmDataTable;
