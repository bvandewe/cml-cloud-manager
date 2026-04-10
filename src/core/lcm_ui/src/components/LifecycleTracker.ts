/**
 * LifecycleTracker - Phase/Pipeline Progress Web Component
 *
 * Visualizes a ManagedLifecycle with ordered phases and their status.
 * Supports horizontal (progress bar), vertical (step list), and compact (dots) layouts.
 *
 * @example
 * ```html
 * <ui-lifecycle-tracker phases='[...]' layout="horizontal"></ui-lifecycle-tracker>
 * <ui-lifecycle-tracker phases='[...]' layout="compact"></ui-lifecycle-tracker>
 * <ui-lifecycle-tracker phases='[...]' layout="vertical" show-timing></ui-lifecycle-tracker>
 * ```
 *
 * @module components
 */

import { BaseComponent } from './BaseComponent.js';
import type { LifecyclePhase } from '../types/columns.js';
import { LIFECYCLE_PHASE_ICONS, formatDuration } from '../types/columns.js';

/**
 * LifecycleTracker Web Component
 *
 * Renders lifecycle phases in three layout modes:
 * - compact: colored dots (backward-compatible with pipeline column)
 * - horizontal: inline step badges with arrows
 * - vertical: detailed step list with timing
 */
export class LifecycleTracker extends BaseComponent {
    static get observedAttributes(): string[] {
        return ['phases', 'current-phase', 'layout', 'show-timing', 'interactive'];
    }

    /** Parsed phases (set via attribute or programmatically) */
    private _phases: LifecyclePhase[] = [];

    constructor() {
        super();
    }

    protected override onMount(): void {
        this.ensureStyles();
        this.parsePhases();
        this.render();
    }

    protected override onAttributeChange(name: string): void {
        if (name === 'phases') this.parsePhases();
        if (this._mounted) this.render();
    }

    // ── Attribute Accessors ──

    get currentPhase(): string {
        return this.getAttr('current-phase', '');
    }

    get layout(): 'horizontal' | 'vertical' | 'compact' {
        const val = this.getAttr('layout', 'compact');
        if (val === 'horizontal' || val === 'vertical' || val === 'compact') return val;
        return 'compact';
    }

    get showTiming(): boolean {
        return this.getBoolAttr('show-timing');
    }

    get isInteractive(): boolean {
        return this.getBoolAttr('interactive');
    }

    get phases(): LifecyclePhase[] {
        return this._phases;
    }

    // ── Public API ──

    /** Set phases programmatically */
    setPhases(phases: LifecyclePhase[]): void {
        this._phases = phases;
        if (this._mounted) this.render();
    }

    /** Update a single phase's status */
    updatePhase(name: string, updates: Partial<LifecyclePhase>): void {
        const idx = this._phases.findIndex(p => p.name === name);
        if (idx !== -1) {
            this._phases[idx] = { ...this._phases[idx]!, ...updates };
            if (this._mounted) this.render();
        }
    }

    // ── Private ──

    private parsePhases(): void {
        const raw = this.getAttribute('phases');
        if (!raw) {
            this._phases = [];
            return;
        }
        try {
            this._phases = JSON.parse(raw) as LifecyclePhase[];
        } catch {
            this._phases = [];
        }
    }

    private getPhaseInfo(status: string): { icon: string; color: string; animation?: string } {
        return LIFECYCLE_PHASE_ICONS[status] || LIFECYCLE_PHASE_ICONS['pending']!;
    }

    private computeDuration(phase: LifecyclePhase): string | null {
        if (!phase.started_at) return null;
        if (phase.status === 'running') {
            const elapsed = (Date.now() - new Date(phase.started_at).getTime()) / 1000;
            return formatDuration(elapsed);
        }
        if (phase.completed_at) {
            const dur = (new Date(phase.completed_at).getTime() - new Date(phase.started_at).getTime()) / 1000;
            return formatDuration(dur);
        }
        return null;
    }

    // ── Compact Layout (colored dots) ──

    private renderCompact(): string {
        if (this._phases.length === 0) {
            return `<span class="text-muted" aria-label="No lifecycle phases">—</span>`;
        }

        const dots = this._phases
            .map(p => {
                const info = this.getPhaseInfo(p.status);
                const animClass = info.animation ? ` ${info.animation}` : '';
                return `<span class="${info.color}${animClass}" title="${p.name}: ${p.status}" aria-label="${p.name} ${p.status}" role="img">${info.icon}</span>`;
            })
            .join('');

        return `
            <div class="d-inline-flex align-items-center gap-1" role="list" aria-label="Pipeline progress">
                ${dots}
            </div>
        `;
    }

    // ── Horizontal Layout (step badges with arrows) ──

