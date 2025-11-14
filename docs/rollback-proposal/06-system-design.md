# System Design: Reflog-Based Rollback

## 1. Design Overview

### 1.1 Purpose

This document provides the complete technical system design for implementing reflog-based rollback functionality in claude-log-viewer. It bridges the gap between the conceptual proposals (documents 01-05) and the actual implementation, serving as the definitive technical specification for developers.

### 1.2 Design Philosophy

The design is guided by three core principles derived from requirements analysis:

1. **Clean Git History** - Rolled-back sessions must be invisible in git log
2. **Single Working Directory** - No infrastructure duplication (worktrees, multiple servers)
3. **Reliable Rollback** - Capture all changes (Edit, Write, and Bash operations)

These principles form what [01-problem-statement.md] called the "trilemma" - most solutions satisfy only 2 of 3. The reflog-based approach is the only strategy that satisfies all three simultaneously (see [03-options-analysis.md] scoring matrix).

### 1.3 Approach Summary

```
Session Lifecycle:
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  1. Create Checkpoint (record HEAD position)                │
│  2. Auto-commit on each tool use (Edit/Write/Bash)         │
│  3. Track commits in database (session_uuid → commits)      │
│  4. User reviews commits                                    │
│  5. Decision:                                               │
│     • Keep → Push to remote (permanent)                    │
│     • Discard → git reset --hard (commits → reflog)        │
│     • Recover → Cherry-pick from reflog                    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

Key insight from [02-research-findings.md]: Git reflog enables a "commit now, decide later" workflow while maintaining clean history through strategic use of `git reset --hard`.

## 2. Requirements Mapping

### 2.1 Primary Requirements Satisfaction

| Requirement (from [01-problem-statement.md]) | Design Solution | Design Section |
|----------------------------------------------|-----------------|----------------|
| **Clean Git History** | Use `git reset --hard` to move commits to reflog, making them invisible in git log | 4.2 Commit Manager |
| **Single Working Directory** | Work directly on current branch, no worktrees | 3.1 Architecture |
| **Reliable Rollback** | Git commits capture all file changes regardless of source | 4.2 Commit Manager |
| **Agent Granularity** | Track agent_id in commit messages and database | 5.2 Git Commits Table |
| **Ease of Use** | Web UI with visual commit timeline and one-click rollback | 7.1 UI Components |
| **No Manual Git Management** | Automated checkpoint creation, auto-commits, and cleanup | 4.1 Session Manager |

### 2.2 Secondary Requirements

| Requirement | Solution | Notes |
|-------------|----------|-------|
| Recovery window (weeks/months) | Extend reflog retention to 180 days | Configurable via git config |
| Partial recovery | Cherry-pick specific commits from reflog | UI for selective recovery |
| Preview before rollback | Display commit list and diff view | Prevent accidental data loss |
| Undo/redo capability | Reflog tracks resets themselves | Can undo a rollback |

### 2.3 Research-Informed Design Decisions

Based on [02-research-findings.md]:

- **Industry pattern adoption**: Follow Aider's "frequent commits + git safety net" pattern (Finding 7)
- **Proven technology**: Built on 15+ year git reflog track record (Finding 3)
- **Avoid JSONL reversal**: Critical analysis identified 10+ fatal flaws (Finding 4)
- **No worktrees**: Infrastructure duplication unacceptable (Finding 2)

## 3. Architecture

### 3.1 System Context

```
┌────────────────────────────────────────────────────────────────┐
│                     claude-log-viewer                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐        │
│  │   Web UI     │  │   Flask API  │  │   Database   │        │
│  │  (React)     │◄─┤   (Python)   │◄─┤  (SQLite)    │        │
│  └──────────────┘  └──────────────┘  └──────────────┘        │
│         ▲                  │                                   │
│         │                  ▼                                   │
│         │          ┌──────────────┐                           │
│         │          │ Git Manager  │                           │
│         │          │  (New)       │                           │
│         │          └──────┬───────┘                           │
└─────────┼─────────────────┼───────────────────────────────────┘
          │                 │
          │                 ▼
    User Actions    ┌──────────────┐
    (browser)       │ Git Repo     │
                    │ (.git)       │
                    │  - commits   │
                    │  - reflog    │
                    │  - branches  │
                    └──────────────┘
```

### 3.2 Component Architecture

```
claude_log_viewer/
├── app.py                    # Flask routes (existing + new rollback API)
├── database.py               # Database manager (extended)
├── git_manager.py           # Git operations manager (NEW)
├── jsonl_processor.py       # JSONL parsing (existing)
└── models/
    ├── session.py           # Session model (existing)
    ├── checkpoint.py        # Checkpoint model (NEW)
    └── git_commit.py        # Git commit tracking (NEW)

Database:
├── sessions                 # Existing session tracking
├── git_checkpoints         # NEW: Checkpoint tracking
├── git_commits             # NEW: Commit tracking
└── tool_results            # Existing tool result tracking
```

### 3.3 Data Flow

**Checkpoint Creation Flow:**
```
1. User clicks "Create Checkpoint"
   ↓
2. UI → API: POST /api/sessions/{id}/checkpoint
   ↓
3. API → GitManager: create_checkpoint(session_uuid)
   ↓
4. GitManager → Git: git rev-parse HEAD
   ↓
5. GitManager → Database: store checkpoint
   ↓
6. API → UI: Return checkpoint info
```

**Auto-Commit Flow:**
```
1. Claude Code executes tool (Edit/Write/Bash)
   ↓
2. JSONL log written to disk
   ↓
3. JSONLProcessor detects tool_result
   ↓
4. JSONLProcessor → GitManager: auto_commit()
   ↓
5. GitManager → Git: git add -A && git commit
   ↓
6. GitManager → Database: store commit metadata
   ↓
7. UI updates commit timeline (WebSocket/polling)
```

**Rollback Flow:**
```
1. User clicks "Rollback Session"
   ↓
2. UI shows confirmation modal with diff preview
   ↓
3. User confirms
   ↓
4. API → GitManager: rollback_session()
   ↓
5. GitManager → Git: git reset --hard <checkpoint>
   ↓
6. GitManager → Database: update checkpoint status
   ↓
7. UI shows success message + reflog info
```

### 3.4 Integration Points

**With Existing Systems:**

1. **JSONL Processing** (existing)
   - Hook into tool_result processing
   - Extract tool name, file paths, descriptions
   - Trigger auto-commit

2. **Session Tracking** (existing)
   - Link checkpoints to sessions
   - Track session lifecycle
   - Determine when to prompt for rollback

3. **Web UI** (existing)
   - Add rollback controls to session detail page
   - Show commit timeline in session view
   - Display git status indicators

4. **Database** (existing)
   - Extend with git_checkpoints and git_commits tables
   - Foreign key relationships to sessions

## 4. Component Design

### 4.1 Session Manager (Extended)

**Responsibility:** Manage session lifecycle and checkpoint creation

**Key Methods:**

```python
class SessionManager:
    def start_session(self, session_uuid: str) -> Dict:
        """
        Called when new Claude session detected.
        Creates git checkpoint automatically.
        """
        # 1. Verify git repo exists
        # 2. Record current HEAD position
        # 3. Create checkpoint in database
        # 4. Optionally create git tag for permanent preservation
        # Returns: checkpoint info

    def end_session(self, session_uuid: str) -> Dict:
        """
        Called when session ends.
        Prompts user for keep/rollback decision.
        """
        # 1. Get all commits for session
        # 2. Calculate session statistics
        # 3. Prepare rollback decision prompt
        # Returns: session summary

    def get_session_status(self, session_uuid: str) -> Dict:
        """
        Returns current session status including:
        - Checkpoint status (active/kept/rolled_back)
        - Number of commits
        - Files changed
        - Current HEAD position
        """
