/**
 * ResourceObservation - Live Telemetry Display
 *
 * Renders ResourceObservation data as progress bars for CPU, memory, storage,
 * with optional per-node detail expansion.
 *
 * @example
 * ```html
 * <ui-resource-observation observation='{"cpu_usage":68,"memory_usage":52}' show-nodes></ui-resource-observation>
 * <ui-resource-observation observation='{"cpu_usage":90}' warn-threshold="80" compact></ui-resource-observation>
 * ```
 *
 * @module components
 */

import { BaseComponent } from './BaseComponent.js';
import type { ResourceObservationData, NodeObservation } from '../types/columns.js';
import { escapeHtml } from '../types/columns.js';

/**
 * ResourceObservation Web Component
 *
 * Displays CPU/memory/storage utilization bars with:
 * - Color-coded thresholds (green/yellow/red)
 * - Expandable node-level detail
 * - Compact mode for table cells
 */
export class ResourceObservation extends BaseComponent {
    static get observedAttributes(): string[] {
        return ['observation', 'show-nodes', 'compact', 'warn-threshold'];
    }

    private _observation: ResourceObservationData | null = null;

    constructor() {
        super();
    }

    protected override onMount(): void {
        this.parseObservation();
        this.render();
    }

    protected override onAttributeChange(name: string): void {
        if (name === 'observation') this.parseObservation();
        if (this._mounted) this.render();
    }

    // ── Attribute Accessors ──

    get showNodes(): boolean {
        return this.getBoolAttr('show-nodes');
    }

    get isCompact(): boolean {
        return this.getBoolAttr('compact');
    }

    get warnThreshold(): number {
        return this.getNumberAttr('warn-threshold', 80);
    }

    get observation(): ResourceObservationData | null {
        return this._observation;
    }

    // ── Public API ──

    /** Set observation data programmatically */
    setObservation(data: ResourceObservationData): void {
        this._observation = data;
        if (this._mounted) this.render();
    }

    // ── Private ──

    private parseObservation(): void {
        const raw = this.getAttribute('observation');
        if (!raw) {
            this._observation = null;
            return;
        }
        try {
            this._observation = JSON.parse(raw) as ResourceObservationData;
        } catch {
            this._observation = null;
        }
    }

    private getBarColor(value: number): string {
        if (value >= 90) return 'bg-danger';
        if (value >= this.warnThreshold) return 'bg-warning';
        return 'bg-success';
    }

    private renderBar(label: string, value: number | undefined, unit: string = '%'): string {
        if (value === undefined || value === null) return '';

        const barColor = this.getBarColor(value);
        const warnIcon = value >= this.warnThreshold ? ' ⚠' : '';
        const rounded = Math.round(value);

        return `
            <div class="d-flex align-items-center gap-2 mb-1" aria-label="${label}: ${rounded}${unit}">
                <span class="small text-muted" style="min-width: 50px;">${label}:</span>
                <div class="progress flex-grow-1" style="height: 8px;" role="progressbar"
                     aria-valuenow="${rounded}" aria-valuemin="0" aria-valuemax="100">
                    <div class="progress-bar ${barColor}" style="width: ${rounded}%"></div>
                </div>
                <span class="small fw-semibold" style="min-width: 45px;">${rounded}${unit}${warnIcon}</span>
            </div>
        `;
    }

    private renderCompactBars(): string {
        const obs = this._observation;
        if (!obs) return `<span class="text-muted small">—</span>`;

        const bars: string[] = [];
        if (obs.cpu_usage !== undefined) bars.push(this.renderMicroBar('CPU', obs.cpu_usage));
        if (obs.memory_usage !== undefined) bars.push(this.renderMicroBar('Mem', obs.memory_usage));
        if (obs.storage_usage !== undefined) bars.push(this.renderMicroBar('Disk', obs.storage_usage));

        if (bars.length === 0) return `<span class="text-muted small">—</span>`;

        const nodeCount = obs.nodes?.length || 0;
        const activeNodes = obs.nodes?.filter(n => n.state?.toLowerCase() === 'booted').length || 0;
        const nodeText = nodeCount > 0 ? `<span class="text-muted small ms-1">${activeNodes}/${nodeCount}</span>` : '';

        return `
            <div class="d-inline-flex align-items-center gap-2" aria-label="Resource utilization">
                ${bars.join('')}
                ${nodeText}
            </div>
        `;
    }