    private renderHorizontal(): string {
        if (this._phases.length === 0) {
            return `<div class="text-muted small">No lifecycle phases.</div>`;
        }

        const steps = this._phases
            .map(p => {
                const info = this.getPhaseInfo(p.status);
                const animClass = info.animation ? ` ${info.animation}` : '';
                const statusIcon = this.getStatusEmoji(p.status);
                const dur = this.showTiming ? this.computeDuration(p) : null;
                const durText = dur ? `<div class="text-muted small text-center">${dur}</div>` : '';
                const interactiveAttr = this.isInteractive ? `role="button" tabindex="0" data-phase="${p.name}" class="lcm-phase-clickable"` : '';

                return `
                    <div class="text-center" ${interactiveAttr} aria-label="${p.name}: ${p.status}">
                        <div class="${info.color}${animClass}">
                            <span class="badge ${this.getStatusBg(p.status)} rounded-pill">
                                ${statusIcon} ${p.name}
                            </span>
                        </div>
                        ${durText}
                    </div>
                `;
            })
            .join('<i class="bi-arrow-right text-muted mx-1 align-self-start mt-1" aria-hidden="true"></i>');

        return `
            <div class="d-flex align-items-start flex-wrap gap-1" role="list" aria-label="Lifecycle progress">
                ${steps}
            </div>
        `;
    }

    // ── Vertical Layout (detailed step list) ──

    private renderVertical(): string {
        if (this._phases.length === 0) {
            return `<div class="text-muted small">No lifecycle phases.</div>`;
        }

        const items = this._phases
            .map((p, i) => {
                const info = this.getPhaseInfo(p.status);
                const animClass = info.animation ? ` ${info.animation}` : '';
                const statusIcon = this.getStatusEmoji(p.status);
                const dur = this.computeDuration(p);
                const durText = dur ? ` — ${dur}` : '';
                const typeLabel = p.phase_type ? ` (${p.phase_type})` : '';
                const isLast = i === this._phases.length - 1;
                const lineClass = isLast ? '' : 'border-start border-2 ms-2 ps-3 pb-2';
                const interactiveAttr = this.isInteractive ? `role="button" tabindex="0" data-phase="${p.name}" class="lcm-phase-clickable"` : '';

                return `
                    <div class="d-flex align-items-start" ${interactiveAttr} role="listitem">
                        <span class="${info.color}${animClass} me-2 mt-1" aria-hidden="true">${info.icon}</span>
                        <div class="${lineClass}">
                            <div>
                                <strong class="small">${statusIcon} ${p.name}</strong>
                                <span class="text-muted small">${typeLabel}${durText}</span>
                            </div>
                            ${p.status === 'running' ? '<div class="text-primary small">Running…</div>' : ''}
                            ${p.status === 'failed' ? '<div class="text-danger small">Failed</div>' : ''}
                        </div>
                    </div>
                `;
            })
            .join('');

        const currentPhase = this._phases.find(p => p.status === 'running');
        const currentInfo = currentPhase ? `<div class="mt-2 small text-muted">Current Phase: <strong>${currentPhase.name}</strong>${currentPhase.phase_type ? ` (${currentPhase.phase_type})` : ''}</div>` : '';

        return `
            <div role="list" aria-label="Lifecycle phases">
                ${items}
            </div>
            ${currentInfo}
        `;
    }

    // ── Helpers ──

    private getStatusEmoji(status: string): string {
        switch (status) {
            case 'completed':
                return '✅';
            case 'running':
                return '⏳';
            case 'failed':
                return '❌';
            case 'skipped':
                return '⊘';
            default:
                return '⬜';
        }
    }

    private getStatusBg(status: string): string {
        switch (status) {
            case 'completed':
                return 'bg-success-subtle text-success';
            case 'running':
                return 'bg-primary-subtle text-primary';
            case 'failed':
                return 'bg-danger-subtle text-danger';
            case 'skipped':
                return 'bg-secondary-subtle text-secondary';
            default:
                return 'bg-light text-muted';
        }
    }

    // ── Main Render ──

    override render(): void {
        switch (this.layout) {
            case 'compact':
                this.innerHTML = this.renderCompact();
                break;
            case 'horizontal':
                this.innerHTML = this.renderHorizontal();
                break;
            case 'vertical':
                this.innerHTML = this.renderVertical();
                break;
        }

        if (this.isInteractive) {
            this.bindPhaseClicks();
        }
    }

    private bindPhaseClicks(): void {
        for (const el of this.$$('.lcm-phase-clickable')) {
            el.addEventListener('click', () => {
                const phaseName = (el as HTMLElement).dataset['phase'];
                if (phaseName) {
                    this.emitDOMEvent('phase-click', { phase: phaseName });
                }
            });
            el.addEventListener('keydown', e => {
                if ((e as KeyboardEvent).key === 'Enter' || (e as KeyboardEvent).key === ' ') {
                    e.preventDefault();
                    const phaseName = (el as HTMLElement).dataset['phase'];
                    if (phaseName) {
                        this.emitDOMEvent('phase-click', { phase: phaseName });
                    }
                }
            });
        }
    }

    private ensureStyles(): void {
        if (!document.getElementById('ui-lifecycle-tracker-styles')) {
            const style = document.createElement('style');
            style.id = 'ui-lifecycle-tracker-styles';
            style.textContent = `
                @keyframes lcm-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.6; } }
                .lcm-pulse { animation: lcm-pulse 1.5s infinite; }
                .lcm-phase-clickable { cursor: pointer; }
                .lcm-phase-clickable:hover { opacity: 0.8; }
                .lcm-phase-clickable:focus-visible { outline: 2px solid var(--bs-primary); outline-offset: 2px; border-radius: 4px; }
            `;
            document.head.appendChild(style);
        }
    }
}

// Register the custom element
if (!customElements.get('ui-lifecycle-tracker')) {
    customElements.define('ui-lifecycle-tracker', LifecycleTracker);
}

export default LifecycleTracker;
