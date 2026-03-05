/**
 * Modal - Dialog Web Component
 *
 * A reusable modal dialog component that wraps Bootstrap 5 modals
 * with a cleaner API. Supports standard dialogs, confirmations, and alerts.
 *
 * @example
 * ```html
 * <ui-modal id="my-modal" title="Confirm Action" size="md">
 *   <div slot="body">Are you sure you want to proceed?</div>
 *   <div slot="footer">
 *     <button class="btn btn-secondary" data-dismiss>Cancel</button>
 *     <button class="btn btn-primary" data-confirm>Confirm</button>
 *   </div>
 * </ui-modal>
 * ```
 *
 * JavaScript API:
 *   const modal = document.getElementById('my-modal');
 *   modal.show();
 *   modal.hide();
 *   const confirmed = await modal.confirm({ title: 'Delete?', message: 'This cannot be undone.' });
 *
 * Events:
 *   - 'modal-show': Before modal is shown
 *   - 'modal-shown': After modal is fully shown
 *   - 'modal-hide': Before modal is hidden
 *   - 'modal-hidden': After modal is fully hidden
 *   - 'modal-confirm': Confirm button clicked
 *   - 'modal-dismiss': Dismiss button clicked
 *
 * @module components
 */

import { BaseComponent } from './BaseComponent.js';

declare const bootstrap: {
    Modal: new (element: Element, options?: ModalBootstrapOptions) => BootstrapModalInstance;
};

interface ModalBootstrapOptions {
    backdrop?: boolean | 'static';
    keyboard?: boolean;
    focus?: boolean;
}

interface BootstrapModalInstance {
    show(): void;
    hide(): void;
    toggle(): void;
    dispose(): void;
}

/**
 * Modal size options
 */
export type ModalSize = 'sm' | 'md' | 'lg' | 'xl' | 'fullscreen';

/**
 * Modal content options
 */
export interface ModalContentOptions {
    title?: string;
    body?: string;
    footer?: string;
}

/**
 * Confirm dialog options
 */
export interface ConfirmOptions {
    title?: string;
    message?: string;
    confirmText?: string;
    cancelText?: string;
    variant?: string;
    icon?: string;
}

/**
 * Alert dialog options
 */
export interface AlertOptions {
    title?: string;
    message: string;
    variant?: 'info' | 'success' | 'warning' | 'danger';
    icon?: string;
    buttonText?: string;
}

/**
 * Modal Web Component
 */
export class Modal extends BaseComponent {
    static get observedAttributes(): string[] {
        return ['title', 'size', 'centered', 'static-backdrop', 'scrollable', 'fullscreen'];
    }

    private _bsModal: BootstrapModalInstance | null = null;
    private _resolvePromise: ((value: boolean) => void) | null = null;
    private _showPromise: (() => void) | null = null;
    private _hidePromise: (() => void) | null = null;

    constructor() {
        super();
    }

    protected override onMount(): void {
        this.render();
        this.initBootstrapModal();
        this.bindEvents();
    }

    protected override onUnmount(): void {
        if (this._bsModal) {
            this._bsModal.dispose();
            this._bsModal = null;
        }
    }

    protected override onAttributeChange(name: string): void {
        if (['title', 'size', 'centered', 'scrollable', 'fullscreen'].includes(name)) {
            if (this._mounted) {
                this.render();
                this.bindEvents();
            }
        }
    }

    // ===================== Getters =====================

    get modalTitle(): string {
        return this.getAttr('title', '');
    }

    get size(): ModalSize {
        const s = this.getAttribute('size');
        if (s === 'sm' || s === 'md' || s === 'lg' || s === 'xl' || s === 'fullscreen') {
            return s;
        }
        return 'md';
    }

    get isCentered(): boolean {
        return this.getBoolAttr('centered');
    }

    get isStaticBackdrop(): boolean {
        return this.getBoolAttr('static-backdrop');
    }

    get isScrollable(): boolean {
        return this.getBoolAttr('scrollable');
    }

    get isFullscreen(): boolean {
        return this.getBoolAttr('fullscreen');
    }

    // ===================== Public API =====================

    /**
     * Show the modal
     */
    show(): Promise<void> {
        this.emitDOMEvent('modal-show');
        this._bsModal?.show();
        return new Promise(resolve => {
            this._showPromise = resolve;
        });
    }

    /**
     * Hide the modal
     */
    hide(): Promise<void> {
        this.emitDOMEvent('modal-hide');
        this._bsModal?.hide();
        return new Promise(resolve => {
            this._hidePromise = resolve;
        });
    }

    /**
     * Toggle modal visibility
     */
    toggle(): void {
        this._bsModal?.toggle();
    }

    /**
     * Update modal content dynamically
     */
    setContent(options: ModalContentOptions): void {
        if (options.title !== undefined) {
            const titleEl = this.$('.modal-title') as HTMLElement | null;
            if (titleEl) titleEl.innerHTML = options.title;
        }
        if (options.body !== undefined) {
            const bodyEl = this.$('.modal-body') as HTMLElement | null;
            if (bodyEl) bodyEl.innerHTML = options.body;
        }
        if (options.footer !== undefined) {
            const footerEl = this.$('.modal-footer') as HTMLElement | null;
            if (footerEl) {
                footerEl.innerHTML = options.footer;
                this.bindFooterEvents();
            }
        }
    }

