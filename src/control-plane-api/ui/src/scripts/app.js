/**
 * Application Entry Point
 * Main application initialization and event handling
 *
 * Uses Web Component-based page architecture (OverviewPage, WorkersPage, LabletsPage, SystemPage).
 */

import { checkAuth } from './api/client.js';
import { login, logout, showLoginForm, showDashboard } from './ui/auth.js';
import { loadTasks, handleCreateTask, handleUpdateTask } from './ui/tasks.js';
import { initializeTheme } from './services/theme.js';
import { initializeConnectionIndicator } from './services/connection-indicator.js';
import { sessionManager } from './services/session-manager.js';
import { eventBus, EventTypes } from './core/EventBus.js';
import { connectSSE, disconnectSSE } from './app/sse/sseAdapter.js';
import { showToast } from './ui/notifications.js';
import { setupCreateWorkerModal, setupImportWorkerModal, setupDeleteWorkerModal, setupLicenseModal, setupCreateWorkerTemplateModal } from './ui/worker-modals.js';
import { setupCreateLabletSessionModal, setupCreateLabletDefinitionModal, setupDeleteLabletSessionModal } from './ui/lablet-modals.js';

// Import page components
import './components/pages/OverviewPage.js';
import './components/pages/WorkersPageV2.js';
import './components/pages/SystemPage.js';
import './components/pages/SchedulerPage.js';
import './components/pages/LabRecordsPageV2.js';
import './components/pages/SessionsPageV2.js';

// Current user and active view
let currentUser = null;
let activeView = 'tasks';

// Page component instances
let workersPageInstance = null;
let overviewPageInstance = null;
let systemPageInstance = null;
let schedulerPageInstance = null;
let labRecordsPageInstance = null;
let sessionsPageInstance = null;

/**
 * Initialize WorkersPage component (V2 — store-driven)
 */
function initializeWorkersPage() {
    const container = document.querySelector('#workers-section .container, #workers-section');
    if (!container) {
        console.warn('[APP] Workers container not found');
        return;
    }

    if (workersPageInstance) return;

    container.innerHTML = '<workers-page-v2 id="workers-page-v2"></workers-page-v2>';
    workersPageInstance = container.querySelector('workers-page-v2');

    if (workersPageInstance) {
        workersPageInstance.initialize(currentUser);
    }
}

/**
 * Initialize OverviewPage component
 */
function initializeOverviewPage() {
    const container = document.querySelector('#overview-section .container, #overview-section');
    if (!container) {
        console.warn('[APP] Overview container not found');
        return;
    }

    // Check if already initialized
    if (overviewPageInstance) {
        return;
    }

    // Clear and insert OverviewPage component
    container.innerHTML = '<overview-page id="overview-page"></overview-page>';
    overviewPageInstance = container.querySelector('overview-page');

    if (overviewPageInstance) {
        overviewPageInstance.initialize(currentUser);
    }
}

/**
 * Initialize SystemPage component
 * @param {string} activeTab - 'monitoring' or 'settings'
 */
function initializeSystemPage(activeTab = 'monitoring') {
    // Use the system-view section for both system and settings views
    const container = document.querySelector('#system-view .container, #system-view');
    if (!container) {
        console.warn('[APP] System container not found');
        return;
    }

    // Check if already initialized
    if (systemPageInstance) {
        // Just switch tabs
        systemPageInstance.setAttribute('active-tab', activeTab);
        return;
    }

    // Clear and insert SystemPage component
    container.innerHTML = '<system-page id="system-page"></system-page>';
    systemPageInstance = container.querySelector('system-page');

    if (systemPageInstance) {
        systemPageInstance.initialize(currentUser);
        systemPageInstance.setAttribute('active-tab', activeTab);
    }
}

/**
 * Initialize SchedulerPage component
 */
function initializeSchedulerPage() {
    const container = document.querySelector('#scheduler-section .container, #scheduler-section');
    if (!container) {
        console.warn('[APP] Scheduler container not found');
        return;
    }

    if (schedulerPageInstance) return;

    container.innerHTML = '<scheduler-page id="scheduler-page"></scheduler-page>';
    schedulerPageInstance = container.querySelector('scheduler-page');

    if (schedulerPageInstance) {
        schedulerPageInstance.initialize(currentUser);
    }
}

/**
 * Initialize LabRecordsPage component (V2 — store-driven)
 */
function initializeLabRecordsPage() {
    const container = document.querySelector('#labs-section .container, #labs-section');
    if (!container) {
        console.warn('[APP] Labs container not found');
        return;
    }

    if (labRecordsPageInstance) return;

    container.innerHTML = '<lab-records-page-v2 id="lab-records-page-v2"></lab-records-page-v2>';
    labRecordsPageInstance = container.querySelector('lab-records-page-v2');

    if (labRecordsPageInstance) {
        labRecordsPageInstance.initialize(currentUser);
    }
}

/**
 * Initialize SessionsPage component (V2 — store-driven)
 */
