/**
 * Session Slice - State definition for authentication session
 *
 * Provides the initial state, action types, and helper functions
 * for managing session state in the StateStore.
 *
 * @module session
 */

import type { SessionState, SessionUser } from './index.js';

/**
 * Session action types
 */
export const SessionActionTypes = {
    /** Initialize session (first load) */
    INIT: 'session/init',
    /** User logged in successfully */
    LOGIN: 'session/login',
    /** User logged out */
    LOGOUT: 'session/logout',
    /** Session data updated */
    UPDATE: 'session/update',
    /** Token refresh started */
    REFRESH_START: 'session/refreshStart',
    /** Token refresh completed */
    REFRESH_SUCCESS: 'session/refreshSuccess',
    /** Token refresh failed */
    REFRESH_FAILURE: 'session/refreshFailure',
    /** Session expired */
    EXPIRED: 'session/expired',
    /** User activity recorded */
    ACTIVITY: 'session/activity',
    /** Set session from external source (e.g., SSE) */
    SET: 'session/set',
} as const;

/**
 * Type for session action type values
 */
export type SessionActionType = (typeof SessionActionTypes)[keyof typeof SessionActionTypes];

/**
 * Initial session state (unauthenticated)
 */
export const initialSessionState: SessionState = {
    isAuthenticated: false,
    user: null,
    expiresAt: null,
    isRefreshing: false,
    lastActivity: Date.now(),
};

/**
 * Session slice configuration for StateStore
 */
export const sessionSlice = {
    name: 'session',
    initialState: initialSessionState,
} as const;

/**
 * Session action creators
 */
export const sessionActions = {
    /**
     * Initialize session state
     */
    init: () => ({
        type: SessionActionTypes.INIT,
        payload: initialSessionState,
        meta: { slice: 'session' },
    }),

    /**
     * Log in user
     */
    login: (user: SessionUser, expiresAt: number) => ({
        type: SessionActionTypes.LOGIN,
        payload: {
            isAuthenticated: true,
            user,
            expiresAt,
            isRefreshing: false,
            lastActivity: Date.now(),
        } satisfies SessionState,
        meta: { slice: 'session' },
    }),

    /**
     * Log out user
     */
    logout: () => ({
        type: SessionActionTypes.LOGOUT,
        payload: initialSessionState,
        meta: { slice: 'session' },
    }),

    /**
     * Update session data (partial update)
     */
    update: (updates: Partial<SessionState>) => ({
        type: SessionActionTypes.UPDATE,
        payload: updates,
        meta: { slice: 'session', partial: true },
    }),

    /**
     * Start token refresh
     */
    refreshStart: () => ({
        type: SessionActionTypes.REFRESH_START,
        payload: { isRefreshing: true },
        meta: { slice: 'session', partial: true },
    }),

    /**
     * Token refresh succeeded
     */
    refreshSuccess: (expiresAt: number) => ({
        type: SessionActionTypes.REFRESH_SUCCESS,
        payload: { isRefreshing: false, expiresAt },
        meta: { slice: 'session', partial: true },
    }),

    /**
     * Token refresh failed
     */
    refreshFailure: () => ({
        type: SessionActionTypes.REFRESH_FAILURE,
        payload: { isRefreshing: false },
        meta: { slice: 'session', partial: true },
    }),

    /**
     * Session expired
     */
    expired: () => ({
        type: SessionActionTypes.EXPIRED,
        payload: {
            isAuthenticated: false,
            user: null,
            expiresAt: null,
            isRefreshing: false,
        },
        meta: { slice: 'session', partial: true },
    }),

    /**
     * Record user activity
     */
    activity: () => ({
        type: SessionActionTypes.ACTIVITY,
        payload: { lastActivity: Date.now() },
        meta: { slice: 'session', partial: true },
    }),

    /**
     * Set full session state (from external source)
     */
    set: (session: SessionState) => ({
        type: SessionActionTypes.SET,
        payload: session,
        meta: { slice: 'session' },
    }),
};

/**
 * Session selectors
 */
export const sessionSelectors = {
    /**
     * Select the full session state
     */
    selectSession: (state: Record<string, unknown>): SessionState => {
        return (state.session as SessionState) ?? initialSessionState;
    },

    /**
     * Select whether user is authenticated
     */
    selectIsAuthenticated: (state: Record<string, unknown>): boolean => {
        const session = state.session as SessionState | undefined;
        return session?.isAuthenticated ?? false;
    },

    /**
     * Select the current user
     */
    selectUser: (state: Record<string, unknown>): SessionUser | null => {
        const session = state.session as SessionState | undefined;
        return session?.user ?? null;
    },

    /**
     * Select session expiration timestamp
     */
    selectExpiresAt: (state: Record<string, unknown>): number | null => {
        const session = state.session as SessionState | undefined;
        return session?.expiresAt ?? null;
    },

    /**
     * Select whether token refresh is in progress
     */
    selectIsRefreshing: (state: Record<string, unknown>): boolean => {
        const session = state.session as SessionState | undefined;
        return session?.isRefreshing ?? false;
    },

    /**
     * Select last activity timestamp
     */
    selectLastActivity: (state: Record<string, unknown>): number => {
        const session = state.session as SessionState | undefined;
        return session?.lastActivity ?? Date.now();
    },

    /**
     * Select time until session expires (ms)
     */
    selectTimeUntilExpiry: (state: Record<string, unknown>): number | null => {
        const session = state.session as SessionState | undefined;
        if (!session?.expiresAt) return null;
        return Math.max(0, session.expiresAt - Date.now());
    },

    /**
     * Select whether session is expiring soon (within threshold)
     */
    selectIsExpiringSoon: (state: Record<string, unknown>, thresholdMs: number = 5 * 60 * 1000): boolean => {
        const timeUntilExpiry = sessionSelectors.selectTimeUntilExpiry(state);
        if (timeUntilExpiry === null) return false;
        return timeUntilExpiry <= thresholdMs && timeUntilExpiry > 0;
    },

    /**
     * Select user roles
     */
    selectUserRoles: (state: Record<string, unknown>): string[] => {
        const user = sessionSelectors.selectUser(state);
        return user?.roles ?? [];
    },

    /**
     * Check if user has a specific role
     */
    selectHasRole: (state: Record<string, unknown>, role: string): boolean => {
        const roles = sessionSelectors.selectUserRoles(state);
        return roles.includes(role);
    },
};
