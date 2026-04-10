/**
 * LCM App Module
 *
 * Main entry point for the LCM application infrastructure.
 * Re-exports all app-level modules for convenient importing.
 */

// EventBus and event types
export { eventBus, LcmEventTypes, EventTypes } from './eventBus.js';

// Store and slices
export { store, getState, getSlice, subscribe } from './store.js';
export {
    workersSlice,
    selectAllWorkers,
    selectWorkerById,
    selectActiveWorker,
    selectWorkerTiming,
    selectIsListLoading,
    selectIsWorkerLoading,
    selectWorkerError,
    selectWorkersCount,
    selectWorkersByStatus,
    selectFleetCapacity,
    selectWorkerStatusSummary,
    selectWorkersListLoading,
    createWorkersActions,
} from './slices/workersSlice.js';
export {
    definitionsSlice,
    selectAllDefinitions,
    selectDefinitionById,
    selectActiveDefinition,
    selectDefinitionsListLoading,
    selectDefinitionsCount,
    selectDefinitionsByStatus,
    selectActiveDefinitions,
    selectDefinitionStatusSummary,
    createDefinitionsActions,
} from './slices/definitionsSlice.js';
export {
    labRecordsSlice,
    selectAllLabRecords,
    selectLabRecordById,
    selectActiveLabRecord,
    selectIsListLoading as selectLabRecordsListLoading,
    selectLabRecordsCount,
    selectLabRecordsByWorker,
    selectLabRecordsByStatus,
    selectStatusSummary as selectLabRecordStatusSummary,
    selectFilters as selectLabRecordFilters,
    createLabRecordsActions,
} from './slices/labRecordsSlice.js';
export {
    sessionsSlice,
    selectAllSessions,
    selectSessionById,
    selectActiveSession,
    selectActiveSessionDetail,
    selectSessionsListLoading,
    selectSessionDetailLoading,
    selectSessionFilters,
    selectSessionsCount,
    selectSessionsByStatus,
    selectSessionStatusSummary,
    createSessionsActions,
} from './slices/sessionsSlice.js';

export {
    templatesSlice,
    selectAllTemplates,
    selectTemplateById,
    selectTemplatesListLoading,
    selectTemplatesCount,
    selectTemplatesByEnabled,
    selectTemplateStatusSummary,
    createTemplatesActions,
} from './slices/templatesSlice.js';

// SSE
export { lcmSSEAdapter, connect as connectSSE, disconnect as disconnectSSE, getStatus as getSSEStatus } from './sse/sseAdapter.js';
export { sseEventMap, toastEventTypes } from './sse/eventMap.js';
