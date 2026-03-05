/**
 * LcmStatusBadge - Status Badge Web Component
 *
 * Displays a colored badge for entity status with consistent styling.
 *
 * Usage:
 *   <lcm-status-badge status="running"></lcm-status-badge>
 *   <lcm-status-badge status="stopped" size="lg"></lcm-status-badge>
 *
 * @module components/core/LcmStatusBadge
 */

import { BaseComponent } from '../../core/BaseComponent.js';

// Status to Bootstrap color mapping
const STATUS_COLORS = {
    // Worker statuses
    running: 'success',
    stopped: 'secondary',
    stopping: 'warning',
    starting: 'info',
    pending: 'info',
    provisioning: 'info',
    terminated: 'dark',
    error: 'danger',
    failed: 'danger',
    unknown: 'secondary',
    imported: 'primary',

    // Lablet instance statuses
    created: 'info',
    scheduled: 'primary',
    instantiating: 'info',
    collecting: 'warning',
    grading: 'warning',
    graded: 'success',
    archived: 'secondary',

    // Lablet definition statuses
    active: 'success',
    inactive: 'secondary',
    deprecated: 'warning',
    draft: 'info',

    // Generic
    online: 'success',
    offline: 'secondary',
    healthy: 'success',
    unhealthy: 'danger',
    warning: 'warning',
    ok: 'success',

    // CML specific
    cml_ready: 'success',
    cml_not_ready: 'warning',
    cml_unavailable: 'secondary',

    // License statuses
    licensed: 'success',
    unlicensed: 'warning',
    license_error: 'danger',

    // Lab record statuses (Phase 10)
    defined: 'info',
    discovered: 'info',
    importing: 'info',
    imported: 'primary',
    booting: 'warning',
    booted: 'success',
    converging: 'warning',
    converged: 'success',
    stopping: 'warning',
    // stopped: already mapped above
    wiping: 'warning',
    wiped: 'secondary',
    deleting: 'danger',
    deleted: 'dark',
    orphaned: 'warning',
    // archived: already mapped above
    // error: already mapped above

    // LabletRecordRun statuses (Phase 11)
    paused: 'warning',
    ending: 'warning',
    ended: 'secondary',
    faulted: 'danger',
};

// Status to icon mapping
const STATUS_ICONS = {
    running: 'bi-play-circle-fill',
    stopped: 'bi-stop-circle-fill',
    stopping: 'bi-pause-circle-fill',
    starting: 'bi-arrow-repeat',
    pending: 'bi-hourglass-split',
    provisioning: 'bi-gear-wide-connected',
    terminated: 'bi-x-circle-fill',
    error: 'bi-exclamation-circle-fill',
    failed: 'bi-exclamation-triangle-fill',
    unknown: 'bi-question-circle-fill',

    // Lablet instance
    scheduled: 'bi-calendar-check',
    instantiating: 'bi-lightning-charge',
    collecting: 'bi-collection',
    grading: 'bi-pencil-square',
    graded: 'bi-check2-circle',
    archived: 'bi-archive',
    orphaned: 'bi-question-diamond-fill',

    // Generic
    active: 'bi-check-circle-fill',
    inactive: 'bi-circle',
    healthy: 'bi-heart-fill',
    unhealthy: 'bi-heart-pulse-fill',

    // Lab record statuses (Phase 10)
    defined: 'bi-file-earmark-text',
    discovered: 'bi-search',
    importing: 'bi-box-arrow-in-down',
    imported: 'bi-box-arrow-in-down',
    booting: 'bi-power',
    booted: 'bi-play-circle-fill',
    converging: 'bi-arrow-repeat',
    converged: 'bi-check-circle-fill',
    stopping: 'bi-pause-circle-fill',
    wiping: 'bi-eraser',
    wiped: 'bi-eraser-fill',
    deleting: 'bi-trash',
    deleted: 'bi-trash-fill',

    // LabletRecordRun statuses (Phase 11)
    paused: 'bi-pause-circle',
    ending: 'bi-hourglass-bottom',
    ended: 'bi-stop-circle',
    faulted: 'bi-exclamation-diamond-fill',
};

export class LcmStatusBadge extends BaseComponent {
    static get observedAttributes() {
        return ['status', 'size', 'icon', 'pill', 'animated'];
    }

    constructor() {
        super();
    }

    onMount() {
        this.render();
    }

    onAttributeChange() {
        this.render();
    }

    get status() {
        return this.getAttribute('status') || 'unknown';
    }

    get size() {
        return this.getAttribute('size'); // 'sm', 'lg', or default
    }

    get showIcon() {
        return this.hasAttribute('icon');
    }

    get isPill() {
        return this.hasAttribute('pill');
    }

    get isAnimated() {
        return this.hasAttribute('animated');
    }

    get color() {
        const statusKey = this.status.toLowerCase().replace(/[- ]/g, '_');
        return STATUS_COLORS[statusKey] || 'secondary';
    }

    get icon() {
        const statusKey = this.status.toLowerCase().replace(/[- ]/g, '_');
        return STATUS_ICONS[statusKey];
    }

    get displayText() {
        // Convert status to human-readable format
        return this.status
            .replace(/_/g, ' ')
            .replace(/-/g, ' ')
            .split(' ')
            .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
            .join(' ');
    }

    render() {
        let badgeClass = `badge bg-${this.color}`;

        if (this.size === 'sm') {
            badgeClass += ' fs-7'; // Custom small font size
        } else if (this.size === 'lg') {
            badgeClass += ' fs-6 px-3 py-2';
        }

        if (this.isPill) {
            badgeClass += ' rounded-pill';
        }

        const iconHtml = this.showIcon && this.icon ? `<i class="${this.icon} me-1${this.isAnimated ? ' spin-slow' : ''}"></i>` : '';

        // Add pulse animation for active/running states
        const pulseClass = this.isAnimated && ['running', 'starting', 'instantiating'].includes(this.status.toLowerCase()) ? 'pulse-animation' : '';

        this.innerHTML = `
            <span class="${badgeClass} ${pulseClass}">
                ${iconHtml}${this.displayText}
            </span>
        `;

        // Add inline styles for animations
        if (pulseClass) {
            const badge = this.querySelector('.badge');
            if (badge) {
                badge.style.animation = 'pulse 2s infinite';
            }
        }
    }
}

// Add keyframe animation to document if not exists
if (!document.getElementById('lcm-status-badge-styles')) {
    const style = document.createElement('style');
    style.id = 'lcm-status-badge-styles';
    style.textContent = `
        @keyframes pulse {
            0% { opacity: 1; }
            50% { opacity: 0.7; }
            100% { opacity: 1; }
        }
        .spin-slow {
            animation: spin 2s linear infinite;
        }
        @keyframes spin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }
        .fs-7 {
            font-size: 0.75rem !important;
        }
    `;
    document.head.appendChild(style);
}

// Register custom element
if (!customElements.get('lcm-status-badge')) {
    customElements.define('lcm-status-badge', LcmStatusBadge);
}

export default LcmStatusBadge;
