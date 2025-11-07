#!/usr/bin/env python3
"""
JSONL Log Viewer - Real-time viewer for Claude Code transcripts
"""

from flask import Flask, render_template, jsonify, request
from pathlib import Path
import json
import os
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import threading
import time
import subprocess
import requests
import argparse
from .database import init_db, insert_snapshot, get_snapshots_in_range, get_latest_snapshot, insert_session, DB_PATH
from .token_counter import count_message_tokens

app = Flask(__name__)

# Get the Claude projects directory - monitor all projects
CLAUDE_PROJECTS_DIR = Path.home() / '.claude' / 'projects'

# Store latest entries
latest_entries = []
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
                            entry['_file'] = file.name
                            entry['_file_path'] = str(file)

                            # Enrich content for display
                            entry['content_display'] = enrich_content(entry)

                            # Extract tool items for detailed viewing
                            tool_items = extract_tool_items(entry)
                            if tool_items:
                                entry['tool_items'] = tool_items

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

    # Keep only the latest entries
    latest_entries = entries[:max_entries]


def start_file_watcher():
    """Start watching all project directories for changes"""
    event_handler = JSONLHandler()
    observer = Observer()
    observer.schedule(event_handler, str(CLAUDE_PROJECTS_DIR), recursive=True)
    observer.start()
    return observer


@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')


@app.route('/api/entries')
def get_entries():
    """Get latest entries"""
    return jsonify({
        'entries': latest_entries,
        'total': len(latest_entries)
    })


@app.route('/api/fields')
def get_fields():
    """Get all unique fields across entries"""
    fields = set()
    for entry in latest_entries:
        fields.update(entry.keys())
    return jsonify(sorted(list(fields)))


@app.route('/api/refresh')
def refresh():
    """Force refresh all entries"""
    load_latest_entries()
    return jsonify({'status': 'success', 'total': len(latest_entries)})


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

            # Check if usage has increased
            should_snapshot = False
            if previous_usage['five_hour_used'] is not None or previous_usage['seven_day_used'] is not None:
                if (previous_usage['five_hour_used'] is not None and five_hour_util > previous_usage['five_hour_used']) or \
                   (previous_usage['seven_day_used'] is not None and seven_day_util > previous_usage['seven_day_used']):
                    should_snapshot = True

            # Store snapshot if usage increased
            if should_snapshot:
                try:
                    five_hour_window = data.get('five_hour', {})
                    seven_day_window = data.get('seven_day', {})

                    insert_snapshot(
                        timestamp=datetime.utcnow().isoformat() + 'Z',
                        five_hour_used=int(five_hour_util),  # Store as integer percentage
                        five_hour_limit=100,  # API returns percentage, so limit is 100%
                        seven_day_used=int(seven_day_util),  # Store as integer percentage
                        seven_day_limit=100,  # API returns percentage, so limit is 100%
                        five_hour_pct=five_hour_util,
                        seven_day_pct=seven_day_util,
                        five_hour_reset=five_hour_window.get('resets_at'),
                        seven_day_reset=seven_day_window.get('resets_at')
                    )
                    print(f"📊 Usage snapshot saved: 5h={five_hour_util}%, 7d={seven_day_util}%")
                except Exception as e:
                    print(f"Error saving usage snapshot: {e}")

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
    args = parser.parse_args()

    # Set global configuration from arguments
    file_age_days = args.days
    max_entries = args.limit

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
    print(f"Loaded {len(latest_entries)} entries")

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
