// Entry rendering and field selection

import { allEntries, selectedFields, pendingSelectedFields, currentFilters, selectedSession, renderedEntryIds, knownFields, saveSelectedFields, setPendingSelectedFields, currentViewMode } from './state.js';
import { getEntryId, getSessionColor, truncateContent, formatRelativeTime, copyToClipboard, formatNumber, formatTimestamp, getUsageClass } from './utils.js';
import { showContentDialog, showToolDetailsDialog, showTimelinePlanDialog, showTimelineTodoDialog } from './modals.js';
import { updateStats } from './sessions.js';
import { loadTimelineGraph } from './api.js';

// Cache for field examples (performance optimization)
let fieldExamplesCache = new Map();

// Build field examples cache in a single pass through entries
function buildFieldExamplesCache() {
    fieldExamplesCache.clear();

    // Collect all fields first
    const allFields = new Set();
    allEntries.forEach(entry => {
        Object.keys(entry).forEach(key => allFields.add(key));
    });

    // Add virtual fields
    allFields.add('when');
    allFields.add('tokens');

    // Find examples in single pass through entries
    const fieldsFound = new Set();

    for (const entry of allEntries) {
        for (const field of allFields) {
            if (!fieldExamplesCache.has(field)) {
                const value = entry[field];
                if (value !== null && value !== undefined && value !== '') {
                    const str = typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
                    fieldExamplesCache.set(field, {
                        full: str,
                        truncated: str.length > 60 ? str.substring(0, 60) + '...' : str
                    });
                    fieldsFound.add(field);

                    // Early exit if we found examples for all fields
                    if (fieldsFound.size === allFields.size) {
                        return;
                    }
                }
            }
        }
    }

    // Add empty examples for fields without values
    for (const field of allFields) {
        if (!fieldExamplesCache.has(field)) {
            fieldExamplesCache.set(field, { full: '', truncated: '' });
        }
    }
}

// Get example value for a field (from cache)
function getFieldExample(field) {
    return fieldExamplesCache.get(field) || { full: '', truncated: '' };
}

// Clear cache (called when entries change)
export function clearFieldExamplesCache() {
    fieldExamplesCache.clear();
}

// Render column preview chips with drag-and-drop
export function renderColumnPreview() {
    const container = document.getElementById('previewColumns');
    container.innerHTML = '';

    pendingSelectedFields.forEach((field, index) => {
        const chip = document.createElement('div');
        chip.className = 'column-chip';
        chip.draggable = true;
        chip.dataset.field = field;
        chip.dataset.index = index;

        // Drag handle icon
        const dragHandle = document.createElement('span');
        dragHandle.className = 'drag-handle';
        dragHandle.textContent = '⋮⋮';

        // Field name
        const fieldName = document.createElement('span');
        fieldName.textContent = field;

        // Remove button
        const removeBtn = document.createElement('span');
        removeBtn.className = 'remove-btn';
        removeBtn.textContent = '×';
        removeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const newPending = pendingSelectedFields.filter(f => f !== field);
            setPendingSelectedFields(newPending);
            renderColumnPreview();
            renderFieldSelector(); // Update checkboxes
        });

        chip.appendChild(dragHandle);
        chip.appendChild(fieldName);
        chip.appendChild(removeBtn);

        // Drag event handlers
        chip.addEventListener('dragstart', (e) => {
            chip.classList.add('dragging');
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', index);
        });

        chip.addEventListener('dragend', () => {
            chip.classList.remove('dragging');
            // Remove all drag-over classes
            document.querySelectorAll('.column-chip').forEach(c => c.classList.remove('drag-over'));
        });

        chip.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';

            const draggingChip = container.querySelector('.dragging');
            if (draggingChip && draggingChip !== chip) {
                chip.classList.add('drag-over');
            }
        });

        chip.addEventListener('dragleave', () => {
            chip.classList.remove('drag-over');
        });

        chip.addEventListener('drop', (e) => {
            e.preventDefault();
            chip.classList.remove('drag-over');

            const fromIndex = parseInt(e.dataTransfer.getData('text/plain'));
            const toIndex = parseInt(chip.dataset.index);

            if (fromIndex !== toIndex) {
                const newPending = [...pendingSelectedFields];
                const [movedField] = newPending.splice(fromIndex, 1);
                newPending.splice(toIndex, 0, movedField);
                setPendingSelectedFields(newPending);
                renderColumnPreview();
            }
        });

        container.appendChild(chip);
    });
}

// Render field selector
export function renderFieldSelector(searchTerm = '') {
    const container = document.getElementById('fieldSelector');
    container.innerHTML = '';

    // Build cache if empty (performance optimization)
    if (fieldExamplesCache.size === 0) {
        buildFieldExamplesCache();
    }

    // Get all unique fields from unpacked entries
    const allFields = new Set();
    allEntries.forEach(entry => {
        Object.keys(entry).forEach(key => allFields.add(key));
    });

    // Add virtual computed fields
    allFields.add('when');
    allFields.add('tokens');

    // Sort alphabetically
    const sortedFields = Array.from(allFields).sort((a, b) => a.localeCompare(b));

    // Filter by search term
    const fieldsWithExamples = sortedFields.map(field => ({
        name: field,
        example: getFieldExample(field)
    }));

    const filteredFields = searchTerm
        ? fieldsWithExamples.filter(({ name, example }) => {
            const term = searchTerm.toLowerCase();
            return name.toLowerCase().includes(term) ||
                   example.full.toLowerCase().includes(term) ||
                   example.truncated.toLowerCase().includes(term);
        })
        : fieldsWithExamples;

    // Render filtered fields
    filteredFields.forEach(({ name, example }) => {
        container.appendChild(createFieldCheckbox(name, example));
    });
}

