/**
 * DataTable extended features tests (B2-B6).
 *
 * Tests the new schema-driven column, visibility, component rendering,
 * expandable rows, column groups, and localStorage persistence features.
 */
import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest';
import '../src/components/DataTable.js';
import '../src/components/StatusBadge.js';

// Minimal type alias
type DataTableEl = HTMLElement & {
    setColumns: (cols: unknown[]) => void;
    setSchemaColumns: (cols: Record<string, unknown>, defaults?: string[]) => void;
    setData: (data: unknown[]) => void;
    setExpandableConfig: (config: unknown) => void;
    setColumnVisibility: (key: string, visible: boolean) => void;
    setColumnsVisibility: (vis: Record<string, boolean>) => void;
    resetColumnVisibility: () => void;
    toggleRowExpand: (id: string) => void;
    collapseAllRows: () => void;
};

describe('DataTable Extended (B2-B6)', () => {
    let el: DataTableEl;

    function create(attrs: Record<string, string> = {}): DataTableEl {
        el = document.createElement('ui-data-table') as DataTableEl;
        for (const [key, value] of Object.entries(attrs)) {
            el.setAttribute(key, value);
        }
        document.body.appendChild(el);
        return el;
    }

    const sampleData = [
        { id: '1', name: 'Worker Alpha', status: 'running', region: 'us-east-1', cpu: 65, state_version: 3 },
        { id: '2', name: 'Worker Beta', status: 'stopped', region: 'eu-west-1', cpu: 0, state_version: 7 },
        { id: '3', name: 'Worker Gamma', status: 'running', region: 'us-west-2', cpu: 82, state_version: 12 },
    ];

    const schemaColumns: Record<string, unknown> = {
        name: { field: 'name', label: 'Name', sortable: true, category: 'identity', visible: true },
        status: {
            field: 'status',
            label: 'Status',
            sortable: true,
            category: 'status',
            visible: true,
            component: 'ui-status-badge',
            componentAttrs: { status: 'row.status' },
        },
        region: { field: 'region', label: 'Region', sortable: true, category: 'identity', visible: true, group: 'Location' },
        cpu: { field: 'cpu', label: 'CPU', type: 'number', category: 'metrics', visible: false, group: 'Metrics' },
        state_version: { field: 'state_version', label: 'Rev', category: 'status', visible: false },
    };

    const defaultColumns = ['name', 'status', 'region'];

    beforeEach(() => {
        localStorage.clear();
    });

    afterEach(() => {
        el?.remove();
        localStorage.clear();
    });

    // ── B1: Schema Columns ──

    describe('setSchemaColumns (B1)', () => {
        it('configures columns from schema record', () => {
            create();
            el.setSchemaColumns(schemaColumns, defaultColumns);
            el.setData(sampleData);

            // Should render visible columns
            const headers = el.querySelectorAll('th[data-key]');
            expect(headers.length).toBe(3); // name, status, region (defaults)
        });

        it('hides non-default columns', () => {
            create();
            el.setSchemaColumns(schemaColumns, defaultColumns);
            el.setData(sampleData);

            // cpu and state_version should not appear
            const headerKeys = Array.from(el.querySelectorAll('th[data-key]')).map(th => (th as HTMLElement).dataset.key);
            expect(headerKeys).not.toContain('cpu');
            expect(headerKeys).not.toContain('state_version');
        });
    });

    // ── B2: Column Visibility ──

    describe('column visibility (B2)', () => {
        it('shows/hides columns via setColumnVisibility', () => {
            create();
            el.setSchemaColumns(schemaColumns, defaultColumns);
            el.setData(sampleData);

            // Initially cpu is hidden
            let headers = Array.from(el.querySelectorAll('th[data-key]')).map(th => (th as HTMLElement).dataset.key);
            expect(headers).not.toContain('cpu');

            // Show cpu
            el.setColumnVisibility('cpu', true);
            headers = Array.from(el.querySelectorAll('th[data-key]')).map(th => (th as HTMLElement).dataset.key);
            expect(headers).toContain('cpu');
        });

        it('hides visible column via setColumnVisibility', () => {
            create();
            el.setSchemaColumns(schemaColumns, defaultColumns);
            el.setData(sampleData);

            el.setColumnVisibility('region', false);
            const headers = Array.from(el.querySelectorAll('th[data-key]')).map(th => (th as HTMLElement).dataset.key);
            expect(headers).not.toContain('region');
        });

        it('resets to defaults via resetColumnVisibility', () => {
            create();
            el.setSchemaColumns(schemaColumns, defaultColumns);
            el.setData(sampleData);

            // Show extra column
            el.setColumnVisibility('cpu', true);
            el.resetColumnVisibility();

            const headers = Array.from(el.querySelectorAll('th[data-key]')).map(th => (th as HTMLElement).dataset.key);
            expect(headers).not.toContain('cpu');
            expect(headers).toContain('name');
        });

        it('applies batch visibility via setColumnsVisibility', () => {
            create();
            el.setSchemaColumns(schemaColumns, defaultColumns);
            el.setData(sampleData);

            el.setColumnsVisibility({ cpu: true, state_version: true, region: false });

            const headers = Array.from(el.querySelectorAll('th[data-key]')).map(th => (th as HTMLElement).dataset.key);
            expect(headers).toContain('cpu');
            expect(headers).toContain('state_version');
            expect(headers).not.toContain('region');
        });
    });

    // ── B3: Component Cell Rendering ──

    describe('component cell rendering (B3)', () => {
        it('renders custom elements for columns with component config', () => {
            create();
            el.setSchemaColumns(schemaColumns, defaultColumns);
            el.setData(sampleData);

            // Status column should render <ui-status-badge> elements
            const statusBadges = el.querySelectorAll('ui-status-badge');
            expect(statusBadges.length).toBe(sampleData.length);
        });

        it('resolves row.field paths to attribute values', () => {
            create();
            el.setSchemaColumns(schemaColumns, defaultColumns);
            el.setData(sampleData);

            const firstBadge = el.querySelector('ui-status-badge');
            expect(firstBadge?.getAttribute('status')).toBe('running');
        });

        it('falls back to formatValue when no component or render', () => {
            create();
            el.setSchemaColumns(schemaColumns, defaultColumns);
            el.setData(sampleData);

            // Name column has no component, should render plain text
            const cells = el.querySelectorAll('tbody td');
            const nameCell = cells[0]; // First cell in first row
            expect(nameCell?.textContent).toContain('Worker Alpha');
        });
    });

    // ── B4: Expandable Rows ──

    describe('expandable rows (B4)', () => {
        it('renders expand toggle buttons', () => {
            create();
            el.setSchemaColumns(schemaColumns, defaultColumns);
            el.setData(sampleData);
            el.setExpandableConfig({
                renderDetail: (row: Record<string, unknown>) => `<div>Detail for ${row.name}</div>`,
            });

            const expandBtns = el.querySelectorAll('.row-expand');
            expect(expandBtns.length).toBe(sampleData.length);
        });

        it('shows detail row when expanded', () => {
            create();
            el.setSchemaColumns(schemaColumns, defaultColumns);
            el.setData(sampleData);
            el.setExpandableConfig({
                renderDetail: (row: Record<string, unknown>) => `<div class="detail-content">Detail for ${row.name}</div>`,
            });

            el.toggleRowExpand('1');
            expect(el.querySelector('.detail-content')).not.toBeNull();
            expect(el.innerHTML).toContain('Detail for Worker Alpha');
        });

        it('hides detail row when collapsed', () => {
            create();
            el.setSchemaColumns(schemaColumns, defaultColumns);
            el.setData(sampleData);
            el.setExpandableConfig({
                renderDetail: (row: Record<string, unknown>) => `<div class="detail-content">Detail</div>`,
            });

            el.toggleRowExpand('1'); // expand
            el.toggleRowExpand('1'); // collapse
            expect(el.querySelector('.detail-content')).toBeNull();
        });

        it('collapses all rows', () => {
            create();
            el.setSchemaColumns(schemaColumns, defaultColumns);
            el.setData(sampleData);
            el.setExpandableConfig({
                renderDetail: () => '<div class="detail-content">Detail</div>',
            });

            el.toggleRowExpand('1');
            el.toggleRowExpand('2');
            el.collapseAllRows();
            expect(el.querySelectorAll('.detail-content').length).toBe(0);
        });

        it('sets aria-expanded on toggle buttons', () => {
            create();
            el.setSchemaColumns(schemaColumns, defaultColumns);
            el.setData(sampleData);
            el.setExpandableConfig({ renderDetail: () => '<div>Detail</div>' });

            el.toggleRowExpand('1');
            const btn = el.querySelector('.row-expand[data-id="1"]');
            expect(btn?.getAttribute('aria-expanded')).toBe('true');
        });
    });

    // ── B5: Column Group Headers ──

    describe('column group headers (B5)', () => {
        it('renders group header row when columns have groups', () => {
            create();
            el.setSchemaColumns(schemaColumns, ['name', 'status', 'region', 'cpu']);
            el.setColumnsVisibility({ cpu: true });
            el.setData(sampleData);

            const groupRow = el.querySelector('.table-group-header');
            expect(groupRow).not.toBeNull();
        });

        it('does not render group row when no groups defined', () => {
            const noGroupCols: Record<string, unknown> = {
                name: { field: 'name', label: 'Name', visible: true },
                status: { field: 'status', label: 'Status', visible: true },
            };
            create();
            el.setSchemaColumns(noGroupCols, ['name', 'status']);
            el.setData(sampleData);

            const groupRow = el.querySelector('.table-group-header');
            expect(groupRow).toBeNull();
        });
    });

    // ── B6: localStorage Persistence ──

    describe('localStorage persistence (B6)', () => {
        it('saves column visibility on change', () => {
            create({ 'table-id': 'persist-test' });
            el.setSchemaColumns(schemaColumns, defaultColumns);
            el.setData(sampleData);

            el.setColumnVisibility('cpu', true);

            const stored = localStorage.getItem('lcm.columns.persist-test');
            expect(stored).not.toBeNull();
            const parsed = JSON.parse(stored!);
            expect(parsed.cpu).toBe(true);
        });

        it('restores column visibility on mount', () => {
            // Pre-seed localStorage
            localStorage.setItem(
                'lcm.columns.restore-test',
                JSON.stringify({
                    name: true,
                    status: true,
                    region: false,
                    cpu: true,
                    state_version: false,
                })
            );

            create({ 'table-id': 'restore-test' });
            el.setSchemaColumns(schemaColumns, defaultColumns);
            el.setData(sampleData);

            const headers = Array.from(el.querySelectorAll('th[data-key]')).map(th => (th as HTMLElement).dataset.key);
            expect(headers).toContain('cpu');
            expect(headers).not.toContain('region');
        });

        it('uses lcm.columns.<tableId> key convention', () => {
            create({ 'table-id': 'my-workers' });
            el.setSchemaColumns(schemaColumns, defaultColumns);
            el.setData(sampleData);

            el.setColumnVisibility('cpu', true);

            expect(localStorage.getItem('lcm.columns.my-workers')).not.toBeNull();
        });

        it('does not persist without table-id', () => {
            create(); // no table-id
            el.setSchemaColumns(schemaColumns, defaultColumns);
            el.setData(sampleData);

            el.setColumnVisibility('cpu', true);

            // No keys should start with lcm.columns.
            const keys = Object.keys(localStorage);
            const lcmKeys = keys.filter(k => k.startsWith('lcm.columns.'));
            expect(lcmKeys.length).toBe(0);
        });
    });

    // ── Backward Compatibility ──

    describe('backward compatibility', () => {
        it('works with legacy setColumns API', () => {
            create();
            el.setColumns([
                { key: 'name', label: 'Name', sortable: true },
                { key: 'status', label: 'Status', sortable: true },
            ]);
            el.setData(sampleData);

            const headers = el.querySelectorAll('th[data-key]');
            expect(headers.length).toBe(2);
        });

        it('uses hidden flag from legacy column definitions', () => {
            create();
            el.setColumns([
                { key: 'name', label: 'Name' },
                { key: 'status', label: 'Status', hidden: true },
            ]);
            el.setData(sampleData);

            const headers = Array.from(el.querySelectorAll('th[data-key]')).map(th => (th as HTMLElement).dataset.key);
            expect(headers).toContain('name');
            expect(headers).not.toContain('status');
        });

        it('supports render functions alongside component config', () => {
            create();
            el.setColumns([
                { key: 'name', label: 'Name', render: (val: unknown) => `<strong>${val}</strong>` },
                { key: 'status', label: 'Status' },
            ]);
            el.setData(sampleData);

            // render function should take priority
            expect(el.innerHTML).toContain('<strong>Worker Alpha</strong>');
        });
    });

    // ── Column Picker Integration ──

    describe('column picker integration', () => {
        it('renders column picker when show-column-picker is set', () => {
            create({ 'table-id': 'picker-test', 'show-column-picker': '' });
            el.setSchemaColumns(schemaColumns, defaultColumns);
            el.setData(sampleData);

            const picker = el.querySelector('ui-column-picker');
            expect(picker).not.toBeNull();
        });

        it('does not render picker without table-id', () => {
            create({ 'show-column-picker': '' }); // no table-id
            el.setSchemaColumns(schemaColumns, defaultColumns);
            el.setData(sampleData);

            const picker = el.querySelector('ui-column-picker');
            expect(picker).toBeNull();
        });
    });
});