```

**Design Decision:** Automatic checkpoint creation (referenced in [04-solution-selection.md], Section "No Manual Git Management")

**Rationale:** Eliminates user error of forgetting to create checkpoint. Addresses [99-critical-analysis.md] Question 1 concern about "relies on user discipline."

### 4.2 Commit Manager (New Component)

**Responsibility:** Handle git commit operations and tracking

**Interface:**

```python
class GitCommitManager:
    def __init__(self, project_root: Path, database: Database):
        """
        Initialize with project root and database connection.
        Verifies git repo and configures reflog retention.
        """

    def auto_commit(
        self,
        session_uuid: str,
        tool_name: str,
        description: str,
        agent_id: Optional[str] = None,
        tool_use_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Auto-commit changes after tool execution.

        Process:
        1. Check for changes (git status --porcelain)
        2. Stage all changes (git add -A)
        3. Generate commit message with metadata
        4. Create commit
        5. Store commit in database
        6. Return commit hash

        Commit Message Format:
        ---
        Claude [ToolName]: Brief description

        Session: <session_uuid>
        Agent: <agent_id>
        Tool: <tool_name>
        Tool use ID: <tool_use_id>

        🤖 Generated with Claude Code
        ---
        """

    def get_commit_diff(self, commit_hash: str) -> str:
        """
        Get diff for specific commit.
        Returns: unified diff format
        """

    def list_commits(
        self,
        session_uuid: str,
        agent_id: Optional[str] = None
    ) -> List[CommitInfo]:
        """
        List commits for session, optionally filtered by agent.
        Returns: List of commit metadata with diffs
        """
```

**Design Decision:** Auto-commit on every tool use (not manual commits)

**Rationale:**
- Addresses [01-problem-statement.md] requirement "handles Edit/Write/Bash"
- Follows industry pattern from [02-research-findings.md] Finding 7 (Aider's approach)
- Mitigates [99-critical-analysis.md] Question 3 concern through commit message quality

**Performance Consideration:** Addresses [99-critical-analysis.md] Question 8

```python
# Optimization strategies for large repos:
# 1. Async commits (don't block UI)
# 2. Only stage changed files (not git add -A for everything)
# 3. Commit batching option (configurable)
# 4. Skip commit if no changes detected
```

### 4.3 Rollback Manager (New Component)

**Responsibility:** Execute rollback operations and recovery

**Interface:**

```python
class RollbackManager:
    def rollback_session(
        self,
        session_uuid: str,
        create_recovery_branch: bool = False
    ) -> RollbackResult:
        """
        Rollback session to checkpoint.

        Process:
        1. Retrieve checkpoint from database
        2. Get all session commits (for reporting)
        3. Optionally push to recovery branch
        4. Check for uncommitted changes (stash if present)
        5. Execute: git reset --hard <checkpoint_commit>
        6. Update database checkpoint status
        7. Return rollback summary

        Returns:
        {
            'success': bool,
            'checkpoint': str,
            'commits_rolled_back': int,
            'recovery_branch': Optional[str],
            'commits': List[str]
        }
        """

    def create_recovery_branch(
        self,
        session_uuid: str,
        branch_name: Optional[str] = None
    ) -> str:
        """
        Push current HEAD to recovery branch before rollback.

        Format: recovery/session-{uuid}
        Location: Origin remote (permanent backup)

        This addresses [99-critical-analysis.md] Question 1
        concern about time-limited recovery.
        """

    def cherry_pick_commit(self, commit_hash: str) -> RecoveryResult:
        """
        Recover specific commit from reflog.

        Process:
        1. Verify commit exists in reflog
        2. Attempt cherry-pick
        3. Handle conflicts if they occur
        4. Return success status

        Conflict Handling (addresses [99-critical-analysis.md] Q4):
        - Detect conflict
        - Return conflict details
        - Provide resolution options:
          - Abort
          - Manual resolution (show conflict markers)
          - Automatic resolution strategies
        """

    def recover_session(
        self,
        session_uuid: str,
        commit_selection: List[str] = None
    ) -> RecoveryResult:
        """
        Recover entire session or selected commits.

        If commit_selection is None, recover all commits.
        If specified, only recover selected commits.

        Supports partial recovery requirement from
        [01-problem-statement.md] "Secondary Requirements #3"
        """
```

**Design Decision:** Mandatory recovery branch option

**Rationale:** Critical safety net per [99-critical-analysis.md] conclusion: "Do NOT skip Phase 1.5 - Recovery branches are the safety net that makes this approach acceptable."

### 4.4 Reflog Manager (New Component)

**Responsibility:** Interface with git reflog

**Interface:**

```python
class ReflogManager:
    def configure_retention(self, days: int = 180):
        """
        Configure reflog retention period.

        Default: 180 days (6 months)
        Per [04-solution-selection.md] mitigation strategy

        Sets:
        - gc.reflogExpire = {days} days
        - gc.reflogExpireUnreachable = {days} days
        """

    def get_reflog_entries(
        self,
        max_entries: int = 100
    ) -> List[ReflogEntry]:
        """
        Parse git reflog output.

        Returns:
        [
            {
                'ref': 'HEAD@{0}',
                'commit': 'abc123...',
                'action': 'commit',
                'message': 'Commit message',
                'timestamp': datetime
            },
            ...
        ]
        """

    def find_commit_in_reflog(self, commit_hash: str) -> Optional[str]:
        """
        Find reflog reference for commit.

        Returns: HEAD@{n} reference or None
        Used for recovery operations
        """

    def get_reflog_stats(self) -> Dict:
        """
        Get reflog statistics.

        Returns:
        {
            'total_entries': int,
            'oldest_entry': datetime,
            'estimated_expiration': datetime,
            'size_bytes': int
        }

        Used for UI display and monitoring
        """
```

**Design Decision:** Abstract reflog operations into dedicated component

**Rationale:** Isolates git reflog complexity, makes testing easier, allows for future reflog format changes

### 4.5 Fork Manager (New Component)

**Responsibility:** Detect conversation forks and create automatic checkpoints

**Design Context:** Based on [02-research-findings.md] Finding 9 and [01-problem-statement.md] Requirement 4 (Fork-Aware Rollback)

**Interface:**

```python
class ForkManager:
    def __init__(self, git_manager: GitManager, database: Database):
        """
        Initialize with GitManager and Database instances.
        Integrates with JSONL processor for fork detection.
        """

    def on_fork_detected(
        self,
        parent_uuid: str,
        child_uuid: str
    ) -> Dict[str, any]:
        """
        Called when JSONL processor detects conversation fork.

        Process:
        1. Get current HEAD (this is the fork point)
        2. Create checkpoint with type='fork_point'
        3. Record fork relationship in database
        4. Update child session metadata (fork_parent_uuid, current_commit)
        5. Record message_uuid for checkpoint context (last 30 messages)
        6. Return fork checkpoint info

        Returns:
        {
            'fork_point_commit': str,  # Git hash at fork
            'parent_uuid': str,
            'child_uuid': str,
            'checkpoint_id': str,
            'message_uuid': str,  # For conversation context
            'created_at': datetime
        }

        Called by: JSONL processor when detecting new session with parent_uuid
        """

    def get_fork_tree(
        self,
        root_uuid: str,
        include_commits: bool = False
    ) -> Dict[str, any]:
        """
        Build fork tree from database relationships.

        Returns nested structure:
        {
            'session_uuid': str,
            'fork_point_commit': Optional[str],
            'current_commit': str,
            'created_at': datetime,
            'commits_ahead': int,  # Commits since fork point
            'children': List[Dict],  # Recursive fork tree
            'commits': Optional[List[Dict]]  # If include_commits=True
        }

        Used for: UI fork tree visualization
        """

    def get_fork_point(self, fork_uuid: str) -> Optional[Dict]:
        """
        Get fork point information for a forked session.

        Returns:
        {
            'fork_point_commit': str,
            'parent_uuid': str,
            'created_at': datetime,
            'checkpoint_id': str,
            'message_uuid': str  # For conversation context
        }

        Returns None if not a forked session.
        Used for: "Rollback to fork point" operation
        """

    def get_checkpoints_with_context(
        self,
        session_uuid: str,
        limit: int = 50
    ) -> List[Dict]:
        """
        Get all checkpoints for session with message context.
        Returns bounded list for UI navigation.

        Returns:
        [
            {
                'checkpoint_id': str,
                'checkpoint_commit': str,
                'message_uuid': str,
                'message_timestamp': datetime,
                'message_preview': str,  # First 100 chars
                'created_at': datetime,
                'checkpoint_type': str  # 'manual' | 'fork_point' | 'auto'
            }
        ]

        Used for: Checkpoint selector UI with bounded navigation
        """

    def get_checkpoint_messages(
        self,
        checkpoint_id: str,
        before: int = 30,
        after: int = 0
    ) -> List[Dict]:
        """
        Get conversation messages around checkpoint for context.
        Default: last 30 messages before checkpoint.

        Returns:
        [
            {
                'message_uuid': str,
                'content': str,
                'role': str,  # 'user' | 'assistant'
                'timestamp': datetime,
                'is_checkpoint': bool  # True for checkpoint message
            }
        ]

        Used for: Showing conversation context in checkpoint selector
        """

    def compare_fork_branches(
        self,
        fork_a_uuid: str,
        fork_b_uuid: str
    ) -> Dict[str, any]:
        """
        Compare changes between two fork branches.

        Process:
        1. Find common ancestor (fork point)
        2. Get commits from ancestor to each fork
        3. Compute diffs for each branch
        4. Return comparison data

        Returns:
        {
            'common_ancestor': str,
            'fork_a': {
                'commits': List[Dict],
                'diff': str,
                'files_changed': List[str]
            },
            'fork_b': {
                'commits': List[Dict],
                'diff': str,
                'files_changed': List[str]
            }
        }

        Used for: UI fork comparison modal
        """
```

**Integration Points:**

1. **JSONL Processor Hook**
   ```python
   # jsonl_processor.py
   def process_session_entry(entry: dict):
       if entry.get('parent_session_uuid'):
           fork_manager.on_fork_detected(
               parent_uuid=entry['parent_session_uuid'],
               child_uuid=entry['uuid']
           )
   ```

2. **Database Integration**
   - Reads/writes conversation_forks table
   - Updates sessions table (fork_parent_uuid, current_commit)
   - Queries git_checkpoints for fork point info

3. **Git Manager Integration**
   - Uses git_manager.create_checkpoint() for fork points
   - Uses git_manager.get_commit_diff() for comparisons
   - Uses git reflog for commit history analysis

**Design Decision:** Automatic checkpoint creation on fork detection

**Rationale:**
- User doesn't need to remember to checkpoint before forking
- 95%+ fork detection rate (proven in existing implementation)
- ~115ms overhead per fork (acceptable)
- Addresses [01-problem-statement.md] Scenario 4 (missing fork checkpoints)

## 5. Data Model

### 5.1 Git Checkpoints Table

```sql
CREATE TABLE IF NOT EXISTS git_checkpoints (
    -- Primary identification
    session_uuid TEXT PRIMARY KEY,

    -- Checkpoint information
    checkpoint_commit TEXT NOT NULL,      -- Git commit hash at checkpoint
    checkpoint_reflog TEXT NOT NULL,      -- Reflog ref (HEAD@{n})
    checkpoint_branch TEXT,               -- Branch name at checkpoint
    message_uuid TEXT,                    -- JSONL message UUID for context

    -- Metadata
    created_at TIMESTAMP NOT NULL,
    status TEXT NOT NULL CHECK(
        status IN ('active', 'kept', 'rolled_back')
    ),
    checkpoint_type TEXT DEFAULT 'manual', -- 'manual' | 'fork_point' | 'auto'

    -- Recovery options
    recovery_tag TEXT,                    -- Git tag for permanent preservation
    recovery_branch TEXT,                 -- Remote branch for backup

    -- Relationships
    FOREIGN KEY (session_uuid) REFERENCES sessions(uuid)
        ON DELETE CASCADE
);

-- Index for status queries
CREATE INDEX idx_git_checkpoints_status
    ON git_checkpoints(status);

-- Index for date-based queries
CREATE INDEX idx_git_checkpoints_created
    ON git_checkpoints(created_at);
```

**Design Rationale:**

- **session_uuid as PK**: One checkpoint per session (1:1 relationship)
- **recovery_tag and recovery_branch**: Support for permanent backup strategy (mitigates [99-critical-analysis.md] Question 1)
- **status field**: Track lifecycle (active → kept/rolled_back)

### 5.2 Git Commits Table

```sql
CREATE TABLE IF NOT EXISTS git_commits (
    -- Git information
    commit_hash TEXT PRIMARY KEY,         -- Git commit SHA

    -- Session tracking
    session_uuid TEXT NOT NULL,
    agent_id TEXT,                        -- NULL for main session

    -- Commit metadata
    message TEXT,                         -- Full commit message
    timestamp TIMESTAMP NOT NULL,
    author_name TEXT,
    author_email TEXT,

    -- Tool tracking
    tool_use_id TEXT,                    -- Link to JSONL tool_use_id
    tool_name TEXT,                      -- Edit/Write/Bash
    tool_description TEXT,               -- Brief description

    -- Recovery tracking
    in_reflog BOOLEAN DEFAULT 1,        -- Still accessible in reflog?
    recovered BOOLEAN DEFAULT 0,         -- Was this commit recovered?

    -- Relationships
    FOREIGN KEY (session_uuid) REFERENCES sessions(uuid)
        ON DELETE CASCADE,
    FOREIGN KEY (tool_use_id) REFERENCES tool_results(tool_use_id)
        ON DELETE SET NULL
);

-- Performance indexes
CREATE INDEX idx_git_commits_session
    ON git_commits(session_uuid);

CREATE INDEX idx_git_commits_agent
    ON git_commits(agent_id);

CREATE INDEX idx_git_commits_timestamp
    ON git_commits(timestamp);

CREATE INDEX idx_git_commits_tool
    ON git_commits(tool_use_id);
```

**Design Rationale:**

- **tool_use_id link**: Connects to existing JSONL data structure
- **agent_id tracking**: Satisfies "Agent Granularity" requirement from [01-problem-statement.md]
- **in_reflog flag**: Track whether commit still accessible (for UI indication)
- **Foreign key to tool_results**: Bi-directional navigation

### 5.3 Conversation Forks Table

**Design Context:** Based on [02-research-findings.md] Finding 9 - Fork detection and tracking

```sql
CREATE TABLE IF NOT EXISTS conversation_forks (
    -- Fork relationship
    parent_uuid TEXT NOT NULL,
    child_uuid TEXT NOT NULL,

    -- Fork point information
    fork_point_commit TEXT NOT NULL,      -- Git hash at fork time
    fork_checkpoint_id TEXT,              -- Link to checkpoint
    message_uuid TEXT,                    -- JSONL message UUID for context

    -- Metadata
    created_at TIMESTAMP NOT NULL,

    -- Primary key
    PRIMARY KEY (parent_uuid, child_uuid),

    -- Foreign keys
    FOREIGN KEY (parent_uuid) REFERENCES sessions(uuid)
        ON DELETE CASCADE,
    FOREIGN KEY (child_uuid) REFERENCES sessions(uuid)
        ON DELETE CASCADE,
    FOREIGN KEY (fork_checkpoint_id) REFERENCES git_checkpoints(session_uuid)
        ON DELETE SET NULL
);

-- Performance indexes
CREATE INDEX idx_conversation_forks_parent
    ON conversation_forks(parent_uuid);

CREATE INDEX idx_conversation_forks_child
    ON conversation_forks(child_uuid);

CREATE INDEX idx_conversation_forks_commit
    ON conversation_forks(fork_point_commit);
```

**Schema Extension: Sessions Table**

```sql
-- Extend existing sessions table
ALTER TABLE sessions ADD COLUMN fork_parent_uuid TEXT;
ALTER TABLE sessions ADD COLUMN current_commit TEXT;

-- Add foreign key constraint
ALTER TABLE sessions ADD CONSTRAINT fk_fork_parent
    FOREIGN KEY (fork_parent_uuid) REFERENCES sessions(uuid)
    ON DELETE SET NULL;

-- Add index for fork queries
CREATE INDEX idx_sessions_fork_parent
    ON sessions(fork_parent_uuid);
```

**Design Rationale:**

- **Composite PK (parent_uuid, child_uuid)**: One fork relationship per parent-child pair
- **fork_point_commit**: Git hash at exact moment of fork (enables rollback to fork point)
- **fork_checkpoint_id**: Links to checkpoint table for additional metadata
- **CASCADE deletes**: If session deleted, remove fork relationships
- **current_commit in sessions**: Track git state per conversation branch
- **fork_parent_uuid in sessions**: Quick lookup of parent session

### 5.4 Data Relationships

```
sessions (existing/extended)
    ↓ 1:1
git_checkpoints (new)
    ↓ 1:many
git_commits (new)
    ↓ many:1
tool_results (existing)

sessions (extended)
    ↓ 1:many (parent → children)
conversation_forks (new)
    ↓ many:1 (children → parent)
sessions (extended)
```

**Entity Relationship Diagram (ASCII):**

```
┌──────────────────┐
│    sessions      │
│  (extended)      │
│──────────────────│
│ uuid [PK]        │◄──────────┐
│ fork_parent_uuid │───┐       │ (parent → children)
│ current_commit   │   │       │
│ start_time       │   │       │
│ ...              │   │       │
└────────┬─────────┘   │       │
         │ 1:1         │       │
         ▼             │       │
┌──────────────────┐   │       │
│ git_checkpoints  │   │       │
│     (new)        │   │       │
│──────────────────│   │       │
│ session_uuid [PK]│──┐│       │
│ checkpoint_...   │  ││       │
│ status           │  ││       │
│ recovery_...     │  ││       │
└──────────────────┘  ││       │
         │ 1:many     ││       │
         ▼            ││       │
┌──────────────────┐  ││       │
│  git_commits     │  ││       │
│     (new)        │  ││       │
│──────────────────│  ││       │
│ commit_hash [PK] │  ││       │
│ session_uuid     │◄─┘│       │
│ agent_id         │   │       │
│ tool_use_id      │──┐│       │
│ message          │  ││       │
│ ...              │  ││       │
└──────────────────┘  ││       │
                      ││       │
         ┌────────────┘│       │
         ▼             │       │
┌──────────────────┐   │       │
│  tool_results    │   │       │
│   (existing)     │   │       │
│──────────────────│   │       │
│ tool_use_id [PK] │   │       │
│ tool_name        │   │       │
│ input            │   │       │
│ output           │   │       │
└──────────────────┘   │       │
                       │       │
         ┌─────────────┘       │
         ▼                     │
┌───────────────────┐          │
│ conversation_forks│          │
│      (new)        │          │
│───────────────────│          │
│ parent_uuid [PK]  │──────────┘
│ child_uuid [PK]   │──────────┐
│ fork_point_commit │          │
│ created_at        │          │
└───────────────────┘          │
                               │
         ┌─────────────────────┘
         ▼
      (back to sessions)
```

### 5.4 Database Migration Strategy

```python
# Migration: add_git_tracking.py

def upgrade(database):
    """Add git tracking tables."""

    # Create git_checkpoints table
    database.execute("""
        CREATE TABLE IF NOT EXISTS git_checkpoints (
            -- ... schema from 5.1 ...
        )
    """)

    # Create git_commits table
    database.execute("""
        CREATE TABLE IF NOT EXISTS git_commits (
            -- ... schema from 5.2 ...
        )
    """)

    # Create indexes
    database.execute("CREATE INDEX ...")

    database.commit()

def downgrade(database):
    """Rollback git tracking tables."""
    database.execute("DROP TABLE IF EXISTS git_commits")
    database.execute("DROP TABLE IF EXISTS git_checkpoints")
    database.commit()
```

**Migration Safety:** Non-destructive to existing data, only adds new tables.

## 6. API Design

### 6.1 Checkpoint Endpoints

**Create Checkpoint**
```
POST /api/sessions/{session_id}/checkpoint

Request Body: (empty)

Response: 200 OK
{
    "success": true,
    "checkpoint": {
        "session_uuid": "abc123...",
        "checkpoint_commit": "def456...",
        "checkpoint_reflog": "HEAD@{0}",
        "checkpoint_branch": "main",
        "created_at": "2025-11-11T10:30:00Z",
        "recovery_tag": "checkpoint-abc12345"
    }
}

Error: 400 Bad Request
{
    "success": false,
    "error": "Not a git repository"
}

Error: 409 Conflict
{
    "success": false,
    "error": "Checkpoint already exists for session"
}
```

**Get Checkpoint**
```
GET /api/sessions/{session_id}/checkpoint

Response: 200 OK
{
    "checkpoint": {
        "session_uuid": "abc123...",
        "checkpoint_commit": "def456...",
        "status": "active",
        "created_at": "2025-11-11T10:30:00Z",
        "commits_since": 5
    }
}

Response: 404 Not Found
{
    "error": "No checkpoint found for session"
}
```

### 6.2 Commit Endpoints

**List Session Commits**
```
GET /api/sessions/{session_id}/commits
    ?agent_id=optional
    &limit=50
    &offset=0

Response: 200 OK
{
    "commits": [
        {
            "commit_hash": "abc123...",
            "short_hash": "abc123",
            "session_uuid": "def456...",
            "agent_id": "agent-789...",
            "message": "Claude [Edit]: Update file.py",
            "timestamp": "2025-11-11T10:35:00Z",
            "tool_name": "Edit",
            "tool_description": "Edit file.py",
            "in_reflog": true,
            "files_changed": 1,
            "insertions": 5,
            "deletions": 2
        },
        ...
    ],
    "total": 15,
    "has_more": false
}
```

**Get Commit Diff**
```
GET /api/commits/{commit_hash}/diff

Response: 200 OK
{
    "commit_hash": "abc123...",
    "diff": "diff --git a/file.py b/file.py\n...",
    "files": [
        {
            "path": "file.py",
            "status": "modified",
            "additions": 5,
            "deletions": 2
        }
    ]
}
```

### 6.3 Rollback Endpoints

**Rollback Session**
```
POST /api/sessions/{session_id}/rollback

Request Body:
{
    "create_recovery_branch": true,
    "recovery_branch_name": "recovery/my-session"  // optional
}

Response: 200 OK
{
    "success": true,
    "checkpoint": "def456...",
    "commits_rolled_back": 5,
    "recovery_branch": "recovery/session-abc12345",
    "commits": ["abc123...", "def456...", ...],
    "reflog_entry": "HEAD@{10}"
}

Error: 400 Bad Request
{
    "success": false,
    "error": "Uncommitted changes present. Stash or commit first."
}
```

**Get Session Diff**
```
GET /api/sessions/{session_id}/diff

Response: 200 OK
{
    "checkpoint_commit": "def456...",
    "current_commit": "abc123...",
    "diff": "diff --git ...",
    "stats": {
        "files_changed": 10,
        "insertions": 150,
        "deletions": 45
    }
}
```

### 6.4 Recovery Endpoints

**Recover Commit**
```
POST /api/commits/{commit_hash}/recover

Request Body:
{
    "strategy": "cherry-pick"  // or "merge"
}

Response: 200 OK
{
    "success": true,
    "commit_hash": "abc123...",
    "new_commit": "xyz789..."
}

Error: 409 Conflict
{
    "success": false,
    "error": "Cherry-pick conflict",
    "conflicts": [
        {
            "file": "file.py",
            "ours": "...",
            "theirs": "...",
            "conflict_markers": "..."
        }
    ],
    "resolution_options": [
        "abort",
        "manual_resolution",
        "use_ours",
        "use_theirs"
    ]
}
```

**Recover Session**
```
POST /api/sessions/{session_id}/recover

Request Body:
{
    "commits": ["abc123...", "def456..."],  // optional, all if omitted
    "strategy": "sequential"  // or "squash"
}

Response: 200 OK
{
    "success": true,
    "commits_recovered": 5,
    "new_commits": ["xyz789...", ...],
    "conflicts_encountered": 0
}
```

### 6.5 Reflog Endpoints

**Get Reflog**
```
GET /api/reflog
    ?session_id=optional
    &limit=100

Response: 200 OK
{
    "entries": [
        {
            "ref": "HEAD@{0}",
            "commit": "abc123...",
            "action": "commit",
            "message": "Claude [Edit]: ...",
            "timestamp": "2025-11-11T10:35:00Z",
            "session_uuid": "def456...",  // if known
            "in_database": true  // tracked in our DB?
        },
        ...
    ],
    "stats": {
        "total_entries": 250,
        "oldest_entry": "2025-05-11T10:00:00Z",
        "estimated_expiration": "2025-05-11T10:00:00Z"
    }
}
```

**Get Reflog Stats**
```
GET /api/reflog/stats

Response: 200 OK
{
    "retention_days": 180,
    "total_entries": 250,
    "sessions_in_reflog": 15,
    "recoverable_commits": 75,
    "oldest_entry": "2025-05-11T10:00:00Z",
    "estimated_next_gc": "2025-11-15T00:00:00Z"
}
```

### 6.6 Checkpoint Selector Endpoints

**Get Checkpoints with Context**
```
GET /api/sessions/{session_id}/checkpoints
    ?limit=50

Response: 200 OK
{
    "checkpoints": [
        {
            "checkpoint_id": "ckpt-abc123",
            "checkpoint_commit": "git789def",
            "message_uuid": "msg-xyz456",
            "message_timestamp": "2025-11-11T10:30:00Z",
            "message_preview": "Let's try a different approach...",
            "created_at": "2025-11-11T10:30:05Z",
            "checkpoint_type": "fork_point"
        },
        ...
    ],
    "total": 15,
    "has_more": false
}
```

**Get Checkpoint Messages (Last 30)**
```
GET /api/checkpoints/{checkpoint_id}/messages
    ?before=30
    &after=0

Response: 200 OK
{
    "checkpoint": {
        "checkpoint_id": "ckpt-abc123",
        "checkpoint_commit": "git789def",
        "message_uuid": "msg-xyz456",
        "created_at": "2025-11-11T10:30:05Z"
    },
    "messages": [
        {
            "message_uuid": "msg-xyz400",
            "content": "Can you help me refactor this?",
            "role": "user",
            "timestamp": "2025-11-11T10:25:00Z",
            "is_checkpoint": false
        },
        {
            "message_uuid": "msg-xyz456",
            "content": "Let's try a different approach...",
            "role": "assistant",
            "timestamp": "2025-11-11T10:30:00Z",
            "is_checkpoint": true
        },
        ...
    ],
    "total_messages": 30
}
```

**Preview Checkpoint Diff**
```
GET /api/checkpoints/{checkpoint_id}/preview

Response: 200 OK
{
    "checkpoint_commit": "git789def",
    "current_commit": "gitabc123",
    "commits_between": 5,
    "diff": "diff --git a/file.py ...",
    "stats": {
        "files_changed": 3,
        "insertions": 45,
        "deletions": 12
    },
    "files": [
        {
            "path": "file.py",
            "status": "modified",
            "insertions": 30,
            "deletions": 8
        }
    ]
}
```

## 7. UI/UX Design

### 7.1 UI Components

**Session Detail Page Enhancement**

```
┌───────────────────────────────────────────────────────────┐
│ Session: abc123... (main branch)                      [×] │
├───────────────────────────────────────────────────────────┤
│                                                           │
│ ┌─────────────────────────────────────────────────────┐  │
│ │  Session Status                                     │  │
│ │  ━━━━━━━━━━━━━                                      │  │
│ │  ✓ Checkpoint created: 10:30 AM                    │  │
│ │  📝 5 commits made                                  │  │
│ │  📊 10 files changed (+150 -45 lines)             │  │
│ │                                                     │  │
│ │  [View Commits]  [View Diff]  [🔴 Rollback]       │  │
│ │  [Select Checkpoint]                                │  │
│ └─────────────────────────────────────────────────────┘  │
│                                                           │
│ ┌─────────────────────────────────────────────────────┐  │
│ │  Commit Timeline                            Filter ▼│  │
│ │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━│  │
│ │                                                     │  │
│ │  ● abc123  10:35 AM  Claude [Edit]                │  │
│ │    Edit config.py - Update API endpoint            │  │
│ │    [View Diff] [Recover This]                      │  │
│ │                                                     │  │
│ │  ● def456  10:40 AM  Agent 789 [Write]            │  │
│ │    Create test_api.py                              │  │
│ │    [View Diff] [Recover This]                      │  │
│ │                                                     │  │
│ │  ● ghi789  10:45 AM  Claude [Bash]                │  │
│ │    Run: pytest tests/                              │  │
│ │    [View Diff] [Recover This]                      │  │
│ │                                                     │  │
│ │  [Load More Commits...]                            │  │
│ └─────────────────────────────────────────────────────┘  │
│                                                           │
│ [Existing session details continue below...]             │
└───────────────────────────────────────────────────────────┘
```

**Checkpoint Selector UI (Non-Destructive by Default)**

```
┌───────────────────────────────────────────────────────────┐
│ Select Checkpoint to Restore                          [×] │
├───────────────────────────────────────────────────────────┤
│                                                           │
│ Browse checkpoints: [←] Checkpoint 3 of 8 [→]           │
│                                                           │
│ ┌─────────────────────────────────────────────────────┐  │
│ │  Fork Point • 10:30 AM • Nov 11, 2025              │  │
│ │  Commit: git789def                                  │  │
│ │                                                     │  │
│ │  Last 30 messages:                                 │  │
│ │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━│  │
│ │                                                     │  │
│ │  User: Can you refactor the API layer?            │  │
│ │  10:20 AM                                          │  │
│ │                                                     │  │
│ │  Assistant: I'll refactor it using...             │  │
│ │  10:22 AM                                          │  │
│ │                                                     │  │
│ │  User: Actually, let's try a different approach   │  │
│ │  10:25 AM                                          │  │
│ │                                                     │  │
│ │  Assistant: Let's try this instead...             │  │
│ │  10:30 AM ← CHECKPOINT                             │  │
│ │                                                     │  │
│ │  [Show all 30 messages...]                         │  │
│ └─────────────────────────────────────────────────────┘  │
│                                                           │
│ Three Restore Actions (reversible via reflog):           │
│                                                           │
│ 1. [Preview Changes]                                     │
│    View diff without making any changes                  │
│                                                           │
│ 2. [Rollback to Checkpoint] (non-destructive)            │
│    Reset to this point. Changes go to reflog (180 days) │
│                                                           │
│ 3. [View Messages Only]                                  │
│    Read conversation context without rollback            │
│                                                           │
│ [Close]                                                   │
└───────────────────────────────────────────────────────────┘
```

**Rollback Confirmation Modal**

```
┌─────────────────────────────────────────────────────────┐
│ ⚠️  Rollback Session?                               [×]│
├─────────────────────────────────────────────────────────┤
│                                                         │
│ This will rollback 5 commits made during this session: │
│                                                         │
│ ┌─────────────────────────────────────────────────────┐│
│ │ Commits to Rollback:                               ││
│ │                                                     ││
│ │ ✓ abc123  Edit config.py                          ││
│ │ ✓ def456  Create test_api.py                      ││
│ │ ✓ ghi789  Run: pytest tests/                      ││
│ │ ✓ jkl012  Fix test failures                       ││
│ │ ✓ mno345  Update documentation                    ││
│ │                                                     ││
│ │ Changes Summary:                                   ││
│ │ 10 files changed: +150 additions, -45 deletions   ││
│ └─────────────────────────────────────────────────────┘│
│                                                         │
│ ┌─────────────────────────────────────────────────────┐│
│ │ [Preview Diff ▼]                                   ││
│ │                                                     ││
│ │ diff --git a/config.py b/config.py                ││
│ │ @@ -10,7 +10,7 @@                                  ││
│ │ - API_URL = "http://old-api.com"                  ││
│ │ + API_URL = "http://new-api.com"                  ││
│ │ ...                                                ││
│ └─────────────────────────────────────────────────────┘│
│                                                         │
│ Options:                                                │
│ ☑️ Create recovery branch (recommended)                │
│   └─ Branch: recovery/session-abc12345                │
│      Permanent backup on remote for later recovery     │
│                                                         │
│ ☐ Show advanced options                               │
│                                                         │
│ ┌─────────────────────────────────────────────────────┐│
│ │ ⚠️  Warning: After rollback, commits will be in    ││
│ │    reflog for 180 days. Use recovery branch for    ││
│ │    permanent backup.                                ││
│ └─────────────────────────────────────────────────────┘│
│                                                         │
│             [Cancel]  [🔴 Confirm Rollback]            │
└─────────────────────────────────────────────────────────┘
```

**Recovery Interface**

```
┌─────────────────────────────────────────────────────────┐
│ Recover from Reflog                                 [×] │
├─────────────────────────────────────────────────────────┤
│                                                         │
│ Session: abc123... (rolled back 2 days ago)            │
│                                                         │
│ Select commits to recover:                             │
│                                                         │
│ ┌─────────────────────────────────────────────────────┐│
│ │ ☑️ abc123  Edit config.py               In Reflog ││
│ │    Edit config.py - Update API endpoint            ││
│ │    [Preview Diff]                                   ││
│ │                                                     ││
│ │ ☑️ def456  Create test_api.py           In Reflog ││
│ │    Create test_api.py                              ││
│ │    [Preview Diff]                                   ││
│ │                                                     ││
│ │ ☐ ghi789  Run: pytest tests/           In Reflog ││
│ │    Run: pytest tests/                              ││
│ │    [Preview Diff]                                   ││
│ │                                                     ││
│ │ ☑️ jkl012  Fix test failures            In Reflog ││
│ │    Fix test failures                               ││
│ │    [Preview Diff]                                   ││
│ │                                                     ││
│ │ ❌ mno345  Update documentation       Expired     ││
│ │    (Reflog entry expired - not recoverable)        ││
│ └─────────────────────────────────────────────────────┘│
│                                                         │
│ Recovery Options:                                       │
│ ○ Sequential (maintain order)                          │
│ ● Cherry-pick selected (may have conflicts)            │
│ ○ Squash into single commit                            │
│                                                         │
│             [Cancel]  [Recover Selected (3)]           │
└─────────────────────────────────────────────────────────┘
```

### 7.2 User Flows

**Flow 1: Create Checkpoint and Rollback**

```
1. User starts Claude session
   ↓
2. Auto-prompt: "Create checkpoint for rollback?"
   [Yes] [Not Now] [Never for this project]
   ↓
3. Checkpoint created (indicator shown)
   💾 Checkpoint: 10:30 AM
   ↓
4. Claude makes changes (commits shown in real-time)
   Commit 1: Edit config.py
   Commit 2: Create test.py
   ...
   ↓
5. Session ends / User reviews
   ↓
6. User clicks "Rollback Session"
   ↓
7. Confirmation modal shows:
   - List of commits
   - Diff preview
   - Recovery branch option
   ↓
8. User confirms
   ↓
9. Rollback executes
   ✓ Session rolled back
   💾 Recovery branch created: recovery/session-abc
   ↓
10. Success message with recovery info
```

**Flow 2: Selective Recovery**

```
1. User views rolled-back session
   ↓
2. Clicks "Recover Commits"
   ↓
3. Recovery UI shows all commits with status:
   - In Reflog ✓
   - Expired ❌
   ↓
4. User selects specific commits (checkboxes)
   ☑️ Commit 1
   ☐ Commit 2
   ☑️ Commit 3
   ↓
5. User clicks "Recover Selected"
   ↓
6. System attempts cherry-pick
   ↓
7. If conflicts:
   → Show conflict resolution UI
   → Options: abort, manual resolve, auto-strategies
   ↓
8. If success:
   → Show success message
   → New commits created
   → Update session timeline
```

**Flow 3: Browse Reflog**

```
1. User clicks "View Reflog" (global nav)
   ↓
2. Reflog browser shows:
   - All reflog entries
   - Sessions they belong to
   - Recovery status
   - Expiration estimates
   ↓
3. User can:
   - Filter by session
   - Search commits
   - View diffs
   - Recover commits
   ↓
4. Stats panel shows:
   - Total entries
   - Oldest entry
   - Estimated expiration
   - Storage usage
```

### 7.3 Visual Indicators

**Session Status Badges**

```
Active Session:     [🟢 Active • 3 commits • Checkpoint at 10:30 AM]
Kept Session:       [🔵 Kept • 5 commits merged to main]
Rolled Back:        [🔴 Rolled Back • Recovery available for 175 days]
Partially Recovered: [🟡 Partial • 2 of 5 commits recovered]
```

**Commit Status Icons**

```
✓ In reflog (recoverable)
⏰ Expiring soon (<30 days)
❌ Expired (not recoverable)
🔄 Recovered
🌿 In recovery branch
```

**Reflog Health Indicator**

```
Good:    [🟢 Reflog Health: Good • 180 days retention]
Warning: [🟡 Reflog Health: Warning • 30 days retention]
Error:   [🔴 Reflog Health: Critical • 7 days retention]
```

## 8. Design Decisions & Rationale

### 8.1 Auto-Commit on Every Tool Use

**Decision:** Automatically create git commit after each Edit/Write/Bash operation.

**Addresses Requirements:**
- [01-problem-statement.md] "Reliable Rollback - Must handle Edit, Write, AND Bash operations"
- [01-problem-statement.md] "Agent Granularity - Track which changes came from which agent"

**Informed By:**
- [02-research-findings.md] Finding 7: Aider AI follows "commit frequently, git is your safety net"
- [03-options-analysis.md]: Reflog-based approach scored 10/10 on "Reliable Rollback"

**Critical Concerns Addressed:**
- [99-critical-analysis.md] Question 3: "Too many commits?" - Mitigated by quality commit messages and squash option
- [99-critical-analysis.md] Question 8: "Performance at scale?" - Design includes async commits and optimization strategies

**Alternative Considered:** Manual commit with UI button
**Rejected Because:** Requires user discipline, easy to forget, breaks automatic workflow

**Implementation Notes:**
```python
# Async to avoid blocking
async def auto_commit_background(changes):
    # Only commit if actually changed
    if not has_changes():
        return

    # Optimize: only stage changed files
    changed_files = get_changed_files()
    git.add(changed_files)  # Not git add -A

    # Commit with rich metadata
    git.commit(message=generate_message())
```

### 8.2 180-Day Reflog Retention

**Decision:** Configure git reflog retention to 180 days (6 months).

**Addresses Requirements:**
- [01-problem-statement.md] "Recovery window must be reasonable (weeks/months, not hours/days)"

**Informed By:**
- [02-research-findings.md] Finding 3: "Default retention: 90 days for reachable, 30 days for unreachable"
- [04-solution-selection.md] Limitation 1: "Time-Limited Recovery"

**Critical Concerns Addressed:**
- [99-critical-analysis.md] Question 1: "Is 180 days sufficient?" - Mitigated by recovery branch option for permanent backup
- [99-critical-analysis.md] Question 2: "What if GC runs unexpectedly?" - Extended retention provides buffer

**Alternative Considered:** Indefinite retention (disable GC)
**Rejected Because:** Causes repository bloat, git performance degradation, not recommended by git

**Mitigation Strategy:**
```python
# Configuration on initialization
git config gc.reflogExpire "180 days"
git config gc.reflogExpireUnreachable "180 days"

# Recovery branch option for permanent backup
def rollback_with_recovery(session_id):
    # Push to remote BEFORE rollback
    git push origin HEAD:refs/heads/recovery/session-{id}
    # Now permanent (survives GC)
    git reset --hard checkpoint
```

### 8.3 Recovery Branch as Optional Safety Net

**Decision:** Offer optional recovery branch creation before rollback, pushed to remote for permanent backup.

**Addresses Requirements:**
- [01-problem-statement.md] "Recovery window must be reasonable" - Unlimited if using recovery branch

**Informed By:**
- [04-solution-selection.md] "Optional Recovery Branches" - Supporting strategy #4

**Critical Concerns Addressed:**
- [99-critical-analysis.md] Question 1: "180 days may not be enough" - Recovery branch provides unlimited retention
- [99-critical-analysis.md] Conclusion: "Do NOT skip Phase 1.5 - Recovery branches are the safety net"

**Alternative Considered:** Mandatory recovery branches
**Rejected Because:** Clutters remote with potentially unnecessary branches, user should decide

**UI Design:**
```
☑️ Create recovery branch (recommended)
   └─ Branch: recovery/session-abc12345
      Permanent backup on remote for later recovery

Checkbox checked by default
Clear warning if unchecked:
  "Without recovery branch, commits expire in 180 days"
```

### 8.4 Commit Message Format

**Decision:** Structured commit messages with session metadata.

**Format:**
```
Claude [ToolName]: Brief description

Session: <session_uuid>
Agent: <agent_id>
Tool: <tool_name>
Tool use ID: <tool_use_id>

🤖 Generated with Claude Code
```

**Addresses Requirements:**
- [01-problem-statement.md] "Agent Granularity - Track which changes came from which agent"
- [01-problem-statement.md] "Ease of Use - Clear status indicators"

**Informed By:**
- [02-research-findings.md] Finding 7: "Descriptive messages" - Common pattern across AI tools

**Alternative Considered:** Minimal messages ("Auto-commit")
**Rejected Because:** Makes recovery difficult, can't distinguish commits, loses context

**Benefits:**
- Searchable (git log --grep="Agent abc")
- Identifies tool used
- Links to JSONL for full context
- Clear attribution

### 8.5 Database Tracking Parallel to Git

**Decision:** Store commit metadata in SQLite database alongside git operations.

**Rationale:**
1. **Fast queries** - Don't need to parse git log every time
2. **Relationships** - Link to sessions, agents, tool results
3. **UI data** - Rich metadata for display
4. **Status tracking** - in_reflog flag, recovered status
5. **Cross-machine** - Database syncs, reflog doesn't

**Trade-off:** Potential inconsistency between git and database
**Mitigation:**
```python
# Atomic operations
def auto_commit(changes):
    try:
        commit_hash = git.commit(changes)
        db.store_commit(commit_hash, metadata)
        db.commit()
    except:
        db.rollback()
        git.reset_soft('HEAD^')  # Undo commit
        raise
```

### 8.6 Cherry-Pick for Recovery

**Decision:** Use git cherry-pick for selective commit recovery.

**Addresses Requirements:**
- [01-problem-statement.md] "Partial recovery should be possible (cherry-pick specific changes)"

**Informed By:**
- [04-solution-selection.md] "Enables Partial Recovery" - Key flexibility advantage

**Critical Concerns Addressed:**
- [99-critical-analysis.md] Question 4: "Merge conflicts during recovery?" - Design includes conflict detection and resolution UI

**Alternative Considered:**
- Merge strategy
- Reapply patches
- Manual copy-paste

**Rejected Because:**
- Merge: Creates merge commits (clutters history)
- Patches: Complex to generate and apply
- Manual: Defeats purpose of automation

**Conflict Handling Design:**
```python
def cherry_pick_with_conflict_handling(commit_hash):
    try:
        git.cherry_pick(commit_hash)
        return {'success': True}
    except CherryPickConflict as e:
        return {
            'success': False,
            'conflicts': parse_conflicts(e),
            'resolution_options': [
                'abort',
                'manual_resolution',
                'use_ours',
                'use_theirs',
                'smart_merge'  # Context-aware strategies
            ]
        }
```

## 9. Risk Mitigation by Design

This section shows how the design specifically addresses concerns raised in [99-critical-analysis.md].

### 9.1 Time-Limited Recovery (Question 1)

**Risk:** 180 days may not be sufficient for all scenarios.

**Design Mitigations:**

1. **Recovery Branches** (Primary Mitigation)
   ```python
   # Offered by default in UI
   def rollback_session(session_id, create_recovery=True):
       if create_recovery:
           # Push to remote = permanent backup
           git.push(f'origin HEAD:recovery/session-{session_id}')
       git.reset('--hard', checkpoint)
   ```

2. **Configurable Retention**
   ```python
   # Admin can extend beyond 180 days
   git config gc.reflogExpire "365 days"  # 1 year
   ```

3. **Expiration Warnings**
   ```python
   # UI shows expiration countdown
   if days_until_expiration < 30:
       show_warning("⏰ Reflog expires in {days} days")
       suggest_recovery_branch()
   ```

4. **Git Tags for Critical Checkpoints**
   ```python
   # Important sessions get permanent tags
   git.tag(f'checkpoint-{session_id}', checkpoint)
   # Tags prevent GC
   ```

**Severity Reduced:** MEDIUM → LOW (with recovery branches)

### 9.2 Unexpected Garbage Collection (Question 2)

**Risk:** Git GC can run unexpectedly and prune reflog entries.

**Design Mitigations:**

1. **GC Configuration on Initialization**
   ```python
   class GitManager:
       def __init__(self):
           # Set retention immediately
           git.config('gc.reflogExpire', '180 days')
           git.config('gc.reflogExpireUnreachable', '180 days')
           # Disable auto-GC during active sessions
           git.config('gc.auto', '0')
   ```

2. **GC Monitoring**
   ```python
   # Background task checks reflog health
   def monitor_reflog_health():
       stats = get_reflog_stats()
       if stats['oldest_entry_days'] < 180:
           alert_admin("Reflog retention compromised")
   ```

3. **Pre-GC Warnings**
   ```python
   # Git hook: pre-gc
   # Runs before any GC operation
   def pre_gc_hook():
       check_for_unprotected_sessions()
       if found:
           warn_user("GC will delete unprotected sessions")
           offer_recovery_branches()
   ```

4. **Recovery Branch Recommendation**
   ```
   UI: "Important session? Create recovery branch for permanent backup"
   ```

**Severity Reduced:** HIGH → MEDIUM (with monitoring and warnings)

### 9.3 Too Many Commits (Question 3)

**Risk:** Auto-commit on every tool use creates excessive commits.

**Design Mitigations:**

1. **Quality Commit Messages**
   ```python
   # Rich metadata makes commits useful
   message = f"""Claude [Edit]: Update API configuration

   Session: abc123
   Agent: main
   Tool: Edit
   File: config.py
   Description: Changed API endpoint from dev to prod
   """
   ```

2. **Squash Option Before Merge**
   ```python
   # UI option: "Keep and Squash"
   def keep_session_squashed(session_id):
       commits = get_session_commits(session_id)
       git.reset('--soft', checkpoint)
       git.commit('-m', generate_squashed_message(commits))
   ```

3. **Skip Commits for No-Change Operations**
   ```python
   def auto_commit():
       if not git.status('--porcelain'):
           return None  # No commit needed
   ```

4. **Commit Batching Option**
   ```python
   # User preference: batch commits every N operations
   if config.batch_commits:
       if operation_count % config.batch_size == 0:
           commit_batched_changes()
   ```

**Severity Reduced:** MEDIUM → LOW (commit quality + squash option)

### 9.4 Merge Conflicts During Recovery (Question 4)

**Risk:** Cherry-picking rolled-back commits may cause conflicts.

**Design Mitigations:**

1. **Conflict Detection UI**
   ```python
   def preview_recovery(commit_hash):
       # Dry-run cherry-pick
       result = git.apply('--check', commit_hash)
       if result.conflicts:
           return {
               'will_conflict': True,
               'conflicting_files': result.files,
               'preview': result.diff
           }
   ```

2. **Conflict Resolution Strategies**
   ```python
   resolution_options = [
       'abort',              # Cancel recovery
       'manual',             # Show conflict markers, user resolves
       'use_ours',          # Keep current version
       'use_theirs',        # Use recovered version
       'smart_merge',       # Context-aware auto-merge
       'skip_file'          # Recover other files, skip conflicting
   ]
   ```

3. **Interactive Resolution UI**
   ```
   Conflict in config.py:

   Current (ours):          Recovered (theirs):
   API_URL = "prod.com"    API_URL = "dev.com"

   [Use Current] [Use Recovered] [Edit Manually]
   ```

4. **Recovery with Context**
   ```python
   # Show what changed since rollback
   def recovery_context(commit_hash):
       return {
           'original_state': get_commit_content(commit_hash),
           'current_state': get_file_content('HEAD'),
           'diff': compute_three_way_diff()
       }
   ```

**Severity Reduced:** HIGH → MEDIUM (with comprehensive conflict handling)

### 9.5 Reflog Complexity Across Git Operations (Question 5)

**Risk:** Rebases, branch switches, and other git operations complicate reflog tracking.

**Design Mitigations:**

1. **Database as Source of Truth**
   ```python
   # Don't rely on parsing reflog
   # Database stores:
   # - commit_hash (immutable)
   # - session_uuid
   # - in_reflog (boolean flag)

   # Even if rebase changes hash, we track old hash in DB
   ```

2. **Rebase Detection**
   ```python
   def detect_rebased_commits(session_id):
       db_commits = get_session_commits(session_id)
       for commit in db_commits:
           if not git.cat_file('commit', commit.hash):
               # Commit doesn't exist anymore
               commit.in_reflog = False
               commit.note = "Changed by rebase"
   ```

3. **Branch Switch Awareness**
   ```python
   # Record branch in checkpoint
   checkpoint.branch = git.current_branch()

   # Warn if switched
   if git.current_branch() != checkpoint.branch:
       warn("On different branch than checkpoint")
   ```

4. **Simplified UI Messaging**
   ```
   Instead of:
   "Commit abc123 at HEAD@{15} on branch feature-x after rebase"

   Show:
   "Commit from session abc (recoverable for 175 days)"
   ```

**Severity Reduced:** MEDIUM-HIGH → MEDIUM (database tracking + detection)

### 9.6 Non-Git Repositories (Question 6)

**Risk:** Feature unavailable if project doesn't use git.

**Design Mitigations:**

1. **Auto-Initialize Option**
   ```python
   if not is_git_repo():
       prompt_user("Initialize git for rollback?")
       if user_agrees:
           git.init()
           git.add('.')
           git.commit('-m', 'Initial commit for rollback tracking')
   ```

2. **Fallback to File Snapshots**
   ```python
   if not is_git_repo() and user_declines_init:
       # Fall back to claude-code-rewind strategy
       use_file_snapshot_rollback()
   ```

3. **Clear Warnings**
   ```
   ⚠️ Git Unavailable

   Rollback features require git. Options:

   1. Initialize git in this project [Recommended]
   2. Use file snapshots (limited capability)
   3. Disable rollback features
   ```

4. **Graceful Degradation**
   ```python
   class RollbackManager:
       def __init__(self):
           self.mode = 'git' if has_git() else 'snapshots'

       def rollback(self):
           if self.mode == 'git':
               return git_rollback()
           else:
               return snapshot_rollback()
   ```

**Severity Reduced:** MEDIUM → LOW (auto-init + fallback)

### 9.7 Accidental Reflog Deletion (Question 7)

**Risk:** Users can accidentally delete reflog.

**Design Mitigations:**

1. **Reflog Backup**
   ```python
   # Periodic backup of .git/logs
   def backup_reflog():
       shutil.copy('.git/logs/HEAD',
                   f'.claude-backups/reflog-{timestamp}')
   ```

2. **Git Hook Protection**
   ```bash
   # .git/hooks/pre-reflog-expire
   echo "WARNING: About to expire reflog entries"
   echo "Claude sessions may be affected"
   read -p "Continue? (y/N) " confirm
   ```

3. **Recovery from Backup**
   ```python
   if reflog_missing():
       show_warning("Reflog missing! Restore from backup?")
       if user_confirms:
           restore_reflog_backup()
   ```

4. **Configuration Validation**
   ```python
   # Check gc.reflogExpire setting
   def validate_git_config():
       expire = git.config('gc.reflogExpire')
       if parse_days(expire) < 30:
           alert("⚠️ Reflog retention too short!")
           offer_fix()
   ```

**Severity Reduced:** MEDIUM → LOW (backups + protection)

### 9.8 Performance at Scale (Question 8)

**Risk:** Large repositories make git operations slow.

**Design Mitigations:**

1. **Async Commits**
   ```python
   # Don't block UI on commit
   async def auto_commit():
       await git.add_async(changed_files)
       await git.commit_async(message)
       update_ui_when_complete()
   ```

2. **Selective Staging**
   ```python
   # Don't use git add -A
   def auto_commit(tool_result):
       changed = extract_changed_files(tool_result)
       git.add(changed)  # Only changed files
   ```

3. **Commit Batching**
   ```python
   # Option: batch commits every 5 operations
   buffer = []
   def auto_commit(change):
       buffer.append(change)
       if len(buffer) >= 5:
           commit_batch(buffer)
           buffer.clear()
   ```

4. **Performance Monitoring**
   ```python
   @timed
   def auto_commit():
       start = time()
       # ... commit ...
       duration = time() - start
       if duration > 1.0:  # >1 second
           log_warning(f"Slow commit: {duration}s")
   ```

5. **Large Repo Detection**
   ```python
   if file_count > 100_000:
       warn("Large repo detected")
       suggest_alternative_strategies()
   ```

**Severity Reduced:** HIGH → MEDIUM (async + optimizations)

### 9.9 Reflog Not Designed for This (Question 9)

**Risk:** Using reflog outside its intended purpose.

**Design Mitigations:**

1. **Recovery Branch Safety Net**
   ```python
   # Primary backup is recovery branches (proper git feature)
   # Reflog is secondary convenience
   always_offer_recovery_branch()
   ```

2. **Git Version Compatibility**
   ```python
   MIN_GIT_VERSION = '2.25'

   def check_git_version():
       version = git.version()
       if version < MIN_GIT_VERSION:
           warn("Git version too old for reliable reflog")
   ```

3. **Testing Across Git Versions**
   ```python
   # CI tests against multiple git versions
   test_matrix = [
       'git:2.25',
       'git:2.30',
       'git:2.40',
       'git:latest'
   ]
   ```

4. **Documentation Transparency**
   ```
   User Docs:
   "This feature uses git reflog for convenience recovery.
   For critical sessions, always create recovery branches."
   ```

**Severity Acknowledged:** LOW-MEDIUM (transparent about trade-offs)

### 9.10 Security - Removed per User Request

**Note:** PII/sensitive data security concern excluded per user instructions.

## 10. Performance Design

### 10.1 Performance Requirements

| Operation | Target | Measurement |
|-----------|--------|-------------|
| Create checkpoint | <100ms | Time from API call to response |
| Auto-commit (small change) | <500ms | Tool execution to commit complete |
| Auto-commit (large change) | <2s | With 100+ files changed |
| Rollback session | <1s | Reset operation complete |
| List commits (paginated) | <200ms | API response time |
| Get diff | <500ms | For typical file sizes |
| Cherry-pick recovery | <1s | For single commit |

### 10.2 Optimization Strategies

**Database Queries:**
```python
# Index on frequently queried columns
CREATE INDEX idx_git_commits_session ON git_commits(session_uuid);
CREATE INDEX idx_git_commits_timestamp ON git_commits(timestamp);

# Use prepared statements
self.cursor.execute(
    "SELECT * FROM git_commits WHERE session_uuid = ?",
    (session_uuid,)
)

# Pagination for large result sets
SELECT * FROM git_commits
WHERE session_uuid = ?
ORDER BY timestamp DESC
LIMIT ? OFFSET ?
```

**Git Operations:**
```python
# Parallel file processing
from concurrent.futures import ThreadPoolExecutor

def stage_files_parallel(files):
    with ThreadPoolExecutor(max_workers=4) as executor:
        executor.map(git.add, batch_files(files, 100))

# Shallow git operations
git.log('--oneline', f'{checkpoint}..HEAD')  # Not full log

# Cache git config values
class GitManager:
    def __init__(self):
        self.config_cache = {
            'reflog_expire': git.config('gc.reflogExpire'),
            'user_name': git.config('user.name'),
        }
```

**UI Performance:**
```javascript
// Virtualized lists for large commit history
import { FixedSizeList } from 'react-window';

<FixedSizeList
  height={600}
  itemCount={commits.length}
  itemSize={80}
>
  {CommitRow}
</FixedSizeList>

// Lazy load diffs
const [diff, setDiff] = useState(null);
const loadDiff = useCallback(async () => {
  const result = await api.getCommitDiff(hash);
  setDiff(result);
}, [hash]);

// Debounce search
const debouncedSearch = useMemo(
  () => debounce(searchCommits, 300),
  []
);
```

**Caching Strategy:**
```python
from functools import lru_cache

class GitManager:
    @lru_cache(maxsize=100)
    def get_commit_info(self, commit_hash):
        """Cache commit metadata."""
        return git.show(commit_hash)

    @lru_cache(maxsize=50)
    def get_commit_diff(self, commit_hash):
        """Cache diffs."""
        return git.diff(f'{commit_hash}^..{commit_hash}')
```

### 10.3 Performance Monitoring

```python
import time
import logging

class PerformanceMonitor:
    def __init__(self):
        self.metrics = {}

    def track(self, operation_name):
        """Decorator for tracking operation performance."""
        def decorator(func):
            def wrapper(*args, **kwargs):
                start = time.time()
                result = func(*args, **kwargs)
                duration = time.time() - start

                # Log slow operations
                if duration > self.get_threshold(operation_name):
                    logging.warning(
                        f"Slow operation: {operation_name} took {duration:.2f}s"
                    )

                # Store metrics
                self.metrics[operation_name] = {
                    'duration': duration,
                    'timestamp': start
                }

                return result
            return wrapper
        return decorator

    def get_threshold(self, operation_name):
        """Operation-specific slow threshold."""
        thresholds = {
            'auto_commit': 2.0,
            'rollback': 1.0,
            'list_commits': 0.5,
        }
        return thresholds.get(operation_name, 1.0)

# Usage
monitor = PerformanceMonitor()

@monitor.track('auto_commit')
def auto_commit(changes):
    # ... implementation ...
```

## 11. Testing Strategy

### 11.1 Unit Tests

**Git Manager Tests:**
```python
class TestGitManager(unittest.TestCase):
    def setUp(self):
        self.temp_repo = create_temp_git_repo()
        self.git_manager = GitManager(self.temp_repo)

    def test_create_checkpoint(self):
        """Test checkpoint creation."""
        session_id = "test-session-123"
        result = self.git_manager.create_checkpoint(session_id)

        self.assertIn('checkpoint_commit', result)
        self.assertIn('checkpoint_reflog', result)

        # Verify database entry
        checkpoint = db.get_checkpoint(session_id)
        self.assertEqual(checkpoint['session_uuid'], session_id)

    def test_auto_commit(self):
        """Test auto-commit on file changes."""
        # Make changes
        write_file(self.temp_repo / 'test.py', 'print("hello")')

        # Auto-commit
        commit_hash = self.git_manager.auto_commit(
            session_uuid="test",
            tool_name="Write",
            description="Create test.py"
        )

        self.assertIsNotNone(commit_hash)
        self.assertEqual(len(commit_hash), 40)  # SHA-1 hash

        # Verify commit exists
        commit = git.show(commit_hash)
        self.assertIn("Create test.py", commit)

    def test_auto_commit_no_changes(self):
        """Test auto-commit when no changes present."""
        commit_hash = self.git_manager.auto_commit(
            session_uuid="test",
            tool_name="Bash",
            description="No-op command"
        )

        self.assertIsNone(commit_hash)  # Should not commit

    def test_rollback_session(self):
        """Test session rollback."""
        session_id = "test-session"

        # Create checkpoint
        checkpoint = self.git_manager.create_checkpoint(session_id)

        # Make commits
        for i in range(3):
            write_file(self.temp_repo / f'file{i}.py', f'content {i}')
            self.git_manager.auto_commit(
                session_uuid=session_id,
                tool_name="Write",
                description=f"Create file{i}"
            )

        # Rollback
        result = self.git_manager.rollback_session(session_id)

        self.assertTrue(result['success'])
        self.assertEqual(result['commits_rolled_back'], 3)

        # Verify HEAD is at checkpoint
        current_head = git.rev_parse('HEAD')
        self.assertEqual(current_head, checkpoint['checkpoint_commit'])

        # Verify files are gone
        for i in range(3):
            self.assertFalse((self.temp_repo / f'file{i}.py').exists())

    def test_cherry_pick_recovery(self):
        """Test recovering specific commit."""
        # Create and rollback session
        session_id = "test-session"
        self.git_manager.create_checkpoint(session_id)

        write_file(self.temp_repo / 'important.py', 'important code')
        commit_hash = self.git_manager.auto_commit(
            session_uuid=session_id,
            tool_name="Write",
            description="Important file"
        )

        self.git_manager.rollback_session(session_id)

        # Verify file is gone
        self.assertFalse((self.temp_repo / 'important.py').exists())

        # Recover
        result = self.git_manager.recover_commit(commit_hash)
        self.assertTrue(result['success'])

        # Verify file is back
        self.assertTrue((self.temp_repo / 'important.py').exists())
```

**Database Tests:**
```python
class TestGitDatabase(unittest.TestCase):
    def test_checkpoint_crud(self):
        """Test checkpoint create/read/update/delete."""
        # Create
        db.create_checkpoint(
            session_uuid="test",
            checkpoint_commit="abc123",
            checkpoint_reflog="HEAD@{0}",
            created_at=datetime.now(),
            status="active"
        )

        # Read
        checkpoint = db.get_checkpoint("test")
        self.assertEqual(checkpoint['status'], 'active')

        # Update
        db.update_checkpoint_status("test", "rolled_back")
        checkpoint = db.get_checkpoint("test")
        self.assertEqual(checkpoint['status'], 'rolled_back')

    def test_commit_tracking(self):
        """Test commit metadata storage."""
        commits = []
        for i in range(5):
            commit_hash = f"abc{i:03d}" + "0" * 37
            db.create_git_commit(
                commit_hash=commit_hash,
                session_uuid="test",
                agent_id=None if i < 3 else "agent-123",
                message=f"Commit {i}",
                timestamp=datetime.now(),
                tool_use_id=f"tool-{i}"
            )
            commits.append(commit_hash)

        # Query all session commits
        session_commits = db.get_session_commits("test")
        self.assertEqual(len(session_commits), 5)

        # Query agent commits
        agent_commits = db.get_agent_commits("agent-123")
        self.assertEqual(len(agent_commits), 2)
```

### 11.2 Integration Tests

**End-to-End Rollback Test:**
```python
class TestRollbackIntegration(IntegrationTestCase):
    def test_full_rollback_flow(self):
        """Test complete rollback workflow."""
        # 1. Start session
        session = self.create_test_session()

        # 2. Create checkpoint via API
        response = self.client.post(
            f'/api/sessions/{session.uuid}/checkpoint'
        )
        self.assertEqual(response.status_code, 200)

        # 3. Simulate Claude operations
        self.simulate_edit_operation(session.uuid, 'config.py')
        self.simulate_write_operation(session.uuid, 'new_file.py')
        self.simulate_bash_operation(session.uuid, 'pytest')

        # 4. Verify commits created
        commits = self.client.get(
            f'/api/sessions/{session.uuid}/commits'
        ).json()
        self.assertEqual(len(commits['commits']), 3)

        # 5. Rollback
        response = self.client.post(
            f'/api/sessions/{session.uuid}/rollback',
            json={'create_recovery_branch': True}
        )
        self.assertEqual(response.status_code, 200)

        result = response.json()
        self.assertTrue(result['success'])
        self.assertEqual(result['commits_rolled_back'], 3)
        self.assertIsNotNone(result['recovery_branch'])

        # 6. Verify file state
        self.assertFalse(Path('new_file.py').exists())

        # 7. Verify reflog
        reflog = git.reflog()
        commit_hashes = [c['commit_hash'] for c in commits['commits']]
        for commit_hash in commit_hashes:
            self.assertIn(commit_hash, reflog)
```

**API Integration Tests:**
```python
class TestRollbackAPI(APITestCase):
    def test_checkpoint_endpoints(self):
        """Test all checkpoint API endpoints."""
        # Create
        response = self.post('/api/sessions/test/checkpoint')
        self.assertEqual(response.status_code, 200)

        # Get
        response = self.get('/api/sessions/test/checkpoint')
        self.assertEqual(response.status_code, 200)
        self.assertIn('checkpoint_commit', response.json())

        # List commits
        response = self.get('/api/sessions/test/commits')
        self.assertEqual(response.status_code, 200)

        # Get diff
        response = self.get('/api/sessions/test/diff')
        self.assertEqual(response.status_code, 200)

    def test_recovery_endpoints(self):
        """Test recovery API endpoints."""
        # Setup: create and rollback session
        self.setup_rolled_back_session('test')

        # Get reflog
        response = self.get('/api/reflog?session_id=test')
        self.assertEqual(response.status_code, 200)

        commits = response.json()['entries']
        self.assertGreater(len(commits), 0)

        # Recover commit
        commit_hash = commits[0]['commit']
        response = self.post(f'/api/commits/{commit_hash}/recover')
        self.assertEqual(response.status_code, 200)
```

### 11.3 Performance Tests

```python
class TestRollbackPerformance(PerformanceTestCase):
    def test_large_repo_commit_speed(self):
        """Test auto-commit performance in large repo."""
        # Setup: repo with 10,000 files
        repo = self.create_large_repo(file_count=10_000)

        # Change 1 file
        write_file(repo / 'test.py', 'new content')

        # Measure commit time
        start = time.time()
        commit_hash = git_manager.auto_commit(
            session_uuid="test",
            tool_name="Edit",
            description="Edit test.py"
        )
        duration = time.time() - start

        # Should complete in <2 seconds
        self.assertLess(duration, 2.0)

    def test_rollback_many_commits(self):
        """Test rollback with many commits."""
        session_id = "test"
        git_manager.create_checkpoint(session_id)

        # Create 100 commits
        for i in range(100):
            write_file(f'file{i}.py', f'content {i}')
            git_manager.auto_commit(
                session_uuid=session_id,
                tool_name="Write",
                description=f"Create file{i}"
            )

        # Measure rollback time
        start = time.time()
        result = git_manager.rollback_session(session_id)
        duration = time.time() - start

        # Should complete in <1 second
        self.assertLess(duration, 1.0)
        self.assertTrue(result['success'])
        self.assertEqual(result['commits_rolled_back'], 100)
```

### 11.4 Error Handling Tests

```python
class TestRollbackErrors(ErrorTestCase):
    def test_rollback_without_checkpoint(self):
        """Test rollback when no checkpoint exists."""
        with self.assertRaises(ValueError) as ctx:
            git_manager.rollback_session("nonexistent")

        self.assertIn("No checkpoint found", str(ctx.exception))

    def test_cherry_pick_conflict(self):
        """Test cherry-pick conflict handling."""
        # Setup: create diverged state
        session_id = "test"
        git_manager.create_checkpoint(session_id)

        # Change file in session
        write_file('conflict.py', 'session version')
        commit_hash = git_manager.auto_commit(
            session_uuid=session_id,
            tool_name="Edit",
            description="Edit conflict.py"
        )

        # Rollback
        git_manager.rollback_session(session_id)

        # Change same file differently
        write_file('conflict.py', 'different version')
        git.add('conflict.py')
        git.commit('-m', 'Different change')

        # Try to recover - should conflict
        result = git_manager.recover_commit(commit_hash)

        self.assertFalse(result['success'])
        self.assertIn('conflict', result['error'].lower())
        self.assertIn('conflicts', result)

    def test_not_git_repo(self):
        """Test behavior when not a git repo."""
        temp_dir = create_temp_dir()  # Not git init

        with self.assertRaises(GitError):
            GitManager(temp_dir)
```

## 12. Deployment Design

### 12.1 Installation Requirements

```yaml
# requirements.txt additions
GitPython>=3.1.40  # Git interface library
```

```python
# Minimum git version check
MIN_GIT_VERSION = (2, 25, 0)

def check_requirements():
    """Verify system requirements."""
    # Check git installed
    if not shutil.which('git'):
        raise SystemError("Git not installed")

    # Check git version
    version_str = subprocess.run(
        ['git', '--version'],
        capture_output=True,
        text=True
    ).stdout

    version = parse_git_version(version_str)
    if version < MIN_GIT_VERSION:
        raise SystemError(
            f"Git {'.'.join(map(str, MIN_GIT_VERSION))} or higher required"
        )
```

### 12.2 Database Migration

```python
# Migration script: migrations/006_add_git_tracking.py

def upgrade(db):
    """Add git tracking tables."""
    print("Creating git_checkpoints table...")
    db.execute(CHECKPOINT_TABLE_SQL)

    print("Creating git_commits table...")
    db.execute(COMMITS_TABLE_SQL)

    print("Creating indexes...")
    db.execute(CHECKPOINT_INDEXES_SQL)
    db.execute(COMMITS_INDEXES_SQL)

    print("Git tracking tables created successfully")

def downgrade(db):
    """Remove git tracking tables."""
    print("Dropping git tracking tables...")
    db.execute("DROP TABLE IF EXISTS git_commits")
    db.execute("DROP TABLE IF EXISTS git_checkpoints")
    print("Git tracking tables removed")

# Run migration
def run_migrations():
    db = Database()
    current_version = db.get_schema_version()

    if current_version < 6:
        print("Upgrading database to version 6...")
        upgrade(db)
        db.set_schema_version(6)
        print("Database upgraded successfully")
```

### 12.3 Configuration

```python
# config.py

class RollbackConfig:
    """Configuration for rollback feature."""

    # Reflog retention
    REFLOG_EXPIRE_DAYS = 180
    REFLOG_EXPIRE_UNREACHABLE_DAYS = 180

    # Auto-commit behavior
    AUTO_COMMIT_ENABLED = True
    SKIP_EMPTY_COMMITS = True

    # Recovery branches
    RECOVERY_BRANCH_PREFIX = "recovery/"
    AUTO_CREATE_RECOVERY_BRANCH = False  # Prompt user

    # Performance
    ASYNC_COMMITS = True
    COMMIT_BATCH_SIZE = 1  # 1 = every operation

    # Monitoring
    SLOW_COMMIT_THRESHOLD_SECONDS = 2.0
    REFLOG_HEALTH_CHECK_INTERVAL_HOURS = 24

    @classmethod
    def from_env(cls):
        """Load from environment variables."""
        config = cls()
        config.REFLOG_EXPIRE_DAYS = int(
            os.getenv('ROLLBACK_REFLOG_EXPIRE_DAYS', 180)
        )
        # ... other env vars ...
        return config
```

### 12.4 Initialization

```python
# app.py startup

def initialize_rollback_feature():
    """Initialize rollback feature on app startup."""

    # 1. Check requirements
    try:
        check_requirements()
    except SystemError as e:
        logger.error(f"Rollback feature unavailable: {e}")
        return None

    # 2. Load configuration
    config = RollbackConfig.from_env()

    # 3. Run database migrations
    run_migrations()

    # 4. Initialize git manager
    try:
        git_manager = GitManager(
            project_root=Path.cwd(),
            database=db,
            config=config
        )
        logger.info("Rollback feature initialized successfully")
        return git_manager
    except GitError as e:
        logger.warning(f"Git initialization failed: {e}")
        logger.info("Rollback feature will be unavailable")
        return None

# App startup
app = Flask(__name__)
git_manager = initialize_rollback_feature()

if git_manager:
    app.config['ROLLBACK_ENABLED'] = True
else:
    app.config['ROLLBACK_ENABLED'] = False
```

### 12.5 Monitoring & Logging

```python
# monitoring.py

class RollbackMonitor:
    """Monitor rollback feature health."""

    def __init__(self, git_manager):
        self.git_manager = git_manager
        self.metrics = {}

    def check_reflog_health(self):
        """Check reflog configuration and status."""
        stats = self.git_manager.get_reflog_stats()

        warnings = []

        # Check retention setting
        if stats['retention_days'] < 90:
            warnings.append(
                f"Reflog retention low: {stats['retention_days']} days"
            )

        # Check oldest entry
        age_days = (datetime.now() - stats['oldest_entry']).days
        if age_days < stats['retention_days'] * 0.8:
            warnings.append(
                f"Reflog entries being pruned early: {age_days} days"
            )

        return {
            'healthy': len(warnings) == 0,
            'warnings': warnings,
            'stats': stats
        }

    def track_operation(self, operation, duration, success):
        """Track operation metrics."""
        key = f"{operation}_{'success' if success else 'failure'}"

        if key not in self.metrics:
            self.metrics[key] = {
                'count': 0,
                'total_duration': 0,
                'max_duration': 0
            }

        self.metrics[key]['count'] += 1
        self.metrics[key]['total_duration'] += duration
        self.metrics[key]['max_duration'] = max(
            self.metrics[key]['max_duration'],
            duration
        )

    def get_metrics_summary(self):
        """Get metrics summary for monitoring dashboard."""
        return {
            metric_name: {
                'count': data['count'],
                'avg_duration': data['total_duration'] / data['count'],
                'max_duration': data['max_duration']
            }
            for metric_name, data in self.metrics.items()
        }

# Background task
def monitor_reflog_health():
    """Periodic health check."""
    while True:
        health = monitor.check_reflog_health()

        if not health['healthy']:
            for warning in health['warnings']:
                logger.warning(f"Reflog health: {warning}")

        time.sleep(86400)  # Check daily
```

### 12.6 Documentation Requirements

**User Documentation:**
- Getting Started Guide
- Rollback Tutorial (with screenshots)
- Recovery Guide
- Troubleshooting
- FAQ

**Developer Documentation:**
- Architecture Overview
- API Reference
- Database Schema
- Testing Guide
- Contributing Guide

**Operational Documentation:**
- Deployment Guide
- Configuration Reference
- Monitoring Guide
- Backup & Recovery
- Performance Tuning

## 13. Conclusion

### 13.1 Design Completeness

This system design provides:

✅ **Complete architecture** - All components, interfaces, and data flows defined
✅ **Requirements mapping** - Every requirement from [01-problem-statement.md] addressed
✅ **Research-informed** - Design decisions based on [02-research-findings.md]
✅ **Risk mitigation** - All concerns from [99-critical-analysis.md] addressed
✅ **Implementation-ready** - Sufficient detail for developers to begin coding

### 13.2 Design Validation

The design satisfies the original "trilemma" from [01-problem-statement.md]:

| Constraint | How Satisfied | Evidence |
|------------|---------------|----------|
| Clean Git History | `git reset --hard` moves commits to reflog | Section 4.3 |
| Single Working Directory | No worktrees, work on current branch | Section 3.1 |
| Reliable Rollback | Git commits capture all changes | Section 4.2 |

The design scored 77/80 in [03-options-analysis.md], highest of all evaluated options.

### 13.3 Critical Success Factors

For successful implementation:

1. **Recovery branches are mandatory** - Not optional (per [99-critical-analysis.md])
2. **Performance optimization is critical** - Async commits, selective staging
3. **User education is essential** - Clear documentation about reflog limitations
4. **Monitoring is required** - Track reflog health, detect issues early

### 13.4 Next Steps

1. **Phase 1 (Weeks 1-2)**: Implement GitManager and core git operations
2. **Phase 1.5 (Week 2)**: Add recovery branch feature (critical safety net)
3. **Phase 2 (Week 3)**: Database schema and migrations
4. **Phase 3 (Week 4)**: Auto-commit integration with JSONL processor
5. **Phase 4 (Weeks 5-6)**: Web UI and API endpoints
6. **Phase 5 (Week 7)**: Testing and documentation
7. **Phase 6 (Week 8)**: Polish and deployment

**Total timeline: 8 weeks** (per [05-implementation-plan.md])

### 13.5 Design Philosophy Summary

This design embodies three key principles:

1. **Pragmatism** - Best available solution, not perfect solution
2. **Safety** - Multiple layers of recovery (reflog + recovery branches + database tracking)
3. **Usability** - Complex git operations hidden behind simple UI

As acknowledged in [99-critical-analysis.md]:
> "We're building a '90% solution' not a '100% solution' - and that's okay if we're honest about it."

This design is honest about limitations while providing the best possible solution given the constraints.
