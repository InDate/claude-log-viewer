// Event handlers and listeners

import { autoRefreshInterval, selectedFields, setAutoRefreshInterval, setPendingSelectedFields, applyPendingFields } from './state.js';
import { loadEntries } from './api.js';
import { renderEntries, renderFieldSelector, renderColumnPreview } from './entries.js';

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

function toggleDrawer() {
    const drawer = document.getElementById('fieldSelectorDrawer');
    const overlay = document.getElementById('drawerOverlay');

    const isOpening = !drawer.classList.contains('active');

    if (isOpening) {
        // Reset pending state to current selected fields when opening
        setPendingSelectedFields([...selectedFields]);
        renderColumnPreview();
        renderFieldSelector();
    }

    drawer.classList.toggle('active');
    overlay.classList.toggle('active');
}

function closeDrawer() {
    const drawer = document.getElementById('fieldSelectorDrawer');
    const overlay = document.getElementById('drawerOverlay');

    // Apply pending changes to selected fields
    applyPendingFields();

    // Re-render table with new column order
    renderEntries();

    drawer.classList.remove('active');
    overlay.classList.remove('active');
}

export function initializeEventListeners() {
    // Event listeners
    document.getElementById('refreshBtn').addEventListener('click', loadEntries);
    document.getElementById('searchInput').addEventListener('input', renderEntries);
    document.getElementById('typeFilter').addEventListener('change', renderEntries);
    document.getElementById('limitSelect').addEventListener('change', renderEntries);
    document.getElementById('autoRefreshCheck').addEventListener('change', toggleAutoRefresh);
    document.getElementById('refreshInterval').addEventListener('change', updateAutoRefreshInterval);

    // Drawer toggle listeners
    document.getElementById('fieldSelectorBtn').addEventListener('click', toggleDrawer);
    document.getElementById('drawerClose').addEventListener('click', closeDrawer);
    document.getElementById('drawerOverlay').addEventListener('click', closeDrawer);

    // Field search listener
    document.getElementById('fieldSearch').addEventListener('input', (e) => {
        renderFieldSelector(e.target.value);
    });
}
