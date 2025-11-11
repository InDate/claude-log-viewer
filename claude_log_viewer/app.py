#!/usr/bin/env python3
"""
JSONL Log Viewer - Real-time viewer for Claude Code transcripts
"""

from flask import Flask, render_template, jsonify, request
from pathlib import Path
import json
import os
from datetime import datetime, timedelta
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import threading
import time
import subprocess
import requests
import argparse
from collections import defaultdict
from .database import (
    init_db, insert_snapshot, get_snapshots_in_range, get_latest_snapshot,
    insert_session, DB_PATH, get_db, migrate_add_fork_tracking,
    insert_snapshot_tick, update_snapshot_calculations, get_snapshot_by_id,
    get_setting, set_setting, get_all_settings
)
from .token_counter import count_message_tokens
from .timeline_builder import build_timeline
from .usage_calculator import (
    detect_reset, calculate_delta, calculate_total_incremental,
    FIVE_HOUR_WINDOW, SEVEN_DAY_WINDOW
)
from .git_manager import GitRollbackManager

app = Flask(__name__)

# Get the Claude projects directory - monitor all projects
CLAUDE_PROJECTS_DIR = Path.home() / '.claude' / 'projects'
CLAUDE_TODOS_DIR = Path.home() / '.claude' / 'todos'
target_project = None  # Set via --project CLI argument for project isolation

# Store latest entries
latest_entries = []
latest_entries_lock = threading.Lock()  # Protect against race conditions with file watcher
max_entries = 500  # Keep last 500 entries in memory (default, configurable via CLI)
file_age_days = 2  # Only load files modified in last N days (default, configurable via CLI)

# Cache for usage data
usage_cache = {
    'data': None,
    'timestamp': 0,
    'cache_duration': 60  # Cache for 60 seconds
}

# Track previous usage values to detect increments
previous_usage = {
    'five_hour_used': None,
    'seven_day_used': None
}


class JSONLHandler(FileSystemEventHandler):
    """Watch for changes to JSONL files"""

    def on_modified(self, event):
        if event.src_path.endswith('.jsonl'):
            # Reload all files to maintain complete view
            load_latest_entries()


class TodoHandler(FileSystemEventHandler):
    """Watch for changes to todo JSON files"""

    def on_modified(self, event):
        if event.src_path.endswith('.json'):
            # Todo files changed, but we don't need to reload here
            # Frontend polls /api/todos regularly
            pass

    def on_created(self, event):
        if event.src_path.endswith('.json'):
            # New todo file created
            pass


def enrich_content(entry):
    """Enrich entry with displayable content from structured data"""
    # If entry already has non-empty string content, return it
    content = entry.get('content', '')
    if isinstance(content, str) and content and content.strip():
        return content

    # Handle different entry types
    entry_type = entry.get('type', '')

    # Summary entries
    if entry_type == 'summary':
        return entry.get('summary', '')

    # File history snapshots
    if entry_type == 'file-history-snapshot':
        snapshot = entry.get('snapshot', {})
        files = snapshot.get('trackedFileBackups', {})
        if files:
            file_list = list(files.keys())[:3]  # Show first 3 files
            count = len(files)
            preview = ', '.join(file_list)
            if count > 3:
                preview += f', ... (+{count-3} more)'
            return f"📸 Snapshot: {count} file{'s' if count != 1 else ''} tracked - {preview}"
        return "📸 File snapshot"

    # System messages
    if entry_type == 'system':
        content = entry.get('content', '')
        subtype = entry.get('subtype', '')
        if subtype == 'compact_boundary':
            metadata = entry.get('compactMetadata', {})
            pre_tokens = metadata.get('preTokens', '')
            if pre_tokens:
                content += f" ({pre_tokens:,} tokens)"
        return content

    # User and assistant messages with structured content
    message = entry.get('message', {})
    if isinstance(message, dict):
        content_array = message.get('content', [])

        # Handle simple string content (common for user messages)
        if isinstance(content_array, str) and content_array.strip():
            return content_array

        # Handle structured array content
        if isinstance(content_array, list) and content_array:
            parts = []

            for item in content_array:
                item_type = item.get('type', '')

                # Text content
                if item_type == 'text':
                    text = item.get('text', '')
                    if text:
                        parts.append(text)

                # Thinking content
                elif item_type == 'thinking':
                    thinking_text = item.get('thinking', '')
                    if thinking_text:
                        # Clean up thinking text: remove newlines and extra whitespace
                        cleaned_text = ' '.join(thinking_text.split())
                        parts.append(f'💭 Thought: {cleaned_text}')

                # Tool use
                elif item_type == 'tool_use':
                    tool_name = item.get('name', 'Unknown')
                    tool_input = item.get('input', {})

                    # Format key parameters
                    params = []
                    for key, value in tool_input.items():
                        if key in ['command', 'file_path', 'url', 'pattern', 'selector', 'description']:
                            if isinstance(value, str):
                                # Truncate long values
                                display_value = value[:50] + '...' if len(value) > 50 else value
                                params.append(f"{key}={display_value}")

                    param_str = ', '.join(params[:2])  # Show first 2 params
                    if param_str:
                        parts.append(f"🔧 {tool_name}({param_str})")
                    else:
                        parts.append(f"🔧 {tool_name}")

                # Tool result
                elif item_type == 'tool_result':
                    result_content = item.get('content', '')
                    tool_use_id = item.get('tool_use_id', '')

                    # Try to get tool name from toolUseResult
                    tool_result = entry.get('toolUseResult', {})

                    # Check if result is empty
                    is_empty = not result_content or result_content == ''

                    # Format based on tool type
                    if isinstance(result_content, str):
                        # Bash output
                        if 'exit code' in result_content.lower() or 'command' in str(tool_result).lower():
                            # Extract first line or exit status
                            lines = result_content.split('\n')
                            first_line = lines[0][:100] if lines else ''
                            if 'exit code' in result_content.lower():
                                parts.append(f"✓ Bash: {first_line}")
                            else:
                                parts.append(f"✓ Output: {first_line}")

                        # File operations
                        elif 'filePath' in tool_result:
                            file_path = tool_result.get('filePath', '')
                            file_name = file_path.split('/')[-1] if file_path else 'file'
                            if 'oldString' in tool_result:
                                parts.append(f"✓ Edited {file_name}")
                            else:
                                parts.append(f"✓ Updated {file_name}")

                        # File read
                        elif result_content and '\n' in result_content and '→' in result_content:
                            # Looks like cat -n output
                            line_count = len(result_content.split('\n'))
                            parts.append(f"✓ Read file: {line_count} lines")

                        # Generic result
                        elif result_content:
                            preview = result_content[:100]
                            parts.append(f"✓ Result: {preview}")
                        else:
                            # Empty result
                            parts.append("✓ Tool completed")

                    # Handle non-string results (lists, objects)
                    elif result_content:
                        if isinstance(result_content, list):
                            parts.append(f"✓ Result: [{len(result_content)} items]")
                        elif isinstance(result_content, dict):
                            parts.append(f"✓ Result: {{{len(result_content)} keys}}")
                        else:
                            parts.append(f"✓ Result: {str(result_content)[:100]}")
                    else:
                        # Completely empty
                        parts.append("✓ Tool completed")

            if parts:
                return ' '.join(parts)

    # Fallback
    return entry.get('content', '')


