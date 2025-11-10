// Timeline visualization component - Vertical Git-Style Graph

export class Timeline {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.data = null;
        this.hiddenBranches = new Set();
        this.highlightedPath = null;
    }

    async load(sessionId = null) {
        try {
            const url = sessionId
                ? `/api/timeline?session_id=${sessionId}`
                : '/api/timeline';

            const response = await fetch(url);
            this.data = await response.json();
            this.render();
        } catch (error) {
            console.error('Error loading timeline:', error);
            this.container.innerHTML = '<div class="timeline-error">Error loading timeline data</div>';
        }
    }

    render() {
        if (!this.data || !this.data.nodes) {
            this.container.innerHTML = '<div class="timeline-empty">No timeline data available</div>';
            return;
        }

        // Clear container
        this.container.innerHTML = '';

        // Create timeline structure
        const timelineEl = document.createElement('div');
        timelineEl.className = 'timeline-vertical';

        // Add filter controls
        timelineEl.appendChild(this.createFilterControls());

        // Sort nodes by yPosition (chronological order)
        const sortedNodes = [...this.data.nodes].sort((a, b) => a.yPosition - b.yPosition);

        // Build node lookup
        const nodeMap = new Map();
        this.data.nodes.forEach(node => nodeMap.set(node.uuid, node));

        // Build children lookup for branching
        const childrenMap = new Map();
        this.data.edges.forEach(edge => {
            if (!childrenMap.has(edge.from)) {
                childrenMap.set(edge.from, []);
            }
            childrenMap.set(edge.from, [...childrenMap.get(edge.from), edge.to]);
        });

        // Track active lanes for drawing branch lines
        const activeLanes = new Map(); // lane -> last node uuid

        // Render each node
        sortedNodes.forEach((node, index) => {
            const nodeEl = this.createNodeElement(node, nodeMap, childrenMap);
            timelineEl.appendChild(nodeEl);
        });

        this.container.appendChild(timelineEl);
    }

    createFilterControls() {
        const controls = document.createElement('div');
        controls.className = 'timeline-controls';

        const branches = this.getBranches();

        controls.innerHTML = `
            <div class="timeline-filters">
                <label class="timeline-filter-label">Show:</label>
                <label class="timeline-filter-item">
                    <input type="checkbox" checked data-branch="main"> Main Thread
                </label>
                ${branches.map(branch => `
                    <label class="timeline-filter-item">
                        <input type="checkbox" checked data-branch="${branch}"> ${branch}
                    </label>
                `).join('')}
                <label class="timeline-filter-item">
                    <input type="checkbox" checked data-branch="compaction"> Compactions
                </label>
            </div>
        `;

        // Add event listeners
        controls.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {
            checkbox.addEventListener('change', (e) => {
                const branch = e.target.dataset.branch;
                if (e.target.checked) {
                    this.hiddenBranches.delete(branch);
                } else {
                    this.hiddenBranches.add(branch);
                }
                this.render();
            });
        });

        return controls;
    }

    getBranches() {
        const branches = new Set();
        this.data.nodes.forEach(node => {
            if (node.isSidechain && node.agentId) {
                branches.add(`Agent: ${node.agentId.substring(0, 8)}`);
            }
        });
        return Array.from(branches);
    }

    createNodeElement(node, nodeMap, childrenMap) {
        const wrapper = document.createElement('div');
        wrapper.className = 'timeline-node-wrapper';
        wrapper.dataset.uuid = node.uuid;
        wrapper.dataset.lane = node.lane;

        // Check if this branch is hidden
        const branchKey = node.displayType === 'compaction' ? 'compaction' :
                         node.isSidechain ? node.branchName :
                         'main';
        if (this.hiddenBranches.has(branchKey)) {
            wrapper.style.display = 'none';
        }

        // Determine if this is a branch point or merge point
        const children = childrenMap.get(node.uuid) || [];
        const isBranchPoint = children.length > 1;
        const parent = node.parentUuid ? nodeMap.get(node.parentUuid) : null;
        const isMergePoint = parent && parent.lane !== node.lane;

        // Create node element
        const nodeEl = document.createElement('div');
        nodeEl.className = `timeline-node timeline-node-${node.displayType}`;

        // Branch connector (git-style characters)
        const connector = document.createElement('div');
        connector.className = 'timeline-connector';

        let connectorChar = '│'; // Default: continue line
        if (isBranchPoint) {
            connectorChar = '├';
        } else if (node.yPosition === 0) {
            connectorChar = '┌'; // Start
        } else if (children.length === 0) {
            connectorChar = '└'; // End
        }

        connector.textContent = connectorChar;

        // Node content
        const content = document.createElement('div');
        content.className = 'timeline-node-content';

        // Role badge
        const badge = document.createElement('span');
        badge.className = `timeline-badge timeline-badge-${node.displayType}`;
        badge.textContent = this.getBadgeText(node);

        // Message preview
        const preview = document.createElement('span');
        preview.className = 'timeline-preview';
        preview.textContent = node.content || `[${node.type}]`;

        // Branch name
        const branchName = document.createElement('span');
        branchName.className = 'timeline-branch-name';
        branchName.textContent = node.branchName;

        // Timestamp
        const timestamp = document.createElement('span');
        timestamp.className = 'timeline-timestamp';
        timestamp.textContent = this.formatTimestamp(node.timestamp);

        content.appendChild(badge);
        content.appendChild(branchName);
        content.appendChild(preview);
        content.appendChild(timestamp);

        nodeEl.appendChild(connector);
        nodeEl.appendChild(content);

        // Add tooltip
        this.addTooltip(nodeEl, node);

        // Add click handler for path highlighting
        nodeEl.addEventListener('click', () => this.highlightPath(node.uuid));

        wrapper.appendChild(nodeEl);

        return wrapper;
    }

    getBadgeText(node) {
        const badges = {
            'user': 'U',
            'assistant': 'A',
            'tool': 'T',
            'agent': 'AG',
            'compaction': 'C',
            'session-link': 'S',
            'system': 'SYS'
        };
        return badges[node.displayType] || '?';
    }

    formatTimestamp(timestamp) {
        if (!timestamp) return '';
        const date = new Date(timestamp);
        return date.toLocaleTimeString('en-US', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    }

    addTooltip(element, node) {
        element.title = `${node.branchName}
Type: ${node.displayType}
Time: ${this.formatTimestamp(node.timestamp)}
${node.content ? '\n' + node.content : ''}`;

        // Enhanced hover tooltip
        element.addEventListener('mouseenter', (e) => {
            const tooltip = document.createElement('div');
            tooltip.className = 'timeline-tooltip';
            tooltip.innerHTML = `
                <div class="timeline-tooltip-header">
                    <span class="timeline-badge timeline-badge-${node.displayType}">${this.getBadgeText(node)}</span>
                    <strong>${node.branchName}</strong>
                </div>
                <div class="timeline-tooltip-time">${this.formatTimestamp(node.timestamp)}</div>
                <div class="timeline-tooltip-content">${node.content || `[${node.type}]`}</div>
                <div class="timeline-tooltip-meta">UUID: ${node.uuid.substring(0, 8)}...</div>
            `;

            document.body.appendChild(tooltip);

            // Position tooltip
            const rect = element.getBoundingClientRect();
            tooltip.style.position = 'fixed';
            tooltip.style.left = (rect.right + 10) + 'px';
            tooltip.style.top = rect.top + 'px';

            element._tooltip = tooltip;
        });

        element.addEventListener('mouseleave', () => {
            if (element._tooltip) {
                element._tooltip.remove();
                delete element._tooltip;
            }
        });
    }

    highlightPath(uuid) {
        // Build path from this node backwards to root
        const path = new Set();
        const nodeMap = new Map(this.data.nodes.map(n => [n.uuid, n]));

        let current = nodeMap.get(uuid);
        while (current) {
            path.add(current.uuid);
            current = current.parentUuid ? nodeMap.get(current.parentUuid) : null;
        }

        // Build path forwards to all descendants
        const edges = new Map();
        this.data.edges.forEach(edge => {
            if (!edges.has(edge.from)) edges.set(edge.from, []);
            edges.get(edge.from).push(edge.to);
        });

        const addDescendants = (id) => {
            const children = edges.get(id) || [];
            children.forEach(childId => {
                if (!path.has(childId)) {
                    path.add(childId);
                    addDescendants(childId);
                }
            });
        };
        addDescendants(uuid);

        // Apply highlighting
        this.highlightedPath = path;
        this.container.querySelectorAll('.timeline-node-wrapper').forEach(wrapper => {
            if (path.has(wrapper.dataset.uuid)) {
                wrapper.classList.add('timeline-highlighted');
            } else {
                wrapper.classList.remove('timeline-highlighted');
            }
        });
    }
}
