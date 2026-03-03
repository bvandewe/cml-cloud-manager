# UI Modularization Architecture

> **Status**: Design Phase
> **Created**: 2026-01-20
> **Authors**: AI-assisted design session
> **Related**: [Frontend State Management](./frontend-state-management.md)

## Overview

This document describes the architecture for modularizing the LCM frontend into a reusable npm package (`@neuroglia/ui-core`) and addresses critical concerns around memory management, session handling, and build/publish workflows.

---

## Part 1: Memory Management & Immutable State

### 1.1 Why Immutable State (Spread Operator)?

**Rationale:**

| Benefit | Description |
|---------|-------------|
| **Change Detection** | Shallow comparison (`===`) is O(1) vs deep comparison O(n) |
| **Time-Travel Debugging** | Each state snapshot is independent |
| **Predictable Updates** | No accidental mutations; state flows one direction |
| **Framework Compatibility** | React, Vue, and others optimize based on reference changes |
| **Safer Concurrency** | Immutable objects can be safely passed across async boundaries |

**Memory Concern:** Yes, creating new objects uses more memory, but modern JavaScript engines are highly optimized for short-lived objects.

### 1.2 Memory Safety Strategy

The StateStore implements several strategies to prevent memory issues:

```javascript
/**
 * Memory-safe StateStore Configuration
 */
class StateStore {
    constructor(options = {}) {
        // === Memory Limits ===
        this._maxHistorySize = options.maxHistorySize ?? 50;     // State snapshots
        this._maxEventHistory = options.maxEventHistory ?? 100;   // Event log entries
        this._gcIntervalMs = options.gcIntervalMs ?? 60000;       // GC check interval

        // === State ===
        this._state = this._deepClone(options.slices || {});
        this._stateHistory = [];  // For time-travel (limited size)

        // === Subscriptions with WeakRef ===
        this._subscribers = new Map();      // slice -> WeakSet<callback>
        this._weakSubscribers = new Map();  // slice -> Set<WeakRef<callback>>

        // === Start periodic GC ===
        if (options.enableGC !== false) {
            this._startGarbageCollection();
        }
    }

    // ==================== Memory Management ====================

    /**
     * Periodically clean up stale WeakRefs and trim history
     */
    _startGarbageCollection() {
        this._gcInterval = setInterval(() => {
            this._cleanupWeakRefs();
            this._trimHistory();
            this._logMemoryStats();
        }, this._gcIntervalMs);
    }

    /**
     * Clean up dead WeakRefs
     */
    _cleanupWeakRefs() {
        for (const [slice, refs] of this._weakSubscribers) {
            for (const ref of refs) {
                if (ref.deref() === undefined) {
                    refs.delete(ref);
                }
            }
        }
    }

    /**
     * Trim state history to max size
     */
    _trimHistory() {
        while (this._stateHistory.length > this._maxHistorySize) {
            this._stateHistory.shift();
        }
    }

    /**
     * Log memory statistics (debug mode)
     */
    _logMemoryStats() {
        if (!this._options?.debug) return;

        const stats = {
            historySize: this._stateHistory.length,
            subscriberCount: this._countSubscribers(),
            stateSlices: Object.keys(this._state).length
        };

        console.debug('[StateStore] Memory stats:', stats);
    }

    /**
     * Force garbage collection and return memory report
     */
    gc() {
        this._cleanupWeakRefs();
        this._trimHistory();

        return {
            historySize: this._stateHistory.length,
            maxHistory: this._maxHistorySize,
            subscriberCount: this._countSubscribers()
        };
    }

    /**
     * Destroy the store (cleanup for SPA navigation)
     */
    destroy() {
        if (this._gcInterval) {
            clearInterval(this._gcInterval);
        }
        this._subscribers.clear();
        this._weakSubscribers.clear();
        this._stateHistory = [];
        this._state = {};
    }
}
```

### 1.3 SSE Event Memory Strategy

**Problem:** SSE events arrive continuously. Storing all of them would cause memory leaks.

**Solution:** Ring buffer with configurable size + event deduplication.

```javascript
/**
 * SSE Event Buffer - Ring buffer with deduplication
 */
class SSEEventBuffer {
    constructor(options = {}) {
        this._maxSize = options.maxSize ?? 1000;       // Max events to keep
        this._dedupeWindowMs = options.dedupeWindowMs ?? 1000;  // Dedupe window
        this._buffer = [];
        this._dedupeMap = new Map();  // hash -> timestamp
    }

    /**
     * Add event to buffer with deduplication
     * @returns {boolean} true if event was added (not duplicate)
     */
    push(event) {
        const hash = this._hashEvent(event);
        const now = Date.now();

        // Check for duplicate within window
        const lastSeen = this._dedupeMap.get(hash);
        if (lastSeen && (now - lastSeen) < this._dedupeWindowMs) {
            return false;  // Duplicate, skip
        }

        // Add to buffer
        this._buffer.push({
            ...event,
            _receivedAt: now,
            _hash: hash
        });

        // Update dedupe map
        this._dedupeMap.set(hash, now);

        // Trim if over size
        while (this._buffer.length > this._maxSize) {
            const removed = this._buffer.shift();
            this._dedupeMap.delete(removed._hash);
        }

        // Cleanup old dedupe entries periodically
        if (this._buffer.length % 100 === 0) {
            this._cleanupDedupeMap(now);
        }

        return true;
    }

    /**
     * Get recent events
     */
    getRecent(count = 50) {
        return this._buffer.slice(-count);
    }

    /**
     * Get events since timestamp
     */
    getSince(timestamp) {
        return this._buffer.filter(e => e._receivedAt >= timestamp);
    }

    /**
     * Clear all events
     */
    clear() {
        this._buffer = [];
        this._dedupeMap.clear();
    }

    /**
     * Get buffer statistics
     */
    getStats() {
        return {
            size: this._buffer.length,
            maxSize: this._maxSize,
            oldestEvent: this._buffer[0]?._receivedAt,
            newestEvent: this._buffer[this._buffer.length - 1]?._receivedAt
        };
    }

    // Private methods

    _hashEvent(event) {
        // Create hash from event type and key identifying fields
        const key = `${event.type}:${event.data?.id || event.data?.worker_id || ''}`;
        return key;
    }

    _cleanupDedupeMap(now) {
        for (const [hash, timestamp] of this._dedupeMap) {
            if (now - timestamp > this._dedupeWindowMs * 2) {
                this._dedupeMap.delete(hash);
            }
        }
    }
}
```

