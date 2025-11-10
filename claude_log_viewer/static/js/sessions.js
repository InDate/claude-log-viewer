// Session statistics and card rendering

import { allEntries, selectedSession, lastSessionStats, allTodoData, setSelectedSession, setLastSessionStats, setCurrentViewMode } from './state.js';
import { getSessionColor, formatNumber, formatTimestamp } from './utils.js';
import { showPlanDialog, showTodoDialog } from './modals.js';

// Calculate session statistics
export function getSessionStats() {
    const sessions = {};

    // First pass: Find the most recent compact_boundary for each session
    const lastCompactTimestamp = {};
    allEntries.forEach(entry => {
        const sessionId = entry.sessionId || 'unknown';
        if (entry.type === 'system' && entry.subtype === 'compact_boundary') {
            // Store the timestamp of the most recent compact for this session
            if (!lastCompactTimestamp[sessionId] || entry.timestamp > lastCompactTimestamp[sessionId]) {
                lastCompactTimestamp[sessionId] = entry.timestamp;
            }
        }
    });

    allEntries.forEach(entry => {
        const sessionId = entry.sessionId || 'unknown';

        if (!sessions[sessionId]) {
            sessions[sessionId] = {
                id: sessionId,
                messageCount: 0,
                lastActive: null,
                tokensUsed: 0,
                timestamps: [],
                todoEntries: [], // Track TodoWrite entries with timestamps
                planEntries: [] // Track ExitPlanMode entries with timestamps
            };
        }

        sessions[sessionId].messageCount++;

        if (entry.timestamp) {
            sessions[sessionId].timestamps.push(entry.timestamp);
        }

        // Sum up token usage from actual content (tiktoken counts)
        // Only count tokens from entries AT OR AFTER the most recent compact
        if (entry.content_tokens !== undefined && entry.content_tokens !== null) {
            const lastCompact = lastCompactTimestamp[sessionId];
            // If no compact, or entry is at/after the last compact, count the tokens
            if (!lastCompact || entry.timestamp >= lastCompact) {
                sessions[sessionId].tokensUsed += entry.content_tokens;
            }
        }

        // Extract ExitPlanMode tool uses (plans)
        if (entry.tool_items && entry.tool_items.tool_uses) {
            entry.tool_items.tool_uses.forEach(toolUse => {
                if (toolUse.name === 'ExitPlanMode' && toolUse.input && toolUse.input.plan) {
                    sessions[sessionId].planEntries.push({
                        timestamp: entry.timestamp,
                        plan: toolUse.input.plan
                    });
                }
            });
        }
    });

    // Calculate last active and process todos for each session
    Object.values(sessions).forEach(session => {
        if (session.timestamps.length > 0) {
            session.lastActive = session.timestamps.sort().reverse()[0];
        }

        // Get todos from API data instead of JSONL
        const sessionTodos = allTodoData[session.id] || [];
        if (sessionTodos.length > 0) {
            // Store all todo entries for navigation
            session.todoEntries = sessionTodos.map(todoFile => ({
                timestamp: todoFile.timestamp,
                todos: todoFile.todos,
                agentId: todoFile.agentId,
                filename: todoFile.filename
            }));

            // Sort by timestamp (newest first)
            session.todoEntries.sort((a, b) => b.timestamp.localeCompare(a.timestamp));

            // Use latest entry with non-empty todos, fallback to first entry
            const latestTodoEntry = session.todoEntries.find(e => e.todos && e.todos.length > 0) || session.todoEntries[0];
            session.todos = latestTodoEntry.todos;

            // Calculate todo stats
            const stats = {
                total: session.todos.length,
                completed: session.todos.filter(t => t.status === 'completed').length,
                inProgress: session.todos.filter(t => t.status === 'in_progress').length,
                pending: session.todos.filter(t => t.status === 'pending').length
            };

            session.todoStats = stats;
            session.hasTodos = stats.total > 0;
        } else {
            session.todoEntries = [];
        }

        // Get latest plan (most recent timestamp)
        if (session.planEntries.length > 0) {
            const latestPlanEntry = session.planEntries.sort((a, b) =>
                b.timestamp.localeCompare(a.timestamp)
            )[0];

            session.latestPlan = latestPlanEntry.plan;
            session.planCount = session.planEntries.length;
            session.hasPlans = true;
        }

        // Session has timeline if it has messages
        session.hasTimeline = session.messageCount > 0;
    });

    return Object.values(sessions).sort((a, b) => {
        // Sort by last active (most recent first)
        if (a.lastActive && b.lastActive) {
            return b.lastActive.localeCompare(a.lastActive);
        }
        return 0;
    });
}

