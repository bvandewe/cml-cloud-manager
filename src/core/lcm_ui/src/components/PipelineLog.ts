/**
 * PipelineLog - Pipeline Execution Log Viewer
 *
 * Detailed execution log for a single pipeline run, showing each step
 * with its output, errors, timing, and retry attempts.
 *
 * @example
 * ```html
 * <ui-pipeline-log pipeline-name="Instantiation" steps='[...]' status="running" attempt="1"></ui-pipeline-log>
 * ```
 *
 * @module components
 */

import { BaseComponent } from './BaseComponent.js';
import type { PipelineStep } from '../types/columns.js';
import { formatDuration, escapeHtml } from '../types/columns.js';

/**
 * PipelineLog Web Component
 *
 * Renders a step-by-step pipeline execution log with:
 * - Expandable/collapsible steps
 * - Live elapsed timer for running steps
 * - Input/output JSON display
 * - Error highlighting for failed steps
 */
export class PipelineLog extends BaseComponent {
    static get observedAttributes(): string[] {
        return ['pipeline-name', 'steps', 'status', 'attempt', 'auto-scroll', 'collapsible'];
    }

    private _steps: PipelineStep[] = [];
    private _timerInterval: ReturnType<typeof setInterval> | null = null;

    constructor() {
        super();
    }

    protected override onMount(): void {
        this.parseSteps();
        this.render();
        this.startTimerIfNeeded();
    }

    protected override onUnmount(): void {
        this.stopTimer();
    }

    protected override onAttributeChange(name: string): void {
        if (name === 'steps') this.parseSteps();
        if (this._mounted) {
            this.render();
            this.startTimerIfNeeded();
        }
    }

    // ── Attribute Accessors ──

    get pipelineName(): string {
        return this.getAttr('pipeline-name', 'Pipeline');
    }

    get pipelineStatus(): string {
        return this.getAttr('status', 'pending');
    }

    get attempt(): number {
        return this.getNumberAttr('attempt', 1);
    }

    get autoScroll(): boolean {
        const attr = this.getAttribute('auto-scroll');
        return attr !== 'false'; // default true
    }

    get isCollapsible(): boolean {
        const attr = this.getAttribute('collapsible');
        return attr !== 'false'; // default true
    }

    get steps(): PipelineStep[] {
        return this._steps;
    }

    // ── Public API ──

    /** Set steps programmatically */
    setSteps(steps: PipelineStep[]): void {
        this._steps = steps;
        if (this._mounted) {
            this.render();
            this.startTimerIfNeeded();
        }
    }

    /** Update a single step */
    updateStep(name: string, updates: Partial<PipelineStep>): void {
        const idx = this._steps.findIndex(s => s.name === name);
        if (idx !== -1) {
            this._steps[idx] = { ...this._steps[idx]!, ...updates };
            if (this._mounted) {
                this.render();
                this.startTimerIfNeeded();
            }
        }
    }

    // ── Private ──

    private parseSteps(): void {
        const raw = this.getAttribute('steps');
        if (!raw) {
            this._steps = [];
            return;
        }
        try {
            this._steps = JSON.parse(raw) as PipelineStep[];
        } catch {
            this._steps = [];
        }
    }

    private startTimerIfNeeded(): void {
        this.stopTimer();
        const hasRunning = this._steps.some(s => s.status === 'running');
        if (hasRunning) {
            this._timerInterval = setInterval(() => {
                this.updateRunningTimers();
            }, 1000);
        }
    }

    private stopTimer(): void {
        if (this._timerInterval) {
            clearInterval(this._timerInterval);
            this._timerInterval = null;
        }
    }

    private updateRunningTimers(): void {
        for (const el of this.$$('.lcm-step-elapsed')) {
            const startedAt = (el as HTMLElement).dataset['startedAt'];
            if (startedAt) {
                const elapsed = (Date.now() - new Date(startedAt).getTime()) / 1000;
                el.textContent = formatDuration(elapsed);
            }
        }
    }

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

    private getOverallStatusEmoji(): string {
        switch (this.pipelineStatus) {
            case 'completed':
                return '✅ Complete';
            case 'running':
                return '⏳ Running';
            case 'failed':
                return '❌ Failed';
            default:
                return '⬜ Pending';
        }
    }

    private renderStepHeader(step: PipelineStep, index: number): string {
        const emoji = this.getStatusEmoji(step.status);
        const isExpandable = this.isCollapsible && step.status !== 'pending';
        const expandIcon = isExpandable ? (step.status === 'running' ? '▼' : '▷') : '▷';
        const dur = step.duration_seconds !== null ? formatDuration(step.duration_seconds) : '';
        const elapsed = step.status === 'running' && step.started_at ? `<span class="lcm-step-elapsed text-primary" data-started-at="${step.started_at}">${formatDuration((Date.now() - new Date(step.started_at).getTime()) / 1000)}</span>` : dur;
        const retryBadge = step.retry_count > 0 ? `<span class="badge bg-warning-subtle text-warning ms-1">retry #${step.retry_count}</span>` : '';

        return `
            <div class="d-flex align-items-center justify-content-between py-1 ${isExpandable ? 'lcm-step-toggle' : ''}"
                 role="${isExpandable ? 'button' : 'text'}"
                 ${isExpandable ? 'tabindex="0"' : ''}
                 data-step-index="${index}"
                 aria-expanded="${step.status === 'running' ? 'true' : 'false'}"
                 aria-label="Step ${index + 1}: ${step.label}, status ${step.status}">
                <div>
                    <span class="me-1">${expandIcon}</span>
                    <strong class="small">Step ${index + 1}: ${escapeHtml(step.label)}</strong>
                    ${retryBadge}
                </div>
                <div class="d-flex align-items-center gap-2">
                    <span>${emoji}</span>
                    <span class="text-muted small">${elapsed}</span>
                </div>
            </div>
        `;
    }

