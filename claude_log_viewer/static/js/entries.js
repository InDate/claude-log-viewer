// Entry rendering and field selection

import { allEntries, selectedFields, pendingSelectedFields, currentFilters, selectedSession, renderedEntryIds, knownFields, saveSelectedFields, setPendingSelectedFields } from './state.js';
import { getEntryId, getSessionColor, truncateContent, formatRelativeTime, copyToClipboard, formatNumber, formatTimestamp, getUsageClass } from './utils.js';
import { showContentDialog, showToolDetailsDialog } from './modals.js';
import { updateStats } from './sessions.js';

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

        // Format tokens and messages for display with "total (+delta)" format
        const formatStat = (totalTokens, totalMessages, deltaTokens, deltaMessages) => {
            if (totalTokens === null || totalTokens === undefined) return '—';
            // Handle null deltas by displaying 0
            const deltaTokensValue = (deltaTokens === null || deltaTokens === undefined) ? 0 : deltaTokens;
            const deltaMessagesValue = (deltaMessages === null || deltaMessages === undefined) ? 0 : deltaMessages;
            const tokensStr = `${formatNumber(totalTokens)} (+${formatNumber(deltaTokensValue)})`;
            const messagesStr = `${totalMessages} (+${deltaMessagesValue})`;
            return `${tokensStr} tokens | ${totalMessages === 1 ? 'message' : 'messages'}`;
        };

        const fiveHourStats = formatStat(
            snapshot.five_hour_tokens_total,
            snapshot.five_hour_messages_total,
            snapshot.five_hour_tokens_consumed,
            snapshot.five_hour_messages_count
        );
        const sevenDayStats = formatStat(
            snapshot.seven_day_tokens_total,
            snapshot.seven_day_messages_total,
            snapshot.seven_day_tokens_consumed,
            snapshot.seven_day_messages_count
        );

        td.innerHTML = `
            <div class="usage-increment-container">
                <div class="usage-increment-icon">📊</div>
                <div class="usage-increment-content">
                    <div class="usage-increment-title">Usage Increment Detected</div>
                    <div class="usage-increment-details">
                        <div class="usage-increment-stat">
                            <span class="usage-increment-label">5-Hour Window:</span>
                            <span class="usage-increment-value usage-value ${fiveHourClass}">${fiveHourPct}% utilization</span>
                            <span class="usage-increment-meta">${fiveHourStats}</span>
                        </div>
                        <div class="usage-increment-stat">
                            <span class="usage-increment-label">7-Day Window:</span>
                            <span class="usage-increment-value usage-value ${sevenDayClass}">${sevenDayPct}% utilization</span>
                            <span class="usage-increment-meta">${sevenDayStats}</span>
                        </div>
                    </div>
                </div>
                <div class="usage-increment-time">${formatTimestamp(entry.timestamp)}</div>
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
