/**
 * lablet-modals.js
 * Modal setup and handlers for Lablet Session and Definition modals
 */

import * as labletSessionsApi from '../api/lablet-sessions.js';
import * as labletDefinitionsApi from '../api/lablet-definitions.js';
import { previewPlacement } from '../api/scheduler.js';
import { showToast } from './notifications.js';
import { eventBus, EventTypes } from '../core/EventBus.js';
import { showPlacementPreviewModal } from '../components/PlacementPreviewModal.js';
import { store } from '../app/store.js';
import * as bootstrap from 'bootstrap';

// =========================================================================
// Port Definition Helpers
// =========================================================================

/**
 * Create a new port definition row element.
 * @param {Object} [defaults] - Optional defaults {name, protocol, port}
 * @returns {HTMLElement} Port row div
 */
function createPortDefinitionRow(defaults = {}) {
    const row = document.createElement('div');
    row.className = 'port-definition-row d-flex gap-2 align-items-center mb-2';
    row.innerHTML = `
        <input type="text" class="form-control form-control-sm"
               placeholder="Name (e.g., ssh)" style="width: 120px;"
               data-port-field="name" value="${defaults.name || ''}" required>
        <select class="form-select form-select-sm" style="width: 90px;"
                data-port-field="protocol">
            <option value="tcp" ${(defaults.protocol || 'tcp') === 'tcp' ? 'selected' : ''}>TCP</option>
            <option value="udp" ${defaults.protocol === 'udp' ? 'selected' : ''}>UDP</option>
        </select>
        <input type="number" class="form-control form-control-sm"
               placeholder="Port" min="1" max="65535" style="width: 100px;"
               data-port-field="port" value="${defaults.port || ''}" required>
        <button type="button" class="btn btn-sm btn-outline-danger"
                data-port-action="remove" title="Remove port">
            <i class="bi bi-x-lg"></i>
        </button>
    `;

    // Wire remove button
    row.querySelector('[data-port-action="remove"]').addEventListener('click', () => row.remove());

    return row;
}

/**
 * Collect port definitions from the container.
 * @returns {Array<{name: string, protocol: string, port: number}>}
 */
function collectPortDefinitions() {
    const container = document.getElementById('portDefinitionsContainer');
    if (!container) return [];

    const ports = [];
    container.querySelectorAll('.port-definition-row').forEach(row => {
        const name = row.querySelector('[data-port-field="name"]')?.value?.trim();
        const protocol = row.querySelector('[data-port-field="protocol"]')?.value || 'tcp';
        const port = parseInt(row.querySelector('[data-port-field="port"]')?.value);

        if (name && port && port >= 1 && port <= 65535) {
            ports.push({ name, protocol, port });
        }
    });

    return ports;
}

/**
 * Populate port definitions container with existing ports (for edit mode).
 * @param {Array<{name: string, protocol: string, port: number}>} ports
 */
export function populatePortDefinitions(ports) {
    const container = document.getElementById('portDefinitionsContainer');
    if (!container) return;

    container.innerHTML = '';
    (ports || []).forEach(p => {
        container.appendChild(createPortDefinitionRow(p));
    });
}

/**
 * Validate port definitions. Returns error message or null.
 * @returns {string|null}
 */
function validatePortDefinitions() {
    const ports = collectPortDefinitions();
    const names = new Set();
    const portNums = new Set();

    for (const p of ports) {
        if (!p.name) return 'Port name is required';
        if (!/^[a-z0-9_-]+$/i.test(p.name)) return `Invalid port name "${p.name}" — use letters, numbers, hyphens, underscores`;
        if (p.port < 1 || p.port > 65535) return `Port number ${p.port} out of range (1–65535)`;
        if (names.has(p.name.toLowerCase())) return `Duplicate port name "${p.name}"`;
        if (portNums.has(`${p.protocol}:${p.port}`)) return `Duplicate port ${p.protocol}:${p.port}`;

        names.add(p.name.toLowerCase());
        portNums.add(`${p.protocol}:${p.port}`);
    }

    return null;
}

/**
 * Setup Create Lablet Session modal
 * Uses a <select> dropdown for definition selection (populated by LabletsPage)
 */