function createFieldCheckbox(field, example) {
    const div = document.createElement('div');
    div.className = 'field-item';

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.id = `field-${field}`;
    checkbox.checked = pendingSelectedFields.includes(field);
    checkbox.addEventListener('change', () => {
        const newPending = [...pendingSelectedFields];
        if (checkbox.checked) {
            if (!newPending.includes(field)) {
                newPending.push(field);
            }
        } else {
            const index = newPending.indexOf(field);
            if (index > -1) {
                newPending.splice(index, 1);
            }
        }
        setPendingSelectedFields(newPending);
        renderColumnPreview(); // Update preview chips
    });

    const fieldInfo = document.createElement('div');
    fieldInfo.className = 'field-info';

    const fieldName = document.createElement('div');
    fieldName.className = 'field-name';
    fieldName.textContent = field;

    const fieldExample = document.createElement('div');
    fieldExample.className = 'field-example';

    const expandIcon = document.createElement('span');
    expandIcon.className = 'expand-icon';
    expandIcon.textContent = '▶';

    const exampleContent = document.createElement('span');
    exampleContent.className = 'field-example-content';
    exampleContent.textContent = example.truncated || '(no example available)';
    exampleContent.title = example.full; // Show full text on hover

    fieldExample.appendChild(expandIcon);
    fieldExample.appendChild(exampleContent);

    fieldInfo.appendChild(fieldName);
    fieldInfo.appendChild(fieldExample);

    div.appendChild(checkbox);
    div.appendChild(fieldInfo);

    // Handle field expansion
    let isExpanded = false;
    let expandedDiv = null;

    fieldExample.addEventListener('click', (e) => {
        e.stopPropagation();
        isExpanded = !isExpanded;

        if (isExpanded) {
            div.classList.add('expanded');
            expandIcon.textContent = '▼';

            // Create expanded markdown view
            if (!expandedDiv) {
                expandedDiv = document.createElement('div');
                expandedDiv.className = 'field-example-expanded';

                // Render as markdown
                const md = window.markdownit({
                    highlight: function (str, lang) {
                        if (lang && hljs.getLanguage(lang)) {
                            try {
                                return hljs.highlight(str, { language: lang }).value;
                            } catch (__) {}
                        }
                        return '';
                    }
                });

                try {
                    expandedDiv.innerHTML = md.render(example.full);
                } catch (e) {
                    // Fall back to plain text if markdown fails
                    expandedDiv.textContent = example.full;
                }

                fieldInfo.appendChild(expandedDiv);
            } else {
                expandedDiv.style.display = 'block';
            }
        } else {
            div.classList.remove('expanded');
            expandIcon.textContent = '▶';
            if (expandedDiv) {
                expandedDiv.style.display = 'none';
            }
        }
    });

    // Make entire div clickable for checkbox (but not example)
    div.addEventListener('click', (e) => {
        if (e.target !== checkbox && !fieldExample.contains(e.target)) {
            checkbox.click();
        }
    });

    return div;
}

// Check if filters have changed
function filtersChanged() {
    const typeFilter = document.getElementById('typeFilter').value;
    const searchTerm = document.getElementById('searchInput').value.toLowerCase();
    const limit = parseInt(document.getElementById('limitSelect').value);

    // Check if selected fields changed (Array comparison)
    const fieldsChanged = currentFilters.fields.length !== selectedFields.length ||
        !selectedFields.every((f, i) => currentFilters.fields[i] === f);

    return currentFilters.search !== searchTerm ||
           currentFilters.type !== typeFilter ||
           currentFilters.session !== selectedSession ||
           currentFilters.limit !== limit ||
           fieldsChanged;
}

// Update current filter state
function updateFilterState() {
    currentFilters.search = document.getElementById('searchInput').value.toLowerCase();
    currentFilters.type = document.getElementById('typeFilter').value;
    currentFilters.session = selectedSession;
    currentFilters.limit = parseInt(document.getElementById('limitSelect').value);
    currentFilters.fields = [...selectedFields]; // Store copy of Array
}