### 1.4 Memory Leak Prevention Checklist

| Source | Prevention Strategy |
|--------|---------------------|
| **Event subscriptions** | Always return unsubscribe function; cleanup on component unmount |
| **SSE event history** | Ring buffer with max size (default 1000) |
| **State history** | Limited snapshots (default 50) for time-travel |
| **Selector cache** | LRU cache with size limit |
| **WeakRefs** | Periodic cleanup of dead references |
| **Timers** | Clear intervals/timeouts on destroy() |
| **DOM references** | BaseComponent cleanup() clears all refs |

---

## Part 2: Session Management

### 2.1 Session Slice

The StateStore includes a dedicated `session` slice for authentication state:

```javascript
/**
 * Session Slice - Manages user authentication state
 */
export const sessionSlice = {
    name: 'session',

    initialState: {
        user: null,                    // UserInfo object
        accessToken: null,             // JWT access token (for API calls)
        refreshToken: null,            // Refresh token (stored securely)
        expiresAt: null,               // Token expiration timestamp
        isAuthenticated: false,
        isRefreshing: false,           // Token refresh in progress
        lastActivity: null,            // Last user interaction timestamp

        // Session settings
        settings: {
            inactivityTimeoutMs: 30 * 60 * 1000,  // 30 minutes
            tokenRefreshBufferMs: 5 * 60 * 1000,  // Refresh 5 min before expiry
            enableAutoLogout: true
        }
    }
};
```

### 2.2 Session Manager

```javascript
/**
 * SessionManager - Handles token refresh and automatic logout
 *
 * Features:
 * - Automatic token refresh before expiration
 * - Inactivity-based logout
 * - SSE-triggered session invalidation
 * - Secure token storage (httpOnly cookies preferred)
 */
class SessionManager {
    constructor(options) {
        this._store = options.store;
        this._eventBus = options.eventBus;
        this._authApi = options.authApi;  // Auth API client

        this._refreshTimer = null;
        this._inactivityTimer = null;
        this._activityListeners = [];

        // Listen for SSE session events
        this._eventBus.on('auth.session.expired', () => this._handleSessionExpired());
        this._eventBus.on('auth.token.refreshed', (data) => this._handleTokenRefreshed(data));

        // Start activity tracking
        this._setupActivityTracking();
    }

    /**
     * Initialize session from stored tokens or cookies
     */
    async initialize() {
        const session = this._store.getState('session');

        // Check if we have a valid session
        if (session.accessToken && session.expiresAt) {
            const now = Date.now();

            if (session.expiresAt > now) {
                // Token still valid
                this._scheduleRefresh(session.expiresAt);
                this._startInactivityTimer();
                return true;
            } else if (session.refreshToken) {
                // Token expired, try refresh
                return await this.refreshTokens();
            }
        }

        // No valid session, try to restore from server (cookie-based)
        try {
            const response = await this._authApi.getSession();
            if (response.user) {
                this._store.mergeState('session', {
                    user: response.user,
                    isAuthenticated: true,
                    expiresAt: response.expiresAt,
                    lastActivity: Date.now()
                });
                this._scheduleRefresh(response.expiresAt);
                this._startInactivityTimer();
                return true;
            }
        } catch (error) {
            console.debug('[SessionManager] No existing session');
        }

        return false;
    }

    /**
     * Refresh tokens before they expire
     */
    async refreshTokens() {
        const session = this._store.getState('session');

        if (session.isRefreshing) {
            console.debug('[SessionManager] Refresh already in progress');
            return;
        }

        this._store.mergeState('session', { isRefreshing: true });

        try {
            const response = await this._authApi.refreshToken();

            this._store.mergeState('session', {
                accessToken: response.accessToken,
                refreshToken: response.refreshToken,
                expiresAt: response.expiresAt,
                isRefreshing: false,
                lastActivity: Date.now()
            });

            this._scheduleRefresh(response.expiresAt);
            this._eventBus.emit('session.refreshed', { expiresAt: response.expiresAt });

            return true;

        } catch (error) {
            console.error('[SessionManager] Token refresh failed:', error);

            this._store.mergeState('session', { isRefreshing: false });

            // If refresh fails, trigger logout
            if (error.status === 401 || error.status === 403) {
                await this.logout('session_expired');
            }

            return false;
        }
    }

    /**
     * Logout user
     */
    async logout(reason = 'user_initiated') {
        this._clearTimers();

        try {
            await this._authApi.logout();
        } catch (error) {
            console.warn('[SessionManager] Logout API call failed:', error);
        }

        // Clear session state
        this._store.setState('session', {
            ...sessionSlice.initialState,
            settings: this._store.getState('session').settings
        });

        // Emit logout event
        this._eventBus.emit('session.logout', { reason });

        // Redirect to login
        if (reason === 'session_expired' || reason === 'inactivity') {
            window.location.href = '/api/auth/login?reason=' + reason;
        }
    }

    /**
     * Update last activity timestamp
     */
    recordActivity() {
        this._store.mergeState('session', { lastActivity: Date.now() });
        this._resetInactivityTimer();
    }

    // ==================== Private Methods ====================

    _scheduleRefresh(expiresAt) {
        if (this._refreshTimer) {
            clearTimeout(this._refreshTimer);
        }

        const session = this._store.getState('session');
        const refreshAt = expiresAt - session.settings.tokenRefreshBufferMs;
        const delay = Math.max(0, refreshAt - Date.now());

        console.debug(`[SessionManager] Scheduling refresh in ${delay}ms`);

        this._refreshTimer = setTimeout(() => {
            this.refreshTokens();
        }, delay);
    }

    _startInactivityTimer() {
        const session = this._store.getState('session');

        if (!session.settings.enableAutoLogout) return;

        this._resetInactivityTimer();
    }

    _resetInactivityTimer() {
        if (this._inactivityTimer) {
            clearTimeout(this._inactivityTimer);
        }

        const session = this._store.getState('session');

        if (!session.settings.enableAutoLogout) return;

        this._inactivityTimer = setTimeout(() => {
            this._handleInactivityTimeout();
        }, session.settings.inactivityTimeoutMs);
    }

    _handleInactivityTimeout() {
        console.warn('[SessionManager] Inactivity timeout');
        this.logout('inactivity');
    }

    _handleSessionExpired() {
        console.warn('[SessionManager] Session expired (SSE event)');
        this.logout('session_expired');
    }

    _handleTokenRefreshed(data) {
        // Server pushed new token via SSE
        this._store.mergeState('session', {
            accessToken: data.accessToken,
            expiresAt: data.expiresAt
        });
        this._scheduleRefresh(data.expiresAt);
    }

    _setupActivityTracking() {
        const events = ['mousedown', 'keydown', 'touchstart', 'scroll'];

        // Throttled activity handler
        let lastActivity = 0;
        const throttleMs = 5000;

        const handler = () => {
            const now = Date.now();
            if (now - lastActivity > throttleMs) {
                lastActivity = now;
                this.recordActivity();
            }
        };

        events.forEach(event => {
            document.addEventListener(event, handler, { passive: true });
            this._activityListeners.push({ event, handler });
        });
    }

    _clearTimers() {
        if (this._refreshTimer) {
            clearTimeout(this._refreshTimer);
            this._refreshTimer = null;
        }
        if (this._inactivityTimer) {
            clearTimeout(this._inactivityTimer);
            this._inactivityTimer = null;
        }
    }

    destroy() {
        this._clearTimers();

        // Remove activity listeners
        this._activityListeners.forEach(({ event, handler }) => {
            document.removeEventListener(event, handler);
        });
        this._activityListeners = [];
    }
}
```

