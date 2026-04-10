/**
 * Worker column registry.
 *
 * Schema-driven column definitions for the Workers instances data table.
 * Uses SchemaColumn format from @neuroglia/ui-core.
 *
 * @module columns/workerColumns
 */

import { renderTimeAgo } from '../utils/dates.js';

/**
 * All available worker columns keyed by column ID.
 * @type {Record<string, import('@neuroglia/ui-core').SchemaColumn>}
 */
export const WORKER_COLUMNS = {
    name: {
        field: 'name',
        label: 'Name',
        sortable: true,
        category: 'identity',
        visible: true,
        description: 'Worker instance display name',
    },
    region: {
        field: 'aws_region',
        label: 'Region',
        sortable: true,
        category: 'identity',
        visible: true,
        description: 'AWS region where the instance runs',
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
            'desired-status': 'row.desired_status',
            'resource-type': "'worker'",
            compact: true,
        },
        description: 'Current and desired status with reconciliation indicator',
    },
    instance_type: {
        field: 'instance_type',
        label: 'Instance Type',
        sortable: true,
        category: 'identity',
        visible: true,
    },
    cpu_utilization: {
        field: 'cpu_utilization',
        label: 'CPU %',
        sortable: true,
        category: 'metrics',
        visible: true,
        type: 'number',
        align: 'right',
        render: val => {
            if (val === null || val === undefined) return '&mdash;';
            const pct = Number(val).toFixed(1);
            const color = val >= 90 ? 'danger' : val >= 70 ? 'warning' : 'success';
            return `<div class="progress" style="height:6px;width:60px;display:inline-block;" title="${pct}%">
                <div class="progress-bar bg-${color}" style="width:${pct}%"></div>
            </div> <small class="text-muted">${pct}%</small>`;
        },
        description: 'CPU utilization percentage',
    },
    memory_utilization: {
        field: 'memory_utilization',
        label: 'Memory %',
        sortable: true,
        category: 'metrics',
        visible: true,
        type: 'number',
        align: 'right',
        render: val => {
            if (val === null || val === undefined) return '&mdash;';
            const pct = Number(val).toFixed(1);
            const color = val >= 90 ? 'danger' : val >= 70 ? 'warning' : 'success';
            return `<div class="progress" style="height:6px;width:60px;display:inline-block;" title="${pct}%">
                <div class="progress-bar bg-${color}" style="width:${pct}%"></div>
            </div> <small class="text-muted">${pct}%</small>`;
        },
        description: 'Memory utilization percentage',
    },
    cml_labs_count: {
        field: 'cml_labs_count',
        label: 'CML Labs',
        sortable: true,
        category: 'metrics',
        visible: true,
        type: 'number',
        align: 'center',
        render: (val, row) => {
            const count = val ?? row?.active_labs_count ?? 0;
            const variant = count > 0 ? 'primary' : 'secondary';
            return `<span class="badge bg-${variant}" title="Labs reported by CML (incl. untracked)">${count}</span>`;
        },
        description: 'Number of labs reported by CML on this worker (includes untracked labs)',
    },
    lab_records_count: {
        field: 'lab_records_count',
        label: 'Lab Records',
        sortable: true,
        category: 'metrics',
        visible: true,
        type: 'number',
        align: 'center',
        render: val => {
            const count = val ?? 0;
            const variant = count > 0 ? 'info' : 'secondary';
            return `<span class="badge bg-${variant}" title="Tracked LabRecords in LCM">${count}</span>`;
        },
        description: 'Number of tracked LabRecords managed by LCM for this worker',
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
    created_at: {
        field: 'created_at',
        label: 'Created',
        sortable: true,
        category: 'timing',
        visible: true,
        type: 'datetime',
        render: val => renderTimeAgo(val),
        description: 'Creation time (hover for full timestamp)',
    },
    desired_status: {
        field: 'desired_status',
        label: 'Desired Status',
        sortable: true,
        category: 'status',
        visible: false,
        component: 'ui-status-badge',
        componentAttrs: {
            status: 'row.desired_status',
        },
        description: 'Desired target status for reconciliation',
    },
    id: {
        field: 'id',
        label: 'ID',
        sortable: false,
        category: 'identity',
        visible: false,
        description: 'Internal worker identifier',
    },
};

/**
 * Default visible columns (ordered).
 * @type {string[]}
 */
export const WORKER_DEFAULT_COLUMNS = ['name', 'region', 'status', 'instance_type', 'cpu_utilization', 'memory_utilization', 'cml_labs_count', 'lab_records_count', 'created_at'];
