/**
 * StatusBadge - Status Indicator Web Component
 *
 * Displays a colored badge for entity status with consistent styling.
 * Supports Bootstrap color themes, icons, and animations.
 *
 * @example
 * ```html
 * <ui-status-badge status="running"></ui-status-badge>
 * <ui-status-badge status="stopped" size="lg" icon pill></ui-status-badge>
 * ```
 *
 * @module components
 */

import { BaseComponent } from './BaseComponent.js';

/**
 * Status to Bootstrap color mapping
 */
export const STATUS_COLORS: Record<string, string> = {
    // Generic statuses
    running: 'success',
    started: 'success',
    active: 'success',
    online: 'success',
    healthy: 'success',
    ok: 'success',
    ready: 'success',
    completed: 'success',
    success: 'success',
    connected: 'success',

    stopped: 'secondary',
    inactive: 'secondary',
    offline: 'secondary',
    idle: 'secondary',
    paused: 'secondary',
    disabled: 'secondary',
    archived: 'secondary',
    unknown: 'secondary',
    disconnected: 'secondary',

    stopping: 'warning',
    starting: 'warning',
    pending: 'warning',
    warning: 'warning',
    degraded: 'warning',
    maintenance: 'warning',
    scheduled: 'warning',
    queued: 'warning',

    provisioning: 'info',
    initializing: 'info',
    instantiating: 'info',
    collecting: 'info',
    grading: 'info',
    processing: 'info',
    loading: 'info',
    created: 'info',
    draft: 'info',
    info: 'info',

    error: 'danger',
    failed: 'danger',
    critical: 'danger',
    unhealthy: 'danger',
    terminated: 'danger',
    expired: 'danger',
    deleted: 'danger',

    imported: 'primary',
    new: 'primary',
    updated: 'primary',
};

/**
 * Status to icon mapping (Bootstrap Icons)
 */
export const STATUS_ICONS: Record<string, string> = {
    running: 'bi-play-circle-fill',
    started: 'bi-play-circle-fill',
    active: 'bi-check-circle-fill',
    online: 'bi-wifi',
    healthy: 'bi-heart-fill',
    ok: 'bi-check-circle-fill',
    ready: 'bi-check-lg',
    completed: 'bi-check-circle-fill',
    success: 'bi-check-circle-fill',
    connected: 'bi-link-45deg',

    stopped: 'bi-stop-circle-fill',
    inactive: 'bi-circle',
    offline: 'bi-wifi-off',
    idle: 'bi-pause-circle',
    paused: 'bi-pause-circle-fill',
    disabled: 'bi-slash-circle',
    archived: 'bi-archive',
    unknown: 'bi-question-circle-fill',
    disconnected: 'bi-x-circle',

    stopping: 'bi-pause-circle-fill',
    starting: 'bi-arrow-repeat',
    pending: 'bi-hourglass-split',
    warning: 'bi-exclamation-triangle-fill',
    degraded: 'bi-exclamation-circle',
    maintenance: 'bi-tools',
    scheduled: 'bi-calendar-check',
    queued: 'bi-list-ol',

    provisioning: 'bi-gear-wide-connected',
    initializing: 'bi-gear',
    instantiating: 'bi-cloud-arrow-up',
    collecting: 'bi-clipboard-data',
    grading: 'bi-mortarboard',
    processing: 'bi-arrow-clockwise',
    loading: 'bi-hourglass',
    created: 'bi-plus-circle',
    draft: 'bi-pencil',
    info: 'bi-info-circle-fill',

    error: 'bi-exclamation-circle-fill',
    failed: 'bi-exclamation-triangle-fill',
    critical: 'bi-x-octagon-fill',
    unhealthy: 'bi-heart-pulse-fill',
    terminated: 'bi-x-circle-fill',
    expired: 'bi-hourglass-bottom',
    deleted: 'bi-trash',

    imported: 'bi-box-arrow-in-down',
    new: 'bi-star-fill',
    updated: 'bi-arrow-clockwise',
};

/**
 * StatusBadge Web Component
 */
export class StatusBadge extends BaseComponent {
    static get observedAttributes(): string[] {
        return ['status', 'size', 'icon', 'pill', 'animated', 'custom-color', 'custom-label'];
    }

    constructor() {
        super();
    }

    protected override onMount(): void {
        this.render();
    }

    protected override onAttributeChange(): void {
        if (this._mounted) {
            this.render();
        }
    }

    /**
     * Get the status value
     */
    get status(): string {
        return this.getAttr('status', 'unknown');
    }

    /**
     * Get the size (sm, lg, or default)
     */
    get size(): string {
        return this.getAttr('size', '');
    }

    /**
     * Whether to show icon
     */
    get showIcon(): boolean {
        return this.getBoolAttr('icon');
    }

    /**
     * Whether to use pill style
     */
    get isPill(): boolean {
        return this.getBoolAttr('pill');
    }

    /**
     * Whether to animate (pulse effect)
     */
    get isAnimated(): boolean {
        return this.getBoolAttr('animated');
    }

    /**
     * Custom color override
     */
    get customColor(): string | null {
        return this.getAttribute('custom-color');
    }

    /**
     * Custom label override
     */
    get customLabel(): string | null {
        return this.getAttribute('custom-label');
    }

    /**
     * Get Bootstrap color for current status
     */
    get color(): string {
        if (this.customColor) return this.customColor;
        const statusKey = this.normalizeStatus(this.status);
        return STATUS_COLORS[statusKey] || 'secondary';
    }

    /**
     * Get icon class for current status
     */
    get iconClass(): string | undefined {
        const statusKey = this.normalizeStatus(this.status);
        return STATUS_ICONS[statusKey];
    }

    /**
     * Get display text for the badge
     */
    get displayText(): string {
        if (this.customLabel) return this.customLabel;
        return this.formatStatusText(this.status);
    }

    /**
     * Normalize status string to key format
     */
    private normalizeStatus(status: string): string {
        return status.toLowerCase().replace(/[- ]/g, '_');
    }

    /**
     * Format status for display
     */
    private formatStatusText(status: string): string {
        return status
            .replace(/_/g, ' ')
            .replace(/-/g, ' ')
            .split(' ')
            .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
            .join(' ');
    }

    /**
     * Update the status programmatically
     */
    setStatus(status: string): void {
        this.setAttribute('status', status);
    }

    override render(): void {
        let badgeClass = `badge bg-${this.color}`;

        // Size modifiers
        if (this.size === 'sm') {
            badgeClass += ' badge-sm';
        } else if (this.size === 'lg') {
            badgeClass += ' fs-6 px-3 py-2';
        }

        // Pill style
        if (this.isPill) {
            badgeClass += ' rounded-pill';
        }

        // Icon HTML
        const iconHtml = this.showIcon && this.iconClass ? `<i class="${this.iconClass} me-1"></i>` : '';

        // Animation style
        const animStyle = this.isAnimated ? 'animation: pulse 1.5s infinite;' : '';

        this.innerHTML = `
      <span class="${badgeClass}" style="${animStyle}">
        ${iconHtml}${this.displayText}
      </span>
    `;

        // Add pulse animation if not already in document
        if (this.isAnimated && !document.getElementById('status-badge-styles')) {
            const style = document.createElement('style');
            style.id = 'status-badge-styles';
            style.textContent = `
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.6; }
        }
      `;
            document.head.appendChild(style);
        }
    }
}

// Register the custom element
if (!customElements.get('ui-status-badge')) {
    customElements.define('ui-status-badge', StatusBadge);
}

export default StatusBadge;