def extract_tool_items(entry):
    """Extract tool_use and tool_result items from message content"""
    tool_items = {
        'tool_uses': [],
        'tool_results': []
    }

    # Check if entry has message.content array
    message = entry.get('message', {})
    if isinstance(message, dict):
        content_array = message.get('content', [])

        if isinstance(content_array, list):
            for item in content_array:
                item_type = item.get('type', '')

                # Extract tool uses
                if item_type == 'tool_use':
                    tool_items['tool_uses'].append({
                        'id': item.get('id', ''),
                        'name': item.get('name', ''),
                        'input': item.get('input', {})
                    })

                # Extract tool results
                elif item_type == 'tool_result':
                    tool_items['tool_results'].append({
                        'tool_use_id': item.get('tool_use_id', ''),
                        'content': item.get('content', ''),
                        'is_error': item.get('is_error', False)
                    })

    # Also include top-level toolUseResult if present
    if 'toolUseResult' in entry:
        tool_items['toolUseResult'] = entry['toolUseResult']

    return tool_items if (tool_items['tool_uses'] or tool_items['tool_results']) else None


def load_latest_entries(file_path=None):
    """Load entries from JSONL files across all project directories"""
    global latest_entries

    if file_path:
        files = [Path(file_path)]
    else:
        # Recursively find all .jsonl files in all project subdirectories
        all_files = list(CLAUDE_PROJECTS_DIR.glob('**/*.jsonl'))

        # Filter to only files modified in the last N days
        cutoff_time = time.time() - (file_age_days * 24 * 60 * 60)
        files = [f for f in all_files if f.stat().st_mtime > cutoff_time]

        print(f"Found {len(files)} file(s) modified in the last {file_age_days} day(s) out of {len(all_files)} total")

    entries = []
    for file in files:
        try:
            with open(file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entry = json.loads(line)
                            # Add metadata
                            entry['_file'] = str(file)
                            entry['_file_path'] = str(file)

                            # Enrich content for display
                            entry['content_display'] = enrich_content(entry)

                            # Extract tool items for detailed viewing
                            tool_items = extract_tool_items(entry)
                            if tool_items:
                                entry['tool_items'] = tool_items
                                # Add a filterable type for tool results
                                if tool_items.get('tool_results'):
                                    entry['has_tool_results'] = True

                            # Count tokens from actual content
                            try:
                                entry['content_tokens'] = count_message_tokens(entry)
                            except Exception as e:
                                # If token counting fails, set to 0 and log error
                                entry['content_tokens'] = 0
                                print(f"Error counting tokens for entry: {e}")

                            entries.append(entry)
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            print(f"Error reading {file}: {e}")

    # Sort by timestamp if available
    entries.sort(key=lambda x: x.get('timestamp', ''), reverse=True)

    # Keep only the latest entries (protected by lock)
    with latest_entries_lock:
        latest_entries = entries[:max_entries]


def load_entries_for_time_range(start_timestamp, end_timestamp=None):
    """
    Load log entries from disk for a specific time range and add them to latest_entries.

    Args:
        start_timestamp: ISO timestamp string (start of range)
        end_timestamp: ISO timestamp string (end of range, defaults to now)

    Returns:
        Number of entries loaded
    """
    global latest_entries

    if end_timestamp is None:
        end_timestamp = datetime.utcnow().isoformat() + 'Z'

    # Find all .jsonl files in all project subdirectories
    all_files = list(CLAUDE_PROJECTS_DIR.glob('**/*.jsonl'))

    # Convert timestamps to datetime for comparison
    start_dt = datetime.fromisoformat(start_timestamp.replace('Z', '+00:00'))
    end_dt = datetime.fromisoformat(end_timestamp.replace('Z', '+00:00'))

    # Get file modification times - only check files modified in the time range
    files_to_check = []
    for file in all_files:
        file_mtime = datetime.fromtimestamp(file.stat().st_mtime, tz=start_dt.tzinfo)
        # Check files modified around the time range (with some buffer)
        if file_mtime >= start_dt - timedelta(hours=1):
            files_to_check.append(file)

    # Track which timestamps we already have in memory (protected by lock)
    with latest_entries_lock:
        existing_timestamps = {entry.get('timestamp') for entry in latest_entries if entry.get('timestamp')}

    new_entries = []
    for file in files_to_check:
        try:
            with open(file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entry = json.loads(line)
                            entry_timestamp = entry.get('timestamp', '')

                            # Skip if we already have this entry in memory
                            if entry_timestamp in existing_timestamps:
                                continue

                            # Check if entry is in our time range
                            if entry_timestamp:
                                entry_dt = datetime.fromisoformat(entry_timestamp.replace('Z', '+00:00'))
                                if start_dt <= entry_dt <= end_dt:
                                    # Add metadata
                                    entry['_file'] = str(file)
                                    entry['_file_path'] = str(file)

                                    # Enrich content
                                    entry['content_display'] = enrich_content(entry)

                                    # Extract tool items
                                    tool_items = extract_tool_items(entry)
                                    if tool_items:
                                        entry['tool_items'] = tool_items
                                        if tool_items.get('tool_results'):
                                            entry['has_tool_results'] = True

                                    # Count tokens
                                    try:
                                        entry['content_tokens'] = count_message_tokens(entry)
                                    except Exception as e:
                                        entry['content_tokens'] = 0

                                    new_entries.append(entry)
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            print(f"Error reading {file} for time range: {e}")

    # Add new entries to latest_entries (protected by lock)
    if new_entries:
        with latest_entries_lock:
            latest_entries.extend(new_entries)
            # Re-sort by timestamp
            latest_entries.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
            # Keep only max_entries
            latest_entries = latest_entries[:max_entries]
        print(f"Loaded {len(new_entries)} entries from time range {start_timestamp} to {end_timestamp}")

    return len(new_entries)


def start_file_watcher():
    """Start watching all project directories and todos directory for changes"""
    observer = Observer()

    # Watch JSONL files in projects directory
    jsonl_handler = JSONLHandler()
    observer.schedule(jsonl_handler, str(CLAUDE_PROJECTS_DIR), recursive=True)

    # Watch todo JSON files in todos directory
    if CLAUDE_TODOS_DIR.exists():
        todo_handler = TodoHandler()
        observer.schedule(todo_handler, str(CLAUDE_TODOS_DIR), recursive=False)

    observer.start()
    return observer


@app.route('/')
def index():
    """Main page"""
    return render_template('index.html', max_entries=max_entries)


def format_usage_snapshot(snapshot):
    """Format usage snapshot for display (mirrors frontend logic)"""
    five_hour_pct = snapshot.get('five_hour_pct', 0) or 0
    seven_day_pct = snapshot.get('seven_day_pct', 0) or 0
    return f"📊 Usage Update: 5h: {five_hour_pct:.1f}% utilization | 7d: {seven_day_pct:.1f}% utilization"


@app.route('/api/entries')
def get_entries():
    """Get latest entries with usage snapshots merged - filtered to active session path"""
    # Take snapshot of entries (protected by lock)
    with latest_entries_lock:
        entries_snapshot = list(latest_entries)

    # Detect active sessions for fork-aware UI filtering
    active_session_ids = detect_active_sessions(entries_snapshot)

    # Filter to show only active conversation path in UI
    filtered_entries = filter_entries_by_active_sessions(entries_snapshot, active_session_ids)

    # Start with filtered log entries
    all_entries = list(filtered_entries)

    # Get time range from filtered entries
    if filtered_entries:
        timestamps = [e.get('timestamp') for e in filtered_entries if e.get('timestamp')]
        if timestamps:
            start_time = min(timestamps)
            end_time = max(timestamps)

            # Fetch snapshots in same time range
            snapshots = get_snapshots_in_range(start_time, end_time)

            # Convert snapshots to entry format
            for snapshot in snapshots:
                snapshot_entry = {
                    'type': 'usage-increment',
                    'timestamp': snapshot['timestamp'],
                    'sessionId': None,
                    'content': 'Usage Increment',
                    'content_display': format_usage_snapshot(snapshot),
                    'snapshot': snapshot,
                    '_isSnapshot': True,
                    'uuid': f"snapshot-{snapshot['id']}"
                }
                all_entries.append(snapshot_entry)

            # Sort merged list by timestamp (newest first)
            all_entries.sort(key=lambda x: x.get('timestamp', ''), reverse=True)

            # Limit to max_entries
            all_entries = all_entries[:max_entries]

    # Calculate session stats for debugging
    total_sessions = len(set(e.get('sessionId') for e in entries_snapshot if e.get('sessionId')))

    return jsonify({
        'entries': all_entries,
        'total': len(all_entries),
        'active_session_count': len(active_session_ids),
        'total_session_count': total_sessions
    })


@app.route('/api/fields')
def get_fields():
    """Get all unique fields across entries"""
    # Take snapshot of entries (protected by lock)
    with latest_entries_lock:
        entries_snapshot = list(latest_entries)

    fields = set()
    for entry in entries_snapshot:
        fields.update(entry.keys())
    return jsonify(sorted(list(fields)))


@app.route('/api/refresh')
def refresh():
    """Force refresh all entries"""
    load_latest_entries()
    with latest_entries_lock:
        total = len(latest_entries)
    return jsonify({'status': 'success', 'total': total})


@app.route('/screenshots/<path:filepath>')
def serve_screenshot(filepath):
    """Serve screenshot files from project's .claude/screenshots directory"""
    from flask import send_from_directory
    # Use project directory's .claude/screenshots, not home directory
    project_dir = Path(__file__).parent.parent  # Go up from app.py to project root
    screenshots_dir = project_dir / '.claude' / 'screenshots'
    return send_from_directory(screenshots_dir, filepath)


@app.route('/api/todos')
def get_todos():
    """Get todo files from ~/.claude/todos directory"""
    session_id = request.args.get('session_id')
    sessions_param = request.args.get('sessions')  # Comma-separated session IDs
    todos_dir = Path.home() / '.claude' / 'todos'

    if not todos_dir.exists():
        return jsonify({'todos': [], 'error': 'Todos directory not found'})

    try:
        todo_files = []

        if sessions_param:
            # Get todos for multiple sessions (comma-separated)
            session_ids = [sid.strip() for sid in sessions_param.split(',')]
            files = []
            for sid in session_ids:
                pattern = f"{sid}-agent-*.json"
                files.extend(list(todos_dir.glob(pattern)))
        elif session_id:
            # Get todos for specific session (legacy support)
            pattern = f"{session_id}-agent-*.json"
            files = list(todos_dir.glob(pattern))
        else:
            # Get all todo files
            files = list(todos_dir.glob('*-agent-*.json'))

        for file_path in files:
            try:
                # Extract session ID and agent ID from filename
                # Format: {sessionId}-agent-{agentId}.json
                filename = file_path.name
                parts = filename.replace('.json', '').split('-agent-')
                if len(parts) == 2:
                    file_session_id = parts[0]
                    agent_id = parts[1]

                    # Read file content
                    with open(file_path, 'r', encoding='utf-8') as f:
                        todos = json.loads(f.read())

                    # Get file modification time
                    mtime = file_path.stat().st_mtime
                    timestamp = datetime.fromtimestamp(mtime).isoformat()

                    # Normalize todos to list
                    todos_list = todos if isinstance(todos, list) else []

                    # Only include files with non-empty todos (skip empty arrays)
                    if len(todos_list) > 0:
                        todo_files.append({
                            'sessionId': file_session_id,
                            'agentId': agent_id,
                            'todos': todos_list,
                            'timestamp': timestamp,
                            'filename': filename
                        })
            except Exception as e:
                print(f"Error reading todo file {file_path}: {e}")
                continue

        # Sort by timestamp (newest first)
        todo_files.sort(key=lambda x: x['timestamp'], reverse=True)

        return jsonify({
            'todos': todo_files,
            'total': len(todo_files)
        })
    except Exception as e:
        return jsonify({'error': str(e), 'todos': []})


def get_oauth_token():
    """Retrieve OAuth token from macOS Keychain"""
    try:
        result = subprocess.run(
            ['security', 'find-generic-password', '-s', 'Claude Code-credentials', '-w'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            credentials = result.stdout.strip()
            # Parse JSON to extract accessToken
            try:
                creds_json = json.loads(credentials)
                token = creds_json.get('claudeAiOauth', {}).get('accessToken')
                if token:
                    return token
                else:
                    print("OAuth token not found in credentials JSON")
                    return None
            except json.JSONDecodeError:
                # If not JSON, assume it's the raw token
                return credentials
        else:
            print(f"Failed to retrieve OAuth token: {result.stderr}")
            return None
    except Exception as e:
        print(f"Error retrieving OAuth token: {e}")
        return None


def detect_active_sessions(entries):
    """
    Detect active sessions by finding leaf nodes (most recent entries in each branch)
    and tracing back through their parent chains.

    IMPORTANT: This returns sessions for UI filtering only.
    Usage tracking counts ALL branches for accurate billing.

    Args:
        entries: List of log entries

    Returns:
        set of active session IDs (includes main session and agent sessions)
    """
    if not entries:
        return set()

    # Build parent-child map and entry index
    entries_by_uuid = {}
    children_map = defaultdict(list)  # uuid -> list of child uuids

    for entry in entries:
        uuid = entry.get('uuid')
        if not uuid:
            continue

        entries_by_uuid[uuid] = entry
        parent_uuid = entry.get('parentUuid')

        if parent_uuid:
            children_map[parent_uuid].append(uuid)

    # Find ALL leaf nodes (entries with no children)
    leaf_nodes = []
    for uuid, entry in entries_by_uuid.items():
        if uuid not in children_map:  # No children = leaf node
            timestamp = entry.get('timestamp', '')
            leaf_nodes.append((uuid, timestamp))

    if not leaf_nodes:
        return set()

    # Sort leaf nodes by timestamp to find most recent branches
    leaf_nodes.sort(key=lambda x: x[1], reverse=True)

    # Take most recent leaf + any others within 60 seconds (concurrent work)
    most_recent_timestamp = leaf_nodes[0][1]
    active_leaves = [leaf_nodes[0][0]]

    for uuid, timestamp in leaf_nodes[1:]:
        if timestamp and most_recent_timestamp:
            try:
                recent_dt = datetime.fromisoformat(most_recent_timestamp.replace('Z', '+00:00'))
                leaf_dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))

                if recent_dt - leaf_dt <= timedelta(seconds=60):
                    active_leaves.append(uuid)
            except:
                pass

    # Trace back through parent chains from active leaves
    active_uuids = set()
    to_visit = list(active_leaves)

    while to_visit:
        current_uuid = to_visit.pop()

        if not current_uuid or current_uuid in active_uuids:
            continue  # Prevents circular references

        active_uuids.add(current_uuid)

        entry = entries_by_uuid.get(current_uuid)
        if not entry:
            continue

        # Follow parentUuid backward
        parent_uuid = entry.get('parentUuid')
        if parent_uuid:
            to_visit.append(parent_uuid)

        # Also follow logicalParentUuid (cross-session links)
        logical_parent_uuid = entry.get('logicalParentUuid')
        if logical_parent_uuid:
            to_visit.append(logical_parent_uuid)

    # Extract session IDs from active entries
    active_session_ids = set()
    for uuid in active_uuids:
        entry = entries_by_uuid.get(uuid)
        if entry:
            session_id = entry.get('sessionId')
            if session_id:
                active_session_ids.add(session_id)

    return active_session_ids


def filter_entries_by_active_sessions(entries, active_session_ids):
    """
    Filter entries to only include those from active session path.

    Used for UI display to show users their current conversation context.
    NOT used for usage tracking (which needs all entries for accurate billing).

    Args:
        entries: List of log entries
        active_session_ids: Set of active session IDs from detect_active_sessions()

    Returns:
        Filtered list of entries from active sessions only
    """
    if not active_session_ids:
        return entries

    return [
        entry for entry in entries
        if entry.get('sessionId') in active_session_ids
    ]


def calculate_increment_stats(baseline_timestamp, active_session_ids=None):
    """
    Calculate tokens consumed and message count since baseline timestamp.

    IMPORTANT: This counts ALL tokens from ALL branches for accurate billing tracking.
    Claude API processes and bills for all conversation attempts, including abandoned forks.
    The active_session_ids parameter is DEPRECATED and ignored (kept for backward compatibility).

    Args:
        baseline_timestamp: ISO timestamp string to calculate from, or None
        active_session_ids: DEPRECATED - no longer used, counts all sessions

    Returns:
        dict with 'tokens' and 'messages' keys
    """
    if baseline_timestamp is None:
        return {'tokens': 0, 'messages': 0}

    total_tokens = 0
    message_count = 0

    # Take snapshot of entries (protected by lock)
    with latest_entries_lock:
        entries_snapshot = list(latest_entries)

    # CORRECT: Query ALL entries since baseline (no session filtering)
    # This accurately reflects what Claude API actually processed and billed
    for entry in entries_snapshot:
        entry_timestamp = entry.get('timestamp', '')
        if entry_timestamp and entry_timestamp >= baseline_timestamp:
            # NO FILTERING - count all tokens from all branches
            content_tokens = entry.get('content_tokens', 0)
            if content_tokens:
                total_tokens += content_tokens
            message_count += 1

    return {
        'tokens': total_tokens,
        'messages': message_count
    }


def calculate_windowed_totals(reset_time, window_hours):
    """
    Calculate total tokens and messages within a time window using database query.

    Args:
        reset_time: ISO timestamp string when the window resets (in the future)
        window_hours: Window duration in hours (5 for 5-hour, 168 for 7-day)

    Returns:
        dict with 'total_tokens' and 'total_messages' keys
    """
    if not reset_time:
        return {'total_tokens': 0, 'total_messages': 0}

    try:
        # Parse reset time and calculate window start
        reset_dt = datetime.fromisoformat(reset_time.replace('Z', '+00:00'))
        window_start = (reset_dt - timedelta(hours=window_hours)).isoformat().replace('+00:00', 'Z')

        # Query database for sum of deltas within window
        with get_db() as conn:
            cursor = conn.cursor()

            if window_hours == 5:
                cursor.execute("""
                    SELECT
                        COALESCE(SUM(five_hour_tokens_consumed), 0) as total_tokens,
                        COALESCE(SUM(five_hour_messages_count), 0) as total_messages
                    FROM usage_snapshots
                    WHERE timestamp >= ?
                      AND timestamp <= ?
                      AND five_hour_tokens_consumed IS NOT NULL
                """, (window_start, reset_time))
            else:  # 7-day window (168 hours)
                cursor.execute("""
                    SELECT
                        COALESCE(SUM(seven_day_tokens_consumed), 0) as total_tokens,
                        COALESCE(SUM(seven_day_messages_count), 0) as total_messages
                    FROM usage_snapshots
                    WHERE timestamp >= ?
                      AND timestamp <= ?
                      AND seven_day_tokens_consumed IS NOT NULL
                """, (window_start, reset_time))

            result = cursor.fetchone()
            return {
                'total_tokens': result['total_tokens'],
                'total_messages': result['total_messages']
            }
    except Exception as e:
        print(f"Error calculating windowed totals: {e}")
        return {'total_tokens': 0, 'total_messages': 0}


def calculate_and_update_snapshot(
    snapshot_id: int,
    five_hour_increased: bool,
    seven_day_increased: bool,
    five_hour_reset_detected: bool,
    seven_day_reset_detected: bool,
    five_hour_reset_time: str,
    seven_day_reset_time: str,
    prev_snapshot: dict
):
    """
    Calculate deltas and totals for a snapshot and update the database.

    This is Phase 2 of the two-phase flow:
    1. API tick already stored (by insert_snapshot_tick)
    2. Now calculate deltas/totals and update

    Args:
        snapshot_id: ID of the snapshot to update
        five_hour_increased: True if 5-hour window usage increased
        seven_day_increased: True if 7-day window usage increased
        five_hour_reset_detected: True if 5-hour window was reset
        seven_day_reset_detected: True if 7-day window was reset
        five_hour_reset_time: ISO timestamp when 5-hour window resets
        seven_day_reset_time: ISO timestamp when 7-day window resets
        prev_snapshot: Previous snapshot dict for baseline reference
    """
    # Get baseline timestamp from previous snapshot
    baseline_timestamp = prev_snapshot.get('timestamp') if prev_snapshot else None

    # Load entries for calculation if we have a baseline
    if baseline_timestamp:
        load_entries_for_time_range(baseline_timestamp)

    # Take snapshot of entries for calculation
    with latest_entries_lock:
        entries_snapshot = list(latest_entries)

    # Detect active sessions (for fork-aware filtering)
    active_session_ids = detect_active_sessions(entries_snapshot)
    print(f"🔍 Fork detection: {len(active_session_ids)} active sessions found")

    # Initialize calculation results
    five_hour_delta_tokens = None
    five_hour_delta_messages = None
    five_hour_total_tokens = None
    five_hour_total_messages = None
    seven_day_delta_tokens = None
    seven_day_delta_messages = None
    seven_day_total_tokens = None
    seven_day_total_messages = None

    # Calculate 5-hour window if it changed
    if five_hour_increased or five_hour_reset_detected:
        # Calculate delta using usage_calculator
        delta_result = calculate_delta(entries_snapshot, baseline_timestamp, active_session_ids)
        five_hour_delta_tokens = delta_result['tokens']
        five_hour_delta_messages = delta_result['messages']

        # Calculate total using incremental approach
        prev_tokens = prev_snapshot.get('five_hour_tokens_total', 0) if prev_snapshot else 0
        prev_messages = prev_snapshot.get('five_hour_messages_total', 0) if prev_snapshot else 0

        five_hour_total_tokens, five_hour_total_messages = calculate_total_incremental(
            prev_tokens or 0,
            prev_messages or 0,
            five_hour_delta_tokens,
            five_hour_delta_messages,
            five_hour_reset_detected
        )

        print(f"  📊 5h window: Counted {five_hour_delta_messages} messages, {five_hour_delta_tokens} tokens (delta)")
    else:
        # Window didn't change - preserve previous totals (default to 0 if NULL)
        if prev_snapshot:
            five_hour_total_tokens = prev_snapshot.get('five_hour_tokens_total', 0) or 0
            five_hour_total_messages = prev_snapshot.get('five_hour_messages_total', 0) or 0

    # Calculate 7-day window if it changed
    if seven_day_increased or seven_day_reset_detected:
        # Calculate delta using usage_calculator
        delta_result = calculate_delta(entries_snapshot, baseline_timestamp, active_session_ids)
        seven_day_delta_tokens = delta_result['tokens']
        seven_day_delta_messages = delta_result['messages']

        # Calculate total using incremental approach
        prev_tokens = prev_snapshot.get('seven_day_tokens_total', 0) if prev_snapshot else 0
        prev_messages = prev_snapshot.get('seven_day_messages_total', 0) if prev_snapshot else 0

        seven_day_total_tokens, seven_day_total_messages = calculate_total_incremental(
            prev_tokens or 0,
            prev_messages or 0,
            seven_day_delta_tokens,
            seven_day_delta_messages,
            seven_day_reset_detected
        )

        print(f"  📊 7d window: Counted {seven_day_delta_messages} messages, {seven_day_delta_tokens} tokens (delta)")
    else:
        # Window didn't change - preserve previous totals (default to 0 if NULL)
        if prev_snapshot:
            seven_day_total_tokens = prev_snapshot.get('seven_day_tokens_total', 0) or 0
            seven_day_total_messages = prev_snapshot.get('seven_day_messages_total', 0) or 0

    # Update snapshot with calculated values
    update_snapshot_calculations(
        snapshot_id=snapshot_id,
        five_hour_tokens_consumed=five_hour_delta_tokens,
        five_hour_messages_count=five_hour_delta_messages,
        seven_day_tokens_consumed=seven_day_delta_tokens,
        seven_day_messages_count=seven_day_delta_messages,
        five_hour_tokens_total=five_hour_total_tokens,
        five_hour_messages_total=five_hour_total_messages,
        seven_day_tokens_total=seven_day_total_tokens,
        seven_day_messages_total=seven_day_total_messages,
        active_sessions=list(active_session_ids)
    )

    print(f"📊 Usage snapshot updated: 5h total={five_hour_total_messages} msgs (+{five_hour_delta_messages} delta), 7d total={seven_day_total_messages} msgs (+{seven_day_delta_messages} delta)")


def fetch_usage_data():
    """Fetch usage data from Anthropic OAuth API and track increments"""
    global usage_cache, previous_usage

    # Check cache
    current_time = time.time()
    if usage_cache['data'] and (current_time - usage_cache['timestamp']) < usage_cache['cache_duration']:
        return usage_cache['data']

    # Get OAuth token
    token = get_oauth_token()
    if not token:
        return {'error': 'Failed to retrieve OAuth token from Keychain'}

    # Make API request
    try:
        response = requests.get(
            'https://api.anthropic.com/api/oauth/usage',
            headers={
                'Authorization': f'Bearer {token}',
                'anthropic-beta': 'oauth-2025-04-20',
                'User-Agent': 'claude-code/2.0.32'
            },
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()

            # Extract usage values (API returns utilization as percentage 0-100)
            five_hour_util = data.get('five_hour', {}).get('utilization', 0)
            seven_day_util = data.get('seven_day', {}).get('utilization', 0)

            # Check if usage has increased and which windows changed
            should_snapshot = False
            five_hour_increased = False
            seven_day_increased = False
            five_hour_reset_detected = False
            seven_day_reset_detected = False

            if previous_usage['five_hour_used'] is not None or previous_usage['seven_day_used'] is not None:
                if previous_usage['five_hour_used'] is not None:
                    if five_hour_util > previous_usage['five_hour_used']:
                        should_snapshot = True
                        five_hour_increased = True
                    elif five_hour_util < previous_usage['five_hour_used']:
                        # Usage dropped - window was reset
                        should_snapshot = True
                        five_hour_reset_detected = True

                if previous_usage['seven_day_used'] is not None:
                    if seven_day_util > previous_usage['seven_day_used']:
                        should_snapshot = True
                        seven_day_increased = True
                    elif seven_day_util < previous_usage['seven_day_used']:
                        # Usage dropped - window was reset
                        should_snapshot = True
                        seven_day_reset_detected = True

            # Store snapshot if usage increased or window was reset
            if should_snapshot:
                try:
                    five_hour_window = data.get('five_hour', {})
                    seven_day_window = data.get('seven_day', {})

                    # Get reset times from API response
                    five_hour_reset_time = five_hour_window.get('resets_at')
                    seven_day_reset_time = seven_day_window.get('resets_at')

                    # Get previous snapshot for baseline reference
                    prev_snapshot = get_latest_snapshot()

                    # PHASE 1: Store API tick immediately (no calculations yet)
                    snapshot_id = insert_snapshot_tick(
                        timestamp=datetime.utcnow().isoformat() + 'Z',
                        five_hour_used=int(five_hour_util),
                        five_hour_limit=100,
                        seven_day_used=int(seven_day_util),
                        seven_day_limit=100,
                        five_hour_pct=five_hour_util,
                        seven_day_pct=seven_day_util,
                        five_hour_reset=five_hour_reset_time,
                        seven_day_reset=seven_day_reset_time
                    )
                    print(f"📝 API tick stored: snapshot_id={snapshot_id}, 5h={five_hour_util}%, 7d={seven_day_util}%")

                    # PHASE 2: Calculate deltas and totals, then update snapshot
                    calculate_and_update_snapshot(
                        snapshot_id=snapshot_id,
                        five_hour_increased=five_hour_increased,
                        seven_day_increased=seven_day_increased,
                        five_hour_reset_detected=five_hour_reset_detected,
                        seven_day_reset_detected=seven_day_reset_detected,
                        five_hour_reset_time=five_hour_reset_time,
                        seven_day_reset_time=seven_day_reset_time,
                        prev_snapshot=prev_snapshot
                    )

                except Exception as e:
                    print(f"Error saving usage snapshot: {e}")
                    import traceback
                    traceback.print_exc()

            # Update previous usage values
            previous_usage['five_hour_used'] = five_hour_util
            previous_usage['seven_day_used'] = seven_day_util

            # Update cache
            usage_cache['data'] = data
            usage_cache['timestamp'] = current_time
            return data
        else:
            return {'error': f'API returned status {response.status_code}', 'details': response.text}

    except Exception as e:
        return {'error': str(e)}


@app.route('/api/usage')
def get_usage():
    """Get Claude Code usage statistics"""
    data = fetch_usage_data()
    return jsonify(data)


@app.route('/api/usage-snapshots')
def get_usage_snapshots():
    """Get usage snapshots within a time range"""
    start_time = request.args.get('start')
    end_time = request.args.get('end')

    if not start_time or not end_time:
        return jsonify({'error': 'start and end parameters are required'}), 400

    try:
        snapshots = get_snapshots_in_range(start_time, end_time)
        return jsonify({
            'snapshots': snapshots,
            'total': len(snapshots)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/timeline')
def get_timeline():
    """Get conversation timeline graph for visualization"""
    session_id = request.args.get('session_id')

    try:
        # Take snapshot of entries (protected by lock)
        with latest_entries_lock:
            entries_snapshot = list(latest_entries)

        # Filter entries by session if specified
        entries_to_analyze = entries_snapshot
        if session_id:
            entries_to_analyze = [e for e in entries_snapshot
                                 if e.get('sessionId') == session_id]

        # Build timeline graph
        timeline_data = build_timeline(entries_to_analyze)

        return jsonify(timeline_data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/sessions/<session_id>/checkpoint', methods=['POST'])
def create_checkpoint_api(session_id):
    """
    Create a manual checkpoint for a session.

    Request body (JSON):
    {
        "description": "Optional description",
        "message_uuid": "Optional message UUID"
    }
    """
    try:
        # Check if git management is enabled
        if not get_setting('git_enabled', False):
            return jsonify({
                'success': False,
                'error': 'Git management is disabled. Enable it in settings first.'
            }), 403

        # Get project directory if targeting specific project
        project_dir = CLAUDE_PROJECTS_DIR if target_project else None

        # Create git manager with database connection
        with get_db() as db:
            git_manager = GitRollbackManager(project_dir=project_dir, db_connection=db)

            # Get request data
            data = request.get_json() or {}
            description = data.get('description')
            message_uuid = data.get('message_uuid')

            # Create checkpoint
            result = git_manager.create_checkpoint(
                session_uuid=session_id,
                checkpoint_type='manual',
                message_uuid=message_uuid,
                description=description
            )

            if result['success']:
                return jsonify(result), 201
            else:
                return jsonify(result), 400

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/sessions/<session_id>/checkpoints', methods=['GET'])
def list_checkpoints_api(session_id):
    """Get all checkpoints for a session."""
    try:
        # Check if git management is enabled
        if not get_setting('git_enabled', False):
            return jsonify({
                'session_id': session_id,
                'checkpoints': [],
                'count': 0,
                'git_disabled': True
            })

        project_dir = CLAUDE_PROJECTS_DIR if target_project else None

        with get_db() as db:
            git_manager = GitRollbackManager(project_dir=project_dir, db_connection=db)
            checkpoints = git_manager.list_checkpoints(session_uuid=session_id)

            return jsonify({
                'session_id': session_id,
                'checkpoints': checkpoints,
                'count': len(checkpoints)
            })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/sessions/<session_id>/commits', methods=['GET'])
def list_commits_api(session_id):
    """Get all git commits for a session."""
    try:
        limit = int(request.args.get('limit', 50))
        project_dir = CLAUDE_PROJECTS_DIR if target_project else None

        with get_db() as db:
            git_manager = GitRollbackManager(project_dir=project_dir, db_connection=db)
            commits = git_manager.list_commits(session_uuid=session_id, limit=limit)

            return jsonify({
                'session_id': session_id,
                'commits': commits,
                'count': len(commits)
            })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/git/status', methods=['GET'])
def git_status_api():
    """Get git repository status."""
    try:
        project_dir = CLAUDE_PROJECTS_DIR if target_project else None

        with get_db() as db:
            git_manager = GitRollbackManager(project_dir=project_dir, db_connection=db)
            status = git_manager.get_repo_status()

            return jsonify(status)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/messages/<message_uuid>/checkpoints', methods=['GET'])
def list_message_checkpoints_api(message_uuid):
    """Get all checkpoints associated with a specific message."""
    try:
        project_dir = CLAUDE_PROJECTS_DIR if target_project else None

        with get_db() as db:
            git_manager = GitRollbackManager(project_dir=project_dir, db_connection=db)
            checkpoints = git_manager.list_checkpoints(message_uuid=message_uuid)

            return jsonify({
                'message_uuid': message_uuid,
                'checkpoints': checkpoints,
                'count': len(checkpoints)
            })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/settings', methods=['GET'])
def get_settings_api():
    """Get all settings."""
    try:
        settings = get_all_settings()
        return jsonify(settings)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/settings/<key>', methods=['GET'])
def get_setting_api(key):
    """Get a specific setting."""
    try:
        value = get_setting(key)
        return jsonify({'key': key, 'value': value})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/settings/<key>', methods=['POST'])
def set_setting_api(key):
    """
    Set a setting value.

    Request body (JSON):
    {
        "value": <value>
    }
    """
    try:
        data = request.get_json()
        if 'value' not in data:
            return jsonify({'error': 'Missing value in request body'}), 400

        set_setting(key, data['value'])

        return jsonify({
            'success': True,
            'key': key,
            'value': data['value']
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def main():
    """Main entry point for the CLI"""
    global max_entries, file_age_days

    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='Claude Code Log Viewer - Interactive web-based transcript viewer'
    )
    parser.add_argument(
        '--reset-db',
        action='store_true',
        help='Reset the database by deleting and recreating it'
    )
    parser.add_argument(
        '--days',
        type=int,
        default=2,
        help='Only load files modified in the last N days (default: 2)'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=500,
        help='Maximum number of entries to keep in memory (default: 500)'
    )
    parser.add_argument(
        '--project',
        type=str,
        help='Target specific project directory (isolates JSONL processing and git operations)'
    )
    args = parser.parse_args()

    # Set global configuration from arguments
    global target_project, CLAUDE_PROJECTS_DIR
    file_age_days = args.days
    max_entries = args.limit

    # Handle project isolation
    if args.project:
        target_project = args.project
        project_path = CLAUDE_PROJECTS_DIR / target_project
        if not project_path.exists():
            print(f"ERROR: Project directory not found: {project_path}")
            print(f"Available projects:")
            if CLAUDE_PROJECTS_DIR.exists():
                for p in sorted(CLAUDE_PROJECTS_DIR.iterdir()):
                    if p.is_dir():
                        print(f"  - {p.name}")
            import sys
            sys.exit(1)
        print(f"🎯 Targeting project: {target_project}")
        print(f"   Project path: {project_path}")
        # Override CLAUDE_PROJECTS_DIR for this session
        CLAUDE_PROJECTS_DIR = project_path

    # Handle database reset
    if args.reset_db:
        if os.path.exists(DB_PATH):
            print(f"Resetting database at {DB_PATH}...")
            os.remove(DB_PATH)
            print("Database deleted.")
        else:
            print(f"No database found at {DB_PATH}")

    # Initialize database
    print(f"Initializing database at {DB_PATH}...")
    init_db()

    # Initialize previous usage from latest snapshot
    latest_snapshot = get_latest_snapshot()
    if latest_snapshot:
        previous_usage['five_hour_used'] = latest_snapshot['five_hour_used']
        previous_usage['seven_day_used'] = latest_snapshot['seven_day_used']
        print(f"Loaded previous usage: 5h={previous_usage['five_hour_used']}, 7d={previous_usage['seven_day_used']}")

    # Initial load
    print(f"Loading JSONL files from: {CLAUDE_PROJECTS_DIR}")
    load_latest_entries()
    with latest_entries_lock:
        total = len(latest_entries)
    print(f"Loaded {total} entries")

    # Start file watcher in background
    observer = start_file_watcher()
    print("Started file watcher")

    try:
        # Run Flask app
        print("Starting web server at http://localhost:5001")
        app.run(host='0.0.0.0', port=5001, debug=True, use_reloader=False)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == '__main__':
    main()
