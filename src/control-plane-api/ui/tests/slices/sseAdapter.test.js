import { describe, expect, it } from 'vitest';

import { LcmSSEAdapter } from '../../src/scripts/app/sse/sseAdapter.js';
import { LcmEventTypes } from '../../src/scripts/app/eventTypes.js';
import { sseEventMap } from '../../src/scripts/app/sse/eventMap.js';

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