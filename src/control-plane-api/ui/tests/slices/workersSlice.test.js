/**
 * Workers Slice Unit Tests — selectFleetCapacity
 *
 * Tests for the fleet capacity selector in workersSlice.
 * Pure state logic — no DOM, no API.
 */

import { describe, it, expect } from 'vitest';
import { workersSlice, selectAllWorkers, selectFleetCapacity, selectWorkerStatusSummary } from '../../src/scripts/app/slices/workersSlice.js';

// ==============================================================================
// Helpers
// ==============================================================================

const { reducers, initialState } = workersSlice;

function makeWorker(overrides = {}) {
    const id = overrides.id || `w-${Math.random().toString(36).slice(2, 8)}`;
    return {
        id,
        name: `worker-${id}`,
        status: 'running',
        aws_region: 'us-east-1',
        declared_capacity: {
            cpu_cores: 48,
            memory_gb: 188,
            storage_gb: 247,
            max_nodes: 100,
        },
        allocated_capacity: {
            cpu_cores: 5,
            memory_gb: 7,
            storage_gb: 65,
            max_nodes: 0,
        },
        ...overrides,
    };
}

function buildState(workers) {
    let state = { ...initialState, byId: {}, allIds: [] };
    workers.forEach(w => {
        state = reducers.upsertWorker(state, w);
    });
    return { workers: state };
}

// ==============================================================================
// selectFleetCapacity — status gating
// ==============================================================================

describe('selectFleetCapacity', () => {
    it('returns zero capacity when no workers exist', () => {
        const fleet = selectFleetCapacity(buildState([]));

        expect(fleet.totalWorkers).toBe(0);
        expect(fleet.runningWorkers).toBe(0);
        expect(fleet.totalCpuCores).toBe(0);
        expect(fleet.totalMemoryGb).toBe(0);
        expect(fleet.totalStorageGb).toBe(0);
        expect(fleet.totalMaxNodes).toBe(0);
    });

    it('includes capacity from running workers', () => {
        const fleet = selectFleetCapacity(buildState([makeWorker({ id: 'w1', status: 'running' })]));

        expect(fleet.totalWorkers).toBe(1);
        expect(fleet.runningWorkers).toBe(1);
        expect(fleet.totalCpuCores).toBe(48);
        expect(fleet.totalMemoryGb).toBe(188);
        expect(fleet.totalStorageGb).toBe(247);
        expect(fleet.totalMaxNodes).toBe(100);
        expect(fleet.usedCpuCores).toBe(5);
        expect(fleet.usedMemoryGb).toBe(7);
        expect(fleet.usedStorageGb).toBe(65);
    });

    it('excludes capacity from stopped workers', () => {
        const fleet = selectFleetCapacity(buildState([makeWorker({ id: 'w1', status: 'stopped' })]));

        expect(fleet.totalWorkers).toBe(1);
        expect(fleet.runningWorkers).toBe(0);
        expect(fleet.totalCpuCores).toBe(0);
        expect(fleet.totalMemoryGb).toBe(0);
        expect(fleet.totalStorageGb).toBe(0);
        expect(fleet.usedCpuCores).toBe(0);
        expect(fleet.usedMemoryGb).toBe(0);
    });

    it('excludes capacity from pending workers', () => {
        const fleet = selectFleetCapacity(buildState([makeWorker({ id: 'w1', status: 'pending' })]));

        expect(fleet.totalWorkers).toBe(1);
        expect(fleet.runningWorkers).toBe(0);
        expect(fleet.totalCpuCores).toBe(0);
    });

    it('excludes capacity from terminated workers', () => {
        const fleet = selectFleetCapacity(buildState([makeWorker({ id: 'w1', status: 'terminated' })]));

        expect(fleet.totalWorkers).toBe(1);
        expect(fleet.runningWorkers).toBe(0);
        expect(fleet.totalCpuCores).toBe(0);
    });

    it('aggregates only running workers in mixed fleet', () => {
        const fleet = selectFleetCapacity(
            buildState([
                makeWorker({
                    id: 'w1',
                    status: 'running',
                    declared_capacity: { cpu_cores: 48, memory_gb: 188, storage_gb: 247, max_nodes: 100 },
                    allocated_capacity: { cpu_cores: 5, memory_gb: 7, storage_gb: 65, max_nodes: 0 },
                }),
                makeWorker({
                    id: 'w2',
                    status: 'stopped',
                    declared_capacity: { cpu_cores: 96, memory_gb: 384, storage_gb: 500, max_nodes: 200 },
                    allocated_capacity: { cpu_cores: 10, memory_gb: 20, storage_gb: 100, max_nodes: 0 },
                }),
                makeWorker({
                    id: 'w3',
                    status: 'running',
                    declared_capacity: { cpu_cores: 24, memory_gb: 64, storage_gb: 120, max_nodes: 50 },
                    allocated_capacity: { cpu_cores: 2, memory_gb: 3, storage_gb: 30, max_nodes: 0 },
                }),
            ])
        );

        // 3 total workers, only 2 running
        expect(fleet.totalWorkers).toBe(3);
        expect(fleet.runningWorkers).toBe(2);

        // Capacity from w1 + w3 only (w2 stopped → excluded)
        expect(fleet.totalCpuCores).toBe(48 + 24);
        expect(fleet.totalMemoryGb).toBe(188 + 64);
        expect(fleet.totalStorageGb).toBe(247 + 120);
        expect(fleet.totalMaxNodes).toBe(100 + 50);
        expect(fleet.usedCpuCores).toBe(5 + 2);
        expect(fleet.usedMemoryGb).toBe(7 + 3);
        expect(fleet.usedStorageGb).toBe(65 + 30);
    });

    it('handles workers without declared_capacity', () => {
        const fleet = selectFleetCapacity(buildState([makeWorker({ id: 'w1', status: 'running', declared_capacity: null, allocated_capacity: null })]));

        expect(fleet.totalWorkers).toBe(1);
        expect(fleet.runningWorkers).toBe(1);
        expect(fleet.totalCpuCores).toBe(0);
        expect(fleet.usedCpuCores).toBe(0);
    });

    it('treats status comparison as case-insensitive', () => {
        const fleet = selectFleetCapacity(buildState([makeWorker({ id: 'w1', status: 'Running' }), makeWorker({ id: 'w2', status: 'RUNNING' })]));

        expect(fleet.runningWorkers).toBe(2);
        expect(fleet.totalCpuCores).toBe(48 * 2);
    });

    it('handles workers with undefined status', () => {
        const fleet = selectFleetCapacity(buildState([makeWorker({ id: 'w1', status: undefined })]));

        expect(fleet.totalWorkers).toBe(1);
        expect(fleet.runningWorkers).toBe(0);
        expect(fleet.totalCpuCores).toBe(0);
    });
});
