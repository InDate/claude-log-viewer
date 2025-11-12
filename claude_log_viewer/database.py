"""
SQLite database for persistent storage of usage statistics and session details.
"""
import sqlite3
import os
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
from pathlib import Path

# Database file path - store in user's home directory for persistence
DB_DIR = Path.home() / '.claude-log-viewer'
DB_DIR.mkdir(exist_ok=True)
DB_PATH = str(DB_DIR / 'logviewer.db')


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Enable column access by name
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def migrate_usage_snapshots_nullable():
    """
    Ensure usage snapshot token/message count columns are nullable.

    This migration verifies that the following columns can accept NULL values:
    - five_hour_tokens_consumed
    - five_hour_messages_count
    - seven_day_tokens_consumed
    - seven_day_messages_count
    - five_hour_tokens_total
    - five_hour_messages_total
    - seven_day_tokens_total
    - seven_day_messages_total

    Note: SQLite does not support ALTER COLUMN to change NOT NULL constraints.
    This function validates that columns were created without NOT NULL constraints.
    If a table was created with the correct schema, this is a no-op.

    This migration is idempotent and safe to run multiple times.
    """
    with get_db() as conn:
        cursor = conn.cursor()

        # Get current table schema
        cursor.execute("PRAGMA table_info(usage_snapshots)")
        columns_info = {row[1]: {'type': row[2], 'notnull': row[3], 'default': row[4]}
                       for row in cursor.fetchall()}

        # Columns that should be nullable
        nullable_columns = [
            'five_hour_tokens_consumed',
            'five_hour_messages_count',
            'seven_day_tokens_consumed',
            'seven_day_messages_count',
            'five_hour_tokens_total',
            'five_hour_messages_total',
            'seven_day_tokens_total',
            'seven_day_messages_total'
        ]

        # Verify all columns are nullable (notnull=0 means nullable)
        all_nullable = True
        for col_name in nullable_columns:
            if col_name in columns_info:
                if columns_info[col_name]['notnull'] == 1:
                    print(f"⚠ Warning: Column '{col_name}' has NOT NULL constraint")
                    all_nullable = False
                else:
                    print(f"✓ Column '{col_name}' is nullable")
            else:
                # Column doesn't exist yet (will be added by ALTER TABLE in another migration)
                pass

        if all_nullable:
            print("✓ All usage snapshot count columns are nullable")
        else:
            print("⚠ Some columns are NOT NULL - requires table recreation to fix")
            print("  Run this query to check constraints:")
            print("  sqlite3 ~/.claude-log-viewer/logviewer.db 'PRAGMA table_info(usage_snapshots)'")

        conn.commit()


def migrate_add_fork_tracking():
    """
    Add fork tracking columns to usage_snapshots table.

    Adds:
    - active_sessions TEXT: JSON array of session IDs active at this snapshot
    - recalculated INTEGER: Flag indicating if totals have been recalculated (0 or 1)

    This migration is idempotent - it checks if columns exist before adding them.
    """
    with get_db() as conn:
        cursor = conn.cursor()

        # Check if columns already exist using PRAGMA table_info
        cursor.execute("PRAGMA table_info(usage_snapshots)")
        columns = {row[1] for row in cursor.fetchall()}

        # Add active_sessions column if it doesn't exist
        if 'active_sessions' not in columns:
            print("Adding 'active_sessions' column to usage_snapshots table...")
            cursor.execute("""
                ALTER TABLE usage_snapshots
                ADD COLUMN active_sessions TEXT
            """)
            print("✓ Added 'active_sessions' column")
        else:
            print("✓ Column 'active_sessions' already exists")

        # Add recalculated column if it doesn't exist
        if 'recalculated' not in columns:
            print("Adding 'recalculated' column to usage_snapshots table...")
            cursor.execute("""
                ALTER TABLE usage_snapshots
                ADD COLUMN recalculated INTEGER DEFAULT 0
            """)
            print("✓ Added 'recalculated' column")
        else:
            print("✓ Column 'recalculated' already exists")

        conn.commit()


def migrate_add_settings_table():
    """
    Add settings table for user preferences.

    Creates settings table with key-value storage.
    This migration is idempotent and safe to run multiple times.
    """
    with get_db() as conn:
        cursor = conn.cursor()

        # Create settings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("✓ Created table 'settings'")

        # Set default values for new settings
        cursor.execute("""
            INSERT OR IGNORE INTO settings (key, value)
            VALUES ('git_enabled', 'false')
        """)
        print("✓ Set default git_enabled = false")

        conn.commit()
        print("✓ Settings table migration complete")


