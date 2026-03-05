/**
 * Basic test file to verify test infrastructure works
 */

import { describe, it, expect } from 'vitest';
import { EventTypes } from '../src/core/index.js';

describe('Package Structure', () => {
    describe('Core Module', () => {
        it('should export EventTypes', () => {
            expect(EventTypes).toBeDefined();
            expect(typeof EventTypes).toBe('object');
        });

        it('should have SSE event types', () => {
            expect(EventTypes.SSE_CONNECTED).toBe('sse:connected');
            expect(EventTypes.SSE_DISCONNECTED).toBe('sse:disconnected');
            expect(EventTypes.SSE_ERROR).toBe('sse:error');
            expect(EventTypes.SSE_MESSAGE).toBe('sse:message');
        });

        it('should have state event types', () => {
            expect(EventTypes.STATE_CHANGED).toBe('state:changed');
            expect(EventTypes.STATE_INITIALIZED).toBe('state:initialized');
        });

        it('should have auth event types', () => {
            expect(EventTypes.AUTH_LOGIN).toBe('auth:login');
            expect(EventTypes.AUTH_LOGOUT).toBe('auth:logout');
            expect(EventTypes.AUTH_SESSION_EXPIRED).toBe('auth:session:expired');
        });
    });
});
