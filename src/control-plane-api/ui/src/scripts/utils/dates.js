/**
 * Date Utility Functions
 * Provides date formatting and relative time utilities
 */

/**
 * Parse a date string ensuring UTC interpretation.
 * Backend sends ISO timestamps without timezone suffix (naive UTC).
 * JavaScript's new Date() treats those as local time, causing offset errors.
 * This function appends 'Z' if no timezone indicator is present.
 * @param {string|Date} dateInput - ISO date string or Date object
 * @returns {Date} Date object with correct UTC interpretation
 */
export function parseUTCDate(dateInput) {
    if (dateInput instanceof Date) return dateInput;
    if (typeof dateInput !== 'string') return new Date(dateInput);
    const s = dateInput.trim();
    // Already has timezone info (Z, +HH:MM, -HH:MM)
    if (/Z$|[+-]\d{2}:\d{2}$|[+-]\d{4}$/.test(s)) {
        return new Date(s);
    }
    // Naive ISO string — treat as UTC
    return new Date(s + 'Z');
}

/**
 * Calculate relative time from a date to now
 * @param {Date|string} dateInput - The date to compare (Date object or ISO string)
 * @returns {string} Relative time string (e.g., "2 hours ago", "in 3 days")
 */
export function getRelativeTime(dateInput) {
    const date = dateInput instanceof Date ? dateInput : parseUTCDate(dateInput);
    const now = new Date();
    const diffMs = now - date;
    const diffSec = Math.floor(diffMs / 1000);
    const diffMin = Math.floor(diffSec / 60);
    const diffHour = Math.floor(diffMin / 60);
    const diffDay = Math.floor(diffHour / 24);
    const diffWeek = Math.floor(diffDay / 7);
    const diffMonth = Math.floor(diffDay / 30);
    const diffYear = Math.floor(diffDay / 365);

    const isFuture = diffMs < 0;
    const prefix = isFuture ? 'in ' : '';
    const suffix = isFuture ? '' : ' ago';

    const absDiffSec = Math.abs(diffSec);
    const absDiffMin = Math.abs(diffMin);
    const absDiffHour = Math.abs(diffHour);
    const absDiffDay = Math.abs(diffDay);
    const absDiffWeek = Math.abs(diffWeek);
    const absDiffMonth = Math.abs(diffMonth);
    const absDiffYear = Math.abs(diffYear);

    if (absDiffSec < 10) {
        return 'just now';
    } else if (absDiffSec < 60) {
        return `${prefix}${absDiffSec} second${absDiffSec !== 1 ? 's' : ''}${suffix}`;
    } else if (absDiffMin < 60) {
        return `${prefix}${absDiffMin} minute${absDiffMin !== 1 ? 's' : ''}${suffix}`;
    } else if (absDiffHour < 24) {
        return `${prefix}${absDiffHour} hour${absDiffHour !== 1 ? 's' : ''}${suffix}`;
    } else if (absDiffDay < 7) {
        return `${prefix}${absDiffDay} day${absDiffDay !== 1 ? 's' : ''}${suffix}`;
    } else if (absDiffWeek < 5) {
        return `${prefix}${absDiffWeek} week${absDiffWeek !== 1 ? 's' : ''}${suffix}`;
    } else if (absDiffMonth < 12) {
        return `${prefix}${absDiffMonth} month${absDiffMonth !== 1 ? 's' : ''}${suffix}`;
    } else {
        return `${prefix}${absDiffYear} year${absDiffYear !== 1 ? 's' : ''}${suffix}`;
    }
}

/**
 * Format a date string with an info icon showing relative time
 * @param {string} dateString - ISO date string
 * @returns {string} HTML string with formatted date and relative time tooltip
 */
export function formatDateWithRelative(dateString) {
    if (!dateString) return 'N/A';

    try {
        const date = parseUTCDate(dateString);
        const formatted = date.toLocaleString();
        const relative = getRelativeTime(date);

        // Generate unique ID for tooltip
        const uniqueId = `date-tooltip-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

        return `${formatted} <i class="bi bi-info-circle text-muted date-tooltip-icon"
                data-bs-toggle="tooltip"
                data-bs-placement="top"
                data-bs-title="${relative}"
                data-tooltip-id="${uniqueId}"
                style="cursor: help;"></i>`;
    } catch (e) {
        return dateString;
    }
}

/**
 * Initialize Bootstrap tooltips for date icons
 * Should be called after rendering content with date tooltips
 */
export function initializeDateTooltips() {
    // Import bootstrap dynamically to avoid circular dependencies
    import('bootstrap').then(bootstrap => {
        const tooltipElements = document.querySelectorAll('.date-tooltip-icon');

        tooltipElements.forEach(element => {
            // Dispose existing tooltip if any
            const existingTooltip = bootstrap.Tooltip.getInstance(element);
            if (existingTooltip) {
                existingTooltip.dispose();
            }

            // Create new tooltip
            const tooltip = new bootstrap.Tooltip(element, {
                trigger: 'hover',
                container: 'body',
            });

            // Ensure tooltip is hidden when mouse leaves
            element.addEventListener('mouseleave', () => {
                tooltip.hide();
            });
        });
    });
}

/**
 * Render a date as "time ago" text with full timestamp in native tooltip.
 * Intended for datatable cell renderers.
 * @param {string} dateString - ISO date string
 * @returns {string} HTML string: relative time with full timestamp tooltip
 */
export function renderTimeAgo(dateString) {
    if (!dateString) return '<span class="text-muted">&mdash;</span>';
    try {
        const date = parseUTCDate(dateString);
        const relative = getRelativeTime(date);
        const full = date.toLocaleString();
        return `<span title="${full}" style="cursor:default;">${relative}</span>`;
    } catch (e) {
        return dateString;
    }
}

/**
 * Format a date string (without relative time, for backward compatibility)
 * @param {string} dateString - ISO date string
 * @returns {string} Formatted date string
 */
export function formatDate(dateString) {
    if (!dateString) return 'N/A';
    const date = parseUTCDate(dateString);
    return date.toLocaleString();
}

/**
 * Format a duration in milliseconds to human-readable string
 * @param {number} durationMs - Duration in milliseconds
 * @returns {string} Human-readable duration string
 */
export function formatDuration(durationMs) {
    if (durationMs <= 0) return '0s';

    const seconds = Math.floor(durationMs / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);

    if (days > 0) {
        const remainingHours = hours % 24;
        return remainingHours > 0 ? `${days}d ${remainingHours}h` : `${days}d`;
    } else if (hours > 0) {
        const remainingMinutes = minutes % 60;
        return remainingMinutes > 0 ? `${hours}h ${remainingMinutes}m` : `${hours}h`;
    } else if (minutes > 0) {
        const remainingSeconds = seconds % 60;
        return remainingSeconds > 0 ? `${minutes}m ${remainingSeconds}s` : `${minutes}m`;
    } else {
        return `${seconds}s`;
    }
}

/**
 * Format a time slot (start to end) with duration
 * @param {string} startTime - ISO date string for start
 * @param {string} endTime - ISO date string for end
 * @returns {string} Formatted time slot string
 */
export function formatTimeSlot(startTime, endTime) {
    if (!startTime || !endTime) return 'N/A';

    try {
        const start = parseUTCDate(startTime);
        const end = parseUTCDate(endTime);
        const durationMs = end - start;

        const startFormatted = start.toLocaleString();
        const endFormatted = end.toLocaleTimeString();
        const duration = formatDuration(durationMs);

        return `${startFormatted} - ${endFormatted} (${duration})`;
    } catch (e) {
        return `${startTime} - ${endTime}`;
    }
}