def migrate_add_project_git_settings():
    """
    Add per-project git settings table.

    Allows enabling/disabling git checkpoints on a per-project basis.
    This migration is idempotent and safe to run multiple times.
    """
    with get_db() as conn:
        cursor = conn.cursor()

        # Create project_git_settings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS project_git_settings (
                project_name TEXT PRIMARY KEY,
                git_enabled INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("✓ Created table 'project_git_settings'")

        # Create repo_git_settings table for per-repo git enable/disable
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS repo_git_settings (
                repo_path TEXT PRIMARY KEY,
                git_enabled INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("✓ Created table 'repo_git_settings'")

        # Create project_git_repos table for discovered repositories
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS project_git_repos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name TEXT NOT NULL,
                repo_path TEXT NOT NULL,
                is_primary INTEGER DEFAULT 0,
                file_count INTEGER DEFAULT 0,
                discovered_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(project_name, repo_path)
            )
        """)
        print("✓ Created table 'project_git_repos'")

        # Create indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_project_repos_project
            ON project_git_repos(project_name)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_project_repos_primary
            ON project_git_repos(project_name, is_primary)
        """)
        print("✓ Created indexes for project_git_repos")

        conn.commit()
        print("✓ Project git settings table migration complete")


def migrate_add_git_tables():
    """
    Add git rollback tables for checkpoint and commit tracking.

    Creates three new tables:
    - git_checkpoints: Stores checkpoint metadata (session start, manual, fork points)
    - git_commits: Tracks auto-commits from tool operations
    - conversation_forks: Links conversation forks to git checkpoints

    This migration is idempotent and safe to run multiple times.
    """
    with get_db() as conn:
        cursor = conn.cursor()

        # Create git_checkpoints table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS git_checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_uuid TEXT NOT NULL,
                checkpoint_type TEXT NOT NULL,
                commit_hash TEXT NOT NULL,
                message_uuid TEXT,
                parent_uuid TEXT,
                timestamp TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                description TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("✓ Created table 'git_checkpoints'")

        # Create indexes for git_checkpoints
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_checkpoints_session
            ON git_checkpoints(session_uuid)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_checkpoints_message
            ON git_checkpoints(message_uuid)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_checkpoints_timestamp
            ON git_checkpoints(timestamp)
        """)
        print("✓ Created indexes for git_checkpoints")

        # Create git_commits table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS git_commits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_uuid TEXT NOT NULL,
                agent_id TEXT,
                commit_hash TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                tool_use_id TEXT,
                description TEXT,
                timestamp TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("✓ Created table 'git_commits'")

        # Create indexes for git_commits
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_commits_session
            ON git_commits(session_uuid)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_commits_hash
            ON git_commits(commit_hash)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_commits_timestamp
            ON git_commits(timestamp)
        """)
        print("✓ Created indexes for git_commits")

        # Create conversation_forks table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversation_forks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_uuid TEXT NOT NULL,
                parent_session_id TEXT NOT NULL,
                child_uuid TEXT NOT NULL,
                child_session_id TEXT NOT NULL,
                fork_timestamp TEXT NOT NULL,
                checkpoint_id INTEGER,
                message_uuid TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (checkpoint_id) REFERENCES git_checkpoints(id)
            )
        """)
        print("✓ Created table 'conversation_forks'")

        # Create indexes for conversation_forks
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_forks_parent
            ON conversation_forks(parent_uuid)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_forks_child
            ON conversation_forks(child_uuid)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_forks_checkpoint
            ON conversation_forks(checkpoint_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_forks_message
            ON conversation_forks(message_uuid)
        """)
        print("✓ Created indexes for conversation_forks")

        conn.commit()
        print("✓ Git rollback tables migration complete")


