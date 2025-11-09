// Main application initialization

import { loadEntries } from './api.js';
import { startUsagePolling } from './usage.js';
import { initializeEventListeners, toggleAutoRefresh } from './events.js';
import { initializeModalListeners } from './modals.js';

// Initialize the application
document.addEventListener('DOMContentLoaded', () => {
    // Initialize modal listeners
    initializeModalListeners();

    // Initialize event listeners
    initializeEventListeners();

    // Initial load
    loadEntries();
    startUsagePolling();

    // Enable auto-refresh by default
    document.getElementById('autoRefreshCheck').checked = true;
    toggleAutoRefresh();
});