export function setupCreateLabletSessionModal() {
    const modal = document.getElementById('createLabletSessionModal');
    if (!modal) return;

    const submitBtn = document.getElementById('submitCreateLabletSession');
    if (!submitBtn) return;

    // Populate definition dropdown and set defaults when modal opens
    modal.addEventListener('show.bs.modal', async () => {
        const definitionSelect = document.getElementById('instanceDefinitionId');
        const startInput = document.getElementById('instanceTimeslotStart');

        // Set default start time to now (rounded to next 5 min)
        if (startInput && !startInput.value) {
            const now = new Date();
            now.setMinutes(Math.ceil(now.getMinutes() / 5) * 5, 0, 0);
            const localISO = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
            startInput.value = localISO;
        }

        // Populate definition dropdown if empty
        if (definitionSelect && definitionSelect.options.length <= 1) {
            definitionSelect.innerHTML = '<option value="">Loading definitions...</option>';
            definitionSelect.disabled = true;
            try {
                const { listLabletDefinitions } = await import('../api/lablet-definitions.js');
                const definitions = await listLabletDefinitions({ status: 'active' });
                if (definitions && definitions.length > 0) {
                    definitionSelect.innerHTML = '<option value="">Select Definition</option>' + definitions.map(d => `<option value="${d.id}">${d.name} v${d.version} (${d.node_count} nodes)</option>`).join('');
                } else {
                    definitionSelect.innerHTML = '<option value="">No definitions available</option>';
                }
            } catch (error) {
                console.error('[lablet-modals] Failed to load definitions:', error);
                definitionSelect.innerHTML = '<option value="">Failed to load definitions</option>';
            } finally {
                definitionSelect.disabled = false;
            }
        }
    });

    submitBtn.addEventListener('click', async () => {
        const definitionId = document.getElementById('instanceDefinitionId')?.value;
        const timeslotStart = document.getElementById('instanceTimeslotStart')?.value;
        const durationMin = parseInt(document.getElementById('instanceDuration')?.value) || 0;
        const reservationId = document.getElementById('instanceReservationId')?.value || null;
        const region = document.getElementById('instanceRegion')?.value || null;

        // Validate
        if (!definitionId) {
            showToast('Please select a Lablet Definition', 'error');
            return;
        }
        if (!timeslotStart) {
            showToast('Please specify a start time', 'error');
            return;
        }
        if (durationMin < 5 || durationMin > 480) {
            showToast('Duration must be between 5 and 480 minutes', 'error');
            return;
        }

        // Compute end time from start + duration
        const startDate = new Date(timeslotStart);
        const endDate = new Date(startDate.getTime() + durationMin * 60 * 1000);

        try {
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Creating...';

            const instanceData = {
                definition_id: definitionId,
                timeslot_start: startDate.toISOString(),
                timeslot_end: endDate.toISOString(),
            };
            if (reservationId) instanceData.reservation_id = reservationId;
            if (region) instanceData.region = region;

            const result = await labletSessionsApi.createLabletSession(instanceData);

            // Immediately populate the store with the full session DTO from the
            // HTTP 201 response so the table row appears without waiting for SSE.
            // SSE events will then progressively update status fields.
            if (result && result.id) {
                store.dispatch('sessions', 'upsertSession', result);
            }

            showToast('Lablet session created successfully', 'success');

            // Notify pages (carries full DTO for any consumers that need it)
            eventBus.emit(EventTypes.UI_SESSION_CREATED, result || instanceData);

            bootstrap.Modal.getInstance(modal)?.hide();
            document.getElementById('createLabletSessionForm')?.reset();
        } catch (error) {
            console.error('[lablet-modals] Create session error:', error);
            showToast(error.message || 'Failed to create lablet session', 'error');
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="bi bi-plus-circle"></i> Create Session';
        }
    });

    // Dry Run button for predictive scheduling preview (AD-SCHED-002)
    const dryRunBtn = document.getElementById('dryRunCreateLabletSession');
    if (dryRunBtn) {
        dryRunBtn.addEventListener('click', async () => {
            const definitionId = document.getElementById('instanceDefinitionId')?.value;
            const timeslotStart = document.getElementById('instanceTimeslotStart')?.value;
            const durationMin = parseInt(document.getElementById('instanceDuration')?.value) || 0;

            if (!definitionId) {
                showToast('Please select a Lablet Definition to preview', 'error');
                return;
            }

            // Compute timeslot if provided
            let timeslotStartIso = null;
            let timeslotEndIso = null;
            if (timeslotStart && durationMin > 0) {
                const startDate = new Date(timeslotStart);
                const endDate = new Date(startDate.getTime() + durationMin * 60 * 1000);
                timeslotStartIso = startDate.toISOString();
                timeslotEndIso = endDate.toISOString();
            }

            try {
                dryRunBtn.disabled = true;
                dryRunBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Previewing…';

                const result = await previewPlacement({
                    definition_id: definitionId,
                    timeslot_start: timeslotStartIso,
                    timeslot_end: timeslotEndIso,
                });

                // Hide the create modal temporarily and show preview
                bootstrap.Modal.getInstance(modal)?.hide();
                showPlacementPreviewModal(result, { showRunButton: true });
            } catch (error) {
                console.error('[lablet-modals] Dry run error:', error);
                showToast(`Dry run failed: ${error.message}`, 'error');
            } finally {
                dryRunBtn.disabled = false;
                dryRunBtn.innerHTML = '<i class="bi bi-cpu me-1"></i>Dry Run';
            }
        });
    }

    // Reset when modal is hidden
    modal.addEventListener('hidden.bs.modal', () => {
        document.getElementById('createLabletSessionForm')?.reset();
    });

    console.log('[lablet-modals] Create Session modal setup complete');
}

