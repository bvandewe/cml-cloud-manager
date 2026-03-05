/**
 * BaseComponent - Foundation Class for Web Components
 *
 * A type-safe base class for building Web Components with:
 * - EventBus integration for pub/sub
 * - StateStore integration for reactive state
 * - Lifecycle hooks (onMount, onUnmount, onStateChange)
 * - Automatic subscription cleanup
 * - Attribute helpers (string, boolean, number, json)
 * - Render utilities
 *
 * @example
 * ```typescript
 * class MyComponent extends BaseComponent {
 *   static override get observedAttributes() { return ['title', 'count']; }
 *
 *   override onMount() {
 *     this.setState({ count: 0 });
 *     this.subscribe('event:type', this.handleEvent.bind(this));
 *   }
 *
 *   override render() {
 *     this.innerHTML = `<h1>${this.getAttr('title')}</h1>`;
 *   }
 * }
 * customElements.define('my-component', MyComponent);
 * ```
 *
 * @module components
 */

import type { EventBus } from '../core/EventBus.js';
import type { StateStore } from '../core/StateStore.js';
import type { Subscription } from '../types/events.js';
import type { StoreConnection, RenderContext } from '../types/components.js';

/**
 * Configuration for BaseComponent
 */
export interface BaseComponentConfig {
    /** EventBus instance for pub/sub */
    eventBus?: EventBus;
    /** StateStore instance for state management */
    store?: StateStore;
    /** Initial component state */
    initialState?: Record<string, unknown>;
    /** Whether to use Shadow DOM */
    useShadow?: boolean;
    /** Shadow DOM mode if using shadow */
    shadowMode?: 'open' | 'closed';
}

/**
 * Global configuration for all BaseComponent instances
 */
let globalEventBus: EventBus | null = null;
let globalStore: StateStore | null = null;

/**
 * Configure global EventBus and StateStore for all components
 */
export function configureComponents(config: { eventBus?: EventBus; store?: StateStore }): void {
    if (config.eventBus) {
        globalEventBus = config.eventBus;
    }
    if (config.store) {
        globalStore = config.store;
    }
}

/**
 * BaseComponent - Base class for all Web Components
 */
export class BaseComponent extends HTMLElement {
    /** Event subscriptions for auto-cleanup */
    protected _subscriptions: Subscription[] = [];
    /** Store subscriptions for auto-cleanup */
    protected _storeSubscriptions: Array<() => void> = [];
    /** Whether component is mounted */
    protected _mounted: boolean = false;
    /** Component-local state */
    protected _state: Record<string, unknown> = {};
    /** Component configuration */
    protected _config: BaseComponentConfig;
    /** Shadow root if using shadow DOM */
    protected _shadow: ShadowRoot | null = null;
    /** Store connection configuration */
    protected _storeConnection: StoreConnection | null = null;
    /** Cached store state for change detection */
    private _cachedStoreState: Record<string, unknown> = {};

    /**
     * Create a new BaseComponent instance
     */
    constructor(config: BaseComponentConfig = {}) {
        super();
        this._config = config;

        // Initialize shadow DOM if requested
        if (config.useShadow) {
            this._shadow = this.attachShadow({ mode: config.shadowMode || 'open' });
        }

        // Initialize state
        if (config.initialState) {
            this._state = { ...config.initialState };
        }
    }

    // ===================== Lifecycle Callbacks =====================

    /**
     * Called when element is added to the DOM
     */
    connectedCallback(): void {
        this._mounted = true;

        // Connect to store if configured
        if (this._storeConnection) {
            this.connectToStore(this._storeConnection);
        }

        this.onMount();
        this.render();
    }

    /**
     * Called when element is removed from the DOM
     */
    disconnectedCallback(): void {
        this._mounted = false;
        this.cleanup();
        this.onUnmount();
    }

    /**
     * Called when observed attributes change
     */
    attributeChangedCallback(name: string, oldValue: string | null, newValue: string | null): void {
        if (oldValue !== newValue) {
            this.onAttributeChange(name, oldValue, newValue);
            if (this._mounted) {
                this.render();
            }
        }
    }

    /**
     * Called when element is moved to a new document
     */
    adoptedCallback(): void {
        this.onAdopted();
    }

    // ===================== Lifecycle Hooks (Override in Subclasses) =====================

    /**
     * Called when component is mounted to DOM
     * Override to add initialization logic
     */
    protected onMount(): void {
        // Override in subclass
    }

    /**
     * Called when component is unmounted from DOM
     * Override to add cleanup logic beyond automatic cleanup
     */
    protected onUnmount(): void {
        // Override in subclass
    }

    /**
     * Called when observed attributes change
     */
    protected onAttributeChange(_name: string, _oldValue: string | null, _newValue: string | null): void {
        // Override in subclass
    }

    /**
     * Called when element is moved to new document
     */
    protected onAdopted(): void {
        // Override in subclass
    }

