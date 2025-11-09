// API calls and data loading

import { allEntries, setAllEntries, setAllTodoData, setKnownFields, knownFields } from './state.js';
import { unpackEntry } from './utils.js';
import { renderSessionSummary, updateStats } from './sessions.js';
import { renderFieldSelector, renderEntries } from './entries.js';

// Fetch usage snapshots and convert to entry format
export async function fetchUsageSnapshots() {
    try {
        // Get time range from all entries
        if (allEntries.length === 0) return [];

        const timestamps = allEntries
            .map(e => e.timestamp)
            .filter(t => t);

        if (timestamps.length === 0) return [];

        const startTime = timestamps[timestamps.length - 1]; // Oldest
        const endTime = timestamps[0]; // Newest

        const response = await fetch(`/api/usage-snapshots?start=${encodeURIComponent(startTime)}&end=${encodeURIComponent(endTime)}`);
        const data = await response.json();

        if (data.error) {
            console.error('Error fetching usage snapshots:', data.error);
            return [];
        }

        // Convert snapshots to entry format
        return data.snapshots.map(snapshot => ({
            type: 'usage-increment',
            timestamp: snapshot.timestamp,
            sessionId: null, // Snapshots are global, not tied to a session
            content: 'Usage Increment',
            content_display: formatUsageSnapshot(snapshot),
            snapshot: snapshot,
            _isSnapshot: true
        }));
    } catch (error) {
        console.error('Error fetching usage snapshots:', error);
        return [];
    }
}

// Format usage snapshot for display
function formatUsageSnapshot(snapshot) {
    const fiveHourPct = snapshot.five_hour_pct ? snapshot.five_hour_pct.toFixed(1) : '0.0';
    const sevenDayPct = snapshot.seven_day_pct ? snapshot.seven_day_pct.toFixed(1) : '0.0';

    return `📊 Usage Update: 5h: ${fiveHourPct}% utilization | 7d: ${sevenDayPct}% utilization`;
}

// Load initial data
export async function loadEntries() {
    try {
        // First fetch entries to determine active sessions
        const entriesResponse = await fetch('/api/entries');
        const data = await entriesResponse.json();

        // Unpack all entries
        let entries = data.entries.map(unpackEntry);

        // Get unique session IDs from entries
        const sessionIds = [...new Set(entries.map(e => e.sessionId).filter(id => id))];

        // Fetch todos only for active sessions
        const todosUrl = sessionIds.length > 0
            ? `/api/todos?sessions=${sessionIds.join(',')}`
            : '/api/todos';
        const todosResponse = await fetch(todosUrl);
        const todosData = await todosResponse.json();

        // Store todo data globally, grouped by session
        const todoData = {};
        if (todosData.todos) {
            todosData.todos.forEach(todoFile => {
                const sessionId = todoFile.sessionId;
                if (!todoData[sessionId]) {
                    todoData[sessionId] = [];
                }
                todoData[sessionId].push(todoFile);
            });
        }
        setAllTodoData(todoData);

        // Fetch and merge usage snapshots
        const snapshots = await fetchUsageSnapshots();
        if (snapshots.length > 0) {
            entries = [...entries, ...snapshots];
            // Re-sort by timestamp (newest first)
            entries.sort((a, b) => {
                const timeA = a.timestamp || '';
                const timeB = b.timestamp || '';
                return timeB.localeCompare(timeA);
            });
        }

        setAllEntries(entries);

        // Only update field selector if fields have changed
        const currentFields = new Set();
        entries.forEach(entry => {
            Object.keys(entry).forEach(key => currentFields.add(key));
        });

        // Check if fields changed
        const fieldsChanged = currentFields.size !== knownFields.size ||
            ![...currentFields].every(f => knownFields.has(f));

        if (fieldsChanged) {
            setKnownFields(currentFields);
            renderFieldSelector();
        }

        renderSessionSummary();
        updateStats();
        renderEntries();
    } catch (error) {
        console.error('Error loading entries:', error);
    }
}

// Load available fields
export async function loadFields() {
    try {
        const response = await fetch('/api/fields');
        const fields = await response.json();
        renderFieldSelector(fields);
    } catch (error) {
        console.error('Error loading fields:', error);
    }
}
