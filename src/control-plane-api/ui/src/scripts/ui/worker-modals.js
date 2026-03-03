// worker-modals.js
// Extracted modal setup & license/delete functionality

import * as workersApi from '../api/workers.js';
import * as workerTemplatesApi from '../api/worker-templates.js';
import { showToast } from './notifications.js';
import { isAdmin } from '../utils/roles.js';
import { renderLicenseRegistration, renderLicenseAuthorization, renderLicenseFeatures, renderLicenseTransport } from '../components/workerLicensePanel.js';
import { fetchWorkerDetails, removeWorker } from '../store/workerStore.js';
import * as bootstrap from 'bootstrap';

export function showLicenseModal(workerId, region, workerName = '', hasLicense = false) {
    const idEl = document.getElementById('license-worker-id');
    const regionEl = document.getElementById('license-worker-region');
    const nameEl = document.getElementById('license-worker-name');
    const reregisterCheckbox = document.getElementById('license-reregister');
    const deregisterBtn = document.getElementById('deregister-license-btn');

    if (!idEl || !regionEl) {
        showToast('License form missing', 'error');
        return;
    }

    idEl.value = workerId;
    regionEl.value = region;
    if (nameEl) nameEl.value = workerName;

    // Show/hide deregister button and reregister checkbox based on license status
    if (reregisterCheckbox) {
        reregisterCheckbox.checked = false;
        reregisterCheckbox.disabled = !hasLicense;
    }

    if (deregisterBtn) {
        deregisterBtn.style.display = hasLicense ? 'inline-block' : 'none';
    }

    const modalEl = document.getElementById('registerLicenseModal');
    if (modalEl) {
        modalEl.style.zIndex = '1060'; // Ensure it shows above worker details modal
        new bootstrap.Modal(modalEl).show();
    }
}

export async function showLicenseDetailsModal() {
    const modal = document.getElementById('workerDetailsModal');
    const workerId = modal?.dataset.workerId;
    const region = modal?.dataset.workerRegion;
    if (!workerId || !region) {
        showToast('No worker selected', 'error');
        return;
    }
    try {
        const worker = await fetchWorkerDetails(region, workerId);
        const licenseData = worker.cml_license_info;
        if (!licenseData) {
            showToast('No license information available', 'warning');
            return;
        }
        const licenseModalElement = document.getElementById('licenseDetailsModal');
        if (!licenseModalElement) {
            showToast('License modal missing', 'error');
            return;
        }
        const registrationContent = document.getElementById('license-registration-content');
        const authorizationContent = document.getElementById('license-authorization-content');
        const featuresContent = document.getElementById('license-features-content');
        const transportContent = document.getElementById('license-transport-content');
        if (!registrationContent || !authorizationContent || !featuresContent || !transportContent) {
            showToast('License modal content missing', 'error');
            return;
        }
        registrationContent.innerHTML = renderLicenseRegistration(licenseData.registration || {});
        authorizationContent.innerHTML = renderLicenseAuthorization(licenseData.authorization || {});
        featuresContent.innerHTML = renderLicenseFeatures(licenseData.features || []);
        transportContent.innerHTML = renderLicenseTransport(licenseData.transport || {}, licenseData.udi || {});
        new bootstrap.Modal(licenseModalElement).show();
    } catch (err) {
        console.error('[worker-modals] License details error:', err);
        showToast('Failed to load license details', 'error');
    }
}

export function setupDeleteWorkerModal() {
    const submitBtn = document.getElementById('submit-delete-worker-btn');
    if (!submitBtn) return;
    submitBtn.addEventListener('click', async () => {
        const workerId = document.getElementById('delete-worker-id')?.value;
        const region = document.getElementById('delete-worker-region')?.value;
        const terminateInstance = document.getElementById('delete-terminate-instance')?.checked || false;
        if (!workerId || !region) {
            showToast('Missing worker information', 'error');
            return;
        }
        try {
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Deleting...';
            await workersApi.deleteWorker(region, workerId, terminateInstance);

            if (terminateInstance) {
                showToast('Worker termination initiated. It will be removed once terminated.', 'info');
                // Do NOT remove locally - let SSE update status to shutting-down/terminated
            } else {
                showToast('Worker deleted successfully', 'success');
                removeWorker(workerId);
            }

            bootstrap.Modal.getInstance(document.getElementById('deleteWorkerModal'))?.hide();
            document.getElementById('delete-worker-form')?.reset();
        } catch (error) {
            console.error('[worker-modals] Delete error:', error);
            showToast(error.message || 'Failed to delete worker', 'error');
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="bi bi-trash"></i> Delete Worker';
        }
    });
}

