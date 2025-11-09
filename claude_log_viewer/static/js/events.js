// Event handlers and listeners

import { autoRefreshInterval, setAutoRefreshInterval } from './state.js';
import { loadEntries } from './api.js';
import { renderEntries } from './entries.js';

export function toggleAutoRefresh() {
    const checkbox = document.getElementById('autoRefreshCheck');
    const container = document.getElementById('autoRefresh');
    const intervalSelect = document.getElementById('refreshInterval');

    if (checkbox.checked) {
        container.classList.add('active');
        const intervalMs = parseInt(intervalSelect.value) * 1000;
        const interval = setInterval(loadEntries, intervalMs);
        setAutoRefreshInterval(interval);
    } else {
        container.classList.remove('active');
        if (autoRefreshInterval) {
            clearInterval(autoRefreshInterval);
            setAutoRefreshInterval(null);
        }
    }
}

export function updateAutoRefreshInterval() {
    const checkbox = document.getElementById('autoRefreshCheck');
    if (checkbox.checked) {
        // Restart with new interval
        toggleAutoRefresh(); // Stop
        checkbox.checked = false;
        setTimeout(() => {
            checkbox.checked = true;
            toggleAutoRefresh(); // Start with new interval
        }, 0);
    }
}

export function initializeEventListeners() {
    // Event listeners
    document.getElementById('refreshBtn').addEventListener('click', loadEntries);
    document.getElementById('searchInput').addEventListener('input', renderEntries);
    document.getElementById('typeFilter').addEventListener('change', renderEntries);
    document.getElementById('limitSelect').addEventListener('change', renderEntries);
    document.getElementById('autoRefreshCheck').addEventListener('change', toggleAutoRefresh);
    document.getElementById('refreshInterval').addEventListener('change', updateAutoRefreshInterval);
}
