/**
 * UI Core Bridge — Component Registration & Configuration
 *
 * Registers all @neuroglia/ui-core Web Components (ui-* prefix) and configures
 * them with the shared EventBus and StateStore instances.
 *
 * This module MUST be imported before any page component that references
 * ui-* custom elements (via column registries or direct markup).
 *
 * Components registered:
 *   ui-data-table, ui-status-badge, ui-resource-status, ui-metric-card,
 *   ui-tab-view, ui-tab, ui-modal, ui-confirm-modal, ui-action-bar,
 *   ui-action-button, ui-filter-chip, ui-dropdown-action, ui-pipeline-log,
 *   ui-lifecycle-tracker, ui-revision-indicator, ui-timeslot-badge,
 *   ui-state-history, ui-resource-observation, ui-column-picker
 *
 * @module bridge/uiCoreSetup
 */

import { registerAllComponents, configureComponents } from '@neuroglia/ui-core';
import { eventBus } from '../app/eventBus.js';
import { store } from '../app/store.js';

/**
 * Initialize the ui-core component library.
 *
 * 1. Configures BaseComponent with the shared EventBus + StateStore
 *    so ui-* components can use this.emit() / this.connectStore().
 * 2. Calls registerAllComponents() which idempotently defines every
 *    ui-* custom element.
 */
export function initializeUiCore() {
    // Wire shared infrastructure into ui-core's BaseComponent
    configureComponents({
        eventBus,
        store,
    });

    // Register all ui-* custom elements
    registerAllComponents();

    console.log('[UI Core Bridge] Components registered and configured');
}

// Auto-initialize on import (side-effect module)
initializeUiCore();