### 2.3 Session Integration with SSE

```javascript
// In sseAdapter.js - Wire session events
eventBus.on('sse.connected', () => {
    // SSE connected, session is valid
    store.mergeState('session', { lastActivity: Date.now() });
});

eventBus.on('auth.session.expired', () => {
    // Server says session expired
    sessionManager.logout('session_expired');
});

eventBus.on('sse.error', (data) => {
    // Check if it's an auth error
    if (data.error?.status === 401) {
        sessionManager.logout('session_expired');
    }
});
```

---

## Part 3: Package Structure (`@neuroglia/ui-core`)

### 3.1 Location in Monorepo

```
src/
└── core/
    ├── lcm_core/          # Python shared package (existing)
    ├── lcm_ui/            # JavaScript shared package (NEW)
    │   ├── package.json
    │   ├── rollup.config.js
    │   ├── tsconfig.json
    │   ├── src/
    │   │   ├── index.ts           # Main entry point
    │   │   ├── core/
    │   │   │   ├── EventBus.ts
    │   │   │   ├── StateStore.ts
    │   │   │   ├── SSEClient.ts
    │   │   │   ├── SSEEventBuffer.ts
    │   │   │   ├── BaseComponent.ts
    │   │   │   └── index.ts
    │   │   ├── session/
    │   │   │   ├── SessionManager.ts
    │   │   │   ├── sessionSlice.ts
    │   │   │   └── index.ts
    │   │   ├── middleware/
    │   │   │   ├── logger.ts
    │   │   │   ├── devtools.ts
    │   │   │   ├── throttle.ts
    │   │   │   ├── persist.ts
    │   │   │   └── index.ts
    │   │   └── types/
    │   │       ├── events.ts
    │   │       ├── store.ts
    │   │       └── index.ts
    │   ├── dist/              # Build output
    │   │   ├── index.js       # UMD bundle
    │   │   ├── index.esm.js   # ES module
    │   │   ├── index.d.ts     # TypeScript declarations
    │   │   └── ...
    │   └── tests/
    │       ├── EventBus.test.ts
    │       ├── StateStore.test.ts
    │       └── ...
    └── pyproject.toml     # Existing (Python only)
```

### 3.2 Package Configuration

```json
// src/core/lcm_ui/package.json
{
    "name": "@neuroglia/ui-core",
    "version": "0.1.0",
    "description": "Generic UI core classes for state management, events, and SSE",
    "author": "Neuroglia Team",
    "license": "MIT",

    "main": "dist/index.js",
    "module": "dist/index.esm.js",
    "types": "dist/index.d.ts",
    "exports": {
        ".": {
            "import": "./dist/index.esm.js",
            "require": "./dist/index.js",
            "types": "./dist/index.d.ts"
        },
        "./core": {
            "import": "./dist/core/index.esm.js",
            "require": "./dist/core/index.js",
            "types": "./dist/core/index.d.ts"
        },
        "./session": {
            "import": "./dist/session/index.esm.js",
            "require": "./dist/session/index.js",
            "types": "./dist/session/index.d.ts"
        },
        "./middleware": {
            "import": "./dist/middleware/index.esm.js",
            "require": "./dist/middleware/index.js",
            "types": "./dist/middleware/index.d.ts"
        }
    },

    "files": [
        "dist",
        "README.md"
    ],

    "scripts": {
        "build": "rollup -c",
        "build:watch": "rollup -c -w",
        "test": "vitest run",
        "test:watch": "vitest",
        "test:coverage": "vitest run --coverage",
        "lint": "eslint src --ext .ts",
        "typecheck": "tsc --noEmit",
        "clean": "rm -rf dist",
        "prepublishOnly": "npm run clean && npm run build"
    },

    "devDependencies": {
        "@rollup/plugin-node-resolve": "^15.0.0",
        "@rollup/plugin-typescript": "^11.0.0",
        "@types/node": "^20.0.0",
        "eslint": "^8.0.0",
        "rollup": "^4.0.0",
        "rollup-plugin-dts": "^6.0.0",
        "tslib": "^2.6.0",
        "typescript": "^5.0.0",
        "vitest": "^1.0.0"
    },

    "peerDependencies": {},

    "engines": {
        "node": ">=18.0.0"
    },

    "keywords": [
        "state-management",
        "event-bus",
        "sse",
        "web-components",
        "neuroglia"
    ]
}
```

### 3.3 Rollup Configuration

