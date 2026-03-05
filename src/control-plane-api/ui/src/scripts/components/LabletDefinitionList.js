/**
 * LabletDefinitionList Component
 *
 * Container component that manages a list of LabletDefinitionCard components.
 * Handles filtering, pagination, and real-time updates.
 *
 * Usage:
 *   <lablet-definition-list filter-status="active"></lablet-definition-list>
 */

import { BaseComponent } from '../core/BaseComponent.js';
import { EventTypes } from '../core/EventBus.js';
import { listLabletDefinitions, getDefinitionStatistics } from '../api/lablet-definitions.js';
import { escapeHtml } from './escape.js';
import './LabletDefinitionCard.js';

export class LabletDefinitionList extends BaseComponent {
    static get observedAttributes() {
        return ['filter-status', 'filter-name', 'compact', 'limit', 'include-deprecated'];
    }

    constructor() {
        super();
        this._state = {
            definitions: [],
            loading: true,
            error: null,
            filters: {},
            stats: null,
        };
    }

    onAttributeChange(name, oldValue, newValue) {
        // Update filters when attributes change
        this.loadDefinitions();
    }

    async onMount() {
        // Initial load
        await this.loadDefinitions();

        // Subscribe to definition events
        this.subscribe(EventTypes.LABLET_DEFINITION_CREATED, data => {
            this.addDefinition(data);
        });

        this.subscribe(EventTypes.LABLET_DEFINITION_DELETED, data => {
            this.removeDefinition(data.definition_id);
        });

        this.subscribe(EventTypes.LABLET_DEFINITIONS_REFRESH_COMPLETED, () => {
            this.loadDefinitions();
        });

        // Periodic refresh (every 60 seconds for definitions)
        this._refreshInterval = setInterval(() => this.loadDefinitions(true), 60000);
    }

    onUnmount() {
        if (this._refreshInterval) {
            clearInterval(this._refreshInterval);
        }
    }

    async loadDefinitions(silent = false) {
        if (!silent) {
            this.setState({ loading: true, error: null });
        }

        try {
            const filters = this.getFilters();
            const [definitions, stats] = await Promise.all([listLabletDefinitions(filters), getDefinitionStatistics()]);

            this.setState({
                definitions: definitions,
                stats: stats,
                loading: false,
                error: null,
            });
        } catch (error) {
            console.error('Failed to load lablet definitions:', error);
            this.setState({
                loading: false,
                error: error.message,
            });
        }
    }

    getFilters() {
        return {
            status: this.getAttribute('filter-status') || null,
            name: this.getAttribute('filter-name') || null,
            include_deprecated: this.getAttribute('include-deprecated') === 'true',
            limit: parseInt(this.getAttribute('limit') || '100', 10),
        };
    }

    addDefinition(definition) {
        this.setState(prevState => ({
            definitions: [definition, ...prevState.definitions],
        }));
    }

    removeDefinition(definitionId) {
        this.setState(prevState => ({
            definitions: prevState.definitions.filter(d => d.id !== definitionId),
        }));
    }

    render() {
        const { definitions, loading, error, stats } = this._state;
        const isCompact = this.hasAttribute('compact');

        let content;

        if (loading && definitions.length === 0) {
            content = this.renderLoading();
        } else if (error) {
            content = this.renderError(error);
        } else if (definitions.length === 0) {
            content = this.renderEmpty();
        } else {
            content = this.renderDefinitions(definitions, isCompact);
        }

        this.innerHTML = `
            ${stats ? this.renderStats(stats) : ''}
            ${this.renderFilters()}
            <div class="lablet-definition-list-content">
                ${content}
            </div>
        `;

        this.setupEventHandlers();
    }