// Create a table row for an entry
function createEntryRow(entry) {
    const row = document.createElement('tr');
    row.dataset.entryId = getEntryId(entry);

    // Special handling for usage-increment rows
    if (entry.type === 'usage-increment' && entry._isSnapshot) {
        row.classList.add('usage-increment-row');

        // Create a single cell that spans all columns
        const td = document.createElement('td');
        td.colSpan = selectedFields.length;
        td.className = 'usage-increment-cell';

        const snapshot = entry.snapshot;
        const fiveHourPct = snapshot.five_hour_pct ? snapshot.five_hour_pct.toFixed(1) : '0.0';
        const sevenDayPct = snapshot.seven_day_pct ? snapshot.seven_day_pct.toFixed(1) : '0.0';
        const fiveHourClass = getUsageClass(snapshot.five_hour_pct || 0);
        const sevenDayClass = getUsageClass(snapshot.seven_day_pct || 0);

        // Check which windows have deltas (actually changed)
        const hasFiveHourDelta = (snapshot.five_hour_tokens_consumed !== null && snapshot.five_hour_tokens_consumed !== undefined);
        const hasSevenDayDelta = (snapshot.seven_day_tokens_consumed !== null && snapshot.seven_day_tokens_consumed !== undefined);

        // Format tokens and messages for display with "total (+delta)" format
        const formatStat = (totalTokens, totalMessages, deltaTokens, deltaMessages) => {
            if (totalTokens === null || totalTokens === undefined) return '—';
            const tokensStr = `${formatNumber(totalTokens)} (+${formatNumber(deltaTokens)})`;
            const messagesStr = `${totalMessages} (+${deltaMessages})`;
            return `${tokensStr} tokens | ${messagesStr} msgs`;
        };

        // Build stats HTML only for windows that changed - compact format
        let statsHTML = '';

        if (hasFiveHourDelta) {
            statsHTML += `
                <div class="usage-window">
                    <span class="window-label">5H</span>
                    <span class="window-percent usage-value ${fiveHourClass}">${fiveHourPct}%</span>
                    <span class="window-stats">Tokens: ${formatNumber(snapshot.five_hour_tokens_total)} <span class="stat-delta">(+${formatNumber(snapshot.five_hour_tokens_consumed)})</span> | Messages: ${snapshot.five_hour_messages_total} <span class="stat-delta">(+${snapshot.five_hour_messages_count})</span></span>
                </div>
            `;
        }

        if (hasSevenDayDelta) {
            statsHTML += `
                <div class="usage-window">
                    <span class="window-label">7D</span>
                    <span class="window-percent usage-value ${sevenDayClass}">${sevenDayPct}%</span>
                    <span class="window-stats">Tokens: ${formatNumber(snapshot.seven_day_tokens_total)} <span class="stat-delta">(+${formatNumber(snapshot.seven_day_tokens_consumed)})</span> | Messages: ${snapshot.seven_day_messages_total} <span class="stat-delta">(+${snapshot.seven_day_messages_count})</span></span>
                </div>
            `;
        }

        td.innerHTML = `
            <div class="usage-increment-container">
                <span class="usage-increment-icon">📊</span>
                <span class="usage-increment-title">Usage Increment</span>
                <span class="usage-increment-time">(${formatTimestamp(entry.timestamp)})</span>
                ${statsHTML}
            </div>
        `;

        row.appendChild(td);
        return row;
    }

    Array.from(selectedFields).forEach(fieldName => {
        const td = document.createElement('td');

        // Store the raw value for copying
        let copyValue = '';

        // Handle virtual fields and actual properties
        const hasField = fieldName === 'when' || fieldName === 'tokens' || fieldName === 'content' || entry.hasOwnProperty(fieldName);
        if (hasField) {
            // For content field, prefer content_display if available
            let fieldValue;
            if (fieldName === 'when') {
                fieldValue = null;
            } else if (fieldName === 'tokens') {
                fieldValue = null; // Will be computed during rendering
            } else if (fieldName === 'content' && entry.hasOwnProperty('content_display')) {
                fieldValue = entry['content_display'];
            } else if (fieldName === 'content') {
                // content field but no content_display, try regular content
                fieldValue = entry['content'] || null;
            } else {
                fieldValue = entry[fieldName];
            }

            // Set copy value based on field type
            if (typeof fieldValue === 'object' && fieldValue !== null) {
                copyValue = JSON.stringify(fieldValue, null, 2);
            } else {
                copyValue = String(fieldValue || '');
            }

            if (fieldName === 'type') {
                const span = document.createElement('span');
                span.className = `cell-type type-${fieldValue || 'other'}`;
                span.textContent = fieldValue || 'unknown';
                td.appendChild(span);
            } else if (fieldName === 'role') {
                const span = document.createElement('span');
                span.className = `cell-type role-${fieldValue || 'other'}`;
                span.textContent = fieldValue || '-';
                td.appendChild(span);
            } else if (fieldName === 'sessionId') {
                const color = getSessionColor(fieldValue);
                const span = document.createElement('span');
                span.className = 'session-color-badge';
                span.style.background = color;
                span.style.color = '#fff';
                span.textContent = fieldValue ? fieldValue.substring(0, 8) : '-';
                td.appendChild(span);
            } else if (fieldName === 'timestamp') {
                td.className = 'cell-timestamp';
                td.textContent = fieldValue || '-';
            } else if (fieldName === 'when') {
                // Special handling for 'when' field - compute from timestamp
                const relativeTime = formatRelativeTime(entry.timestamp);
                td.className = 'cell-when';
                td.textContent = relativeTime;
                copyValue = relativeTime; // Update copy value
            } else if (fieldName === 'tokens') {
                // Special handling for 'tokens' virtual field - combine input and output
                td.className = 'cell-tokens';
                td.style.textAlign = 'right';
                const inTokens = entry.input_tokens;
                const outTokens = entry.output_tokens;
                if ((inTokens !== undefined && inTokens !== 0) || (outTokens !== undefined && outTokens !== 0)) {
                    const inStr = inTokens ? inTokens.toLocaleString() : '0';
                    const outStr = outTokens ? outTokens.toLocaleString() : '0';
                    td.textContent = `↑${inStr} ↓${outStr}`;
                    copyValue = `in: ${inStr}, out: ${outStr}`;
                } else {
                    td.textContent = '-';
                }
            } else if (fieldName === 'content_tokens') {
                // Special handling for content token counts (from tiktoken)
                td.className = 'cell-tokens';
                td.style.textAlign = 'right';
                if (fieldValue !== undefined && fieldValue !== null && fieldValue !== 0) {
                    // Format as ~2.5k or ~156
                    let formatted;
                    if (fieldValue >= 1000) {
                        const kValue = fieldValue / 1000;
                        if (kValue >= 100) {
                            formatted = `~${Math.round(kValue)}k`;
                        } else {
                            formatted = `~${kValue.toFixed(1)}k`;
                        }
                    } else {
                        formatted = `~${fieldValue}`;
                    }
                    td.textContent = formatted;
                    copyValue = `${fieldValue} tokens`;
                } else {
                    td.textContent = '-';
                }
            } else if (fieldName === 'input_tokens' || fieldName === 'output_tokens') {
                // Special handling for API token fields
                td.className = 'cell-tokens';
                td.style.textAlign = 'right';
                if (fieldValue !== undefined && fieldValue !== null && fieldValue !== 0) {
                    // Format number with commas
                    td.textContent = fieldValue.toLocaleString();
                } else {
                    td.textContent = '-';
                }
            } else if (typeof fieldValue === 'object' && fieldValue !== null) {
                const pre = document.createElement('div');
                pre.className = 'cell-json';
                pre.textContent = JSON.stringify(fieldValue, null, 2);
                td.appendChild(pre);
            } else {
                const div = document.createElement('div');
                div.className = 'cell-text';

                const originalText = String(fieldValue || '-');
                const truncatedText = truncateContent(originalText);

                // Check if content has tool indicators and entry has tool_items data
                const hasToolIndicators = originalText.includes('🔧') || originalText.includes('✓');
                const hasToolItems = entry.tool_items &&
                    (entry.tool_items.tool_uses?.length > 0 || entry.tool_items.tool_results?.length > 0);

                if (truncatedText !== originalText) {
                    // Text was truncated, make it clickable to open in modal
                    div.classList.add('truncated');
                    div.textContent = truncatedText;

                    const indicator = document.createElement('span');
                    indicator.className = 'expand-indicator';
                    indicator.textContent = '▼ click to view';
                    div.appendChild(indicator);

                    // Open modal dialog on click
                    div.addEventListener('click', (e) => {
                        e.stopPropagation(); // Prevent copy-to-clipboard handler
                        showContentDialog(originalText);
                    });
                } else if (hasToolIndicators && hasToolItems) {
                    // Content has tool uses/results, make it clickable to show JSON
                    div.classList.add('has-tools');
                    div.textContent = originalText;

                    const indicator = document.createElement('span');
                    indicator.className = 'expand-indicator';
                    indicator.textContent = '▼ view details';
                    div.appendChild(indicator);

                    // Open modal with tool JSON on click
                    div.addEventListener('click', (e) => {
                        e.stopPropagation(); // Prevent copy-to-clipboard handler
                        showToolDetailsDialog(entry);
                    });
                } else {
                    div.textContent = originalText;
                }

                td.appendChild(div);
            }
        } else {
            td.textContent = '-';
            copyValue = '';
        }

        // Add click to copy handler
        if (copyValue) {
            td.addEventListener('click', (e) => {
                // Don't interfere with modal dialog clicks or expand indicator
                if (!e.target.classList.contains('expand-indicator') &&
                    !e.target.classList.contains('truncated')) {
                    copyToClipboard(copyValue);
                }
            });
        }

        row.appendChild(td);
    });

    return row;
}

