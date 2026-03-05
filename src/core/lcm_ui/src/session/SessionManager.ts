/**
 * SessionManager - Authentication Session Lifecycle Management
 *
 * Manages authentication session with features:
 * - Automatic token refresh before expiration
 * - Inactivity timeout detection
 * - SSE event integration for real-time session updates
 * - Activity tracking with throttling
 * - StateStore integration for reactive state
 *
 * @example
 * ```typescript
 * import { SessionManager, StateStore, EventBus } from '@neuroglia/ui-core';
 *
 * const eventBus = EventBus.getInstance();
 * const store = new StateStore({
 *   slices: { session: initialSessionState },
 *   eventBus,
 * });
 *
 * const sessionManager = new SessionManager({
 *   store,
 *   eventBus,
 *   fetchSession: () => fetch('/api/auth/session').then(r => r.json()),
 *   refreshSession: () => fetch('/api/auth/refresh', { method: 'POST' }),
 *   onLogout: () => window.location.href = '/login',
 * });
 *
 * await sessionManager.start();
 * ```
 *
 * @module session
 */

import type { EventBus } from '../core/EventBus.js';
import type { StateStore } from '../core/StateStore.js';
import type { Subscription } from '../types/events.js';
import { EventTypes } from '../core/constants.js';
import type { SessionState, SessionUser } from './index.js';
import { sessionActions, sessionSelectors } from './sessionSlice.js';

/**
 * Session info response from the server
 */
export interface SessionInfo {
    /** Whether the user is authenticated */
    authenticated: boolean;
    /** User information */
    user?: {
        id: string;
        name: string;
        email: string;
        roles?: string[];
    };
    /** Seconds until session expires */
    expires_in_seconds?: number | null;
    /** Warning threshold in minutes */
    session_expiration_warning_minutes?: number;
}

/**
 * SessionManager configuration
 */
export interface SessionManagerConfig {
    /** StateStore instance */
    store: StateStore;
    /** EventBus instance */
    eventBus: EventBus;
    /** Function to fetch current session info */
    fetchSession: () => Promise<SessionInfo>;
    /** Function to refresh/extend the session */
    refreshSession: () => Promise<Response>;
    /** Callback when user should be logged out */
    onLogout: () => void;
    /** Callback when session expires */
    onExpired?: () => void;
    /** Time before expiry to trigger refresh (ms) - default 5 minutes */
    refreshThreshold?: number;
    /** Inactivity timeout (ms) - default 30 minutes, 0 to disable */
    inactivityTimeout?: number;
    /** Activity tracking throttle (ms) - default 30 seconds */
    activityThrottle?: number;
    /** Session check interval (ms) - default 60 seconds */
    checkInterval?: number;
    /** Enable debug logging */
    debug?: boolean;
}

/**
 * Default configuration values
 */
const DEFAULT_CONFIG = {
    refreshThreshold: 5 * 60 * 1000, // 5 minutes
    inactivityTimeout: 30 * 60 * 1000, // 30 minutes
    activityThrottle: 30 * 1000, // 30 seconds
    checkInterval: 60 * 1000, // 1 minute
    debug: false,
};

/**
 * User activity events to track
 */
const ACTIVITY_EVENTS = ['mousedown', 'mousemove', 'keydown', 'scroll', 'touchstart', 'click'];

/**
 * SessionManager - Manages authentication session lifecycle
 */
export class SessionManager {
    private store: StateStore;
    private eventBus: EventBus;
    private config: Required<Omit<SessionManagerConfig, 'store' | 'eventBus' | 'fetchSession' | 'refreshSession' | 'onLogout' | 'onExpired'>> & {
        fetchSession: () => Promise<SessionInfo>;
        refreshSession: () => Promise<Response>;
        onLogout: () => void;
        onExpired?: () => void;
    };

    private checkIntervalId: ReturnType<typeof setInterval> | null = null;
    private refreshTimeoutId: ReturnType<typeof setTimeout> | null = null;
    private inactivityTimeoutId: ReturnType<typeof setTimeout> | null = null;
    private lastActivityTrack: number = 0;
    private isStarted: boolean = false;
    private eventSubscriptions: Subscription[] = [];
    private boundActivityHandler: () => void;

