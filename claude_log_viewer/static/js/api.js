// API calls and data loading

import { setAllEntries, setAllTodoData, setKnownFields, knownFields } from './state.js';
import { unpackEntry } from './utils.js';
import { renderSessionSummary, updateStats } from './sessions.js';
import { renderFieldSelector, renderEntries, clearFieldExamplesCache } from './entries.js';

// Load initial data
export async function loadEntries() {
    try {
        // Fetch entries (now includes usage snapshots merged by backend)
        const entriesResponse = await fetch('/api/entries');
        const data = await entriesResponse.json();

        // Unpack all entries
        const entries = data.entries.map(unpackEntry);

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

        setAllEntries(entries);
        clearFieldExamplesCache(); // Clear cache when entries change

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

// Load timeline graph for a session
export async function loadTimelineGraph(sessionId) {
    try {
        const response = await fetch(`/api/timeline?session_id=${sessionId}`);
        const data = await response.json();
        return data; // { nodes, edges, lanes, stats }
    } catch (error) {
        console.error('Error loading timeline:', error);
        throw error;
    }
}
