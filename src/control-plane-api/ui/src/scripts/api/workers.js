/**
 * Workers API Client
 * Handles all API calls related to CML Workers
 */

import { apiRequest } from './client.js';

/**
 * List all CML Workers in a region
 * @param {string} region - AWS region
 * @param {string|null} status - Optional status filter
 * @param {boolean} includeTerminated - Whether to include terminated workers
 * @returns {Promise<Array>}
 */
export async function listWorkers(region = 'us-east-1', status = null, includeTerminated = false) {
    const params = new URLSearchParams();
    if (status) params.append('status', status);
    if (includeTerminated) params.append('include_terminated', 'true');

    const queryString = params.toString() ? `?${params.toString()}` : '';
    const response = await apiRequest(`/api/workers/region/${region}/workers${queryString}`, {
        method: 'GET',
    });
    return await response.json();
}

/**
 * Get worker details by ID
 * @param {string} region - AWS region
 * @param {string} workerId - Worker UUID
 * @returns {Promise<Object>}
 */
export async function getWorkerDetails(region, workerId) {
    const response = await apiRequest(`/api/workers/region/${region}/workers/${workerId}`, {
        method: 'GET',
    });
    return await response.json();
}

/**
 * Create a new CML Worker
 * @param {string} region - AWS region
 * @param {Object} workerData - Worker creation data
 * @returns {Promise<Object>}
 */
export async function createWorker(region, workerData) {
    const response = await apiRequest(`/api/workers/region/${region}/workers`, {
        method: 'POST',
        body: JSON.stringify(workerData),
    });
    return await response.json();
}

/**
 * Import an existing EC2 instance as a CML Worker
 * @param {string} region - AWS region
 * @param {Object} importData - Import parameters
 * @returns {Promise<Object>}
 */
export async function importWorker(region, importData) {
    const response = await apiRequest(`/api/workers/region/${region}/workers/import`, {
        method: 'POST',
        body: JSON.stringify(importData),
    });
    return await response.json();
}

/**
 * Start a CML Worker
 * @param {string} region - AWS region
 * @param {string} workerId - Worker UUID
 * @returns {Promise<Object>}
 */
export async function startWorker(region, workerId) {
    const response = await apiRequest(`/api/workers/region/${region}/workers/${workerId}/start`, {
        method: 'POST',
    });
    return await response.json();
}

/**
 * Stop a CML Worker
 * @param {string} region - AWS region
 * @param {string} workerId - Worker UUID
 * @returns {Promise<Object>}
 */
export async function stopWorker(region, workerId) {
    const response = await apiRequest(`/api/workers/region/${region}/workers/${workerId}/stop`, {
        method: 'POST',
    });
    return await response.json();
}

/**
 * Delete a CML Worker from the database
 * @param {string} region - AWS region
 * @param {string} workerId - Worker UUID
 * @param {boolean} terminateInstance - Whether to also terminate the EC2 instance
 * @returns {Promise<Object>}
 */
export async function deleteWorker(region, workerId, terminateInstance = false) {
    const response = await apiRequest(`/api/workers/region/${region}/workers/${workerId}`, {
        method: 'DELETE',
        body: JSON.stringify({ terminate_instance: terminateInstance }),
    });
    // DELETE may return 204 No Content
    if (response.status === 204) return {};
    return await response.json();
}

/**
 * Register CML license for a worker (async operation)
 * @param {string} region - AWS region
 * @param {string} workerId - Worker UUID
 * @param {string} licenseToken - CML license token
 * @param {boolean} reregister - Force re-registration if already licensed
 * @returns {Promise<Object>} Returns 202 Accepted with job details
 */
export async function registerLicense(region, workerId, licenseToken, reregister = false) {
    const response = await apiRequest(`/api/workers/region/${region}/workers/${workerId}/license`, {
        method: 'POST',
        body: JSON.stringify({
            license_token: licenseToken,
            reregister: reregister,
        }),
    });
    return await response.json();
}

/**
 * Deregister CML license from a worker (sync operation, 10-60s)
 * @param {string} region - AWS region
 * @param {string} workerId - Worker UUID
 * @returns {Promise<Object>}
 */
