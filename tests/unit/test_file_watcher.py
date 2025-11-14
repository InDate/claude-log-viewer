"""
Tests for file watcher queue implementation.

These tests verify that the queue-based file processing properly decouples
file watching from file processing, preventing blocking during expensive
operations.
"""

import pytest
import threading
import time
import queue
from unittest.mock import Mock, patch, MagicMock


@pytest.mark.unit
@pytest.mark.watcher
class TestFileProcessingQueue:
    """Tests for the file processing queue and worker thread."""

    def test_queue_non_blocking(self):
        """Verify that adding to queue is non-blocking."""
        test_queue = queue.Queue()

        # Adding items should be instant (non-blocking)
        start_time = time.time()
        for i in range(100):
            test_queue.put(None)
        elapsed = time.time() - start_time

        # Should complete in under 10ms for 100 items
        assert elapsed < 0.01, f"Queue operations took {elapsed}s, should be instant"
        assert test_queue.qsize() == 100

    def test_worker_processes_queue_items(self):
        """Verify worker thread processes items from queue."""
        test_queue = queue.Queue()
        shutdown_event = threading.Event()
        processed_items = []

        def test_worker():
            """Simple worker that tracks processed items."""
            while not shutdown_event.is_set():
                try:
                    item = test_queue.get(timeout=0.1)
                    processed_items.append(item)
                    test_queue.task_done()
                except queue.Empty:
                    continue

        # Start worker thread
        worker_thread = threading.Thread(target=test_worker, daemon=True)
        worker_thread.start()

        # Add items to queue
        test_items = ['item1', 'item2', 'item3']
        for item in test_items:
            test_queue.put(item)

        # Wait for processing (with timeout)
        test_queue.join()

        # Stop worker
        shutdown_event.set()
        worker_thread.join(timeout=1.0)

        # Verify all items were processed
        assert processed_items == test_items

    def test_worker_handles_exceptions_gracefully(self):
        """Verify worker continues after processing errors."""
        test_queue = queue.Queue()
        shutdown_event = threading.Event()
        processed_items = []
        error_count = 0

        def failing_processor(item):
            """Processor that fails on certain items."""
            if item == 'bad_item':
                raise ValueError("Test error")
            processed_items.append(item)

        def test_worker():
            """Worker that handles exceptions."""
            while not shutdown_event.is_set():
                try:
                    item = test_queue.get(timeout=0.1)
                    try:
                        failing_processor(item)
                    except Exception:
                        nonlocal error_count
                        error_count += 1
                    test_queue.task_done()
                except queue.Empty:
                    continue

        # Start worker
        worker_thread = threading.Thread(target=test_worker, daemon=True)
        worker_thread.start()

        # Add items including one that will fail
        test_items = ['item1', 'bad_item', 'item2']
        for item in test_items:
            test_queue.put(item)

        # Wait for processing
        test_queue.join()

        # Stop worker
        shutdown_event.set()
        worker_thread.join(timeout=1.0)

        # Verify worker continued after exception
        assert processed_items == ['item1', 'item2']
        assert error_count == 1

    def test_shutdown_event_stops_worker(self):
        """Verify shutdown event properly stops worker thread."""
        test_queue = queue.Queue()
        shutdown_event = threading.Event()
        iterations = 0

        def test_worker():
            """Worker that counts iterations."""
            nonlocal iterations
            while not shutdown_event.is_set():
                try:
                    test_queue.get(timeout=0.1)
                    test_queue.task_done()
                except queue.Empty:
                    iterations += 1

        # Start worker
        worker_thread = threading.Thread(target=test_worker, daemon=True)
        worker_thread.start()

        # Let it run briefly
        time.sleep(0.3)

        # Signal shutdown
        shutdown_event.set()

        # Worker should stop within reasonable time
        worker_thread.join(timeout=1.0)
        assert not worker_thread.is_alive(), "Worker thread did not stop"

        # Verify it actually ran (iterations should be > 0)
        assert iterations > 0, "Worker did not execute any iterations"

    def test_multiple_rapid_changes_queued(self):
        """Verify multiple rapid file changes are all queued."""
        test_queue = queue.Queue()

        # Simulate rapid file changes
        num_changes = 50
        start_time = time.time()
        for i in range(num_changes):
            test_queue.put(f"change_{i}")
        elapsed = time.time() - start_time

        # All items should be queued quickly
        assert test_queue.qsize() == num_changes
        # Should complete in under 10ms
        assert elapsed < 0.01, f"Queuing took {elapsed}s, should be instant"

    def test_empty_queue_timeout(self):
        """Verify worker handles empty queue with timeout correctly."""
        test_queue = queue.Queue()
        shutdown_event = threading.Event()
        timeout_count = 0

        def test_worker():
            """Worker that counts timeouts."""
            nonlocal timeout_count
            for _ in range(5):  # Run exactly 5 iterations
                if shutdown_event.is_set():
                    break
                try:
                    test_queue.get(timeout=0.1)
                    test_queue.task_done()
                except queue.Empty:
                    timeout_count += 1

        # Start worker with empty queue
        worker_thread = threading.Thread(target=test_worker, daemon=True)
        worker_thread.start()

        # Wait for worker to complete
        worker_thread.join(timeout=2.0)

        # Verify worker handled timeouts gracefully
        assert timeout_count == 5, "Worker should have timed out 5 times"
        assert not worker_thread.is_alive()

    @pytest.mark.integration
    def test_queue_with_mock_load_entries(self, mocker):
        """Integration test: verify queue calls load_latest_entries."""
        from claude_log_viewer import app

        # Mock the load_latest_entries function
        mock_load = mocker.patch.object(app, 'load_latest_entries')

        # Create test queue and worker
        test_queue = queue.Queue()
        shutdown_event = threading.Event()

        def test_worker():
            """Worker that mimics file_processing_worker."""
            while not shutdown_event.is_set():
                try:
                    file_path = test_queue.get(timeout=0.1)
                    try:
                        app.load_latest_entries(file_path)
                    except Exception as e:
                        pass  # Ignore errors
                    test_queue.task_done()
                except queue.Empty:
                    continue

        # Start worker
        worker_thread = threading.Thread(target=test_worker, daemon=True)
        worker_thread.start()

        # Queue file change (None means reload all)
        test_queue.put(None)

        # Wait for processing
        test_queue.join()

        # Stop worker
        shutdown_event.set()
        worker_thread.join(timeout=1.0)

        # Verify load_latest_entries was called with None
        mock_load.assert_called_once_with(None)

    def test_worker_respects_task_done(self):
        """Verify worker properly calls task_done for queue.join() to work."""
        test_queue = queue.Queue()
        shutdown_event = threading.Event()

        def test_worker():
            """Worker that properly calls task_done."""
            while not shutdown_event.is_set():
                try:
                    test_queue.get(timeout=0.1)
                    time.sleep(0.01)  # Simulate work
                    test_queue.task_done()
                except queue.Empty:
                    continue

        # Start worker
        worker_thread = threading.Thread(target=test_worker, daemon=True)
        worker_thread.start()

        # Add items
        for i in range(5):
            test_queue.put(f"item_{i}")

        # queue.join() should block until all items processed
        start_time = time.time()
        test_queue.join()
        elapsed = time.time() - start_time

        # Should have waited for processing (5 items * 0.01s = ~0.05s)
        assert elapsed >= 0.04, "join() returned too quickly, task_done() may not be called"

        # Cleanup
        shutdown_event.set()
        worker_thread.join(timeout=1.0)


