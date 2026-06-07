/**
 * Extended Column and Resource Display Type Definitions
 *
 * Provides schema-driven column configuration, expandable row support,
 * and resource state types for rich datatable rendering.
 *
 * @module types/columns
 */

// ===================== State Transition =====================

/**
 * A single state transition in a resource's history
 */
export interface StateTransition {
    /** Previous state */
    from_state: string;
    /** New state */
    to_state: string;
    /** When the transition occurred (ISO datetime) */
    transitioned_at: string;
    /** What triggered the transition */
    triggered_by?: string;
    /** Human-readable reason */
    reason?: string;
    /** Additional metadata */
    metadata?: Record<string, unknown>;
}

// ===================== Lifecycle Phase =====================

/**
 * A single phase in a managed lifecycle
 */
export interface LifecyclePhase {
    /** Phase name (e.g. "Upstream Sync", "POD Setup") */
    name: string;
    /** Type of phase */
    phase_type?: 'pipeline' | 'workflow';
    /** Phase execution status */
    status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped';
    /** When the phase started (ISO datetime) */
    started_at?: string | null;
    /** When the phase completed (ISO datetime) */
    completed_at?: string | null;
}

// ===================== Pipeline Step =====================

/**
 * A single step in a pipeline execution log
 */
export interface PipelineStep {
    /** Step identifier */
    name: string;
    /** Human-readable label */
    label: string;
    /** Step execution status */
    status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped';
    /** Prerequisites (step names) */
    prerequisites: string[];
    /** When the step started (ISO datetime) */
    started_at: string | null;
    /** When the step completed (ISO datetime) */
    completed_at: string | null;
    /** Duration in seconds */
    duration_seconds: number | null;
    /** Input data */
    input: Record<string, unknown> | null;
    /** Output data */
    output: Record<string, unknown> | null;
    /** Error message if failed */
    error: string | null;
    /** Number of retry attempts */
    retry_count: number;
}

// ===================== Resource Observation =====================

/**
 * Per-node telemetry observation
 */
export interface NodeObservation {
    /** Node label */
    label: string;
    /** Node state (e.g. "BOOTED", "STOPPED") */
    state: string;
    /** CPU usage percentage */
    cpu_usage?: number;
    /** Memory usage in MB */
    memory_usage_mb?: number;
    /** Network interfaces */
    interfaces?: string[];
}

/**
 * Aggregate resource telemetry observation
 */
export interface ResourceObservationData {
    /** Overall status */
    status?: string;
    /** CPU usage percentage */
    cpu_usage?: number;
    /** Memory usage percentage */
    memory_usage?: number;
    /** Storage usage percentage */
    storage_usage?: number;
    /** Per-node observations */
    nodes?: NodeObservation[];
}

// ===================== Timeslot =====================

/**
 * Time-bounded resource reservation window
 */
export interface Timeslot {
    /** Window start (ISO datetime) */
    start: string;
    /** Window end (ISO datetime) */
    end: string;
    /** Lead time in minutes */
    lead_time_minutes?: number;
    /** Teardown buffer in minutes */
    teardown_buffer_minutes?: number;
}

/**
 * Computed timeslot window phase
 */
export type TimeslotWindowPhase = 'before' | 'approaching' | 'active' | 'teardown' | 'expired';

// ===================== Expandable Row =====================

/**
 * Configuration for expandable row detail panels in DataTable
 */
export interface ExpandableRowConfig<T = Record<string, unknown>> {
    /** Enable expandable rows */
    enabled: boolean;
    /** Render function for expanded detail panel HTML */
    renderDetail: (row: T) => string;
    /** Whether clicking the row (vs. explicit button) expands it */
    expandOnClick?: boolean;
    /** Only one row expanded at a time */
    singleExpand?: boolean;
    /** Fetch detail data on expand (lazy loading) */
    lazyLoad?: boolean;
    /** REST endpoint template for lazy load (e.g. "/api/sessions/{id}") */
    detailUrl?: string;
}

// ===================== Schema Column =====================

