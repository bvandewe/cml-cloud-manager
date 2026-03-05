/**
 * SessionManager unit tests
 */

import { describe, it, expect, beforeEach, afterEach, vi, type Mock } from 'vitest';
import { SessionManager, type SessionInfo, type SessionManagerConfig } from '../src/session/SessionManager.js';
import { sessionActions, sessionSelectors, initialSessionState } from '../src/session/sessionSlice.js';
import { StateStore } from '../src/core/StateStore.js';
import { EventBus } from '../src/core/EventBus.js';
import { EventTypes } from '../src/core/constants.js';
import type { SessionState, SessionUser } from '../src/session/index.js';

// Mock timers
vi.useFakeTimers();

describe('SessionManager', () => {
    let store: StateStore;
    let eventBus: EventBus;
    let sessionManager: SessionManager;
    let mockFetchSession: Mock<() => Promise<SessionInfo>>;
    let mockRefreshSession: Mock<() => Promise<Response>>;
    let mockOnLogout: Mock;
    let mockOnExpired: Mock;

    const mockUser: SessionUser = {
        id: 'user-123',
        name: 'Test User',
        email: 'test@example.com',
        roles: ['user', 'admin'],
    };

    const mockAuthenticatedSession: SessionInfo = {
        authenticated: true,
        user: {
            id: mockUser.id,
            name: mockUser.name,
            email: mockUser.email,
            roles: mockUser.roles,
        },
        expires_in_seconds: 3600, // 1 hour
    };

    const mockUnauthenticatedSession: SessionInfo = {
        authenticated: false,
    };

    function createSessionManager(overrides: Partial<SessionManagerConfig> = {}): SessionManager {
        return new SessionManager({
            store,
            eventBus,
            fetchSession: mockFetchSession,
            refreshSession: mockRefreshSession,
            onLogout: mockOnLogout,
            onExpired: mockOnExpired,
            debug: false,
            ...overrides,
        });
    }

    beforeEach(() => {
        // Reset singletons
        EventBus.resetInstance();

        // Create fresh instances
        eventBus = new EventBus({ debug: false });
        store = new StateStore({
            slices: {
                session: initialSessionState,
            },
            eventBus,
        });

        // Create mocks
        mockFetchSession = vi.fn().mockResolvedValue(mockAuthenticatedSession);
        mockRefreshSession = vi.fn().mockResolvedValue(new Response(null, { status: 200 }));
        mockOnLogout = vi.fn();
        mockOnExpired = vi.fn();

        // Create session manager
        sessionManager = createSessionManager();
    });

    afterEach(() => {
        sessionManager.stop();
        vi.clearAllTimers();
        vi.clearAllMocks();
    });

    describe('initialization', () => {
        it('should not be started by default', () => {
            expect(sessionManager.isAuthenticated()).toBe(false);
        });

        it('should fetch session on start', async () => {
            await sessionManager.start();
            expect(mockFetchSession).toHaveBeenCalledTimes(1);
        });

        it('should update state with session info on start', async () => {
            await sessionManager.start();

            expect(sessionManager.isAuthenticated()).toBe(true);
            expect(sessionManager.getUser()).toEqual(mockUser);
        });

        it('should not start twice', async () => {
            await sessionManager.start();
            await sessionManager.start();

            expect(mockFetchSession).toHaveBeenCalledTimes(1);
        });
    });

    describe('session state', () => {
        it('should return session state', async () => {
            await sessionManager.start();

            const state = sessionManager.getSessionState();
            expect(state.isAuthenticated).toBe(true);
            expect(state.user).toEqual(mockUser);
            expect(state.expiresAt).toBeGreaterThan(Date.now());
        });

        it('should check roles correctly', async () => {
            await sessionManager.start();

            expect(sessionManager.hasRole('admin')).toBe(true);
            expect(sessionManager.hasRole('user')).toBe(true);
            expect(sessionManager.hasRole('superadmin')).toBe(false);
        });

        it('should return null user when not authenticated', () => {
            expect(sessionManager.getUser()).toBeNull();
        });
    });

    describe('periodic session check', () => {
        it('should check session at configured interval', async () => {
            sessionManager = createSessionManager({ checkInterval: 30000 }); // 30 seconds

            await sessionManager.start();
            expect(mockFetchSession).toHaveBeenCalledTimes(1);

            // Advance time by 30 seconds
            vi.advanceTimersByTime(30000);
            expect(mockFetchSession).toHaveBeenCalledTimes(2);

            // Advance another 30 seconds
            vi.advanceTimersByTime(30000);
            expect(mockFetchSession).toHaveBeenCalledTimes(3);
        });

        it('should stop checking after stop()', async () => {
            sessionManager = createSessionManager({ checkInterval: 30000 });

            await sessionManager.start();
            sessionManager.stop();

            vi.advanceTimersByTime(60000);
            expect(mockFetchSession).toHaveBeenCalledTimes(1);
        });
    });

    describe('token refresh', () => {
        it('should schedule refresh before expiry', async () => {
            // Session expires in 10 minutes, refresh threshold is 5 minutes
            mockFetchSession.mockResolvedValue({
                authenticated: true,
                user: mockUser,
                expires_in_seconds: 600, // 10 minutes
            });

            sessionManager = createSessionManager({ refreshThreshold: 5 * 60 * 1000 }); // 5 minutes
            await sessionManager.start();

            // Advance to just before refresh should happen (5 minutes before expiry = 5 minutes from now)
            vi.advanceTimersByTime(4 * 60 * 1000); // 4 minutes
            expect(mockRefreshSession).not.toHaveBeenCalled();

            // Advance past the scheduled refresh time
            vi.advanceTimersByTime(2 * 60 * 1000); // 2 more minutes
            expect(mockRefreshSession).toHaveBeenCalledTimes(1);
        });

        it('should schedule refresh when expiring within threshold', async () => {
            // Session expires in 3 minutes, refresh threshold is 5 minutes
            // This means the session is already within the refresh threshold at start
            mockFetchSession.mockResolvedValue({
                authenticated: true,
                user: mockUser,
                expires_in_seconds: 180, // 3 minutes
            });

            sessionManager = createSessionManager({ refreshThreshold: 5 * 60 * 1000 });
            await sessionManager.start();

            // Since expiry (180s) < threshold (300s), refresh is scheduled for 180s from now
            // Advance time to trigger the refresh (using sync advance like the passing test above)
            vi.advanceTimersByTime(180 * 1000 + 1000);

            // The callback is sync but calls async refreshSession - give it a tick
            await Promise.resolve();
            await Promise.resolve();

            expect(mockRefreshSession).toHaveBeenCalledTimes(1);
        });

        it('should update state on successful refresh', async () => {
            await sessionManager.start();

            const result = await sessionManager.refresh();

            expect(result).toBe(true);
            expect(mockRefreshSession).toHaveBeenCalled();
        });

        it('should prevent concurrent refreshes', async () => {
            await sessionManager.start();

            // Start refresh
            store.dispatch(sessionActions.refreshStart());

            // Try to refresh again
            const result = await sessionManager.refresh();

            expect(result).toBe(false);
            expect(mockRefreshSession).not.toHaveBeenCalled();
        });

        it('should handle refresh failure', async () => {
            mockRefreshSession.mockResolvedValue(new Response(null, { status: 401 }));

            await sessionManager.start();
            const result = await sessionManager.refresh();

            expect(result).toBe(false);

            const state = sessionManager.getSessionState();
            expect(state.isRefreshing).toBe(false);
        });
    });

    describe('session expiration', () => {
        it('should handle expired session', async () => {
            mockFetchSession.mockResolvedValue({
                authenticated: true,
                user: mockUser,
                expires_in_seconds: 0, // Already expired
            });

            await sessionManager.start();

            expect(mockOnExpired).toHaveBeenCalled();
            expect(sessionManager.isAuthenticated()).toBe(false);
        });

        it('should call onLogout when onExpired not provided', async () => {
            sessionManager = createSessionManager({ onExpired: undefined });

            mockFetchSession.mockResolvedValue({
                authenticated: true,
                user: mockUser,
                expires_in_seconds: 0,
            });

            await sessionManager.start();

            expect(mockOnLogout).toHaveBeenCalled();
        });

        it('should emit AUTH_SESSION_EXPIRED event', async () => {
            const expiredHandler = vi.fn();
            eventBus.on(EventTypes.AUTH_SESSION_EXPIRED, expiredHandler);

            mockFetchSession.mockResolvedValue({
                authenticated: true,
                user: mockUser,
                expires_in_seconds: 0,
            });

            await sessionManager.start();

            expect(expiredHandler).toHaveBeenCalled();
        });
    });

    describe('inactivity timeout', () => {
        it('should logout after inactivity timeout', async () => {
            sessionManager = createSessionManager({ inactivityTimeout: 10000 }); // 10 seconds

            await sessionManager.start();
            expect(sessionManager.isAuthenticated()).toBe(true);

            // Advance past inactivity timeout and let async callback resolve
            await vi.advanceTimersByTimeAsync(15000);

            expect(mockOnLogout).toHaveBeenCalled();
        });

        it('should reset inactivity timer on activity', async () => {
            sessionManager = createSessionManager({ inactivityTimeout: 10000, activityThrottle: 1000 });

            await sessionManager.start();

            // Advance 5 seconds
            await vi.advanceTimersByTimeAsync(5000);
            expect(mockOnLogout).not.toHaveBeenCalled();

            // Record activity
            sessionManager.recordActivity();

            // Advance another 8 seconds (total 13 from start, but only 8 from activity)
            await vi.advanceTimersByTimeAsync(8000);
            expect(mockOnLogout).not.toHaveBeenCalled();

            // Advance 5 more seconds (13 from activity, past timeout)
            await vi.advanceTimersByTimeAsync(5000);
            expect(mockOnLogout).toHaveBeenCalled();
        });

        it('should disable inactivity timeout when set to 0', async () => {
            sessionManager = createSessionManager({ inactivityTimeout: 0 });

            await sessionManager.start();

            // Advance a long time
            vi.advanceTimersByTime(60 * 60 * 1000); // 1 hour

            expect(mockOnLogout).not.toHaveBeenCalled();
        });
    });

    describe('activity tracking', () => {
        it('should update lastActivity in state', async () => {
            sessionManager = createSessionManager({ activityThrottle: 100 });

            await sessionManager.start();

            const initialActivity = sessionManager.getSessionState().lastActivity;

            // Wait past throttle
            vi.advanceTimersByTime(200);
            sessionManager.recordActivity();

            const newActivity = sessionManager.getSessionState().lastActivity;
            expect(newActivity).toBeGreaterThan(initialActivity);
        });

        it('should throttle activity updates', async () => {
            sessionManager = createSessionManager({ activityThrottle: 1000 });

            await sessionManager.start();

            const initialActivity = sessionManager.getSessionState().lastActivity;

            // Record activity before throttle period ends
            vi.advanceTimersByTime(500);
            sessionManager.recordActivity();

            // Activity time should not have updated yet
            const activity = sessionManager.getSessionState().lastActivity;
            expect(activity).toBe(initialActivity);
        });
    });

    describe('logout', () => {
        it('should clear session state', async () => {
            await sessionManager.start();
            expect(sessionManager.isAuthenticated()).toBe(true);

            await sessionManager.logout();

            expect(sessionManager.isAuthenticated()).toBe(false);
            expect(sessionManager.getUser()).toBeNull();
        });

        it('should stop session manager', async () => {
            await sessionManager.start();
            await sessionManager.logout();

            // Timers should be cleared
            vi.advanceTimersByTime(60000);
            expect(mockFetchSession).toHaveBeenCalledTimes(1); // Only initial fetch
        });

        it('should emit AUTH_LOGOUT event', async () => {
            const logoutHandler = vi.fn();
            eventBus.on(EventTypes.AUTH_LOGOUT, logoutHandler);

            await sessionManager.start();
            await sessionManager.logout();

            expect(logoutHandler).toHaveBeenCalled();
        });

        it('should call onLogout callback', async () => {
            await sessionManager.start();
            await sessionManager.logout();

            expect(mockOnLogout).toHaveBeenCalled();
        });
    });

    describe('SSE event handling', () => {
        it('should handle session_expiring SSE event', async () => {
            const expiringHandler = vi.fn();
            eventBus.on(EventTypes.AUTH_SESSION_EXPIRING, expiringHandler);

            await sessionManager.start();

            // Simulate SSE event
            await eventBus.emit(EventTypes.SSE_MESSAGE, {
                type: 'session_expiring',
                data: { expires_in_seconds: 120 },
            });

            expect(expiringHandler).toHaveBeenCalled();

            const state = sessionManager.getSessionState();
            expect(state.expiresAt).toBeDefined();
        });

        it('should handle session_extended SSE event', async () => {
            const refreshedHandler = vi.fn();
            eventBus.on(EventTypes.AUTH_TOKEN_REFRESHED, refreshedHandler);

            await sessionManager.start();

            // Simulate SSE event
            await eventBus.emit(EventTypes.SSE_MESSAGE, {
                type: 'session_extended',
                data: { expires_in_seconds: 3600 },
            });

            expect(refreshedHandler).toHaveBeenCalled();
        });

        it('should handle session_expired SSE event', async () => {
            await sessionManager.start();
            expect(sessionManager.isAuthenticated()).toBe(true);

            // Simulate SSE event
            await eventBus.emit(EventTypes.SSE_MESSAGE, {
                type: 'session_expired',
            });

            // Wait for async handling
            await vi.runAllTimersAsync();

            expect(mockOnExpired).toHaveBeenCalled();
        });
    });

    describe('stop', () => {
        it('should clear all timers', async () => {
            sessionManager = createSessionManager({ checkInterval: 1000 });

            await sessionManager.start();
            sessionManager.stop();

            // Advance time - should not trigger any callbacks
            vi.advanceTimersByTime(10000);

            expect(mockFetchSession).toHaveBeenCalledTimes(1);
        });

        it('should unsubscribe from events', async () => {
            await sessionManager.start();
            sessionManager.stop();

            // SSE events should not be handled
            await eventBus.emit(EventTypes.SSE_MESSAGE, {
                type: 'session_expired',
            });

            await vi.runAllTimersAsync();

            // Should not have expired (was already stopped)
            expect(mockOnExpired).not.toHaveBeenCalled();
        });

        it('should be safe to call multiple times', () => {
            sessionManager.stop();
            sessionManager.stop();
            sessionManager.stop();
            // No error should occur
        });
    });

    describe('error handling', () => {
        it('should handle fetchSession errors gracefully', async () => {
            mockFetchSession.mockRejectedValue(new Error('Network error'));

            await sessionManager.start();

            // Should not throw, just log
            expect(sessionManager.isAuthenticated()).toBe(false);
        });

        it('should handle refreshSession errors gracefully', async () => {
            await sessionManager.start();

            mockRefreshSession.mockRejectedValue(new Error('Refresh failed'));

            const result = await sessionManager.refresh();

            expect(result).toBe(false);
            expect(sessionManager.getSessionState().isRefreshing).toBe(false);
        });
    });
});