    /**
     * Create a new SessionManager
     * @param config - Configuration options
     */
    constructor(config: SessionManagerConfig) {
        this.store = config.store;
        this.eventBus = config.eventBus;
        this.config = {
            fetchSession: config.fetchSession,
            refreshSession: config.refreshSession,
            onLogout: config.onLogout,
            onExpired: config.onExpired,
            refreshThreshold: config.refreshThreshold ?? DEFAULT_CONFIG.refreshThreshold,
            inactivityTimeout: config.inactivityTimeout ?? DEFAULT_CONFIG.inactivityTimeout,
            activityThrottle: config.activityThrottle ?? DEFAULT_CONFIG.activityThrottle,
            checkInterval: config.checkInterval ?? DEFAULT_CONFIG.checkInterval,
            debug: config.debug ?? DEFAULT_CONFIG.debug,
        };

        // Bind activity handler for consistent reference
        this.boundActivityHandler = this.handleActivity.bind(this);
    }

    /**
     * Start session management
     * Fetches current session, sets up timers, and subscribes to events
     */
    async start(): Promise<void> {
        if (this.isStarted) {
            this.log('Already started, skipping');
            return;
        }

        this.isStarted = true;
        this.log('Starting session manager');

        // Fetch initial session state
        await this.checkSession();

        // Start periodic session check
        this.checkIntervalId = setInterval(() => this.checkSession(), this.config.checkInterval);

        // Set up activity tracking
        this.setupActivityTracking();

        // Subscribe to SSE events
        this.setupEventSubscriptions();

        // Emit ready event
        await this.eventBus.emit(EventTypes.AUTH_LOGIN, this.getSessionState());

        this.log('Session manager started');
    }

    /**
     * Stop session management
     * Clears all timers and unsubscribes from events
     */
    stop(): void {
        if (!this.isStarted) {
            return;
        }

        this.log('Stopping session manager');

        this.isStarted = false;

        // Clear all timers
        this.clearTimers();

        // Remove activity listeners
        this.removeActivityTracking();

        // Unsubscribe from events
        this.eventSubscriptions.forEach(sub => sub.unsubscribe());
        this.eventSubscriptions = [];

        this.log('Session manager stopped');
    }

    /**
     * Get current session state from store
     */
    getSessionState(): SessionState {
        return sessionSelectors.selectSession(this.store.getState());
    }

    /**
     * Check if user is authenticated
     */
    isAuthenticated(): boolean {
        return sessionSelectors.selectIsAuthenticated(this.store.getState());
    }

    /**
     * Get current user
     */
    getUser(): SessionUser | null {
        return sessionSelectors.selectUser(this.store.getState());
    }

    /**
     * Check if user has a specific role
     */
    hasRole(role: string): boolean {
        return sessionSelectors.selectHasRole(this.store.getState(), role);
    }

    /**
     * Manually trigger session refresh
     */
    async refresh(): Promise<boolean> {
        return this.refreshSession();
    }

    /**
     * Log out the user
     */
    async logout(): Promise<void> {
        this.log('Logging out');

        this.stop();

        // Update state
        this.store.dispatch(sessionActions.logout());

        // Emit logout event
        await this.eventBus.emit(EventTypes.AUTH_LOGOUT, {});

        // Call logout callback
        this.config.onLogout();
    }

    /**
     * Manually record user activity
     */
    recordActivity(): void {
        this.handleActivity();
    }

    // ========================================================================
    // Private Methods
    // ========================================================================

