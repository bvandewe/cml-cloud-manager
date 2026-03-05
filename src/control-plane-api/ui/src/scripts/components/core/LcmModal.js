/**
 * LcmModal - Modal Dialog Web Component
 *
 * A reusable modal dialog component that wraps Bootstrap 5 modals
 * with a cleaner API and support for confirmation dialogs.
 *
 * Usage:
 *   <lcm-modal id="my-modal" title="Confirm Action" size="md">
 *     <div slot="body">Are you sure you want to proceed?</div>
 *     <div slot="footer">
 *       <button class="btn btn-secondary" data-dismiss>Cancel</button>
 *       <button class="btn btn-primary" data-confirm>Confirm</button>
 *     </div>
 *   </lcm-modal>
 *
 * JavaScript API:
 *   const modal = document.getElementById('my-modal');
 *   modal.show();
 *   modal.hide();
 *   modal.setContent({ title: 'New Title', body: '<p>New content</p>' });
 *
 * Events:
 *   - 'modal-show': Fired before modal is shown
 *   - 'modal-shown': Fired after modal is fully shown
 *   - 'modal-hide': Fired before modal is hidden
 *   - 'modal-hidden': Fired after modal is fully hidden
 *   - 'modal-confirm': Fired when confirm button is clicked
 *   - 'modal-dismiss': Fired when dismiss button is clicked
 *
 * @module components/core/LcmModal
 */

import { BaseComponent } from '../../core/BaseComponent.js';

export class LcmModal extends BaseComponent {
    static get observedAttributes() {
        return ['title', 'size', 'centered', 'static-backdrop', 'scrollable'];
    }

    constructor() {
        super();
        this._bsModal = null;
        this._resolvePromise = null;
    }

    onMount() {
        this.render();
        this._initBootstrapModal();
        this._bindEvents();
    }

    onUnmount() {
        if (this._bsModal) {
            this._bsModal.dispose();
            this._bsModal = null;
        }
    }

    onAttributeChange(name) {
        if (['title', 'size', 'centered', 'scrollable'].includes(name)) {
            this.render();
            this._bindEvents();
        }
    }

    // ==================== Public API ====================

    /**
     * Show the modal
     * @returns {Promise} Resolves when modal is fully shown
     */
    show() {
        this.dispatchEvent(new CustomEvent('modal-show', { bubbles: true }));
        this._bsModal?.show();
        return new Promise(resolve => {
            this._showPromise = resolve;
        });
    }

    /**
     * Hide the modal
     * @returns {Promise} Resolves when modal is fully hidden
     */
    hide() {
        this.dispatchEvent(new CustomEvent('modal-hide', { bubbles: true }));
        this._bsModal?.hide();
        return new Promise(resolve => {
            this._hidePromise = resolve;
        });
    }

    /**
     * Toggle modal visibility
     */
    toggle() {
        this._bsModal?.toggle();
    }

    /**
     * Update modal content dynamically
     * @param {Object} options - { title, body, footer }
     */
    setContent({ title, body, footer }) {
        if (title !== undefined) {
            const titleEl = this.querySelector('.modal-title');
            if (titleEl) titleEl.innerHTML = title;
        }
        if (body !== undefined) {
            const bodyEl = this.querySelector('.modal-body');
            if (bodyEl) bodyEl.innerHTML = body;
        }
        if (footer !== undefined) {
            const footerEl = this.querySelector('.modal-footer');
            if (footerEl) footerEl.innerHTML = footer;
            this._bindFooterEvents();
        }
    }

    /**
     * Show as confirmation dialog
     * @param {Object} options - { title, message, confirmText, cancelText, variant }
     * @returns {Promise<boolean>} Resolves true if confirmed, false if cancelled
     */
    async confirm({ title = 'Confirm', message = 'Are you sure?', confirmText = 'Confirm', cancelText = 'Cancel', variant = 'primary' } = {}) {
        this.setContent({
            title,
            body: `<p class="mb-0">${message}</p>`,
            footer: `
                <button type="button" class="btn btn-secondary" data-dismiss>${cancelText}</button>
                <button type="button" class="btn btn-${variant}" data-confirm>${confirmText}</button>
            `,
        });

        return new Promise(resolve => {
            this._resolvePromise = resolve;
            this.show();
        });
    }

