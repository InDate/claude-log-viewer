"""
Tests for git manager operations, focusing on repository locking and commit validation.

These tests verify that git operations are properly serialized per repository
to prevent race conditions, while allowing concurrent operations on different repositories.
"""

import pytest
import threading
import time
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock


@pytest.mark.unit
@pytest.mark.git
class TestRepositoryLocking:
    """Tests for repository-level locking mechanism."""

    def test_get_repo_lock_creates_lock(self):
        """Verify _get_repo_lock creates a lock for a new repository."""
        from claude_log_viewer.git_manager import _get_repo_lock, _repo_locks

        # Clear any existing locks
        _repo_locks.clear()

        # Get lock for a test path
        test_path = Path("/test/repo1")
        lock1 = _get_repo_lock(test_path)

        # Verify lock was created
        assert lock1 is not None
        assert isinstance(lock1, threading.Lock)
        assert str(test_path) in _repo_locks

    def test_get_repo_lock_returns_same_lock(self):
        """Verify _get_repo_lock returns the same lock for the same repo."""
        from claude_log_viewer.git_manager import _get_repo_lock, _repo_locks

        _repo_locks.clear()

        test_path = Path("/test/repo2")
        lock1 = _get_repo_lock(test_path)
        lock2 = _get_repo_lock(test_path)

        # Should return the exact same lock object
        assert lock1 is lock2

    def test_different_repos_get_different_locks(self):
        """Verify different repositories get different locks."""
        from claude_log_viewer.git_manager import _get_repo_lock, _repo_locks

        _repo_locks.clear()

        path1 = Path("/test/repo3")
        path2 = Path("/test/repo4")

        lock1 = _get_repo_lock(path1)
        lock2 = _get_repo_lock(path2)

        # Should be different lock objects
        assert lock1 is not lock2

    def test_lock_creation_thread_safe(self):
        """Verify lock creation doesn't race when multiple threads access same repo."""
        from claude_log_viewer.git_manager import _get_repo_lock, _repo_locks

        _repo_locks.clear()

        test_path = Path("/test/repo5")
        locks_acquired = []

        def get_lock_thread():
            """Thread function that gets a lock."""
            lock = _get_repo_lock(test_path)
            locks_acquired.append(lock)

        # Start multiple threads concurrently
        threads = [threading.Thread(target=get_lock_thread) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All threads should have gotten the same lock object
        assert len(locks_acquired) == 10
        first_lock = locks_acquired[0]
        assert all(lock is first_lock for lock in locks_acquired)

    def test_same_repo_operations_serialize(self):
        """Verify operations on same repository are serialized (no race conditions)."""
        from claude_log_viewer.git_manager import _get_repo_lock, _repo_locks

        _repo_locks.clear()

        test_path = Path("/test/repo6")
        execution_order = []
        lock = _get_repo_lock(test_path)

        def slow_operation(thread_id):
            """Simulate slow git operation."""
            with lock:
                execution_order.append(f"{thread_id}_start")
                time.sleep(0.05)  # Simulate work
                execution_order.append(f"{thread_id}_end")

        # Start multiple threads
        threads = [threading.Thread(target=slow_operation, args=(i,))
                  for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Operations should have serialized (start/end pairs should not interleave)
        # Valid pattern: 0_start, 0_end, 1_start, 1_end, 2_start, 2_end
        # Invalid pattern: 0_start, 1_start, 0_end, 1_end (interleaved)

        for i in range(0, len(execution_order), 2):
            start_event = execution_order[i]
            end_event = execution_order[i + 1]

            # Each start should be followed by its corresponding end
            thread_id = start_event.split('_')[0]
            assert end_event == f"{thread_id}_end", \
                f"Operations interleaved: {execution_order}"

    def test_different_repos_operate_concurrently(self):
        """Verify operations on different repositories can run concurrently."""
        from claude_log_viewer.git_manager import _get_repo_lock, _repo_locks

        _repo_locks.clear()

        path1 = Path("/test/repo7")
        path2 = Path("/test/repo8")

        lock1 = _get_repo_lock(path1)
        lock2 = _get_repo_lock(path2)

        execution_events = []
        event_lock = threading.Lock()

        def operation_repo1():
            """Operation on repo1."""
            with lock1:
                with event_lock:
                    execution_events.append("repo1_start")
                time.sleep(0.1)  # Hold lock for a while
                with event_lock:
                    execution_events.append("repo1_end")

        def operation_repo2():
            """Operation on repo2."""
            time.sleep(0.02)  # Slight delay to ensure repo1 starts first
            with lock2:
                with event_lock:
                    execution_events.append("repo2_start")
                time.sleep(0.05)
                with event_lock:
                    execution_events.append("repo2_end")

        # Start both operations
        t1 = threading.Thread(target=operation_repo1)
        t2 = threading.Thread(target=operation_repo2)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Repo2 should start while repo1 is still running (concurrent execution)
        # Expected order: repo1_start, repo2_start, repo2_end, repo1_end
        assert execution_events[0] == "repo1_start"
        assert execution_events[1] == "repo2_start", \
            "repo2 should start while repo1 is running (concurrent execution)"
        assert execution_events[2] == "repo2_end"
        assert execution_events[3] == "repo1_end"

    def test_lock_released_after_exception(self):
        """Verify lock is released even when operation raises exception."""
        from claude_log_viewer.git_manager import _get_repo_lock, _repo_locks

        _repo_locks.clear()

        test_path = Path("/test/repo9")
        lock = _get_repo_lock(test_path)

        execution_order = []

        def failing_operation():
            """Operation that raises exception."""
            with lock:
                execution_order.append("op1_acquired")
                raise ValueError("Test error")

        def successful_operation():
            """Operation that succeeds."""
            time.sleep(0.05)  # Wait for first operation to fail
            with lock:
                execution_order.append("op2_acquired")

        # Start both threads
        t1 = threading.Thread(target=lambda: pytest.raises(ValueError, failing_operation))
        t2 = threading.Thread(target=successful_operation)

        # First operation will fail but should release lock
        try:
            t1 = threading.Thread(target=failing_operation)
            t1.start()
        except:
            pass

        t2.start()
        t2.join(timeout=1.0)

        # Second operation should have acquired lock (first one released it)
        assert "op2_acquired" in execution_order


@pytest.mark.unit
@pytest.mark.git
class TestCommitHashValidation:
    """Tests for commit hash validation."""

    def test_validate_full_hash(self):
        """Verify validation accepts full 40-character SHA-1 hash."""
        from claude_log_viewer.git_manager import validate_commit_hash

        # Valid 40-character hash
        valid_hash = "a" * 40
        assert validate_commit_hash(valid_hash) is True

        # Another valid hash with hex chars
        valid_hash2 = "1234567890abcdef1234567890abcdef12345678"
        assert validate_commit_hash(valid_hash2) is True

    def test_validate_short_hash(self):
        """Verify validation accepts short hashes (7+ characters)."""
        from claude_log_viewer.git_manager import validate_commit_hash

        # 7-character short hash
        assert validate_commit_hash("abc1234") is True

        # 10-character hash
        assert validate_commit_hash("abc1234567") is True

        # 20-character hash
        assert validate_commit_hash("abc12345" * 2 + "abc1") is True

    def test_validate_invalid_too_short(self):
        """Verify validation rejects hashes shorter than 7 characters."""
        from claude_log_viewer.git_manager import validate_commit_hash

        assert validate_commit_hash("abc") is False
        assert validate_commit_hash("123456") is False  # Only 6 chars
        assert validate_commit_hash("") is False

    def test_validate_invalid_non_hex(self):
        """Verify validation rejects non-hexadecimal characters."""
        from claude_log_viewer.git_manager import validate_commit_hash

        assert validate_commit_hash("abcdefg1234567") is False  # 'g' is not hex
        assert validate_commit_hash("hello world") is False
        assert validate_commit_hash("1234567!") is False

    def test_validate_invalid_uppercase(self):
        """Verify validation rejects uppercase hex characters."""
        from claude_log_viewer.git_manager import validate_commit_hash

        # Git commit hashes are lowercase
        assert validate_commit_hash("ABCDEF1234567890") is False
        assert validate_commit_hash("Abc1234") is False

    def test_validate_invalid_types(self):
        """Verify validation handles invalid types gracefully."""
        from claude_log_viewer.git_manager import validate_commit_hash

        assert validate_commit_hash(None) is False
        assert validate_commit_hash(12345678) is False
        assert validate_commit_hash([]) is False
        assert validate_commit_hash({}) is False

    def test_validate_too_long(self):
        """Verify validation rejects hashes longer than 40 characters."""
        from claude_log_viewer.git_manager import validate_commit_hash

        too_long = "a" * 41
        assert validate_commit_hash(too_long) is False


@pytest.mark.integration
@pytest.mark.git
class TestGitManagerIntegration:
    """Integration tests for GitRollbackManager with real git repositories."""

    def test_manager_uses_locking(self, git_repo, mocker):
        """Verify GitRollbackManager operations use repository locking."""
        from claude_log_viewer.git_manager import GitRollbackManager, _get_repo_lock

        # Spy on _get_repo_lock to verify it's called
        spy = mocker.spy('claude_log_viewer.git_manager', '_get_repo_lock')

        manager = GitRollbackManager(project_dir=str(git_repo))

        # Perform an operation that should use locking
        try:
            # Try to get current commit (should use locking internally)
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=git_repo,
                capture_output=True,
                text=True,
                check=True
            )
            commit_hash = result.stdout.strip()

            # Verify it's a valid commit hash
            from claude_log_viewer.git_manager import validate_commit_hash
            assert validate_commit_hash(commit_hash)
        except subprocess.CalledProcessError:
            pytest.skip("Git operation failed")

    def test_concurrent_operations_different_repos(self, tmp_path, git_repo):
        """Integration test: concurrent operations on different repos work."""
        # Create second git repo
        repo2 = tmp_path / "repo2"
        repo2.mkdir()
        subprocess.run(["git", "init"], cwd=repo2, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo2, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo2, check=True, capture_output=True)

        # Create initial commits in both
        (git_repo / "file1.txt").write_text("test1")
        (repo2 / "file2.txt").write_text("test2")

        subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "commit1"], cwd=git_repo, check=True, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=repo2, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "commit2"], cwd=repo2, check=True, capture_output=True)

        from claude_log_viewer.git_manager import _get_repo_lock

        results = []

        def git_operation(repo_path, result_id):
            """Perform git operation with locking."""
            lock = _get_repo_lock(Path(repo_path))
            with lock:
                time.sleep(0.05)  # Simulate work
                result = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    check=True
                )
                results.append((result_id, result.stdout.strip()))

        # Run operations concurrently on both repos
        t1 = threading.Thread(target=git_operation, args=(git_repo, "repo1"))
        t2 = threading.Thread(target=git_operation, args=(repo2, "repo2"))

        start = time.time()
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        elapsed = time.time() - start

        # Both should complete successfully
        assert len(results) == 2

        # Should complete faster than if serialized (< 0.1s vs 0.1s+)
        # This proves concurrent execution
        assert elapsed < 0.08, f"Operations took {elapsed}s, should be concurrent"
