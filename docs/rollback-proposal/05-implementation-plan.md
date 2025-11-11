# Implementation Plan: Reflog-Based Rollback System

## Overview

This document outlines the detailed implementation plan for integrating reflog-based rollback functionality into claude-log-viewer.

## Phase 1: Core Git Management Module (Week 1-2)

### New File: `claude_log_viewer/git_manager.py`

Core functionality for git operations and reflog management.

```python
import subprocess
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Tuple

logger = logging.getLogger(__name__)

class GitRollbackManager:
    """Manages git-based rollback using reflog strategy."""

    def __init__(self, project_root: Path, db_manager):
        self.project_root = project_root
        self.db = db_manager
        self._verify_git_repo()
        self._configure_reflog()

    def _verify_git_repo(self) -> bool:
        """Verify project is a git repository."""
        try:
            subprocess.run(
                ['git', 'rev-parse', '--git-dir'],
                cwd=self.project_root,
                check=True,
                capture_output=True
            )
            return True
        except subprocess.CalledProcessError:
            logger.warning(f"Not a git repository: {self.project_root}")
            return False

    def _configure_reflog(self):
        """Configure extended reflog retention."""
        commands = [
            ['git', 'config', 'gc.reflogExpire', '180 days'],
            ['git', 'config', 'gc.reflogExpireUnreachable', '180 days'],
        ]
        for cmd in commands:
            subprocess.run(cmd, cwd=self.project_root, check=False)

    def create_checkpoint(self, session_uuid: str) -> Dict[str, str]:
        """Create checkpoint before Claude session starts."""
        try:
            # Get current HEAD
            result = subprocess.run(
                ['git', 'rev-parse', 'HEAD'],
                cwd=self.project_root,
                check=True,
                capture_output=True,
                text=True
            )
            checkpoint_commit = result.stdout.strip()

            # Get reflog position
            checkpoint_reflog = "HEAD@{0}"

            # Store in database
            self.db.create_checkpoint(
                session_uuid=session_uuid,
                checkpoint_commit=checkpoint_commit,
                checkpoint_reflog=checkpoint_reflog,
                created_at=datetime.now(),
                status='active'
            )

            # Optional: Create tag for permanent preservation
            tag_name = f"checkpoint-{session_uuid[:8]}"
            subprocess.run(
                ['git', 'tag', '-a', tag_name, checkpoint_commit, '-m', f'Checkpoint for session {session_uuid}'],
                cwd=self.project_root,
                check=False
            )

            logger.info(f"Created checkpoint for session {session_uuid}: {checkpoint_commit}")
            return {
                'checkpoint_commit': checkpoint_commit,
                'checkpoint_reflog': checkpoint_reflog,
                'tag': tag_name
            }

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to create checkpoint: {e}")
            raise

    def auto_commit(self, session_uuid: str, tool_name: str,
                   description: str, agent_id: Optional[str] = None,
                   tool_use_id: Optional[str] = None) -> Optional[str]:
        """Auto-commit changes after tool use."""
        try:
            # Check if there are changes
            status_result = subprocess.run(
                ['git', 'status', '--porcelain'],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=True
            )

            if not status_result.stdout.strip():
                logger.debug("No changes to commit")
                return None

            # Stage all changes
            subprocess.run(
                ['git', 'add', '-A'],
                cwd=self.project_root,
                check=True
            )

            # Create commit message
            agent_prefix = f"Agent {agent_id[:8]}" if agent_id else "Claude"
            commit_message = f"""{agent_prefix} [{tool_name}]: {description}

Session: {session_uuid}
Agent: {agent_id or 'main'}
Tool: {tool_name}
Tool use ID: {tool_use_id}

🤖 Generated with Claude Code
"""

            # Commit
            result = subprocess.run(
                ['git', 'commit', '-m', commit_message],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=True
            )

            # Get commit hash
            commit_hash_result = subprocess.run(
                ['git', 'rev-parse', 'HEAD'],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=True
            )
            commit_hash = commit_hash_result.stdout.strip()

            # Store in database
            self.db.create_git_commit(
                commit_hash=commit_hash,
                session_uuid=session_uuid,
                agent_id=agent_id,
                message=commit_message,
                timestamp=datetime.now(),
                tool_use_id=tool_use_id
            )

            logger.info(f"Auto-committed {commit_hash[:8]} for {tool_name}")
            return commit_hash

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to auto-commit: {e}")
            return None

    def rollback_session(self, session_uuid: str,
                        create_recovery_branch: bool = False) -> Dict[str, any]:
        """Rollback session to checkpoint (commits go to reflog)."""
        try:
            # Get checkpoint
            checkpoint = self.db.get_checkpoint(session_uuid)
            if not checkpoint:
                raise ValueError(f"No checkpoint found for session {session_uuid}")

            checkpoint_commit = checkpoint['checkpoint_commit']

            # Get all commits from session (for recovery info)
            commits = self.db.get_session_commits(session_uuid)

            # Optional: Create recovery branch before rollback
            recovery_branch = None
            if create_recovery_branch:
                recovery_branch = f"recovery/session-{session_uuid[:8]}"
                subprocess.run(
                    ['git', 'push', 'origin', f'HEAD:refs/heads/{recovery_branch}'],
                    cwd=self.project_root,
                    check=False
                )
                logger.info(f"Created recovery branch: {recovery_branch}")

            # Check for uncommitted changes
            status_result = subprocess.run(
                ['git', 'status', '--porcelain'],
                cwd=self.project_root,
                capture_output=True,
                text=True
            )

            if status_result.stdout.strip():
                logger.warning("Uncommitted changes detected - stashing")
                subprocess.run(
                    ['git', 'stash', 'save', f'Pre-rollback stash for {session_uuid}'],
                    cwd=self.project_root,
                    check=False
                )

            # Perform rollback
            subprocess.run(
                ['git', 'reset', '--hard', checkpoint_commit],
                cwd=self.project_root,
                check=True
            )

            # Update database
            self.db.update_checkpoint_status(session_uuid, 'rolled_back')

            logger.info(f"Rolled back session {session_uuid} to {checkpoint_commit[:8]}")

            return {
                'success': True,
                'checkpoint': checkpoint_commit,
                'commits_rolled_back': len(commits),
                'recovery_branch': recovery_branch,
                'commits': [c['commit_hash'] for c in commits]
            }

        except subprocess.CalledProcessError as e:
            logger.error(f"Rollback failed: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def list_session_commits(self, session_uuid: str) -> List[Dict[str, str]]:
        """List all commits from a session."""
        commits = self.db.get_session_commits(session_uuid)

        # Enhance with git log info
        for commit in commits:
            try:
                result = subprocess.run(
                    ['git', 'show', '--no-patch', '--format=%H%n%an%n%ae%n%at%n%s',
                     commit['commit_hash']],
                    cwd=self.project_root,
                    capture_output=True,
                    text=True,
                    check=True
                )
                lines = result.stdout.strip().split('\n')
                commit['author_name'] = lines[1] if len(lines) > 1 else ''
                commit['author_email'] = lines[2] if len(lines) > 2 else ''
                commit['timestamp'] = lines[3] if len(lines) > 3 else ''
                commit['subject'] = lines[4] if len(lines) > 4 else ''
            except subprocess.CalledProcessError:
                logger.warning(f"Could not get git info for {commit['commit_hash']}")

        return commits

    def recover_commit(self, commit_hash: str) -> bool:
        """Cherry-pick a specific commit from reflog."""
        try:
            subprocess.run(
                ['git', 'cherry-pick', commit_hash],
                cwd=self.project_root,
                check=True
            )
            logger.info(f"Recovered commit {commit_hash[:8]}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to recover commit {commit_hash}: {e}")
            return False

    def get_session_diff(self, session_uuid: str) -> str:
        """Get diff of all session changes."""
        try:
            checkpoint = self.db.get_checkpoint(session_uuid)
            if not checkpoint:
                return ""

            result = subprocess.run(
                ['git', 'diff', checkpoint['checkpoint_commit'], 'HEAD'],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to get diff: {e}")
            return ""

    def find_in_reflog(self, commit_hash: str) -> Optional[str]:
        """Find reflog entry for a commit."""
        try:
            result = subprocess.run(
                ['git', 'reflog', '--format=%H %gd', '--all'],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=True
            )

            for line in result.stdout.strip().split('\n'):
                parts = line.split()
                if parts[0] == commit_hash:
                    return parts[1]  # HEAD@{n}

            return None
        except subprocess.CalledProcessError:
            return None
```

