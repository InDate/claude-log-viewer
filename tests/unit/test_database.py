"""
Tests for database operations focusing on WAL mode, foreign keys, and concurrency.

These tests verify critical database features:
- WAL (Write-Ahead Logging) mode for concurrent access
- Foreign key constraint enforcement
- Concurrent read/write operations
- Nullable columns for usage calculations
- Two-phase snapshot storage (insert tick + update calculations)
"""

import pytest
import sqlite3
import threading
import time
import json
from pathlib import Path
from unittest.mock import Mock, patch


@pytest.mark.unit
@pytest.mark.database
class TestWALMode:
    """Tests for Write-Ahead Logging (WAL) mode configuration."""

    def test_wal_mode_enabled(self, db_conn):
        """Verify WAL mode is enabled for concurrent access."""
        cursor = db_conn.cursor()
        cursor.execute('PRAGMA journal_mode')
        journal_mode = cursor.fetchone()[0]

        assert journal_mode.upper() == 'WAL', \
            f"Expected WAL mode, got {journal_mode}"

    def test_synchronous_normal(self, db_conn):
        """Verify synchronous mode is set to NORMAL for WAL."""
        cursor = db_conn.cursor()
        cursor.execute('PRAGMA synchronous')
        synchronous = cursor.fetchone()[0]

        # synchronous=1 is NORMAL (0=OFF, 1=NORMAL, 2=FULL)
        assert synchronous == 1, \
            f"Expected synchronous=1 (NORMAL), got {synchronous}"

    def test_wal_allows_concurrent_reads(self, temp_db):
        """Verify WAL mode allows concurrent read operations."""
        # Create test database with WAL
        conn1 = sqlite3.connect(temp_db)
        conn1.execute('PRAGMA journal_mode=WAL')
        conn1.execute('CREATE TABLE test (id INTEGER, value TEXT)')
        conn1.execute('INSERT INTO test VALUES (1, "test")')
        conn1.commit()

        # Open two concurrent readers
        conn2 = sqlite3.connect(temp_db)
        conn2.execute('PRAGMA journal_mode=WAL')
        conn3 = sqlite3.connect(temp_db)
        conn3.execute('PRAGMA journal_mode=WAL')

        results = []

        def read_data(conn, reader_id):
            """Read from database in separate thread."""
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM test')
            count = cursor.fetchone()[0]
            results.append((reader_id, count))

        # Start concurrent reads
        t1 = threading.Thread(target=read_data, args=(conn2, 'reader1'))
        t2 = threading.Thread(target=read_data, args=(conn3, 'reader2'))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Both readers should succeed
        assert len(results) == 2
        assert results[0][1] == 1
        assert results[1][1] == 1

        # Cleanup
        conn1.close()
        conn2.close()
        conn3.close()

    def test_wal_allows_concurrent_read_write(self, temp_db):
        """Verify WAL mode allows concurrent read and write operations."""
        # Create test database with WAL
        conn_writer = sqlite3.connect(temp_db)
        conn_writer.execute('PRAGMA journal_mode=WAL')
        conn_writer.execute('CREATE TABLE test (id INTEGER, value TEXT)')
        conn_writer.execute('INSERT INTO test VALUES (1, "initial")')
        conn_writer.commit()

        conn_reader = sqlite3.connect(temp_db)
        conn_reader.execute('PRAGMA journal_mode=WAL')

        read_results = []
        write_completed = threading.Event()

        def slow_write():
            """Perform slow write operation."""
            cursor = conn_writer.cursor()
            cursor.execute('INSERT INTO test VALUES (2, "second")')
            time.sleep(0.05)  # Simulate slow write
            conn_writer.commit()
            write_completed.set()

        def concurrent_read():
            """Read while write is in progress."""
            time.sleep(0.01)  # Let write start first
            cursor = conn_reader.cursor()
            cursor.execute('SELECT COUNT(*) FROM test')
            count = cursor.fetchone()[0]
            read_results.append(count)

        # Start write and read concurrently
        t_write = threading.Thread(target=slow_write)
        t_read = threading.Thread(target=concurrent_read)

        t_write.start()
        t_read.start()
        t_write.join()
        t_read.join()

        # Read should succeed (may see 1 or 2 rows depending on timing)
        assert len(read_results) == 1
        assert read_results[0] in [1, 2], \
            "Read should succeed during write with WAL mode"

        # Cleanup
        conn_writer.close()
        conn_reader.close()