// Timeline state cache for incremental updates
let timelineState = {
    sessionId: null,
    renderedNodeIds: new Set(),
    lastGraph: null,
    initialized: false
};

// Render timeline view using backend graph API
async function renderTimelineView(entries) {
    const container = document.getElementById('entriesContainer');

    if (!selectedSession) {
        container.innerHTML = '<div class="empty-state"><h2>Select a session</h2><p>Click the Timeline button on a session card to view its timeline</p></div>';
        timelineState.initialized = false;
        timelineState.sessionId = null;
        return;
    }

    // Session changed - reset state
    if (timelineState.sessionId !== selectedSession) {
        timelineState.sessionId = selectedSession;
        timelineState.renderedNodeIds.clear();
        timelineState.lastGraph = null;
        timelineState.initialized = false;
    }

    // Show loading only on first render
    if (!timelineState.initialized) {
        container.innerHTML = '<div class="loading-state"><h2>Loading timeline...</h2></div>';
    }

    try {
        // Fetch timeline graph from backend
        const graph = await loadTimelineGraph(selectedSession);

        if (!graph.nodes || graph.nodes.length === 0) {
            container.innerHTML = '<div class="empty-state"><h2>No timeline data</h2><p>This session has no graph data</p></div>';
            return;
        }

        // First render - build complete timeline
        if (!timelineState.initialized) {
            buildInitialTimeline(container, graph);
            timelineState.initialized = true;
            timelineState.lastGraph = graph;
            return;
        }

        // For structural timeline, rebuild if structural events changed
        // TODO: Implement proper incremental updates for structural events
        const eventsChanged = JSON.stringify(graph.structuralEvents) !== JSON.stringify(timelineState.lastGraph?.structuralEvents);

        if (eventsChanged) {
            // Preserve scroll position
            const scrollTop = container.scrollTop;

            // Rebuild timeline
            buildInitialTimeline(container, graph);

            // Restore scroll position
            container.scrollTop = scrollTop;
        } else {
            // Just update stats
            updateTimelineStats(graph.stats);
        }

        timelineState.lastGraph = graph;

    } catch (error) {
        console.error('Error rendering timeline:', error);
        if (!timelineState.initialized) {
            container.innerHTML = `<div class="empty-state"><h2>Error loading timeline</h2><p>${error.message}</p></div>`;
        }
    }
}

// Build initial timeline structure (first render only)
function buildInitialTimeline(container, graph) {
    const laneCount = Math.max(...Object.values(graph.lanes)) + 1;
    const flowContent = createLaneNodes(graph.nodes, laneCount, graph.structuralEvents || []);

    const timelineHTML = `
        <div class="timeline-view">
            <div class="timeline-stats" id="timelineStats">
                <span id="statNodes">Nodes: ${graph.stats.totalNodes}</span>
                <span id="statAgents">Agents: ${graph.stats.agentBranchCount}</span>
                <span id="statCompactions">Compactions: ${graph.stats.compactionCount}</span>
            </div>
            <div class="timeline-container">
                ${flowContent}
            </div>
        </div>
    `;

    container.innerHTML = timelineHTML;

    // Track all rendered nodes
    graph.nodes.forEach(node => timelineState.renderedNodeIds.add(node.uuid));

    // Add click handlers
    addTimelineClickHandlers(graph.nodes);
}

// Append new nodes to existing timeline (incremental update)
function appendNewNodesToTimeline(newNodes, lanes) {
    const lanesContainer = document.getElementById('timelineLanes');
    if (!lanesContainer) return;

    // Group new nodes by lane
    const nodesByLane = {};
    newNodes.forEach(node => {
        if (!nodesByLane[node.lane]) {
            nodesByLane[node.lane] = [];
        }
        nodesByLane[node.lane].push(node);
    });

    // Append to each lane
    Object.keys(nodesByLane).forEach(laneIndex => {
        const laneElement = lanesContainer.querySelector(`.timeline-lane[data-lane="${laneIndex}"]`);
        if (laneElement) {
            nodesByLane[laneIndex].forEach(node => {
                const nodeHTML = createGraphTimelineNode(node);
                const tempDiv = document.createElement('div');
                tempDiv.innerHTML = nodeHTML;
                laneElement.appendChild(tempDiv.firstElementChild);
                timelineState.renderedNodeIds.add(node.uuid);
            });
        }
    });
}

// Update SVG edges (replace entire SVG content)
function updateTimelineEdges(nodes, edges) {
    const svgElement = document.getElementById('timelineEdges');
    if (!svgElement) return;

    if (!edges || edges.length === 0) {
        svgElement.innerHTML = '';
        return;
    }

    // Create a map of node UUIDs to their RENDERED positions in DOM
    const nodePositions = new Map();
    const nodeElements = document.querySelectorAll('.timeline-node-wrapper');

    nodeElements.forEach((nodeEl, index) => {
        const uuid = nodeEl.dataset.uuid;
        const lane = parseInt(nodeEl.closest('.timeline-lane')?.dataset.lane || '0');

        // Get the actual position in the DOM (index within parent lane)
        const laneElement = nodeEl.closest('.timeline-lane');
        const nodesInLane = Array.from(laneElement.querySelectorAll('.timeline-node-wrapper'));
        const positionInLane = nodesInLane.indexOf(nodeEl);

        nodePositions.set(uuid, {
            lane: lane,
            y: positionInLane,  // Use position within lane, not global yPosition
            domIndex: index
        });
    });

    // Generate SVG paths
    const paths = edges.map(edge => {
        const fromPos = nodePositions.get(edge.from);
        const toPos = nodePositions.get(edge.to);

        if (!fromPos || !toPos) {
            return '';
        }

        const x1 = fromPos.lane * 300 + 150;
        const y1 = fromPos.y * 100 + 50;
        const x2 = toPos.lane * 300 + 150;
        const y2 = toPos.y * 100 + 50;

        const edgeClass = `edge-${edge.type}`;

        let pathD;
        if (fromPos.lane === toPos.lane) {
            pathD = `M ${x1} ${y1} L ${x2} ${y2}`;
        } else {
            const midY = (y1 + y2) / 2;
            pathD = `M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2}`;
        }

        return `<path d="${pathD}" class="timeline-edge ${edgeClass}" />`;
    }).join('');

    // Calculate viewBox based on actual rendered nodes
    const maxLane = Math.max(...Array.from(nodePositions.values()).map(p => p.lane), 0);
    const maxY = Math.max(...Array.from(nodePositions.values()).map(p => p.y), 0);
    const viewBox = `0 0 ${maxLane * 300 + 300} ${maxY * 100 + 100}`;

    svgElement.setAttribute('viewBox', viewBox);
    svgElement.innerHTML = paths;
}

