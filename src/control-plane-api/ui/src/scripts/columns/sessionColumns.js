/**
 * Session column registry.
 *
 * Schema-driven column definitions for the Lablet Sessions data table.
 * Uses SchemaColumn format from @neuroglia/ui-core.
 *
 * @module columns/sessionColumns
 */

/**
 * All available session columns keyed by column ID.
 * @type {Record<string, import('@neuroglia/ui-core').SchemaColumn>}
 */
export const SESSION_COLUMNS = {
    definition_name: {
        field: 'definition_name',
        label: 'Definition',
        sortable: true,
        width: '200px',
        category: 'identity',
        visible: true,
        render: (val, row) => {
            const icon = row.definition_icon || 'bi-diagram-3';
            const fqn = row.definition_fqn || '';
            const nameHtml = val || 'Unknown';
            return `<div>
                <i class="${icon} me-1 text-muted"></i>
                <strong class="session-name-link" role="button" data-id="${row.id}">${nameHtml}</strong>
                ${fqn ? `<div class="text-muted small text-truncate" style="max-width:180px;" title="${fqn}">${fqn}</div>` : ''}
            </div>`;
        },
        description: 'Lablet definition name and FQN',
    },
    candidate_id: {
        field: 'candidate_id',
        label: 'Candidate',
        sortable: true,
        width: '130px',
        category: 'identity',
        visible: true,
        render: val => {
            if (!val) return '&mdash;';
            return `<i class="bi-person me-1"></i>${val}`;
        },
    },
    status: {
        field: 'status',
        label: 'Status',
        sortable: true,
        width: '100px',
        category: 'status',
        visible: true,
        component: 'ui-status-badge',
        componentAttrs: {
            status: 'row.status',
            icon: true,
            pill: true,
        },
    },
    worker_name: {
        field: 'worker_name',
        label: 'Worker',
        sortable: true,
        width: '120px',
        category: 'identity',
        visible: true,
        render: (val, row) => {
            if (!val) return '&mdash;';
            const workerId = row.worker_id || '';
            return `<span class="worker-link" role="button" data-worker-id="${workerId}" title="View worker details">${val}</span>`;
        },
        description: 'Assigned worker instance',
    },
    topology: {
        field: 'topology',
        label: 'Topology',
        sortable: true,
        width: '80px',
        category: 'metrics',
        visible: true,
        align: 'center',
        render: (val, row) => {
            const nodes = row.node_count ?? val?.nodes ?? '?';
            const links = row.link_count ?? val?.links ?? '?';
            return `<span title="${nodes} nodes / ${links} links">${nodes} / ${links}</span>`;
        },
        description: 'Node / Link count',
    },
    timeslot: {
        field: 'timeslot',
        label: 'Timeslot',
        sortable: true,
        width: '150px',
        category: 'timing',
        visible: true,
        component: 'ui-timeslot-badge',
        componentAttrs: {
            start: 'row.timeslot.start',
            end: 'row.timeslot.end',
            'lead-time': 'row.timeslot.lead_time',
            'teardown-buffer': 'row.timeslot.teardown_buffer',
            compact: true,
        },
        description: 'Scheduled time window with phase indicator',
    },
    form_fqn: {
        field: 'form_fqn',
        label: 'Form',
        sortable: true,
        width: '160px',
        category: 'identity',
        visible: true,
        render: val => {
            if (!val) return '&mdash;';
            return `<span class="text-truncate d-inline-block" style="max-width:150px;" title="${val}">${val}</span>`;
        },
    },
    pipeline: {
        field: 'pipeline',
        label: 'Pipeline',
        sortable: false,
        width: '120px',
        category: 'status',
        visible: true,
        component: 'ui-lifecycle-tracker',
        componentAttrs: {
            phases: 'row.pipeline_phases',
            'current-phase': 'row.current_pipeline_phase',
            layout: "'compact'",
        },
        description: 'Pipeline execution progress',
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
    reservation_id: {
        field: 'reservation_id',
        label: 'Reservation',
        sortable: true,
        category: 'identity',
        visible: false,
        render: val => {
            if (!val) return '&mdash;';
            return `<code class="small">${String(val).slice(0, 8)}</code>`;
        },
        description: 'Linked reservation identifier',
    },
    created_at: {
        field: 'created_at',
        label: 'Created',
        sortable: true,
        category: 'timing',
        visible: false,
        type: 'datetime',
    },
    updated_at: {
        field: 'updated_at',
        label: 'Updated',
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
export const SESSION_DEFAULT_COLUMNS = ['definition_name', 'candidate_id', 'status', 'worker_name', 'topology', 'timeslot', 'form_fqn', 'pipeline'];