/**
 * Setup Create Lablet Definition modal (supports create + edit modes)
 * Edit mode is triggered by setting dataset.editId on the submit button
 */
export function setupCreateLabletDefinitionModal() {
    const modal = document.getElementById('createLabletDefinitionModal');
    if (!modal) return;

    const submitBtn = document.getElementById('submitCreateLabletDefinition');
    if (!submitBtn) return;

    submitBtn.addEventListener('click', async () => {
        // Gather form data
        const name = document.getElementById('defName')?.value?.trim();
        const version = document.getElementById('defVersion')?.value?.trim();
        const formQualifiedName = document.getElementById('defFormQualifiedName')?.value?.trim();

        // Respect resource toggle state (Phase 1 — ADR-030 UX)
        const resourceToggle = document.getElementById('defResourceToggle');
        const isResourceExpanded = resourceToggle?.checked ?? false;

        const cpuCores = isResourceExpanded ? parseInt(document.getElementById('defCpuCores')?.value) || 2 : 2;
        const memoryGb = isResourceExpanded ? parseInt(document.getElementById('defMemoryGb')?.value) || 4 : 4;
        const storageGb = isResourceExpanded ? parseInt(document.getElementById('defStorageGb')?.value) || 20 : 20;
        const nestedVirt = isResourceExpanded ? (document.getElementById('defNestedVirt')?.checked ?? true) : true;
        const nodeCount = isResourceExpanded ? parseInt(document.getElementById('defNodeCount')?.value) || 1 : 1;

        const maxDurationMinutes = parseInt(document.getElementById('defMaxDuration')?.value) || 60;
        const warmPoolDepth = parseInt(document.getElementById('defWarmPoolDepth')?.value) || 0;
        const bootLeadTimeRaw = document.getElementById('defBootLeadTime')?.value?.trim();
        const bootLeadTimeMinutes = bootLeadTimeRaw ? parseInt(bootLeadTimeRaw) : null;

        // Content sync fields
        const userSessionPackageName = document.getElementById('defUserSessionPackageName')?.value?.trim();
        const gradingRulesetPackageName = document.getElementById('defGradingRulesetPackageName')?.value?.trim();
        const userSessionType = document.getElementById('defUserSessionType')?.value?.trim();
        const userSessionDefaultRegion = document.getElementById('defUserSessionDefaultRegion')?.value?.trim();

        const licenseAffinity = [];
        if (document.getElementById('defLicensePersonal')?.checked) licenseAffinity.push('personal');
        if (document.getElementById('defLicenseEnterprise')?.checked) licenseAffinity.push('enterprise');
        if (document.getElementById('defLicenseEvaluation')?.checked) licenseAffinity.push('evaluation');

        if (!name || !version || !formQualifiedName) {
            showToast('Please fill in all required fields (Name, Version, Form Qualified Name)', 'error');
            return;
        }

        // Validate and collect port definitions (Phase 3 — ADR-030 UX)
        const portValidationError = validatePortDefinitions();
        if (portValidationError) {
            showToast(portValidationError, 'error');
            return;
        }
        const portDefinitions = collectPortDefinitions();

        const definitionData = {
            name,
            version,
            form_qualified_name: formQualifiedName,
            user_session_package_name: userSessionPackageName || 'SVN.zip',
            grading_ruleset_package_name: gradingRulesetPackageName || 'SVN.zip',
            user_session_type: userSessionType || 'LDS',
            user_session_default_region: userSessionDefaultRegion || null,
            cpu_cores: cpuCores,
            memory_gb: memoryGb,
            storage_gb: storageGb,
            nested_virt: nestedVirt,
            node_count: nodeCount,
            max_duration_minutes: maxDurationMinutes,
            license_affinity: licenseAffinity.length > 0 ? licenseAffinity : null,
            warm_pool_depth: warmPoolDepth,
            boot_lead_time_minutes: bootLeadTimeMinutes,
            port_definitions: portDefinitions.length > 0 ? portDefinitions : null,
        };

        const editId = submitBtn.dataset.editId;
        const isEdit = !!editId;

        try {
            submitBtn.disabled = true;
            submitBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-2"></span>${isEdit ? 'Saving...' : 'Creating...'}`;

            if (isEdit) {
                const result = await labletDefinitionsApi.updateLabletDefinition(editId, definitionData);
                showToast('Lablet definition updated successfully', 'success');
                eventBus.emit(EventTypes.LABLET_DEFINITION_UPDATED, { definition: result });
            } else {
                const result = await labletDefinitionsApi.createLabletDefinition(definitionData);
                showToast('Lablet definition created successfully', 'success');
                eventBus.emit(EventTypes.LABLET_DEFINITION_CREATED, { definition: result });
            }

            bootstrap.Modal.getInstance(modal)?.hide();
            document.getElementById('createLabletDefinitionForm')?.reset();
        } catch (error) {
            console.error(`[lablet-modals] ${isEdit ? 'Update' : 'Create'} definition error:`, error);
            showToast(error.message || `Failed to ${isEdit ? 'update' : 'create'} lablet definition`, 'error');
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = isEdit ? '<i class="bi bi-check-circle"></i> Save Changes' : '<i class="bi bi-plus-circle"></i> Create Definition';
        }
    });

    // Port definition add button (Phase 3 — ADR-030 UX)
    const addPortBtn = document.getElementById('addPortDefinition');
    const portContainer = document.getElementById('portDefinitionsContainer');
    if (addPortBtn && portContainer) {
        addPortBtn.addEventListener('click', () => {
            portContainer.appendChild(createPortDefinitionRow());
        });
    }

    // Reset form and edit mode when modal is hidden
    modal.addEventListener('hidden.bs.modal', () => {
        const titleEl = modal.querySelector('.modal-title');
        if (titleEl) titleEl.innerHTML = '<i class="bi bi-plus-circle"></i> Create Lablet Definition';
        if (submitBtn) {
            submitBtn.innerHTML = '<i class="bi bi-plus-circle"></i> Create Definition';
            delete submitBtn.dataset.editId;
        }
        document.getElementById('createLabletDefinitionForm')?.reset();

        // Reset resource toggle (Phase 1 — ADR-030 UX)
        const resourceToggle = document.getElementById('defResourceToggle');
        if (resourceToggle) resourceToggle.checked = false;
        const collapseEl = document.getElementById('resourceRequirementsCollapse');
        if (collapseEl) {
            const bsCollapse = bootstrap.Collapse.getInstance(collapseEl);
            if (bsCollapse) bsCollapse.hide();
        }
        const defaultsHint = document.getElementById('resourceDefaultsHint');
        if (defaultsHint) defaultsHint.style.display = '';

        // Clear port definitions (Phase 3 — ADR-030 UX)
        const portCont = document.getElementById('portDefinitionsContainer');
        if (portCont) portCont.innerHTML = '';
    });

    console.log('[lablet-modals] Create/Edit Definition modal setup complete');
}