function initializeSessionsPage() {
    const container = document.querySelector('#sessions-section .container, #sessions-section');
    if (!container) {
        console.warn('[APP] Sessions container not found');
        return;
    }

    if (sessionsPageInstance) return;

    container.innerHTML = '<sessions-page-v2 id="sessions-page-v2"></sessions-page-v2>';
    sessionsPageInstance = container.querySelector('sessions-page-v2');

    if (sessionsPageInstance) {
        sessionsPageInstance.initialize(currentUser);
    }
}

/**
 * Check for authentication error query parameters and display appropriate toast
 */
function handleAuthErrorParams() {
    const urlParams = new URLSearchParams(window.location.search);
    const authError = urlParams.get('auth_error');

    if (authError) {
        // Remove the error parameter from URL to prevent showing toast on refresh
        const newUrl = window.location.pathname;
        window.history.replaceState({}, document.title, newUrl);

        // Show appropriate error message based on error type
        const errorMessages = {
            keycloak_unavailable: 'Authentication service is currently unavailable. Please try again later or contact your administrator.',
            session_expired: 'Your session has expired. Please log in again.',
            unauthorized: 'You are not authorized to access this application.',
        };

        const message = errorMessages[authError] || 'An authentication error occurred. Please try again.';
        showToast(message, 'error', 8000);
    }
}

/**
 * Initialize the application
 */
async function initializeApp() {
    // Check for authentication error parameters first (e.g., Keycloak unavailable)
    handleAuthErrorParams();

    // Set page title from config
    if (window.APP_CONFIG && window.APP_CONFIG.title) {
        document.title = window.APP_CONFIG.title;
    }

    // Set app version in footer
    const versionElement = document.getElementById('app-version');
    if (versionElement && window.APP_CONFIG && window.APP_CONFIG.version) {
        versionElement.textContent = window.APP_CONFIG.version;
    }

    // Set MinIO console link from config
    const minioLink = document.getElementById('minio-console-link');
    if (minioLink && window.APP_CONFIG?.minioConsoleUrl) {
        minioLink.href = `${window.APP_CONFIG.minioConsoleUrl}/login`;
    }

    // Check if user is authenticated
    const user = await checkAuth();

    if (user) {
        // User is logged in - show dashboard
        currentUser = user;
        const hasValidRole = await showDashboard(user);

        // Only proceed if user has valid role
        if (!hasValidRole) {
            console.warn('[APP] User lacks required roles, showing error page');
            return;
        }

        // Show navigation
        const mainNav = document.getElementById('main-nav');
        if (mainNav) {
            mainNav.style.display = 'flex';
        }

        // Initialize modals globally (needed for Overview page action buttons)
        setupCreateWorkerModal();
        setupImportWorkerModal();
        setupDeleteWorkerModal();
        setupLicenseModal();
        setupCreateWorkerTemplateModal();

        // Initialize lablet modals (needed for Lablets page and Overview action buttons)
        setupCreateLabletSessionModal();
        setupCreateLabletDefinitionModal();
        setupDeleteLabletSessionModal();

        // Start session monitoring
        sessionManager.init();

        // Connect SSE for real-time updates (all aggregates)
        connectSSE();

        // Subscribe to session expiration
        eventBus.on(EventTypes.AUTH_SESSION_EXPIRED, () => {
            console.warn('[APP] Session expired via SSE');
            sessionManager.stop();
            disconnectSSE();
            showLoginForm();
        });

        // Show default view - overview
        console.log('[APP] Showing default view: overview');
        showView('overview');
    } else {
        // Not logged in - show login button
        sessionManager.stop();
        disconnectSSE();
        showLoginForm();
    }
}

/**
 * Show specific view
 * @param {string} view - View name: 'overview', 'tasks', 'workers', 'worker-templates', 'lablet-instances', 'lablet-definitions', 'system', or 'settings'
 */
