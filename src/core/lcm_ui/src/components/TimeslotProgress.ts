/**
 * TimeslotProgress — Inline progress bar showing timeslot consumption
 *
 * Renders a compact progress bar that visually communicates how much of the
 * timeslot window has been consumed, with phase-aware coloring and a
 * countdown/elapsed label.
 *
 * Features:
 * - Progress bar fills from 0% → 100% during the active window
 * - Phase-aware coloring (before=gray, approaching=amber, active=green→warning, teardown=blue, expired=red)
 * - Auto-refresh every 10 seconds
 * - Tooltip with full time range and percentage
 * - Compact enough for table cells (~130px wide)
 *
 * @example
 * ```html
 * <ui-timeslot-progress start="2026-03-10T14:00:00Z" end="2026-03-10T16:00:00Z"></ui-timeslot-progress>
 * ```
 *
 * @module components
 */

import { BaseComponent } from './BaseComponent.js';
import { computeWindowPhase, parseUTCDate } from '../types/columns.js';
import type { TimeslotWindowPhase } from '../types/columns.js';

const REFRESH_INTERVAL = 10_000;

/** Bootstrap color class for progress bar by phase */
const PHASE_BAR_COLORS: Record<TimeslotWindowPhase, string> = {
    before: 'bg-secondary',
    approaching: 'bg-warning',
    active: 'bg-success',
    teardown: 'bg-info',
    expired: 'bg-danger',
};

/**
 * TimeslotProgress Web Component
 *
 * Shows a thin progress bar representing the time consumed within a timeslot window.
 */
export class TimeslotProgress extends BaseComponent {
    static get observedAttributes(): string[] {
        return ['start', 'end', 'lead-time', 'teardown-buffer', 'status'];
    }

    private _refreshInterval: ReturnType<typeof setInterval> | null = null;

    constructor() {
        super();
    }

    protected override onMount(): void {
        this.render();
        this._startRefresh();
    }