def init_db():
    """Initialize database schema."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Create usage_snapshots table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usage_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                five_hour_used INTEGER NOT NULL,
                five_hour_limit INTEGER NOT NULL,
                seven_day_used INTEGER NOT NULL,
                seven_day_limit INTEGER NOT NULL,
                five_hour_pct REAL,
                seven_day_pct REAL,
                five_hour_reset TEXT,
                seven_day_reset TEXT,
                five_hour_tokens_consumed INTEGER,
                five_hour_messages_count INTEGER,
                seven_day_tokens_consumed INTEGER,
                seven_day_messages_count INTEGER,
                five_hour_tokens_total INTEGER,
                five_hour_messages_total INTEGER,
                seven_day_tokens_total INTEGER,
                seven_day_messages_total INTEGER,
                active_sessions TEXT,
                recalculated INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create index on timestamp for efficient range queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_snapshots_timestamp
            ON usage_snapshots(timestamp)
        """)

        # Create session_details table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS session_details (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                total_messages INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                model_used TEXT,
                has_plans INTEGER DEFAULT 0,
                has_todos INTEGER DEFAULT 0,
                plan_count INTEGER DEFAULT 0,
                todo_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create index on session_id for quick lookups
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_session_id
            ON session_details(session_id)
        """)

        # Create index on start_time for range queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_session_start
            ON session_details(start_time)
        """)

        conn.commit()
        print(f"Database initialized at: {DB_PATH}")

        # Run migrations
        migrate_usage_snapshots_nullable()
        migrate_add_fork_tracking()
        migrate_add_settings_table()
        migrate_add_project_git_settings()
        migrate_add_git_tables()


def validate_session_ids(session_ids: List[str]) -> List[str]:
    """
    Validate session IDs before storing in database.

    Args:
        session_ids: List of session ID strings

    Returns:
        Validated list of session IDs

    Raises:
        ValueError: If any session ID is invalid
    """
    if not session_ids:
        return []

    validated = []
    for session_id in session_ids:
        # Session IDs should be non-empty strings
        if not isinstance(session_id, str):
            raise ValueError(f"Session ID must be string, got {type(session_id)}")

        if not session_id or not session_id.strip():
            raise ValueError("Session ID cannot be empty")

        # Session IDs should be reasonable length (UUIDs are ~36 chars)
        if len(session_id) > 100:
            raise ValueError(f"Session ID too long: {len(session_id)} chars")

        # Session IDs should be alphanumeric with hyphens
        if not all(c.isalnum() or c in '-_' for c in session_id):
            raise ValueError(f"Session ID contains invalid characters: {session_id}")

        validated.append(session_id.strip())

    return validated


def insert_snapshot(
    timestamp: str,
    five_hour_used: int,
    five_hour_limit: int,
    seven_day_used: int,
    seven_day_limit: int,
    five_hour_pct: float = None,
    seven_day_pct: float = None,
    five_hour_reset: str = None,
    seven_day_reset: str = None,
    five_hour_tokens_consumed: int = None,
    five_hour_messages_count: int = None,
    seven_day_tokens_consumed: int = None,
    seven_day_messages_count: int = None,
    five_hour_tokens_total: int = None,
    five_hour_messages_total: int = None,
    seven_day_tokens_total: int = None,
    seven_day_messages_total: int = None,
    active_sessions: List[str] = None
) -> int:
    """
    Insert a usage snapshot into the database.

    Required Args:
        timestamp: ISO format timestamp (NOT NULL)
        five_hour_used: Tokens used in 5-hour window (NOT NULL)
        five_hour_limit: Token limit for 5-hour window (NOT NULL)
        seven_day_used: Tokens used in 7-day window (NOT NULL)
        seven_day_limit: Token limit for 7-day window (NOT NULL)

    Optional Args (nullable - can be None):
        five_hour_pct: Percentage of 5-hour limit used (0-100)
        seven_day_pct: Percentage of 7-day limit used (0-100)
        five_hour_reset: ISO timestamp when 5-hour window resets
        seven_day_reset: ISO timestamp when 7-day window resets
        five_hour_tokens_consumed: Tokens consumed since last snapshot (5h window)
        five_hour_messages_count: Messages sent since last snapshot (5h window)
        seven_day_tokens_consumed: Tokens consumed since last snapshot (7d window)
        seven_day_messages_count: Messages sent since last snapshot (7d window)
        five_hour_tokens_total: Running total of tokens in current 5h window
        five_hour_messages_total: Running total of messages in current 5h window
        seven_day_tokens_total: Running total of tokens in current 7d window
        seven_day_messages_total: Running total of messages in current 7d window
        active_sessions: List of session IDs that were active at this snapshot time

    Note:
        All token/message count fields are nullable to support scenarios where:
        - First snapshot has no baseline for delta calculation
        - Usage data is unavailable or incomplete
        - Fork-aware filtering hasn't been applied yet

    Returns:
        The ID of the inserted snapshot

    Raises:
        ValueError: If active_sessions contains invalid session IDs (logged but doesn't fail)
    """
    # Validate and convert active_sessions
    if active_sessions is not None:
        try:
            validated_sessions = validate_session_ids(active_sessions)
            active_sessions_json = json.dumps(validated_sessions)
        except ValueError as e:
            # Log error but don't fail insertion - just store None
            print(f"Warning: Invalid active_sessions: {e}")
            active_sessions_json = None
    else:
        active_sessions_json = None

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO usage_snapshots (
                timestamp, five_hour_used, five_hour_limit,
                seven_day_used, seven_day_limit,
                five_hour_pct, seven_day_pct,
                five_hour_reset, seven_day_reset,
                five_hour_tokens_consumed, five_hour_messages_count,
                seven_day_tokens_consumed, seven_day_messages_count,
                five_hour_tokens_total, five_hour_messages_total,
                seven_day_tokens_total, seven_day_messages_total,
                active_sessions
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            timestamp, five_hour_used, five_hour_limit,
            seven_day_used, seven_day_limit,
            five_hour_pct, seven_day_pct,
            five_hour_reset, seven_day_reset,
            five_hour_tokens_consumed, five_hour_messages_count,
            seven_day_tokens_consumed, seven_day_messages_count,
            five_hour_tokens_total, five_hour_messages_total,
            seven_day_tokens_total, seven_day_messages_total,
            active_sessions_json
        ))
        return cursor.lastrowid