/**
 * Setup Delete Lablet Session modal
 */
export function setupDeleteLabletSessionModal() {
    const submitBtn = document.getElementById('submitDeleteLabletSession');
    if (!submitBtn) return;

    submitBtn.addEventListener('click', async () => {
        const instanceId = document.getElementById('deleteSessionId')?.value;
        const reason = document.getElementById('deleteSessionReason')?.value?.trim() || null;

        if (!instanceId) {
            showToast('Missing session information', 'error');
            return;
        }

        try {
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Terminating...';

            await labletSessionsApi.terminateLabletSession(instanceId, reason);
            showToast('Lablet session terminated', 'success');

            const modal = document.getElementById('deleteLabletSessionModal');
            if (modal) bootstrap.Modal.getInstance(modal)?.hide();
        } catch (error) {
            console.error('[lablet-modals] Delete session error:', error);
            showToast(error.message || 'Failed to terminate session', 'error');
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="bi bi-trash"></i> Terminate';
        }
    });

    console.log('[lablet-modals] Delete Session modal setup complete');
}

/**
 * Show the delete session modal with pre-filled data
 * Uses getOrCreateInstance to avoid duplicate backdrops
 * @param {string} sessionId - Session ID to delete
 * @param {string} sessionName - Session name for display
 */
export function showDeleteLabletSessionModal(sessionId, sessionName = '') {
    const idEl = document.getElementById('deleteSessionId');
    const nameEl = document.getElementById('deleteSessionName');
    const reasonEl = document.getElementById('deleteSessionReason');

    if (idEl) idEl.value = sessionId;
    if (nameEl) nameEl.textContent = sessionName || sessionId;
    if (reasonEl) reasonEl.value = '';

    const modal = document.getElementById('deleteLabletSessionModal');
    if (modal) {
        bootstrap.Modal.getOrCreateInstance(modal).show();
    }
}
