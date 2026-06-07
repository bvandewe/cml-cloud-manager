/**
 * TimeslotBadge - Rich Timeslot Visualization
 *
 * Displays a timeslot with phase-aware coloring, countdown/elapsed times,
 * and auto-refresh every 10 seconds.
 *
 * @example
 * ```html
 * <ui-timeslot-badge start="2026-03-10T14:00:00Z" end="2026-03-10T15:30:00Z"></ui-timeslot-badge>
 * <ui-timeslot-badge start="2026-03-10T14:00:00Z" end="2026-03-10T15:30:00Z" lead-time="15" compact></ui-timeslot-badge>
 * ```
 *
 * @module components
 */

import { BaseComponent } from './BaseComponent.js';
import { computeWindowPhase, parseUTCDate, TIMESLOT_PHASE_COLORS } from '../types/columns.js';
import type { TimeslotWindowPhase } from '../types/columns.js';

/** Auto-refresh interval in milliseconds (10 seconds — SSE is primary, this is fallback) */
const REFRESH_INTERVAL = 10_000;

/**
 * TimeslotBadge Web Component
 *
 * Renders a timeslot with:
 * - Phase-aware coloring (before, approaching, active, teardown, expired)
 * - Countdown or elapsed time
 * - Auto-refresh for relative times
 */
export class TimeslotBadge extends BaseComponent {
    static get observedAttributes(): string[] {
        return ['start', 'end', 'lead-time', 'teardown-buffer', 'compact'];
    }

    private _refreshInterval: ReturnType<typeof setInterval> | null = null;

    constructor() {
        super();
    }

    protected override onMount(): void {
        this.render();
        this.startRefresh();
    }

    protected override onUnmount(): void {
        this.stopRefresh();
    }

    protected override onAttributeChange(): void {
        if (this._mounted) this.render();
    }

    // ── Attribute Accessors ──

    get start(): string {
        return this.getAttr('start', '');
    }

    get end(): string {
        return this.getAttr('end', '');
    }

    get leadTime(): number {
        return this.getNumberAttr('lead-time', 0);
    }

    get teardownBuffer(): number {
        return this.getNumberAttr('teardown-buffer', 0);
    }

    get isCompact(): boolean {
        return this.getBoolAttr('compact');
    }

    /** Computed window phase */
    get windowPhase(): TimeslotWindowPhase {
        if (!this.start || !this.end) return 'before';
        return computeWindowPhase(this.start, this.end, this.leadTime, this.teardownBuffer);
    }

    // ── Private ──

    private startRefresh(): void {
        this.stopRefresh();
        this._refreshInterval = setInterval(() => {
            if (this._mounted) this.render();
        }, REFRESH_INTERVAL);
    }

    private stopRefresh(): void {
        if (this._refreshInterval) {
            clearInterval(this._refreshInterval);
            this._refreshInterval = null;
        }
    }

    private formatTime(iso: string): string {
        if (!iso) return '';
        const d = parseUTCDate(iso);
        if (isNaN(d.getTime())) return '';
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    private formatDate(iso: string): string {
        if (!iso) return '';
        const d = parseUTCDate(iso);
        if (isNaN(d.getTime())) return '';
        return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
    }

    private getRelativeLabel(phase: TimeslotWindowPhase): string {
        const now = Date.now();

        switch (phase) {
            case 'before': {
                const startMs = parseUTCDate(this.start).getTime();
                const diffMin = Math.round((startMs - now) / 60000);
                if (diffMin > 1440) return `Starts in ${Math.round(diffMin / 1440)}d`;
                if (diffMin > 60) return `Starts in ${Math.round(diffMin / 60)}h`;
                return `Starts in ${diffMin}m`;
            }
            case 'approaching': {
                const startMs = parseUTCDate(this.start).getTime();
                const diffMin = Math.round((startMs - now) / 60000);
                return `Starts in ${diffMin}m`;
            }
            case 'active': {
                const endMs = parseUTCDate(this.end).getTime();
                const remainMin = Math.round((endMs - now) / 60000);
                return `${remainMin}m remaining`;
            }
            case 'teardown': {
                return 'Teardown';
            }
            case 'expired': {
                const endMs = parseUTCDate(this.end).getTime();
                const agoMin = Math.round((now - endMs) / 60000);
                if (agoMin > 1440) return `Ended ${Math.round(agoMin / 1440)}d ago`;
                if (agoMin > 60) return `Ended ${Math.round(agoMin / 60)}h ago`;
                return `Ended ${agoMin}m ago`;
            }
        }
    }

    private getPhaseLabel(phase: TimeslotWindowPhase): string {
        switch (phase) {
            case 'before':
                return 'Scheduled';
            case 'approaching':
                return 'Starting Soon';
            case 'active':
                return 'Active';
            case 'teardown':
                return 'Teardown';
            case 'expired':
                return 'Ended';
        }
    }

    // ── Rendering ──

    override render(): void {
        if (!this.start || !this.end) {
            this.innerHTML = `<span class="badge bg-secondary-subtle text-secondary" aria-label="No timeslot">⚪ No timeslot</span>`;
            return;
        }

        const phase = this.windowPhase;
        const colors = TIMESLOT_PHASE_COLORS[phase];
        const timeRange = `${this.formatTime(this.start)}–${this.formatTime(this.end)}`;
        const dateStr = this.formatDate(this.start);
        const relativeLabel = this.getRelativeLabel(phase);
        const phaseLabel = this.getPhaseLabel(phase);

        if (this.isCompact) {
            this.innerHTML = `
                <span class="badge bg-${colors.badge} rounded-pill" role="status"
                      aria-label="${phaseLabel}: ${timeRange}, ${relativeLabel}"
                      title="${dateStr} ${timeRange} — ${relativeLabel}">
                    <i class="${colors.icon} me-1" aria-hidden="true"></i>
                    ${timeRange}
                </span>
            `;
            return;
        }

        this.innerHTML = `
            <span class="badge bg-${colors.badge} rounded-pill" role="status"
                  aria-label="${phaseLabel}: ${dateStr} ${timeRange}, ${relativeLabel}">
                <i class="${colors.icon} me-1" aria-hidden="true"></i>
                ${phaseLabel} ${timeRange}
                <span class="ms-1 opacity-75">(${relativeLabel})</span>
            </span>
        `;
    }

    // ── Public API ──

    /** Programmatically set the timeslot */
    setTimeslot(start: string, end: string): void {
        this.setAttribute('start', start);
        this.setAttribute('end', end);
    }
}

// Register the custom element
if (!customElements.get('ui-timeslot-badge')) {
    customElements.define('ui-timeslot-badge', TimeslotBadge);
}

export default TimeslotBadge;
