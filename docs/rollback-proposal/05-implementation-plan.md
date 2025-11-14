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

## Phase 2.5: Fork Detection Integration (Week 3)

### Overview

Integrate automatic fork detection and checkpoint creation based on [02-research-findings.md] Finding 9. This phase adds fork awareness to the rollback system, enabling automatic checkpoints when conversations fork and tracking git state per conversation branch.

### ForkManager Component

**Responsibility:** Detect conversation forks via JSONL monitoring and create automatic checkpoints

**Interface Description:**
```python
class ForkManager:
    """
    Manages fork detection and checkpoint creation.
    Integrates with existing JSONL processor to detect fork events.
    """

    def __init__(self, git_manager, database):
        """Initialize with GitManager and Database instances"""

    def on_fork_detected(self, parent_uuid: str, child_uuid: str) -> dict:
        """
        Called when JSONL processor detects fork (new session with parent_uuid).
        Creates automatic checkpoint at fork point.
        Records fork relationship in database.
        Returns: fork checkpoint info including commit hash
        """

    def get_fork_tree(self, root_uuid: str) -> dict:
        """
        Builds fork tree from database relationships.
        Returns: nested structure of all fork branches
        """

    def get_fork_point(self, fork_uuid: str) -> dict:
        """
        Retrieves fork point checkpoint for a forked session.
        Returns: fork_point_commit, parent_uuid, timestamp
        """
```

### Database Migration for Fork Tracking

**Schema Extension:**
```sql
-- New table: conversation_forks
CREATE TABLE IF NOT EXISTS conversation_forks (
    parent_uuid TEXT NOT NULL,
    child_uuid TEXT NOT NULL,
    fork_point_commit TEXT NOT NULL,
    fork_checkpoint_id TEXT,
    message_uuid TEXT,  -- For conversation context
    created_at TIMESTAMP NOT NULL,
    PRIMARY KEY (parent_uuid, child_uuid),
    FOREIGN KEY (parent_uuid) REFERENCES sessions(uuid),
    FOREIGN KEY (child_uuid) REFERENCES sessions(uuid)
);

-- Extend sessions table
ALTER TABLE sessions ADD COLUMN fork_parent_uuid TEXT;
ALTER TABLE sessions ADD COLUMN current_commit TEXT;

-- Extend git_checkpoints table
ALTER TABLE git_checkpoints ADD COLUMN message_uuid TEXT;
ALTER TABLE git_checkpoints ADD COLUMN checkpoint_type TEXT DEFAULT 'manual';

-- Indexes for performance
CREATE INDEX idx_conversation_forks_parent ON conversation_forks(parent_uuid);
CREATE INDEX idx_conversation_forks_child ON conversation_forks(child_uuid);
CREATE INDEX idx_sessions_fork_parent ON sessions(fork_parent_uuid);
```

### Database Methods for Fork Operations

**Method Interfaces:**
```python
# database.py additions

def create_fork_relationship(
    self,
    parent_uuid: str,
    child_uuid: str,
    fork_point_commit: str,
    fork_checkpoint_id: str
) -> None:
    """
    Record fork relationship when conversation branches.
    Links parent and child sessions with git commit at fork point.
    """

def get_fork_children(self, parent_uuid: str) -> List[dict]:
    """
    Get all child sessions that forked from parent.
    Returns: list of fork records with child_uuid, fork_point_commit, created_at
    """

def get_fork_tree(self, root_uuid: str) -> dict:
    """
    Recursively build entire fork tree from root session.
    Returns: nested dict structure representing fork hierarchy
    """

def update_session_commit(self, session_uuid: str, commit_hash: str) -> None:
    """
    Update current_commit for session as work progresses.
    Used for tracking git state per conversation branch.
    """

def get_checkpoints_with_context(
    self,
    session_uuid: str,
    limit: int = 50
) -> List[dict]:
    """
    Get checkpoints with message context for UI navigation.
    Returns bounded list with message_uuid and preview.
    """

def get_checkpoint_messages(
    self,
    checkpoint_id: str,
    before: int = 30,
    after: int = 0
) -> List[dict]:
    """
    Get conversation messages around checkpoint.
    Default: last 30 messages before checkpoint.
    """
```

### JSONL Integration for Fork Detection

**Hook Point:**
```python
# jsonl_processor.py integration

def process_session_entry(entry: dict):
    """
    Process session start entry from JSONL.
    Detects fork by checking for parent_session_uuid field.
    """
    session_uuid = entry.get('uuid')
    parent_uuid = entry.get('parent_session_uuid')

    if parent_uuid:
        # Fork detected!
        fork_manager.on_fork_detected(
            parent_uuid=parent_uuid,
            child_uuid=session_uuid
        )
```

**Detection Pattern:**
- Monitor JSONL for new session entries with `parent_session_uuid` field
- Cross-session detection (fork may be in different .jsonl file)
- Real-time detection via file watcher (2-second poll interval)
- ~115ms overhead per fork event (acceptable)

### Testing for Fork Detection

**Test Scenarios:**

1. **Single Fork Detection**
   - Create parent session with checkpoint
   - Create child session with parent_uuid
   - Verify automatic checkpoint created at fork point
   - Verify database records fork relationship