### Tasks

- [ ] Implement GitRollbackManager class
- [ ] Add error handling and logging
- [ ] Write unit tests for git operations
- [ ] Document all methods

## Phase 2: Database Schema Extensions (Week 2)

### Migration: `claude_log_viewer/migrations/add_git_tracking.sql`

```sql
-- Git checkpoints table
CREATE TABLE IF NOT EXISTS git_checkpoints (
    session_uuid TEXT PRIMARY KEY,
    checkpoint_commit TEXT NOT NULL,
    checkpoint_reflog TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('active', 'kept', 'rolled_back')),
    recovery_tag TEXT,
    recovery_branch TEXT,
    FOREIGN KEY (session_uuid) REFERENCES sessions(uuid)
);

-- Git commits table
CREATE TABLE IF NOT EXISTS git_commits (
    commit_hash TEXT PRIMARY KEY,
    session_uuid TEXT NOT NULL,
    agent_id TEXT,
    message TEXT,
    timestamp TIMESTAMP NOT NULL,
    tool_use_id TEXT,
    in_reflog BOOLEAN DEFAULT 1,
    FOREIGN KEY (session_uuid) REFERENCES sessions(uuid)
);

-- Index for performance
CREATE INDEX IF NOT EXISTS idx_git_commits_session ON git_commits(session_uuid);
CREATE INDEX IF NOT EXISTS idx_git_commits_agent ON git_commits(agent_id);
CREATE INDEX IF NOT EXISTS idx_git_checkpoints_status ON git_checkpoints(status);
```