// Update timeline stats display
function updateTimelineStats(stats) {
    const statNodes = document.getElementById('statNodes');
    const statAgents = document.getElementById('statAgents');
    const statCompactions = document.getElementById('statCompactions');

    if (statNodes) statNodes.textContent = `Nodes: ${stats.totalNodes}`;
    if (statAgents) statAgents.textContent = `Agents: ${stats.agentBranchCount}`;
    if (statCompactions) statCompactions.textContent = `Compactions: ${stats.compactionCount}`;
}

// Create SVG overlay for drawing edges between nodes
function createEdgesSVG(nodes, edges) {
    if (!edges || edges.length === 0) {
        return '<svg class="timeline-edges"></svg>';
    }

    // Create a map of node UUIDs to their positions
    const nodePositions = new Map();
    nodes.forEach(node => {
        nodePositions.set(node.uuid, {
            lane: node.lane,
            y: node.yPosition,
            x: node.xPosition
        });
    });

    // Generate SVG paths for each edge
    const paths = edges.map(edge => {
        const fromPos = nodePositions.get(edge.from);
        const toPos = nodePositions.get(edge.to);

        if (!fromPos || !toPos) {
            return '';
        }

        // Calculate SVG coordinates (will be scaled by CSS)
        const x1 = fromPos.lane * 300 + 150; // Center of lane
        const y1 = fromPos.y * 100 + 50;
        const x2 = toPos.lane * 300 + 150;
        const y2 = toPos.y * 100 + 50;

        // Determine edge class based on type
        const edgeClass = `edge-${edge.type}`;

        // Create path - use curved line for cross-lane edges
        let pathD;
        if (fromPos.lane === toPos.lane) {
            // Straight vertical line for same lane
            pathD = `M ${x1} ${y1} L ${x2} ${y2}`;
        } else {
            // Curved line for cross-lane connections
            const midY = (y1 + y2) / 2;
            pathD = `M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2}`;
        }

        return `<path d="${pathD}" class="timeline-edge ${edgeClass}" />`;
    }).join('');

    return `<svg class="timeline-edges" viewBox="0 0 ${Math.max(...nodes.map(n => n.lane)) * 300 + 300} ${Math.max(...nodes.map(n => n.yPosition)) * 100 + 100}">${paths}</svg>`;
}

// Group consecutive messages to reduce noise
function groupNodesForLane(nodes) {
    const groups = [];
    let currentGroup = [];

    for (let i = 0; i < nodes.length; i++) {
        const node = nodes[i];

        // Never group these - always show individually
        const shouldShowAlways =
            node.displayType === 'tool' ||
            node.displayType === 'compaction' ||
            node.displayType === 'agent' ||
            node.displayType === 'session-link';

        if (shouldShowAlways) {
            // Flush current group if it has 4+ messages
            if (currentGroup.length >= 4) {
                groups.push({ type: 'collapsed', nodes: currentGroup });
                currentGroup = [];
            } else if (currentGroup.length > 0) {
                // Too small to collapse, add individually
                currentGroup.forEach(n => groups.push({ type: 'single', node: n }));
                currentGroup = [];
            }

            // Add important node individually
            groups.push({ type: 'single', node });

        } else {
            // Regular message - add to group
            currentGroup.push(node);

            // If group gets too large (15+), flush it
            if (currentGroup.length >= 15) {
                groups.push({ type: 'collapsed', nodes: currentGroup });
                currentGroup = [];
            }
        }
    }

    // Flush remaining group
    if (currentGroup.length >= 4) {
        groups.push({ type: 'collapsed', nodes: currentGroup });
    } else if (currentGroup.length > 0) {
        currentGroup.forEach(n => groups.push({ type: 'single', node: n }));
    }

    return groups;
}

// Create chronological single-column view using structural events
function createLaneNodes(nodes, laneCount, structuralEvents) {
    if (!structuralEvents || structuralEvents.length === 0) return '<div class="empty-state">No timeline events</div>';

    // Create a map of nodes by UUID for quick lookup
    const nodeMap = new Map(nodes.map(n => [n.uuid, n]));

    // Structural events are already chronologically sorted
    const eventsHTML = structuralEvents.map(event => {
        if (event.type === 'context_group') {
            // Context summary (collapsed)
            return createContextSummaryNode(event, event.lane);
        } else if (event.type === 'handover') {
            // Handover message (full content)
            const node = nodeMap.get(event.node);
            return createHandoverNode(event, node);
        } else if (event.type === 'notable_event') {
            // Notable event (todo/plan)
            return createNotableEventNode(event);
        } else if (event.type === 'message_group') {
            // Legacy message group
            return createMessageGroupNode(event);
        } else {
            // Structural event marker
            const node = nodeMap.get(event.node);
            return createStructuralEventNode(event, node);
        }
    }).join('');

    // Single column timeline
    return `<div class="timeline-flow">${eventsHTML}</div>`;
}

// Create a context summary node (collapsed messages between handovers) - minimal line-based layout
function createContextSummaryNode(event, lane) {
    const details = [];
    if (event.userCount > 0) details.push(`${event.userCount} user`);
    if (event.assistantCount > 0) details.push(`${event.assistantCount} assistant`);
    if (event.toolCount > 0) details.push(`${event.toolCount} tool calls`);

    const detailsText = details.length > 0 ? details.join(', ') : `${event.count} messages`;
    const uuids = event.nodes.join(',');

    return `
        <div class="timeline-context-summary" data-uuids="${uuids}" data-lane="${lane}">
            ${detailsText}
        </div>
    `;
}