    protected override onUnmount(): void {
        this._stopRefresh();
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

    /** Session status — used to grey out terminal sessions */
    get status(): string {
        return this.getAttr('status', '').toLowerCase();
    }

    /** Whether the session is in a terminal state */
    get isTerminal(): boolean {
        const st = this.status;
        return st === 'terminated' || st === 'expired' || st === 'archived';
    }

    // ── Computed Properties ──

    get windowPhase(): TimeslotWindowPhase {
        if (!this.start || !this.end) return 'before';
        return computeWindowPhase(this.start, this.end, this.leadTime, this.teardownBuffer);
    }

    /** Percentage of timeslot consumed (0–100) */
    get progressPercent(): number {
        if (!this.start || !this.end) return 0;
        const now = Date.now();
        const startMs = parseUTCDate(this.start).getTime();
        const endMs = parseUTCDate(this.end).getTime();
        if (isNaN(startMs) || isNaN(endMs)) return 0;
        const total = endMs - startMs;
        if (total <= 0) return 100;
        if (now <= startMs) return 0;
        if (now >= endMs) return 100;
        return Math.round(((now - startMs) / total) * 100);
    }

    // ── Private ──

    private _startRefresh(): void {
        this._stopRefresh();
        this._refreshInterval = setInterval(() => {
            if (this._mounted) this.render();
        }, REFRESH_INTERVAL);
    }

    private _stopRefresh(): void {
        if (this._refreshInterval) {
            clearInterval(this._refreshInterval);
            this._refreshInterval = null;
        }
    }

    private _formatTime(iso: string): string {
        if (!iso) return '';
        const d = parseUTCDate(iso);
        if (isNaN(d.getTime())) return '';
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    private _getRelativeLabel(phase: TimeslotWindowPhase): string {
        const now = Date.now();

        switch (phase) {
            case 'before': {
                const startMs = parseUTCDate(this.start).getTime();
                const diffMin = Math.round((startMs - now) / 60000);
                if (diffMin > 1440) return `in ${Math.round(diffMin / 1440)}d`;
                if (diffMin > 60) return `in ${Math.round(diffMin / 60)}h`;
                return `in ${diffMin}m`;
            }
            case 'approaching': {
                const startMs = parseUTCDate(this.start).getTime();
                const diffMin = Math.round((startMs - now) / 60000);
                return `in ${diffMin}m`;
            }
            case 'active': {
                const endMs = parseUTCDate(this.end).getTime();
                const remainMin = Math.round((endMs - now) / 60000);
                if (remainMin > 60) return `${Math.round(remainMin / 60)}h ${remainMin % 60}m left`;
                return `${remainMin}m left`;
            }
            case 'teardown': {
                return 'teardown';
            }
            case 'expired': {
                const endMs = parseUTCDate(this.end).getTime();
                const agoMin = Math.round((now - endMs) / 60000);
                if (agoMin > 1440) return `${Math.round(agoMin / 1440)}d ago`;
                if (agoMin > 60) return `${Math.round(agoMin / 60)}h ago`;
                return `${agoMin}m ago`;
            }
        }
    }

    private _getDurationLabel(): string {
        if (!this.start || !this.end) return '';
        const startMs = parseUTCDate(this.start).getTime();
        const endMs = parseUTCDate(this.end).getTime();
        if (isNaN(startMs) || isNaN(endMs)) return '';
        const totalMin = Math.round((endMs - startMs) / 60000);
        if (totalMin >= 60) return `${Math.floor(totalMin / 60)}h${totalMin % 60 > 0 ? (totalMin % 60) + 'm' : ''}`;
        return `${totalMin}m`;
    }

    // ── Rendering ──

    override render(): void {
        if (!this.start || !this.end) {
            this.innerHTML = `<span class="text-muted small">—</span>`;
            return;
        }

        const phase = this.windowPhase;
        const pct = this.progressPercent;
        const relLabel = this._getRelativeLabel(phase);
        const timeRange = `${this._formatTime(this.start)}–${this._formatTime(this.end)}`;
        const duration = this._getDurationLabel();

        // Terminal sessions: muted bar, no animation
        const terminal = this.isTerminal;
        let barColor: string;
        let barAnimClass = '';

        if (terminal) {
            barColor = 'bg-secondary';
        } else if (phase === 'active' && pct > 80) {
            barColor = 'bg-warning';
            barAnimClass = 'progress-bar-animated progress-bar-striped';
        } else if (phase === 'active') {
            barColor = PHASE_BAR_COLORS[phase];
            barAnimClass = 'progress-bar-striped';
        } else {
            barColor = PHASE_BAR_COLORS[phase];
        }

        const labelClass = terminal ? 'text-muted' : '';
        const tooltip = `${timeRange} (${duration}) — ${pct}% elapsed`;

        this.innerHTML = `
            <div class="d-flex flex-column gap-0" style="min-width: 110px; max-width: 140px;"
                 data-bs-toggle="tooltip" data-bs-placement="top" title="${tooltip}">
                <div class="d-flex justify-content-between align-items-center mb-0">
                    <span class="small text-nowrap ${labelClass}" style="font-size: 0.7rem; line-height: 1.2;">
                        ${relLabel}
                    </span>
                    <span class="small text-muted text-nowrap" style="font-size: 0.65rem; line-height: 1.2;">
                        ${duration}
                    </span>
                </div>
                <div class="progress" style="height: 5px;" role="progressbar"
                     aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100"
                     aria-label="Timeslot ${pct}% consumed">
                    <div class="progress-bar ${barColor} ${barAnimClass}"
                         style="width: ${pct}%;"></div>
                </div>
            </div>
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
if (!customElements.get('ui-timeslot-progress')) {
    customElements.define('ui-timeslot-progress', TimeslotProgress);
}

export default TimeslotProgress;