### Update: `claude_log_viewer/database.py`

Add methods:

```python
def create_checkpoint(self, session_uuid: str, checkpoint_commit: str,
                     checkpoint_reflog: str, created_at: datetime, status: str):
    """Create checkpoint record."""
    self.cursor.execute("""
        INSERT INTO git_checkpoints
        (session_uuid, checkpoint_commit, checkpoint_reflog, created_at, status)
        VALUES (?, ?, ?, ?, ?)
    """, (session_uuid, checkpoint_commit, checkpoint_reflog, created_at, status))
    self.conn.commit()

def create_git_commit(self, commit_hash: str, session_uuid: str,
                     agent_id: Optional[str], message: str,
                     timestamp: datetime, tool_use_id: Optional[str]):
    """Record git commit."""
    self.cursor.execute("""
        INSERT INTO git_commits
        (commit_hash, session_uuid, agent_id, message, timestamp, tool_use_id)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (commit_hash, session_uuid, agent_id, message, timestamp, tool_use_id))
    self.conn.commit()

def get_checkpoint(self, session_uuid: str) -> Optional[Dict]:
    """Get checkpoint for session."""
    self.cursor.execute("""
        SELECT * FROM git_checkpoints WHERE session_uuid = ?
    """, (session_uuid,))
    row = self.cursor.fetchone()
    if row:
        return dict(row)
    return None

def get_session_commits(self, session_uuid: str) -> List[Dict]:
    """Get all commits for a session."""
    self.cursor.execute("""
        SELECT * FROM git_commits
        WHERE session_uuid = ?
        ORDER BY timestamp ASC
    """, (session_uuid,))
    return [dict(row) for row in self.cursor.fetchall()]

def update_checkpoint_status(self, session_uuid: str, status: str):
    """Update checkpoint status."""
    self.cursor.execute("""
        UPDATE git_checkpoints SET status = ? WHERE session_uuid = ?
    """, (status, session_uuid))
    self.conn.commit()
```

### Tasks

- [ ] Write migration script
- [ ] Add database methods
- [ ] Test migration on existing database
- [ ] Add rollback migration (if needed)

## Phase 3: Auto-Commit Integration (Week 3)

### Update: Tool Result Processing

Integrate auto-commit into existing JSONL processing:

```python
# In existing tool result handler
def process_tool_result(message: Dict):
    tool_use_id = message.get('id')
    tool_name = message.get('name')
    session_uuid = get_current_session_uuid()
    agent_id = get_current_agent_id()  # None if main session

    # Existing processing...
    # ...

    # New: Auto-commit if Edit/Write/Bash
    if tool_name in ['Edit', 'Write', 'Bash']:
        description = generate_description(tool_name, message.get('input', {}))
        git_manager.auto_commit(
            session_uuid=session_uuid,
            tool_name=tool_name,
            description=description,
            agent_id=agent_id,
            tool_use_id=tool_use_id
        )

def generate_description(tool_name: str, tool_input: Dict) -> str:
    """Generate commit description from tool input."""
    if tool_name == 'Edit':
        file_path = tool_input.get('file_path', 'unknown')
        return f"Edit {file_path}"
    elif tool_name == 'Write':
        file_path = tool_input.get('file_path', 'unknown')
        return f"Create/update {file_path}"
    elif tool_name == 'Bash':
        command = tool_input.get('command', 'unknown')
        # Truncate long commands
        if len(command) > 50:
            command = command[:47] + '...'
        return f"Run: {command}"
    return "Unknown change"
```

### Tasks

- [ ] Integrate auto-commit into JSONL processing
- [ ] Add commit description generation
- [ ] Test with sample sessions
- [ ] Handle errors gracefully

## Phase 4: Web UI Integration (Week 4-5)

### New API Routes: `claude_log_viewer/app.py`

```python
@app.route('/api/sessions/<session_id>/checkpoint', methods=['POST'])
def create_session_checkpoint(session_id):
    """Create checkpoint for session."""
    try:
        result = git_manager.create_checkpoint(session_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sessions/<session_id>/commits', methods=['GET'])
def get_session_commits(session_id):
    """Get commits for session."""
    commits = git_manager.list_session_commits(session_id)
    return jsonify(commits)

@app.route('/api/sessions/<session_id>/rollback', methods=['POST'])
def rollback_session(session_id):
    """Rollback session to checkpoint."""
    create_recovery = request.json.get('create_recovery_branch', False)
    result = git_manager.rollback_session(session_id, create_recovery)
    return jsonify(result)

@app.route('/api/sessions/<session_id>/diff', methods=['GET'])
def get_session_diff(session_id):
    """Get diff for session."""
    diff = git_manager.get_session_diff(session_id)
    return jsonify({'diff': diff})

@app.route('/api/commits/<commit_hash>/recover', methods=['POST'])
def recover_commit(commit_hash):
    """Cherry-pick commit from reflog."""
    success = git_manager.recover_commit(commit_hash)
    return jsonify({'success': success})
```

### UI Components

**Session Detail Page Enhancement:**

```javascript
// Add buttons to session detail page
<div className="session-actions">
  {!checkpoint && (
    <button onClick={createCheckpoint}>
      Create Checkpoint
    </button>
  )}

  {checkpoint && checkpoint.status === 'active' && (
    <>
      <button onClick={viewCommits}>
        View Commits ({commitsCount})
      </button>

      <button onClick={() => setShowRollbackModal(true)}
              className="danger">
        Rollback Session
      </button>

      <button onClick={viewDiff}>
        View Diff
      </button>
    </>
  )}
</div>
```

**Rollback Confirmation Modal:**

```javascript
<Modal show={showRollbackModal}>
  <h2>Rollback Session?</h2>

  <div className="rollback-preview">
    <p>This will rollback {commitsCount} commits:</p>
    <ul>
      {commits.map(c => (
        <li key={c.commit_hash}>
          {c.commit_hash.substring(0, 8)}: {c.message}
        </li>
      ))}
    </ul>

    <DiffPreview diff={sessionDiff} />
  </div>

  <div className="options">
    <label>
      <input type="checkbox" checked={createRecoveryBranch}
             onChange={(e) => setCreateRecoveryBranch(e.target.checked)} />
      Create recovery branch (permanent backup)
    </label>
  </div>

  <div className="actions">
    <button onClick={confirmRollback} className="danger">
      Confirm Rollback
    </button>
    <button onClick={cancelRollback}>
      Cancel
    </button>
  </div>
</Modal>
```

**Commit Timeline View:**

```javascript
<div className="commit-timeline">
  <h3>Session Commits</h3>
  {commits.map(commit => (
    <div key={commit.commit_hash}
         className={`commit ${commit.agent_id ? 'agent-commit' : 'main-commit'}`}>
      <div className="commit-header">
        <span className="commit-hash">{commit.commit_hash.substring(0, 8)}</span>
        <span className="commit-author">
          {commit.agent_id ? `Agent ${commit.agent_id.substring(0, 8)}` : 'Claude'}
        </span>
        <span className="commit-time">{formatTime(commit.timestamp)}</span>
      </div>

      <div className="commit-message">{commit.message}</div>

      <div className="commit-actions">
        <button onClick={() => viewCommitDiff(commit.commit_hash)}>
          View Diff
        </button>
        <button onClick={() => recoverCommit(commit.commit_hash)}>
          Recover This
        </button>
      </div>
    </div>
  ))}
</div>
```

