/**
 * StateHistory - Transition Timeline Web Component
 *
 * Renders a resource's state_history as a visual timeline or compact breadcrumb.
 *
 * @example
 * ```html
 * <ui-state-history transitions='[...]' resource-type="session"></ui-state-history>
 * <ui-state-history transitions='[...]' compact max-visible="3"></ui-state-history>
 * ```
 *
 * @module components
 */

import { BaseComponent } from './BaseComponent.js';
import { STATUS_COLORS } from './StatusBadge.js';
import type { StateTransition } from '../types/columns.js';
import { formatRelativeTime, escapeHtml } from '../types/columns.js';

/**
 * StateHistory Web Component
 *
 * Full mode: vertical timeline with from→to badges, timestamps, triggered_by, reason.
 * Compact mode: horizontal breadcrumb chain ("PENDING → SCHEDULED → … → READY").
 */
export class StateHistory extends BaseComponent {
    static get observedAttributes(): string[] {
        return ['transitions', 'resource-type', 'max-visible', 'compact', 'show-metadata', 'newest-first'];
    }

    /** Parsed transitions (set via attribute or programmatically) */
    private _transitions: StateTransition[] = [];

    constructor() {
        super();
    }

    protected override onMount(): void {
        this.parseTransitions();
        this.render();
    }

    protected override onAttributeChange(name: string): void {
        if (name === 'transitions') this.parseTransitions();
        if (this._mounted) this.render();
    }

    // ── Attribute Accessors ──

    get resourceType(): string {
        return this.getAttr('resource-type', '');
    }

    get maxVisible(): number {
        return this.getNumberAttr('max-visible', 5);
    }

    get isCompact(): boolean {
        return this.getBoolAttr('compact');
    }

    get showMetadata(): boolean {
        return this.getBoolAttr('show-metadata');
    }

    get newestFirst(): boolean {
        const attr = this.getAttribute('newest-first');
        // Default: newest first
        return attr !== 'false';
    }

    get transitions(): StateTransition[] {
        return this._transitions;
    }

    // ── Public API ──

    /** Set transitions programmatically */
    setTransitions(transitions: StateTransition[]): void {
        this._transitions = transitions;
        if (this._mounted) this.render();
    }

    // ── Private ──

    private parseTransitions(): void {
        const raw = this.getAttribute('transitions');
        if (!raw) {
            this._transitions = [];
            return;
        }
        try {
            this._transitions = JSON.parse(raw) as StateTransition[];
        } catch {
            this._transitions = [];
        }
    }

    private normalizeStatus(status: string): string {
        return status.toLowerCase().replace(/[- ]/g, '_');
    }

    private getColor(status: string): string {
        return STATUS_COLORS[this.normalizeStatus(status)] || 'secondary';
    }

    private formatStatus(status: string): string {
        return status
            .replace(/_/g, ' ')
            .replace(/-/g, ' ')
            .split(' ')
            .map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
            .join(' ');
    }

    private renderSmallBadge(status: string): string {
        const color = this.getColor(status);
        return `<span class="badge bg-${color} badge-sm rounded-pill">${this.formatStatus(status)}</span>`;
    }

    // ── Compact Rendering ──

    private renderCompact(): string {
        if (this._transitions.length === 0) {
            return `<span class="text-muted small" aria-label="No state history">—</span>`;
        }

        // Collect ordered unique states
        const states: string[] = [];
        const sorted = [...this._transitions].sort((a, b) => new Date(a.transitioned_at).getTime() - new Date(b.transitioned_at).getTime());

        if (sorted.length > 0 && sorted[0]!.from_state) {
            states.push(sorted[0]!.from_state);
        }
        for (const t of sorted) {
            states.push(t.to_state);
        }

        // Truncate middle if too many
        const max = this.maxVisible;
        let display: string[];
        if (states.length <= max) {
            display = states;
        } else {
            display = [...states.slice(0, 2), '…', ...states.slice(-2)];
        }

        const badges = display.map(s => (s === '…' ? `<span class="text-muted mx-1" aria-hidden="true">…</span>` : this.renderSmallBadge(s)));

        return `
            <div class="d-inline-flex align-items-center flex-wrap gap-1" role="list"
                 aria-label="State history: ${states.length} transitions">
                ${badges.join('<i class="bi-chevron-right text-muted small mx-1" aria-hidden="true"></i>')}
            </div>
        `;
    }