    /**
     * Called when component state changes
     */
    protected onStateChange(_oldState: Record<string, unknown>, _newState: Record<string, unknown>): void {
        // Override in subclass
    }

    /**
     * Called when connected store state changes
     */
    protected onStoreChange(_state: Record<string, unknown>): void {
        // Override in subclass
    }

    // ===================== Render =====================

    /**
     * Render the component
     * Override to provide component template
     */
    render(): void {
        // Override in subclass
        // Default: do nothing
    }

    /**
     * Get render context for template rendering
     */
    protected getRenderContext(): RenderContext {
        return {
            state: { ...this._state },
            attributes: this.getAttributesObject(),
            component: this,
        };
    }

    /**
     * Get all attributes as object
     */
    protected getAttributesObject(): Record<string, string> {
        const attrs: Record<string, string> = {};
        for (const attr of this.attributes) {
            attrs[attr.name] = attr.value;
        }
        return attrs;
    }

    /**
     * Get the render target (shadow root or this element)
     */
    protected get renderTarget(): HTMLElement | ShadowRoot {
        return this._shadow || this;
    }

    /**
     * Helper: Query selector within component (including shadow DOM)
     */
    protected $(selector: string): Element | null {
        return this.renderTarget.querySelector(selector);
    }

    /**
     * Helper: Query selector all within component
     */
    protected $$(selector: string): Element[] {
        return Array.from(this.renderTarget.querySelectorAll(selector));
    }

    // ===================== State Management =====================

    /**
     * Update component state and trigger re-render
     */
    protected setState(updates: Record<string, unknown>): void {
        const oldState = { ...this._state };
        this._state = { ...this._state, ...updates };

        if (this._mounted) {
            this.onStateChange(oldState, this._state);
            this.render();
        }
    }

    /**
     * Get a copy of the component state
     */
    protected getState(): Record<string, unknown> {
        return { ...this._state };
    }

    /**
     * Get a specific state value
     */
    protected getStateValue<T = unknown>(key: string): T | undefined {
        return this._state[key] as T | undefined;
    }

    // ===================== EventBus Integration =====================

    /**
     * Get the EventBus instance
     */
    protected get eventBus(): EventBus | null {
        return this._config.eventBus || globalEventBus;
    }

    /**
     * Subscribe to EventBus events with auto-cleanup
     */
    protected subscribe<T = unknown>(eventType: string, handler: (data: T) => void): Subscription | null {
        const bus = this.eventBus;
        if (!bus) {
            console.warn('[BaseComponent] No EventBus configured');
            return null;
        }

        const sub = bus.on(eventType, handler as (data: unknown) => void);
        this._subscriptions.push(sub);
        return sub;
    }

    /**
     * Subscribe once to EventBus events
     */
    protected subscribeOnce<T = unknown>(eventType: string, handler: (data: T) => void): Subscription | null {
        const bus = this.eventBus;
        if (!bus) {
            console.warn('[BaseComponent] No EventBus configured');
            return null;
        }

        const sub = bus.once(eventType, handler as (data: unknown) => void);
        this._subscriptions.push(sub);
        return sub;
    }

    /**
     * Emit an event to EventBus
     */
    protected async emit<T = unknown>(eventType: string, data: T): Promise<void> {
        const bus = this.eventBus;
        if (!bus) {
            console.warn('[BaseComponent] No EventBus configured');
            return;
        }

        await bus.emit(eventType, data);
    }

    // ===================== StateStore Integration =====================

    /**
     * Get the StateStore instance
     */
    protected get store(): StateStore | null {
        return this._config.store || globalStore;
    }

    /**
     * Connect to StateStore with a selector
     */
    protected connectToStore(connection: StoreConnection): void {
        const storeInstance = this.store;
        if (!storeInstance) {
            console.warn('[BaseComponent] No StateStore configured');
            return;
        }

        this._storeConnection = connection;

        // Subscribe to state changes - StateStore.subscribe takes a StateListener
        const unsub = storeInstance.subscribe(() => this.handleStoreStateChange());
        this._storeSubscriptions.push(unsub);

        // Initial state sync
        this.handleStoreStateChange();
    }

    /**
     * Handle store state changes
     */
    private handleStoreStateChange(): void {
        const storeInstance = this.store;
        if (!storeInstance || !this._storeConnection) return;

        const fullState = storeInstance.getState() as Record<string, Record<string, unknown>>;

        // Build state from watched slices or full state
        let relevantState: Record<string, unknown>;
        if (this._storeConnection.watchSlices) {
            relevantState = {};
            for (const slice of this._storeConnection.watchSlices) {
                relevantState[slice] = fullState[slice];
            }
        } else {
            relevantState = fullState;
        }

        const selectedState = this._storeConnection.selector(relevantState);

        // Check for actual changes
        if (this.shallowEqual(selectedState, this._cachedStoreState)) {
            return;
        }

        this._cachedStoreState = selectedState;
        this.onStoreChange(selectedState);

        if (this._storeConnection.autoRender && this._mounted) {
            this.render();
        }
    }

