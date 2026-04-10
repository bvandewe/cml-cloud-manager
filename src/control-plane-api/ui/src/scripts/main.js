// Main application entry point
import 'bootstrap';
import '../styles/main.scss';

// Register @neuroglia/ui-core components (ui-* prefix)
// Must run BEFORE page components that reference ui-* elements
import './bridge/uiCoreSetup.js';

// Register all core components (lcm-* prefix)
import './components/core/index.js';

// Register page components
import './components/pages/index.js';

// Initialize application
import './app.js';