// Create a notable event node (todo/plan marker) - minimal line-based layout
function createNotableEventNode(event) {
    const heading = event.eventType === 'todo' ? 'Todo Update:' : 'Plan Update:';

    // Convert newlines in summary to HTML line breaks
    const lines = event.summary.split('\n');
    const formattedContent = lines.map(line => `  ${line}`).join('<br>');

    return `
        <div class="timeline-notable-event" data-type="${event.eventType}" data-uuid="${event.node}">
            <div class="notable-heading">${heading}</div>
            <div class="notable-content">${formattedContent}</div>
        </div>
    `;
}

// Create a handover node (full message at transition points) - minimal line-based layout
function createHandoverNode(event, node) {
    if (!node) return '';

    const handoverLabels = {
        'branch_trigger': 'Agent Triggered:',
        'agent_start': 'Agent Started:',
        'agent_end': 'Agent Completed:',
        'merge_response': 'Continued:'
    };

    const label = handoverLabels[event.handoverType] || event.handoverType + ':';
    const content = node.content || '';

    // Build sub-items
    let details = '';
    if (event.agentId) {
        details += `  Agent: ${event.agentId.substring(0, 8)}\n`;
    }
    if (event.branchName) {
        details += `  Branch: ${event.branchName}\n`;
    }
    if (content) {
        const truncatedContent = content.length > 100 ? content.substring(0, 100) + '...' : content;
        details += `  ${truncatedContent}`;
    }

    return `
        <div class="timeline-handover" data-type="${event.handoverType}" data-uuid="${node.uuid}" data-lane="${event.lane}">
            <div class="handover-heading">${label}</div>
            <div class="handover-details">${details}</div>
        </div>
    `;
}

// Create a collapsed message group node (legacy)
function createMessageGroupNode(event) {
    const count = event.count;
    const uuids = event.nodes.join(',');

    return `
        <div class="timeline-message-group" data-uuids="${uuids}" data-count="${count}">
            <div class="timeline-group-header">
                <span class="group-icon">▶</span>
                <span class="group-title">📦 ${count} message${count !== 1 ? 's' : ''}</span>
            </div>
        </div>
    `;
}

// Create a structural event marker
function createStructuralEventNode(event, node) {
    const eventIcons = {
        'agent_start': '🔀',
        'agent_end': '✓',
        'branch_point': '⑂',
        'compaction': '📦'
    };

    const eventLabels = {
        'agent_start': 'Agent Started',
        'agent_end': 'Agent Completed',
        'branch_point': 'Branch Point',
        'compaction': 'Compaction'
    };

    const icon = eventIcons[event.type] || '•';
    const label = eventLabels[event.type] || event.type;

    // For agent events, show the branch name
    let title = label;
    if (event.type === 'agent_start' && event.branchName) {
        title = `${icon} ${event.branchName}`;
    } else if (event.type === 'agent_end' && event.branchName) {
        title = `${icon} ${event.branchName} → Main`;
    } else {
        title = `${icon} ${label}`;
    }

    const timestamp = node && node.timestamp ? formatTimestamp(node.timestamp) : '';

    return `
        <div class="timeline-structural-event" data-type="${event.type}" data-uuid="${event.node || ''}">
            <div class="structural-event-marker">
                <span class="structural-icon">${icon}</span>
                <span class="structural-title">${title}</span>
                <span class="structural-timestamp">${timestamp}</span>
            </div>
        </div>
    `;
}

// Create a collapsed group node (legacy - kept for compatibility)
function createCollapsedGroupNode(nodes) {
    const count = nodes.length;
    const firstNode = nodes[0];
    const lastNode = nodes[nodes.length - 1];

    // Get time range
    const firstTime = firstNode.timestamp ? formatTimestamp(firstNode.timestamp) : '';
    const lastTime = lastNode.timestamp ? formatTimestamp(lastNode.timestamp) : '';

    // Store node UUIDs as data attribute
    const uuids = nodes.map(n => n.uuid).join(',');

    return `
        <div class="timeline-collapsed-group" data-uuids="${uuids}" data-count="${count}">
            <div class="timeline-collapsed-header">
                <span class="collapse-icon">▶</span>
                <span class="collapse-title">📁 ${count} messages</span>
            </div>
            <div class="timeline-collapsed-meta">
                <span>${firstTime} → ${lastTime}</span>
            </div>
            <div class="timeline-collapsed-content" style="display: none;">
                ${nodes.map(node => createGraphTimelineNode(node)).join('')}
            </div>
        </div>
    `;
}

// Create a single timeline node from graph data
function createGraphTimelineNode(node) {
    // Determine badge text
    const badgeText = {
        'user': 'U',
        'assistant': 'A',
        'tool': 'T',
        'agent': 'AG',
        'compaction': 'C',
        'session-link': 'L',
        'unknown': '?'
    }[node.displayType] || '?';

    // Format timestamp
    const timestamp = node.timestamp ? formatTimestamp(node.timestamp) : '';

    // Truncate content for preview
    const contentPreview = truncateContent(node.content || '', 80);

    return `
        <div class="timeline-node-wrapper" data-uuid="${node.uuid}" data-y="${node.yPosition}">
            <div class="timeline-node timeline-node-${node.displayType}">
                <div class="timeline-node-content">
                    <span class="timeline-badge timeline-badge-${node.displayType}">${badgeText}</span>
                    <span class="timeline-branch-name">${node.branchName}</span>
                    <span class="timeline-preview">${contentPreview}</span>
                    <span class="timeline-timestamp">${timestamp}</span>
                </div>
            </div>
        </div>
    `;
}