def get_snapshots_in_range(start_time: str, end_time: str) -> List[Dict[str, Any]]:
    """
    Get all usage snapshots within a time range.

    Args:
        start_time: ISO format timestamp
        end_time: ISO format timestamp

    Returns:
        List of snapshot dictionaries
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM usage_snapshots
            WHERE timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp DESC
        """, (start_time, end_time))

        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_latest_snapshot() -> Optional[Dict[str, Any]]:
    """Get the most recent usage snapshot."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM usage_snapshots
            ORDER BY timestamp DESC
            LIMIT 1
        """)

        row = cursor.fetchone()
        return dict(row) if row else None


def get_snapshot_by_id(snapshot_id: int) -> Optional[Dict[str, Any]]:
    """
    Get a specific snapshot by its ID.

    Args:
        snapshot_id: The snapshot ID to retrieve

    Returns:
        Snapshot dictionary or None if not found
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM usage_snapshots
            WHERE id = ?
        """, (snapshot_id,))

        row = cursor.fetchone()
        return dict(row) if row else None


def insert_snapshot_tick(
    timestamp: str,
    five_hour_used: int,
    five_hour_limit: int,
    seven_day_used: int,
    seven_day_limit: int,
    five_hour_pct: float = None,
    seven_day_pct: float = None,
    five_hour_reset: str = None,
    seven_day_reset: str = None
) -> int:
    """
    Insert an API tick snapshot with only raw API data (no calculations).

    This is Phase 1 of the two-phase snapshot storage:
    1. Store API data immediately (this function)
    2. Calculate and update deltas/totals later (update_snapshot_calculations)

    All delta and total fields are set to NULL initially, enabling offline
    recalculation per FR6 requirement.

    Required Args:
        timestamp: ISO format timestamp (NOT NULL)
        five_hour_used: Percentage used in 5-hour window (0-100)
        five_hour_limit: Limit for 5-hour window (always 100)
        seven_day_used: Percentage used in 7-day window (0-100)
        seven_day_limit: Limit for 7-day window (always 100)

    Optional Args:
        five_hour_pct: Percentage of 5-hour limit used (0-100)
        seven_day_pct: Percentage of 7-day limit used (0-100)
        five_hour_reset: ISO timestamp when 5-hour window resets
        seven_day_reset: ISO timestamp when 7-day window resets

    Returns:
        The ID of the inserted snapshot

    Example:
        >>> snapshot_id = insert_snapshot_tick(
        ...     timestamp="2025-11-11T10:00:00Z",
        ...     five_hour_used=75,
        ...     five_hour_limit=100,
        ...     seven_day_used=45,
        ...     seven_day_limit=100,
        ...     five_hour_pct=75.0,
        ...     seven_day_pct=45.0,
        ...     five_hour_reset="2025-11-11T14:00:00Z",
        ...     seven_day_reset="2025-11-18T10:00:00Z"
        ... )
        >>> # All delta/total fields are NULL at this point
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO usage_snapshots (
                timestamp, five_hour_used, five_hour_limit,
                seven_day_used, seven_day_limit,
                five_hour_pct, seven_day_pct,
                five_hour_reset, seven_day_reset,
                five_hour_tokens_consumed, five_hour_messages_count,
                seven_day_tokens_consumed, seven_day_messages_count,
                five_hour_tokens_total, five_hour_messages_total,
                seven_day_tokens_total, seven_day_messages_total,
                active_sessions, recalculated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 0)
        """, (
            timestamp, five_hour_used, five_hour_limit,
            seven_day_used, seven_day_limit,
            five_hour_pct, seven_day_pct,
            five_hour_reset, seven_day_reset
        ))
        return cursor.lastrowid