@pytest.mark.unit
@pytest.mark.database
class TestForeignKeyConstraints:
    """Tests for foreign key constraint enforcement."""

    def test_foreign_keys_enabled(self, db_conn):
        """Verify foreign key constraints are enabled."""
        cursor = db_conn.cursor()
        cursor.execute('PRAGMA foreign_keys')
        fk_enabled = cursor.fetchone()[0]

        assert fk_enabled == 1, "Foreign keys should be enabled"

    def test_foreign_key_violation_rejected(self, db_conn):
        """Verify foreign key violations are caught and rejected."""
        cursor = db_conn.cursor()

        # Create parent and child tables with FK constraint
        cursor.execute("""
            CREATE TABLE parent (
                id INTEGER PRIMARY KEY,
                name TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE child (
                id INTEGER PRIMARY KEY,
                parent_id INTEGER NOT NULL,
                value TEXT,
                FOREIGN KEY (parent_id) REFERENCES parent(id)
            )
        """)

        # Insert valid parent
        cursor.execute("INSERT INTO parent (id, name) VALUES (1, 'Parent 1')")
        db_conn.commit()

        # Try to insert child with non-existent parent (should fail)
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
            cursor.execute("INSERT INTO child (id, parent_id, value) VALUES (1, 999, 'Invalid')")
            db_conn.commit()

    def test_foreign_key_cascade_delete(self, db_conn):
        """Verify foreign key CASCADE deletes work correctly."""
        cursor = db_conn.cursor()

        # Create tables with CASCADE delete
        cursor.execute("""
            CREATE TABLE parent (
                id INTEGER PRIMARY KEY,
                name TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE child (
                id INTEGER PRIMARY KEY,
                parent_id INTEGER NOT NULL,
                value TEXT,
                FOREIGN KEY (parent_id) REFERENCES parent(id) ON DELETE CASCADE
            )
        """)

        # Insert parent and child
        cursor.execute("INSERT INTO parent (id, name) VALUES (1, 'Parent 1')")
        cursor.execute("INSERT INTO child (id, parent_id, value) VALUES (1, 1, 'Child 1')")
        db_conn.commit()

        # Verify child exists
        cursor.execute("SELECT COUNT(*) FROM child WHERE parent_id = 1")
        assert cursor.fetchone()[0] == 1

        # Delete parent
        cursor.execute("DELETE FROM parent WHERE id = 1")
        db_conn.commit()

        # Verify child was cascade deleted
        cursor.execute("SELECT COUNT(*) FROM child WHERE parent_id = 1")
        assert cursor.fetchone()[0] == 0

    def test_git_checkpoints_foreign_key(self, db_conn):
        """Verify conversation_forks table enforces FK to git_checkpoints."""
        from claude_log_viewer.database import migrate_add_git_tables

        # Add git tables
        migrate_add_git_tables()

        cursor = db_conn.cursor()

        # Try to insert conversation_fork with non-existent checkpoint
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
            cursor.execute("""
                INSERT INTO conversation_forks (
                    parent_uuid, parent_session_id,
                    child_uuid, child_session_id,
                    fork_timestamp, checkpoint_id
                ) VALUES (
                    'parent-uuid', 'parent-session',
                    'child-uuid', 'child-session',
                    '2025-11-12T10:00:00Z', 999
                )
            """)
            db_conn.commit()


