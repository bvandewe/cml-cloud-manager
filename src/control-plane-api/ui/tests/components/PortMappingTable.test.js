/**
 * PortMappingTable Component Tests — Phase 11 (P11-24)
 *
 * Tests for the <port-mapping-table> custom element.
 * Uses jsdom environment for DOM testing.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// Mock the EventBus before importing the component
vi.mock('../../src/scripts/core/EventBus.js', () => ({
    EventTypes: {},
    LcmEventTypes: {},
    eventBus: {
        on: vi.fn(() => vi.fn()),
        off: vi.fn(),
        emit: vi.fn(),
        once: vi.fn(() => vi.fn()),
    },
    default: {
        on: vi.fn(() => vi.fn()),
        off: vi.fn(),
        emit: vi.fn(),
        once: vi.fn(() => vi.fn()),
    },
}));

vi.mock('../../src/scripts/app/eventBus.js', () => ({
    LcmEventTypes: {},
    EventTypes: {},
    eventBus: {
        on: vi.fn(() => vi.fn()),
        off: vi.fn(),
        emit: vi.fn(),
        once: vi.fn(() => vi.fn()),
    },
    default: {
        on: vi.fn(() => vi.fn()),
        off: vi.fn(),
        emit: vi.fn(),
        once: vi.fn(() => vi.fn()),
    },
}));

// Now import the component class
import { PortMappingTable } from '../../src/scripts/components/sessions/PortMappingTable.js';

// ==============================================================================
// Helpers
// ==============================================================================

function createElement() {
    const el = document.createElement('port-mapping-table');
    document.body.appendChild(el);
    return el;
}

function teardown(el) {
    el?.remove();
}

// ==============================================================================
// Tests
// ==============================================================================

describe('PortMappingTable', () => {
    let element;

    afterEach(() => {
        teardown(element);
        element = null;
    });

    describe('initial state', () => {
        it('should register as custom element', () => {
            expect(customElements.get('port-mapping-table')).toBeDefined();
        });

        it('should render empty state message', () => {
            element = createElement();
            expect(element.textContent).toContain('No port mappings available');
        });
    });

    describe('setPorts()', () => {
        it('should render a table with port rows', () => {
            element = createElement();
            element.setPorts({
                'router-1': { protocol: 'ssh', external_port: 9001, internal_port: 22, host: '10.0.0.1' },
                'switch-1': { protocol: 'http', external_port: 8080, internal_port: 80, host: '10.0.0.2' },
            });

            const rows = element.querySelectorAll('tbody tr');
            expect(rows.length).toBe(2);
            expect(element.textContent).toContain('router-1');
            expect(element.textContent).toContain('switch-1');
        });

        it('should handle array port info per node', () => {
            element = createElement();
            element.setPorts({
                'router-1': [
                    { protocol: 'ssh', external_port: 9001, internal_port: 22, host: '10.0.0.1' },
                    { protocol: 'http', external_port: 8080, internal_port: 80, host: '10.0.0.1' },
                ],
            });

            const rows = element.querySelectorAll('tbody tr');
            expect(rows.length).toBe(2);
        });

        it('should display protocol badges', () => {
            element = createElement();
            element.setPorts({
                'router-1': { protocol: 'ssh', external_port: 22, internal_port: 22 },
            });

            expect(element.textContent).toContain('SSH');
        });

        it('should render empty state for null ports', () => {
            element = createElement();
            element.setPorts(null);
            expect(element.textContent).toContain('No port mappings available');
        });

        it('should render empty state for empty object', () => {
            element = createElement();
            element.setPorts({});
            expect(element.textContent).toContain('No port mappings available');
        });

        it('should show dashes for missing port values', () => {
            element = createElement();
            element.setPorts({
                'router-1': { protocol: 'tcp' },
            });

            const html = element.innerHTML;
            expect(html).toContain('—');
        });
    });

    describe('compact mode', () => {
        it('should use compact table class', () => {
            element = createElement();
            element.setAttribute('compact', '');
            element.setPorts({
                'router-1': { protocol: 'ssh', external_port: 22, internal_port: 22 },
            });

            const table = element.querySelector('table');
            expect(table.classList.contains('table-borderless')).toBe(true);
        });

        it('should hide host and access columns in compact mode', () => {
            element = createElement();
            element.setAttribute('compact', '');
            element.setPorts({
                'router-1': { protocol: 'ssh', external_port: 22, internal_port: 22, host: '10.0.0.1' },
            });

            const headers = element.querySelectorAll('thead th');
            const headerTexts = Array.from(headers).map(h => h.textContent.trim());
            expect(headerTexts).not.toContain('Host');
            expect(headerTexts).not.toContain('Access');
        });

        it('should show host and access in non-compact mode', () => {
            element = createElement();
            // Don't set compact attribute
            element.setPorts({
                'router-1': { protocol: 'ssh', external_port: 22, internal_port: 22, host: '10.0.0.1' },
            });

            const headers = element.querySelectorAll('thead th');
            const headerTexts = Array.from(headers).map(h => h.textContent.trim());
            expect(headerTexts).toContain('Host');
            expect(headerTexts).toContain('Access');
        });
    });

    describe('access links', () => {
        it('should render SSH access command in full mode', () => {
            element = createElement();
            element.setPorts({
                'router-1': { protocol: 'SSH', external_port: 9001, internal_port: 22, host: '10.0.0.1' },
            });

            expect(element.innerHTML).toContain('ssh -p 9001 10.0.0.1');
        });

        it('should render HTTP link for HTTP protocol', () => {
            element = createElement();
            element.setPorts({
                'web-1': { protocol: 'HTTP', external_port: 8080, internal_port: 80, host: '10.0.0.2' },
            });

            const link = element.querySelector('a[target="_blank"]');
            expect(link).toBeTruthy();
            expect(link.href).toContain('http://10.0.0.2:8080');
        });

        it('should render generic host:port for other protocols', () => {
            element = createElement();
            element.setPorts({
                'device-1': { protocol: 'TCP', external_port: 5000, internal_port: 5000, host: '10.0.0.3' },
            });

            expect(element.innerHTML).toContain('10.0.0.3:5000');
        });
    });

    describe('_flattenPorts()', () => {
        it('should flatten mixed single and array ports', () => {
            element = createElement();
            element._ports = {
                'node-a': { protocol: 'ssh', external_port: 22 },
                'node-b': [
                    { protocol: 'http', external_port: 80 },
                    { protocol: 'https', external_port: 443 },
                ],
            };

            const rows = element._flattenPorts();
            expect(rows).toHaveLength(3);
            expect(rows[0].node_label).toBe('node-a');
            expect(rows[1].node_label).toBe('node-b');
            expect(rows[2].node_label).toBe('node-b');
        });
    });

    describe('XSS protection', () => {
        it('should escape HTML in node labels', () => {
            element = createElement();
            element.setPorts({
                '<script>alert(1)</script>': { protocol: 'tcp', external_port: 80, internal_port: 80 },
            });

            expect(element.innerHTML).not.toContain('<script>');
            expect(element.innerHTML).toContain('&lt;script&gt;');
        });
    });
});