// Render session summary cards
export function renderSessionSummary() {
    const container = document.getElementById('sessionCards');
    const sessions = getSessionStats();

    // Build map of current sessions
    const currentSessions = {};
    sessions.forEach(s => {
        currentSessions[s.id] = s;
    });

    // Check if we need full rebuild
    const sessionIds = Object.keys(currentSessions);
    const lastSessionIds = Object.keys(lastSessionStats);

    // Check if todo/plan data changed for any session (compare file modification timestamps)
    const todoOrPlanChanged = sessionIds.some(id => {
        const current = currentSessions[id];
        const last = lastSessionStats[id];
        if (!last) return true;

        // Check if todo file timestamps changed
        const currentTodoTimestamps = (current.todoEntries || []).map(t => t.timestamp).sort().join(',');
        const lastTodoTimestamps = (last.todoEntries || []).map(t => t.timestamp).sort().join(',');
        if (currentTodoTimestamps !== lastTodoTimestamps) return true;

        // Check if plan timestamps changed
        const currentPlanTimestamps = (current.planEntries || []).map(p => p.timestamp).sort().join(',');
        const lastPlanTimestamps = (last.planEntries || []).map(p => p.timestamp).sort().join(',');
        if (currentPlanTimestamps !== lastPlanTimestamps) return true;

        return false;
    });

    const needsRebuild = sessionIds.length !== lastSessionIds.length ||
        !sessionIds.every(id => lastSessionIds.includes(id)) ||
        todoOrPlanChanged;

    if (needsRebuild) {
        // Full rebuild
        container.innerHTML = '';

        sessions.forEach(session => {
            const color = getSessionColor(session.id);

            const card = document.createElement('div');
            card.className = 'session-card';
            card.dataset.sessionId = session.id;
            if (selectedSession === session.id) {
                card.classList.add('selected');
            }
            card.style.borderLeftColor = color;

            // Calculate context percentage (assume 200K limit)
            const contextLimit = 200000;
            const contextPct = (session.tokensUsed / contextLimit) * 100;
            const contextClass = contextPct < 70 ? 'low' : (contextPct < 90 ? 'medium' : 'high');

            const todoHTML = session.hasTodos ? `
                <div class="session-stat session-todo-summary" data-session-id="${session.id}">
                    <span class="session-stat-label">Todos:</span>
                    <span class="session-stat-value" style="color: #9d9d9d;">
                        ${session.todoStats.total} total:
                        <span style="color: #4ec9b0;">${session.todoStats.completed} done</span>,
                        ${session.todoStats.pending} pending
                    </span>
                </div>
            ` : '';

            const planHTML = session.hasPlans ? `
                <div class="session-stat session-plan-summary" data-session-id="${session.id}">
                    <span class="session-stat-label">Plans:</span>
                    <span class="session-stat-value" style="color: #9d9d9d;">
                        ${session.planCount} ${session.planCount === 1 ? 'plan' : 'plans'}
                    </span>
                </div>
            ` : '';

            card.innerHTML = `
                <div class="session-icon-actions">
                    <div class="session-icon-btn" data-action="filter" title="Toggle filter">
                        <div class="icon">🔍</div>
                        <div class="label">Filter</div>
                    </div>
                    ${session.hasPlans ? `
                    <div class="session-icon-btn" data-action="plans" title="View plans">
                        <div class="icon">📋</div>
                        <div class="label">Plans</div>
                    </div>
                    ` : ''}
                    ${session.hasTodos ? `
                    <div class="session-icon-btn" data-action="todos" title="View todos">
                        <div class="icon">☑</div>
                        <div class="label">Todos</div>
                    </div>
                    ` : ''}
                    ${session.hasTimeline ? `
                    <div class="session-icon-btn" data-action="timeline" title="View timeline">
                        <div class="icon">📊</div>
                        <div class="label">Timeline</div>
                    </div>
                    ` : ''}
                </div>
                <div class="session-id">
                    <span class="session-color-badge" style="background: ${color}; color: #fff;">
                        ${session.id.substring(0, 8)}
                    </span>
                </div>
                <div class="session-stats">
                    <div class="session-stat">
                        <span class="session-stat-label">Messages:</span>
                        <span class="session-stat-value" data-stat="messageCount">${session.messageCount}</span>
                    </div>
                    <div class="session-stat">
                        <span class="session-stat-label">Last Active:</span>
                        <span class="session-stat-value" data-stat="lastActive">${formatTimestamp(session.lastActive)}</span>
                    </div>
                    <div class="session-stat">
                        <span class="session-stat-label">Context:</span>
                        <span class="session-stat-value usage-value ${contextClass}" data-stat="tokensUsed" style="padding: 2px 6px; font-size: 10px;">
                            ${formatNumber(session.tokensUsed)} / 200K (${contextPct.toFixed(1)}%)
                        </span>
                    </div>
                    ${planHTML}
                    ${todoHTML}
                </div>
            `;

            // Add icon action handlers
            const iconButtons = card.querySelectorAll('.session-icon-btn');
            iconButtons.forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const action = btn.dataset.action;

                    if (action === 'filter') {
                        // Toggle filter
                        if (selectedSession === session.id) {
                            setSelectedSession(null);
                        } else {
                            setSelectedSession(session.id);
                        }

                        // Update selected state and filter button active state on all cards
                        container.querySelectorAll('.session-card').forEach(c => {
                            if (c.dataset.sessionId === selectedSession) {
                                c.classList.add('selected');
                                c.querySelector('[data-action="filter"]')?.classList.add('active');
                            } else {
                                c.classList.remove('selected');
                                c.querySelector('[data-action="filter"]')?.classList.remove('active');
                            }
                        });

                        // Import renderEntries dynamically to avoid circular dependency
                        import('./entries.js').then(module => module.renderEntries());
                    } else if (action === 'plans') {
                        showPlanDialog(session);
                    } else if (action === 'todos') {
                        showTodoDialog(session);
                    } else if (action === 'timeline') {
                        // Switch to timeline view and filter to this session
                        setSelectedSession(session.id);
                        setCurrentViewMode('timeline');

                        // Update filter button active state
                        container.querySelectorAll('.session-card').forEach(c => {
                            if (c.dataset.sessionId === session.id) {
                                c.classList.add('selected');
                                c.querySelector('[data-action="filter"]')?.classList.add('active');
                            } else {
                                c.classList.remove('selected');
                                c.querySelector('[data-action="filter"]')?.classList.remove('active');
                            }
                        });

                        // Render timeline view
                        import('./entries.js').then(module => module.renderEntries());
                    }
                });
            });

            // Set initial active state for filter button if this session is selected
            if (selectedSession === session.id) {
                card.querySelector('[data-action="filter"]')?.classList.add('active');
            }

            container.appendChild(card);
        });

        setLastSessionStats(currentSessions);
    } else {
        // Incremental update - only update changed stats
        sessions.forEach(session => {
            const lastStats = lastSessionStats[session.id];

            if (lastStats) {
                const card = container.querySelector(`[data-session-id="${session.id}"]`);

                if (card) {
                    // Update only changed values
                    if (session.messageCount !== lastStats.messageCount) {
                        const elem = card.querySelector('[data-stat="messageCount"]');
                        if (elem) elem.textContent = session.messageCount;
                    }

                    if (session.lastActive !== lastStats.lastActive) {
                        const elem = card.querySelector('[data-stat="lastActive"]');
                        if (elem) elem.textContent = formatTimestamp(session.lastActive);
                    }

                    if (session.tokensUsed !== lastStats.tokensUsed) {
                        const elem = card.querySelector('[data-stat="tokensUsed"]');
                        if (elem) {
                            const contextLimit = 200000;
                            const contextPct = (session.tokensUsed / contextLimit) * 100;
                            const contextClass = contextPct < 70 ? 'low' : (contextPct < 90 ? 'medium' : 'high');

                            // Update classes
                            elem.className = `session-stat-value usage-value ${contextClass}`;
                            elem.textContent = `${formatNumber(session.tokensUsed)} / 200K (${contextPct.toFixed(1)}%)`;
                        }
                    }
                }
            }
        });

        setLastSessionStats(currentSessions);
    }
}

// Update stats display
export function updateStats() {
    const stats = document.getElementById('stats');
    const typeFilter = document.getElementById('typeFilter').value;
    const searchTerm = document.getElementById('searchInput').value.toLowerCase();

    let filtered = allEntries;
    if (typeFilter) {
        if (typeFilter === 'tool_result') {
            filtered = filtered.filter(e => e.has_tool_results);
        } else {
            filtered = filtered.filter(e => e.type === typeFilter);
        }
    }
    if (searchTerm) {
        filtered = filtered.filter(e =>
            JSON.stringify(e).toLowerCase().includes(searchTerm)
        );
    }

    stats.textContent = `Showing ${filtered.length} of ${allEntries.length} entries`;
}
