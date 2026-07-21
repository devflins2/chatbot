// main.js - Sidebar toggle, theme switcher, and general dashboard controls

// Global fallback for marked if CDN fails to load
if (typeof window.marked === 'undefined') {
    window.marked = {
        setOptions: () => {},
        parse: (text) => text.replace(/\n/g, '<br>')
    };
}

// Generic fetch wrappers to handle API requests and CSRF tokens automatically
const getCsrfToken = () => {
    const metaToken = document.querySelector('meta[name="csrf-token"]');
    if (metaToken) return metaToken.getAttribute('content');
    const csrfInput = document.querySelector('input[name="csrf_token"]');
    if (csrfInput) return csrfInput.value;
    return '';
};

const apiRequest = async (url, method = 'GET', body = null) => {
    const headers = {
        'Content-Type': 'application/json',
    };
    
    // Add CSRF token for state-modifying requests
    if (['POST', 'PUT', 'DELETE', 'PATCH'].includes(method.toUpperCase())) {
        const token = getCsrfToken();
        if (token) {
            headers['X-CSRFToken'] = token;
        }
    }

    const config = {
        method,
        headers,
    };

    if (body) {
        config.body = JSON.stringify(body);
    }

    const response = await fetch(url, config);
    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
        const errorMsg = data.error || data.message || `Request failed with status ${response.status}`;
        const err = new Error(errorMsg);
        err.status = response.status;
        err.data = data;
        throw err;
    }

    return data;
};

// Global API helpers expected by view scripts
window.apiGet = (url) => apiRequest(url, 'GET');
window.apiPost = (url, body) => apiRequest(url, 'POST', body);
window.apiPut = (url, body) => apiRequest(url, 'PUT', body);
window.apiDelete = (url) => apiRequest(url, 'DELETE');

// Global toast alert helper
window.showToast = (message, type = 'success') => {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast align-items-center text-white bg-${type === 'danger' ? 'danger' : 'success'} border-0 show glass-card mb-2`;
    toast.role = 'alert';
    toast.ariaLive = 'assertive';
    toast.ariaAtomic = 'true';

    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">
                <i class="bi bi-${type === 'success' ? 'check-circle' : 'exclamation-triangle'} me-2"></i>
                ${message}
            </div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
        </div>
    `;

    container.appendChild(toast);

    // Auto-remove after 4 seconds
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 4000);
};

document.addEventListener('DOMContentLoaded', () => {
    // Sidebar toggle
    const sidebarToggle = document.getElementById('sidebar-toggle');
    const sidebar = document.getElementById('sidebar');
    const mainContent = document.getElementById('main-content');

    if (sidebarToggle && sidebar && mainContent) {
        sidebarToggle.addEventListener('click', () => {
            sidebar.classList.toggle('collapsed');
            mainContent.classList.toggle('expanded');
        });
    }

    // Theme toggle
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
        themeToggle.addEventListener('click', () => {
            const html = document.documentElement;
            const currentTheme = html.getAttribute('data-theme') || 'dark';
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            html.setAttribute('data-theme', newTheme);
            
            const icon = themeToggle.querySelector('i');
            if (icon) {
                icon.className = newTheme === 'dark' ? 'bi bi-moon-stars' : 'bi bi-sun';
            }
            
            // Persist theme to settings
            fetch('/api/settings-data', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ theme: newTheme })
            }).catch(err => console.warn('Failed to persist theme:', err));
        });
    }
});

// Global HTML Escaping Helper (for XSS prevention)
window.escHtml = (text) => {
    if (text === null || text === undefined) return '';
    const temp = document.createElement('div');
    temp.textContent = text;
    return temp.innerHTML;
};

// Global Relative Time Helper
window.timeAgo = (dateString) => {
    if (!dateString) return 'Never';
    try {
        const date = new Date(dateString);
        const now = new Date();
        const seconds = Math.floor((now - date) / 1000);
        
        if (isNaN(seconds)) return 'Unknown';
        if (seconds < 0) return 'Just now';

        const intervals = {
            year: 31536000,
            month: 2592000,
            week: 604800,
            day: 86400,
            hour: 3600,
            minute: 60,
            second: 1
        };

        for (const [unit, value] of Object.entries(intervals)) {
            const count = Math.floor(seconds / value);
            if (count >= 1) {
                return `${count} ${unit}${count > 1 ? 's' : ''} ago`;
            }
        }
        return 'Just now';
    } catch (e) {
        return 'Unknown';
    }
};