// Add click handlers to timeline elements
function addTimelineClickHandlers(nodes) {
    // Add click handlers for handover messages
    document.querySelectorAll('.timeline-handover').forEach(handover => {
        const uuid = handover.dataset.uuid;
        handover.addEventListener('click', () => {
            const entry = allEntries.find(e => e.uuid === uuid);
            if (entry) {
                if (entry.tool_items) {
                    showToolDetailsDialog(entry);
                } else {
                    const content = entry.content || entry.text || JSON.stringify(entry, null, 2);
                    showContentDialog(content);
                }
            }
        });
        handover.style.cursor = 'pointer';
    });

    // Add click handlers for context summaries (expand/collapse)
    document.querySelectorAll('.timeline-context-summary').forEach(summary => {
        summary.addEventListener('click', (e) => {
            e.stopPropagation();
            const uuids = summary.dataset.uuids.split(',');

            // TODO: Expand to show messages
            console.log('Context summary clicked:', uuids);
        });
        summary.style.cursor = 'pointer';
    });

    // Add click handlers for notable events (plan/todo markers)
    document.querySelectorAll('.timeline-notable-event').forEach(notableEvent => {
        const uuid = notableEvent.dataset.uuid;
        const eventType = notableEvent.dataset.type;

        notableEvent.addEventListener('click', (e) => {
            e.stopPropagation();
            const entry = allEntries.find(e => e.uuid === uuid);

            if (entry && entry.tool_items && entry.tool_items.tool_uses) {
                const toolUse = entry.tool_items.tool_uses.find(t =>
                    t.name === 'TodoWrite' || t.name === 'ExitPlanMode'
                );

                if (toolUse) {
                    if (eventType === 'plan' && toolUse.input && toolUse.input.plan) {
                        showTimelinePlanDialog(toolUse.input.plan);
                    } else if (eventType === 'todo' && toolUse.input && toolUse.input.todos) {
                        showTimelineTodoDialog(toolUse.input.todos);
                    }
                }
            }
        });
        notableEvent.style.cursor = 'pointer';
    });
}

// Add click handlers to timeline nodes (legacy)
function addTimelineNodeClickHandlers(nodes) {
    // Create a map of UUIDs to full node data
    const nodeMap = new Map(nodes.map(n => [n.uuid, n]));

    // Add click handler to each node wrapper
    document.querySelectorAll('.timeline-node-wrapper').forEach(wrapper => {
        const uuid = wrapper.dataset.uuid;
        const node = nodeMap.get(uuid);

        if (node) {
            wrapper.addEventListener('click', () => {
                // Find the original entry in allEntries to show full content
                const entry = allEntries.find(e => e.uuid === uuid);
                if (entry) {
                    // Determine if it has tools
                    if (entry.tool_items) {
                        showToolDetailsDialog(entry);
                    } else {
                        // Show content in modal
                        const content = entry.content || entry.text || JSON.stringify(entry, null, 2);
                        showContentDialog(content);
                    }
                }
            });

            // Add hover effect
            wrapper.style.cursor = 'pointer';
        }
    });

    // Add click handlers for new message groups (structural timeline)
    document.querySelectorAll('.timeline-message-group').forEach(group => {
        group.addEventListener('click', async (e) => {
            e.stopPropagation();

            // Get the UUIDs of messages in this group
            const uuids = group.dataset.uuids.split(',');

            // Show a loading indicator
            const isExpanded = group.classList.contains('expanded');

            if (!isExpanded) {
                // Expand - fetch and display messages
                group.classList.add('expanded');

                // Check if content is already loaded
                let content = group.querySelector('.timeline-group-content');
                if (!content) {
                    // Create content container
                    content = document.createElement('div');
                    content.className = 'timeline-group-content';

                    // Fetch the actual nodes for these UUIDs from allEntries
                    const messages = uuids
                        .map(uuid => allEntries.find(e => e.uuid === uuid))
                        .filter(e => e); // Remove nulls

                    // Render nodes
                    content.innerHTML = messages.map(entry => {
                        const timestamp = entry.timestamp ? formatTimestamp(entry.timestamp) : '';
                        const contentPreview = truncateContent(entry.content_display || '', 80);
                        const badgeText = entry.role === 'user' ? 'U' : entry.role === 'assistant' ? 'A' : 'T';

                        return `
                            <div class="timeline-group-message" data-uuid="${entry.uuid}">
                                <span class="timeline-badge timeline-badge-${entry.role || 'unknown'}">${badgeText}</span>
                                <span class="timeline-preview">${contentPreview}</span>
                                <span class="timeline-timestamp">${timestamp}</span>
                            </div>
                        `;
                    }).join('');

                    group.appendChild(content);

                    // Add click handlers to messages
                    content.querySelectorAll('.timeline-group-message').forEach(msg => {
                        const uuid = msg.dataset.uuid;
                        msg.addEventListener('click', (e) => {
                            e.stopPropagation();
                            const entry = allEntries.find(e => e.uuid === uuid);
                            if (entry) {
                                if (entry.tool_items) {
                                    showToolDetailsDialog(entry);
                                } else {
                                    const content = entry.content || entry.text || JSON.stringify(entry, null, 2);
                                    showContentDialog(content);
                                }
                            }
                        });
                        msg.style.cursor = 'pointer';
                    });
                } else {
                    content.style.display = 'block';
                }
            } else {
                // Collapse
                group.classList.remove('expanded');
                const content = group.querySelector('.timeline-group-content');
                if (content) {
                    content.style.display = 'none';
                }
            }
        });
    });

    // Add click handlers for collapsed groups (legacy)
    document.querySelectorAll('.timeline-collapsed-group').forEach(group => {
        group.addEventListener('click', (e) => {
            // Don't toggle if clicking on inner nodes
            if (e.target.closest('.timeline-node-wrapper')) {
                return;
            }

            e.stopPropagation();

            // Toggle expanded state
            const isExpanded = group.classList.contains('expanded');
            const content = group.querySelector('.timeline-collapsed-content');

            if (isExpanded) {
                // Collapse
                group.classList.remove('expanded');
                content.style.display = 'none';
            } else {
                // Expand
                group.classList.add('expanded');
                content.style.display = 'block';
            }
        });
    });
}

// Create a single timeline node (old flat list version - keep for reference)
function createTimelineNode(entry, index, allEntries) {
    // Determine display type
    const displayType = getDisplayType(entry);

    // Get badge text
    const badgeText = getBadgeText(displayType);

    // Get branch name
    const branchName = getBranchName(entry);

    // Get content preview
    const contentPreview = getContentPreview(entry);

    // Determine connector character
    const connector = getConnectorChar(entry, index, allEntries);

    // Format timestamp
    const timestamp = entry.timestamp ? formatTimestamp(entry.timestamp) : '';

    return `
        <div class="timeline-node-wrapper" data-uuid="${entry.uuid || ''}" data-index="${index}">
            <div class="timeline-node timeline-node-${displayType}">
                <div class="timeline-connector">${connector}</div>
                <div class="timeline-node-content">
                    <span class="timeline-badge timeline-badge-${displayType}">${badgeText}</span>
                    <span class="timeline-branch-name">${branchName}</span>
                    <span class="timeline-preview">${truncateContent(contentPreview, 80)}</span>
                    <span class="timeline-timestamp">${timestamp}</span>
                </div>
            </div>
        </div>
    `;
}

