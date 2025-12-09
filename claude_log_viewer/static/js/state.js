// Global state management

// Load selected fields from localStorage, or use defaults
function loadSelectedFields() {
    const saved = localStorage.getItem('selectedFields');
    if (saved) {
        try {
            return JSON.parse(saved); // Return as Array
        } catch (e) {
            console.error('Error loading selectedFields from localStorage:', e);
        }
    }
    return ['role', 'when', 'content', 'sessionId', 'content_tokens']; // Array instead of Set
}

export let allEntries = [];
export let selectedFields = loadSelectedFields(); // Now an Array
export let pendingSelectedFields = [...selectedFields]; // Working copy for drawer changes
export let autoRefreshInterval = null;
export let knownFields = new Set(); // Track known fields to avoid re-rendering
export let sessionColors = {}; // Map sessionId to color
export let selectedSession = null; // Currently selected session filter
export let currentPlanNavigation = null; // Track current plan navigation state: { session, currentIndex }
export let currentTodoNavigation = null; // Track current todo navigation state: { session, currentIndex }
export let renderedEntryIds = new Set(); // Track which entries are already in the DOM
export let allTodoData = {}; // Store all todo data from API, keyed by sessionId
export let currentFilters = { // Track current filter state
    search: '',
    type: '',
    session: null,
    limit: 100, // Default limit - will be updated from HTML
    fields: ['role', 'when', 'content', 'sessionId'] // Array instead of Set
};
export let lastSessionStats = {}; // Track previous session stats for incremental updates
export let usageRefreshInterval = null; // Interval for usage polling
export let currentViewMode = 'table'; // Current view mode: 'table' or 'timeline'
export let fullFileSearchActive = false; // Track if we're showing full file search results
export let fullFileSearchQuery = ''; // Track the query for full file search

// Setter functions to update state from other modules
export function setAllEntries(entries) {
    allEntries = entries;
}

export function setAutoRefreshInterval(interval) {
    autoRefreshInterval = interval;
}

export function setKnownFields(fields) {
    knownFields = fields;
}

export function setSelectedSession(session) {
    selectedSession = session;
}

export function setCurrentPlanNavigation(nav) {
    currentPlanNavigation = nav;
}

export function setCurrentTodoNavigation(nav) {
    currentTodoNavigation = nav;
}

export function setAllTodoData(data) {
    allTodoData = data;
}

export function setLastSessionStats(stats) {
    lastSessionStats = stats;
}

export function setUsageRefreshInterval(interval) {
    usageRefreshInterval = interval;
}

export function setCurrentViewMode(mode) {
    currentViewMode = mode;
}

export function setFullFileSearchActive(active, query = '') {
    fullFileSearchActive = active;
    fullFileSearchQuery = query;
}

// Save selected fields to localStorage
export function saveSelectedFields() {
    try {
        localStorage.setItem('selectedFields', JSON.stringify(selectedFields)); // Already an Array
    } catch (e) {
        console.error('Error saving selectedFields to localStorage:', e);
    }
}

// Apply pending changes to selected fields
export function applyPendingFields() {
    selectedFields = [...pendingSelectedFields];
    saveSelectedFields();
}

// Update pending selected fields
export function setPendingSelectedFields(fields) {
    pendingSelectedFields = fields;
}
