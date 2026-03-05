/**
 * Worker Templates API Client
 * Handles all API calls related to Worker Templates
 */

import { apiRequest } from './client.js';

/**
 * List all worker templates
 * @param {boolean} enabledOnly - Only return enabled templates
 * @returns {Promise<Array>}
 */
export async function listWorkerTemplates(enabledOnly = false) {
    const params = new URLSearchParams();
    if (enabledOnly) params.append('enabled_only', 'true');

    const queryString = params.toString() ? `?${params.toString()}` : '';
    const response = await apiRequest(`/api/worker-templates/${queryString}`, {
        method: 'GET',
    });
    return await response.json();
}

/**
 * Get worker template by ID
 * @param {string} templateId - Template UUID
 * @returns {Promise<Object>}
 */
export async function getWorkerTemplate(templateId) {
    const response = await apiRequest(`/api/worker-templates/${templateId}`, {
        method: 'GET',
    });
    return await response.json();
}

/**
 * Get worker template by name
 * @param {string} name - Template name (e.g., "small", "medium", "large")
 * @returns {Promise<Object>}
 */
export async function getWorkerTemplateByName(name) {
    const response = await apiRequest(`/api/worker-templates/by-name/${name}`, {
        method: 'GET',
    });
    return await response.json();
}

/**
 * Create a new worker template
 * @param {Object} templateData - Template creation data
 * @returns {Promise<Object>}
 */
export async function createWorkerTemplate(templateData) {
    const response = await apiRequest('/api/worker-templates/', {
        method: 'POST',
        body: JSON.stringify(templateData),
    });
    return await response.json();
}

/**
 * Update an existing worker template
 * @param {string} templateId - Template UUID
 * @param {Object} updateData - Fields to update
 * @returns {Promise<Object>}
 */
export async function updateWorkerTemplate(templateId, updateData) {
    const response = await apiRequest(`/api/worker-templates/${templateId}`, {
        method: 'PUT',
        body: JSON.stringify(updateData),
    });
    return await response.json();
}

/**
 * Soft-delete a worker template
 * @param {string} templateId - Template UUID
 * @returns {Promise<Object>}
 */
export async function deleteWorkerTemplate(templateId) {
    const response = await apiRequest(`/api/worker-templates/${templateId}`, {
        method: 'DELETE',
    });
    return await response.json();
}

/**
 * Enable a worker template for provisioning
 * @param {string} templateId - Template UUID
 * @returns {Promise<Object>}
 */
export async function enableWorkerTemplate(templateId) {
    const response = await apiRequest(`/api/worker-templates/${templateId}/enable`, {
        method: 'PATCH',
    });
    return await response.json();
}

/**
 * Disable a worker template
 * @param {string} templateId - Template UUID
 * @returns {Promise<Object>}
 */
export async function disableWorkerTemplate(templateId) {
    const response = await apiRequest(`/api/worker-templates/${templateId}/disable`, {
        method: 'PATCH',
    });
    return await response.json();
}
