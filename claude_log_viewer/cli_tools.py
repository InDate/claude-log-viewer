#!/usr/bin/env python3
"""CLI tools for searching Claude JSONL log files.

Usage:
    claude-log-tools search "pattern" [--project NAME] [--days N] [-i]
    claude-log-tools count [--project NAME] [--days N]
    claude-log-tools sessions [--project NAME] [--days N]
"""

import argparse
import json
import re
import sys
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

CLAUDE_PROJECTS_DIR = Path.home() / '.claude' / 'projects'


def get_jsonl_files(project=None, days=7):
    """Get JSONL files matching criteria.

    Args:
        project: Project name filter (substring match)
        days: Only include files modified within N days

    Returns:
        List of Path objects
    """
    if not CLAUDE_PROJECTS_DIR.exists():
        print(f"Error: Claude projects directory not found: {CLAUDE_PROJECTS_DIR}", file=sys.stderr)
        return []

    cutoff_time = datetime.now().timestamp() - (days * 24 * 60 * 60)
    files = []

    for jsonl_file in CLAUDE_PROJECTS_DIR.glob('**/*.jsonl'):
        # Filter by modification time
        if jsonl_file.stat().st_mtime < cutoff_time:
            continue

        # Filter by project name if specified
        if project:
            # Project name is in the parent directory name
            project_dir = jsonl_file.parent.name
            if project.lower() not in project_dir.lower():
                continue

        files.append(jsonl_file)

    return sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)