@pytest.mark.unit
@pytest.mark.database
class TestNullableColumns:
    """Tests for nullable token/message count columns."""

    def test_usage_snapshot_nullable_columns(self, db_conn):
        """Verify token/message count columns accept NULL values."""
        cursor = db_conn.cursor()

        # Get table schema
        cursor.execute("PRAGMA table_info(usage_snapshots)")
        columns_info = {row[1]: {'notnull': row[3]} for row in cursor.fetchall()}

        # Verify nullable columns (notnull=0 means nullable)
        nullable_columns = [
            'five_hour_tokens_consumed',
            'five_hour_messages_count',
            'seven_day_tokens_consumed',
            'seven_day_messages_count',
            'five_hour_tokens_total',
            'five_hour_messages_total',
            'seven_day_tokens_total',
            'seven_day_messages_total',
            'active_sessions',
            'recalculated'
        ]

        for col_name in nullable_columns:
            if col_name in columns_info:
                assert columns_info[col_name]['notnull'] == 0, \
                    f"Column '{col_name}' should be nullable (notnull=0)"

    def test_insert_snapshot_with_nulls(self, db_conn):
        """Verify snapshots can be inserted with NULL calculation fields."""
        from claude_log_viewer.database import insert_snapshot

        # Insert snapshot with all nullable fields as None
        snapshot_id = insert_snapshot(
            timestamp='2025-11-12T10:00:00Z',
            five_hour_used=75,
            five_hour_limit=100,
            seven_day_used=45,
            seven_day_limit=100,
            five_hour_tokens_consumed=None,
            five_hour_messages_count=None,
            seven_day_tokens_consumed=None,
            seven_day_messages_count=None,
            five_hour_tokens_total=None,
            five_hour_messages_total=None,
            seven_day_tokens_total=None,
            seven_day_messages_total=None,
            active_sessions=None
        )

        # Verify snapshot was inserted
        assert snapshot_id is not None

        # Verify NULL values are stored
        cursor = db_conn.cursor()
        cursor.execute("SELECT * FROM usage_snapshots WHERE id = ?", (snapshot_id,))
        row = cursor.fetchone()

        assert row['five_hour_tokens_consumed'] is None
        assert row['five_hour_messages_count'] is None
        assert row['seven_day_tokens_consumed'] is None
        assert row['seven_day_messages_count'] is None


