import { describe, expect, it, vi } from 'vitest';

import { LcmSSEAdapter } from '../../src/scripts/app/sse/sseAdapter.js';
import { LcmEventTypes } from '../../src/scripts/app/eventTypes.js';
import { sseEventMap } from '../../src/scripts/app/sse/eventMap.js';
import { eventBus } from '../../src/scripts/app/eventBus.js';
import { store } from '../../src/scripts/app/store.js';

describe('LcmSSEAdapter normalization helpers', () => {
    const adapter = new LcmSSEAdapter();

    it('normalizes lablet definition identifiers to id', () => {
        const normalized = adapter._normalizeDefinitionRecord({
            definition_id: 'def-123',
            sync_status: 'sync_requested',
        });

        expect(normalized.id).toBe('def-123');
        expect(normalized.definition_id).toBe('def-123');
        expect(normalized.sync_status).toBe('sync_requested');
    });

    it('merges definition change payloads into the top-level record', () => {
        const normalized = adapter._normalizeDefinitionRecord({
            definition_id: 'def-456',
            changes: {
                name: 'Updated Definition',
                warm_pool_depth: 3,
            },
            updated_at: '2026-04-13T12:00:00Z',
        });

        expect(normalized.id).toBe('def-456');
        expect(normalized.name).toBe('Updated Definition');
        expect(normalized.warm_pool_depth).toBe(3);
        expect(normalized.updated_at).toBe('2026-04-13T12:00:00Z');
    });

    it('normalizes worker template identifiers to id', () => {
        const normalized = adapter._normalizeTemplateRecord({
            template_id: 'tpl-123',
            name: 'm5zn.metal',
        });

        expect(normalized.id).toBe('tpl-123');
        expect(normalized.template_id).toBe('tpl-123');
        expect(normalized.name).toBe('m5zn.metal');
    });
});

describe('sseEventMap template coverage', () => {
    it('maps worker template enabled and disabled SSE events', () => {
        expect(sseEventMap['worker.template.enabled']).toBe(LcmEventTypes.WORKER_TEMPLATE_ENABLED);
        expect(sseEventMap['worker.template.disabled']).toBe(LcmEventTypes.WORKER_TEMPLATE_DISABLED);
    });
});

// =============================================================================
// ADR-041: WebSocket-derived SSE event mapping
// =============================================================================

describe('sseEventMap ADR-041 WebSocket events', () => {
    it('maps worker.lab.state_change to WORKER_LAB_STATE_CHANGE', () => {
        expect(sseEventMap['worker.lab.state_change']).toBe(LcmEventTypes.WORKER_LAB_STATE_CHANGE);
    });

    it('maps worker.lab.stats_updated to WORKER_LAB_STATS_UPDATED', () => {
        expect(sseEventMap['worker.lab.stats_updated']).toBe(LcmEventTypes.WORKER_LAB_STATS_UPDATED);
    });

    it('maps worker.ws.connected to WORKER_WS_CONNECTED', () => {
        expect(sseEventMap['worker.ws.connected']).toBe(LcmEventTypes.WORKER_WS_CONNECTED);
    });

    it('maps worker.ws.disconnected to WORKER_WS_DISCONNECTED', () => {
        expect(sseEventMap['worker.ws.disconnected']).toBe(LcmEventTypes.WORKER_WS_DISCONNECTED);
    });
});

// =============================================================================
// ADR-041: SSE → Store dispatch integration
// =============================================================================

describe('SSE adapter ADR-041 store dispatches', () => {
    // Instead of testing through the full middleware stack, verify
    // that the SSE adapter wires eventBus → store.dispatch correctly
    // by spying on store.dispatch.

    it('worker.lab.state_change dispatches updateLabNodeState to labRecords store', () => {
        const adapter = new LcmSSEAdapter();
        const dispatchSpy = vi.spyOn(store, 'dispatch');
        adapter._setupStoreUpdates();

        const payload = {
            worker_id: 'w-001',
            lab_id: 'lab-123',
            element_type: 'node',
            element_id: 'node-001',
            event: 'STARTED',
        };

        eventBus.emit(LcmEventTypes.WORKER_LAB_STATE_CHANGE, payload);

        expect(dispatchSpy).toHaveBeenCalledWith('labRecords', 'updateLabNodeState', payload);
        dispatchSpy.mockRestore();
    });

    it('worker.lab.stats_updated dispatches updateLabStats to labRecords store', () => {
        const adapter = new LcmSSEAdapter();
        const dispatchSpy = vi.spyOn(store, 'dispatch');
        adapter._setupStoreUpdates();

        const payload = {
            worker_id: 'w-001',
            lab_id: 'lab-456',
            nodes: { 'node-001': { cpu: 25.0, memory: 1024000000 } },
        };

        eventBus.emit(LcmEventTypes.WORKER_LAB_STATS_UPDATED, payload);

        expect(dispatchSpy).toHaveBeenCalledWith('labRecords', 'updateLabStats', payload);
        dispatchSpy.mockRestore();
    });

    it('worker.ws.connected updates worker.ws_connected = true', () => {
        const adapter = new LcmSSEAdapter();
        const dispatchSpy = vi.spyOn(store, 'dispatch');
        adapter._setupStoreUpdates();

        const payload = { worker_id: 'ws-worker-001' };

        eventBus.emit(LcmEventTypes.WORKER_WS_CONNECTED, payload);

        expect(dispatchSpy).toHaveBeenCalledWith('workers', 'upsertWorker', { id: 'ws-worker-001', ws_connected: true });
        dispatchSpy.mockRestore();
    });

    it('worker.ws.disconnected updates worker.ws_connected = false', () => {
        const adapter = new LcmSSEAdapter();
        const dispatchSpy = vi.spyOn(store, 'dispatch');
        adapter._setupStoreUpdates();

        const payload = { worker_id: 'ws-worker-002' };

        eventBus.emit(LcmEventTypes.WORKER_WS_DISCONNECTED, payload);

        expect(dispatchSpy).toHaveBeenCalledWith('workers', 'upsertWorker', { id: 'ws-worker-002', ws_connected: false });
        dispatchSpy.mockRestore();
    });
});