    private renderMicroBar(label: string, value: number): string {
        const color = this.getBarColor(value);
        const rounded = Math.round(value);
        return `
            <span class="d-inline-flex align-items-center gap-1" title="${label}: ${rounded}%" aria-label="${label} ${rounded}%">
                <span class="small text-muted">${label}</span>
                <div class="progress" style="width: 40px; height: 6px;" role="progressbar"
                     aria-valuenow="${rounded}" aria-valuemin="0" aria-valuemax="100">
                    <div class="progress-bar ${color}" style="width: ${rounded}%"></div>
                </div>
                <span class="small">${rounded}%</span>
            </span>
        `;
    }

    private renderNodeDetail(node: NodeObservation): string {
        const stateColor = node.state?.toLowerCase() === 'booted' ? 'text-success' : node.state?.toLowerCase() === 'stopped' ? 'text-secondary' : 'text-muted';
        const cpuWarn = node.cpu_usage !== undefined && node.cpu_usage >= this.warnThreshold ? ' ⚠' : '';
        const memWarn = node.memory_usage_mb !== undefined && node.memory_usage_mb > 1024 ? '' : '';

        return `
            <tr>
                <td class="small">${escapeHtml(node.label)}</td>
                <td class="small ${stateColor}">${node.state || '—'}</td>
                <td class="small text-end">${node.cpu_usage !== undefined ? `${Math.round(node.cpu_usage)}%${cpuWarn}` : '—'}</td>
                <td class="small text-end">${node.memory_usage_mb !== undefined ? `${Math.round(node.memory_usage_mb)}MB${memWarn}` : '—'}</td>
            </tr>
        `;
    }

    // ── Main Render ──

    override render(): void {
        if (this.isCompact) {
            this.innerHTML = this.renderCompactBars();
            return;
        }

        const obs = this._observation;
        if (!obs) {
            this.innerHTML = `<div class="text-muted small">No observation data.</div>`;
            return;
        }

        const bars = [this.renderBar('CPU', obs.cpu_usage), this.renderBar('Memory', obs.memory_usage), this.renderBar('Storage', obs.storage_usage)].filter(b => b).join('');

        const nodeCount = obs.nodes?.length || 0;
        const activeNodes = obs.nodes?.filter(n => n.state?.toLowerCase() === 'booted').length || 0;
        const nodeSummary = nodeCount > 0 ? `Nodes: ${activeNodes}/${nodeCount} active` : '';

        const nodesExpanded = this.getStateValue<boolean>('nodesExpanded') ?? this.showNodes;
        let nodeSection = '';
        if (nodeCount > 0) {
            const nodeToggle = `
                <button class="btn btn-sm btn-link text-muted p-0 node-toggle"
                        aria-expanded="${nodesExpanded}" aria-label="${nodesExpanded ? 'Hide' : 'Show'} node details">
                    ${nodesExpanded ? '▼' : '▶'} Node Details
                </button>
            `;

            const nodeTable = nodesExpanded
                ? `
                    <table class="table table-sm table-borderless mt-1 mb-0">
                        <thead>
                            <tr class="text-muted">
                                <th class="small fw-normal">Node</th>
                                <th class="small fw-normal">State</th>
                                <th class="small fw-normal text-end">CPU</th>
                                <th class="small fw-normal text-end">Mem</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${obs.nodes?.map(n => this.renderNodeDetail(n)).join('') || ''}
                        </tbody>
                    </table>
                `
                : '';

            nodeSection = `<div class="mt-2">${nodeToggle}${nodeTable}</div>`;
        }

        this.innerHTML = `
            <div class="resource-observation" role="region" aria-label="Resource observation">
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <span class="fw-semibold small">Resource Observation</span>
                    <span class="text-muted small">${nodeSummary}</span>
                </div>
                ${bars}
                ${nodeSection}
            </div>
        `;

        this.bindEvents();
    }

    private bindEvents(): void {
        const nodeToggle = this.$('.node-toggle');
        nodeToggle?.addEventListener('click', () => {
            const current = this.getStateValue<boolean>('nodesExpanded') ?? this.showNodes;
            this.setState({ nodesExpanded: !current });
        });
    }
}

// Register the custom element
if (!customElements.get('ui-resource-observation')) {
    customElements.define('ui-resource-observation', ResourceObservation);
}

export default ResourceObservation;