export function showDeleteModal(workerId, region, name) {
    if (!isAdmin()) {
        showToast('Permission denied', 'error');
        return;
    }
    const idEl = document.getElementById('delete-worker-id');
    const regionEl = document.getElementById('delete-worker-region');
    const nameEl = document.getElementById('delete-worker-name');
    const terminateEl = document.getElementById('delete-terminate-instance');
    if (!idEl || !regionEl || !nameEl || !terminateEl) {
        showToast('Delete modal missing elements', 'error');
        return;
    }
    idEl.value = workerId;
    regionEl.value = region;
    nameEl.textContent = name;
    terminateEl.checked = false;
    new bootstrap.Modal(document.getElementById('deleteWorkerModal')).show();
}

export function setupLicenseModal() {
    const form = document.getElementById('register-license-form');
    const submitBtn = document.getElementById('submit-register-license-btn');
    const deregisterBtn = document.getElementById('deregister-license-btn');

    if (!form || !submitBtn) return;

    // Register license handler
    submitBtn.addEventListener('click', async () => {
        const workerId = document.getElementById('license-worker-id')?.value;
        const region = document.getElementById('license-worker-region')?.value;
        const workerName = document.getElementById('license-worker-name')?.value || workerId;
        const token = document.getElementById('license-token')?.value?.trim();
        const reregister = document.getElementById('license-reregister')?.checked || false;

        if (!token) {
            showToast('Please provide a license token', 'error');
            return;
        }

        try {
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Initiating...';

            // Call async API (returns 202 Accepted immediately)
            const response = await workersApi.registerLicense(region, workerId, token, reregister);

            showToast(`License registration initiated for ${workerName}. Processing in background...`, 'info', 5000);

            // Close modal and reset form
            bootstrap.Modal.getInstance(document.getElementById('registerLicenseModal'))?.hide();
            form.reset();

            // SSE events will notify of completion/failure automatically
            console.log('[license] Registration job started:', response);
        } catch (error) {
            console.error('[worker-modals] License register error:', error);
            showToast(error.message || 'Failed to initiate license registration', 'error');
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="bi bi-key"></i> Register License';
        }
    });

    // Deregister license handler
    if (deregisterBtn) {
        deregisterBtn.addEventListener('click', () => {
            const workerId = document.getElementById('license-worker-id')?.value;
            const region = document.getElementById('license-worker-region')?.value;
            const workerName = document.getElementById('license-worker-name')?.value || workerId;

            // Populate confirmation modal
            document.getElementById('deregister-confirm-worker-id').value = workerId;
            document.getElementById('deregister-confirm-region').value = region;
            document.getElementById('deregister-confirm-worker-name').textContent = workerName;

            // Hide register modal and show confirmation modal
            bootstrap.Modal.getInstance(document.getElementById('registerLicenseModal'))?.hide();
            new bootstrap.Modal(document.getElementById('deregisterLicenseConfirmModal')).show();
        });
    }

    // Confirm deregister button handler
    const confirmDeregisterBtn = document.getElementById('confirm-deregister-license-btn');
    if (confirmDeregisterBtn) {
        confirmDeregisterBtn.addEventListener('click', async () => {
            const workerId = document.getElementById('deregister-confirm-worker-id')?.value;
            const region = document.getElementById('deregister-confirm-region')?.value;
            const workerName = document.getElementById('deregister-confirm-worker-name')?.textContent;

            try {
                confirmDeregisterBtn.disabled = true;
                confirmDeregisterBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Deregistering...';

                await workersApi.deregisterLicense(region, workerId);

                showToast(`License deregistered successfully from ${workerName}`, 'success');

                bootstrap.Modal.getInstance(document.getElementById('deregisterLicenseConfirmModal'))?.hide();
                form.reset();

                // Refresh worker list to show updated license status
                setTimeout(() => window.workersApp.refreshWorkers?.(), 1000);
            } catch (error) {
                console.error('[worker-modals] License deregister error:', error);
                showToast(error.message || 'Failed to deregister license', 'error');
            } finally {
                confirmDeregisterBtn.disabled = false;
                confirmDeregisterBtn.innerHTML = '<i class="bi bi-x-circle"></i> Deregister License';
            }
        });
    }
}