@pytest.mark.unit
@pytest.mark.database
class TestTwoPhaseSnapshot:
    """Tests for two-phase snapshot storage pattern."""

    def test_insert_snapshot_tick_creates_with_nulls(self, db_conn):
        """Verify insert_snapshot_tick creates snapshot with NULL calculations."""
        from claude_log_viewer.database import insert_snapshot_tick, get_snapshot_by_id

        # Phase 1: Insert API tick (no calculations)
        snapshot_id = insert_snapshot_tick(
            timestamp='2025-11-12T10:00:00Z',
            five_hour_used=75,
            five_hour_limit=100,
            seven_day_used=45,
            seven_day_limit=100,
            five_hour_pct=75.0,
            seven_day_pct=45.0
        )

        # Verify snapshot was created
        snapshot = get_snapshot_by_id(snapshot_id)
        assert snapshot is not None

        # Verify API data is stored
        assert snapshot['five_hour_used'] == 75
        assert snapshot['five_hour_limit'] == 100
        assert snapshot['seven_day_used'] == 45
        assert snapshot['seven_day_limit'] == 100

        # Verify calculation fields are NULL
        assert snapshot['five_hour_tokens_consumed'] is None
        assert snapshot['five_hour_messages_count'] is None
        assert snapshot['seven_day_tokens_consumed'] is None
        assert snapshot['seven_day_messages_count'] is None
        assert snapshot['five_hour_tokens_total'] is None
        assert snapshot['five_hour_messages_total'] is None
        assert snapshot['seven_day_tokens_total'] is None
        assert snapshot['seven_day_messages_total'] is None
        assert snapshot['active_sessions'] is None
        assert snapshot['recalculated'] == 0

    def test_update_snapshot_calculations(self, db_conn):
        """Verify update_snapshot_calculations updates only provided fields."""
        from claude_log_viewer.database import (
            insert_snapshot_tick, update_snapshot_calculations, get_snapshot_by_id
        )

        # Phase 1: Insert API tick
        snapshot_id = insert_snapshot_tick(
            timestamp='2025-11-12T10:00:00Z',
            five_hour_used=75,
            five_hour_limit=100,
            seven_day_used=45,
            seven_day_limit=100
        )

        # Phase 2: Update 5-hour calculations
        update_snapshot_calculations(
            snapshot_id=snapshot_id,
            five_hour_tokens_consumed=1000,
            five_hour_messages_count=5,
            five_hour_tokens_total=15000,
            five_hour_messages_total=75,
            active_sessions=['session-123', 'session-456']
        )

        # Verify updates
        snapshot = get_snapshot_by_id(snapshot_id)
        assert snapshot['five_hour_tokens_consumed'] == 1000
        assert snapshot['five_hour_messages_count'] == 5
        assert snapshot['five_hour_tokens_total'] == 15000
        assert snapshot['five_hour_messages_total'] == 75

        # Verify active_sessions JSON
        active_sessions = json.loads(snapshot['active_sessions'])
        assert active_sessions == ['session-123', 'session-456']

        # Verify 7-day fields still NULL (not updated)
        assert snapshot['seven_day_tokens_consumed'] is None
        assert snapshot['seven_day_messages_count'] is None

    def test_update_snapshot_calculations_partial(self, db_conn):
        """Verify partial updates work (only some fields updated)."""
        from claude_log_viewer.database import (
            insert_snapshot_tick, update_snapshot_calculations, get_snapshot_by_id
        )

        # Phase 1: Insert API tick
        snapshot_id = insert_snapshot_tick(
            timestamp='2025-11-12T10:00:00Z',
            five_hour_used=75,
            five_hour_limit=100,
            seven_day_used=45,
            seven_day_limit=100
        )

        # Phase 2a: Update only 5-hour consumed
        update_snapshot_calculations(
            snapshot_id=snapshot_id,
            five_hour_tokens_consumed=1000
        )

        snapshot = get_snapshot_by_id(snapshot_id)
        assert snapshot['five_hour_tokens_consumed'] == 1000
        assert snapshot['five_hour_messages_count'] is None  # Still NULL

        # Phase 2b: Update only 7-day consumed
        update_snapshot_calculations(
            snapshot_id=snapshot_id,
            seven_day_tokens_consumed=5000
        )

        snapshot = get_snapshot_by_id(snapshot_id)
        assert snapshot['five_hour_tokens_consumed'] == 1000  # Unchanged
        assert snapshot['seven_day_tokens_consumed'] == 5000

    def test_update_snapshot_empty_call(self, db_conn):
        """Verify update with no fields is a no-op."""
        from claude_log_viewer.database import (
            insert_snapshot_tick, update_snapshot_calculations, get_snapshot_by_id
        )

        # Phase 1: Insert API tick
        snapshot_id = insert_snapshot_tick(
            timestamp='2025-11-12T10:00:00Z',
            five_hour_used=75,
            five_hour_limit=100,
            seven_day_used=45,
            seven_day_limit=100
        )

        # Phase 2: Update with no fields (should be no-op)
        update_snapshot_calculations(snapshot_id=snapshot_id)

        # Verify snapshot still exists and unchanged
        snapshot = get_snapshot_by_id(snapshot_id)
        assert snapshot is not None
        assert snapshot['five_hour_tokens_consumed'] is None


@pytest.mark.unit
@pytest.mark.database
class TestActiveSessionsValidation:
    """Tests for active_sessions validation and storage."""

    def test_validate_valid_session_ids(self):
        """Verify valid session IDs pass validation."""
        from claude_log_viewer.database import validate_session_ids

        valid_sessions = [
            'session-123',
            'abc-def-456',
            'test_session_1',
            '1234567890'
        ]

        result = validate_session_ids(valid_sessions)
        assert result == valid_sessions

    def test_validate_invalid_session_ids(self):
        """Verify invalid session IDs are rejected."""
        from claude_log_viewer.database import validate_session_ids

        # Non-string type
        with pytest.raises(ValueError, match="Session ID must be string"):
            validate_session_ids([123])

        # Empty string
        with pytest.raises(ValueError, match="Session ID cannot be empty"):
            validate_session_ids([''])

        # Too long
        with pytest.raises(ValueError, match="Session ID too long"):
            validate_session_ids(['x' * 101])

        # Invalid characters
        with pytest.raises(ValueError, match="Session ID contains invalid characters"):
            validate_session_ids(['session@123'])

    def test_insert_snapshot_with_valid_sessions(self, db_conn):
        """Verify snapshots store valid active_sessions as JSON."""
        from claude_log_viewer.database import insert_snapshot, get_snapshot_by_id

        snapshot_id = insert_snapshot(
            timestamp='2025-11-12T10:00:00Z',
            five_hour_used=75,
            five_hour_limit=100,
            seven_day_used=45,
            seven_day_limit=100,
            active_sessions=['session-1', 'session-2', 'session-3']
        )

        snapshot = get_snapshot_by_id(snapshot_id)
        active_sessions = json.loads(snapshot['active_sessions'])

        assert active_sessions == ['session-1', 'session-2', 'session-3']

    def test_insert_snapshot_with_invalid_sessions_logs_warning(self, db_conn, capfd):
        """Verify invalid active_sessions logs warning but doesn't fail insertion."""
        from claude_log_viewer.database import insert_snapshot, get_snapshot_by_id

        # Insert with invalid session IDs
        snapshot_id = insert_snapshot(
            timestamp='2025-11-12T10:00:00Z',
            five_hour_used=75,
            five_hour_limit=100,
            seven_day_used=45,
            seven_day_limit=100,
            active_sessions=['session@invalid']  # Invalid character
        )

        # Verify snapshot was created (doesn't fail)
        snapshot = get_snapshot_by_id(snapshot_id)
        assert snapshot is not None

        # Verify active_sessions is NULL (validation failed)
        assert snapshot['active_sessions'] is None

        # Verify warning was logged
        captured = capfd.readouterr()
        assert 'Warning: Invalid active_sessions' in captured.out


