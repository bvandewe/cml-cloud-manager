/**
 * Theme Switcher Service
 * Handles light/dark theme toggling with localStorage persistence
 */

const THEME_KEY = 'cml-theme';
const DARK_THEME = 'dark';
const LIGHT_THEME = 'light';

// Guard against double initialization
let initialized = false;

/**
 * Get the current theme from localStorage or default to light
 * @returns {string} Current theme ('light' or 'dark')
 */
export function getCurrentTheme() {
    const theme = localStorage.getItem(THEME_KEY) || LIGHT_THEME;
    console.log('[Theme] getCurrentTheme:', theme);
    return theme;
}

/**
 * Set the theme
 * @param {string} theme - Theme to set ('light' or 'dark')
 */
export function setTheme(theme) {
    console.log('[Theme] setTheme:', theme);
    localStorage.setItem(THEME_KEY, theme);
    applyTheme(theme);
}

/**
 * Toggle between light and dark themes
 * @returns {string} New theme
 */
export function toggleTheme() {
    const currentTheme = getCurrentTheme();
    const newTheme = currentTheme === DARK_THEME ? LIGHT_THEME : DARK_THEME;
    console.log('[Theme] toggleTheme:', currentTheme, '->', newTheme);
    setTheme(newTheme);
    return newTheme;
}

/**
 * Apply theme to the document
 * @param {string} theme - Theme to apply
 */
function applyTheme(theme) {
    const html = document.documentElement;
    const themeIcon = document.getElementById('theme-icon');

    console.log('[Theme] applyTheme:', theme);
    console.log('[Theme] html element:', html);
    console.log('[Theme] themeIcon element:', themeIcon);

    if (theme === DARK_THEME) {
        // Dark theme: white on black
        html.setAttribute('data-bs-theme', 'dark');
        console.log('[Theme] Set data-bs-theme to dark');
        if (themeIcon) {
            themeIcon.className = 'bi bi-sun-fill';
            console.log('[Theme] Changed icon to sun');
        }
    } else {
        // Light theme: black on white (Bootstrap default)
        html.setAttribute('data-bs-theme', 'light');
        console.log('[Theme] Set data-bs-theme to light');
        if (themeIcon) {
            themeIcon.className = 'bi bi-moon-fill';
            console.log('[Theme] Changed icon to moon');
        }
    }

    // Verify the attribute was set
    console.log('[Theme] Verified data-bs-theme:', html.getAttribute('data-bs-theme'));

    // Check if Bootstrap CSS is loaded and has dark theme styles
    const computedBg = getComputedStyle(document.body).backgroundColor;
    console.log('[Theme] Body background color:', computedBg);
}

/**
 * Initialize theme on page load
 */
export function initializeTheme() {
    // Prevent double initialization (module auto-init + explicit call)
    if (initialized) {
        console.log('[Theme] Already initialized, skipping');
        return;
    }
    initialized = true;

    console.log('[Theme] initializeTheme called');
    const savedTheme = getCurrentTheme();
    applyTheme(savedTheme);

    // Setup theme toggle button
    const themeToggle = document.getElementById('theme-toggle');
    console.log('[Theme] themeToggle button:', themeToggle);
    if (themeToggle) {
        themeToggle.addEventListener('click', () => {
            console.log('[Theme] Toggle button clicked');
            toggleTheme();
        });
        console.log('[Theme] Click listener attached to toggle button');
    } else {
        console.warn('[Theme] No theme-toggle button found!');
    }
}

// Auto-initialize when DOM is ready
if (document.readyState === 'loading') {
    console.log('[Theme] DOM loading, waiting for DOMContentLoaded');
    document.addEventListener('DOMContentLoaded', initializeTheme);
} else {
    console.log('[Theme] DOM ready, initializing immediately');
    initializeTheme();
}