### Tasks

- [ ] Implement API routes
- [ ] Create React components
- [ ] Add modal dialogs
- [ ] Implement diff viewer
- [ ] Add loading states and error handling
- [ ] Style components

## Phase 5: Documentation & Testing (Week 6)

### User Documentation

**File: `docs/rollback-guide.md`**

- How reflog-based rollback works
- Creating checkpoints
- Reviewing commits
- Rolling back sessions
- Recovering from reflog
- Creating recovery branches
- Understanding 180-day window
- Troubleshooting

### Developer Documentation

**File: `docs/developers/git-integration.md`**

- Architecture overview
- GitRollbackManager API
- Database schema
- API endpoints
- UI components
- Testing guidelines

### Tests

```python
# tests/test_git_manager.py
def test_create_checkpoint():
    """Test checkpoint creation."""
    session_id = "test-session-123"
    result = git_manager.create_checkpoint(session_id)
    assert result['checkpoint_commit']
    assert result['checkpoint_reflog']

def test_auto_commit():
    """Test auto-commit on tool use."""
    commit = git_manager.auto_commit(
        session_uuid="test-session",
        tool_name="Edit",
        description="Edit file.py",
        tool_use_id="tool-123"
    )
    assert commit is not None

def test_rollback_session():
    """Test session rollback."""
    # Create checkpoint
    git_manager.create_checkpoint("test-session")

    # Make commits
    git_manager.auto_commit("test-session", "Edit", "change 1")
    git_manager.auto_commit("test-session", "Edit", "change 2")

    # Rollback
    result = git_manager.rollback_session("test-session")
    assert result['success']
    assert result['commits_rolled_back'] == 2

def test_recover_commit():
    """Test commit recovery from reflog."""
    # Rollback session
    git_manager.rollback_session("test-session")

    # Get rolled back commits
    commits = git_manager.list_session_commits("test-session")

    # Recover one
    success = git_manager.recover_commit(commits[0]['commit_hash'])
    assert success
```

### Tasks

- [ ] Write user documentation
- [ ] Write developer documentation
- [ ] Create test suite
- [ ] Test on sample projects
- [ ] Create demo video/screenshots

## Phase 6: Polish & Launch (Week 7)

### Final Tasks

- [ ] Code review
- [ ] Performance testing
- [ ] Security review
- [ ] UI polish
- [ ] Error message improvements
- [ ] Logging enhancements
- [ ] Create release notes
- [ ] Update README

## Timeline

| Phase | Duration | Deliverables |
|-------|----------|--------------|
| Phase 1: Core Git Module | 2 weeks | GitRollbackManager class, tests |
| Phase 2: Database | 1 week | Schema, migrations, methods |
| Phase 3: Auto-Commit | 1 week | JSONL integration, auto-commit |
| Phase 4: Web UI | 2 weeks | API routes, React components |
| Phase 5: Docs & Tests | 1 week | Documentation, test suite |
| Phase 6: Polish | 1 week | Final testing, release prep |
| **Total** | **8 weeks** | **Full implementation** |

## Success Metrics

Post-implementation tracking:

1. **Rollback Success Rate**: >90% of rollbacks succeed
2. **User Adoption**: >50% of users create checkpoints
3. **Recovery Usage**: Track recovery attempts within 180 days
4. **Performance**: Auto-commit adds <100ms overhead
5. **Storage**: Reflog overhead <5% of project size

## Future Enhancements

Post-v1.0 considerations:

1. **Worktree Support** (if parallel sessions needed)
2. **Conflict Resolution UI** (for cherry-pick conflicts)
3. **Visual Diff Viewer** (syntax-highlighted diffs)
4. **Recovery Branch Management** (list, delete old recovery branches)
5. **Team Collaboration** (shared recovery branches)
6. **AI Commit Messages** (improve auto-generated messages)
7. **Smart Recovery Suggestions** (analyze reflog, suggest recoveries)

## Conclusion

This implementation plan provides a complete roadmap from core git integration through UI implementation to documentation and testing. The 8-week timeline is realistic for a single developer and can be accelerated with team collaboration.