export function setupCreateWorkerModal() {
    const submitBtn = document.getElementById('submit-create-worker-btn');
    const templateSelect = document.getElementById('worker-template');
    const templateHint = document.getElementById('worker-template-hint');
    const modal = document.getElementById('createWorkerModal');

    if (!submitBtn) return;

    // Cache for loaded templates
    let templatesCache = null;

    // Load templates when modal is shown
    modal?.addEventListener('show.bs.modal', async () => {
        if (templateSelect) {
            templateSelect.innerHTML = '<option value="">Loading templates...</option>';
            templateSelect.disabled = true;

            try {
                // Use cache if available, otherwise fetch from API
                const templates = templatesCache || (await workerTemplatesApi.listWorkerTemplates(true));
                templatesCache = templates;

                if (templates && templates.length > 0) {
                    templateSelect.innerHTML =
                        '<option value="">Select Template</option>' +
                        templates.map(t => `<option value="${t.id}" data-instance-type="${t.instance_type}" data-ami="${t.ami_id || ''}" data-region="${t.aws_region || ''}">${t.name} (${t.instance_type})</option>`).join('');
                } else {
                    templateSelect.innerHTML = '<option value="">No templates available</option>';
                }
            } catch (error) {
                console.error('[worker-modals] Failed to load templates:', error);
                templateSelect.innerHTML = '<option value="">Failed to load templates</option>';
                showToast('Failed to load worker templates', 'error');
            } finally {
                templateSelect.disabled = false;
            }
        }
    });

    // Show template details when selected
    templateSelect?.addEventListener('change', e => {
        const option = e.target.selectedOptions[0];
        if (option && option.value && templateHint) {
            const instanceType = option.dataset.instanceType || '';
            const ami = option.dataset.ami || 'default';
            templateHint.textContent = `Instance: ${instanceType}, AMI: ${ami}`;
        } else if (templateHint) {
            templateHint.textContent = '';
        }
    });

    submitBtn.addEventListener('click', async () => {
        const name = document.getElementById('worker-name')?.value;
        const region = document.getElementById('worker-region')?.value;
        const templateSelect = document.getElementById('worker-template');
        const templateId = templateSelect?.value;

        if (!name || !region || !templateId) {
            showToast('Please fill in all required fields', 'error');
            return;
        }

        // Resolve instance_type and ami_id from the selected template option
        const selectedOption = templateSelect.selectedOptions[0];
        const instanceType = selectedOption?.dataset.instanceType;
        const amiId = selectedOption?.dataset.ami || null;

        if (!instanceType) {
            showToast('Selected template is missing instance type information', 'error');
            return;
        }

        try {
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Creating...';
            const data = { name, instance_type: instanceType };
            if (amiId) data.ami_id = amiId;
            await workersApi.createWorker(region, data);
            showToast('Worker creation initiated', 'success');
            bootstrap.Modal.getInstance(document.getElementById('createWorkerModal'))?.hide();
            document.getElementById('create-worker-form')?.reset();
            setTimeout(() => window.workersApp.refreshWorkers?.(), 2000);
        } catch (error) {
            console.error('[worker-modals] Create worker error:', error);
            showToast(error.message || 'Failed to create worker', 'error');
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="bi bi-plus-circle"></i> Create Worker';
        }
    });
}

