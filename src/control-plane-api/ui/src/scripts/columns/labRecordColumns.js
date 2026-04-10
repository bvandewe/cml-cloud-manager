/**
 * Lab record column registry.
 *
 * Schema-driven column definitions for the Lab Records data table.
 * Uses SchemaColumn format from @neuroglia/ui-core.
 *
 * @module columns/labRecordColumns
 */

/**
 * All available lab record columns keyed by column ID.
 * @type {Record<string, import('@neuroglia/ui-core').SchemaColumn>}
 */
export const LAB_RECORD_COLUMNS = {
    title: {
        field: 'title',
        label: 'Title',
        sortable: true,
        category: 'identity',
        visible: true,
        render: (val, row) => {
            const status = row.status || 'unknown';
            const icon = status === 'STARTED' ? 'bi-play-circle-fill text-success' : status === 'STOPPED' ? 'bi-stop-circle text-secondary' : status === 'WIPED' ? 'bi-eraser text-warning' : 'bi-circle text-muted';
            const id = row.id || '';
            return `<i class="${icon} me-1"></i><strong class="lab-title-link" role="button" data-id="${id}">${val || 'Untitled'}</strong>`;
        },
        description: 'Lab title with status icon',
    },
    worker_name: {
        field: 'worker_name',
        label: 'Worker',
        sortable: true,
        category: 'identity',
        visible: true,
        render: (val, row) => val || row.worker_id || '&mdash;',
        description: 'Host worker instance',
    },
    status: {
        field: 'status',
        label: 'Status',
        sortable: true,
        category: 'status',
        visible: true,
        component: 'ui-resource-status',
        componentAttrs: {
            status: 'row.status',
            'desired-status': 'row.pending_action',
            'resource-type': "'lab'",
            compact: true,
        },
        description: 'Current status with pending action indicator',
    },
    node_count: {
        field: 'node_count',
        label: 'Nodes',
        sortable: true,
        category: 'metrics',
        visible: true,
        type: 'number',
        align: 'center',
        render: val => (val !== null && val !== undefined ? String(val) : '&mdash;'),
    },
    link_count: {
        field: 'link_count',
        label: 'Links',
        sortable: true,
        category: 'metrics',
        visible: true,
        type: 'number',
        align: 'center',
        render: val => (val !== null && val !== undefined ? String(val) : '&mdash;'),
    },
    source: {
        field: 'source',
        label: 'Source',
        sortable: true,
        category: 'identity',
        visible: true,
        render: val => {
            const sourceIcons = {
                discovery: 'bi-search text-info',
                import: 'bi-box-arrow-in-down text-primary',
                manual: 'bi-pencil text-secondary',
            };
            const lcVal = String(val || '').toLowerCase();
            const icon = sourceIcons[lcVal] || 'bi-question-circle text-muted';
            return `<i class="${icon} me-1" title="${val || 'Unknown'}"></i>${val || '&mdash;'}`;
        },
        description: 'How the lab was added (discovery, import, manual)',
    },
    state_version: {
        field: 'state_version',
        label: 'Rev',
        sortable: true,
        category: 'status',
        visible: false,
        component: 'ui-revision-indicator',
        componentAttrs: {
            version: 'row.state_version',
            'resource-id': 'row.id',
            compact: true,
        },
        description: 'Aggregate revision (state version)',
    },
    owner: {
        field: 'owner',
        label: 'Owner',
        sortable: true,
        category: 'identity',
        visible: false,
        render: val => val || '&mdash;',
    },
    description: {
        field: 'description',
        label: 'Description',
        sortable: false,
        category: 'identity',
        visible: false,
        render: val => {
            if (!val) return '&mdash;';
            const truncated = String(val).length > 80 ? String(val).slice(0, 80) + '…' : val;
            return `<span title="${val}">${truncated}</span>`;
        },
    },
    updated_at: {
        field: 'updated_at',
        label: 'Updated',
        sortable: true,
        category: 'timing',
        visible: true,
        type: 'datetime',
    },
    created_at: {
        field: 'created_at',
        label: 'Created',
        sortable: true,
        category: 'timing',
        visible: false,
        type: 'datetime',
    },
    id: {
        field: 'id',
        label: 'ID',
        sortable: false,
        category: 'identity',
        visible: false,
    },
};

/**
 * Default visible columns (ordered).
 * @type {string[]}
 */
export const LAB_RECORD_DEFAULT_COLUMNS = ['title', 'worker_name', 'status', 'node_count', 'link_count', 'source', 'updated_at'];
