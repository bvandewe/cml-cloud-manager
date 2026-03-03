/**
 * API Client Module
 * Handles all HTTP requests to the backend API
 */

/**
 * Make an authenticated API request
 * @param {string} url - The API endpoint URL
 * @param {Object} options - Fetch options (method, headers, body, etc.)
 * @returns {Promise<Response>} - The fetch response
 */
export async function apiRequest(url, options = {}) {
    const headers = {
        ...options.headers,
    };

    // Only set Content-Type if not sending FormData (browser will set it with boundary)
    // and only when there IS a body to send (avoid empty JSON body on POST/PUT with no payload)
    if (options.body != null && !(options.body instanceof FormData)) {
        headers['Content-Type'] = 'application/json';
    }

    const response = await fetch(url, {
        ...options,
        headers,
        credentials: 'include', // Always send cookies
    });

    if (response.status === 401) {
        // Session expired - trigger login redirect
        const { showLoginForm } = await import('../ui/auth.js');
        showLoginForm();
        throw new Error('Authentication required');
    }

    if (response.status === 403) {
        // Forbidden - user doesn't have required permissions
        throw new Error('Permission denied: You do not have access to this resource');
    }

    if (!response.ok) {
        // Handle other error status codes (400, 500, etc.)
        let errorMessage = `Request failed with status ${response.status}`;
        try {
            const errorData = await response.json();
            // Extract error message from various possible response formats
            if (errorData.error) {
                errorMessage = typeof errorData.error === 'string' ? errorData.error : JSON.stringify(errorData.error);
            } else if (errorData.message) {
                errorMessage = typeof errorData.message === 'string' ? errorData.message : JSON.stringify(errorData.message);
            } else if (errorData.detail) {
                errorMessage = typeof errorData.detail === 'string' ? errorData.detail : JSON.stringify(errorData.detail);
            } else if (typeof errorData === 'string') {
                errorMessage = errorData;
            }
        } catch (e) {
            // If response body is not JSON, use status text
            errorMessage = response.statusText || errorMessage;
        }
        throw new Error(errorMessage);
    }

    return response;
}

/**
 * Check if user is authenticated
 * @returns {Promise<Object|null>} - User object or null
 */
export async function checkAuth() {
    try {
        const response = await fetch('/api/auth/user', {
            credentials: 'include', // Send session cookie
        });

        if (response.ok) {
            const user = await response.json();
            return user;
        }

        return null;
    } catch {
        return null;
    }
}