    /**
     * Dispatch an action to the store
     */
    protected dispatch(action: { type: string; payload?: unknown }): void {
        const storeInstance = this.store;
        if (!storeInstance) {
            console.warn('[BaseComponent] No StateStore configured');
            return;
        }
        storeInstance.dispatch(action);
    }

    /**
     * Shallow equality check for objects
     */
    private shallowEqual(a: Record<string, unknown>, b: Record<string, unknown>): boolean {
        const keysA = Object.keys(a);
        const keysB = Object.keys(b);

        if (keysA.length !== keysB.length) return false;

        for (const key of keysA) {
            if (a[key] !== b[key]) return false;
        }

        return true;
    }

    // ===================== Attribute Helpers =====================

    /**
     * Get attribute as string
     */
    protected getAttr(name: string, defaultValue: string = ''): string {
        return this.getAttribute(name) ?? defaultValue;
    }

    /**
     * Get attribute as boolean (presence = true)
     */
    protected getBoolAttr(name: string): boolean {
        return this.hasAttribute(name);
    }

    /**
     * Get attribute as number
     */
    protected getNumberAttr(name: string, defaultValue: number = 0): number {
        const val = this.getAttribute(name);
        if (val === null) return defaultValue;
        const num = parseFloat(val);
        return isNaN(num) ? defaultValue : num;
    }

    /**
     * Get attribute as JSON
     */
    protected getJsonAttr<T = unknown>(name: string, defaultValue: T | null = null): T | null {
        const val = this.getAttribute(name);
        if (val === null) return defaultValue;
        try {
            return JSON.parse(val) as T;
        } catch (e) {
            console.warn(`[BaseComponent] Failed to parse JSON attribute "${name}":`, e);
            return defaultValue;
        }
    }

    /**
     * Set attribute (chainable)
     */
    protected setAttr(name: string, value: string | number | boolean | null | undefined): this {
        if (value === null || value === undefined || value === false) {
            this.removeAttribute(name);
        } else if (value === true) {
            this.setAttribute(name, '');
        } else {
            this.setAttribute(name, String(value));
        }
        return this;
    }

    // ===================== DOM Events =====================

    /**
     * Emit a custom DOM event (bubbles up to parent components)
     */
    protected emitDOMEvent<T = unknown>(eventName: string, detail?: T): boolean {
        return this.dispatchEvent(
            new CustomEvent(eventName, {
                detail,
                bubbles: true,
                composed: true, // Cross shadow DOM boundary
            })
        );
    }

    /**
     * Add event listener with auto-cleanup
     */
    protected addListener<K extends keyof HTMLElementEventMap>(target: EventTarget, event: K, handler: (ev: HTMLElementEventMap[K]) => void, options?: AddEventListenerOptions): () => void {
        const boundHandler = handler.bind(this) as EventListener;
        target.addEventListener(event, boundHandler, options);

        const cleanup = () => {
            target.removeEventListener(event, boundHandler, options);
        };

        // Track for auto-cleanup - we'll store as a fake subscription
        this._subscriptions.push({
            unsubscribe: cleanup,
            eventType: `dom:${event}`,
        });

        return cleanup;
    }

    // ===================== Utilities =====================

    /**
     * Debounce a function
     */
    protected debounce<T extends (...args: unknown[]) => unknown>(fn: T, delay: number = 300): T {
        let timeoutId: ReturnType<typeof setTimeout>;

        return ((...args: unknown[]) => {
            clearTimeout(timeoutId);
            timeoutId = setTimeout(() => fn.apply(this, args), delay);
        }) as T;
    }

    /**
     * Throttle a function
     */
    protected throttle<T extends (...args: unknown[]) => unknown>(fn: T, limit: number = 300): T {
        let inThrottle = false;

        return ((...args: unknown[]) => {
            if (!inThrottle) {
                fn.apply(this, args);
                inThrottle = true;
                setTimeout(() => (inThrottle = false), limit);
            }
        }) as T;
    }

    /**
     * Wait for next animation frame
     */
    protected nextFrame(): Promise<void> {
        return new Promise(resolve => requestAnimationFrame(() => resolve()));
    }

    /**
     * Wait for a specified delay
     */
    protected delay(ms: number): Promise<void> {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    // ===================== Cleanup =====================

    /**
     * Clean up all subscriptions and listeners
     */
    protected cleanup(): void {
        // Unsubscribe from all EventBus subscriptions
        for (const sub of this._subscriptions) {
            sub.unsubscribe();
        }
        this._subscriptions = [];

        // Unsubscribe from all store subscriptions
        for (const unsub of this._storeSubscriptions) {
            unsub();
        }
        this._storeSubscriptions = [];
    }
}

export default BaseComponent;
