/**
 * Lablets Slice
 *
 * State management for Lablet Definitions and Lablet Instances.
 * Uses the StateStore slice pattern from @neuroglia/ui-core.
 */

import { eventBus, LcmEventTypes } from '../eventBus.js';

/**
 * Initial state for lablets slice
 */
const initialState = {
    // Lablet Definitions
    definitions: {
        byId: {},
        allIds: [],
        loading: false,
        error: null,
        lastRefreshedAt: null,
    },
    // Lablet Instances
    instances: {
        byId: {},
        allIds: [],
        loading: false,
        error: null,
        lastRefreshedAt: null,
    },
    // Currently selected
    activeDefinitionId: null,
    activeInstanceId: null,
};

/**
 * Lablets slice definition
 */
export const labletsSlice = {
    name: 'lablets',
    initialState,

    /**
     * Reducers
     */
    reducers: {
        // ============== Definitions ==============

        /**
         * Set active definition
         */
        setActiveDefinition(state, definitionId) {
            return {
                ...state,
                activeDefinitionId: definitionId,
            };
        },

        /**
         * Upsert a definition
         */
        upsertDefinition(state, definition) {
            if (!definition || !definition.id) return state;

            const isNew = !state.definitions.byId[definition.id];
            const existing = state.definitions.byId[definition.id] || {};
            const merged = { ...existing, ...definition };

            return {
                ...state,
                definitions: {
                    ...state.definitions,
                    byId: {
                        ...state.definitions.byId,
                        [definition.id]: merged,
                    },
                    allIds: isNew ? [...state.definitions.allIds, definition.id] : state.definitions.allIds,
                },
            };
        },

        /**
         * Upsert multiple definitions
         */
        upsertDefinitions(state, definitions) {
            if (!Array.isArray(definitions)) return state;

            const newById = { ...state.definitions.byId };
            const newIds = [...state.definitions.allIds];

            definitions.forEach(def => {
                if (!def || !def.id) return;
                const isNew = !newById[def.id];
                newById[def.id] = { ...(newById[def.id] || {}), ...def };
                if (isNew) {
                    newIds.push(def.id);
                }
            });

            return {
                ...state,
                definitions: {
                    ...state.definitions,
                    byId: newById,
                    allIds: newIds,
                },
            };
        },

        /**
         * Remove a definition
         */
        removeDefinition(state, definitionId) {
            if (!definitionId) return state;

            const { [definitionId]: removed, ...restById } = state.definitions.byId;

            return {
                ...state,
                definitions: {
                    ...state.definitions,
                    byId: restById,
                    allIds: state.definitions.allIds.filter(id => id !== definitionId),
                },
                activeDefinitionId: state.activeDefinitionId === definitionId ? null : state.activeDefinitionId,
            };
        },

        /**
         * Set definitions loading state
         */
        setDefinitionsLoading(state, loading) {
            return {
                ...state,
                definitions: {
                    ...state.definitions,
                    loading,
                },
            };
        },

        /**
         * Set definitions error
         */
        setDefinitionsError(state, error) {
            return {
                ...state,
                definitions: {
                    ...state.definitions,
                    error,
                    loading: false,
                },
            };
        },

        /**
         * Set definitions last refreshed
         */
        setDefinitionsRefreshed(state, timestamp) {
            return {
                ...state,
                definitions: {
                    ...state.definitions,
                    lastRefreshedAt: timestamp || new Date().toISOString(),
                },
            };
        },

        // ============== Instances ==============

        /**
         * Set active instance
         */
        setActiveInstance(state, instanceId) {
            return {
                ...state,
                activeInstanceId: instanceId,
            };
        },

        /**
         * Upsert an instance
         */
        upsertInstance(state, instance) {
            if (!instance || !instance.id) return state;

            const isNew = !state.instances.byId[instance.id];
            const existing = state.instances.byId[instance.id] || {};
            const merged = { ...existing, ...instance };

            return {
                ...state,
                instances: {
                    ...state.instances,
                    byId: {
                        ...state.instances.byId,
                        [instance.id]: merged,
                    },
                    allIds: isNew ? [...state.instances.allIds, instance.id] : state.instances.allIds,
                },
            };
        },

        /**
         * Upsert multiple instances
         */
        upsertInstances(state, instances) {
            if (!Array.isArray(instances)) return state;

            const newById = { ...state.instances.byId };
            const newIds = [...state.instances.allIds];

            instances.forEach(inst => {
                if (!inst || !inst.id) return;
                const isNew = !newById[inst.id];
                newById[inst.id] = { ...(newById[inst.id] || {}), ...inst };
                if (isNew) {
                    newIds.push(inst.id);
                }
            });

            return {
                ...state,
                instances: {
                    ...state.instances,
                    byId: newById,
                    allIds: newIds,
                },
            };
        },

        /**
         * Remove an instance
         */
        removeInstance(state, instanceId) {
            if (!instanceId) return state;

            const { [instanceId]: removed, ...restById } = state.instances.byId;

            return {
                ...state,
                instances: {
                    ...state.instances,
                    byId: restById,
                    allIds: state.instances.allIds.filter(id => id !== instanceId),
                },
                activeInstanceId: state.activeInstanceId === instanceId ? null : state.activeInstanceId,
            };
        },

        /**
         * Set instances loading state
         */
        setInstancesLoading(state, loading) {
            return {
                ...state,
                instances: {
                    ...state.instances,
                    loading,
                },
            };
        },

        /**
         * Set instances error
         */
        setInstancesError(state, error) {
            return {
                ...state,
                instances: {
                    ...state.instances,
                    error,
                    loading: false,
                },
            };
        },

        /**
         * Set instances last refreshed
         */
        setInstancesRefreshed(state, timestamp) {
            return {
                ...state,
                instances: {
                    ...state.instances,
                    lastRefreshedAt: timestamp || new Date().toISOString(),
                },
            };
        },

        /**
         * Reset to initial state
         */
        reset() {
            return initialState;
        },
    },
};

