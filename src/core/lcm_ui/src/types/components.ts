/**
 * Component type definitions
 */

/**
 * Component registration options
 */
export interface ComponentRegistration {
    /** Custom element tag name */
    tagName: string;
    /** Component class */
    component: CustomElementConstructor;
    /** Whether to skip if already defined */
    skipIfDefined?: boolean;
}

/**
 * Render context passed to render methods
 */
export interface RenderContext {
    /** Current component state */
    state: Record<string, unknown>;
    /** Component attributes */
    attributes: Record<string, string>;
    /** Access to the component instance */
    component: HTMLElement;
}

/**
 * Event binding definition
 */
export interface EventBinding {
    /** CSS selector for target element(s) */
    selector: string;
    /** DOM event type (click, input, etc.) */
    event: string;
    /** Handler method name or function */
    handler: string | ((event: Event) => void);
    /** Whether to use event delegation */
    delegate?: boolean;
}

/**
 * Store connection options
 */
export interface StoreConnection {
    /** Selector function to extract needed state */
    selector: (state: Record<string, unknown>) => Record<string, unknown>;
    /** Whether to trigger re-render on state change */
    autoRender?: boolean;
    /** Slice names to watch (optimization) */
    watchSlices?: string[];
}

/**
 * Component observed attributes configuration
 */
export interface AttributeConfig {
    /** Attribute name */
    name: string;
    /** Type for conversion (string, number, boolean, json) */
    type?: 'string' | 'number' | 'boolean' | 'json';
    /** Default value if not set */
    default?: unknown;
    /** Whether attribute reflects to property */
    reflect?: boolean;
}

/**
 * Modal component options
 */
export interface ModalOptions {
    /** Modal title */
    title?: string;
    /** Modal size (sm, md, lg, xl) */
    size?: 'sm' | 'md' | 'lg' | 'xl';
    /** Whether clicking backdrop closes modal */
    closeOnBackdrop?: boolean;
    /** Whether ESC key closes modal */
    closeOnEscape?: boolean;
    /** Whether to show close button */
    showCloseButton?: boolean;
    /** Custom CSS classes */
    className?: string;
}

/**
 * Data table pagination options
 */
export interface PaginationOptions {
    /** Current page (1-indexed) */
    page: number;
    /** Items per page */
    pageSize: number;
    /** Total items count */
    total: number;
    /** Available page size options */
    pageSizeOptions?: number[];
}

/**
 * Data table sort state
 */
export interface SortState {
    /** Column key being sorted */
    column: string | null;
    /** Sort direction */
    direction: 'asc' | 'desc';
}

/**
 * Data table filter state
 */
export interface FilterState {
    /** Column key */
    column: string;
    /** Filter value */
    value: string;
    /** Filter operator */
    operator?: 'contains' | 'equals' | 'startsWith' | 'endsWith';
}
