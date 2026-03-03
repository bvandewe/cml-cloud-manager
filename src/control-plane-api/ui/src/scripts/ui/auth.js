import * as bootstrap from 'bootstrap';

/**
 * Authentication UI Module
 * Handles login/logout UI interactions
 */

/**
 * Redirect to Keycloak login
 */
export function login() {
    window.location.href = '/api/auth/login';
}

/**
 * Redirect to logout
 */
export function logout() {
    window.location.href = '/api/auth/logout';
}

/**
 * Show login form (hide dashboard)
 */
export function showLoginForm() {
    // Close all open Bootstrap modals
    const openModals = document.querySelectorAll('.modal.show');
    openModals.forEach(modalElement => {
        const modalInstance = bootstrap.Modal.getInstance(modalElement);
        if (modalInstance) {
            modalInstance.hide();
        } else {
            // Fallback: manually hide if instance not found
            modalElement.classList.remove('show');
            modalElement.style.display = 'none';
            modalElement.setAttribute('aria-hidden', 'true');
            modalElement.removeAttribute('aria-modal');
            modalElement.removeAttribute('role');
        }
    });

    // Remove any lingering modal backdrops
    const backdrops = document.querySelectorAll('.modal-backdrop');
    backdrops.forEach(backdrop => backdrop.remove());

    // Reset body classes that Bootstrap adds for modals
    document.body.classList.remove('modal-open');
    document.body.style.overflow = '';
    document.body.style.paddingRight = '';

    // Show login, hide dashboard - with null checks for new navbar
    const loginSection = document.getElementById('login-section');
    const dashboardSection = document.getElementById('dashboard-section');
    const logoutBtn = document.getElementById('logout-btn');
    const userInfo = document.getElementById('user-info');

    if (loginSection) loginSection.style.display = 'flex';
    if (dashboardSection) dashboardSection.style.display = 'none';
    if (logoutBtn) logoutBtn.style.display = 'none';
    if (userInfo) userInfo.textContent = '';

    // Hide demo users info if not in dev environment
    const demoUsersInfo = document.getElementById('demo-users-info');
    if (demoUsersInfo) {
        const env = (window.APP_CONFIG && window.APP_CONFIG.environment) || 'development';
        if (!env.startsWith('dev')) {
            demoUsersInfo.style.display = 'none';
        } else {
            demoUsersInfo.style.display = 'block';
        }
    }

    // Hide LcmUserMenu if present (new navbar)
    const userMenu = document.querySelector('lcm-user-menu');
    if (userMenu) userMenu.style.display = 'none';

    // Show login button if present (new navbar)
    const loginBtn = document.getElementById('login-btn');
    if (loginBtn) loginBtn.style.display = '';

    // Hide ALL other sections (must include every view added to the SPA)
    const sectionsToHide = [
        'overview-section',
        'dashboard-section',
        'workers-section',
        'lablet-definitions-section',
        'system-view',
        'settings-section',
        'labs-section',
        'scheduler-section',
        'sessions-section',
        'insufficient-permissions-section',
        'main-nav',
        'session-warning',
    ];
    sectionsToHide.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
    });

    // Clear user roles from localStorage on logout
    localStorage.removeItem('user_roles');
}

/**
 * Show dashboard (hide login form)
 * @param {Object} user - User object from auth
 * @returns {Promise<boolean>} True if user has valid role, false otherwise
 */