// ============================================================================
// Selectors
// ============================================================================

// Definitions
export function selectAllDefinitions(state) {
    const defs = state.lablets?.definitions;
    if (!defs) return [];
    return defs.allIds.map(id => defs.byId[id]).filter(Boolean);
}

export function selectDefinitionById(state, id) {
    return state.lablets?.definitions?.byId?.[id] || null;
}

export function selectActiveDefinition(state) {
    const lablets = state.lablets;
    if (!lablets?.activeDefinitionId) return null;
    return lablets.definitions.byId[lablets.activeDefinitionId] || null;
}

export function selectDefinitionsLoading(state) {
    return state.lablets?.definitions?.loading || false;
}

// Instances
export function selectAllInstances(state) {
    const insts = state.lablets?.instances;
    if (!insts) return [];
    return insts.allIds.map(id => insts.byId[id]).filter(Boolean);
}

export function selectInstanceById(state, id) {
    return state.lablets?.instances?.byId?.[id] || null;
}

export function selectActiveInstance(state) {
    const lablets = state.lablets;
    if (!lablets?.activeInstanceId) return null;
    return lablets.instances.byId[lablets.activeInstanceId] || null;
}

export function selectInstancesLoading(state) {
    return state.lablets?.instances?.loading || false;
}

export function selectInstancesByDefinition(state, definitionId) {
    return selectAllInstances(state).filter(i => i.definition_id === definitionId);
}

export function selectInstancesByStatus(state, status) {
    return selectAllInstances(state).filter(i => i.status === status);
}

// ============================================================================
// Actions
// ============================================================================

/**
 * Create action creators bound to a store instance
 */
export function createLabletsActions(store) {
    return {
        // Definitions
        upsertDefinition(definition) {
            const isNew = !store.getState().lablets?.definitions?.byId?.[definition.id];
            store.dispatch('lablets', 'upsertDefinition', definition);
            eventBus.emit(isNew ? LcmEventTypes.LABLET_DEFINITION_CREATED : LcmEventTypes.LABLET_DEFINITION_UPDATED, definition);
        },

        removeDefinition(definitionId) {
            const definition = store.getState().lablets?.definitions?.byId?.[definitionId];
            store.dispatch('lablets', 'removeDefinition', definitionId);
            if (definition) {
                eventBus.emit(LcmEventTypes.LABLET_DEFINITION_DELETED, {
                    definition_id: definitionId,
                    definition,
                });
            }
        },

        // Sessions (Phase 7 — formerly Instances)
        upsertInstance(instance) {
            const isNew = !store.getState().lablets?.instances?.byId?.[instance.id];
            const existing = store.getState().lablets?.instances?.byId?.[instance.id];
            store.dispatch('lablets', 'upsertInstance', instance);

            if (isNew) {
                eventBus.emit(LcmEventTypes.LABLET_SESSION_CREATED, instance);
            } else {
                eventBus.emit(LcmEventTypes.LABLET_SESSION_UPDATED, instance);
                if (existing?.status !== instance.status) {
                    eventBus.emit(LcmEventTypes.LABLET_SESSION_STATUS_CHANGED, {
                        session_id: instance.id,
                        old_status: existing?.status,
                        new_status: instance.status,
                    });
                }
            }
        },

        removeInstance(instanceId) {
            const instance = store.getState().lablets?.instances?.byId?.[instanceId];
            store.dispatch('lablets', 'removeInstance', instanceId);
            if (instance) {
                eventBus.emit(LcmEventTypes.LABLET_SESSION_DELETED, {
                    session_id: instanceId,
                    instance,
                });
            }
        },
    };
}

export default labletsSlice;