describe('sessionSlice', () => {
    describe('action creators', () => {
        it('should create init action', () => {
            const action = sessionActions.init();
            expect(action.type).toBe('session/init');
            expect(action.payload).toEqual(initialSessionState);
        });

        it('should create login action', () => {
            const user: SessionUser = {
                id: '123',
                name: 'Test',
                email: 'test@test.com',
                roles: ['user'],
            };
            const expiresAt = Date.now() + 3600000;

            const action = sessionActions.login(user, expiresAt);

            expect(action.type).toBe('session/login');
            expect(action.payload.isAuthenticated).toBe(true);
            expect(action.payload.user).toEqual(user);
            expect(action.payload.expiresAt).toBe(expiresAt);
        });

        it('should create logout action', () => {
            const action = sessionActions.logout();
            expect(action.type).toBe('session/logout');
            expect(action.payload.isAuthenticated).toBe(false);
        });

        it('should create update action with partial flag', () => {
            const action = sessionActions.update({ isRefreshing: true });
            expect(action.type).toBe('session/update');
            expect(action.meta?.partial).toBe(true);
        });

        it('should create activity action with current timestamp', () => {
            const before = Date.now();
            const action = sessionActions.activity();
            const after = Date.now();

            expect(action.type).toBe('session/activity');
            expect(action.payload.lastActivity).toBeGreaterThanOrEqual(before);
            expect(action.payload.lastActivity).toBeLessThanOrEqual(after);
        });
    });

    describe('selectors', () => {
        const mockState: Record<string, unknown> = {
            session: {
                isAuthenticated: true,
                user: { id: '1', name: 'Test', email: 'test@test.com', roles: ['admin'] },
                expiresAt: Date.now() + 300000, // 5 minutes
                isRefreshing: false,
                lastActivity: Date.now(),
            } satisfies SessionState,
        };

        it('should select full session', () => {
            const session = sessionSelectors.selectSession(mockState);
            expect(session.isAuthenticated).toBe(true);
        });

        it('should select isAuthenticated', () => {
            expect(sessionSelectors.selectIsAuthenticated(mockState)).toBe(true);
        });

        it('should select user', () => {
            const user = sessionSelectors.selectUser(mockState);
            expect(user?.name).toBe('Test');
        });

        it('should select user roles', () => {
            const roles = sessionSelectors.selectUserRoles(mockState);
            expect(roles).toContain('admin');
        });

        it('should check hasRole', () => {
            expect(sessionSelectors.selectHasRole(mockState, 'admin')).toBe(true);
            expect(sessionSelectors.selectHasRole(mockState, 'superuser')).toBe(false);
        });

        it('should select time until expiry', () => {
            const time = sessionSelectors.selectTimeUntilExpiry(mockState);
            expect(time).toBeGreaterThan(0);
            expect(time).toBeLessThanOrEqual(300000);
        });

        it('should detect expiring soon', () => {
            // 5 minutes until expiry, 10 minute threshold
            expect(sessionSelectors.selectIsExpiringSoon(mockState, 10 * 60 * 1000)).toBe(true);

            // 5 minutes until expiry, 3 minute threshold
            expect(sessionSelectors.selectIsExpiringSoon(mockState, 3 * 60 * 1000)).toBe(false);
        });

        it('should return defaults for missing state', () => {
            const emptyState: Record<string, unknown> = {};

            expect(sessionSelectors.selectIsAuthenticated(emptyState)).toBe(false);
            expect(sessionSelectors.selectUser(emptyState)).toBeNull();
            expect(sessionSelectors.selectUserRoles(emptyState)).toEqual([]);
        });
    });
});