    renderStats(stats) {
        return `
            <div class="row mb-4">
                <div class="col-md-3">
                    <div class="card stats-card bg-primary text-white">
                        <div class="card-body py-2 px-3">
                            <div class="d-flex justify-content-between align-items-center">
                                <div>
                                    <small class="card-subtitle">Total Definitions</small>
                                    <h4 class="card-title mb-0">${stats.total}</h4>
                                </div>
                                <i class="bi bi-file-earmark-code fs-3 opacity-50"></i>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card stats-card bg-success text-white">
                        <div class="card-body py-2 px-3">
                            <div class="d-flex justify-content-between align-items-center">
                                <div>
                                    <small class="card-subtitle">Active</small>
                                    <h4 class="card-title mb-0">${stats.active || 0}</h4>
                                </div>
                                <i class="bi bi-check-circle fs-3 opacity-50"></i>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card stats-card bg-warning text-dark">
                        <div class="card-body py-2 px-3">
                            <div class="d-flex justify-content-between align-items-center">
                                <div>
                                    <small class="card-subtitle">Deprecated</small>
                                    <h4 class="card-title mb-0">${stats.deprecated || 0}</h4>
                                </div>
                                <i class="bi bi-exclamation-triangle fs-3 opacity-50"></i>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card stats-card bg-info text-white">
                        <div class="card-body py-2 px-3">
                            <div class="d-flex justify-content-between align-items-center">
                                <div>
                                    <small class="card-subtitle">Total Instances</small>
                                    <h4 class="card-title mb-0">${stats.totalInstances || 0}</h4>
                                </div>
                                <i class="bi bi-collection fs-3 opacity-50"></i>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    renderFilters() {
        const currentStatus = this.getAttribute('filter-status') || '';
        const currentName = this.getAttribute('filter-name') || '';

        return `
            <div class="card mb-3">
                <div class="card-body py-2">
                    <div class="row g-2 align-items-center">
                        <div class="col-auto">
                            <label class="form-label mb-0 small">Status:</label>
                        </div>
                        <div class="col-md-2">
                            <select class="form-select form-select-sm" id="definition-status-filter">
                                <option value="">All</option>
                                <option value="active" ${currentStatus === 'active' ? 'selected' : ''}>Active</option>
                                <option value="deprecated" ${currentStatus === 'deprecated' ? 'selected' : ''}>Deprecated</option>
                                <option value="archived" ${currentStatus === 'archived' ? 'selected' : ''}>Archived</option>
                            </select>
                        </div>
                        <div class="col-auto">
                            <label class="form-label mb-0 small">Name:</label>
                        </div>
                        <div class="col-md-3">
                            <input type="text" class="form-control form-control-sm" id="definition-name-filter"
                                   placeholder="Filter by name..." value="${escapeHtml(currentName)}">
                        </div>
                        <div class="col-auto">
                            <div class="form-check">
                                <input type="checkbox" class="form-check-input" id="include-deprecated-check"
                                       ${this.getAttribute('include-deprecated') === 'true' ? 'checked' : ''}>
                                <label class="form-check-label small" for="include-deprecated-check">
                                    Include Deprecated
                                </label>
                            </div>
                        </div>
                        <div class="col-auto ms-auto">
                            <button class="btn btn-sm btn-outline-secondary" id="refresh-definitions-btn">
                                <i class="bi bi-arrow-clockwise"></i> Refresh
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    renderLoading() {
        return `
            <div class="d-flex justify-content-center align-items-center py-5">
                <div class="spinner-border text-primary" role="status">
                    <span class="visually-hidden">Loading definitions...</span>
                </div>
                <span class="ms-3 text-muted">Loading lablet definitions...</span>
            </div>
        `;
    }

    renderError(error) {
        return `
            <div class="alert alert-danger d-flex align-items-center" role="alert">
                <i class="bi bi-exclamation-triangle-fill me-2"></i>
                <div>
                    <strong>Error loading definitions:</strong> ${escapeHtml(error)}
                    <button class="btn btn-sm btn-outline-danger ms-3" id="retry-load-btn">
                        <i class="bi bi-arrow-clockwise"></i> Retry
                    </button>
                </div>
            </div>
        `;
    }

    renderEmpty() {
        return `
            <div class="text-center py-5">
                <i class="bi bi-file-earmark-x text-muted" style="font-size: 3rem;"></i>
                <h5 class="text-muted mt-3">No Lablet Definitions</h5>
                <p class="text-muted">
                    No definitions match your current filters, or none have been created yet.
                </p>
            </div>
        `;
    }

    renderDefinitions(definitions, isCompact) {
        const cards = definitions
            .map(definition => {
                const dataAttr = escapeHtml(JSON.stringify(definition));
                const compact = isCompact ? 'compact' : '';
                return `<lablet-definition-card
                        definition-id="${escapeHtml(definition.id)}"
                        data='${dataAttr}'
                        ${compact}>
                    </lablet-definition-card>`;
            })
            .join('');

        return isCompact
            ? `<div class="lablet-definitions-compact">${cards}</div>`
            : `<div class="row row-cols-1 row-cols-md-2 row-cols-xl-3 g-3">${cards
                  .split('</lablet-definition-card>')
                  .filter(Boolean)
                  .map(c => `<div class="col">${c}</lablet-definition-card></div>`)
                  .join('')}</div>`;
    }

    setupEventHandlers() {
        // Status filter
        const statusFilter = this.querySelector('#definition-status-filter');
        if (statusFilter) {
            statusFilter.addEventListener('change', e => {
                this.setAttribute('filter-status', e.target.value);
                this.loadDefinitions();
            });
        }

        // Name filter
        const nameFilter = this.querySelector('#definition-name-filter');
        if (nameFilter) {
            let debounceTimer;
            nameFilter.addEventListener('input', e => {
                clearTimeout(debounceTimer);
                debounceTimer = setTimeout(() => {
                    this.setAttribute('filter-name', e.target.value);
                    this.loadDefinitions();
                }, 300);
            });
        }

        // Include deprecated checkbox
        const deprecatedCheck = this.querySelector('#include-deprecated-check');
        if (deprecatedCheck) {
            deprecatedCheck.addEventListener('change', e => {
                this.setAttribute('include-deprecated', e.target.checked ? 'true' : 'false');
                this.loadDefinitions();
            });
        }

        // Refresh button
        const refreshBtn = this.querySelector('#refresh-definitions-btn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => this.loadDefinitions());
        }

        // Retry button
        const retryBtn = this.querySelector('#retry-load-btn');
        if (retryBtn) {
            retryBtn.addEventListener('click', () => this.loadDefinitions());
        }
    }
}

// Register the custom element
customElements.define('lablet-definition-list', LabletDefinitionList);
