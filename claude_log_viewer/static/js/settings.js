// Settings management

let currentSettings = {};

// Load settings from API
export async function loadSettings() {
    try {
        const response = await fetch('/api/settings');
        const settings = await response.json();
        currentSettings = settings;
        return settings;
    } catch (error) {
        console.error('Error loading settings:', error);
        return {};
    }
}

// Save a setting to API
export async function saveSetting(key, value) {
    try {
        const response = await fetch(`/api/settings/${key}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ value })
        });

        const result = await response.json();

        if (result.success) {
            currentSettings[key] = value;
            return true;
        } else {
            console.error('Failed to save setting:', result.error);
            return false;
        }
    } catch (error) {
        console.error('Error saving setting:', error);
        return false;
    }
}

// Get current value of a setting
export function getSetting(key, defaultValue = null) {
    return currentSettings[key] !== undefined ? currentSettings[key] : defaultValue;
}

// Initialize settings UI
export function initSettingsUI() {
    const settingsBtn = document.getElementById('settingsBtn');
    const settingsModal = document.getElementById('settingsModal');
    const settingsModalClose = document.getElementById('settingsModalClose');
    const gitEnabledToggle = document.getElementById('gitEnabledToggle');
    const gitStatusMessage = document.getElementById('gitStatusMessage');

    if (!settingsBtn || !settingsModal) {
        console.error('Settings UI elements not found');
        return;
    }

    // Open settings modal
    settingsBtn.addEventListener('click', async () => {
        // Load current settings
        const settings = await loadSettings();

        // Update toggle state
        gitEnabledToggle.checked = settings.git_enabled || false;

        // Show modal
        settingsModal.style.display = 'flex';

        // Run auto-discovery if git is enabled
        if (settings.git_enabled) {
            await runDiscoverAll();
        }

        // Check git status
        checkGitStatus();
    });

    // Close modal
    settingsModalClose.addEventListener('click', () => {
        settingsModal.style.display = 'none';
    });

    // Close modal when clicking outside
    settingsModal.addEventListener('click', (e) => {
        if (e.target === settingsModal) {
            settingsModal.style.display = 'none';
        }
    });

    // Handle git enabled toggle
    gitEnabledToggle.addEventListener('change', async (e) => {
        const enabled = e.target.checked;

        // Show loading state
        gitStatusMessage.style.display = 'block';
        gitStatusMessage.style.color = '#888';
        gitStatusMessage.textContent = enabled ? 'Enabling git management...' : 'Disabling git management...';

        // Save setting
        const success = await saveSetting('git_enabled', enabled);

        if (success) {
            // Show success message
            gitStatusMessage.style.color = '#4ec9b0';
            gitStatusMessage.textContent = enabled
                ? '✓ Git management enabled globally.'
                : '✓ Git management disabled. No checkpoints will be created.';

            // Check git status if enabled
            if (enabled) {
                setTimeout(() => {
                    checkGitStatus();
                    loadProjectGitSettings();
                }, 1000);
            } else {
                // Hide project settings if global is disabled
                document.getElementById('projectGitSettings').style.display = 'none';
            }

            // Reload entries to update UI
            setTimeout(() => {
                import('./entries.js').then(module => module.loadEntries());
            }, 500);
        } else {
            // Show error and revert toggle
            gitStatusMessage.style.color = '#f48771';
            gitStatusMessage.textContent = '❌ Failed to save setting. Please try again.';
            gitEnabledToggle.checked = !enabled;
        }
    });
}

// Check git repository status
async function checkGitStatus() {
    const gitStatusMessage = document.getElementById('gitStatusMessage');

    try {
        const response = await fetch('/api/git/status');
        const status = await response.json();

        if (status.is_git_repo) {
            gitStatusMessage.style.display = 'block';
            gitStatusMessage.style.color = '#4ec9b0';

            let html = `✓ Git repo detected at <code style="background: #1a1a1a; padding: 2px 4px; border-radius: 2px;">${status.repo_path}</code><br>`;
            html += `Current branch: <strong>${status.current_branch}</strong> (${status.current_commit.substring(0, 8)})`;

            // Show discovered repos if available
            if (status.discovered_repos && status.discovered_repos.length > 0) {
                html += '<br><br><strong>Discovered repos:</strong><br>';
                status.discovered_repos.forEach(repo => {
                    const badge = repo.is_primary ? ' <span style="color: #4ec9b0;">[Primary]</span>' : '';
                    html += `• ${repo.repo_path} (${repo.file_count} files)${badge}<br>`;
                });
            }

            gitStatusMessage.innerHTML = html;
        } else {
            gitStatusMessage.style.display = 'block';
            gitStatusMessage.style.color = '#f48771';

            // No repos found - discovery runs automatically when modal opens
            gitStatusMessage.style.display = 'none';
        }
    } catch (error) {
        gitStatusMessage.style.display = 'block';
        gitStatusMessage.style.color = '#f48771';
        gitStatusMessage.textContent = '❌ Error checking git status';
        console.error('Error checking git status:', error);
    }
}

// Create skeleton loading UI
function createSkeletonRepos(count = 3) {
    const html = [];
    for (let i = 0; i < count; i++) {
        html.push(`
            <div class="skeleton-repo">
                <div class="skeleton skeleton-line" style="width: 200px;"></div>
                <div class="skeleton skeleton-line-small" style="width: 350px;"></div>
                <div class="skeleton skeleton-line-small" style="width: 180px;"></div>
            </div>
        `);
    }
    return html.join('');
}

// Load and display per-project git settings
export async function loadProjectGitSettings() {
    const projectGitSettings = document.getElementById('projectGitSettings');
    const projectGitList = document.getElementById('projectGitList');

    // Only show if global git is enabled
    if (!getSetting('git_enabled', false)) {
        projectGitSettings.style.display = 'none';
        return;
    }

    // Show project settings section with skeleton
    projectGitSettings.style.display = 'block';
    projectGitList.innerHTML = createSkeletonRepos();

    try {
        // Get current project from URL parameter or detect from page
        const urlParams = new URLSearchParams(window.location.search);
        const currentProject = urlParams.get('project') || getProjectFromPath();

        // Get all repo git settings (enabled/disabled status)
        const settingsResponse = await fetch('/api/repos/git-settings');
        const repoSettings = await settingsResponse.json();

        // Get all discovered repos (grouped by repo path)
        const discoveredRepos = await getAllDiscoveredRepos();

        // Build project list
        projectGitList.innerHTML = '';

        if (discoveredRepos.length === 0) {
            projectGitList.innerHTML = '<div style="padding: 10px; color: #888; font-size: 12px;">No repos discovered yet. Click "Discover All Projects" to scan for git repos.</div>';
            return;
        }

        // Show all discovered repos grouped by path
        discoveredRepos.forEach(repo => {
            const repoDiv = createRepoToggle(repo, repoSettings, currentProject);
            projectGitList.appendChild(repoDiv);
        });

    } catch (error) {
        console.error('Error loading project git settings:', error);
        projectGitList.innerHTML = '<div style="padding: 10px; color: #f48771; font-size: 12px;">Error loading projects</div>';
    }
}

// Get all discovered git repos (grouped and deduplicated)
async function getAllDiscoveredRepos() {
    try {
        const response = await fetch('/api/projects/all-discovered');
        if (!response.ok) {
            return [];
        }
        const data = await response.json();
        return data.repos || [];
    } catch (error) {
        console.error('Error fetching discovered repos:', error);
        return [];
    }
}

// Create a repo toggle UI element showing all sessions that use this repo
function createRepoToggle(repo, repoSettings, currentProject) {
    const div = document.createElement('div');
    div.style.cssText = 'padding: 12px; background: #1a1a1a; border-radius: 4px; margin-bottom: 10px;';

    // Check if this repo is enabled
    const isEnabled = repoSettings[repo.repo_path] || false;

    // Extract folder name from path
    const folderName = repo.repo_path.split('/').pop() || repo.repo_path;

    // Header with repo path, toggle, and collapse button
    const header = document.createElement('div');
    header.style.cssText = 'display: flex; align-items: center; justify-content: space-between;';
    header.innerHTML = `
        <div style="flex: 1;">
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
                <div style="font-weight: 500; font-size: 14px; color: #4ec9b0;">
                    ${folderName}
                </div>
                <button class="collapse-btn" style="background: none; border: none; color: #888; cursor: pointer; font-size: 12px; padding: 0; display: flex; align-items: center;">
                    ▶
                </button>
            </div>
            <div style="font-size: 11px; color: #666; margin-bottom: 4px;">
                ${repo.repo_path}
            </div>
            <div style="font-size: 11px; color: #888;">
                Total: ${repo.total_files} files across ${repo.sessions.length} session(s)
            </div>
        </div>
        <label class="toggle-switch">
            <input type="checkbox" ${isEnabled ? 'checked' : ''} data-repo="${repo.repo_path}">
            <span class="toggle-slider"></span>
        </label>
    `;
    div.appendChild(header);

    // Add event listener for repo-level toggle
    const toggle = header.querySelector('input[type="checkbox"]');
    toggle.addEventListener('change', async (e) => {
        const newEnabled = e.target.checked;

        try {
            // URL encode the repo path for the API call
            const encodedRepoPath = encodeURIComponent(repo.repo_path);
            const response = await fetch(`/api/repos/${encodedRepoPath}/git-enabled`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: newEnabled })
            });

            const result = await response.json();

            if (result.success) {
                console.log(`✓ Git ${newEnabled ? 'enabled' : 'disabled'} for repo: ${repo.repo_path}`);
            } else {
                console.error('Failed to update setting:', result.error);
                toggle.checked = !newEnabled;
                alert(result.error);
            }
        } catch (error) {
            console.error('Error updating setting:', error);
            toggle.checked = !newEnabled;
            alert('Failed to update setting');
        }
    });

    // List of sessions using this repo (informational only, no toggles)
    const sessionsDiv = document.createElement('div');
    sessionsDiv.style.cssText = 'padding-left: 12px; border-left: 2px solid #333; margin-top: 8px; display: none;'; // Start collapsed

    repo.sessions.forEach(session => {
        const sessionDiv = document.createElement('div');
        sessionDiv.style.cssText = 'padding: 6px 8px; background: #0e0e0e; border-radius: 3px; margin-bottom: 6px;';

        const isCurrent = session.session_id === currentProject;
        if (isCurrent) {
            sessionDiv.style.border = '1px solid #4ec9b0';
        }

        sessionDiv.innerHTML = `
            <div style="font-size: 12px; color: #569cd6;">${session.session_id}</div>
            <div style="font-size: 10px; color: #666;">
                ${session.file_count} files
                ${session.is_primary ? ' • <span style="color: #4ec9b0;">Primary</span>' : ''}
                ${isCurrent ? ' • <span style="color: #4ec9b0;">Current</span>' : ''}
            </div>
        `;

        sessionsDiv.appendChild(sessionDiv);
    });

    div.appendChild(sessionsDiv);

    // Add collapse/expand functionality
    const collapseBtn = header.querySelector('.collapse-btn');
    collapseBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const isVisible = sessionsDiv.style.display !== 'none';
        sessionsDiv.style.display = isVisible ? 'none' : 'block';
        collapseBtn.textContent = isVisible ? '▶' : '▼';
    });

    return div;
}

// Create a project toggle UI element with discovered repos displayed
function createProjectToggleWithRepos(projectName, repos, enabled, isCurrent) {
    const div = document.createElement('div');
    div.style.cssText = 'padding: 10px; background: #1a1a1a; border-radius: 4px; margin-bottom: 8px;';

    if (isCurrent) {
        div.style.border = '1px solid #4ec9b0';
    }

    // Header with project name and toggle
    const header = document.createElement('div');
    header.style.cssText = 'display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;';

    header.innerHTML = `
        <div style="flex: 1;">
            <div style="font-weight: 500; font-size: 13px; color: #569cd6;">${projectName}</div>
            <div style="font-size: 11px; color: #888;">${isCurrent ? '(Current project)' : ''}</div>
        </div>
        <label class="toggle-switch">
            <input type="checkbox" ${enabled ? 'checked' : ''} data-project="${projectName}">
            <span class="toggle-slider"></span>
        </label>
    `;

    div.appendChild(header);

    // Show discovered repos
    if (repos && repos.length > 0) {
        const reposDiv = document.createElement('div');
        reposDiv.style.cssText = 'padding-left: 12px; border-left: 2px solid #333; margin-top: 8px;';

        repos.forEach(repo => {
            const repoItem = document.createElement('div');
            repoItem.style.cssText = 'font-size: 11px; color: #888; margin-bottom: 4px;';
            const badge = repo.is_primary ? ' <span style="color: #4ec9b0;">[Primary]</span>' : '';
            repoItem.innerHTML = `• <code style="background: #0e0e0e; padding: 2px 4px; border-radius: 2px;">${repo.repo_path}</code> (${repo.file_count} files)${badge}`;
            reposDiv.appendChild(repoItem);
        });

        div.appendChild(reposDiv);
    }

    // Add event listener to toggle
    const toggle = div.querySelector('input[type="checkbox"]');
    toggle.addEventListener('change', async (e) => {
        const newEnabled = e.target.checked;

        try {
            const response = await fetch(`/api/projects/${projectName}/git-enabled`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ enabled: newEnabled })
            });

            const result = await response.json();

            if (result.success) {
                console.log(`✓ Git ${newEnabled ? 'enabled' : 'disabled'} for project: ${projectName}`);
            } else {
                console.error('Failed to update project setting:', result.error);
                // Revert toggle
                toggle.checked = !newEnabled;
                alert(result.error);
            }
        } catch (error) {
            console.error('Error updating project git setting:', error);
            // Revert toggle
            toggle.checked = !newEnabled;
            alert('Failed to update project setting');
        }
    });

    return div;
}

// Create a project toggle UI element (legacy - kept for compatibility)
function createProjectToggle(projectName, enabled, isCurrent) {
    return createProjectToggleWithRepos(projectName, [], enabled, isCurrent);
}

// Run auto-discovery for a project
async function runAutoDiscovery(projectName) {
    const gitStatusMessage = document.getElementById('gitStatusMessage');

    // Show loading
    gitStatusMessage.style.color = '#888';
    gitStatusMessage.innerHTML = '🔍 Scanning JSONL files for git repositories...';

    try {
        const response = await fetch(`/api/projects/${projectName}/discover-git`, {
            method: 'POST'
        });
        const result = await response.json();

        if (result.success && result.repos && result.repos.length > 0) {
            // Hide loading message
            gitStatusMessage.style.display = 'none';
            // Reload git status and project settings
            checkGitStatus();
        } else {
            gitStatusMessage.style.color = '#f48771';
            gitStatusMessage.textContent = '⚠ No git repositories found in JSONL entries. Make sure the project has file operations logged.';
        }
    } catch (error) {
        console.error('Error during discovery:', error);
        gitStatusMessage.style.color = '#f48771';
        gitStatusMessage.textContent = '❌ Error during discovery: ' + error.message;
    }
}

// Run auto-discovery for all projects
async function runDiscoverAll() {
    const gitStatusMessage = document.getElementById('gitStatusMessage');

    // Show loading
    gitStatusMessage.style.color = '#888';
    gitStatusMessage.innerHTML = '🔍 Scanning JSONL files across all projects...';

    try {
        const response = await fetch('/api/projects/discover-all', {
            method: 'POST'
        });
        const result = await response.json();

        if (result.success && result.total_repos > 0) {
            // Hide loading message
            gitStatusMessage.style.display = 'none';
            // Load project settings to show all discovered repos with toggles
            loadProjectGitSettings();
        } else if (result.success && result.total_repos === 0) {
            gitStatusMessage.style.color = '#f48771';
            gitStatusMessage.textContent = `⚠ Scanned ${result.projects_scanned} project(s) but no git repositories found. Make sure projects have file operations logged.`;
        } else {
            gitStatusMessage.style.color = '#f48771';
            gitStatusMessage.textContent = result.error || '⚠ No projects found in loaded entries';
        }
    } catch (error) {
        console.error('Error during discover-all:', error);
        gitStatusMessage.style.color = '#f48771';
        gitStatusMessage.textContent = '❌ Error during discovery: ' + error.message;
    }
}

// Get current project from the page/URL
function getProjectFromPath() {
    // Get from hidden field set by backend
    const targetProjectInput = document.getElementById('targetProject');
    return targetProjectInput ? targetProjectInput.value : null;
}

// Get list of available projects
async function getAvailableProjects() {
    // This would ideally come from the backend
    // For now, we can get it from the current sessions
    try {
        const response = await fetch('/api/entries?limit=1');
        const data = await response.json();

        // Extract unique session IDs and infer projects
        // This is a simplified approach - in production you'd want a proper endpoint
        const sessions = new Set();

        if (data.entries) {
            data.entries.forEach(entry => {
                if (entry.sessionId) {
                    sessions.add(entry.sessionId);
                }
            });
        }

        // For now, just return empty - projects will be added as they're used
        return [];
    } catch (error) {
        console.error('Error getting available projects:', error);
        return [];
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    loadSettings().then(() => {
        initSettingsUI();
    });
});