def update_snapshot_calculations(
    snapshot_id: int,
    five_hour_tokens_consumed: int = None,
    five_hour_messages_count: int = None,
    seven_day_tokens_consumed: int = None,
    seven_day_messages_count: int = None,
    five_hour_tokens_total: int = None,
    five_hour_messages_total: int = None,
    seven_day_tokens_total: int = None,
    seven_day_messages_total: int = None,
    active_sessions: List[str] = None
) -> None:
    """
    Update calculated fields for a snapshot after API tick has been stored.

    This is Phase 2 of the two-phase snapshot storage:
    1. Store API data immediately (insert_snapshot_tick)
    2. Calculate and update deltas/totals (this function)

    All parameters are optional - only provided fields will be updated.
    Allows selective updates of 5-hour or 7-day window calculations.

    Args:
        snapshot_id: ID of the snapshot to update
        five_hour_tokens_consumed: Tokens consumed since last snapshot (5h window)
        five_hour_messages_count: Messages sent since last snapshot (5h window)
        seven_day_tokens_consumed: Tokens consumed since last snapshot (7d window)
        seven_day_messages_count: Messages sent since last snapshot (7d window)
        five_hour_tokens_total: Running total of tokens in current 5h window
        five_hour_messages_total: Running total of messages in current 5h window
        seven_day_tokens_total: Running total of tokens in current 7d window
        seven_day_messages_total: Running total of messages in current 7d window
        active_sessions: List of session IDs that were active at snapshot time

    Raises:
        ValueError: If active_sessions contains invalid session IDs

    Example:
        >>> # Phase 1: Store API tick
        >>> snapshot_id = insert_snapshot_tick(...)
        >>>
        >>> # Phase 2: Calculate and update
        >>> update_snapshot_calculations(
        ...     snapshot_id=snapshot_id,
        ...     five_hour_tokens_consumed=1000,
        ...     five_hour_messages_count=5,
        ...     five_hour_tokens_total=15000,
        ...     five_hour_messages_total=75,
        ...     active_sessions=['session-123', 'session-456']
        ... )
    """
    # Validate and convert active_sessions
    if active_sessions is not None:
        validated_sessions = validate_session_ids(active_sessions)
        active_sessions_json = json.dumps(validated_sessions)
    else:
        active_sessions_json = None

    # Build UPDATE query dynamically based on provided fields
    update_fields = []
    params = []

    if five_hour_tokens_consumed is not None:
        update_fields.append("five_hour_tokens_consumed = ?")
        params.append(five_hour_tokens_consumed)

    if five_hour_messages_count is not None:
        update_fields.append("five_hour_messages_count = ?")
        params.append(five_hour_messages_count)

    if seven_day_tokens_consumed is not None:
        update_fields.append("seven_day_tokens_consumed = ?")
        params.append(seven_day_tokens_consumed)

    if seven_day_messages_count is not None:
        update_fields.append("seven_day_messages_count = ?")
        params.append(seven_day_messages_count)

    if five_hour_tokens_total is not None:
        update_fields.append("five_hour_tokens_total = ?")
        params.append(five_hour_tokens_total)

    if five_hour_messages_total is not None:
        update_fields.append("five_hour_messages_total = ?")
        params.append(five_hour_messages_total)

    if seven_day_tokens_total is not None:
        update_fields.append("seven_day_tokens_total = ?")
        params.append(seven_day_tokens_total)

    if seven_day_messages_total is not None:
        update_fields.append("seven_day_messages_total = ?")
        params.append(seven_day_messages_total)

    if active_sessions_json is not None:
        update_fields.append("active_sessions = ?")
        params.append(active_sessions_json)

    # If no fields to update, return early
    if not update_fields:
        return

    # Add snapshot_id to params for WHERE clause
    params.append(snapshot_id)

    with get_db() as conn:
        cursor = conn.cursor()
        query = f"""
            UPDATE usage_snapshots
            SET {', '.join(update_fields)}
            WHERE id = ?
        """
        cursor.execute(query, params)


