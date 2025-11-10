// Modal dialog functions

import { md } from './config.js';
import { currentPlanNavigation, currentTodoNavigation, setCurrentPlanNavigation, setCurrentTodoNavigation } from './state.js';

// Helper function to detect if text contains markdown syntax
function hasMarkdownSyntax(text) {
    if (!text || typeof text !== 'string') return false;

    // Check for common markdown patterns
    const markdownPatterns = [
        /^#{1,6}\s/m,           // Headers
        /```/,                   // Code blocks
        /^\s*[-*+]\s/m,         // Unordered lists
        /^\s*\d+\.\s/m,         // Ordered lists
        /\[.+\]\(.+\)/,         // Links
        /\*\*.+\*\*/,           // Bold
        /\*.+\*/,               // Italic
        /__.+__/,               // Bold (underscore)
        /_.+_/,                 // Italic (underscore)
        /^\s*>/m,               // Blockquotes
        /\|.+\|/,               // Tables
    ];

    return markdownPatterns.some(pattern => pattern.test(text));
}

// Helper function to extract image file paths from text
function extractImagePaths(text) {
    if (!text || typeof text !== 'string') return [];

    const images = [];

    // Pattern 1: Backtick-wrapped paths (most reliable for screenshot tool output)
    // Matches: `path/to/image.jpg`
    const backtickPattern = /`([^`]+\.(jpg|jpeg|png|gif|webp|svg|bmp|ico))`/gi;
    let match;

    while ((match = backtickPattern.exec(text)) !== null) {
        images.push({
            fullMatch: match[0],
            path: match[1],
            extension: match[2]
        });
    }

    // Pattern 2: Standalone absolute paths (fallback)
    // Matches: /path/to/image.jpg or C:\path\to\image.jpg
    if (images.length === 0) {
        const standalonePattern = /((?:\/|[A-Z]:\\|\\\\)[\w\/\\.\- ]+\.(jpg|jpeg|png|gif|webp|svg|bmp|ico))/gi;
        while ((match = standalonePattern.exec(text)) !== null) {
            images.push({
                fullMatch: match[0],
                path: match[1],
                extension: match[2]
            });
        }
    }

    return images;
}

// Show content in modal dialog
export function showContentDialog(content) {
    const modal = document.getElementById('contentModal');
    const modalContent = document.getElementById('modalContent');

    // Parse and render markdown
    const htmlContent = md.render(content);
    modalContent.innerHTML = htmlContent;

    // Show modal
    modal.classList.add('active');
}

// Show tool details dialog with JSON
export function showToolDetailsDialog(entry) {
    const modal = document.getElementById('contentModal');
    const modalContent = document.getElementById('modalContent');

    // Build markdown content with tool details
    let markdownContent = '# Tool Use & Result Details\n\n';

    // Add entry context
    markdownContent += `**Session:** ${entry.sessionId || 'N/A'}  \n`;
    markdownContent += `**Timestamp:** ${entry.timestamp || 'N/A'}  \n`;
    markdownContent += `**Type:** ${entry.type || 'N/A'}\n\n`;

    // Add summary from content_display
    if (entry.content_display) {
        markdownContent += '## Summary\n\n';
        markdownContent += entry.content_display + '\n\n';
    }

    // Add tool uses
    if (entry.tool_items?.tool_uses?.length > 0) {
        markdownContent += '## Tool Uses\n\n';
        entry.tool_items.tool_uses.forEach((toolUse, index) => {
            markdownContent += `### ${index + 1}. ${toolUse.name}\n\n`;
            markdownContent += '```json\n';
            markdownContent += JSON.stringify(toolUse, null, 2);
            markdownContent += '\n```\n\n';
        });
    }

    // Add tool results with enhanced rendering
    const imageElements = []; // Track images to insert after markdown rendering

    if (entry.tool_items?.tool_results?.length > 0) {
        markdownContent += '## Tool Results\n\n';
        entry.tool_items.tool_results.forEach((toolResult, index) => {
            markdownContent += `### Result ${index + 1}\n\n`;
            if (toolResult.is_error) {
                markdownContent += '⚠️ **Error Result**\n\n';
            }

            const content = toolResult.content;

            // Handle different content types
            if (Array.isArray(content)) {
                // Content is an array of blocks
                content.forEach((block, blockIndex) => {
                    if (block.type === 'text' && block.text) {
                        // Check for image paths in text
                        const imagePaths = extractImagePaths(block.text);

                        // Render the text first (preserve context)
                        if (hasMarkdownSyntax(block.text)) {
                            markdownContent += block.text + '\n\n';
                        } else {
                            // Plain text - preserve formatting
                            markdownContent += '```\n' + block.text + '\n```\n\n';
                        }

                        // Add image placeholders for each detected path
                        if (imagePaths.length > 0) {
                            imagePaths.forEach((imgInfo, imgIndex) => {
                                markdownContent += `<div class="tool-result-image-placeholder tool-result-image-from-text" data-result-index="${index}" data-block-index="${blockIndex}" data-image-index="${imgIndex}"></div>\n\n`;
                                imageElements.push({
                                    resultIndex: index,
                                    blockIndex: blockIndex,
                                    imageIndex: imgIndex,
                                    imagePath: imgInfo.path,
                                    fromText: true
                                });
                            });
                        }
                    } else if (block.type === 'image') {
                        // Store image info for later insertion
                        markdownContent += `<div class="tool-result-image-placeholder" data-result-index="${index}" data-block-index="${blockIndex}"></div>\n\n`;
                        imageElements.push({
                            resultIndex: index,
                            blockIndex: blockIndex,
                            block: block
                        });
                    }
                });
            } else if (typeof content === 'string') {
                // Check for image paths in string content
                const imagePaths = extractImagePaths(content);

                // Render the text first (preserve context)
                if (hasMarkdownSyntax(content)) {
                    markdownContent += content + '\n\n';
                } else {
                    // Plain text - preserve formatting
                    markdownContent += '```\n' + content + '\n```\n\n';
                }

                // Add image placeholders for each detected path
                if (imagePaths.length > 0) {
                    imagePaths.forEach((imgInfo, imgIndex) => {
                        markdownContent += `<div class="tool-result-image-placeholder tool-result-image-from-text" data-result-index="${index}" data-image-index="${imgIndex}"></div>\n\n`;
                        imageElements.push({
                            resultIndex: index,
                            imageIndex: imgIndex,
                            imagePath: imgInfo.path,
                            fromText: true
                        });
                    });
                }
            } else if (content !== null && content !== undefined) {
                // Fallback to JSON for objects
                markdownContent += '```json\n';
                markdownContent += JSON.stringify(content, null, 2);
                markdownContent += '\n```\n\n';
            }

            // Show full metadata in JSON
            markdownContent += '<details>\n<summary>Full Result Metadata (JSON)</summary>\n\n';
            markdownContent += '```json\n';
            markdownContent += JSON.stringify(toolResult, null, 2);
            markdownContent += '\n```\n</details>\n\n';
        });
    }

    // Add toolUseResult metadata if present
    if (entry.tool_items?.toolUseResult) {
        markdownContent += '## Tool Metadata\n\n';
        markdownContent += '```json\n';
        markdownContent += JSON.stringify(entry.tool_items.toolUseResult, null, 2);
        markdownContent += '\n```\n\n';
    }

    // Parse and render markdown
    const htmlContent = md.render(markdownContent);
    modalContent.innerHTML = htmlContent;

    // Insert images into their placeholders
    imageElements.forEach(({ resultIndex, blockIndex, imageIndex, block, imagePath, fromText }) => {
        // Build selector based on whether image is from text or native block
        let selector = `.tool-result-image-placeholder[data-result-index="${resultIndex}"]`;

        if (fromText) {
            // Text-extracted image - needs imageIndex
            selector += `[data-image-index="${imageIndex}"]`;
            // blockIndex may or may not be present for string content
            if (blockIndex !== undefined) {
                selector += `[data-block-index="${blockIndex}"]`;
            }
        } else {
            // Native image block - uses blockIndex
            selector += `[data-block-index="${blockIndex}"]`;
        }

        const placeholder = modalContent.querySelector(selector);

        if (placeholder) {
            const img = document.createElement('img');
            img.className = fromText ? 'tool-result-image tool-result-image-from-text' : 'tool-result-image';

            // Extract image source
            let imageSrc = null;

            if (fromText) {
                // For text-extracted images, convert absolute path to relative URL
                // Extract the screenshots path portion (everything after .claude/screenshots/)
                const screenshotsMatch = imagePath.match(/\.claude\/screenshots\/(.+)$/);
                if (screenshotsMatch) {
                    imageSrc = `/screenshots/${screenshotsMatch[1]}`;
                } else {
                    // Fallback to original path (might not work for local file paths)
                    imageSrc = imagePath;
                }
            } else if (block) {
                // For native image blocks, extract from block.source
                if (block.source) {
                    if (block.source.type === 'url') {
                        imageSrc = block.source.url;
                    } else if (block.source.type === 'base64') {
                        imageSrc = `data:${block.source.media_type || 'image/png'};base64,${block.source.data}`;
                    } else if (typeof block.source === 'string') {
                        // Direct path or URL
                        imageSrc = block.source;
                    }
                } else if (block.url) {
                    imageSrc = block.url;
                } else if (block.path) {
                    imageSrc = block.path;
                }
            }

            if (imageSrc) {
                img.src = imageSrc;
                img.alt = 'Tool result image';
                img.onerror = function() {
                    // Replace with error message if image fails to load
                    const errorDiv = document.createElement('div');
                    errorDiv.className = 'tool-result-image-error';
                    errorDiv.textContent = `⚠️ Failed to load image: ${imageSrc}`;
                    placeholder.replaceWith(errorDiv);
                };
                placeholder.replaceWith(img);
            } else {
                // No valid image source found
                const errorDiv = document.createElement('div');
                errorDiv.className = 'tool-result-image-error';
                errorDiv.textContent = '⚠️ Image block found but no valid source';
                placeholder.replaceWith(errorDiv);
            }
        }
    });

    // Show modal
    modal.classList.add('active');
}

// Show plan dialog with navigation
export function showPlanDialog(session, planIndex = 0) {
    const modal = document.getElementById('contentModal');
    const modalContent = document.getElementById('modalContent');

    if (!session.planEntries || session.planEntries.length === 0) {
        return;
    }

    // Sort plans by timestamp (newest first)
    const sortedPlans = [...session.planEntries].sort((a, b) =>
        b.timestamp.localeCompare(a.timestamp)
    );

    // Ensure planIndex is valid
    planIndex = Math.max(0, Math.min(planIndex, sortedPlans.length - 1));

    // Store current navigation state
    setCurrentPlanNavigation({
        session: session,
        currentIndex: planIndex
    });

    const currentPlan = sortedPlans[planIndex];

    // Build markdown content with navigation info
    let markdownContent = `# Plan ${planIndex + 1} of ${sortedPlans.length} - Session ${session.id.substring(0, 8)}\n\n`;
    markdownContent += `**Timestamp:** ${currentPlan.timestamp}\n\n`;
    markdownContent += '---\n\n';
    markdownContent += currentPlan.plan;

    // Parse and render markdown
    const htmlContent = md.render(markdownContent);

    // Build navigation controls
    const hasPrev = planIndex < sortedPlans.length - 1;
    const hasNext = planIndex > 0;

    const navControls = `
        <div class="plan-navigation">
            <button class="plan-nav-btn" id="planPrevBtn" ${!hasPrev ? 'disabled' : ''}>
                ← Older
            </button>
            <span class="plan-counter">${planIndex + 1} / ${sortedPlans.length}</span>
            <button class="plan-nav-btn" id="planNextBtn" ${!hasNext ? 'disabled' : ''}>
                Newer →
            </button>
        </div>
    `;

    modalContent.innerHTML = navControls + htmlContent;

    // Add event listeners for navigation buttons
    const prevBtn = document.getElementById('planPrevBtn');
    const nextBtn = document.getElementById('planNextBtn');

    if (prevBtn && hasPrev) {
        prevBtn.addEventListener('click', () => {
            showPlanDialog(session, planIndex + 1);
        });
    }

    if (nextBtn && hasNext) {
        nextBtn.addEventListener('click', () => {
            showPlanDialog(session, planIndex - 1);
        });
    }

    // Show modal
    modal.classList.add('active');
}

// Navigate plan (used for keyboard navigation)
export function navigatePlan(direction) {
    if (!currentPlanNavigation) return;

    const { session, currentIndex } = currentPlanNavigation;
    const sortedPlans = [...session.planEntries].sort((a, b) =>
        b.timestamp.localeCompare(a.timestamp)
    );

    let newIndex = currentIndex;
    if (direction === 'prev' && currentIndex < sortedPlans.length - 1) {
        newIndex = currentIndex + 1;
    } else if (direction === 'next' && currentIndex > 0) {
        newIndex = currentIndex - 1;
    }

    if (newIndex !== currentIndex) {
        showPlanDialog(session, newIndex);
    }
}

// Navigate todo (used for keyboard navigation)
export function navigateTodo(direction) {
    if (!currentTodoNavigation) return;

    const { session, currentIndex } = currentTodoNavigation;
    const sortedTodos = [...session.todoEntries].sort((a, b) =>
        b.timestamp.localeCompare(a.timestamp)
    );

    let newIndex = currentIndex;
    if (direction === 'prev' && currentIndex < sortedTodos.length - 1) {
        newIndex = currentIndex + 1;
    } else if (direction === 'next' && currentIndex > 0) {
        newIndex = currentIndex - 1;
    }

    if (newIndex !== currentIndex) {
        showTodoDialog(session, newIndex);
    }
}

// Show todo list dialog with navigation
export function showTodoDialog(session, todoIndex = 0) {
    const modal = document.getElementById('contentModal');
    const modalContent = document.getElementById('modalContent');

    if (!session.todoEntries || session.todoEntries.length === 0) {
        return;
    }

    // Sort todos by timestamp (newest first)
    const sortedTodos = [...session.todoEntries].sort((a, b) =>
        b.timestamp.localeCompare(a.timestamp)
    );

    // Ensure todoIndex is valid
    todoIndex = Math.max(0, Math.min(todoIndex, sortedTodos.length - 1));

    // Store current navigation state
    setCurrentTodoNavigation({
        session: session,
        currentIndex: todoIndex
    });

    const currentTodoEntry = sortedTodos[todoIndex];
    const todos = currentTodoEntry.todos;

    // Group todos by status
    const inProgress = todos.filter(t => t.status === 'in_progress');
    const pending = todos.filter(t => t.status === 'pending');
    const completed = todos.filter(t => t.status === 'completed');

    // Build markdown content with navigation info
    let markdownContent = `# Todo List ${todoIndex + 1} of ${sortedTodos.length} - Session ${session.id.substring(0, 8)}\n\n`;
    markdownContent += `**Agent:** ${currentTodoEntry.agentId.substring(0, 8)}\n\n`;
    markdownContent += `**Timestamp:** ${currentTodoEntry.timestamp}\n\n`;
    markdownContent += '---\n\n';

    // In Progress section
    if (inProgress.length > 0) {
        markdownContent += `## ⏳ In Progress (${inProgress.length})\n\n`;
        inProgress.forEach(todo => {
            markdownContent += `- [ ] **${todo.content}**\n`;
            if (todo.activeForm && todo.activeForm !== todo.content) {
                markdownContent += `  - *${todo.activeForm}*\n`;
            }
        });
        markdownContent += '\n';
    }

    // Pending section
    if (pending.length > 0) {
        markdownContent += `## ☐ Pending (${pending.length})\n\n`;
        pending.forEach(todo => {
            markdownContent += `- [ ] ${todo.content}\n`;
            if (todo.activeForm && todo.activeForm !== todo.content) {
                markdownContent += `  - *${todo.activeForm}*\n`;
            }
        });
        markdownContent += '\n';
    }

    // Completed section
    if (completed.length > 0) {
        markdownContent += `## ✅ Completed (${completed.length})\n\n`;
        completed.forEach(todo => {
            markdownContent += `- [x] ${todo.content}\n`;
            if (todo.activeForm && todo.activeForm !== todo.content) {
                markdownContent += `  - *${todo.activeForm}*\n`;
            }
        });
    }

    // Parse and render markdown
    const htmlContent = md.render(markdownContent);

    // Build navigation controls
    const hasPrev = todoIndex < sortedTodos.length - 1;
    const hasNext = todoIndex > 0;

    const navControls = `
        <div class="plan-navigation">
            <button class="plan-nav-btn" id="todoPrevBtn" ${!hasPrev ? 'disabled' : ''}>
                ← Older
            </button>
            <span class="plan-counter">${todoIndex + 1} / ${sortedTodos.length}</span>
            <button class="plan-nav-btn" id="todoNextBtn" ${!hasNext ? 'disabled' : ''}>
                Newer →
            </button>
        </div>
    `;

    modalContent.innerHTML = navControls + htmlContent;

    // Add event listeners for navigation buttons
    const prevBtn = document.getElementById('todoPrevBtn');
    const nextBtn = document.getElementById('todoNextBtn');

    if (prevBtn && hasPrev) {
        prevBtn.addEventListener('click', () => {
            showTodoDialog(session, todoIndex + 1);
        });
    }

    if (nextBtn && hasNext) {
        nextBtn.addEventListener('click', () => {
            showTodoDialog(session, todoIndex - 1);
        });
    }

    // Show modal
    modal.classList.add('active');
}

// Show plan dialog from timeline (simplified - no navigation)
export function showTimelinePlanDialog(planText) {
    const modal = document.getElementById('contentModal');
    const modalContent = document.getElementById('modalContent');

    if (!planText) {
        return;
    }

    // Build markdown content
    let markdownContent = `# Plan\n\n`;
    markdownContent += planText;

    // Parse and render markdown
    const htmlContent = md.render(markdownContent);

    modalContent.innerHTML = htmlContent;

    // Show modal
    modal.classList.add('active');
}

// Show todo dialog from timeline (simplified - no navigation)
export function showTimelineTodoDialog(todos) {
    const modal = document.getElementById('contentModal');
    const modalContent = document.getElementById('modalContent');

    if (!todos || todos.length === 0) {
        return;
    }

    // Group todos by status
    const inProgress = todos.filter(t => t.status === 'in_progress');
    const pending = todos.filter(t => t.status === 'pending');
    const completed = todos.filter(t => t.status === 'completed');

    // Build markdown content
    let markdownContent = `# Todo List\n\n`;

    // In Progress section
    if (inProgress.length > 0) {
        markdownContent += `## ⏳ In Progress (${inProgress.length})\n\n`;
        inProgress.forEach(todo => {
            markdownContent += `- [ ] **${todo.content}**\n`;
            if (todo.activeForm && todo.activeForm !== todo.content) {
                markdownContent += `  - *${todo.activeForm}*\n`;
            }
        });
        markdownContent += '\n';
    }

    // Pending section
    if (pending.length > 0) {
        markdownContent += `## ☐ Pending (${pending.length})\n\n`;
        pending.forEach(todo => {
            markdownContent += `- [ ] ${todo.content}\n`;
            if (todo.activeForm && todo.activeForm !== todo.content) {
                markdownContent += `  - *${todo.activeForm}*\n`;
            }
        });
        markdownContent += '\n';
    }

    // Completed section
    if (completed.length > 0) {
        markdownContent += `## ✅ Completed (${completed.length})\n\n`;
        completed.forEach(todo => {
            markdownContent += `- [x] ${todo.content}\n`;
            if (todo.activeForm && todo.activeForm !== todo.content) {
                markdownContent += `  - *${todo.activeForm}*\n`;
            }
        });
    }

    // Parse and render markdown
    const htmlContent = md.render(markdownContent);

    modalContent.innerHTML = htmlContent;

    // Show modal
    modal.classList.add('active');
}

// Close modal dialog
export function closeContentDialog() {
    const modal = document.getElementById('contentModal');

    modal.classList.remove('active');
    // Reset navigation states
    setCurrentPlanNavigation(null);
    setCurrentTodoNavigation(null);
}

// Initialize modal event listeners
export function initializeModalListeners() {
    const modalCloseBtn = document.getElementById('modalClose');
    const contentModal = document.getElementById('contentModal');

    if (modalCloseBtn) {
        modalCloseBtn.addEventListener('click', closeContentDialog);
    }

    if (contentModal) {
        contentModal.addEventListener('click', (e) => {
            // Close when clicking on overlay (not on dialog itself)
            if (e.target === e.currentTarget) {
                closeContentDialog();
            }
        });
    }

    // Close on Escape key and navigate plans/todos with arrow keys
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeContentDialog();
        } else if (e.key === 'ArrowLeft') {
            // Navigate to older plan or todo
            if (currentPlanNavigation) {
                navigatePlan('prev');
            } else if (currentTodoNavigation) {
                navigateTodo('prev');
            }
        } else if (e.key === 'ArrowRight') {
            // Navigate to newer plan or todo
            if (currentPlanNavigation) {
                navigatePlan('next');
            } else if (currentTodoNavigation) {
                navigateTodo('next');
            }
        }
    });
}