/**
 * Extended column definition for schema-driven datatables.
 *
 * Adds column grouping, visibility control, component-based rendering,
 * and category-based organization to the base ColumnDefinition.
 */
export interface SchemaColumn<T = Record<string, unknown>> {
    /** Column field path (dot-notation for nested, e.g. "license.status") */
    field: string;
    /** Column header label */
    label: string;
    /** Whether column is sortable */
    sortable?: boolean;
    /** Whether column is filterable */
    filterable?: boolean;
    /** Custom cell renderer function */
    render?: (value: unknown, row: T, index: number) => string;
    /** Column width (CSS value) */
    width?: string;
    /** Column alignment */
    align?: 'left' | 'center' | 'right';
    /** Column data type for default formatting */
    type?: 'string' | 'number' | 'date' | 'datetime' | 'boolean';
    /** CSS class for cells */
    className?: string;

    // ── Schema-driven extensions ──

    /** Column group name for two-level headers */
    group?: string;
    /** Default visibility (true = shown by default) */
    visible?: boolean;
    /** Pin column to left or right edge */
    pinned?: 'left' | 'right';
    /** Allow column resize (future) */
    resizable?: boolean;
    /** Tooltip text on column header */
    description?: string;
    /**
     * Category for column picker grouping.
     * Common categories: 'identity', 'status', 'timing', 'metrics',
     * 'lifecycle', 'metadata', 'revision', 'actions'
     */
    category?: string;
    /**
     * Custom element tag to render the cell content.
     * E.g. 'ui-status-badge', 'ui-resource-status', 'ui-timeslot-badge'
     */
    component?: string;
    /**
     * Attribute mapping for the component.
     *
     * Values use simple path resolution:
     * - `'row.field_name'` → resolves to `row[field_name]`
     * - `"'literal'"` → resolves to the literal string (single-quoted)
     * - `true` / `false` → boolean attribute (presence/absence)
     *
     * @example
     * ```
     * componentAttrs: {
     *   status: 'row.status',
     *   'desired-status': 'row.desired_status',
     *   'resource-type': "'worker'",
     *   compact: true
     * }
     * ```
     */
    componentAttrs?: Record<string, string | boolean>;
}

/**
 * Column category definition for the column picker UI
 */
export interface ColumnCategory {
    /** Category identifier */
    id: string;
    /** Display label */
    label: string;
    /** Bootstrap icon class */
    icon?: string;
}

/**
 * Column preset (saved configuration)
 */
export interface ColumnPreset {
    /** Preset name */
    name: string;
    /** Visible column field names */
    columns: string[];
}

/**
 * Reconciliation display state
 */
export type ReconciliationState = 'reconciling' | 'converged' | 'diverged';

// ===================== Design Tokens =====================

/**
 * Status color mapping for reconciliation states
 */
export const RECONCILIATION_COLORS: Record<ReconciliationState, { bg: string; text: string; icon: string }> = {
    reconciling: { bg: 'bg-warning-subtle', text: 'text-warning', icon: 'bi-arrow-repeat' },
    converged: { bg: 'bg-success-subtle', text: 'text-success', icon: 'bi-check-circle' },
    diverged: { bg: 'bg-danger-subtle', text: 'text-danger', icon: 'bi-exclamation-triangle' },
};

/**
 * Status icons for lifecycle phases
 */
export const LIFECYCLE_PHASE_ICONS: Record<string, { icon: string; color: string; animation?: string }> = {
    pending: { icon: '○', color: 'text-muted' },
    running: { icon: '◐', color: 'text-primary', animation: 'lcm-pulse' },
    completed: { icon: '●', color: 'text-success' },
    failed: { icon: '●', color: 'text-danger' },
    skipped: { icon: '◌', color: 'text-muted' },
};

/**
 * Color mapping for timeslot window phases
 */
export const TIMESLOT_PHASE_COLORS: Record<TimeslotWindowPhase, { badge: string; icon: string }> = {
    before: { badge: 'outline-secondary', icon: 'bi-clock' },
    approaching: { badge: 'warning', icon: 'bi-clock-history' },
    active: { badge: 'success', icon: 'bi-play-circle' },
    teardown: { badge: 'info', icon: 'bi-hourglass-split' },
    expired: { badge: 'outline-danger', icon: 'bi-clock-fill' },
};

