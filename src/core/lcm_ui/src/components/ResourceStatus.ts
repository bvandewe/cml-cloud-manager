/**
 * ResourceStatus - Desired vs Current Status Display
 *
 * Shows a single status badge when the resource is converged,
 * or dual badges with a reconciliation indicator when desired ≠ current.
 *
 * @example
 * ```html
 * <ui-resource-status status="running"></ui-resource-status>
 * <ui-resource-status status="running" desired-status="stopped" resource-type="worker"></ui-resource-status>
 * <ui-resource-status status="running" desired-status="stopped" compact></ui-resource-status>
 * ```
 *
 * @module components
 */

import { BaseComponent } from './BaseComponent.js';
import { STATUS_COLORS, STATUS_ICONS } from './StatusBadge.js';

/**
 * ResourceStatus Web Component
 *
 * Renders current status, and when desired_status differs,
 * shows dual badges with animated transition arrow and "Reconciling…" subtext.
 */
export class ResourceStatus extends BaseComponent {
    static get observedAttributes(): string[] {
        return ['status', 'desired-status', 'resource-type', 'show-arrow', 'compact'];
    }

    constructor() {
        super();
    }

    protected override onMount(): void {
        this.render();
    }

    protected override onAttributeChange(): void {
        if (this._mounted) this.render();
    }

    // ── Attribute Accessors ──

    /** Current resource status */
    get status(): string {
        return this.getAttr('status', 'unknown');
    }

    /** Target/desired status (null when converged or not managed) */
    get desiredStatus(): string | null {
        return this.getAttribute('desired-status');
    }

    /** Resource type for status color mapping */
    get resourceType(): string {
        return this.getAttr('resource-type', '');
    }

    /** Whether to show the transition arrow */
    get showArrow(): boolean {
        const attr = this.getAttribute('show-arrow');
        if (attr !== null) return attr !== 'false';
        return this.isReconciling;
    }

    /** Compact single-line mode for table cells */
    get isCompact(): boolean {
        return this.getBoolAttr('compact');
    }

    /** Whether current ≠ desired (reconciliation in progress) */
    get isReconciling(): boolean {
        const desired = this.desiredStatus;
        return desired !== null && desired !== '' && desired !== this.status;
    }

    // ── Private Helpers ──

    private normalizeStatus(status: string): string {
        return status.toLowerCase().replace(/[- ]/g, '_');
    }

    private formatStatusText(status: string): string {
        return status
            .replace(/_/g, ' ')
            .replace(/-/g, ' ')
            .split(' ')
            .map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
            .join(' ');
    }

    private getColor(status: string): string {
        return STATUS_COLORS[this.normalizeStatus(status)] || 'secondary';
    }

    private getIcon(status: string): string {
        return STATUS_ICONS[this.normalizeStatus(status)] || '';
    }

    private renderBadge(status: string, animated = false): string {
        const color = this.getColor(status);
        const icon = this.getIcon(status);
        const iconHtml = icon ? `<i class="${icon} me-1" aria-hidden="true"></i>` : '';
        const animStyle = animated ? ' animation: lcm-pulse 1.5s infinite;' : '';
        const sizeClass = this.isCompact ? ' badge-sm' : '';
        const label = this.formatStatusText(status);

        return `<span class="badge bg-${color} rounded-pill${sizeClass}" style="${animStyle}" role="status" aria-label="${label}">${iconHtml}${label}</span>`;
    }

    // ── Rendering ──

    override render(): void {
        this.ensureStyles();

        if (!this.isReconciling) {
            this.innerHTML = this.renderBadge(this.status);
            return;
        }

        const currentLabel = this.formatStatusText(this.status);
        const desiredLabel = this.formatStatusText(this.desiredStatus!);

        const arrow = this.showArrow ? `<i class="bi-arrow-right${this.isCompact ? '' : '-circle'} mx-1 text-warning${this.isCompact ? '' : ' mx-2'}" aria-hidden="true" style="animation: lcm-pulse 1.5s infinite;"></i>` : '';

        const reconcileText = this.isCompact ? '' : `<div class="text-warning small mt-1" aria-live="polite"><i class="bi-arrow-repeat lcm-spin me-1" aria-hidden="true"></i>Reconciling…</div>`;

        this.innerHTML = `
            <div class="d-inline-flex align-items-center flex-wrap" role="group"
                 aria-label="Status: ${currentLabel}, transitioning to ${desiredLabel}">
                ${this.renderBadge(this.status)}
                ${arrow}
                ${this.renderBadge(this.desiredStatus!, true)}
            </div>
            ${reconcileText}
        `;
    }

    private ensureStyles(): void {
        if (!document.getElementById('ui-resource-status-styles')) {
            const style = document.createElement('style');
            style.id = 'ui-resource-status-styles';
            style.textContent = `
                @keyframes lcm-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.6; } }
                @keyframes lcm-spin-anim { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
                .lcm-spin { display: inline-block; animation: lcm-spin-anim 1s linear infinite; }
            `;
            document.head.appendChild(style);
        }
    }

    // ── Public API ──

    /** Programmatically update the status */
    setStatus(status: string): void {
        this.setAttribute('status', status);
    }

    /** Programmatically update the desired status */
    setDesiredStatus(status: string | null): void {
        if (status === null) {
            this.removeAttribute('desired-status');
        } else {
            this.setAttribute('desired-status', status);
        }
    }
}

// Register the custom element
if (!customElements.get('ui-resource-status')) {
    customElements.define('ui-resource-status', ResourceStatus);
}

export default ResourceStatus;