```javascript
// src/core/lcm_ui/rollup.config.js
import resolve from '@rollup/plugin-node-resolve';
import typescript from '@rollup/plugin-typescript';
import dts from 'rollup-plugin-dts';

const external = [];  // No external dependencies for core

export default [
    // Main bundle (UMD + ESM)
    {
        input: 'src/index.ts',
        output: [
            {
                file: 'dist/index.js',
                format: 'umd',
                name: 'NeurogliaUICore',
                sourcemap: true
            },
            {
                file: 'dist/index.esm.js',
                format: 'esm',
                sourcemap: true
            }
        ],
        plugins: [
            resolve(),
            typescript({ tsconfig: './tsconfig.json' })
        ],
        external
    },

    // Type declarations
    {
        input: 'src/index.ts',
        output: {
            file: 'dist/index.d.ts',
            format: 'esm'
        },
        plugins: [dts()]
    },

    // Subpath exports (core, session, middleware)
    ...['core', 'session', 'middleware'].map(subpath => ({
        input: `src/${subpath}/index.ts`,
        output: [
            {
                file: `dist/${subpath}/index.js`,
                format: 'umd',
                name: `NeurogliaUICore_${subpath}`,
                sourcemap: true
            },
            {
                file: `dist/${subpath}/index.esm.js`,
                format: 'esm',
                sourcemap: true
            }
        ],
        plugins: [
            resolve(),
            typescript({ tsconfig: './tsconfig.json' })
        ],
        external
    }))
];
```

### 3.4 TypeScript Configuration

```json
// src/core/lcm_ui/tsconfig.json
{
    "compilerOptions": {
        "target": "ES2020",
        "module": "ESNext",
        "moduleResolution": "bundler",
        "lib": ["ES2020", "DOM", "DOM.Iterable"],
        "strict": true,
        "declaration": true,
        "declarationDir": "dist",
        "outDir": "dist",
        "rootDir": "src",
        "esModuleInterop": true,
        "skipLibCheck": true,
        "forceConsistentCasingInFileNames": true,
        "resolveJsonModule": true,
        "isolatedModules": true,
        "noEmit": false,
        "sourceMap": true
    },
    "include": ["src/**/*"],
    "exclude": ["node_modules", "dist", "tests"]
}
```

---

## Part 4: Build & Publish Workflow

### 4.1 Makefile Updates

```makefile
# src/core/Makefile (NEW - for both lcm_core and lcm_ui)

.PHONY: help install build test lint clean publish-local

# Colors
BLUE := \033[0;34m
GREEN := \033[0;32m
NC := \033[0m

.DEFAULT_GOAL := help

##@ General

help: ## Display this help
 @awk 'BEGIN {FS = ":.*##"; printf "Usage: make $(GREEN)<target>$(NC)\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  $(GREEN)%-20s$(NC) %s\n", $$1, $$2 } /^##@/ { printf "\n%s\n", substr($$0, 5) }' $(MAKEFILE_LIST)

##@ Python (lcm_core)

install-python: ## Install Python dependencies
 @echo "$(BLUE)Installing lcm_core Python dependencies...$(NC)"
 poetry install

test-python: ## Run Python tests
 @echo "$(BLUE)Running lcm_core tests...$(NC)"
 poetry run pytest tests/ -v

lint-python: ## Lint Python code
 @echo "$(BLUE)Linting lcm_core...$(NC)"
 poetry run ruff check lcm_core
 poetry run black --check lcm_core

##@ JavaScript (lcm_ui)

install-ui: ## Install JavaScript dependencies
 @echo "$(BLUE)Installing lcm_ui dependencies...$(NC)"
 cd lcm_ui && npm ci

build-ui: ## Build lcm_ui package
 @echo "$(BLUE)Building lcm_ui...$(NC)"
 cd lcm_ui && npm run build
 @echo "$(GREEN)lcm_ui built successfully!$(NC)"

test-ui: ## Run JavaScript tests
 @echo "$(BLUE)Running lcm_ui tests...$(NC)"
 cd lcm_ui && npm test

test-ui-watch: ## Run JavaScript tests in watch mode
 cd lcm_ui && npm run test:watch

lint-ui: ## Lint JavaScript code
 @echo "$(BLUE)Linting lcm_ui...$(NC)"
 cd lcm_ui && npm run lint

typecheck-ui: ## TypeScript type checking
 @echo "$(BLUE)Type checking lcm_ui...$(NC)"
 cd lcm_ui && npm run typecheck

##@ All

install: install-python install-ui ## Install all dependencies

build: build-ui ## Build all packages

test: test-python test-ui ## Run all tests

lint: lint-python lint-ui ## Lint all code

clean: ## Clean build artifacts
 rm -rf lcm_ui/dist
 rm -rf lcm_ui/node_modules
 rm -rf .pytest_cache
 rm -rf .ruff_cache

##@ Publishing

pack-ui: build-ui ## Create npm tarball (for local testing)
 @echo "$(BLUE)Creating npm package tarball...$(NC)"
 cd lcm_ui && npm pack
 @echo "$(GREEN)Package created: lcm_ui/neuroglia-ui-core-*.tgz$(NC)"

publish-local: pack-ui ## Publish to local registry (verdaccio)
 @echo "$(BLUE)Publishing to local registry...$(NC)"
 cd lcm_ui && npm publish --registry http://localhost:4873
 @echo "$(GREEN)Published to local registry!$(NC)"

publish-github: build-ui ## Publish to GitHub Packages
 @echo "$(BLUE)Publishing to GitHub Packages...$(NC)"
 cd lcm_ui && npm publish --registry https://npm.pkg.github.com
 @echo "$(GREEN)Published to GitHub Packages!$(NC)"

link-ui: build-ui ## Create npm link for local development
 @echo "$(BLUE)Creating npm link...$(NC)"
 cd lcm_ui && npm link
 @echo "$(GREEN)Run 'npm link @neuroglia/ui-core' in consumer projects$(NC)"
```

### 4.2 Consumer Project Integration

```makefile
# src/control-plane-api/Makefile (UPDATED)

# Add these targets:

##@ UI Dependencies

link-ui-core: ## Link local @neuroglia/ui-core package
 @echo "$(BLUE)Linking @neuroglia/ui-core...$(NC)"
 cd ui && npm link @neuroglia/ui-core
 @echo "$(GREEN)Linked! Changes in lcm_ui will be reflected automatically.$(NC)"

unlink-ui-core: ## Unlink local package and use published version
 @echo "$(BLUE)Unlinking @neuroglia/ui-core...$(NC)"
 cd ui && npm unlink @neuroglia/ui-core
 cd ui && npm install
 @echo "$(GREEN)Unlinked. Now using published version.$(NC)"

install-ui: ## Install UI dependencies (including @neuroglia/ui-core)
 @echo "$(BLUE)Installing UI dependencies...$(NC)"
 cd ui && npm ci
 @echo "$(GREEN)UI dependencies installed!$(NC)"
```