// ===================== Utility Functions =====================

/**
 * Resolve a componentAttrs value against a row data object.
 *
 * - `'row.field'` → nested field lookup
 * - `"'literal'"` → literal string (single-quoted)
 * - `true` → boolean presence attribute
 * - `false` → omit attribute
 *
 * @param value - The attribute template value
 * @param row - The row data object
 * @returns Resolved string, boolean, or undefined
 */
export function resolveAttrValue(value: string | boolean, row: Record<string, unknown>): string | boolean | undefined {
    if (typeof value === 'boolean') return value;

    // Literal string: "'some value'"
    if (value.startsWith("'") && value.endsWith("'")) {
        return value.slice(1, -1);
    }

    // Row path: "row.field.nested"
    if (value.startsWith('row.')) {
        const path = value.slice(4);
        const resolved = getNestedValue(row, path);
        if (resolved === null || resolved === undefined) return undefined;
        if (typeof resolved === 'object') return JSON.stringify(resolved);
        return String(resolved);
    }

    // Pass through as literal
    return value;
}

/**
 * Get a nested value from an object using dot-notation path
 */
export function getNestedValue(obj: Record<string, unknown>, path: string): unknown {
    return path.split('.').reduce<unknown>((o, k) => {
        if (o && typeof o === 'object' && k in (o as Record<string, unknown>)) {
            return (o as Record<string, unknown>)[k];
        }
        return undefined;
    }, obj);
}

/**
 * Format a relative time string (e.g. "2m ago", "just now")
 */
export function formatRelativeTime(isoDate: string): string {
    const now = Date.now();
    const then = new Date(isoDate).getTime();
    const diffMs = now - then;

    if (isNaN(then)) return '';

    const seconds = Math.floor(diffMs / 1000);
    if (seconds < 0) {
        // Future
        const abs = Math.abs(seconds);
        if (abs < 60) return `in ${abs}s`;
        if (abs < 3600) return `in ${Math.floor(abs / 60)}m`;
        if (abs < 86400) return `in ${Math.floor(abs / 3600)}h`;
        return `in ${Math.floor(abs / 86400)}d`;
    }

    if (seconds < 10) return 'just now';
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
}

/**
 * Format duration in seconds to human-readable string
 */
export function formatDuration(seconds: number): string {
    if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
    return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

/**
 * Parse an ISO date string ensuring UTC interpretation.
 * Backend sends naive ISO timestamps without timezone suffix.
 * JavaScript's `new Date()` treats those as local time, causing offset errors.
 * This appends 'Z' if no timezone indicator is present.
 */
export function parseUTCDate(dateInput: string): Date {
    const s = dateInput.trim();
    // Already has timezone info (Z, +HH:MM, -HH:MM, +HHMM, -HHMM)
    if (/Z$|[+-]\d{2}:\d{2}$|[+-]\d{4}$/.test(s)) {
        return new Date(s);
    }
    // Naive ISO string — treat as UTC
    return new Date(s + 'Z');
}

/**
 * Compute the current window phase of a timeslot
 */
export function computeWindowPhase(start: string, end: string, leadTimeMinutes: number = 0, teardownBufferMinutes: number = 0): TimeslotWindowPhase {
    const now = Date.now();
    const startMs = parseUTCDate(start).getTime();
    const endMs = parseUTCDate(end).getTime();

    if (isNaN(startMs) || isNaN(endMs)) return 'before';

    const leadMs = leadTimeMinutes * 60 * 1000;
    const teardownMs = teardownBufferMinutes * 60 * 1000;

    if (now < startMs - leadMs) return 'before';
    if (now < startMs) return 'approaching';
    if (now < endMs - teardownMs) return 'active';
    if (now < endMs) return 'teardown';
    return 'expired';
}

/**
 * Escape HTML special characters
 */
export function escapeHtml(str: string): string {
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}
