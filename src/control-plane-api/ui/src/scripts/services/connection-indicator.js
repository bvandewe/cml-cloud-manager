/**
 * Connection Indicator Service
 * Manages the real-time connection status indicator in the navbar
 *
 * Listens to SSE connection events and updates the visual indicator accordingly.
 */

import { eventBus, EventTypes } from '../core/EventBus.js';

const CONNECTION_STATES = {
    CONNECTING: 'connecting',
    CONNECTED: 'connected',
    DISCONNECTED: 'disconnected',
    ERROR: 'error',
};

const STATE_LABELS = {
    [CONNECTION_STATES.CONNECTING]: 'Connecting...',
    [CONNECTION_STATES.CONNECTED]: 'Connected',
    [CONNECTION_STATES.DISCONNECTED]: 'Disconnected',
    [CONNECTION_STATES.ERROR]: 'Connection Error',
};

let currentState = CONNECTION_STATES.DISCONNECTED;

/**
 * Update the connection indicator UI
 * @param {string} state - One of CONNECTION_STATES values
 */
function updateIndicatorUI(state) {
    const indicator = document.getElementById('connection-indicator');
    const icon = document.getElementById('connection-icon');
    const text = indicator?.querySelector('.connection-text');

    if (!indicator) {
        console.debug('[ConnectionIndicator] Indicator element not found');
        return;
    }

    // Update state class
    indicator.className = 'connection-indicator';
    indicator.classList.add(state);

    // Update icon based on state
    if (icon) {
        switch (state) {
            case CONNECTION_STATES.CONNECTED:
                icon.className = 'bi bi-broadcast';
                break;
            case CONNECTION_STATES.CONNECTING:
                icon.className = 'bi bi-broadcast';
                break;
            case CONNECTION_STATES.DISCONNECTED:
                icon.className = 'bi bi-broadcast';
                break;
            case CONNECTION_STATES.ERROR:
                icon.className = 'bi bi-exclamation-triangle';
                break;
        }
    }

    // Update text
    if (text) {
        text.textContent = STATE_LABELS[state];
    }

    // Update title for tooltip
    indicator.title = STATE_LABELS[state];

    currentState = state;
}

/**
 * Set up event listeners for connection state changes
 */
function setupEventListeners() {
    // SSE Connected
    eventBus.on(EventTypes.SSE_CONNECTED, () => {
        console.log('[ConnectionIndicator] SSE connected');
        updateIndicatorUI(CONNECTION_STATES.CONNECTED);
    });

    // SSE Disconnected
    eventBus.on(EventTypes.SSE_DISCONNECTED, () => {
        console.log('[ConnectionIndicator] SSE disconnected');
        updateIndicatorUI(CONNECTION_STATES.DISCONNECTED);
    });

    // SSE Error
    eventBus.on(EventTypes.SSE_ERROR, error => {
        console.error('[ConnectionIndicator] SSE error:', error);
        updateIndicatorUI(CONNECTION_STATES.ERROR);
    });

    // Handle reconnecting state (if SSE service emits it)
    eventBus.on('sse.reconnecting', () => {
        console.log('[ConnectionIndicator] SSE reconnecting');
        updateIndicatorUI(CONNECTION_STATES.CONNECTING);
    });
}

/**
 * Initialize the connection indicator
 * Should be called after DOM is ready
 */
export function initializeConnectionIndicator() {
    console.log('[ConnectionIndicator] Initializing');

    // Set initial state
    updateIndicatorUI(CONNECTION_STATES.CONNECTING);

    // Set up event listeners
    setupEventListeners();
}

/**
 * Get current connection state
 * @returns {string} Current connection state
 */
export function getConnectionState() {
    return currentState;
}

/**
 * Check if currently connected
 * @returns {boolean} True if connected
 */
export function isConnected() {
    return currentState === CONNECTION_STATES.CONNECTED;
}

// Export constants for external use
export { CONNECTION_STATES };
