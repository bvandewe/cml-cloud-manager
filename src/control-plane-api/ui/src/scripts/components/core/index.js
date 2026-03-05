/**
 * LCM Core Components Index
 *
 * This module exports all reusable Web Components that form the
 * foundation of the Lablet Cloud Manager UI. These components
 * are designed to be framework-agnostic and could potentially
 * be extracted to the Neuroglia framework.
 *
 * Components:
 *   - LcmTabView, LcmTab: Tabbed navigation containers
 *   - LcmUserMenu: User profile dropdown
 *   - LcmMetricCard: Dashboard metric display cards
 *   - LcmStatusBadge: Colored status indicators
 *   - LcmDataTable: Full-featured data table with pagination
 *   - LcmActionBar, LcmFilterChip, LcmDropdownAction: Toolbar components
 *   - LcmModal, LcmConfirmModal: Modal dialog components
 *   - LcmGrafanaPanel, LcmGrafanaDashboard: Grafana embedding components
 *
 * Usage:
 *   import { LcmDataTable, LcmStatusBadge } from './components/core/index.js';
 *
 * Or import all:
 *   import './components/core/index.js';
 *
 * @module components/core
 */

// Tab Navigation
export { LcmTab, LcmTabView } from './LcmTabView.js';

// User Interface
export { LcmUserMenu } from './LcmUserMenu.js';

// Dashboard Components
export { LcmMetricCard } from './LcmMetricCard.js';

// Status Display
export { LcmStatusBadge } from './LcmStatusBadge.js';

// Data Table
export { LcmDataTable } from './LcmDataTable.js';

// Action Bar & Filters
export { LcmActionBar, LcmFilterChip, LcmDropdownAction } from './LcmActionBar.js';

// Modals
export { LcmModal, LcmConfirmModal } from './LcmModal.js';

// Grafana Integration
export { LcmGrafanaPanel, LcmGrafanaDashboard } from './LcmGrafanaPanel.js';

// Re-export everything as default for easy importing
export default {
    // Re-register all custom elements by importing modules
};

// Ensure all components are registered
import './LcmTabView.js';
import './LcmUserMenu.js';
import './LcmMetricCard.js';
import './LcmStatusBadge.js';
import './LcmDataTable.js';
import './LcmActionBar.js';
import './LcmModal.js';
import './LcmGrafanaPanel.js';

console.log('[LCM Core Components] All components registered');
