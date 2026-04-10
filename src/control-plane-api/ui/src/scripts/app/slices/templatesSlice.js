/**
 * Templates Slice
 *
 * State management for Worker Templates.
 * Uses the StateStore slice pattern from @neuroglia/ui-core.
 *
 * Follows the same patterns as workersSlice and labRecordsSlice:
 *   - byId / allIds normalized state
 *   - replaceAll for bulk API refresh
 *   - upsert for SSE-driven single-item updates
 *   - Action creators for API operations (load, create, update, enable, disable, delete)
 */

import { eventBus, LcmEventTypes } from '../eventBus.js';
import * as workerTemplatesApi from '../../api/worker-templates.js';

/**
 * Initial state for templates slice
 */
const initialState = {
    /** Map of template ID to template object */
    byId: {},
    /** Ordered list of template IDs */
    allIds: [],
    /** Loading states */
    loading: {
        list: false,
        details: {},
    },
    /** Error states */
    errors: {},
    /** Last refresh timestamp */
    lastRefreshedAt: null,
};

/**
 * Templates slice definition
 */
export const templatesSlice = {
    name: 'templates',
    initialState,

    /**
     * Reducers — pure functions that update state
     */
    reducers: {
        /**
         * Replace all templates (full refresh from API).
         * Resets byId/allIds to exactly the given array.
         */
        replaceAll(state, templates) {
            if (!Array.isArray(templates)) return state;

            const byId = {};
            const allIds = [];

            templates.forEach(t => {
                if (!t || !t.id) return;
                byId[t.id] = t;
                allIds.push(t.id);
            });

            return {
                ...state,
                byId,
                allIds,
                lastRefreshedAt: new Date().toISOString(),
            };
        },

        /**
         * Upsert a template (create or update)
         */
        upsertTemplate(state, template) {
            if (!template || !template.id) return state;

            const isNew = !state.byId[template.id];
            const existing = state.byId[template.id] || {};

            // Merge template data (allow null to overwrite, skip undefined)
            const merged = { ...existing };
            Object.entries(template).forEach(([key, value]) => {
                if (value !== undefined) {
                    merged[key] = value;
                }
            });

            const newById = {
                ...state.byId,
                [template.id]: merged,
            };

            const newAllIds = isNew ? [...state.allIds, template.id] : state.allIds;

            return {
                ...state,
                byId: newById,
                allIds: newAllIds,
            };
        },

        /**
         * Remove a template
         */
        removeTemplate(state, templateId) {
            if (!templateId || !state.byId[templateId]) return state;

            const { [templateId]: removed, ...restById } = state.byId;

            return {
                ...state,
                byId: restById,
                allIds: state.allIds.filter(id => id !== templateId),
            };
        },

        /**
         * Set list-level loading state
         */
        setListLoading(state, loading) {
            return {
                ...state,
                loading: {
                    ...state.loading,
                    list: loading,
                },
            };
        },

        /**
         * Set error state
         */
        setError(state, { key, error }) {
            return {
                ...state,
                errors: {
                    ...state.errors,
                    [key || '_list']: error,
                },
            };
        },

        /**
         * Clear all errors
         */
        clearErrors(state) {
            return {
                ...state,
                errors: {},
            };
        },

        /**
         * Reset state to initial
         */
        reset() {
            return initialState;
        },
    },
};

// ============================================================================
// Selectors
// ============================================================================

/**
 * Get all templates as an array
 */
export function selectAllTemplates(state) {
    const templates = state.templates;
    if (!templates) return [];
    return templates.allIds.map(id => templates.byId[id]).filter(Boolean);
}

/**
 * Get a template by ID
 */
export function selectTemplateById(state, templateId) {
    return state.templates?.byId?.[templateId] || null;
}

/**
 * Check if templates list is loading
 */
export function selectTemplatesListLoading(state) {
    return state.templates?.loading?.list || false;
}

/**
 * Get templates count
 */
export function selectTemplatesCount(state) {
    return state.templates?.allIds?.length || 0;
}

/**
 * Get templates by enabled status
 */
export function selectTemplatesByEnabled(state, enabled) {
    return selectAllTemplates(state).filter(t => t.enabled === enabled);
}

/**
 * Get template status summary (count by enabled/disabled)
 */
export function selectTemplateStatusSummary(state) {
    const templates = selectAllTemplates(state);
    return {
        total: templates.length,
        enabled: templates.filter(t => t.enabled).length,
        disabled: templates.filter(t => !t.enabled).length,
    };
}

// ============================================================================
// Actions (thunks that dispatch reducers and emit events)
// ============================================================================

/**
 * Create action creators bound to a store instance
 */
export function createTemplatesActions(store) {
    return {
        /**
         * Load all templates from API into the store.
         * @param {boolean} enabledOnly - Only load enabled templates
         */
        async loadTemplates(enabledOnly = false) {
            store.dispatch('templates', 'setListLoading', true);
            try {
                const templates = await workerTemplatesApi.listWorkerTemplates(enabledOnly);
                store.dispatch('templates', 'replaceAll', templates);
                return templates;
            } catch (error) {
                console.error('[templatesSlice] Failed to load templates:', error);
                store.dispatch('templates', 'setError', { key: '_list', error: error.message });
                throw error;
            } finally {
                store.dispatch('templates', 'setListLoading', false);
            }
        },

        /**
         * Create a new template via API.
         * @param {Object} templateData - Template creation data
         * @returns {Promise<Object>} Created template
         */
        async createTemplate(templateData) {
            const result = await workerTemplatesApi.createWorkerTemplate(templateData);
            if (result?.id) {
                store.dispatch('templates', 'upsertTemplate', result);
                eventBus.emit(LcmEventTypes.WORKER_TEMPLATE_CREATED, result);
            }
            return result;
        },

        /**
         * Update an existing template via API.
         * @param {string} templateId - Template UUID
         * @param {Object} updateData - Fields to update
         * @returns {Promise<Object>} Updated template
         */
        async updateTemplate(templateId, updateData) {
            const result = await workerTemplatesApi.updateWorkerTemplate(templateId, updateData);
            if (result?.id) {
                store.dispatch('templates', 'upsertTemplate', result);
                eventBus.emit(LcmEventTypes.WORKER_TEMPLATE_UPDATED, result);
            }
            return result;
        },

        /**
         * Enable a template via API.
         * @param {string} templateId - Template UUID
         */
        async enableTemplate(templateId) {
            const result = await workerTemplatesApi.enableWorkerTemplate(templateId);
            // Optimistic update: set enabled=true immediately
            store.dispatch('templates', 'upsertTemplate', { id: templateId, enabled: true });
            eventBus.emit(LcmEventTypes.WORKER_TEMPLATE_ENABLED, { id: templateId });
            return result;
        },

        /**
         * Disable a template via API.
         * @param {string} templateId - Template UUID
         */
        async disableTemplate(templateId) {
            const result = await workerTemplatesApi.disableWorkerTemplate(templateId);
            // Optimistic update: set enabled=false immediately
            store.dispatch('templates', 'upsertTemplate', { id: templateId, enabled: false });
            eventBus.emit(LcmEventTypes.WORKER_TEMPLATE_DISABLED, { id: templateId });
            return result;
        },

        /**
         * Delete a template via API.
         * @param {string} templateId - Template UUID
         */
        async deleteTemplate(templateId) {
            await workerTemplatesApi.deleteWorkerTemplate(templateId);
            store.dispatch('templates', 'removeTemplate', templateId);
            eventBus.emit(LcmEventTypes.WORKER_TEMPLATE_DELETED, { id: templateId });
        },
    };
}

export default templatesSlice;