    /**
     * Check current session status
     */
    private async checkSession(): Promise<void> {
        try {
            const sessionInfo = await this.config.fetchSession();

            this.log('Session check result:', sessionInfo);

            if (!sessionInfo.authenticated) {
                // Not authenticated
                if (this.isAuthenticated()) {
                    // Was authenticated, now expired
                    await this.handleExpiration();
                }
                return;
            }

            // Calculate expiration timestamp
            const expiresInSeconds = sessionInfo.expires_in_seconds ?? null;
            const expiresAt = expiresInSeconds !== null ? Date.now() + expiresInSeconds * 1000 : null;

            // Build user object
            const user: SessionUser | null = sessionInfo.user
                ? {
                      id: sessionInfo.user.id,
                      name: sessionInfo.user.name,
                      email: sessionInfo.user.email,
                      roles: sessionInfo.user.roles ?? [],
                  }
                : null;

            // Update state
            if (user) {
                if (!this.isAuthenticated()) {
                    // First login
                    this.store.dispatch(sessionActions.login(user, expiresAt ?? Date.now() + 3600000));
                } else {
                    // Update existing session
                    this.store.dispatch(
                        sessionActions.update({
                            user,
                            expiresAt,
                        })
                    );
                }
            }

            // Check if session is expiring soon
            if (expiresInSeconds !== null) {
                if (expiresInSeconds <= 0) {
                    await this.handleExpiration();
                } else if (expiresInSeconds * 1000 <= this.config.refreshThreshold) {
                    // Schedule refresh
                    this.scheduleRefresh(expiresInSeconds * 1000);

                    // Emit expiring event
                    await this.eventBus.emit(EventTypes.AUTH_SESSION_EXPIRING, {
                        expiresIn: expiresInSeconds,
                        expiresAt,
                    });
                } else {
                    // Schedule refresh for later
                    const refreshIn = expiresInSeconds * 1000 - this.config.refreshThreshold;
                    this.scheduleRefresh(refreshIn);
                }
            }
        } catch (error) {
            this.log('Session check failed:', error);
        }
    }

    /**
     * Schedule a token refresh
     */
    private scheduleRefresh(delayMs: number): void {
        // Clear existing timeout
        if (this.refreshTimeoutId) {
            clearTimeout(this.refreshTimeoutId);
        }

        const actualDelay = Math.max(0, delayMs);
        this.log(`Scheduling refresh in ${Math.round(actualDelay / 1000)}s`);

        this.refreshTimeoutId = setTimeout(() => {
            this.refreshSession();
        }, actualDelay);
    }

    /**
     * Refresh the session token
     */
    private async refreshSession(): Promise<boolean> {
        const session = this.getSessionState();

        if (session.isRefreshing) {
            this.log('Refresh already in progress');
            return false;
        }

        this.log('Refreshing session');
        this.store.dispatch(sessionActions.refreshStart());

        try {
            const response = await this.config.refreshSession();

            if (!response.ok) {
                throw new Error(`Refresh failed: ${response.status}`);
            }

            // Re-check session to get new expiry
            await this.checkSession();

            this.store.dispatch(sessionActions.refreshSuccess(this.getSessionState().expiresAt ?? Date.now() + 3600000));

            // Emit token refreshed event
            await this.eventBus.emit(EventTypes.AUTH_TOKEN_REFRESHED, {
                expiresAt: this.getSessionState().expiresAt,
            });

            this.log('Session refreshed successfully');
            return true;
        } catch (error) {
            this.log('Session refresh failed:', error);
            this.store.dispatch(sessionActions.refreshFailure());
            return false;
        }
    }

    /**
     * Handle session expiration
     */
    private async handleExpiration(): Promise<void> {
        this.log('Session expired');

        this.stop();

        // Update state
        this.store.dispatch(sessionActions.expired());

        // Emit expired event
        await this.eventBus.emit(EventTypes.AUTH_SESSION_EXPIRED, {});

        // Call expired callback or logout
        if (this.config.onExpired) {
            this.config.onExpired();
        } else {
            this.config.onLogout();
        }
    }

    /**
     * Set up activity tracking
     */
    private setupActivityTracking(): void {
        if (typeof window === 'undefined') {
            return;
        }

        ACTIVITY_EVENTS.forEach(event => {
            window.addEventListener(event, this.boundActivityHandler, { passive: true });
        });

        // Set initial activity time
        this.lastActivityTrack = Date.now();
        this.store.dispatch(sessionActions.activity());

        // Start inactivity check if enabled
        if (this.config.inactivityTimeout > 0) {
            this.resetInactivityTimer();
        }
    }

    /**
     * Remove activity tracking
     */
    private removeActivityTracking(): void {
        if (typeof window === 'undefined') {
            return;
        }

        ACTIVITY_EVENTS.forEach(event => {
            window.removeEventListener(event, this.boundActivityHandler);
        });
    }

