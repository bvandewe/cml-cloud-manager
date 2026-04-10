/**
 * Definition column registry.
 *
 * Schema-driven column definitions for the Lablet Definitions data table.
 * Uses SchemaColumn format from @neuroglia/ui-core.
 *
 * @module columns/definitionColumns
 */

/**
 * All available definition columns keyed by column ID.
 * @type {Record<string, import('@neuroglia/ui-core').SchemaColumn>}
 */
export const DEFINITION_COLUMNS = {
    name: {
        field: 'name',
        label: 'Name',
        sortable: true,
        category: 'identity',
        visible: true,
        description: 'Lablet definition display name',
    },
    form_fqn: {
        field: 'form_fqn',
        label: 'Form QN',
        sortable: true,
        category: 'identity',
        visible: true,
        render: val => {
            if (!val) return '&mdash;';
            return `<span class="text-truncate d-inline-block" style="max-width:200px;" title="${val}">${val}</span>`;
        },
        description: 'Fully qualified name of the associated form',
    },
    status: {
        field: 'status',
        label: 'Status',
        sortable: true,
        category: 'status',
        visible: true,
        component: 'ui-status-badge',
        componentAttrs: {
            status: 'row.status',
        },
    },
    sync_status: {
        field: 'sync_status',
        label: 'Sync',
        sortable: true,
        category: 'status',
        visible: true,
        component: 'ui-status-badge',
        componentAttrs: {
            status: 'row.sync_status',
        },
        render: val => {
            if (!val) return '&mdash;';
            return undefined; // fall through to component rendering
        },
        description: 'Synchronization status',
    },
    node_count: {
        field: 'node_count',
        label: 'Nodes',
        sortable: true,
        category: 'metrics',
        visible: true,
        type: 'number',
        align: 'center',
    },
    link_count: {
        field: 'link_count',
        label: 'Links',
        sortable: true,
        category: 'metrics',
        visible: true,
        type: 'number',
        align: 'center',
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
    updated_at: {
        field: 'updated_at',
        label: 'Updated',
        sortable: true,
        category: 'timing',
        visible: true,
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
export const DEFINITION_DEFAULT_COLUMNS = ['name', 'form_fqn', 'status', 'sync_status', 'node_count', 'link_count', 'updated_at'];
