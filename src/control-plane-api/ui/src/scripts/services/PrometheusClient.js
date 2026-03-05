/**
 * LcmPrometheusClient - Prometheus Query Service
 *
 * A lightweight client for querying Prometheus API with graceful
 * error handling when Prometheus is unavailable.
 *
 * Usage:
 *   import { prometheusClient } from './services/PrometheusClient.js';
 *
 *   // Instant query
 *   const result = await prometheusClient.query('up{job="control-plane-api"}');
 *
 *   // Range query
 *   const data = await prometheusClient.queryRange(
 *     'rate(http_requests_total[5m])',
 *     { start: 'now-1h', end: 'now', step: '1m' }
 *   );
 *
 *   // Get metric value with graceful fallback
 *   const value = await prometheusClient.getMetricValue('worker_count', 0);
 *
 * @module services/PrometheusClient
 */

/**
 * Prometheus Query Result Types
 * @typedef {Object} PrometheusResult
 * @property {string} status - 'success' or 'error'
 * @property {Object} data - Query result data
 * @property {string} [error] - Error message if status is 'error'
 */

export class LcmPrometheusClient {
    /**
     * Create a Prometheus client
     * @param {Object} options - Configuration options
     * @param {string} options.baseUrl - Prometheus API base URL (default: /prometheus)
     * @param {number} options.timeout - Request timeout in ms (default: 5000)
     * @param {number} options.retries - Number of retries on failure (default: 1)
     */
    constructor(options = {}) {
        this.baseUrl = options.baseUrl || '/prometheus';
        this.timeout = options.timeout || 5000;
        this.retries = options.retries || 1;
        this._isAvailable = null; // null = unknown, true/false = cached status
        this._lastHealthCheck = 0;
        this._healthCheckInterval = 30000; // 30 seconds
    }

    // ==================== Health Check ====================

    /**
     * Check if Prometheus is available
     * @param {boolean} force - Force a fresh check (ignore cache)
     * @returns {Promise<boolean>}
     */
    async isAvailable(force = false) {
        const now = Date.now();

        // Return cached status if recent
        if (!force && this._isAvailable !== null && now - this._lastHealthCheck < this._healthCheckInterval) {
            return this._isAvailable;
        }

        try {
            const response = await this._fetch('/-/ready', { timeout: 2000 });
            this._isAvailable = response.ok;
        } catch (e) {
            this._isAvailable = false;
        }

        this._lastHealthCheck = now;
        return this._isAvailable;
    }

    // ==================== Query API ====================

    /**
     * Execute an instant query
     * @param {string} query - PromQL query
     * @param {Object} options - Query options
     * @param {string} options.time - Evaluation timestamp (default: now)
     * @returns {Promise<PrometheusResult>}
     */
    async query(query, options = {}) {
        const params = new URLSearchParams({ query });

        if (options.time) {
            params.set('time', this._parseTime(options.time));
        }

        return this._queryApi(`/api/v1/query?${params}`);
    }

    /**
     * Execute a range query
     * @param {string} query - PromQL query
     * @param {Object} options - Query options
     * @param {string} options.start - Start time (required)
     * @param {string} options.end - End time (required)
     * @param {string} options.step - Query resolution step (required)
     * @returns {Promise<PrometheusResult>}
     */
    async queryRange(query, options = {}) {
        const { start, end, step } = options;

        if (!start || !end || !step) {
            throw new Error('queryRange requires start, end, and step options');
        }

        const params = new URLSearchParams({
            query,
            start: this._parseTime(start),
            end: this._parseTime(end),
            step,
        });

        return this._queryApi(`/api/v1/query_range?${params}`);
    }