2. **Multiple Forks from Same Parent**
   - Create parent session
   - Create 3 child sessions from same parent
   - Verify 3 separate fork checkpoints
   - Verify all fork relationships recorded

3. **Nested Forks (Fork of Fork)**
   - Create parent → child1 → grandchild
   - Verify checkpoint at each fork point
   - Verify fork tree builds correctly

4. **Cross-Session File Fork Detection**
   - Parent in session-abc.jsonl
   - Child in session-def.jsonl
   - Verify detection across files

5. **Performance Test**
   - Create 10+ forks in rapid succession
   - Verify all detected within expected timeframe
   - Verify no checkpoint creation failures

### Tasks

- [ ] Implement ForkManager class
- [ ] Add conversation_forks table migration
- [ ] Add fork-related database methods
- [ ] Add checkpoint selector methods (get_checkpoints_with_context, get_checkpoint_messages)
- [ ] Integrate fork detection into JSONL processor
- [ ] Store message_uuid with each checkpoint
- [ ] Write unit tests for fork detection
- [ ] Write integration tests for checkpoint creation
- [ ] Test cross-session fork detection
- [ ] Test message context retrieval
- [ ] Document fork detection behavior

## Phase 3: Auto-Commit Integration (Week 4)

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

## Phase 4: Web UI Integration (Week 5-6)

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

# Fork-aware API endpoints
@app.route('/api/sessions/<session_id>/fork-tree', methods=['GET'])
def get_fork_tree(session_id):
    """Get fork tree for session (parent and all children)."""
    tree = fork_manager.get_fork_tree(session_id)
    return jsonify(tree)

@app.route('/api/sessions/<session_id>/rollback-to-fork', methods=['POST'])
def rollback_to_fork_point(session_id):
    """Rollback to fork point (where this session branched from parent)."""
    fork_info = fork_manager.get_fork_point(session_id)
    if not fork_info:
        return jsonify({'error': 'Not a forked session'}), 400
    result = git_manager.rollback_to_commit(fork_info['fork_point_commit'])
    return jsonify(result)

@app.route('/api/forks/compare', methods=['POST'])
def compare_forks():
    """Compare changes between two fork branches."""
    fork_a_uuid = request.json.get('fork_a')
    fork_b_uuid = request.json.get('fork_b')
    comparison = fork_manager.compare_fork_branches(fork_a_uuid, fork_b_uuid)
    return jsonify(comparison)
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

**Fork Tree Visualization Component:**

```javascript
<div className="fork-tree-view">
  <h3>Conversation Fork Tree</h3>
  <ForkTreeNode node={rootNode} depth={0} />
</div>

const ForkTreeNode = ({ node, depth }) => (
  <div className="fork-node" style={{ marginLeft: depth * 20 }}>
    <div className="fork-header">
      <span className="fork-icon">{depth > 0 ? '└─' : ''}</span>
      <span className="session-label">
        {node.is_current ? '● ' : '○ '}
        {node.session_name || node.session_uuid.substring(0, 8)}
      </span>
      {node.fork_point_commit && (
        <span className="git-hash">
          Fork point: {node.fork_point_commit.substring(0, 8)}
        </span>
      )}
      <span className="fork-time">{formatTime(node.created_at)}</span>
    </div>

    <div className="fork-stats">
      Current: {node.current_commit?.substring(0, 8)} •
      {node.commits_ahead} commits since fork
    </div>

    <div className="fork-actions">
      <button onClick={() => viewForkDiff(node)}>View Changes</button>
      <button onClick={() => rollbackToFork(node)}>Rollback to Fork Point</button>
      {node.siblings?.length > 0 && (
        <button onClick={() => compareForks(node)}>Compare with Siblings</button>
      )}
    </div>

    {node.children?.map(child => (
      <ForkTreeNode key={child.session_uuid} node={child} depth={depth + 1} />
    ))}
  </div>
);
```

**Checkpoint Selector Component (Non-Destructive UI):**