def insert_session(
    session_id: str,
    start_time: str,
    total_messages: int = 0,
    total_tokens: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    model_used: str = None,
    has_plans: bool = False,
    has_todos: bool = False,
    plan_count: int = 0,
    todo_count: int = 0,
    end_time: str = None
):
    """
    Insert or update session details.

    Uses REPLACE to handle both insert and update cases.
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO session_details (
                session_id, start_time, end_time,
                total_messages, total_tokens, input_tokens, output_tokens,
                model_used, has_plans, has_todos, plan_count, todo_count,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            session_id, start_time, end_time,
            total_messages, total_tokens, input_tokens, output_tokens,
            model_used, int(has_plans), int(has_todos), plan_count, todo_count
        ))


def get_session_details(session_id: str) -> Optional[Dict[str, Any]]:
    """Get details for a specific session."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM session_details
            WHERE session_id = ?
        """, (session_id,))

        row = cursor.fetchone()
        return dict(row) if row else None


def get_all_sessions() -> List[Dict[str, Any]]:
    """Get all session details ordered by start time."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM session_details
            ORDER BY start_time DESC
        """)

        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_total_stats() -> Dict[str, Any]:
    """Get aggregate statistics across all sessions."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                COUNT(*) as total_sessions,
                SUM(total_tokens) as total_tokens,
                SUM(input_tokens) as total_input_tokens,
                SUM(output_tokens) as total_output_tokens,
                SUM(total_messages) as total_messages,
                AVG(total_tokens) as avg_tokens_per_session,
                SUM(has_plans) as sessions_with_plans,
                SUM(has_todos) as sessions_with_todos
            FROM session_details
        """)

        row = cursor.fetchone()
        return dict(row) if row else {}


def get_setting(key: str, default: Any = None) -> Any:
    """
    Get a setting value from the database.

    Args:
        key: Setting key
        default: Default value if setting doesn't exist

    Returns:
        Setting value (parsed as JSON if possible) or default
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()

        if row is None:
            return default

        value = row[0]

        # Try to parse as JSON for boolean/number types
        if value in ('true', 'false'):
            return value == 'true'
        elif value.isdigit():
            return int(value)
        else:
            return value


def set_setting(key: str, value: Any) -> None:
    """
    Set a setting value in the database.

    Args:
        key: Setting key
        value: Setting value (will be converted to string)
    """
    with get_db() as conn:
        cursor = conn.cursor()

        # Convert boolean to string
        if isinstance(value, bool):
            value_str = 'true' if value else 'false'
        else:
            value_str = str(value)

        cursor.execute("""
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
        """, (key, value_str))

        conn.commit()