    // ── Full Timeline Rendering ──

    private renderTimeline(): string {
        if (this._transitions.length === 0) {
            return `<div class="text-muted small p-2">No state transitions recorded.</div>`;
        }

        const sorted = [...this._transitions].sort((a, b) => {
            const diff = new Date(a.transitioned_at).getTime() - new Date(b.transitioned_at).getTime();
            return this.newestFirst ? -diff : diff;
        });

        const visible = sorted.slice(0, this.maxVisible);
        const remaining = sorted.length - visible.length;

        const items = visible
            .map((t, i) => {
                const isLast = i === visible.length - 1 && remaining === 0;
                const dot = isLast ? '◉' : '●';
                const lineClass = isLast ? '' : 'border-start border-2 ms-1 ps-3';
                const triggeredBy = t.triggered_by ? `<span class="text-muted">by: ${escapeHtml(t.triggered_by)}</span>` : '';
                const reason = t.reason ? `<div class="text-muted small mt-1">${escapeHtml(t.reason)}</div>` : '';
                const time = formatRelativeTime(t.transitioned_at);
                const meta =
                    this.showMetadata && t.metadata
                        ? `<details class="mt-1"><summary class="text-muted small">metadata</summary><pre class="small bg-light p-2 rounded mt-1 mb-0">${escapeHtml(JSON.stringify(t.metadata, null, 2))}</pre></details>`
                        : '';

                return `
                    <div class="d-flex align-items-start mb-2" role="listitem">
                        <span class="${this.getColor(t.to_state) === 'success' ? 'text-success' : this.getColor(t.to_state) === 'danger' ? 'text-danger' : 'text-primary'} me-2" aria-hidden="true">${dot}</span>
                        <div class="${lineClass} pb-2" style="min-width: 0;">
                            <div class="d-flex align-items-center flex-wrap gap-1">
                                ${this.renderSmallBadge(t.from_state)}
                                <i class="bi-arrow-right text-muted mx-1" aria-hidden="true"></i>
                                ${this.renderSmallBadge(t.to_state)}
                                <span class="text-muted small ms-2">${time}</span>
                                ${triggeredBy}
                            </div>
                            ${reason}
                            ${meta}
                        </div>
                    </div>
                `;
            })
            .join('');

        const showMoreBtn = remaining > 0 ? `<button class="btn btn-sm btn-link text-muted p-0 show-more-btn" aria-label="Show ${remaining} more transitions">+ ${remaining} more</button>` : '';

        return `
            <div role="list" aria-label="State history with ${this._transitions.length} transitions">
                ${items}
                ${showMoreBtn}
            </div>
        `;
    }

    // ── Main Render ──

    override render(): void {
        if (this.isCompact) {
            this.innerHTML = this.renderCompact();
            return;
        }

        const count = this._transitions.length;
        const collapsed = this.getStateValue<boolean>('collapsed') ?? false;

        this.innerHTML = `
            <div class="state-history-panel">
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <span class="fw-semibold small">State History (${count} transition${count !== 1 ? 's' : ''})</span>
                    <button class="btn btn-sm btn-link text-muted p-0 collapse-toggle"
                            aria-expanded="${!collapsed}" aria-label="${collapsed ? 'Expand' : 'Collapse'} state history">
                        ${collapsed ? 'Expand ▼' : 'Collapse ▲'}
                    </button>
                </div>
                ${collapsed ? '' : this.renderTimeline()}
            </div>
        `;

        this.bindEvents();
    }

    private bindEvents(): void {
        const collapseBtn = this.$('.collapse-toggle');
        collapseBtn?.addEventListener('click', () => {
            const current = this.getStateValue<boolean>('collapsed') ?? false;
            this.setState({ collapsed: !current });
        });

        const showMoreBtn = this.$('.show-more-btn');
        showMoreBtn?.addEventListener('click', () => {
            this.setAttribute('max-visible', String(this._transitions.length));
        });
    }
}

// Register the custom element
if (!customElements.get('ui-state-history')) {
    customElements.define('ui-state-history', StateHistory);
}

export default StateHistory;