// Get display type from entry
function getDisplayType(entry) {
    if (entry.type === 'system' && entry.subtype === 'compact_boundary') {
        return 'compaction';
    }
    if (entry.has_tool_results || entry.type === 'tool_result') {
        return 'tool';
    }
    if (entry.isSidechain) {
        return 'agent';
    }
    if (entry.role === 'user' || entry.type === 'user') {
        return 'user';
    }
    if (entry.role === 'assistant' || entry.type === 'assistant') {
        return 'assistant';
    }
    return entry.type || 'unknown';
}

// Get badge text
function getBadgeText(displayType) {
    const badges = {
        'user': 'U',
        'assistant': 'A',
        'tool': 'T',
        'agent': 'AG',
        'compaction': 'C',
        'system': 'SYS'
    };
    return badges[displayType] || '?';
}

// Get branch name
function getBranchName(entry) {
    if (entry.isSidechain && entry.agentId) {
        return `Agent: ${entry.agentId.substring(0, 8)}`;
    }
    if (entry.type === 'system' && entry.subtype === 'compact_boundary') {
        return 'Compaction';
    }
    return 'Main';
}

// Get content preview from entry
function getContentPreview(entry) {
    // Try to extract content from various places
    if (entry.content && typeof entry.content === 'string') {
        return entry.content;
    }

    if (entry.text && typeof entry.text === 'string') {
        return entry.text;
    }

    // For tool results, show a summary
    if (entry.has_tool_results && entry.tool_items) {
        const toolCount = entry.tool_items.tool_uses?.length || 0;
        return `[${toolCount} tool${toolCount !== 1 ? 's' : ''} used]`;
    }

    // Fallback to type
    return `[${entry.type || entry.role || 'message'}]`;
}

// Get connector character
function getConnectorChar(entry, index, allEntries) {
    if (index === 0) {
        return '┌'; // Start
    }
    if (index === allEntries.length - 1) {
        return '└'; // End
    }

    // Check if next entry is different type (potential branch point)
    const nextEntry = allEntries[index + 1];
    if (nextEntry) {
        const currentBranch = entry.isSidechain ? entry.agentId : 'main';
        const nextBranch = nextEntry.isSidechain ? nextEntry.agentId : 'main';

        if (currentBranch !== nextBranch) {
            return '├'; // Branch point
        }
    }

    return '│'; // Continue
}

export function renderEntries() {
    const container = document.getElementById('entriesContainer');
    const typeFilter = document.getElementById('typeFilter').value;
    const searchTerm = document.getElementById('searchInput').value.toLowerCase();
    const limit = parseInt(document.getElementById('limitSelect').value);

    let filtered = allEntries;

    if (typeFilter) {
        if (typeFilter === 'tool_result') {
            // Filter for entries that have tool results
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

    // Filter by selected session
    if (selectedSession) {
        filtered = filtered.filter(e => e.sessionId === selectedSession);
    }

    filtered = filtered.slice(0, limit);

    // Check view mode and render accordingly
    if (currentViewMode === 'timeline') {
        renderTimelineView(filtered);
        return;
    }

    // Continue with normal table rendering

    if (filtered.length === 0) {
        container.innerHTML = '<div class="empty-state"><h2>No entries found</h2><p>Try adjusting your filters</p></div>';
        renderedEntryIds.clear();
        updateFilterState();
        return;
    }

    // Check if we need a full rebuild or can append
    const needsRebuild = filtersChanged();

    if (needsRebuild) {
        // Full rebuild needed
        renderedEntryIds.clear();

        // Create table
        const table = document.createElement('table');

        // Create header
        const thead = document.createElement('thead');
        const headerRow = document.createElement('tr');

        Array.from(selectedFields).forEach(fieldName => {
            const th = document.createElement('th');
            th.textContent = fieldName;
            headerRow.appendChild(th);
        });

        thead.appendChild(headerRow);
        table.appendChild(thead);

        // Create body
        const tbody = document.createElement('tbody');

        filtered.forEach(entry => {
            const row = createEntryRow(entry);
            tbody.appendChild(row);
            renderedEntryIds.add(getEntryId(entry));
        });

        table.appendChild(tbody);

        container.innerHTML = '';
        const tableContainer = document.createElement('div');
        tableContainer.className = 'table-container';
        tableContainer.appendChild(table);
        container.appendChild(tableContainer);

        updateFilterState();
    } else {
        // Incremental update - only add new entries
        const existingTable = container.querySelector('table');

        if (!existingTable) {
            // Table doesn't exist, do full rebuild
            renderedEntryIds.clear();

            const table = document.createElement('table');
            const thead = document.createElement('thead');
            const headerRow = document.createElement('tr');

            Array.from(selectedFields).forEach(fieldName => {
                const th = document.createElement('th');
                th.textContent = fieldName;
                headerRow.appendChild(th);
            });

            thead.appendChild(headerRow);
            table.appendChild(thead);

            const tbody = document.createElement('tbody');

            filtered.forEach(entry => {
                const row = createEntryRow(entry);
                tbody.appendChild(row);
                renderedEntryIds.add(getEntryId(entry));
            });

            table.appendChild(tbody);

            container.innerHTML = '';
            const tableContainer = document.createElement('div');
            tableContainer.className = 'table-container';
            tableContainer.appendChild(table);
            container.appendChild(tableContainer);
        } else {
            // Append only new entries
            const tbody = existingTable.querySelector('tbody');

            filtered.forEach(entry => {
                const entryId = getEntryId(entry);
                if (!renderedEntryIds.has(entryId)) {
                    const row = createEntryRow(entry);
                    // Insert at the beginning (newest first)
                    tbody.insertBefore(row, tbody.firstChild);
                    renderedEntryIds.add(entryId);
                }
            });
        }
    }

    updateStats();
}
