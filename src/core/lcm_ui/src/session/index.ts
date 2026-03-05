/**
 * Session management module exports
 *
 * Contains:
 * - SessionManager: Authentication session lifecycle management
 * - sessionSlice: State slice definition for session data
 * - Session state interfaces and types
 * - Action creators and selectors
 *
 * @module session
 */

// ============================================================================
// Type Definitions
// ============================================================================

/**
 * Session state interface
 */
export interface SessionState {
    /** Whether the user is authenticated */
    isAuthenticated: boolean;
    /** User information from the token */
    user: SessionUser | null;
    /** Session expiration timestamp (ms since epoch) */
    expiresAt: number | null;
    /** Whether a token refresh is in progress */
    isRefreshing: boolean;
    /** Last activity timestamp for inactivity detection */
    lastActivity: number;
}

/**
 * User information extracted from authentication token
 */
export interface SessionUser {
    /** User's unique identifier */
    id: string;
    /** User's display name */
    name: string;
    /** User's email address */
    email: string;
    /** User's roles/permissions */
    roles: string[];
}

/**
 * Session configuration options (for endpoint-based config)
 */
export interface SessionConfig {
    /** Token refresh endpoint */
    refreshEndpoint: string;
    /** Logout endpoint */
    logoutEndpoint: string;
    /** Session info endpoint */
    sessionInfoEndpoint: string;
    /** Time before expiry to trigger refresh (ms) - default 5 minutes */
    refreshThreshold: number;
    /** Inactivity timeout (ms) - default 30 minutes */
    inactivityTimeout: number;
    /** Activity tracking throttle (ms) - default 30 seconds */
    activityThrottle: number;
}

/**
 * Default session configuration
 */
export const defaultSessionConfig: SessionConfig = {
    refreshEndpoint: '/api/auth/refresh',
    logoutEndpoint: '/api/auth/logout',
    sessionInfoEndpoint: '/api/auth/me',
    refreshThreshold: 5 * 60 * 1000, // 5 minutes
    inactivityTimeout: 30 * 60 * 1000, // 30 minutes
    activityThrottle: 30 * 1000, // 30 seconds
};

// ============================================================================
// Session Slice Exports
// ============================================================================

export {
    // Action types
    SessionActionTypes,
    type SessionActionType,
    // Initial state
    initialSessionState,
    // Slice configuration
    sessionSlice,
    // Action creators
    sessionActions,
    // Selectors
    sessionSelectors,
} from './sessionSlice.js';

// ============================================================================
// SessionManager Exports
// ============================================================================

export { SessionManager, type SessionManagerConfig, type SessionInfo } from './SessionManager.js';
