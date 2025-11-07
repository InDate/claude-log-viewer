"""
SQLite database for persistent storage of usage statistics and session details.
"""
import sqlite3
import os
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


def insert_snapshot(
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
    Insert a usage snapshot.

    Returns:
        The ID of the inserted snapshot
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO usage_snapshots (
                timestamp, five_hour_used, five_hour_limit,
                seven_day_used, seven_day_limit,
                five_hour_pct, seven_day_pct,
                five_hour_reset, seven_day_reset
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            timestamp, five_hour_used, five_hour_limit,
            seven_day_used, seven_day_limit,
            five_hour_pct, seven_day_pct,
            five_hour_reset, seven_day_reset
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
            ORDER BY timestamp ASC
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


if __name__ == '__main__':
    # Initialize database when run directly
    init_db()
    print("Database initialized successfully!")