```javascript
const CheckpointSelector = ({ sessionId }) => {
  const [checkpoints, setCheckpoints] = useState([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [messages, setMessages] = useState([]);

  const currentCheckpoint = checkpoints[currentIndex];

  useEffect(() => {
    // Load checkpoints with context
    fetch(`/api/sessions/${sessionId}/checkpoints?limit=50`)
      .then(res => res.json())
      .then(data => setCheckpoints(data.checkpoints));
  }, [sessionId]);

  useEffect(() => {
    if (currentCheckpoint) {
      // Load last 30 messages for context
      fetch(`/api/checkpoints/${currentCheckpoint.checkpoint_id}/messages?before=30`)
        .then(res => res.json())
        .then(data => setMessages(data.messages));
    }
  }, [currentCheckpoint]);

  const handlePrevious = () => {
    if (currentIndex > 0) setCurrentIndex(currentIndex - 1);
  };

  const handleNext = () => {
    if (currentIndex < checkpoints.length - 1) setCurrentIndex(currentIndex + 1);
  };

  return (
    <div className="checkpoint-selector">
      <h2>Select Checkpoint to Restore</h2>

      <div className="checkpoint-navigation">
        <button onClick={handlePrevious} disabled={currentIndex === 0}>
          ←
        </button>
        <span>Checkpoint {currentIndex + 1} of {checkpoints.length}</span>
        <button onClick={handleNext} disabled={currentIndex === checkpoints.length - 1}>
          →
        </button>
      </div>

      {currentCheckpoint && (
        <div className="checkpoint-details">
          <div className="checkpoint-header">
            <span className="checkpoint-type">{currentCheckpoint.checkpoint_type}</span>
            <span className="checkpoint-time">
              {formatTime(currentCheckpoint.created_at)}
            </span>
            <span className="checkpoint-commit">
              Commit: {currentCheckpoint.checkpoint_commit.substring(0, 8)}
            </span>
          </div>

          <div className="checkpoint-messages">
            <h3>Last 30 messages:</h3>
            <div className="message-list">
              {messages.map(msg => (
                <div key={msg.message_uuid}
                     className={`message ${msg.is_checkpoint ? 'checkpoint-message' : ''}`}>
                  <div className="message-header">
                    <span className="role">{msg.role}</span>
                    <span className="time">{formatTime(msg.timestamp)}</span>
                    {msg.is_checkpoint && <span className="badge">← CHECKPOINT</span>}
                  </div>
                  <div className="message-content">{msg.content}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="restore-actions">
            <p className="reversibility-note">
              All actions are reversible via reflog (180-day window)
            </p>

            <button onClick={() => handlePreview(currentCheckpoint)}>
              Preview Changes
            </button>
            <p className="action-description">
              View diff without making any changes
            </p>

            <button onClick={() => handleRollback(currentCheckpoint)}
                    className="primary-action">
              Rollback to Checkpoint (non-destructive)
            </button>
            <p className="action-description">
              Reset to this point. Changes go to reflog (180 days)
            </p>

            <button onClick={() => handleViewMessages(currentCheckpoint)}>
              View Messages Only
            </button>
            <p className="action-description">
              Read conversation context without rollback
            </p>
          </div>
        </div>
      )}
    </div>
  );
};
```

**Fork Comparison Modal:**

```javascript
<Modal show={showForkComparison}>
  <h2>Compare Fork Branches</h2>

  <div className="fork-comparison">
    <div className="fork-column">
      <h3>Fork A: {forkA.name}</h3>
      <div className="fork-info">
        <p>Fork point: {forkA.fork_point_commit.substring(0, 8)}</p>
        <p>Current: {forkA.current_commit.substring(0, 8)}</p>
        <p>Commits: {forkA.commits.length}</p>
      </div>
      <CommitList commits={forkA.commits} />
    </div>

    <div className="fork-divider">↔</div>

    <div className="fork-column">
      <h3>Fork B: {forkB.name}</h3>
      <div className="fork-info">
        <p>Fork point: {forkB.fork_point_commit.substring(0, 8)}</p>
        <p>Current: {forkB.current_commit.substring(0, 8)}</p>
        <p>Commits: {forkB.commits.length}</p>
      </div>
      <CommitList commits={forkB.commits} />
    </div>
  </div>

  <div className="diff-preview">
    <h3>File Changes Comparison</h3>
    <DiffViewer
      oldContent={forkA.diff}
      newContent={forkB.diff}
      splitView={true}
    />
  </div>

  <div className="actions">
    <button onClick={closeForkComparison}>Close</button>
  </div>
</Modal>
```

### Tasks

- [ ] Implement API routes (including fork endpoints)
- [ ] Implement checkpoint selector API endpoints
  - [ ] GET /api/sessions/{id}/checkpoints
  - [ ] GET /api/checkpoints/{id}/messages
  - [ ] GET /api/checkpoints/{id}/preview
- [ ] Create React components
- [ ] Add CheckpointSelector component with bounded navigation
- [ ] Add fork tree visualization component
- [ ] Add fork comparison modal
- [ ] Implement three restore actions (Preview, Rollback, View Messages)
- [ ] Add message context display (last 30 messages)
- [ ] Implement diff viewer
- [ ] Add reversibility indicators and non-destructive messaging
- [ ] Add loading states and error handling
- [ ] Style components with emphasis on non-destructive default

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
| Phase 2.5: Fork Detection | 1 week | ForkManager, fork tracking, auto-checkpoints |
| Phase 3: Auto-Commit | 1 week | JSONL integration, auto-commit |
| Phase 4: Web UI | 2 weeks | API routes, React components, fork visualization |
| Phase 5: Docs & Tests | 1 week | Documentation, test suite, fork tests |
| Phase 6: Polish | 1 week | Final testing, release prep |
| **Total** | **9 weeks** | **Full implementation with fork awareness** |

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

This implementation plan provides a complete roadmap from core git integration through UI implementation to documentation and testing, including fork detection and visualization. The 9-week timeline is realistic for a single developer and can be accelerated with team collaboration.

**Key Addition:** Phase 2.5 adds fork awareness based on [02-research-findings.md] Finding 9, enabling automatic checkpoints when conversations fork and providing fork tree visualization in the UI.
