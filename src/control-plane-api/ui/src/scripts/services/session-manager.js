import { apiRequest } from '../api/client.js';
import { login } from '../ui/auth.js';

class SessionManager {
    constructor() {
        this.checkInterval = null;
        this.countdownInterval = null;
        this.warningShown = false;
        this.bannerId = 'session-warning-banner';
        this.secondsRemaining = 0;
    }

    async init() {
        await this.checkSession();
        // Check session status every minute
        this.checkInterval = setInterval(() => this.checkSession(), 60000);
    }

    async checkSession() {
        try {
            const response = await apiRequest('/api/auth/session');
            const data = await response.json();

            if (!data.authenticated) {
                return;
            }

            const expiresInSeconds = data.expires_in_seconds;
            const warningMinutes = data.session_expiration_warning_minutes || 5;
            const warningSeconds = warningMinutes * 60;

            if (expiresInSeconds !== null) {
                if (expiresInSeconds <= 0) {
                    this.handleExpiration();
                } else if (expiresInSeconds <= warningSeconds) {
                    this.showWarning(expiresInSeconds);
                } else {
                    this.hideWarning();
                }
            }
        } catch (error) {
            console.error('Session check failed:', error);
        }
    }

    showWarning(secondsRemaining) {
        this.secondsRemaining = secondsRemaining;
        this.updateTimerDisplay();

        if (this.warningShown) {
            // Timer is already running via countdownInterval
            return;
        }

        this.warningShown = true;

        // Create banner - positioned below navbar
        const banner = document.createElement('div');
        banner.id = this.bannerId;
        banner.className = 'alert alert-warning text-center d-flex justify-content-center align-items-center';
        banner.style.cssText = 'position: fixed; top: 56px; left: 0; right: 0; z-index: 1040; margin: 0; border-radius: 0; background-color: #fff3cd; border-color: #ffc107;';
        banner.innerHTML = `
            <span class="me-3">
                <i class="bi bi-exclamation-triangle-fill me-2"></i>
                Your session will expire in <strong id="session-timer">--:--</strong>.
            </span>
            <button id="extend-session-btn" class="btn btn-sm btn-primary me-2">Extend Session</button>
            <button type="button" class="btn-close" aria-label="Close"></button>
        `;

        document.body.prepend(banner);

        // Add event listeners
        document.getElementById('extend-session-btn').addEventListener('click', () => this.extendSession());

        // Handle dismiss
        banner.querySelector('.btn-close').addEventListener('click', () => {
            this.hideWarning();
        });

        // Start countdown
        this.startCountdown();
    }

    startCountdown() {
        if (this.countdownInterval) clearInterval(this.countdownInterval);

        this.updateTimerDisplay();

        this.countdownInterval = setInterval(() => {
            this.secondsRemaining--;
            if (this.secondsRemaining <= 0) {
                this.handleExpiration();
            } else {
                this.updateTimerDisplay();
            }
        }, 1000);
    }

    updateTimerDisplay() {
        const timerEl = document.getElementById('session-timer');
        if (timerEl && this.secondsRemaining >= 0) {
            const minutes = Math.floor(this.secondsRemaining / 60);
            const seconds = this.secondsRemaining % 60;
            timerEl.textContent = `${minutes}:${seconds.toString().padStart(2, '0')}`;
        }
    }

    hideWarning() {
        const banner = document.getElementById(this.bannerId);
        if (banner) {
            banner.remove();
        }
        this.warningShown = false;
        if (this.countdownInterval) {
            clearInterval(this.countdownInterval);
            this.countdownInterval = null;
        }
    }

    async extendSession() {
        try {
            await apiRequest('/api/auth/extend-session', { method: 'POST' });
            this.hideWarning();
            await this.checkSession(); // Update status immediately
        } catch (error) {
            console.error('Failed to extend session:', error);
        }
    }

    stop() {
        if (this.checkInterval) {
            clearInterval(this.checkInterval);
            this.checkInterval = null;
        }
        this.hideWarning();
    }

    handleExpiration() {
        this.hideWarning();
        if (this.checkInterval) {
            clearInterval(this.checkInterval);
        }
        // Redirect to login (using auth.js login which redirects to Keycloak,
        // or showLoginForm which shows login form?
        // Requirement: "redirects to the login view and hides everything else"
        // showLoginForm does that.
        // But if session is really expired, we might want to refresh the page or go to /api/auth/login
        // to start a new flow.
        // client.js uses showLoginForm().
        // Let's use showLoginForm() too.
        import('../ui/auth.js').then(({ showLoginForm }) => {
            showLoginForm();
        });
    }
}

export const sessionManager = new SessionManager();
