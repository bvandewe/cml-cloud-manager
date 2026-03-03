/**
 * Modal Utilities
 * Handles modal dialogs and toast notifications
 */

import * as bootstrap from 'bootstrap';

/**
 * Show alert modal
 * @param {string} title - Modal title
 * @param {string} message - Alert message
 * @param {string} type - Alert type ('error', 'warning', 'info', 'success')
 */
export function showAlert(title, message, type = 'error') {
    const modal = document.getElementById('alertModal');
    const titleElement = document.getElementById('alert-modal-title');
    const messageElement = document.getElementById('alert-modal-message');
    const iconElement = document.getElementById('alert-modal-icon');

    titleElement.textContent = title;
    messageElement.textContent = message;

    // Update icon based on type
    const iconMap = {
        error: 'bi-x-circle text-danger',
        warning: 'bi-exclamation-triangle text-warning',
        info: 'bi-info-circle text-info',
        success: 'bi-check-circle text-success',
    };

    iconElement.className = `bi ${iconMap[type] || iconMap.error} me-2`;

    const bsModal = new bootstrap.Modal(modal);
    bsModal.show();
}

/**
 * Show confirmation modal
 * @param {string} title - Modal title
 * @param {string} message - Confirmation message
 * @param {Function} onConfirm - Callback function when confirmed
 */
export function showConfirm(title, message, onConfirm, options = {}) {
    // options: { actionLabel, actionClass, iconClass, detailsHtml, dismissOnAction }
    const { actionLabel = 'Confirm', actionClass = 'btn-danger', iconClass = 'bi bi-exclamation-triangle text-warning me-2', detailsHtml = '', dismissOnAction = true } = options;

    const modal = document.getElementById('confirmModal');
    if (!modal) {
        console.error('confirmModal element not found in DOM');
        return;
    }
    const titleElement = document.getElementById('confirm-modal-title');
    const messageElement = document.getElementById('confirm-modal-message');
    const confirmButton = document.getElementById('confirm-modal-action');
    const iconWrapper = titleElement.previousElementSibling?.querySelector('i') || modal.querySelector('.modal-title i');

    titleElement.textContent = title;
    messageElement.innerHTML = `${message}${detailsHtml ? `<div class="text-muted mt-2">${detailsHtml}</div>` : ''}`;
    if (iconWrapper) {
        iconWrapper.className = iconClass;
    }

    // Adjust button appearance
    confirmButton.textContent = actionLabel;
    confirmButton.className = `btn ${actionClass}`;

    // Use onclick to replace previous handler (cleaner than cloneNode)
    confirmButton.onclick = async () => {
        if (dismissOnAction) {
            // Try to get existing instance
            const bsModalInstance = bootstrap.Modal.getInstance(modal);
            if (bsModalInstance) {
                bsModalInstance.hide();
            } else {
                // Fallback if instance lost
                const temp = new bootstrap.Modal(modal);
                temp.hide();
            }
        }
        try {
            console.log('[modals] Confirm button clicked, executing callback');
            await onConfirm();
        } catch (err) {
            console.error('Confirmation action error:', err);
        }
    };

    // Show modal (reuse instance if exists)
    let bsModal = bootstrap.Modal.getInstance(modal);
    if (!bsModal) {
        bsModal = new bootstrap.Modal(modal);
    }
    bsModal.show();
}

/**
 * Promise-based confirmation modal (drop-in replacement for native confirm()).
 *
 * Returns a Promise that resolves to `true` when the user clicks the action
 * button, or `false` when they dismiss/cancel the modal.
 *
 * @param {string} title - Modal title
 * @param {string} message - Confirmation message
 * @param {object} [options] - Same options as showConfirm (actionLabel, actionClass, iconClass, detailsHtml)
 * @returns {Promise<boolean>}
 */
export function showConfirmAsync(title, message, options = {}) {
    return new Promise(resolve => {
        let settled = false;

        const settle = value => {
            if (!settled) {
                settled = true;
                resolve(value);
            }
        };

        showConfirm(title, message, () => settle(true), { ...options, dismissOnAction: true });

        // Resolve false when the modal is hidden without confirming
        const modal = document.getElementById('confirmModal');
        if (modal) {
            modal.addEventListener('hidden.bs.modal', () => settle(false), { once: true });
        } else {
            // confirmModal element missing — fall back to native confirm
            settle(window.confirm(message));
        }
    });
}

/**
 * Show success toast message
 * @param {string} message - Message to display
 */
export function showSuccessToast(message = 'Task updated successfully!') {
    const toastElement = document.getElementById('success-toast');
    const messageElement = document.getElementById('toast-message');
    messageElement.textContent = message;

    const toast = new bootstrap.Toast(toastElement);
    toast.show();
}