export function setupImportWorkerModal() {
    const submitBtn = document.getElementById('submit-import-worker-btn');
    if (!submitBtn) return;

    const byInstanceRadio = document.getElementById('import-by-instance');
    const byAmiRadio = document.getElementById('import-by-ami');
    const instanceGroup = document.getElementById('instance-id-group');
    const amiGroup = document.getElementById('ami-name-group');
    const nameGroup = document.getElementById('worker-name-group');
    const importAllCheckbox = document.getElementById('import-all-instances');

    function updateImportModeUI() {
        const byInstance = byInstanceRadio?.checked;
        if (byInstance) {
            instanceGroup && (instanceGroup.style.display = 'block');
            amiGroup && (amiGroup.style.display = 'none');
            nameGroup && (nameGroup.style.display = 'block');
        } else {
            instanceGroup && (instanceGroup.style.display = 'none');
            amiGroup && (amiGroup.style.display = 'block');
            if (importAllCheckbox?.checked) {
                nameGroup && (nameGroup.style.display = 'none');
            } else {
                nameGroup && (nameGroup.style.display = 'block');
            }
        }
    }

    byInstanceRadio?.addEventListener('change', updateImportModeUI);
    byAmiRadio?.addEventListener('change', updateImportModeUI);
    importAllCheckbox?.addEventListener('change', updateImportModeUI);
    // Initial state
    updateImportModeUI();

    submitBtn.addEventListener('click', async () => {
        const region = document.getElementById('import-region')?.value; // corrected ID
        const importMethodInstance = byInstanceRadio?.checked;
        const instanceId = document.getElementById('import-instance-id')?.value?.trim();
        const amiName = document.getElementById('import-ami-name')?.value?.trim();
        const name = document.getElementById('import-worker-name')?.value?.trim();
        const importAll = importAllCheckbox?.checked || false;

        // Validation
        if (!region) {
            showToast('Please select a region', 'error');
            return;
        }
        if (importMethodInstance) {
            if (!instanceId) {
                showToast('Instance ID required', 'error');
                return;
            }
        } else {
            // AMI mode
            if (!amiName) {
                showToast('AMI name pattern required', 'error');
                return;
            }
        }
        if (importMethodInstance && !name) {
            showToast('Worker name required for single instance import', 'error');
            return;
        }
        try {
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Importing...';
            const data = {};
            if (importMethodInstance) {
                data.aws_instance_id = instanceId;
                if (name) data.name = name;
            } else {
                data.ami_name = amiName;
                if (importAll) {
                    data.import_all = true;
                } else if (name) {
                    data.name = name;
                }
            }
            await workersApi.importWorker(region, data);
            showToast(importAll ? 'Bulk import initiated' : 'Worker import initiated', 'success');
            bootstrap.Modal.getInstance(document.getElementById('importWorkerModal'))?.hide();
            document.getElementById('import-worker-form')?.reset();
            setTimeout(() => window.workersApp.refreshWorkers?.(), 2000);
        } catch (error) {
            console.error('[worker-modals] Import worker error:', error);
            showToast(error.message || 'Failed to import worker', 'error');
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="bi bi-upload"></i> Import Worker';
            updateImportModeUI(); // reset visibility after form reset
        }
    });
}

/**
 * Setup Create Worker Template modal
 * Note: Worker Templates API endpoints are not yet implemented.
 * This is a placeholder that shows a "coming soon" message.
 */
export function setupCreateWorkerTemplateModal() {
    const modal = document.getElementById('createWorkerTemplateModal');
    if (!modal) return;

    const submitBtn = document.getElementById('submitCreateWorkerTemplate');
    if (!submitBtn) return;

    submitBtn.addEventListener('click', async () => {
        // Gather form data
        const name = document.getElementById('templateName')?.value?.trim();
        const instanceType = document.getElementById('templateInstanceType')?.value;
        const description = document.getElementById('templateDescription')?.value?.trim();

        // Capacity
        const cpuCores = parseInt(document.getElementById('templateCpuCores')?.value) || 4;
        const memoryGb = parseInt(document.getElementById('templateMemoryGb')?.value) || 8;
        const storageGb = parseInt(document.getElementById('templateStorageGb')?.value) || 100;
        const maxNodes = parseInt(document.getElementById('templateMaxNodes')?.value) || 50;
        const maxLabs = parseInt(document.getElementById('templateMaxLabs')?.value) || 5;

        // Configuration
        const amiPattern = document.getElementById('templateAmiPattern')?.value?.trim() || 'CML-*';
        const costPerHour = parseFloat(document.getElementById('templateCostPerHour')?.value) || 0.0;
        const enabled = document.getElementById('templateEnabled')?.checked ?? true;

        // Validation
        if (!name || !instanceType || !description) {
            showToast('Please fill in all required fields (Name, Instance Type, Description)', 'error');
            return;
        }

        // TODO: Implement API call when worker templates controller is available
        // For now, show a "coming soon" message
        showToast('Worker Template API is not yet implemented. Template data collected but not saved.', 'warning');

        console.log('[worker-modals] Template data collected:', {
            name,
            instance_type: instanceType,
            description,
            capacity: {
                cpu_cores: cpuCores,
                memory_gb: memoryGb,
                storage_gb: storageGb,
                max_nodes: maxNodes,
                max_labs: maxLabs,
            },
            ami_name_pattern: amiPattern,
            cost_per_hour_usd: costPerHour,
            enabled,
        });

        // Close modal
        bootstrap.Modal.getInstance(modal)?.hide();
        document.getElementById('createWorkerTemplateForm')?.reset();
    });

    // Reset form when modal is hidden
    modal.addEventListener('hidden.bs.modal', () => {
        document.getElementById('createWorkerTemplateForm')?.reset();
    });

    console.log('[worker-modals] Create Worker Template modal setup complete');
}
