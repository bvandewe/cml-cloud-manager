/**
 * Components module exports
 *
 * Contains Web Components:
 * - BaseComponent: Foundation class for all components
 * - TabView: Tabbed content container
 * - DataTable: Sortable, filterable data table
 * - Modal: Dialog/modal component
 * - ActionBar: Button/action toolbar
 * - MetricCard: Metric display card
 * - StatusBadge: Status indicator badge
 *
 * All components use the `ui-*` element prefix.
 *
 * @example
 * ```typescript
 * import {
 *   BaseComponent,
 *   TabView,
 *   DataTable,
 *   StatusBadge,
 *   Modal,
 *   MetricCard,
 *   ActionBar
 * } from '@neuroglia/ui-core';
 *
 * // Configure global EventBus and StateStore for components
 * configureComponents({ eventBus, store });
 *
 * // Use components in HTML
 * // <ui-data-table id="my-table" selectable></ui-data-table>
 * ```
 *
 * @module components
 */

// ===================== Base Component =====================
export { BaseComponent, configureComponents } from './BaseComponent.js';
export type { BaseComponentConfig } from './BaseComponent.js';

// ===================== Status Badge =====================
export { StatusBadge, STATUS_COLORS, STATUS_ICONS } from './StatusBadge.js';

// ===================== Metric Card =====================
export { MetricCard } from './MetricCard.js';
export type { TrendDirection, MetricCardData } from './MetricCard.js';

// ===================== Tab View =====================
export { Tab, TabView } from './TabView.js';
export type { TabVariant, TabPosition, TabChangeEventDetail } from './TabView.js';

// ===================== Modal =====================
export { Modal, ConfirmModal } from './Modal.js';
export type { ModalSize, ModalContentOptions, ConfirmOptions, AlertOptions } from './Modal.js';

// ===================== Action Bar =====================
export { ActionBar, ActionButton, FilterChip, DropdownAction } from './ActionBar.js';
export type { ActionEventDetail, FilterRemoveEventDetail, ButtonVariant } from './ActionBar.js';

// ===================== Data Table =====================
export { DataTable } from './DataTable.js';
export type { ColumnDefinition, RowAction, BulkAction, SortDirection, PaginationInfo, RowClickEventDetail, RowActionEventDetail, BulkActionEventDetail, SelectionChangeEventDetail, SortChangeEventDetail, PageChangeEventDetail } from './DataTable.js';

// ===================== Shared Types =====================

/**
 * Tab definition for TabView component
 */
export interface TabDefinition {
    /** Unique tab identifier */
    id: string;
    /** Tab label text */
    label: string;
    /** Optional icon class */
    icon?: string;
    /** Whether tab is disabled */
    disabled?: boolean;
    /** Tab content (HTML string or element) */
    content?: string | HTMLElement;
}

/**
 * Status badge mapping
 */
export interface StatusMapping {
    /** CSS class to apply */
    className: string;
    /** Display label */
    label?: string;
    /** Optional icon */
    icon?: string;
}

/**
 * Component lifecycle hooks (for external use)
 */
export interface LifecycleHooks {
    /** Called when component is connected to DOM */
    onConnected?: () => void;
    /** Called when component is disconnected from DOM */
    onDisconnected?: () => void;
    /** Called when an observed attribute changes */
    onAttributeChanged?: (name: string, oldValue: string | null, newValue: string | null) => void;
    /** Called when component state changes */
    onStateChanged?: (newState: Record<string, unknown>, oldState: Record<string, unknown>) => void;
}

// ===================== Component Registration =====================

/**
 * Register all components at once
 * Call this to ensure all custom elements are registered
 */
export function registerAllComponents(): void {
    // Import all modules to trigger custom element registration
    import('./BaseComponent.js');
    import('./StatusBadge.js');
    import('./MetricCard.js');
    import('./TabView.js');
    import('./Modal.js');
    import('./ActionBar.js');
    import('./DataTable.js');

    console.log('[UI Components] All components registered');
}
