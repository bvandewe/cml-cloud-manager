/**
 * StoreConnectedPage — Base class for store-driven page components
 *
 * Extends CPA's BaseComponent with StateStore integration, providing:
 *   - Store subscription lifecycle (auto-subscribe on mount, auto-cleanup on unmount)
 *   - Selector-based re-rendering when store state changes
 *   - Action creator binding (lazily created, cached)
 *   - Structured page lifecycle: initialize() → render() → subscribeToStore()
 *
 * Usage pattern (for v2 migration pages):
 *
 * ```javascript
 * import { StoreConnectedPage } from '../../bridge/StoreConnectedPage.js';
 * import { store } from '../../app/store.js';
 * import { selectAllLabRecords, createLabRecordsActions } from '../../app/slices/labRecordsSlice.js';
 *
 * class LabRecordsPageV2 extends StoreConnectedPage {
 *     getStoreInstance() { return store; }
 *     getActionCreators(store) { return createLabRecordsActions(store); }
 *
 *     subscribeToStore() {
 *         this.connectSlice('labRecords', selectAllLabRecords, (records) => {
 *             this._updateDataTable(records);
 *         });
 *     }
 * }
 * ```
 *
 * @module bridge/StoreConnectedPage
 */

import { BaseComponent } from '../core/BaseComponent.js';

export class StoreConnectedPage extends BaseComponent {
    constructor() {
        super();
        /** @type {Function[]} Store unsubscribe functions (separate from EventBus subs) */
        this._storeSubscriptions = [];
        /** @type {Object|null} Cached action creators bound to the store */
        this._actions = null;
        /** @type {Object|null} Current user context */
        this._currentUser = null;
        /** @type {boolean} Whether the page has been initialized */
        this._initialized = false;
    }

    // =========================================================================
    // Overridable Hooks (subclasses MUST/SHOULD implement)
    // =========================================================================

    /**
     * Return the StateStore instance. Subclasses MUST override.
     * @returns {import('@neuroglia/ui-core').StateStore}
     */
    getStoreInstance() {
        throw new Error('StoreConnectedPage subclass must implement getStoreInstance()');
    }

    /**
     * Return action creators bound to the store. Subclasses SHOULD override.
     * Called once, result is cached in this.actions.
     * @param {import('@neuroglia/ui-core').StateStore} store
     * @returns {Object} Map of action creator functions
     */
    getActionCreators(_store) {
        return {};
    }

    /**
     * Set up store subscriptions. Subclasses SHOULD override.
     * Called after initial render when the page is mounted and initialized.
     * Use this.connectSlice() inside this method.
     */
    subscribeToStore() {}

    /**
     * Called when store-connected state changes.
     * Override for side effects beyond the per-subscription callbacks.
     * @param {string} sliceName - Which slice changed
     * @param {*} newValue - New derived value from selector
     */
    onStoreChange(_sliceName, _newValue) {}

    // =========================================================================
    // Store Integration API
    // =========================================================================

    /**
     * Lazily-initialized action creators.
     * @returns {Object}
     */
    get actions() {
        if (!this._actions) {
            this._actions = this.getActionCreators(this.getStoreInstance());
        }
        return this._actions;
    }

    /**
     * Subscribe to a store slice with a selector.
     * Automatically unsubscribes on page unmount.
     *
     * Uses a raw StateStore listener internally, applying the selector
     * on each state change and only invoking the callback when the
     * selected value actually changes (by reference).
     *
     * @param {string} sliceName - Slice name (for logging/onStoreChange)
     * @param {Function} selector - (state) => derivedValue
     * @param {Function} callback - (derivedValue) => void, called on change
     * @returns {Function} Unsubscribe function
     */
    connectSlice(sliceName, selector, callback) {
        const store = this.getStoreInstance();
        let previousValue = selector(store.getState());

        // StateStore.subscribe accepts a single listener: (newState, oldState, action) => void
        const unsubscribe = store.subscribe(newState => {
            const newValue = selector(newState);
            if (newValue !== previousValue) {
                previousValue = newValue;
                callback(newValue);
                this.onStoreChange(sliceName, newValue);
            }
        });
        this._storeSubscriptions.push(unsubscribe);
        return unsubscribe;
    }

    /**
     * Dispatch an action to a store slice.
     * Convenience wrapper around store.dispatch().
     *
     * @param {string} sliceName
     * @param {string} reducerName
     * @param {*} payload
     */
    dispatch(sliceName, reducerName, payload) {
        this.getStoreInstance().dispatch(sliceName, reducerName, payload);
    }

    /**
     * Get current state snapshot from the store.
     * @returns {Object}
     */
    getStoreState() {
        return this.getStoreInstance().getState();
    }

    /**
     * Get a specific slice of state.
     * @param {string} sliceName
     * @returns {Object}
     */
    getSliceState(sliceName) {
        return this.getStoreInstance().getSlice(sliceName);
    }

    // =========================================================================
    // Page Lifecycle
    // =========================================================================

    /**
     * Initialize the page with user context.
     * This is the main entry point called by app.js showView().
     *
     * Lifecycle: initialize() → render() → subscribeToStore() → loadData()
     *
     * @param {Object} user - Current user object with roles
     */
    initialize(user) {
        if (this._initialized) return;
        this._currentUser = user;
        this._initialized = true;

        this.render();
        this._setupPageEventListeners();
        this.subscribeToStore();

        // Kick off initial data load after DOM is ready
        requestAnimationFrame(() => {
            this.loadInitialData();
        });
    }

    /**
     * Load initial data from the store/API. Subclasses SHOULD override.
     * Called after render + subscribeToStore, in a requestAnimationFrame.
     */
    loadInitialData() {}

    /**
     * Set up page-level event listeners (EventBus). Subclasses SHOULD override.
     * Called during initialize(), after render().
     */
    _setupPageEventListeners() {}

    // =========================================================================
    // Role Helpers
    // =========================================================================

    /**
     * Check if current user has admin or manager role.
     * @returns {boolean}
     */
    isAdminOrManager() {
        if (!this._currentUser?.roles) return false;
        const adminRoles = ['admin', 'manager', 'lcm-admin', 'lcm-manager'];
        return this._currentUser.roles.some(role => adminRoles.includes(role.toLowerCase()));
    }

    // =========================================================================
    // Lifecycle Overrides
    // =========================================================================

    /**
     * Called on connectedCallback. Shows loading state.
     */
    onMount() {
        if (!this._initialized) {
            this.innerHTML = this._renderLoadingSpinner();
        }
    }

    /**
     * Cleanup store subscriptions + EventBus subscriptions on unmount.
     */
    onUnmount() {
        this._cleanupStoreSubscriptions();
    }

    /**
     * Override cleanup to also clear store subscriptions.
     */
    cleanup() {
        this._cleanupStoreSubscriptions();
        super.cleanup();
    }

    // =========================================================================
    // Internal Helpers
    // =========================================================================

    _cleanupStoreSubscriptions() {
        this._storeSubscriptions.forEach(unsub => {
            if (typeof unsub === 'function') {
                unsub();
            } else if (unsub && typeof unsub.unsubscribe === 'function') {
                unsub.unsubscribe();
            }
        });
        this._storeSubscriptions = [];
    }

    _renderLoadingSpinner() {
        return `
            <div class="d-flex justify-content-center align-items-center py-5">
                <div class="spinner-border text-primary" role="status">
                    <span class="visually-hidden">Loading...</span>
                </div>
            </div>
        `;
    }
}

export default StoreConnectedPage;
