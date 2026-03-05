/**
 * LcmUserMenu - User Profile Dropdown Web Component
 *
 * Displays user avatar/initials with a dropdown menu for preferences and logout.
 *
 * Usage:
 *   <lcm-user-menu
 *     user-name="John Doe"
 *     user-email="john@example.com"
 *     avatar-url="/api/users/me/avatar"
 *     roles="admin,manager">
 *   </lcm-user-menu>
 *
 * Events:
 *   - 'user-menu-action': Fired when menu item clicked { action }
 *
 * @module components/core/LcmUserMenu
 */

import { BaseComponent } from '../../core/BaseComponent.js';
import { EventTypes, eventBus } from '../../core/EventBus.js';
import * as bootstrap from 'bootstrap';

export class LcmUserMenu extends BaseComponent {
    static get observedAttributes() {
        return ['user-name', 'user-email', 'avatar-url', 'roles'];
    }

    constructor() {
        super();
        this._dropdown = null;
    }

    onMount() {
        this.render();
        this._initDropdown();
    }

    onUnmount() {
        if (this._dropdown) {
            this._dropdown.dispose();
        }
    }

    onAttributeChange() {
        this.render();
        this._initDropdown();
    }

    get userName() {
        return this.getAttribute('user-name') || 'User';
    }

    get userEmail() {
        return this.getAttribute('user-email') || '';
    }

    get avatarUrl() {
        return this.getAttribute('avatar-url');
    }

    get roles() {
        const rolesAttr = this.getAttribute('roles') || '';
        return rolesAttr.split(',').filter(r => r.trim());
    }

    get initials() {
        const parts = this.userName.split(' ');
        if (parts.length >= 2) {
            return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
        }
        return this.userName.substring(0, 2).toUpperCase();
    }

    get isAdmin() {
        return this.roles.includes('admin') || this.roles.includes('lcm_admin');
    }

    render() {
        const avatarHtml = this.avatarUrl
            ? `<img src="${this.avatarUrl}" alt="${this.userName}" class="rounded-circle" width="32" height="32">`
            : `<div class="avatar-initials rounded-circle bg-primary text-white d-flex align-items-center justify-content-center"
                    style="width: 32px; height: 32px; font-size: 12px; font-weight: 600;">
                ${this.initials}
               </div>`;

        const rolesBadge = this.isAdmin ? '<span class="badge bg-danger ms-1" style="font-size: 0.65rem;">Admin</span>' : '';

        this.innerHTML = `
            <div class="dropdown">
                <button class="btn btn-link nav-link dropdown-toggle d-flex align-items-center gap-2 text-decoration-none"
                        type="button"
                        id="userMenuDropdown"
                        data-bs-toggle="dropdown"
                        aria-expanded="false">
                    ${avatarHtml}
                    <span class="d-none d-lg-inline text-white">${this.userName}${rolesBadge}</span>
                </button>
                <ul class="dropdown-menu dropdown-menu-end shadow" aria-labelledby="userMenuDropdown">
                    <li class="dropdown-header">
                        <div class="fw-bold">${this.userName}</div>
                        <small class="text-muted">${this.userEmail}</small>
                    </li>
                    <li><hr class="dropdown-divider"></li>
                    <li>
                        <a class="dropdown-item" href="#" data-action="preferences">
                            <i class="bi bi-gear me-2"></i> Preferences
                        </a>
                    </li>
                    <li>
                        <a class="dropdown-item" href="#" data-action="notifications">
                            <i class="bi bi-bell me-2"></i> Notifications
                        </a>
                    </li>
                    ${
                        this.isAdmin
                            ? `
                    <li><hr class="dropdown-divider"></li>
                    <li>
                        <a class="dropdown-item" href="/api/docs/" target="_blank">
                            <i class="bi bi-file-code me-2"></i> API Docs
                        </a>
                    </li>
                    `
                            : ''
                    }
                    <li><hr class="dropdown-divider"></li>
                    <li>
                        <a class="dropdown-item text-danger" href="#" data-action="logout">
                            <i class="bi bi-box-arrow-right me-2"></i> Logout
                        </a>
                    </li>
                </ul>
            </div>
        `;

        // Bind action handlers
        this.querySelectorAll('[data-action]').forEach(item => {
            item.addEventListener('click', e => {
                e.preventDefault();
                const action = item.dataset.action;
                this._handleAction(action);
            });
        });
    }

    _initDropdown() {
        const dropdownEl = this.querySelector('.dropdown-toggle');
        if (dropdownEl) {
            this._dropdown = new bootstrap.Dropdown(dropdownEl);
        }
    }

    _handleAction(action) {
        console.log('[LcmUserMenu] Action triggered:', action);

        // Emit local event (matches app.js listener 'user-menu-action')
        this.dispatchEvent(
            new CustomEvent('user-menu-action', {
                detail: { action },
                bubbles: true,
            })
        );

        // Emit on EventBus
        eventBus.emit(EventTypes.UI_USER_ACTION, { action });

        // Handle specific actions via EventBus
        switch (action) {
            case 'logout':
                eventBus.emit(EventTypes.AUTH_LOGOUT);
                break;
            case 'preferences':
                eventBus.emit(EventTypes.UI_SHOW_PREFERENCES);
                break;
            case 'notifications':
                eventBus.emit(EventTypes.UI_SHOW_NOTIFICATIONS);
                break;
        }
    }
}

// Register custom element
if (!customElements.get('lcm-user-menu')) {
    customElements.define('lcm-user-menu', LcmUserMenu);
}

export default LcmUserMenu;
