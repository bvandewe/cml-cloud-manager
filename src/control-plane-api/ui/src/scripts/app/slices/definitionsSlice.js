/**
 * Definitions Slice
 *
 * State management for Lablet Definitions (lab templates/blueprints).
 * Extracted from the old labletsSlice as part of the M3-PREP domain separation:
 *   - definitionsSlice → Lablet Definitions (this file)
 *   - sessionsSlice   → Lablet Sessions (formerly "instances")
 *
 * Uses the StateStore slice pattern from @neuroglia/ui-core.
 *
 * @module app/slices/definitionsSlice
 */

import { eventBus, LcmEventTypes } from '../eventBus.js';
import * as definitionsApi from '../../api/lablet-definitions.js';

// ==============================================================================
// Initial State
// ==============================================================================

const initialState = {
    /** Map of definition ID to definition object */
    byId: {},
    /** Ordered list of definition IDs */
    allIds: [],
    /** Currently selected definition ID */
    activeId: null,
    /** Loading states */
    loading: {
        list: false,
        detail: false,
    },
    /** Error states */
    errors: {},
    /** Last refresh timestamp */
    lastRefreshedAt: null,
};

// ==============================================================================
// Slice Definition
// ==============================================================================

export const definitionsSlice = {
    name: 'definitions',
    initialState,

    reducers: {
        /**
         * Set active definition
         */
        setActiveDefinition(state, definitionId) {
            return { ...state, activeId: definitionId };
        },

        /**
         * Upsert a single definition (create or merge)
         */
        upsertDefinition(state, definition) {
            if (!definition || !definition.id) return state;

            const isNew = !state.byId[definition.id];
            const existing = state.byId[definition.id] || {};

            const merged = { ...existing };
            Object.entries(definition).forEach(([key, value]) => {
                if (value !== undefined) {
                    merged[key] = value;
                }
            });

            return {
                ...state,
                byId: { ...state.byId, [definition.id]: merged },
                allIds: isNew ? [...state.allIds, definition.id] : state.allIds,
            };
        },

        /**
         * Replace all definitions (full refresh)
         */
        replaceAll(state, definitions) {
            if (!Array.isArray(definitions)) return state;

            const byId = {};
            const allIds = [];

            definitions.forEach(d => {
                if (!d || !d.id) return;
                byId[d.id] = d;
                allIds.push(d.id);
            });

            return {
                ...state,
                byId,
                allIds,
                lastRefreshedAt: new Date().toISOString(),
            };
        },

        /**
         * Remove a definition from state
         */
        removeDefinition(state, definitionId) {
            if (!definitionId) return state;

            const { [definitionId]: _removed, ...restById } = state.byId;
            return {
                ...state,
                byId: restById,
                allIds: state.allIds.filter(id => id !== definitionId),
                activeId: state.activeId === definitionId ? null : state.activeId,
            };
        },

        /**
         * Set list loading state
         */
        setListLoading(state, loading) {
            return {
                ...state,
                loading: { ...state.loading, list: loading },
            };
        },

        /**
         * Set error
         */
        setError(state, { key, error }) {
            return {
                ...state,
                errors: { ...state.errors, [key]: error },
            };
        },

        /**
         * Clear errors
         */
        clearErrors(state) {
            return { ...state, errors: {} };
        },

        /**
         * Reset to initial state
         */
        reset() {
            return initialState;
        },
    },
};

// ==============================================================================
// Selectors
// ==============================================================================

/** Select all definitions as array */
export function selectAllDefinitions(state) {
    const slice = state.definitions || initialState;
    return slice.allIds.map(id => slice.byId[id]).filter(Boolean);
}

/** Select a definition by ID */
export function selectDefinitionById(state, id) {
    return state.definitions?.byId?.[id] || null;
}

/** Select the active definition */
export function selectActiveDefinition(state) {
    const slice = state.definitions || initialState;
    return slice.activeId ? slice.byId[slice.activeId] || null : null;
}

/** Select list loading state */
export function selectDefinitionsListLoading(state) {
    return state.definitions?.loading?.list || false;
}

/** Select definitions count */
export function selectDefinitionsCount(state) {
    return state.definitions?.allIds?.length || 0;
}

/** Select definitions by status */
export function selectDefinitionsByStatus(state, status) {
    return selectAllDefinitions(state).filter(d => d.status === status);
}

