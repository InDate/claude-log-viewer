"""
Shared pytest fixtures for claude-log-viewer tests.

This module provides reusable fixtures for testing database operations,
git operations, and file processing.
"""

import pytest
import sqlite3
import tempfile
import subprocess
from pathlib import Path
from contextlib import contextmanager


@pytest.fixture
def temp_db():
    """
    Provide a clean in-memory SQLite database for testing.

    Returns:
        str: Database path (":memory:")

    Example:
        def test_something(temp_db):
            conn = sqlite3.connect(temp_db)
            # ... test code ...
    """
    return ":memory:"


@pytest.fixture
def db_conn(temp_db):
    """
    Provide a database connection with schema initialized.

    Yields:
        sqlite3.Connection: Database connection with schema and WAL mode enabled

    Example:
        def test_insert(db_conn):
            cursor = db_conn.cursor()
            cursor.execute("INSERT INTO ...")
            db_conn.commit()
    """
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row

    # Enable WAL mode (critical for concurrency testing)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')

    # Enable foreign key constraints
    conn.execute('PRAGMA foreign_keys = ON')

    # Create basic schema (minimal for testing)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS usage_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            five_hour_used INTEGER,
            seven_day_used INTEGER,
            five_hour_total INTEGER,
            seven_day_total INTEGER,
            five_hour_tokens_consumed INTEGER,
            five_hour_messages_count INTEGER,
            seven_day_tokens_consumed INTEGER,
            seven_day_messages_count INTEGER,
            five_hour_tokens_total INTEGER,
            five_hour_messages_total INTEGER,
            seven_day_tokens_total INTEGER,
            seven_day_messages_total INTEGER,
            five_hour_pct REAL,
            seven_day_pct REAL,
            active_sessions TEXT,
            recalculated INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            first_seen TEXT,
            last_seen TEXT,
            message_count INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            path TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS git_checkpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            commit_hash TEXT NOT NULL,
            checkpoint_type TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            description TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );

        CREATE TABLE IF NOT EXISTS git_commits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            commit_hash TEXT NOT NULL,
            committed_at TEXT DEFAULT CURRENT_TIMESTAMP,
            tool_name TEXT,
            tool_metadata TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );
    """)
    conn.commit()

    yield conn
    conn.close()


@pytest.fixture
def git_repo(tmp_path):
    """
    Provide a temporary git repository for testing.

    Args:
        tmp_path: pytest's tmp_path fixture (temporary directory)

    Yields:
        Path: Path to the temporary git repository

    Example:
        def test_git_operation(git_repo):
            # git_repo is a Path object pointing to a real git repository
            subprocess.run(["git", "status"], cwd=git_repo, check=True)
    """
    repo_path = tmp_path / "test_repo"
    repo_path.mkdir()

    # Initialize git repository
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"],
                   cwd=repo_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"],
                   cwd=repo_path, check=True, capture_output=True)

    # Create initial commit
    (repo_path / "README.md").write_text("# Test Repository\n")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"],
                   cwd=repo_path, check=True, capture_output=True)

    yield repo_path


@pytest.fixture
def sample_jsonl_entries():
    """
    Provide sample JSONL entries for testing token counting and usage calculations.

    Returns:
        list[dict]: List of JSONL entry dictionaries

    Example:
        def test_token_counting(sample_jsonl_entries):
            for entry in sample_jsonl_entries:
                tokens = count_message_tokens(entry)
                assert tokens > 0
    """
    return [
        # User message
        {
            "type": "user",
            "timestamp": "2025-11-12T10:00:00Z",
            "message": {
                "role": "user",
                "content": "Hello, can you help me with Python?"
            },
            "sessionUuid": "test-session-1"
        },
        # Assistant response with text
        {
            "type": "assistant",
            "timestamp": "2025-11-12T10:00:05Z",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": "Of course! I'd be happy to help you with Python. What would you like to know?"
                    }
                ]
            },
            "sessionUuid": "test-session-1"
        },
        # Assistant response with tool use
        {
            "type": "assistant",
            "timestamp": "2025-11-12T10:00:10Z",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool_123",
                        "name": "read_file",
                        "input": {"path": "/test/file.py"}
                    }
                ]
            },
            "sessionUuid": "test-session-1"
        },
        # Tool result
        {
            "type": "tool_result",
            "timestamp": "2025-11-12T10:00:11Z",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool_123",
                        "content": "def hello():\n    print('Hello, World!')\n"
                    }
                ]
            },
            "sessionUuid": "test-session-1"
        },
        # System message
        {
            "type": "system",
            "timestamp": "2025-11-12T10:00:15Z",
            "content": "Session started",
            "subtype": "session_start",
            "sessionUuid": "test-session-1"
        }
    ]


@pytest.fixture
def sample_jsonl_file(tmp_path, sample_jsonl_entries):
    """
    Provide a temporary JSONL file with sample entries.

    Args:
        tmp_path: pytest's tmp_path fixture
        sample_jsonl_entries: Fixture providing sample entries

    Returns:
        Path: Path to the temporary JSONL file

    Example:
        def test_file_reading(sample_jsonl_file):
            with open(sample_jsonl_file, 'r') as f:
                for line in f:
                    entry = json.loads(line)
                    assert 'type' in entry
    """
    import json

    jsonl_file = tmp_path / "test_session.jsonl"
    with open(jsonl_file, 'w') as f:
        for entry in sample_jsonl_entries:
            f.write(json.dumps(entry) + '\n')

    return jsonl_file