@pytest.mark.integration
@pytest.mark.database
class TestConcurrentDatabaseOperations:
    """Integration tests for concurrent database operations."""

    def test_concurrent_snapshot_inserts(self, temp_db):
        """Verify concurrent snapshot insertions work correctly."""
        from claude_log_viewer.database import insert_snapshot

        # Mock the DB_PATH to use temp_db
        with patch('claude_log_viewer.database.DB_PATH', temp_db):
            from claude_log_viewer.database import init_db
            init_db()

            results = []
            errors = []

            def insert_snapshots(thread_id):
                """Insert snapshots from separate thread."""
                try:
                    for i in range(5):
                        snapshot_id = insert_snapshot(
                            timestamp=f'2025-11-12T10:00:{thread_id:02d}Z',
                            five_hour_used=50 + thread_id,
                            five_hour_limit=100,
                            seven_day_used=30 + thread_id,
                            seven_day_limit=100
                        )
                        results.append((thread_id, snapshot_id))
                except Exception as e:
                    errors.append((thread_id, str(e)))

            # Start multiple threads inserting concurrently
            threads = [threading.Thread(target=insert_snapshots, args=(i,))
                      for i in range(3)]

            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # Verify all insertions succeeded
            assert len(errors) == 0, f"Errors occurred: {errors}"
            assert len(results) == 15  # 3 threads * 5 inserts each

    def test_concurrent_read_write_snapshot(self, temp_db):
        """Verify concurrent reads and writes to snapshots work."""
        from claude_log_viewer.database import (
            insert_snapshot_tick, update_snapshot_calculations, get_snapshot_by_id
        )

        # Mock the DB_PATH to use temp_db
        with patch('claude_log_viewer.database.DB_PATH', temp_db):
            from claude_log_viewer.database import init_db
            init_db()

            # Create initial snapshot
            snapshot_id = insert_snapshot_tick(
                timestamp='2025-11-12T10:00:00Z',
                five_hour_used=75,
                five_hour_limit=100,
                seven_day_used=45,
                seven_day_limit=100
            )

            read_results = []
            write_completed = threading.Event()

            def slow_write():
                """Perform slow calculation update."""
                time.sleep(0.02)
                update_snapshot_calculations(
                    snapshot_id=snapshot_id,
                    five_hour_tokens_consumed=1000,
                    five_hour_messages_count=5
                )
                write_completed.set()

            def concurrent_reads():
                """Read snapshot while write is happening."""
                for _ in range(5):
                    snapshot = get_snapshot_by_id(snapshot_id)
                    read_results.append(snapshot is not None)
                    time.sleep(0.01)

            # Start write and reads concurrently
            t_write = threading.Thread(target=slow_write)
            t_read = threading.Thread(target=concurrent_reads)

            t_write.start()
            t_read.start()
            t_write.join()
            t_read.join()

            # All reads should succeed
            assert all(read_results), "All reads should succeed during write"
            assert len(read_results) == 5