    /**
     * Show as alert dialog
     * @param {Object} options - { title, message, variant, icon }
     * @returns {Promise} Resolves when dismissed
     */
    async alert({ title = 'Alert', message, variant = 'info', icon = 'bi-info-circle' } = {}) {
        const iconColors = {
            success: 'text-success',
            danger: 'text-danger',
            warning: 'text-warning',
            info: 'text-info',
        };

        this.setContent({
            title,
            body: `
                <div class="d-flex align-items-center gap-3">
                    <i class="${icon} fs-1 ${iconColors[variant] || ''}" aria-hidden="true"></i>
                    <div>${message}</div>
                </div>
            `,
            footer: `<button type="button" class="btn btn-${variant}" data-dismiss>OK</button>`,
        });

        return new Promise(resolve => {
            this._resolvePromise = () => resolve();
            this.show();
        });
    }

    // ==================== Private Methods ====================

    _initBootstrapModal() {
        const modalEl = this.querySelector('.modal');
        if (modalEl && typeof bootstrap !== 'undefined') {
            const options = {
                backdrop: this.hasAttribute('static-backdrop') ? 'static' : true,
                keyboard: !this.hasAttribute('static-backdrop'),
            };
            this._bsModal = new bootstrap.Modal(modalEl, options);

            // Bootstrap modal events
            modalEl.addEventListener('shown.bs.modal', () => {
                this.dispatchEvent(new CustomEvent('modal-shown', { bubbles: true }));
                this._showPromise?.();
            });

            modalEl.addEventListener('hidden.bs.modal', () => {
                this.dispatchEvent(new CustomEvent('modal-hidden', { bubbles: true }));
                this._hidePromise?.();
            });
        }
    }

    _bindEvents() {
        this._bindFooterEvents();

        // Handle backdrop click for non-static modals
        const modalEl = this.querySelector('.modal');
        modalEl?.addEventListener('click', e => {
            if (e.target === modalEl && !this.hasAttribute('static-backdrop')) {
                this._handleDismiss();
            }
        });
    }

    _bindFooterEvents() {
        // Confirm button
        this.querySelectorAll('[data-confirm]').forEach(btn => {
            btn.addEventListener('click', () => this._handleConfirm());
        });

        // Dismiss button
        this.querySelectorAll('[data-dismiss]').forEach(btn => {
            btn.addEventListener('click', () => this._handleDismiss());
        });
    }

    _handleConfirm() {
        this.dispatchEvent(new CustomEvent('modal-confirm', { bubbles: true }));
        if (this._resolvePromise) {
            this._resolvePromise(true);
            this._resolvePromise = null;
        }
        this.hide();
    }

    _handleDismiss() {
        this.dispatchEvent(new CustomEvent('modal-dismiss', { bubbles: true }));
        if (this._resolvePromise) {
            this._resolvePromise(false);
            this._resolvePromise = null;
        }
        this.hide();
    }

    // ==================== Rendering ====================

    render() {
        const title = this.getAttribute('title') || 'Modal';
        const size = this.getAttribute('size') || 'md'; // sm, md, lg, xl
        const centered = this.hasAttribute('centered');
        const scrollable = this.hasAttribute('scrollable');

        // Get slotted content
        const bodySlot = this.querySelector('[slot="body"]');
        const footerSlot = this.querySelector('[slot="footer"]');

        const bodyContent = bodySlot?.innerHTML || '';
        const footerContent =
            footerSlot?.innerHTML ||
            `
            <button type="button" class="btn btn-secondary" data-dismiss>Close</button>
        `;

        const sizeClass = size !== 'md' ? `modal-${size}` : '';
        const centeredClass = centered ? 'modal-dialog-centered' : '';
        const scrollableClass = scrollable ? 'modal-dialog-scrollable' : '';

        this.innerHTML = `
            <div class="modal fade" tabindex="-1" aria-labelledby="modal-title" aria-hidden="true">
                <div class="modal-dialog ${sizeClass} ${centeredClass} ${scrollableClass}">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title" id="modal-title">${title}</h5>
                            <button type="button" class="btn-close" aria-label="Close" data-dismiss></button>
                        </div>
                        <div class="modal-body">
                            ${bodyContent}
                        </div>
                        <div class="modal-footer">
                            ${footerContent}
                        </div>
                    </div>
                </div>
            </div>
        `;
    }
}