### 4.3 Consumer Package.json

```json
// src/control-plane-api/ui/package.json (UPDATED)
{
    "name": "lablet-cloud-manager-ui",
    "version": "1.0.0",
    "description": "Frontend UI for Lablet Cloud Manager",
    "scripts": {
        "prebuild": "node build-template.js",
        "build": "npm run prebuild && parcel build src/tmp_build/index.html --dist-dir ../static --public-url /static",
        "predev": "node build-template.js",
        "dev": "npm run predev && parcel src/tmp_build/index.html",
        "watch": "node build-template.js && parcel watch src/tmp_build/index.html --dist-dir ../static --public-url /static",
        "render": "node build-template.js"
    },
    "dependencies": {
        "@neuroglia/ui-core": "^0.1.0",
        "bootstrap": "^5.3.2",
        "bootstrap-icons": "^1.11.1",
        "marked": "^17.0.0",
        "moment": "^2.30.1"
    },
    "devDependencies": {
        "@parcel/transformer-sass": "^2.12.0",
        "nunjucks": "^3.2.4",
        "parcel": "^2.12.0",
        "parcel-reporter-static-files-copy": "^1.5.3",
        "sass": "^1.69.0"
    }
}
```

### 4.4 Development Workflow

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Development Workflow                             │
└─────────────────────────────────────────────────────────────────────┘

1. LOCAL DEVELOPMENT (npm link)
   ┌──────────────┐                    ┌──────────────────────┐
   │  lcm_ui/     │  npm link          │ control-plane-api/ui │
   │  (source)    │ ───────────────────│ (consumer)           │
   └──────────────┘                    └──────────────────────┘

   # In lcm_ui:
   $ make link-ui

   # In control-plane-api:
   $ make link-ui-core

   # Changes in lcm_ui are immediately available!

2. GITHUB PACKAGES (Primary - Production) ⭐
   ┌──────────────┐    CI/CD           ┌─────────────────┐   npm i    ┌─────────────┐
   │  lcm_ui/     │ ─────────────────► │ GitHub Packages │ ◄──────────│  consumers  │
   └──────────────┘                    │ npm.pkg.github  │            └─────────────┘
                                       └─────────────────┘

   # Manual publish (requires GITHUB_TOKEN):
   $ make publish-github

   # Automated via GitHub Actions on tag push (see section 4.5)

   # Consume (after .npmrc configured):
   $ npm install @neuroglia/ui-core

3. LOCAL REGISTRY (Verdaccio - for offline/CI testing)
   ┌──────────────┐    publish         ┌───────────┐    install    ┌─────────────┐
   │  lcm_ui/     │ ─────────────────► │ Verdaccio │ ◄─────────────│  consumers  │
   └──────────────┘                    │ :4873     │               └─────────────┘
                                       └───────────┘

   # Start Verdaccio (Docker):
   $ docker run -d -p 4873:4873 verdaccio/verdaccio

   # Publish:
   $ make publish-local

   # Consume:
   $ npm install @neuroglia/ui-core --registry http://localhost:4873

4. PUBLIC NPM (Future - if extracted to Neuroglia framework)
   ┌──────────────┐    npm publish     ┌───────────┐
   │  lcm_ui/     │ ─────────────────► │  npmjs    │
   └──────────────┘                    └───────────┘
```

### 4.5 GitHub Packages Configuration

#### Package Scope & Registry

GitHub Packages requires scoped packages. The package name must match the GitHub organization/user:

```json
// src/core/lcm_ui/package.json
{
    "name": "@neuroglia/ui-core",
    "publishConfig": {
        "registry": "https://npm.pkg.github.com"
    },
    "repository": {
        "type": "git",
        "url": "https://github.com/neuroglia/lablet-cloud-manager.git",
        "directory": "src/core/lcm_ui"
    }
}
```

#### Consumer .npmrc Configuration

Consumers need to configure npm to fetch `@neuroglia` packages from GitHub:

```ini
# src/control-plane-api/ui/.npmrc
@neuroglia:registry=https://npm.pkg.github.com
//npm.pkg.github.com/:_authToken=${GITHUB_TOKEN}
```

**For local development**, create a personal access token (PAT) with `read:packages` scope:

```bash
# Set token in environment (add to ~/.zshrc or ~/.bashrc)
export GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
```

**For CI/CD**, use the built-in `GITHUB_TOKEN` secret.

#### GitHub Actions Workflow (Publish on Tag)

```yaml
# .github/workflows/publish-ui-core.yml
name: Publish @neuroglia/ui-core

on:
  push:
    tags:
      - 'ui-core-v*'  # e.g., ui-core-v0.1.0, ui-core-v1.0.0

jobs:
  publish:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'
          registry-url: 'https://npm.pkg.github.com'
          scope: '@neuroglia'

      - name: Install dependencies
        working-directory: src/core/lcm_ui
        run: npm ci

      - name: Run tests
        working-directory: src/core/lcm_ui
        run: npm test

      - name: Build
        working-directory: src/core/lcm_ui
        run: npm run build

      - name: Publish to GitHub Packages
        working-directory: src/core/lcm_ui
        run: npm publish
        env:
          NODE_AUTH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

#### Release Workflow

```bash
# 1. Update version in package.json
cd src/core/lcm_ui
npm version patch  # or minor, major

# 2. Commit and tag
git add package.json
git commit -m "chore(ui-core): bump version to $(node -p "require('./package.json').version")"
git tag "ui-core-v$(node -p "require('./package.json').version")"

# 3. Push (triggers GitHub Actions)
git push origin main --tags
```

#### Consuming the Package

```bash
# In consumer project (after .npmrc configured)
cd src/control-plane-api/ui
npm install @neuroglia/ui-core

# Or specify version
npm install @neuroglia/ui-core@0.1.0
```

---

## Part 5: Import Patterns

### 5.1 Importing in Consumer Projects