    /**
     * Handle user activity (throttled)
     */
    private handleActivity(): void {
        const now = Date.now();

        // Throttle activity tracking
        if (now - this.lastActivityTrack < this.config.activityThrottle) {
            // Still reset inactivity timer on any activity
            if (this.config.inactivityTimeout > 0) {
                this.resetInactivityTimer();
            }
            return;
        }

        this.lastActivityTrack = now;
        this.store.dispatch(sessionActions.activity());

        // Reset inactivity timer
        if (this.config.inactivityTimeout > 0) {
            this.resetInactivityTimer();
        }
    }

    /**
     * Reset the inactivity timeout timer
     */
    private resetInactivityTimer(): void {
        if (this.inactivityTimeoutId) {
            clearTimeout(this.inactivityTimeoutId);
        }

        this.inactivityTimeoutId = setTimeout(() => {
            this.handleInactivityTimeout();
        }, this.config.inactivityTimeout);
    }

    /**
     * Handle inactivity timeout
     */
    private async handleInactivityTimeout(): Promise<void> {
        this.log('Inactivity timeout reached');

        // Check if still authenticated before logging out
        if (this.isAuthenticated()) {
            await this.logout();
        }
    }

    /**
     * Set up SSE event subscriptions
     */
    private setupEventSubscriptions(): void {
        // Listen for SSE session events
        const sessionExpiringSub = this.eventBus.on(EventTypes.SSE_MESSAGE, (data: unknown) => {
            const event = data as { type?: string; data?: unknown };

            // Handle session-related SSE events
            if (event.type === 'session_expiring') {
                this.handleSseSessionExpiring(event.data);
            } else if (event.type === 'session_extended') {
                this.handleSseSessionExtended(event.data);
            } else if (event.type === 'session_expired') {
                this.handleSseSessionExpired();
            }
        });

        this.eventSubscriptions.push(sessionExpiringSub);
    }

    /**
     * Handle SSE session expiring event
     */
    private handleSseSessionExpiring(data: unknown): void {
        const eventData = data as { expires_in_seconds?: number } | undefined;
        const expiresInSeconds = eventData?.expires_in_seconds ?? 300;

        this.log('SSE: Session expiring in', expiresInSeconds, 'seconds');

        const expiresAt = Date.now() + expiresInSeconds * 1000;
        this.store.dispatch(sessionActions.update({ expiresAt }));

        // Emit auth event
        this.eventBus.emit(EventTypes.AUTH_SESSION_EXPIRING, {
            expiresIn: expiresInSeconds,
            expiresAt,
        });

        // Schedule refresh if not already scheduled
        if (!this.refreshTimeoutId) {
            this.scheduleRefresh(Math.min(expiresInSeconds * 1000, this.config.refreshThreshold));
        }
    }

    /**
     * Handle SSE session extended event
     */
    private handleSseSessionExtended(data: unknown): void {
        const eventData = data as { expires_in_seconds?: number } | undefined;
        const expiresInSeconds = eventData?.expires_in_seconds ?? 3600;

        this.log('SSE: Session extended');

        const expiresAt = Date.now() + expiresInSeconds * 1000;
        this.store.dispatch(sessionActions.update({ expiresAt }));

        // Emit token refreshed event
        this.eventBus.emit(EventTypes.AUTH_TOKEN_REFRESHED, { expiresAt });

        // Reschedule refresh
        const refreshIn = expiresInSeconds * 1000 - this.config.refreshThreshold;
        this.scheduleRefresh(refreshIn);
    }

    /**
     * Handle SSE session expired event
     */
    private handleSseSessionExpired(): void {
        this.log('SSE: Session expired');
        this.handleExpiration();
    }

    /**
     * Clear all timers
     */
    private clearTimers(): void {
        if (this.checkIntervalId) {
            clearInterval(this.checkIntervalId);
            this.checkIntervalId = null;
        }

        if (this.refreshTimeoutId) {
            clearTimeout(this.refreshTimeoutId);
            this.refreshTimeoutId = null;
        }

        if (this.inactivityTimeoutId) {
            clearTimeout(this.inactivityTimeoutId);
            this.inactivityTimeoutId = null;
        }
    }

    /**
     * Log debug message
     */
    private log(...args: unknown[]): void {
        if (this.config.debug) {
            console.log('[SessionManager]', ...args);
        }
    }
}