export async function deregisterLicense(region, workerId) {
    const response = await apiRequest(`/api/workers/region/${region}/workers/${workerId}/license`, {
        method: 'DELETE',
    });
    return await response.json();
}

/**
 * Update worker tags
 * @param {string} region - AWS region
 * @param {string} workerId - Worker UUID
 * @param {Object} tags - Tags to update
 * @returns {Promise<Object>}
 */
export async function updateWorkerTags(region, workerId, tags) {
    // Controller currently exposes POST for tags update
    const response = await apiRequest(`/api/workers/region/${region}/workers/${workerId}/tags`, {
        method: 'POST',
        body: JSON.stringify({ tags }),
    });
    return await response.json();
}

/**
 * Get worker resources utilization
 * @param {string} region - AWS region
 * @param {string} workerId - Worker UUID
 * @param {string} startTime - Relative start time: '30s', '1m', '5m', or '10m'
 * @returns {Promise<Object>}
 */
export async function getWorkerResources(region, workerId, startTime = '5m') {
    const response = await apiRequest(`/api/workers/region/${region}/workers/${workerId}/resources?start_time=${startTime}`, {
        method: 'GET',
    });
    return await response.json();
}

/**
 * Lightweight fetch of a single worker (wrapper for clarity in UI layer)
 */
export async function getWorker(region, workerId) {
    const response = await apiRequest(`/api/workers/region/${region}/workers/${workerId}`, { method: 'GET' });
    return await response.json();
}

/**
 * Enable detailed CloudWatch monitoring on worker instance
 * @param {string} region - AWS region
 * @param {string} workerId - Worker UUID
 * @returns {Promise<Object>}
 */
export async function enableDetailedMonitoring(region, workerId) {
    const response = await apiRequest(`/api/workers/region/${region}/workers/${workerId}/monitoring`, {
        method: 'POST',
    });
    return await response.json();
}

/**
 * Request an on-demand metrics/data refresh for a worker.
 * Schedules background job; SSE events will deliver updated metrics.
 * @param {string} region - AWS region
 * @param {string} workerId - Worker UUID
 * @returns {Promise<Object>} { scheduled, reason?, eta_seconds?, retry_after_seconds? }
 */
export async function requestWorkerRefresh(region, workerId) {
    const response = await apiRequest(`/api/workers/region/${region}/workers/${workerId}/refresh`, {
        method: 'POST',
    });
    return await response.json();
}

/**
 * Trigger targeted lab discovery for a worker (ADR-041 Phase 2).
 * Signals lablet-controller to immediately scan this worker's labs.
 * Discovery is idempotent — safe to call multiple times.
 * @param {string} region - AWS region
 * @param {string} workerId - Worker UUID
 * @returns {Promise<Object>} { worker_id, lab_ids, source, triggered_at }
 */
export async function triggerLabDiscovery(region, workerId) {
    const response = await apiRequest(`/api/workers/region/${region}/workers/${workerId}/discover-labs`, {
        method: 'POST',
    });
    return await response.json();
}

/**
 * Legacy refresh alias used by pre-refactor UI code (calls requestWorkerRefresh).
 * Some older bundles called refreshWorker(workerId, region) with reversed argument order.
 * This function normalizes argument order and provides backward compatibility.
 * @param {string} region - AWS region (or workerId if legacy reversed order)
 * @param {string} workerId - Worker UUID (or region if legacy reversed order)
 * @returns {Promise<Object>} Same shape as requestWorkerRefresh
 */
export async function refreshWorker(region, workerId) {
    // Detect reversed arguments (UUID first, region second expected by legacy code)
    if (region && workerId && /^[0-9a-fA-F-]{36}$/.test(region) && /[a-z]{2}-[a-z]+-\d/.test(workerId)) {
        const tmp = region;
        region = workerId;
        workerId = tmp;
    }
    return await requestWorkerRefresh(region, workerId);
}

/**
 * Get labs for a specific worker
 * @param {string} region - AWS region
 * @param {string} workerId - Worker ID
 * @returns {Promise<Array>} Array of lab objects
 */
