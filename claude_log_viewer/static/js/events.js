// Event handlers and listeners

import { autoRefreshInterval, selectedFields, currentViewMode, selectedSession, setAutoRefreshInterval, setPendingSelectedFields, applyPendingFields, setCurrentViewMode } from './state.js';
import { loadEntries } from './api.js';
import { renderEntries, renderFieldSelector, renderColumnPreview } from './entries.js';

// Debounce function to limit how often a function is called
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Parse search input for special filters (file:path, etc.)
function parseSearchInput(searchValue) {
    const filters = {
        q: '',
        file: null
    };

    // Check for file: prefix
    const fileMatch = searchValue.match(/file:(\S+)/);
    if (fileMatch) {
        filters.file = fileMatch[1];
        // Remove file: from search term, keep rest as search query
        filters.q = searchValue.replace(/file:\S+/, '').trim();
    } else {
        filters.q = searchValue.trim();
    }

    return filters;
}

// Get current filter values from UI
function getCurrentFilters() {
    const searchValue = document.getElementById('searchInput').value;
    const parsed = parseSearchInput(searchValue);

    return {
        q: parsed.q,
        file: parsed.file,
        type: document.getElementById('typeFilter').value,
        session: selectedSession,
        limit: document.getElementById('limitSelect').value
    };
}

// Load entries with current filters (debounced for search input)
const debouncedLoadWithFilters = debounce(() => {
    const searchValue = document.getElementById('searchInput').value;
    // If --all flag is present, just trigger renderEntries (handles full file search)
    if (searchValue.includes('--all')) {
        renderEntries();
        return;
    }
    loadEntries(getCurrentFilters());
}, 300);

// Load entries with current filters (immediate, for dropdowns)
function loadWithFilters() {
    const searchValue = document.getElementById('searchInput').value;
    // If --all flag is present, just trigger renderEntries (handles full file search)
    if (searchValue.includes('--all')) {
        renderEntries();
        return;
    }
    loadEntries(getCurrentFilters());
}

export function toggleAutoRefresh() {
    const checkbox = document.getElementById('autoRefreshCheck');
    const container = document.getElementById('autoRefresh');
    const intervalSelect = document.getElementById('refreshInterval');

    if (checkbox.checked) {
        container.classList.add('active');
        const intervalMs = parseInt(intervalSelect.value) * 1000;
        const interval = setInterval(loadWithFilters, intervalMs);
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
    // Event listeners - filters now trigger server-side search
    document.getElementById('refreshBtn').addEventListener('click', loadWithFilters);
    document.getElementById('searchInput').addEventListener('input', debouncedLoadWithFilters);
    document.getElementById('typeFilter').addEventListener('change', loadWithFilters);
    document.getElementById('limitSelect').addEventListener('change', loadWithFilters);
    document.getElementById('autoRefreshCheck').addEventListener('change', toggleAutoRefresh);
    document.getElementById('refreshInterval').addEventListener('change', updateAutoRefreshInterval);

    // View toggle listener
    document.getElementById('viewToggleBtn').addEventListener('click', () => {
        const newMode = currentViewMode === 'table' ? 'timeline' : 'table';
        setCurrentViewMode(newMode);

        // Update button appearance
        const icon = document.getElementById('viewToggleIcon');
        const label = document.getElementById('viewToggleLabel');
        if (newMode === 'timeline') {
            icon.textContent = '📊';
            label.textContent = 'Timeline';
        } else {
            icon.textContent = '📋';
            label.textContent = 'Table';
        }

        // Re-render with new view
        renderEntries();
    });

    // Drawer toggle listeners
    document.getElementById('fieldSelectorBtn').addEventListener('click', toggleDrawer);
    document.getElementById('drawerClose').addEventListener('click', closeDrawer);
    document.getElementById('drawerOverlay').addEventListener('click', closeDrawer);

    // Field search listener
    document.getElementById('fieldSearch').addEventListener('input', (e) => {
        renderFieldSelector(e.target.value);
    });
}
