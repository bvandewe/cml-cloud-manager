/**
 * RevisionIndicator - Version / Revision Display
 *
 * Shows a resource's state_version with change-since-last-view indicator.
 * Persists last-viewed version in localStorage per resource ID.
 *
 * @example
 * ```html
 * <ui-revision-indicator version="12" resource-id="worker-abc"></ui-revision-indicator>
 * <ui-revision-indicator version="5" resource-id="session-xyz" compact></ui-revision-indicator>
 * ```
 *
 * @module components
 */

import { BaseComponent } from './BaseComponent.js';

/** localStorage key prefix for last-seen versions */
const STORAGE_PREFIX = 'lcm.revision.';

/**
 * RevisionIndicator Web Component
 *
 * Displays version number with delta badge showing changes since last view.
 * Clicking emits 'revision-clicked' event and updates last-seen version.
 */
export class RevisionIndicator extends BaseComponent {
    static get observedAttributes(): string[] {
        return ['version', 'previous-version', 'resource-id', 'compact'];
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

    /** Current state_version */
    get version(): number {
        return this.getNumberAttr('version', 0);
    }

    /** Explicitly provided previous version (overrides localStorage) */
    get previousVersion(): number | null {
        const attr = this.getAttribute('previous-version');
        if (attr === null) return null;
        const num = parseInt(attr, 10);
        return isNaN(num) ? null : num;
    }

    /** Resource ID for localStorage tracking */
    get resourceId(): string {
        return this.getAttr('resource-id', '');
    }

    /** Compact badge-only mode */
    get isCompact(): boolean {
        return this.getBoolAttr('compact');
    }

    // ── Public API ──

    /** Get the last-seen version from localStorage or explicit attribute */
    getLastSeenVersion(): number | null {
        if (this.previousVersion !== null) return this.previousVersion;
        if (!this.resourceId) return null;

        const stored = localStorage.getItem(`${STORAGE_PREFIX}${this.resourceId}`);
        if (stored === null) return null;
        const num = parseInt(stored, 10);
        return isNaN(num) ? null : num;
    }

    /** Mark the current version as seen (persist to localStorage) */
    markAsSeen(): void {
        if (this.resourceId && this.version > 0) {
            localStorage.setItem(`${STORAGE_PREFIX}${this.resourceId}`, String(this.version));
        }
    }

    /** Get the delta between current and last-seen version */
    get delta(): number | null {
        const lastSeen = this.getLastSeenVersion();
        if (lastSeen === null) return null;
        const diff = this.version - lastSeen;
        return diff > 0 ? diff : null;
    }

    // ── Rendering ──

    override render(): void {
        const delta = this.delta;
        const deltaHtml = delta ? `<span class="badge bg-info-subtle text-info ms-1" aria-label="${delta} changes since last viewed">△+${delta}</span>` : '';

        if (this.isCompact) {
            this.innerHTML = `
                <span class="lcm-revision-badge text-muted small" role="button" tabindex="0"
                      aria-label="Version ${this.version}${delta ? `, ${delta} new changes` : ''}"
                      title="Version ${this.version}${delta ? ` (${delta} new changes)` : ''}">
                    v${this.version}${deltaHtml}
                </span>
            `;
        } else {
            this.innerHTML = `
                <span class="lcm-revision-badge badge bg-light text-dark border" role="button" tabindex="0"
                      aria-label="Version ${this.version}${delta ? `, ${delta} new changes` : ''}"
                      title="Click to view state history">
                    v${this.version}${deltaHtml}
                </span>
            `;
        }

        this.bindEvents();
    }

    private bindEvents(): void {
        const badge = this.$('.lcm-revision-badge');
        if (!badge) return;

        const handleClick = () => {
            this.markAsSeen();
            this.emitDOMEvent('revision-clicked', {
                version: this.version,
                resourceId: this.resourceId,
            });
            this.render();
        };

        badge.addEventListener('click', handleClick);
        badge.addEventListener('keydown', e => {
            if ((e as KeyboardEvent).key === 'Enter' || (e as KeyboardEvent).key === ' ') {
                e.preventDefault();
                handleClick();
            }
        });
    }
}

// Register the custom element
if (!customElements.get('ui-revision-indicator')) {
    customElements.define('ui-revision-indicator', RevisionIndicator);
}

export default RevisionIndicator;