    private renderStepDetail(step: PipelineStep): string {
        const parts: string[] = [];

        if (step.input) {
            parts.push(`
                <div class="mb-1">
                    <span class="text-muted small">Input:</span>
                    <pre class="small bg-light p-2 rounded mb-0 mt-1" style="max-height: 150px; overflow: auto;">${escapeHtml(JSON.stringify(step.input, null, 2))}</pre>
                </div>
            `);
        }

        if (step.output) {
            parts.push(`
                <div class="mb-1">
                    <span class="text-muted small">Output:</span>
                    <pre class="small bg-light p-2 rounded mb-0 mt-1" style="max-height: 150px; overflow: auto;">${escapeHtml(JSON.stringify(step.output, null, 2))}</pre>
                </div>
            `);
        }

        if (step.error) {
            parts.push(`
                <div class="mb-1">
                    <span class="text-danger small">Error:</span>
                    <pre class="small bg-danger-subtle text-danger p-2 rounded mb-0 mt-1">${escapeHtml(step.error)}</pre>
                </div>
            `);
        }

        if (parts.length === 0 && step.status !== 'pending') {
            parts.push(`<div class="text-muted small fst-italic">No details available.</div>`);
        }

        return `<div class="ps-4 pb-2 lcm-step-detail" data-step-index="${this._steps.indexOf(step)}">${parts.join('')}</div>`;
    }

    private renderStep(step: PipelineStep, index: number): string {
        const borderClass = step.status === 'failed' ? 'border-danger' : step.status === 'running' ? 'border-primary' : '';
        const expanded = step.status === 'running' || step.status === 'failed';

        return `
            <div class="border-start border-2 ${borderClass} ps-2 mb-2">
                ${this.renderStepHeader(step, index)}
                ${expanded ? this.renderStepDetail(step) : ''}
            </div>
        `;
    }

    // ── Main Render ──

    override render(): void {
        const totalDuration = this._steps.reduce((sum, s) => sum + (s.duration_seconds || 0), 0);
        const startedStep = this._steps.find(s => s.started_at);
        const startedAt = startedStep?.started_at ? new Date(startedStep.started_at).toLocaleString() : '—';

        const stepsHtml = this._steps.map((s, i) => this.renderStep(s, i)).join('');

        this.innerHTML = `
            <div class="pipeline-log" role="region" aria-label="Pipeline: ${escapeHtml(this.pipelineName)}">
                <div class="d-flex justify-content-between align-items-center border-bottom pb-2 mb-2">
                    <div>
                        <strong>Pipeline: ${escapeHtml(this.pipelineName)}</strong>
                        ${this.attempt > 1 ? `<span class="badge bg-warning-subtle text-warning ms-1">Attempt #${this.attempt}</span>` : ''}
                    </div>
                    <div class="small">Status: ${this.getOverallStatusEmoji()}</div>
                </div>
                <div class="d-flex gap-3 text-muted small mb-3">
                    <span>Started: ${startedAt}</span>
                    ${totalDuration > 0 ? `<span>Duration: ${formatDuration(totalDuration)}</span>` : ''}
                </div>
                <div class="pipeline-steps">
                    ${stepsHtml}
                </div>
            </div>
        `;

        this.bindEvents();
    }

    private bindEvents(): void {
        for (const toggle of this.$$('.lcm-step-toggle')) {
            const handler = () => {
                const index = parseInt((toggle as HTMLElement).dataset['stepIndex'] || '0', 10);
                const detail = this.$(`[data-step-index="${index}"].lcm-step-detail`);
                if (detail) {
                    detail.remove();
                    toggle.setAttribute('aria-expanded', 'false');
                } else {
                    const step = this._steps[index];
                    if (step) {
                        toggle.setAttribute('aria-expanded', 'true');
                        toggle.insertAdjacentHTML('afterend', this.renderStepDetail(step));
                    }
                }
            };
            toggle.addEventListener('click', handler);
            toggle.addEventListener('keydown', e => {
                if ((e as KeyboardEvent).key === 'Enter' || (e as KeyboardEvent).key === ' ') {
                    e.preventDefault();
                    handler();
                }
            });
        }
    }
}

// Register the custom element
if (!customElements.get('ui-pipeline-log')) {
    customElements.define('ui-pipeline-log', PipelineLog);
}

export default PipelineLog;
