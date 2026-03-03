/**
 * BaseComponent - Base class for all Web Components
 *
 * Provides common functionality:
 * - EventBus integration
 * - Lifecycle management
 * - Shadow DOM utilities
 * - Auto-cleanup on disconnect
 */

import { eventBus } from './EventBus.js';

export class BaseComponent extends HTMLElement {
    constructor() {
        super();
        this._subscriptions = [];
        this._mounted = false;
        this._state = {};
    }

    /**
     * Component lifecycle: called when added to DOM
     */
    connectedCallback() {
        this._mounted = true;
        this.onMount();
    }

    /**
     * Component lifecycle: called when removed from DOM
     */
    disconnectedCallback() {
        this._mounted = false;
        this.cleanup();
        this.onUnmount();
    }

    /**
     * Component lifecycle: called when attributes change
     */
    attributeChangedCallback(name, oldValue, newValue) {
        if (oldValue !== newValue) {
            this.onAttributeChange(name, oldValue, newValue);
        }
    }

    // ========== Lifecycle Hooks (override in subclasses) ==========

    /**
     * Called when component is mounted
     */
    onMount() {}

    /**
     * Called when component is unmounted
     */
    onUnmount() {}

    /**
     * Called when attributes change
     */
    onAttributeChange(name, oldValue, newValue) {}

    // ========== EventBus Integration ==========

    /**
     * Subscribe to event with auto-cleanup
     * @param {string} eventType - Event type
     * @param {Function} handler - Event handler
     */
    subscribe(eventType, handler) {
        const unsubscribe = eventBus.on(eventType, handler.bind(this));
        this._subscriptions.push(unsubscribe);
        return unsubscribe;
    }

    /**
     * Emit event to EventBus
     * @param {string} eventType - Event type
     * @param {*} data - Event payload
     */
    emit(eventType, data) {
        eventBus.emit(eventType, data);
    }

    /**
     * Subscribe once with auto-cleanup
     */
    subscribeOnce(eventType, handler) {
        const unsubscribe = eventBus.once(eventType, handler.bind(this));
        this._subscriptions.push(unsubscribe);
        return unsubscribe;
    }

    // ========== State Management ==========

    /**
     * Set component state and trigger re-render
     */
    setState(updates) {
        const oldState = { ...this._state };
        this._state = { ...this._state, ...updates };

        if (this._mounted) {
            this.onStateChange(oldState, this._state);
            this.render();
        }
    }

    /**
     * Get component state
     */
    getState() {
        return { ...this._state };
    }

    /**
     * Called when state changes (override for side effects)
     */
    onStateChange(oldState, newState) {}

    // ========== Rendering ==========

    /**
     * Render component (override in subclasses)
     */
    render() {}

    /**
     * Helper: render HTML from template string
     */
    html(strings, ...values) {
        return strings.reduce((result, str, i) => {
            return result + str + (values[i] || '');
        }, '');
    }

    /**
     * Helper: query selector within component
     */
    $(selector) {
        return this.querySelector(selector);
    }

    /**
     * Helper: query selector all within component
     */
    $$(selector) {
        return Array.from(this.querySelectorAll(selector));
    }

    // ========== Cleanup ==========

    /**
     * Clean up subscriptions and timers.
     * Handles both plain unsubscribe functions and Subscription objects
     * (from @neuroglia/ui-core EventBus which returns { unsubscribe: () => void }).
     */
    cleanup() {
        this._subscriptions.forEach(sub => {
            if (typeof sub === 'function') {
                sub();
            } else if (sub && typeof sub.unsubscribe === 'function') {
                sub.unsubscribe();
            }
        });
        this._subscriptions = [];
    }

    // ========== Attributes ==========

    /**
     * Get attribute as string
     */
    getAttr(name, defaultValue = null) {
        return this.getAttribute(name) || defaultValue;
    }

    /**
     * Get attribute as boolean
     */
    getBoolAttr(name) {
        return this.hasAttribute(name);
    }

    /**
     * Get attribute as number
     */
    getNumberAttr(name, defaultValue = 0) {
        const val = this.getAttribute(name);
        return val ? parseFloat(val) : defaultValue;
    }

    /**
     * Get attribute as JSON
     */
    getJsonAttr(name, defaultValue = null) {
        const val = this.getAttribute(name);
        try {
            return val ? JSON.parse(val) : defaultValue;
        } catch (e) {
            console.error(`Failed to parse JSON attribute ${name}:`, e);
            return defaultValue;
        }
    }

    /**
     * Set attribute (chainable)
     */
    setAttr(name, value) {
        if (value === null || value === undefined) {
            this.removeAttribute(name);
        } else {
            this.setAttribute(name, value);
        }
        return this;
    }

    // ========== Utilities ==========

    /**
     * Emit custom DOM event (for parent components).
     * Supports two call signatures:
     *   1. dispatchEvent(eventName: string, detail?: object) — convenience shorthand
     *   2. dispatchEvent(event: Event) — native HTMLElement API
     */
    dispatchEvent(eventOrName, detail = {}) {
        // If called with a native Event object, delegate to the native method
        if (eventOrName instanceof Event) {
            return super.dispatchEvent(eventOrName);
        }
        // Otherwise, treat first arg as a string event name (convenience API)
        return super.dispatchEvent(
            new CustomEvent(eventOrName, {
                detail,
                bubbles: true,
                composed: true,
            })
        );
    }

    /**
     * Debounce function calls
     */
    debounce(fn, delay = 300) {
        let timeoutId;
        return (...args) => {
            clearTimeout(timeoutId);
            timeoutId = setTimeout(() => fn.apply(this, args), delay);
        };
    }

    /**
     * Throttle function calls
     */
    throttle(fn, limit = 300) {
        let inThrottle;
        return (...args) => {
            if (!inThrottle) {
                fn.apply(this, args);
                inThrottle = true;
                setTimeout(() => (inThrottle = false), limit);
            }
        };
    }
}

export default BaseComponent;