function showView(view) {
    console.log('[APP showView] Called with view:', view);
    activeView = view;

    // Hide all sections
    const sections = {
        overview: document.getElementById('overview-section'),
        dashboard: document.getElementById('dashboard-section'),
        workers: document.getElementById('workers-section'),
        system: document.getElementById('system-view'),
        settings: document.getElementById('settings-section'),
        scheduler: document.getElementById('scheduler-section'),
        labs: document.getElementById('labs-section'),
        sessions: document.getElementById('sessions-section'),
    };

    Object.values(sections).forEach(section => {
        if (section) section.style.display = 'none';
    });

    // Remove active state from all nav links
    document.querySelectorAll('#main-nav .nav-link').forEach(link => {
        link.classList.remove('active');
    });

    // Map views to their parent dropdown (only for System sub-views)
    const viewToParent = {
        system: 'nav-system-menu',
        settings: 'nav-system-menu',
        tasks: 'nav-system-menu',
        scheduler: 'nav-system-menu',
    };

    // Activate parent dropdown if applicable
    const parentId = viewToParent[view];
    if (parentId) {
        const parentNav = document.getElementById(parentId);
        if (parentNav) parentNav.classList.add('active');
    }

    // Activate the direct nav item
    const navMap = {
        overview: 'nav-overview',
        workers: 'nav-workers',
        labs: 'nav-labs',
        sessions: 'nav-sessions',
        system: 'nav-system-menu',
        settings: 'nav-system-menu',
        tasks: 'nav-system-menu',
        scheduler: 'nav-system-menu',
    };
    const navId = navMap[view];
    if (navId) {
        const navElement = document.getElementById(navId);
        if (navElement) navElement.classList.add('active');
    }

    // Also highlight data-view items
    const dataViewItem = document.querySelector(`[data-view="${view}"]`);
    if (dataViewItem) dataViewItem.classList.add('active');

    // Show selected section and initialize view
    switch (view) {
        case 'overview':
            console.log('[APP showView] Showing overview view');
            if (sections.overview) sections.overview.style.display = 'block';
            initializeOverviewPage();
            break;

        case 'tasks':
            console.log('[APP showView] Showing tasks view');
            if (sections.dashboard) sections.dashboard.style.display = 'block';
            loadTasks();
            break;

        case 'workers':
            console.log('[APP showView] Showing workers view');
            if (sections.workers) sections.workers.style.display = 'block';
            initializeWorkersPage();
            break;

        case 'system':
            console.log('[APP showView] Showing system view');
            if (sections.system) sections.system.style.display = 'block';
            initializeSystemPage('monitoring');
            break;

        case 'settings':
            console.log('[APP showView] Showing settings view');
            if (sections.system) sections.system.style.display = 'block';
            initializeSystemPage('settings');
            break;

        case 'scheduler':
            console.log('[APP showView] Showing scheduler view');
            if (sections.scheduler) sections.scheduler.style.display = 'block';
            initializeSchedulerPage();
            break;

        case 'labs':
            console.log('[APP showView] Showing labs view');
            if (sections.labs) sections.labs.style.display = 'block';
            initializeLabRecordsPage();
            break;

        case 'sessions':
            console.log('[APP showView] Showing sessions view');
            if (sections.sessions) sections.sessions.style.display = 'block';
            initializeSessionsPage();
            break;

        default:
            console.warn('[APP showView] Unknown view:', view);
    }
}

/**
 * Setup event listeners
 */
function setupEventListeners() {
    // Login button (redirect to Keycloak)
    const loginBtn = document.getElementById('login-btn');
    if (loginBtn) {
        loginBtn.addEventListener('click', login);
    }

    // Logout button
    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', e => {
            e.preventDefault();
            sessionManager.stop();
            disconnectSSE();
            logout();
        });
    }

    // Setup navigation - supports both old nav-* links and new data-view dropdown items
    setupNavigation();

    // Create task button
    const submitTaskBtn = document.getElementById('submit-task-btn');
    if (submitTaskBtn) {
        submitTaskBtn.addEventListener('click', handleCreateTask);
    }

    // Edit task button
    const submitEditTaskBtn = document.getElementById('submit-edit-task-btn');
    if (submitEditTaskBtn) {
        submitEditTaskBtn.addEventListener('click', handleUpdateTask);
    }
}

/**
 * Setup navigation event handlers
 * Supports both legacy nav-* IDs and new data-view attributes
 */
function setupNavigation() {
    // Navigation links (by ID)
    const legacyNavLinks = [
        { id: 'nav-overview', view: 'overview' },
        { id: 'nav-workers', view: 'workers' },
        { id: 'nav-labs', view: 'labs' },
        { id: 'nav-sessions', view: 'sessions' },
        { id: 'nav-tasks', view: 'tasks' },
        { id: 'nav-system', view: 'system' },
        { id: 'nav-settings', view: 'settings' },
        { id: 'nav-scheduler', view: 'scheduler' },
    ];

    legacyNavLinks.forEach(({ id, view }) => {
        const element = document.getElementById(id);
        if (element) {
            element.addEventListener('click', e => {
                e.preventDefault();
                showView(view);
            });
        }
    });

    // New data-view based navigation (dropdown items)
    document.querySelectorAll('[data-view]').forEach(element => {
        element.addEventListener('click', e => {
            e.preventDefault();
            const view = element.dataset.view;
            showView(view);
        });
    });

    // LcmUserMenu event handling
    const userMenu = document.querySelector('lcm-user-menu');
    console.log('[APP] Setting up user menu listener, userMenu found:', !!userMenu);
    if (userMenu) {
        userMenu.addEventListener('user-menu-action', e => {
            console.log('[APP] user-menu-action event received:', e.detail);
            const { action } = e.detail;
            if (action === 'logout') {
                console.log('[APP] Logout action - stopping session and calling logout()');
                sessionManager.stop();
                disconnectSSE();
                logout();
            } else if (action === 'preferences') {
                showView('settings');
            }
        });
    }
}

/**
 * Application startup
 */
document.addEventListener('DOMContentLoaded', async () => {
    // Initialize theme first (before content is visible)
    initializeTheme();

    // Initialize connection indicator
    initializeConnectionIndicator();

    // Set up event listeners
    setupEventListeners();

    // Initialize the application
    await initializeApp();
});