    /**
     * Show as confirmation dialog
     * @returns true if confirmed, false if cancelled
     */
    async confirm(options: ConfirmOptions = {}): Promise<boolean> {
        const { title = 'Confirm', message = 'Are you sure?', confirmText = 'Confirm', cancelText = 'Cancel', variant = 'primary' } = options;

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
     */
    async alert(options: AlertOptions): Promise<void> {
        const { title = 'Alert', message, variant = 'info', icon = 'bi-info-circle', buttonText = 'OK' } = options;

        const iconColors: Record<string, string> = {
            success: 'text-success',
            danger: 'text-danger',
            warning: 'text-warning',
            info: 'text-info',
        };

        this.setContent({
            title,
            body: `
        <div class="text-center py-3">
          <i class="${icon} ${iconColors[variant]} fs-1 mb-3 d-block"></i>
          <p class="mb-0">${message}</p>
        </div>
      `,
            footer: `
        <button type="button" class="btn btn-${variant}" data-dismiss>${buttonText}</button>
      `,
        });

        return new Promise(resolve => {
            this._resolvePromise = () => resolve();
            this.show();
        });
    }

    // ===================== Private Methods =====================

    private initBootstrapModal(): void {
        const modalEl = this.$('.modal');
        if (!modalEl || typeof bootstrap === 'undefined') {
            console.warn('[Modal] Bootstrap not available or modal element not found');
            return;
        }

        this._bsModal = new bootstrap.Modal(modalEl, {
            backdrop: this.isStaticBackdrop ? 'static' : true,
            keyboard: !this.isStaticBackdrop,
        });

        // Listen for Bootstrap modal events
        modalEl.addEventListener('shown.bs.modal', () => {
            this.emitDOMEvent('modal-shown');
            this._showPromise?.();
            this._showPromise = null;
        });

        modalEl.addEventListener('hidden.bs.modal', () => {
            this.emitDOMEvent('modal-hidden');
            this._hidePromise?.();
            this._hidePromise = null;
            // If no explicit confirm, resolve as false
            if (this._resolvePromise) {
                this._resolvePromise(false);
                this._resolvePromise = null;
            }
        });
    }

    private bindEvents(): void {
        this.bindFooterEvents();
    }

    private bindFooterEvents(): void {
        // Dismiss buttons
        const dismissBtns = this.$$('[data-dismiss]');
        for (const btn of dismissBtns) {
            btn.addEventListener('click', () => {
                this.emitDOMEvent('modal-dismiss');
                if (this._resolvePromise) {
                    this._resolvePromise(false);
                    this._resolvePromise = null;
                }
                this.hide();
            });
        }

        // Confirm buttons
        const confirmBtns = this.$$('[data-confirm]');
        for (const btn of confirmBtns) {
            btn.addEventListener('click', () => {
                this.emitDOMEvent('modal-confirm');
                if (this._resolvePromise) {
                    this._resolvePromise(true);
                    this._resolvePromise = null;
                }
                this.hide();
            });
        }
    }

    private getSizeClass(): string {
        if (this.isFullscreen) return 'modal-fullscreen';
        switch (this.size) {
            case 'sm':
                return 'modal-sm';
            case 'lg':
                return 'modal-lg';
            case 'xl':
                return 'modal-xl';
            default:
                return '';
        }
    }

    override render(): void {
        const sizeClass = this.getSizeClass();
        const centeredClass = this.isCentered ? 'modal-dialog-centered' : '';
        const scrollableClass = this.isScrollable ? 'modal-dialog-scrollable' : '';

        // Check for slotted content
        const bodySlot = this.querySelector('[slot="body"]');
        const footerSlot = this.querySelector('[slot="footer"]');

        const bodyContent = bodySlot?.innerHTML || '<p>Modal content</p>';
        const footerContent =
            footerSlot?.innerHTML ||
            `
      <button type="button" class="btn btn-secondary" data-dismiss>Close</button>
    `;

        this.innerHTML = `
      <div class="modal fade" tabindex="-1" aria-hidden="true">
        <div class="modal-dialog ${sizeClass} ${centeredClass} ${scrollableClass}">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title">${this.modalTitle}</h5>
              <button type="button" class="btn-close" data-dismiss aria-label="Close"></button>
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
 * ConfirmModal - Convenience component for confirmation dialogs
 */
export class ConfirmModal extends Modal {
    static override get observedAttributes(): string[] {
        return [...super.observedAttributes, 'message', 'confirm-text', 'cancel-text', 'variant'];
    }

    protected override onMount(): void {
        // Build confirm dialog from attributes
        this.setAttribute('title', this.getAttr('title', 'Confirm'));

        super.onMount();
    }

    override render(): void {
        const message = this.getAttr('message', 'Are you sure?');
        const confirmText = this.getAttr('confirm-text', 'Confirm');
        const cancelText = this.getAttr('cancel-text', 'Cancel');
        const variant = this.getAttr('variant', 'primary');

        const sizeClass = this.getConfirmSizeClass();
        const centeredClass = this.isCentered ? 'modal-dialog-centered' : '';

        this.innerHTML = `
      <div class="modal fade" tabindex="-1" aria-hidden="true">
        <div class="modal-dialog ${sizeClass} ${centeredClass}">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title">${this.modalTitle}</h5>
              <button type="button" class="btn-close" data-dismiss aria-label="Close"></button>
            </div>
            <div class="modal-body">
              <p class="mb-0">${message}</p>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-secondary" data-dismiss>${cancelText}</button>
              <button type="button" class="btn btn-${variant}" data-confirm>${confirmText}</button>
            </div>
          </div>
        </div>
      </div>
    `;
    }

    private getConfirmSizeClass(): string {
        switch (this.size) {
            case 'sm':
                return 'modal-sm';
            case 'lg':
                return 'modal-lg';
            case 'xl':
                return 'modal-xl';
            default:
                return '';
        }
    }
}

// Register custom elements
if (!customElements.get('ui-modal')) {
    customElements.define('ui-modal', Modal);
}

if (!customElements.get('ui-confirm-modal')) {
    customElements.define('ui-confirm-modal', ConfirmModal);
}

export default Modal;