/** Select definitions with ACTIVE status (successfully synced, eligible for sessions) */
export function selectActiveDefinitions(state) {
    return selectAllDefinitions(state).filter(d => d.status === 'active');
}

/** Compute definition status summary */
export function selectDefinitionStatusSummary(state) {
    const definitions = selectAllDefinitions(state);
    const summary = {
        total: definitions.length,
        active: 0,
        draft: 0,
        deprecated: 0,
        syncing: 0,
    };

    definitions.forEach(d => {
        const st = d.status?.toLowerCase() || d.sync_status?.toLowerCase();
        if (st === 'active') summary.active++;
        else if (st === 'draft') summary.draft++;
        else if (st === 'deprecated') summary.deprecated++;
        else if (st === 'sync_requested' || st === 'syncing') summary.syncing++;
        else summary.active++; // default to active
    });

    return summary;
}

// ==============================================================================
// Action Creators (API-backed operations)
// ==============================================================================

/**
 * Create action creators bound to a store instance
 * @param {Object} store - The StateStore instance
 * @returns {Object} Action creators
 */
export function createDefinitionsActions(store) {
    return {
        /**
         * Load all definitions from API
         */
        async loadDefinitions(filters = {}) {
            store.dispatch('definitions', 'setListLoading', true);
            try {
                const result = await definitionsApi.listLabletDefinitions(filters);
                const data = Array.isArray(result) ? result : result.items || result.data || [];
                store.dispatch('definitions', 'replaceAll', data);
                eventBus.emit(LcmEventTypes.LABLET_DEFINITIONS_REFRESH_COMPLETED, { count: data.length });
            } catch (error) {
                console.error('[definitionsSlice] Failed to load definitions:', error);
                store.dispatch('definitions', 'setError', { key: '_list', error: error.message });
            } finally {
                store.dispatch('definitions', 'setListLoading', false);
            }
        },

        /**
         * Create a new definition
         */
        async createDefinition(data) {
            try {
                const result = await definitionsApi.createLabletDefinition(data);
                store.dispatch('definitions', 'upsertDefinition', result);
                eventBus.emit(LcmEventTypes.LABLET_DEFINITION_CREATED, result);
                return result;
            } catch (error) {
                console.error('[definitionsSlice] Failed to create definition:', error);
                store.dispatch('definitions', 'setError', { key: '_create', error: error.message });
                throw error;
            }
        },

        /**
         * Update an existing definition
         */
        async updateDefinition(id, data) {
            try {
                const result = await definitionsApi.updateLabletDefinition(id, data);
                store.dispatch('definitions', 'upsertDefinition', result);
                eventBus.emit(LcmEventTypes.LABLET_DEFINITION_UPDATED, result);
                return result;
            } catch (error) {
                console.error('[definitionsSlice] Failed to update definition:', error);
                store.dispatch('definitions', 'setError', { key: id, error: error.message });
                throw error;
            }
        },

        /**
         * Delete a definition
         */
        async deleteDefinition(id) {
            try {
                await definitionsApi.deleteLabletDefinition(id);
                store.dispatch('definitions', 'removeDefinition', id);
                eventBus.emit(LcmEventTypes.LABLET_DEFINITION_DELETED, { definition_id: id });
            } catch (error) {
                console.error('[definitionsSlice] Failed to delete definition:', error);
                store.dispatch('definitions', 'setError', { key: id, error: error.message });
                throw error;
            }
        },

        /**
         * Set the active definition
         */
        setActiveDefinition(definitionId) {
            store.dispatch('definitions', 'setActiveDefinition', definitionId);
        },

        /**
         * Sync a definition with external source
         */
        async syncDefinition(definitionId) {
            try {
                const result = await definitionsApi.syncLabletDefinition(definitionId);
                return result;
            } catch (error) {
                console.error('[definitionsSlice] Failed to sync definition:', error);
                store.dispatch('definitions', 'setError', { key: definitionId, error: error.message });
                throw error;
            }
        },

        /**
         * Load full definition detail (for view/edit modals)
         */
        async loadDefinitionDetail(definitionId) {
            try {
                const def = await definitionsApi.getLabletDefinition(definitionId);
                store.dispatch('definitions', 'upsertDefinition', def);
                return def;
            } catch (error) {
                console.error('[definitionsSlice] Failed to load definition detail:', error);
                store.dispatch('definitions', 'setError', { key: definitionId, error: error.message });
                throw error;
            }
        },
    };
}

export default definitionsSlice;