/**
 * LcmConfirmModal - Specialized confirmation modal
 *
 * A pre-configured modal specifically for confirmation dialogs.
 * Simplifies the common use case of asking for user confirmation.
 *
 * Usage:
 *   <lcm-confirm-modal
 *     id="delete-confirm"
 *     title="Delete Worker?"
 *     message="This action cannot be undone."
 *     confirm-text="Delete"
 *     variant="danger">
 *   </lcm-confirm-modal>
 *
 * JavaScript:
 *   const confirmed = await document.getElementById('delete-confirm').show();
 *   if (confirmed) { ... }
 */
export class LcmConfirmModal extends BaseComponent {
    static get observedAttributes() {
        return ['title', 'message', 'confirm-text', 'cancel-text', 'variant', 'icon'];
    }

    constructor() {
        super();
        this._bsModal = null;
        this._resolvePromise = null;
    }

    onMount() {
        this.render();
        this._initBootstrapModal();
        this._bindEvents();
    }

    onUnmount() {
        if (this._bsModal) {
            this._bsModal.dispose();
            this._bsModal = null;
        }
    }

    /**
     * Show the confirmation modal
     * @returns {Promise<boolean>} Resolves true if confirmed, false if cancelled
     */
    show() {
        return new Promise(resolve => {
            this._resolvePromise = resolve;
            this._bsModal?.show();
        });
    }

    /**
     * Hide the modal
     */
    hide() {
        this._bsModal?.hide();
    }

    /**
     * Update the message dynamically
     */
    setMessage(message) {
        const messageEl = this.querySelector('.lcm-confirm-message');
        if (messageEl) messageEl.innerHTML = message;
    }

    _initBootstrapModal() {
        const modalEl = this.querySelector('.modal');
        if (modalEl && typeof bootstrap !== 'undefined') {
            this._bsModal = new bootstrap.Modal(modalEl, {
                backdrop: 'static',
                keyboard: false,
            });

            modalEl.addEventListener('hidden.bs.modal', () => {
                if (this._resolvePromise) {
                    this._resolvePromise(false);
                    this._resolvePromise = null;
                }
            });
        }
    }

    _bindEvents() {
        this.querySelector('[data-confirm]')?.addEventListener('click', () => {
            if (this._resolvePromise) {
                this._resolvePromise(true);
                this._resolvePromise = null;
            }
            this.hide();
        });

        this.querySelector('[data-dismiss]')?.addEventListener('click', () => {
            if (this._resolvePromise) {
                this._resolvePromise(false);
                this._resolvePromise = null;
            }
            this.hide();
        });
    }

    render() {
        const title = this.getAttribute('title') || 'Confirm';
        const message = this.getAttribute('message') || 'Are you sure?';
        const confirmText = this.getAttribute('confirm-text') || 'Confirm';
        const cancelText = this.getAttribute('cancel-text') || 'Cancel';
        const variant = this.getAttribute('variant') || 'primary';
        const icon = this.getAttribute('icon');

        const iconHtml = icon ? `<i class="${icon} fs-1 text-${variant} me-3" aria-hidden="true"></i>` : '';

        this.innerHTML = `
            <div class="modal fade" tabindex="-1" aria-hidden="true">
                <div class="modal-dialog modal-dialog-centered">
                    <div class="modal-content">
                        <div class="modal-header border-0 pb-0">
                            <h5 class="modal-title">${title}</h5>
                            <button type="button" class="btn-close" data-dismiss aria-label="Close"></button>
                        </div>
                        <div class="modal-body d-flex align-items-center">
                            ${iconHtml}
                            <p class="lcm-confirm-message mb-0">${message}</p>
                        </div>
                        <div class="modal-footer border-0 pt-0">
                            <button type="button" class="btn btn-outline-secondary" data-dismiss>${cancelText}</button>
                            <button type="button" class="btn btn-${variant}" data-confirm>${confirmText}</button>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }
}

// Register custom elements
if (!customElements.get('lcm-modal')) {
    customElements.define('lcm-modal', LcmModal);
}

if (!customElements.get('lcm-confirm-modal')) {
    customElements.define('lcm-confirm-modal', LcmConfirmModal);
}

export default LcmModal;