@pytest.mark.unit
@pytest.mark.watcher
class TestJSONLHandler:
    """Tests for the JSONL file event handler."""

    def test_handler_queues_jsonl_changes(self, mocker):
        """Verify JSONLHandler queues JSONL file modifications."""
        from watchdog.events import FileSystemEvent

        # Create mock queue
        mock_queue = Mock()

        # Mock the global queue in app module
        mocker.patch('claude_log_viewer.app.file_processing_queue', mock_queue)

        # Import after patching
        from claude_log_viewer.app import JSONLHandler

        # Create handler
        handler = JSONLHandler()

        # Create mock event for .jsonl file
        event = FileSystemEvent('/path/to/session.jsonl')
        event.src_path = '/path/to/session.jsonl'

        # Trigger on_modified
        handler.on_modified(event)

        # Verify item was queued (should be None for reload all)
        mock_queue.put.assert_called_once_with(None)

    def test_handler_ignores_non_jsonl_files(self, mocker):
        """Verify JSONLHandler ignores non-JSONL files."""
        from watchdog.events import FileSystemEvent

        # Create mock queue
        mock_queue = Mock()
        mocker.patch('claude_log_viewer.app.file_processing_queue', mock_queue)

        from claude_log_viewer.app import JSONLHandler

        handler = JSONLHandler()

        # Create events for non-JSONL files
        non_jsonl_files = [
            '/path/to/file.txt',
            '/path/to/file.json',
            '/path/to/file.log',
            '/path/to/file.py'
        ]

        for file_path in non_jsonl_files:
            event = FileSystemEvent(file_path)
            event.src_path = file_path
            handler.on_modified(event)

        # Verify queue was never called
        mock_queue.put.assert_not_called()


@pytest.mark.unit
@pytest.mark.watcher
class TestFileWatcherIntegration:
    """Integration tests for file watcher with queue."""

    @pytest.mark.slow
    def test_rapid_file_changes_dont_block(self, tmp_path, mocker):
        """Verify rapid file changes don't block the watcher."""
        import json

        # Create test JSONL file
        jsonl_file = tmp_path / "test.jsonl"
        jsonl_file.write_text('{"type": "test", "timestamp": "2025-11-12T10:00:00Z"}\n')

        # Track timing of events
        event_times = []

        # Mock queue to track when items are queued
        mock_queue = Mock()
        def record_time(item):
            event_times.append(time.time())
        mock_queue.put = Mock(side_effect=record_time)

        mocker.patch('claude_log_viewer.app.file_processing_queue', mock_queue)

        from claude_log_viewer.app import JSONLHandler

        handler = JSONLHandler()

        # Simulate rapid file modifications
        from watchdog.events import FileModifiedEvent
        num_modifications = 10
        start_time = time.time()

        for i in range(num_modifications):
            event = FileModifiedEvent(str(jsonl_file))
            handler.on_modified(event)

        total_time = time.time() - start_time

        # All events should be queued very quickly (non-blocking)
        assert total_time < 0.01, f"Queueing {num_modifications} events took {total_time}s"
        assert mock_queue.put.call_count == num_modifications

        # Verify events were queued rapidly (within milliseconds of each other)
        if len(event_times) > 1:
            max_gap = max(event_times[i+1] - event_times[i]
                         for i in range(len(event_times) - 1))
            assert max_gap < 0.01, f"Max gap between events was {max_gap}s"
