/**
 * Logger Middleware
 *
 * Logs state changes to the console with optional diffs.
 *
 * @example
 * ```typescript
 * import { StateStore, createLoggerMiddleware } from '@neuroglia/ui-core';
 *
 * const store = new StateStore({
 *   slices: { counter: { value: 0 } },
 *   middleware: [
 *     createLoggerMiddleware({ collapsed: true, diff: true })
 *   ]
 * });
 * ```
 *
 * @module middleware
 */

import type { StoreMiddleware, StoreAction, StoreAPI } from '../types/store.js';

/**
 * Logger middleware options
 */
export interface LoggerOptions {
    /** Whether logging is enabled (default: true) */
    enabled?: boolean;
    /** Whether to log state diffs (default: false) */
    diff?: boolean;
    /** Whether to collapse console groups (default: true) */
    collapsed?: boolean;
    /** Custom logger (default: console) */
    logger?: Pick<Console, 'log' | 'group' | 'groupCollapsed' | 'groupEnd'>;
    /** Action types to ignore */
    ignoredActions?: string[];
    /** Custom action formatter */
    actionFormatter?: (action: StoreAction) => string;
    /** Whether to log timestamps (default: true) */
    timestamp?: boolean;
    /** Color theme for console output */
    colors?: {
        title?: string;
        prevState?: string;
        action?: string;
        nextState?: string;
        diff?: string;
    };
}

/**
 * Default logger options
 */
const DEFAULT_OPTIONS: Required<Omit<LoggerOptions, 'actionFormatter'>> & { actionFormatter?: (action: StoreAction) => string } = {
    enabled: true,
    diff: false,
    collapsed: true,
    logger: console,
    ignoredActions: [],
    timestamp: true,
    colors: {
        title: '#888',
        prevState: '#9E9E9E',
        action: '#03A9F4',
        nextState: '#4CAF50',
        diff: '#E8A400',
    },
};

/**
 * Create a simple object diff
 */
function createDiff(prevState: Record<string, unknown>, nextState: Record<string, unknown>): Record<string, { prev: unknown; next: unknown }> {
    const diff: Record<string, { prev: unknown; next: unknown }> = {};
    const allKeys = new Set([...Object.keys(prevState), ...Object.keys(nextState)]);

    for (const key of allKeys) {
        const prev = prevState[key];
        const next = nextState[key];

        if (!Object.is(prev, next)) {
            diff[key] = { prev, next };
        }
    }

    return diff;
}

/**
 * Format timestamp
 */
function formatTimestamp(): string {
    const now = new Date();
    return `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}.${now.getMilliseconds().toString().padStart(3, '0')}`;
}

/**
 * Create logger middleware
 *
 * @param options - Logger options
 * @returns Middleware function
 */
export function createLoggerMiddleware(options: LoggerOptions = {}): StoreMiddleware {
    const config = { ...DEFAULT_OPTIONS, ...options };

    return (store: StoreAPI) => next => (action: StoreAction) => {
        // Skip if disabled or action is ignored
        if (!config.enabled || config.ignoredActions.includes(action.type)) {
            return next(action);
        }

        const prevState = store.getState();
        const startTime = performance.now();

        // Execute action
        const result = next(action);

        const nextState = store.getState();
        const duration = performance.now() - startTime;

        // Format title
        const timestamp = config.timestamp ? ` @ ${formatTimestamp()}` : '';
        const title = config.actionFormatter ? config.actionFormatter(action) : `action ${action.type}${timestamp} (${duration.toFixed(2)}ms)`;

        // Log group
        const groupMethod = config.collapsed ? 'groupCollapsed' : 'group';
        config.logger[groupMethod](`%c${title}`, `color: ${config.colors.title}; font-weight: bold;`);

        // Log prev state
        config.logger.log(`%cprev state`, `color: ${config.colors.prevState}; font-weight: bold;`, prevState);

        // Log action
        config.logger.log(`%caction    `, `color: ${config.colors.action}; font-weight: bold;`, action);

        // Log next state
        config.logger.log(`%cnext state`, `color: ${config.colors.nextState}; font-weight: bold;`, nextState);

        // Log diff if enabled
        if (config.diff) {
            const stateDiff = createDiff(prevState, nextState);
            if (Object.keys(stateDiff).length > 0) {
                config.logger.log(`%cdiff      `, `color: ${config.colors.diff}; font-weight: bold;`, stateDiff);
            }
        }

        config.logger.groupEnd();

        return result;
    };
}

/**
 * Pre-configured logger middleware with sensible defaults
 */
export const loggerMiddleware = createLoggerMiddleware();
