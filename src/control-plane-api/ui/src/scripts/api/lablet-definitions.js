/**
 * Lablet Definitions API Client
 * Handles all API calls related to Lablet Definitions (lab templates)
 */

import { apiRequest } from './client.js';

/**
 * List lablet definitions with optional filtering
 * @param {Object} filters - Filter parameters
 * @param {string} filters.name - Filter by name
 * @param {string} filters.status - Filter by status
 * @param {boolean} filters.include_deprecated - Include deprecated definitions
 * @param {number} filters.skip - Pagination offset
 * @param {number} filters.limit - Pagination limit
 * @returns {Promise<Array>}
 */
export async function listLabletDefinitions(filters = {}) {
    const params = new URLSearchParams();

    if (filters.name) params.append('name', filters.name);
    if (filters.status) params.append('status', filters.status);
    if (filters.include_deprecated) params.append('include_deprecated', 'true');
    if (filters.skip) params.append('skip', filters.skip.toString());
    if (filters.limit) params.append('limit', filters.limit.toString());

    const queryString = params.toString() ? `?${params.toString()}` : '';
    const response = await apiRequest(`/api/lablet-definitions/${queryString}`, {
        method: 'GET',
    });
    return await response.json();
}

/**
 * Get lablet definition details by ID
 * @param {string} definitionId - Definition UUID
 * @returns {Promise<Object>}
 */
export async function getLabletDefinition(definitionId) {
    const response = await apiRequest(`/api/lablet-definitions/${definitionId}`, {
        method: 'GET',
    });
    return await response.json();
}

/**
 * Get lablet definition by name and version
 * @param {string} name - Definition name
 * @param {string} version - Definition version
 * @returns {Promise<Object>}
 */
export async function getLabletDefinitionByNameVersion(name, version) {
    const response = await apiRequest(`/api/lablet-definitions/by-name/${name}/version/${version}`, {
        method: 'GET',
    });
    return await response.json();
}

/**
 * Create a new lablet definition
 * @param {Object} definitionData - Definition creation data
 * @returns {Promise<Object>}
 */
export async function createLabletDefinition(definitionData) {
    const response = await apiRequest('/api/lablet-definitions/', {
        method: 'POST',
        body: JSON.stringify(definitionData),
    });
    return await response.json();
}

/**
 * Sync a lablet definition with external source
 * @param {string} definitionId - Definition UUID
 * @returns {Promise<Object>}
 */
export async function syncLabletDefinition(definitionId) {
    const response = await apiRequest(`/api/lablet-definitions/${definitionId}/sync`, {
        method: 'POST',
    });
    return await response.json();
}

/**
 * Update an existing lablet definition
 * @param {string} definitionId - Definition UUID
 * @param {Object} definitionData - Updated definition data
 * @returns {Promise<Object>}
 */
export async function updateLabletDefinition(definitionId, definitionData) {
    const response = await apiRequest(`/api/lablet-definitions/${definitionId}`, {
        method: 'PUT',
        body: JSON.stringify(definitionData),
    });
    return await response.json();
}

/**
 * Delete a lablet definition
 * @param {string} definitionId - Definition UUID
 * @returns {Promise<void>}
 */
export async function deleteLabletDefinition(definitionId) {
    await apiRequest(`/api/lablet-definitions/${definitionId}`, {
        method: 'DELETE',
    });
}

/**
 * Search lablet definitions by name (for autocomplete)
 * @param {string} query - Search query (min 2 characters)
 * @param {number} limit - Max results (default 10, max 50)
 * @param {boolean} includeDeprecated - Include deprecated definitions
 * @returns {Promise<Array>}
 */
export async function searchLabletDefinitions(query, limit = 10, includeDeprecated = false) {
    const params = new URLSearchParams();
    params.append('q', query);
    params.append('limit', limit.toString());
    if (includeDeprecated) params.append('include_deprecated', 'true');

    const response = await apiRequest(`/api/lablet-definitions/search?${params.toString()}`, {
        method: 'GET',
    });
    return await response.json();
}

/**
 * Get aggregated resource observations for a definition (ADR-030).
 * Returns max/avg/latest observed resources across sessions.
 * @param {string} definitionId - Definition UUID
 * @param {number} [limit=20] - Max sessions to aggregate
 * @returns {Promise<Object>} Aggregated observation data
 */
export async function getDefinitionResourceObservations(definitionId, limit = 20) {
    const params = new URLSearchParams();
    params.append('limit', limit.toString());
    const response = await apiRequest(`/api/lablet-definitions/${definitionId}/resource-observations?${params.toString()}`, {
        method: 'GET',
    });
    return await response.json();
}

/**
 * Get definition statistics
 * @returns {Promise<Object>}
 */
export async function getDefinitionStatistics() {
    const definitions = await listLabletDefinitions({ include_deprecated: false });

    const stats = {
        total: definitions.length,
        active: 0,
        deprecated: 0,
        archived: 0,
        totalInstances: 0,
    };

    for (const definition of definitions) {
        const status = (definition.status || 'active').toLowerCase();
        if (stats.hasOwnProperty(status)) {
            stats[status]++;
        }
        stats.totalInstances += definition.instance_count || 0;
    }

    return stats;
}