export async function showDashboard(user) {
    // Store user roles in localStorage for UI role checks
    if (user.roles) {
        localStorage.setItem('user_roles', JSON.stringify(user.roles));
    }

    // Import hasValidRole dynamically to avoid circular dependencies
    const { hasValidRole } = await import('../utils/roles.js');

    if (!hasValidRole()) {
        showInsufficientPermissionsError(user);
        return false;
    }

    // User has valid role - show dashboard with null checks for new navbar
    const loginSection = document.getElementById('login-section');
    const dashboardSection = document.getElementById('dashboard-section');
    const logoutBtn = document.getElementById('logout-btn');
    const userInfo = document.getElementById('user-info');

    if (loginSection) loginSection.style.display = 'none';
    if (dashboardSection) dashboardSection.style.display = 'block';
    if (logoutBtn) logoutBtn.style.display = 'block';
    if (userInfo) userInfo.textContent = `${user.preferred_username || user.email} (${user.email})`;

    // Setup LcmUserMenu component if present (new navbar)
    const userMenu = document.querySelector('lcm-user-menu');
    if (userMenu) {
        userMenu.setAttribute('user-name', user.preferred_username || user.name || user.email);
        userMenu.setAttribute('user-email', user.email || '');
        userMenu.setAttribute('roles', JSON.stringify(user.roles || []));
        // Hide legacy logout button when using new user menu
        if (logoutBtn) logoutBtn.style.display = 'none';
        if (userInfo) userInfo.style.display = 'none';
        // Show the user menu
        userMenu.style.display = '';
    }

    // Hide login button when authenticated
    const loginBtn = document.getElementById('login-btn');
    if (loginBtn) loginBtn.style.display = 'none';

    // Show/hide nav items based on role - System nav is admin-only
    const isAdmin = user.roles && user.roles.includes('admin');
    const adminOnlyNavItems = document.querySelectorAll('.admin-only-nav');
    adminOnlyNavItems.forEach(item => {
        if (isAdmin) {
            item.style.display = ''; // Reset to default display
        } else {
            item.style.display = 'none';
        }
    });

    // Also handle admin-only dropdown items
    const adminOnlyItems = document.querySelectorAll('.admin-only');
    adminOnlyItems.forEach(item => {
        if (isAdmin) {
            item.style.display = '';
        } else {
            item.style.display = 'none';
        }
    });

    return true;
}

/**
 * Show insufficient permissions error page
 * @param {Object} user - User object with roles
 */
export function showInsufficientPermissionsError(user) {
    // Hide all sections completely
    document.getElementById('login-section').style.display = 'none';
    document.getElementById('dashboard-section').style.display = 'none';

    const workersSection = document.getElementById('workers-section');
    if (workersSection) workersSection.style.display = 'none';

    const labletDefinitionsSection = document.getElementById('lablet-definitions-section');
    if (labletDefinitionsSection) labletDefinitionsSection.style.display = 'none';

    const systemSection = document.getElementById('system-view');
    if (systemSection) systemSection.style.display = 'none';

    const settingsSection = document.getElementById('settings-section');
    if (settingsSection) settingsSection.style.display = 'none';

    const mainNav = document.getElementById('main-nav');
    if (mainNav) mainNav.style.display = 'none';

    // Show only logout button
    document.getElementById('logout-btn').style.display = 'block';

    // Create or show error message
    let errorSection = document.getElementById('insufficient-permissions-section');
    if (!errorSection) {
        errorSection = document.createElement('div');
        errorSection.id = 'insufficient-permissions-section';
        errorSection.className = 'container mt-5';
        errorSection.innerHTML = `
            <div class="row justify-content-center">
                <div class="col-md-8 col-lg-6">
                    <div class="card border-warning">
                        <div class="card-header bg-warning text-dark">
                            <h4 class="mb-0">
                                <i class="bi bi-exclamation-triangle-fill me-2"></i>
                                Insufficient Permissions
                            </h4>
                        </div>
                        <div class="card-body">
                            <p class="lead">You do not have the required permissions to access this application.</p>
                            <hr>
                            <p class="text-muted mb-3">
                                <strong>What to do:</strong>
                            </p>
                            <ul class="text-muted">
                                <li>Contact your administrator to request appropriate access</li>
                                <li>Ensure you are logged in with the correct account</li>
                                <li>If you believe this is an error, please contact support</li>
                            </ul>
                            <div class="d-grid gap-2 mt-4">
                                <button id="error-logout-btn" class="btn btn-primary btn-lg">
                                    <i class="bi bi-box-arrow-right me-2"></i>
                                    Logout
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(errorSection);

        // Add logout handler
        document.getElementById('error-logout-btn').addEventListener('click', logout);
    }

    errorSection.style.display = 'block';
}