```javascript
// Option 1: Import everything
import { EventBus, StateStore, SSEClient, SessionManager } from '@neuroglia/ui-core';

// Option 2: Subpath imports (tree-shakeable)
import { EventBus, StateStore } from '@neuroglia/ui-core/core';
import { SessionManager } from '@neuroglia/ui-core/session';
import { loggerMiddleware, devToolsMiddleware } from '@neuroglia/ui-core/middleware';

// Option 3: Create configured instances
import { createStore, createEventBus, createSSEClient } from '@neuroglia/ui-core';

const eventBus = createEventBus({ debug: true });
const store = createStore({
    slices: { workers: { items: [] } },
    eventBus
});
```

### 5.2 LCM Application Layer Structure

The LCM-specific code remains in `control-plane-api/ui/src/scripts/app/`:

```javascript
// control-plane-api/ui/src/scripts/app/store.js
import { StateStore, EventBus, SSEClient, SessionManager } from '@neuroglia/ui-core';
import { loggerMiddleware, devToolsMiddleware } from '@neuroglia/ui-core/middleware';

// Import LCM-specific slices
import { workersSlice, registerWorkerActions } from './slices/workersSlice.js';
import { labletsSlice, registerLabletActions } from './slices/labletsSlice.js';
import { configureSSEAdapter } from './sse/sseAdapter.js';
import { LCM_SSE_EVENTS } from './sse/eventTypes.js';

// Create instances with LCM configuration
export const eventBus = new EventBus({
    debug: localStorage.getItem('debug') === 'true',
    historySize: 100
});

export const store = new StateStore({
    slices: {
        workers: workersSlice.initialState,
        lablets: labletsSlice.initialState,
        // ... other slices
    },
    middleware: [loggerMiddleware],
    eventBus
});

// Register LCM actions
registerWorkerActions(store);
registerLabletActions(store);

// Create SSE client with LCM event types
export const sseClient = new SSEClient({
    url: '/api/events/stream',
    eventBus,
    eventMap: LCM_SSE_EVENTS
});

// Configure SSE → Store wiring
configureSSEAdapter(sseClient, store, eventBus);

// Session manager
export const sessionManager = new SessionManager({
    store,
    eventBus,
    authApi: { /* LCM auth API */ }
});

// Auto-connect
sseClient.connect();
sessionManager.initialize();
```

---

## Part 6: Migration Checklist

### Phase 1: Create Package Structure

- [ ] Create `src/core/lcm_ui/` directory
- [ ] Initialize npm package with `package.json`
- [ ] Set up TypeScript with `tsconfig.json`
- [ ] Configure Rollup bundler
- [ ] Create `src/core/Makefile` for dual Python/JS builds

### Phase 2: Migrate Core Classes

- [ ] Port `EventBus.js` → `EventBus.ts` with types
- [ ] Create `StateStore.ts` (new implementation)
- [ ] Port `SSEClient` from `SSEService.js`
- [ ] Create `BaseComponent.ts` base class
- [ ] Add memory management utilities
- [ ] Implement `SessionManager.ts`

### Phase 3: Add Middleware & Utilities

- [ ] Logger middleware
- [ ] DevTools middleware
- [ ] Throttle middleware
- [ ] Persist middleware
- [ ] SSEEventBuffer utility

### Phase 4: Testing & Documentation

- [ ] Unit tests for all core classes
- [ ] Integration tests for store + SSE
- [ ] JSDoc comments for all public APIs
- [ ] README with usage examples
- [ ] TypeScript declaration files

### Phase 5: Consumer Integration

- [ ] Add `@neuroglia/ui-core` to control-plane-api
- [ ] Refactor existing code to use package
- [ ] Update Makefiles with new targets
- [ ] Test build and hot-reload workflow
- [ ] Remove duplicated code from consumer

### Phase 6: CI/CD

- [ ] GitHub Actions workflow for lcm_ui
- [ ] Automated testing on PR
- [ ] Automated publishing to internal registry
- [ ] Version bumping strategy

---

## Part 7: Web Component Promotion

This section identifies which web components should be promoted from the LCM application layer to the `@neuroglia/ui-core` package.

### 7.1 Component Analysis

The following components currently reside in `control-plane-api/ui/src/scripts/components/core/`:

| Component | Lines | Verdict | Notes |
|-----------|-------|---------|-------|
| `BaseComponent.js` | 254 | ✅ **PROMOTE** | Foundation class - EventBus integration, lifecycle, auto-cleanup |
| `LcmTabView.js` | 293 | ✅ **PROMOTE** | Generic tabbed navigation with variants (pills, underline, buttons) |
| `LcmDataTable.js` | 831 | ✅ **PROMOTE** | Full-featured data table: filtering, sorting, pagination, bulk actions |
| `LcmModal.js` | 427 | ✅ **PROMOTE** | Bootstrap 5 modal wrapper with promise API |
| `LcmActionBar.js` | 259 | ✅ **PROMOTE** | Generic toolbar pattern with primary/filter/secondary slots |
| `LcmMetricCard.js` | 166 | ✅ **PROMOTE** | Statistic display card with trend indicators |
| `LcmStatusBadge.js` | 213 | ⚠️ **PROMOTE (Refactor)** | Status badge - needs configurable status→color mappings |
| `LcmGrafanaPanel.js` | 422 | ❌ **KEEP IN APP** | Domain-specific: Grafana iframe embedding |
| `LcmUserMenu.js` | 189 | ⚠️ **PROMOTE (Refactor)** | User dropdown - needs configurable role checks |

### 7.2 Promotion Criteria

Components are considered **generic** if they meet all of the following:

1. **No hardcoded domain concepts** (e.g., "worker", "lablet", "CML")
2. **Configurable through attributes/properties** rather than internal constants
3. **Reusable across different applications** without modification
4. **Bootstrap 5 compatible** but not Bootstrap-dependent (graceful fallback)
5. **Follows Web Component standards** (Custom Elements v1)

### 7.3 Components to Promote

#### 7.3.1 BaseComponent (Foundation)

**Current:** `ui/src/scripts/core/BaseComponent.js`
**Target:** `lcm_ui/src/components/BaseComponent.ts`

No refactoring needed. This is already generic:

```typescript
// @neuroglia/ui-core/components/BaseComponent.ts
export abstract class BaseComponent extends HTMLElement {
    protected _subscriptions: (() => void)[] = [];
    protected _mounted = false;
    protected _state: Record<string, unknown> = {};

    connectedCallback(): void;
    disconnectedCallback(): void;
    attributeChangedCallback(name: string, oldValue: string | null, newValue: string | null): void;

    // Lifecycle hooks (override in subclasses)
    protected onMount(): void;
    protected onUnmount(): void;
    protected onAttributeChange(name: string, oldValue: string | null, newValue: string | null): void;

    // EventBus integration
    protected subscribe(eventType: string, handler: EventHandler): () => void;
    protected emit(eventType: string, data?: unknown): void;
    protected cleanup(): void;

    // State utilities
    protected setState(updates: Record<string, unknown>): void;
    protected getState<T>(key: string): T | undefined;

    // DOM utilities
    protected $(selector: string): Element | null;
    protected $$(selector: string): NodeListOf<Element>;
    protected createElement<K extends keyof HTMLElementTagNameMap>(tag: K, attrs?: Record<string, string>): HTMLElementTagNameMap[K];
}
```

#### 7.3.2 TabView

**Current:** `LcmTabView.js` (293 lines)
**Target:** `lcm_ui/src/components/TabView.ts`
**Element Name:** `<ui-tab-view>` (renamed from `<lcm-tab-view>`)

No refactoring needed. Already generic with configurable variants:

```html
<!-- Usage (unchanged pattern) -->
<ui-tab-view variant="pills" active-tab="workers">
    <ui-tab name="workers" label="Workers" icon="bi-cpu">
        <div slot="content">...</div>
    </ui-tab>
    <ui-tab name="labs" label="Labs">
        <div slot="content">...</div>
    </ui-tab>
</ui-tab-view>
```

#### 7.3.3 DataTable

**Current:** `LcmDataTable.js` (831 lines)
**Target:** `lcm_ui/src/components/DataTable.ts`
**Element Name:** `<ui-data-table>`

No refactoring needed. Already generic with column definitions passed as data:

```html
<ui-data-table
    columns='[{"key":"name","label":"Name","sortable":true}]'
    data='[{"name":"Item 1"}]'
    paginated
    selectable
    filterable>
</ui-data-table>
```

#### 7.3.4 Modal

**Current:** `LcmModal.js` (427 lines)
**Target:** `lcm_ui/src/components/Modal.ts`
**Element Name:** `<ui-modal>`

No refactoring needed. Generic Bootstrap 5 modal wrapper:

```javascript
const modal = document.querySelector('ui-modal');
const result = await modal.show();  // Returns promise
if (result.confirmed) { /* ... */ }
```

#### 7.3.5 ActionBar

**Current:** `LcmActionBar.js` (259 lines)
**Target:** `lcm_ui/src/components/ActionBar.ts`
**Element Name:** `<ui-action-bar>`

No refactoring needed. Generic toolbar with slots:

```html
<ui-action-bar>
    <slot name="primary"><!-- Primary actions --></slot>
    <slot name="filters"><!-- Filter chips --></slot>
    <slot name="secondary"><!-- Secondary actions --></slot>
</ui-action-bar>
```

#### 7.3.6 MetricCard

**Current:** `LcmMetricCard.js` (166 lines)
**Target:** `lcm_ui/src/components/MetricCard.ts`
**Element Name:** `<ui-metric-card>`

No refactoring needed. Generic statistic display:

```html
<ui-metric-card
    label="Total Workers"
    value="42"
    icon="bi-cpu"
    trend="up"
    trend-value="+5%">
</ui-metric-card>
```

### 7.4 Components Requiring Refactoring

#### 7.4.1 StatusBadge (Needs Configurable Mappings)

**Problem:** Contains hardcoded LCM-specific status mappings:

```javascript
// Current (LCM-specific)
static STATUS_COLORS = {
    'running': 'success',
    'stopped': 'secondary',
    'cml_ready': 'success',      // LCM-specific
    'licensed': 'info',          // LCM-specific
    'unlicensed': 'warning'      // LCM-specific
};
```

**Solution:** Make mappings configurable via attribute or global registration:

```typescript
// @neuroglia/ui-core - Generic StatusBadge
export interface StatusConfig {
    color: 'primary' | 'secondary' | 'success' | 'warning' | 'danger' | 'info';
    icon?: string;
    label?: string;  // Optional display label override
}

export class StatusBadge extends BaseComponent {
    // Default mappings (generic)
    static defaultMappings: Record<string, StatusConfig> = {
        'active': { color: 'success', icon: 'bi-check-circle' },
        'inactive': { color: 'secondary', icon: 'bi-pause-circle' },
        'pending': { color: 'warning', icon: 'bi-hourglass-split' },
        'error': { color: 'danger', icon: 'bi-exclamation-circle' },
        'unknown': { color: 'secondary', icon: 'bi-question-circle' }
    };

    // Configurable mappings
    private _mappings: Record<string, StatusConfig>;

    // Option 1: Configure via attribute (JSON)
    static get observedAttributes() {
        return ['status', 'mappings'];
    }

    // Option 2: Register mappings globally
    static registerMappings(mappings: Record<string, StatusConfig>): void {
        Object.assign(StatusBadge.defaultMappings, mappings);
    }
}
```

**LCM Application Layer Usage:**

```javascript
// In LCM app initialization
import { StatusBadge } from '@neuroglia/ui-core/components';

// Register LCM-specific mappings
StatusBadge.registerMappings({
    'cml_ready': { color: 'success', icon: 'bi-cloud-check' },
    'licensed': { color: 'info', icon: 'bi-key' },
    'unlicensed': { color: 'warning', icon: 'bi-key-fill' },
    'provisioning': { color: 'warning', icon: 'bi-gear' },
    'terminating': { color: 'danger', icon: 'bi-trash' }
});
```

#### 7.4.2 UserMenu (Needs Configurable Roles)

**Problem:** Contains hardcoded LCM role checks:

```javascript
// Current (LCM-specific)
get isAdmin() {
    return this._user?.roles?.includes('lcm-admin');
}
```

**Solution:** Make role checking configurable via callback or config:

```typescript
// @neuroglia/ui-core - Generic UserMenu
export interface UserMenuConfig {
    user: {
        name: string;
        email?: string;
        avatar?: string;
        roles?: string[];
    };
    menuItems: MenuItem[];
    roleCheck?: (role: string) => boolean;  // Custom role checker
}

export interface MenuItem {
    label: string;
    icon?: string;
    href?: string;
    action?: () => void;
    requiresRole?: string;  // Optional role requirement
    divider?: boolean;
}

export class UserMenu extends BaseComponent {
    private _config: UserMenuConfig;

    setConfig(config: UserMenuConfig): void {
        this._config = config;
        this.render();
    }

    private hasRole(role: string): boolean {
        if (this._config.roleCheck) {
            return this._config.roleCheck(role);
        }
        return this._config.user.roles?.includes(role) ?? false;
    }

    private renderMenuItems(): void {
        for (const item of this._config.menuItems) {
            if (item.requiresRole && !this.hasRole(item.requiresRole)) {
                continue;  // Skip items user doesn't have access to
            }
            // Render item...
        }
    }
}
```

**LCM Application Layer Usage:**

```javascript
// In LCM app
import { UserMenu } from '@neuroglia/ui-core/components';

const userMenu = document.querySelector('ui-user-menu');
userMenu.setConfig({
    user: currentUser,
    menuItems: [
        { label: 'Profile', icon: 'bi-person', href: '/profile' },
        { label: 'Settings', icon: 'bi-gear', href: '/settings', requiresRole: 'lcm-admin' },
        { divider: true },
        { label: 'Logout', icon: 'bi-box-arrow-right', action: () => logout() }
    ],
    roleCheck: (role) => currentUser.keycloakRoles?.includes(role)
});
```

### 7.5 Components to Keep in Application Layer

#### 7.5.1 GrafanaPanel

**Reason:** Highly domain-specific (Grafana embedding). Not reusable outside observability contexts.

**Location:** Keep in `control-plane-api/ui/src/scripts/components/`

### 7.6 Updated Package Structure

```
src/core/lcm_ui/
├── package.json
├── rollup.config.js
├── tsconfig.json
├── src/
│   ├── index.ts                    # Main entry point
│   ├── core/
│   │   ├── EventBus.ts
│   │   ├── StateStore.ts
│   │   ├── SSEClient.ts
│   │   ├── SSEEventBuffer.ts
│   │   └── index.ts
│   ├── session/
│   │   ├── SessionManager.ts
│   │   ├── sessionSlice.ts
│   │   └── index.ts
│   ├── middleware/
│   │   ├── logger.ts
│   │   ├── devtools.ts
│   │   ├── throttle.ts
│   │   ├── persist.ts
│   │   └── index.ts
│   ├── components/                  # NEW - Promoted web components
│   │   ├── BaseComponent.ts
│   │   ├── TabView.ts
│   │   ├── DataTable.ts
│   │   ├── Modal.ts
│   │   ├── ActionBar.ts
│   │   ├── MetricCard.ts
│   │   ├── StatusBadge.ts          # With configurable mappings
│   │   ├── UserMenu.ts             # With configurable roles
│   │   └── index.ts
│   └── types/
│       ├── events.ts
│       ├── store.ts
│       ├── components.ts           # NEW - Component type definitions
│       └── index.ts
└── tests/
    ├── EventBus.test.ts
    ├── StateStore.test.ts
    ├── components/                  # NEW - Component tests
    │   ├── TabView.test.ts
    │   ├── DataTable.test.ts
    │   └── ...
    └── ...
```

### 7.7 Element Naming Convention

When promoting components to `@neuroglia/ui-core`, rename element tags to use a generic prefix:

| LCM Element | Core Element | Reason |
|-------------|--------------|--------|
| `<lcm-tab-view>` | `<ui-tab-view>` | Generic UI prefix |
| `<lcm-data-table>` | `<ui-data-table>` | Generic UI prefix |
| `<lcm-modal>` | `<ui-modal>` | Generic UI prefix |
| `<lcm-action-bar>` | `<ui-action-bar>` | Generic UI prefix |
| `<lcm-metric-card>` | `<ui-metric-card>` | Generic UI prefix |
| `<lcm-status-badge>` | `<ui-status-badge>` | Generic UI prefix |
| `<lcm-user-menu>` | `<ui-user-menu>` | Generic UI prefix |
| `<lcm-grafana-panel>` | N/A (keep LCM) | Domain-specific |

**Namespace alternatives:**

- `<ui-*>` - Simple, generic (recommended)
- `<ng-*>` - Neuroglia prefix (may conflict with Angular)
- `<nui-*>` - Neuroglia UI prefix (unique)

### 7.8 Updated Package Exports

```json
// package.json exports field (updated)
{
    "exports": {
        ".": {
            "import": "./dist/index.esm.js",
            "require": "./dist/index.js",
            "types": "./dist/index.d.ts"
        },
        "./core": { /* ... */ },
        "./session": { /* ... */ },
        "./middleware": { /* ... */ },
        "./components": {
            "import": "./dist/components/index.esm.js",
            "require": "./dist/components/index.js",
            "types": "./dist/components/index.d.ts"
        }
    }
}
```

### 7.9 Updated Migration Checklist

Add these items to **Phase 2**:

- [ ] Port `BaseComponent.js` → `BaseComponent.ts`
- [ ] Port `LcmTabView.js` → `TabView.ts` (rename element)
- [ ] Port `LcmDataTable.js` → `DataTable.ts` (rename element)
- [ ] Port `LcmModal.js` → `Modal.ts` (rename element)
- [ ] Port `LcmActionBar.js` → `ActionBar.ts` (rename element)
- [ ] Port `LcmMetricCard.js` → `MetricCard.ts` (rename element)
- [ ] Refactor `LcmStatusBadge.js` → `StatusBadge.ts` (configurable mappings)
- [ ] Refactor `LcmUserMenu.js` → `UserMenu.ts` (configurable roles)
- [ ] Add component type definitions
- [ ] Add component unit tests

Add to **Phase 5** (Consumer Integration):

- [ ] Update LCM to register StatusBadge mappings
- [ ] Update LCM to configure UserMenu with LCM roles
- [ ] Update LCM templates to use new element names (`ui-*`)
- [ ] Keep `LcmGrafanaPanel` in LCM application layer

---

## References

- [Frontend State Management Architecture](./frontend-state-management.md)
- [Verdaccio - Private npm Registry](https://verdaccio.org/)
- [Rollup.js Bundler](https://rollupjs.org/)
- [npm Workspaces](https://docs.npmjs.com/cli/v7/using-npm/workspaces)
- [Custom Elements v1 Specification](https://html.spec.whatwg.org/multipage/custom-elements.html)