def search_jsonl(pattern, project=None, days=7, case_sensitive=False, limit=50):
    """Search JSONL files for a pattern.

    Args:
        pattern: Regex pattern to search for
        project: Project name filter
        days: Only search files modified within N days
        case_sensitive: Whether search is case-sensitive
        limit: Maximum number of results to return

    Returns:
        List of matching entries with metadata
    """
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        print(f"Invalid regex pattern: {e}", file=sys.stderr)
        return []

    files = get_jsonl_files(project, days)
    results = []

    for jsonl_file in files:
        project_name = jsonl_file.parent.name

        try:
            with open(jsonl_file, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue

                    # Quick string check before JSON parsing
                    if not regex.search(line):
                        continue

                    try:
                        entry = json.loads(line)
                        results.append({
                            'file': str(jsonl_file),
                            'project': project_name,
                            'line': line_num,
                            'timestamp': entry.get('timestamp', ''),
                            'sessionId': entry.get('sessionId', ''),
                            'type': entry.get('type', ''),
                            'uuid': entry.get('uuid', ''),
                            'entry': entry
                        })

                        if len(results) >= limit:
                            return results
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            print(f"Error reading {jsonl_file}: {e}", file=sys.stderr)

    return results


def count_entries(project=None, days=7):
    """Count entries per session/file.

    Args:
        project: Project name filter
        days: Only count files modified within N days

    Returns:
        Dict with counts by session and project
    """
    files = get_jsonl_files(project, days)

    stats = {
        'total_files': len(files),
        'total_entries': 0,
        'by_project': defaultdict(int),
        'by_session': defaultdict(int),
        'by_type': defaultdict(int)
    }

    for jsonl_file in files:
        project_name = jsonl_file.parent.name

        try:
            with open(jsonl_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        entry = json.loads(line)
                        stats['total_entries'] += 1
                        stats['by_project'][project_name] += 1

                        session_id = entry.get('sessionId', 'unknown')
                        if session_id:
                            stats['by_session'][session_id] += 1

                        entry_type = entry.get('type', 'unknown')
                        stats['by_type'][entry_type] += 1
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            print(f"Error reading {jsonl_file}: {e}", file=sys.stderr)

    return stats


def list_sessions(project=None, days=7):
    """List sessions with metadata.

    Args:
        project: Project name filter
        days: Only include files modified within N days

    Returns:
        List of session info dicts
    """
    files = get_jsonl_files(project, days)

    sessions = defaultdict(lambda: {
        'count': 0,
        'first_timestamp': None,
        'last_timestamp': None,
        'project': None,
        'files': set()
    })

    for jsonl_file in files:
        project_name = jsonl_file.parent.name

        try:
            with open(jsonl_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        entry = json.loads(line)
                        session_id = entry.get('sessionId')
                        if not session_id:
                            continue

                        sessions[session_id]['count'] += 1
                        sessions[session_id]['project'] = project_name
                        sessions[session_id]['files'].add(str(jsonl_file))

                        timestamp = entry.get('timestamp', '')
                        if timestamp:
                            if not sessions[session_id]['first_timestamp'] or timestamp < sessions[session_id]['first_timestamp']:
                                sessions[session_id]['first_timestamp'] = timestamp
                            if not sessions[session_id]['last_timestamp'] or timestamp > sessions[session_id]['last_timestamp']:
                                sessions[session_id]['last_timestamp'] = timestamp
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            print(f"Error reading {jsonl_file}: {e}", file=sys.stderr)

    # Convert to list and sort by last activity
    result = []
    for session_id, info in sessions.items():
        result.append({
            'sessionId': session_id,
            'count': info['count'],
            'project': info['project'],
            'first': info['first_timestamp'],
            'last': info['last_timestamp'],
            'files': len(info['files'])
        })

    result.sort(key=lambda x: x['last'] or '', reverse=True)
    return result


def cmd_search(args):
    """Handle search command."""
    results = search_jsonl(
        args.pattern,
        project=args.project,
        days=args.days,
        case_sensitive=not args.i,
        limit=args.limit
    )

    if not results:
        print("No matches found.")
        return 1

    print(f"Found {len(results)} match(es):\n")

    for r in results:
        print(f"  [{r['timestamp'][:19] if r['timestamp'] else 'no-timestamp'}] {r['type']}")
        print(f"    Session: {r['sessionId'][:20]}..." if r['sessionId'] else "    Session: unknown")
        print(f"    Project: {r['project']}")
        print(f"    File: {r['file']}:{r['line']}")
        print()

    return 0


def cmd_count(args):
    """Handle count command."""
    stats = count_entries(project=args.project, days=args.days)

    print(f"Total files: {stats['total_files']}")
    print(f"Total entries: {stats['total_entries']}")
    print()

    print("By project:")
    for project, count in sorted(stats['by_project'].items(), key=lambda x: -x[1])[:10]:
        print(f"  {project}: {count}")

    print()
    print("By type:")
    for entry_type, count in sorted(stats['by_type'].items(), key=lambda x: -x[1]):
        print(f"  {entry_type}: {count}")

    return 0


def cmd_sessions(args):
    """Handle sessions command."""
    sessions = list_sessions(project=args.project, days=args.days)

    if not sessions:
        print("No sessions found.")
        return 1

    print(f"Found {len(sessions)} session(s):\n")

    for s in sessions[:args.limit]:
        print(f"  {s['sessionId'][:20]}...")
        print(f"    Entries: {s['count']}, Files: {s['files']}")
        print(f"    Project: {s['project']}")
        print(f"    First: {s['first'][:19] if s['first'] else 'unknown'}")
        print(f"    Last: {s['last'][:19] if s['last'] else 'unknown'}")
        print()

    return 0


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='CLI tools for searching Claude JSONL log files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  claude-log-tools search "EXPERT-UIUX-REVIEW" --project inference-engine
  claude-log-tools search "error" -i --days 1
  claude-log-tools count --project claude-log-viewer
  claude-log-tools sessions --days 7
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # Search command
    search_p = subparsers.add_parser('search', help='Search JSONL files for a pattern')
    search_p.add_argument('pattern', help='Regex pattern to search for')
    search_p.add_argument('--project', '-p', help='Filter by project name (substring match)')
    search_p.add_argument('--days', '-d', type=int, default=7, help='Search files modified within N days (default: 7)')
    search_p.add_argument('-i', action='store_true', help='Case insensitive search')
    search_p.add_argument('--limit', '-l', type=int, default=50, help='Maximum results to return (default: 50)')

    # Count command
    count_p = subparsers.add_parser('count', help='Count entries per session/project')
    count_p.add_argument('--project', '-p', help='Filter by project name (substring match)')
    count_p.add_argument('--days', '-d', type=int, default=7, help='Count files modified within N days (default: 7)')

    # Sessions command
    sessions_p = subparsers.add_parser('sessions', help='List sessions with metadata')
    sessions_p.add_argument('--project', '-p', help='Filter by project name (substring match)')
    sessions_p.add_argument('--days', '-d', type=int, default=7, help='Include files modified within N days (default: 7)')
    sessions_p.add_argument('--limit', '-l', type=int, default=20, help='Maximum sessions to show (default: 20)')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    if args.command == 'search':
        return cmd_search(args)
    elif args.command == 'count':
        return cmd_count(args)
    elif args.command == 'sessions':
        return cmd_sessions(args)

    return 0


if __name__ == '__main__':
    sys.exit(main())