    /**
     * Get a single metric value with graceful fallback
     * @param {string} query - PromQL query that returns a single value
     * @param {*} defaultValue - Value to return if query fails
     * @returns {Promise<number|string|*>}
     */
    async getMetricValue(query, defaultValue = null) {
        try {
            const result = await this.query(query);

            if (result.status === 'success' && result.data?.result?.length > 0) {
                const value = result.data.result[0].value;
                if (value && value.length > 1) {
                    return parseFloat(value[1]);
                }
            }

            return defaultValue;
        } catch (e) {
            console.warn(`[PrometheusClient] Failed to get metric "${query}":`, e.message);
            return defaultValue;
        }
    }

    /**
     * Get multiple metrics in parallel
     * @param {Object} queries - Object with { name: query } pairs
     * @param {Object} defaults - Object with { name: defaultValue } pairs
     * @returns {Promise<Object>} - Object with { name: value } pairs
     */
    async getMetrics(queries, defaults = {}) {
        const entries = Object.entries(queries);
        const results = await Promise.all(entries.map(([name, query]) => this.getMetricValue(query, defaults[name] ?? null).then(value => [name, value])));

        return Object.fromEntries(results);
    }

    // ==================== Metadata API ====================

    /**
     * Get all metric names
     * @returns {Promise<string[]>}
     */
    async getMetricNames() {
        try {
            const result = await this._queryApi('/api/v1/label/__name__/values');
            return result.data || [];
        } catch (e) {
            console.warn('[PrometheusClient] Failed to get metric names:', e.message);
            return [];
        }
    }

    /**
     * Get label values for a label name
     * @param {string} labelName - Label name
     * @returns {Promise<string[]>}
     */
    async getLabelValues(labelName) {
        try {
            const result = await this._queryApi(`/api/v1/label/${encodeURIComponent(labelName)}/values`);
            return result.data || [];
        } catch (e) {
            console.warn(`[PrometheusClient] Failed to get label values for "${labelName}":`, e.message);
            return [];
        }
    }

    // ==================== Private Methods ====================

    async _queryApi(path) {
        // Check availability first (uses cache)
        if (!(await this.isAvailable())) {
            return {
                status: 'error',
                error: 'Prometheus is unavailable',
                data: null,
            };
        }

        try {
            const response = await this._fetch(path);

            if (!response.ok) {
                const text = await response.text();
                return {
                    status: 'error',
                    error: `HTTP ${response.status}: ${text}`,
                    data: null,
                };
            }

            return await response.json();
        } catch (e) {
            // Mark as unavailable on network error
            this._isAvailable = false;
            return {
                status: 'error',
                error: e.message,
                data: null,
            };
        }
    }

    async _fetch(path, options = {}) {
        const url = `${this.baseUrl}${path}`;
        const timeout = options.timeout || this.timeout;

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeout);

        try {
            const response = await fetch(url, {
                signal: controller.signal,
                credentials: 'include',
                headers: {
                    Accept: 'application/json',
                },
            });
            return response;
        } finally {
            clearTimeout(timeoutId);
        }
    }

    _parseTime(time) {
        if (typeof time === 'number') {
            return time.toString();
        }

        if (typeof time === 'string') {
            // Handle relative time expressions like "now-1h"
            if (time.startsWith('now')) {
                const now = Date.now() / 1000;
                const match = time.match(/now(-|\+)?(\d+)?([smhdw])?/);

                if (match) {
                    const [, operator, value, unit] = match;

                    if (!operator || !value) {
                        return now.toString();
                    }

                    const multipliers = {
                        s: 1,
                        m: 60,
                        h: 3600,
                        d: 86400,
                        w: 604800,
                    };

                    const seconds = parseInt(value) * (multipliers[unit] || 1);
                    const result = operator === '-' ? now - seconds : now + seconds;
                    return result.toString();
                }

                return now.toString();
            }

            // ISO timestamp or Unix timestamp string
            const parsed = Date.parse(time);
            if (!isNaN(parsed)) {
                return (parsed / 1000).toString();
            }
        }

        return time.toString();
    }
}

// Singleton instance
export const prometheusClient = new LcmPrometheusClient();

export default LcmPrometheusClient;