def get_all_settings() -> Dict[str, Any]:
    """
    Get all settings from the database.

    Returns:
        Dictionary of all settings with parsed values
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM settings")

        settings = {}
        for row in cursor.fetchall():
            key, value = row[0], row[1]

            # Parse value
            if value in ('true', 'false'):
                settings[key] = (value == 'true')
            elif value.isdigit():
                settings[key] = int(value)
            else:
                settings[key] = value

        return settings


def get_project_git_enabled(project_name: str) -> bool:
    """
    Check if git is enabled for a specific project.

    Args:
        project_name: Project name

    Returns:
        True if git is enabled for this project
    """
    # First check global setting
    if not get_setting('git_enabled', False):
        return False

    # Then check project-specific setting
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT git_enabled FROM project_git_settings WHERE project_name = ?",
            (project_name,)
        )
        row = cursor.fetchone()

        # Default to False if no setting exists
        return bool(row[0]) if row else False


def set_project_git_enabled(project_name: str, enabled: bool) -> None:
    """
    Enable or disable git for a specific project.

    Args:
        project_name: Project name
        enabled: True to enable, False to disable
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO project_git_settings (project_name, git_enabled, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(project_name) DO UPDATE SET
                git_enabled = excluded.git_enabled,
                updated_at = CURRENT_TIMESTAMP
        """, (project_name, 1 if enabled else 0))

        conn.commit()


def get_all_project_git_settings() -> Dict[str, bool]:
    """
    Get git enabled status for all projects.

    Returns:
        Dictionary mapping project names to git enabled status
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT project_name, git_enabled FROM project_git_settings")

        return {row[0]: bool(row[1]) for row in cursor.fetchall()}


def get_repo_git_enabled(repo_path: str) -> bool:
    """
    Check if git is enabled for a specific repository.

    Args:
        repo_path: Repository path

    Returns:
        True if git is enabled for this repository
    """
    # First check global setting
    if not get_setting('git_enabled', False):
        return False

    # Then check repo-specific setting
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT git_enabled FROM repo_git_settings WHERE repo_path = ?",
            (repo_path,)
        )
        row = cursor.fetchone()

        # Default to False if no setting exists
        return bool(row[0]) if row else False


def set_repo_git_enabled(repo_path: str, enabled: bool) -> None:
    """
    Enable or disable git for a specific repository.

    Args:
        repo_path: Repository path
        enabled: True to enable, False to disable
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO repo_git_settings (repo_path, git_enabled, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(repo_path) DO UPDATE SET
                git_enabled = excluded.git_enabled,
                updated_at = CURRENT_TIMESTAMP
        """, (repo_path, 1 if enabled else 0))

        conn.commit()


def get_all_repo_git_settings() -> Dict[str, bool]:
    """
    Get git enabled status for all repositories.

    Returns:
        Dictionary mapping repo paths to git enabled status
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT repo_path, git_enabled FROM repo_git_settings")

        return {row[0]: bool(row[1]) for row in cursor.fetchall()}


def save_discovered_repos(project_name: str, repo_file_counts: Dict[str, int], primary_repo: Optional[str] = None) -> None:
    """
    Save discovered git repositories for a project.

    Args:
        project_name: Project name
        repo_file_counts: Dict of {repo_path: file_count}
        primary_repo: Optional primary repo path (auto-determined if None)
    """
    if not repo_file_counts:
        return

    # Determine primary if not specified
    if primary_repo is None and repo_file_counts:
        primary_repo = max(repo_file_counts, key=repo_file_counts.get)

    with get_db() as conn:
        cursor = conn.cursor()

        # Clear existing repos for this project (fresh discovery)
        cursor.execute("DELETE FROM project_git_repos WHERE project_name = ?", (project_name,))

        # Insert discovered repos
        for repo_path, file_count in repo_file_counts.items():
            is_primary = 1 if repo_path == primary_repo else 0

            cursor.execute("""
                INSERT INTO project_git_repos (project_name, repo_path, is_primary, file_count)
                VALUES (?, ?, ?, ?)
            """, (project_name, repo_path, is_primary, file_count))

        conn.commit()


def get_project_repos(project_name: str) -> List[Dict[str, Any]]:
    """
    Get all discovered git repositories for a project.

    Args:
        project_name: Project name

    Returns:
        List of repo dicts with path, is_primary, file_count
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT repo_path, is_primary, file_count, discovered_at
            FROM project_git_repos
            WHERE project_name = ?
            ORDER BY is_primary DESC, file_count DESC
        """, (project_name,))

        repos = []
        for row in cursor.fetchall():
            repos.append({
                'repo_path': row[0],
                'is_primary': bool(row[1]),
                'file_count': row[2],
                'discovered_at': row[3]
            })

        return repos


def get_primary_repo_for_project(project_name: str) -> Optional[str]:
    """
    Get the primary git repository path for a project.

    Args:
        project_name: Project name

    Returns:
        Path to primary repo, or None if not discovered
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT repo_path
            FROM project_git_repos
            WHERE project_name = ? AND is_primary = 1
            LIMIT 1
        """, (project_name,))

        row = cursor.fetchone()
        return row[0] if row else None


if __name__ == '__main__':
    # Initialize database when run directly
    init_db()
    print("Database initialized successfully!")
