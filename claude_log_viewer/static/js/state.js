// Global state management

export let allEntries = [];
export let selectedFields = new Set(['role', 'when', 'content', 'sessionId', 'content_tokens']);
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
    fields: new Set(['role', 'when', 'content', 'sessionId'])
};
export let lastSessionStats = {}; // Track previous session stats for incremental updates
export let usageRefreshInterval = null; // Interval for usage polling

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