export async function getWorkerLabs(region, workerId) {
    const response = await apiRequest(`/api/labs/region/${region}/workers/${workerId}/labs`, {
        method: 'GET',
    });
    return await response.json();
}

/**
 * Start a lab on a worker
 * @param {string} region - AWS region
 * @param {string} workerId - Worker UUID
 * @param {string} labId - Lab ID
 * @returns {Promise<Object>}
 */
export async function startLab(region, workerId, labId) {
    const response = await apiRequest(`/api/labs/region/${region}/workers/${workerId}/labs/${labId}/start`, {
        method: 'POST',
    });
    return await response.json();
}

/**
 * Stop a lab on a worker
 * @param {string} region - AWS region
 * @param {string} workerId - Worker UUID
 * @param {string} labId - Lab ID
 * @returns {Promise<Object>}
 */
export async function stopLab(region, workerId, labId) {
    const response = await apiRequest(`/api/labs/region/${region}/workers/${workerId}/labs/${labId}/stop`, {
        method: 'POST',
    });
    return await response.json();
}

/**
 * Wipe a lab on a worker (factory reset)
 * @param {string} region - AWS region
 * @param {string} workerId - Worker UUID
 * @param {string} labId - Lab ID
 * @returns {Promise<Object>}
 */
export async function wipeLab(region, workerId, labId) {
    const response = await apiRequest(`/api/labs/region/${region}/workers/${workerId}/labs/${labId}/wipe`, {
        method: 'POST',
    });
    return await response.json();
}

/**
 * Delete a lab from a worker
 * @param {string} region - AWS region
 * @param {string} workerId - Worker UUID
 * @param {string} labId - Lab ID
 * @returns {Promise<Object>}
 */
export async function deleteLab(region, workerId, labId) {
    const response = await apiRequest(`/api/labs/region/${region}/workers/${workerId}/labs/${labId}/delete`, {
        method: 'POST',
    });
    return await response.json();
}

/**
 * Download a lab's topology as YAML
 * @param {string} region - AWS region
 * @param {string} workerId - Worker UUID
 * @param {string} labId - Lab ID
 * @returns {Promise<string>} YAML content
 */
export async function downloadLab(region, workerId, labId) {
    const response = await apiRequest(`/api/labs/region/${region}/workers/${workerId}/labs/${labId}/download`, {
        method: 'GET',
    });
    return await response.text();
}

/**
 * Import a lab from YAML file
 * @param {string} region - AWS region
 * @param {string} workerId - Worker UUID
 * @param {File} file - YAML file to upload
 * @returns {Promise<Object>} Import result with lab_id
 */
export async function importLab(region, workerId, file) {
    const formData = new FormData();
    formData.append('file', file);

    const response = await apiRequest(`/api/labs/region/${region}/workers/${workerId}/labs/import`, {
        method: 'POST',
        body: formData,
    });
    return await response.json();
}

/**
 * Refresh labs data from CML API for a specific worker
 * @param {string} region - AWS region
 * @param {string} workerId - Worker UUID
 * @returns {Promise<Object>} Summary with synced/created/updated counts
 */
export async function refreshWorkerLabs(region, workerId) {
    const response = await apiRequest(`/api/labs/region/${region}/workers/${workerId}/labs/refresh`, {
        method: 'POST',
    });
    return await response.json();
}

/**
 * Enable idle detection for a worker
 * @param {string} region - AWS region
 * @param {string} workerId - Worker UUID
 * @returns {Promise<Object>}
 */
export async function enableIdleDetection(region, workerId) {
    const response = await apiRequest(`/api/workers/region/${region}/workers/${workerId}/idle-detection/enable`, {
        method: 'POST',
    });
    return await response.json();
}

/**
 * Disable idle detection for a worker
 * @param {string} region - AWS region
 * @param {string} workerId - Worker UUID
 * @returns {Promise<Object>}
 */
export async function disableIdleDetection(region, workerId) {
    const response = await apiRequest(`/api/workers/region/${region}/workers/${workerId}/idle-detection/disable`, {
        method: 'POST',
    });
    return await response.json();
}
