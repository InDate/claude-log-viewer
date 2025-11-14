"""
Snapshot Pipeline - Unified snapshot creation and calculation engine.

This module provides the backend pipeline for creating usage snapshots and
calculating token/message usage using the ccusage methodology.

Architecture:
1. API poller calls trigger_snapshot_calculation() with usage data
2. Pipeline loads JSONL entries from ~/.claude/projects
3. Calculates usage using ccusage token counting (token_utils)
4. Updates snapshot with calculated values
5. Returns results for frontend display

This replaces frontend-driven calculations with backend-driven automatic processing.
"""
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Set, Any, Tuple, Optional

from .token_utils import extract_tokens_from_entry
from .database import (
    insert_snapshot_tick,
    update_snapshot_calculations,
    get_db,
    get_snapshot_by_id
)


# Configuration
CLAUDE_PROJECTS_DIR = Path.home() / '.claude' / 'projects'


def normalize_reset_time(reset_time_str: str) -> str:
    """
    Normalize reset time to the top of the hour (:00).
    
    The Claude API sometimes returns :59 or :00 for the same hour boundary,
    causing jitter in reset times. This function rounds to :00 for consistency.
    
    Args:
        reset_time_str: ISO format timestamp string (e.g., "2024-11-14T04:00:00.000Z")
    
    Returns:
        Normalized ISO format timestamp string with minutes/seconds set to :00
    
    Example:
        "2024-11-14T03:59:59.999Z" -> "2024-11-14T04:00:00.000Z"
        "2024-11-14T04:00:00.123Z" -> "2024-11-14T04:00:00.000Z"
    """
    # Parse the timestamp
    dt = datetime.fromisoformat(reset_time_str.replace('Z', '+00:00'))
    
    # Round to nearest hour
    if dt.minute >= 30:
        # Round up to next hour
        dt = dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        # Round down to current hour
        dt = dt.replace(minute=0, second=0, microsecond=0)
    
    # Return in ISO format with Z suffix
    return dt.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def get_previous_snapshot(current_snapshot_id: int) -> Optional[Dict]:
    """
    Get the snapshot immediately before the current one.

    Args:
        current_snapshot_id: ID of current snapshot

    Returns:
        Previous snapshot dictionary or None if this is the first snapshot
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM usage_snapshots
            WHERE id < ?
            ORDER BY id DESC
            LIMIT 1
        """, (current_snapshot_id,))

        row = cursor.fetchone()
        return dict(row) if row else None


def trigger_snapshot_calculation(usage_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main entry point called by api_poller when usage data is received.

    This function orchestrates the entire snapshot pipeline:
    1. Creates snapshot in database (Phase 1)
    2. Loads JSONL entries from ~/.claude/projects
    3. Calculates usage using ccusage methodology
    4. Updates snapshot with calculated values (Phase 2)
    5. Returns results

    Args:
        usage_data: Claude API response data containing:
            - timestamp: ISO timestamp for this snapshot
            - five_hour: {tokens_consumed, messages_count, tokens_limit, messages_limit, pct, reset}
            - seven_day: {tokens_consumed, messages_count, tokens_limit, messages_limit, pct, reset}

    Returns:
        Dictionary with:
        - snapshot_id: Database ID of created snapshot
        - timestamp: ISO timestamp
        - api_data: Original API data
        - calculated: Calculated usage values
        - active_sessions: List of active session IDs

    Example:
        >>> usage_data = {
        ...     'timestamp': '2025-11-12T10:00:00Z',
        ...     'five_hour': {
        ...         'tokens_consumed': 12345,
        ...         'messages_count': 67,
        ...         'tokens_limit': 100000,
        ...         'messages_limit': 1000,
        ...         'pct': 12.3,
        ...         'reset': '2025-11-12T15:00:00Z'
        ...     },
        ...     'seven_day': {...}
        ... }
        >>> result = trigger_snapshot_calculation(usage_data)
        >>> result['snapshot_id']
        12345
    """
    timestamp = usage_data.get('timestamp')
    if not timestamp:
        raise ValueError("usage_data must contain 'timestamp' field")

    # Parse timestamp
    snapshot_time = parse_timestamp(timestamp)

    # Extract API data
    five_hour = usage_data.get('five_hour', {})
    seven_day = usage_data.get('seven_day', {})

    # Normalize reset times to eliminate API jitter
    # The API returns times like "03:59:59.xxx" and "04:00:00.xxx" that should be the same window
    five_hour_reset_raw = five_hour.get('reset')
    seven_day_reset_raw = seven_day.get('reset')

    five_hour_reset = normalize_reset_time(five_hour_reset_raw) if five_hour_reset_raw else None
    seven_day_reset = normalize_reset_time(seven_day_reset_raw) if seven_day_reset_raw else None

    # Phase 1: Create snapshot with API data only
    snapshot_id = insert_snapshot_tick(
        timestamp=timestamp,
        five_hour_used=five_hour.get('pct', 0),
        five_hour_limit=five_hour.get('messages_limit', 0),
        seven_day_used=seven_day.get('pct', 0),
        seven_day_limit=seven_day.get('messages_limit', 0),
        five_hour_pct=five_hour.get('pct'),
        seven_day_pct=seven_day.get('pct'),
        five_hour_reset=five_hour_reset,
        seven_day_reset=seven_day_reset
    )

    # Phase 2: Calculate usage from JSONL
    try:
        # Load JSONL entries
        entries, session_info = load_jsonl_entries(str(CLAUDE_PROJECTS_DIR))

        # Detect active sessions (fork-aware)
        active_sessions = detect_active_sessions(entries, snapshot_time)

        # Get previous snapshot to calculate deltas
        previous_snapshot = get_previous_snapshot(snapshot_id)
        previous_snapshot_time = None
        if previous_snapshot:
            previous_snapshot_time = parse_timestamp(previous_snapshot['timestamp'])

        # Calculate usage for both time windows (deltas + totals)
        calculated_usage = calculate_usage(
            entries,
            snapshot_time,
            active_sessions,
            previous_snapshot_time
        )

        # Update snapshot with calculated values
        update_snapshot_calculations(
            snapshot_id=snapshot_id,
            five_hour_tokens_consumed=calculated_usage['five_hour_tokens'],
            five_hour_messages_count=calculated_usage['five_hour_messages'],
            seven_day_tokens_consumed=calculated_usage['seven_day_tokens'],
            seven_day_messages_count=calculated_usage['seven_day_messages'],
            five_hour_tokens_total=calculated_usage['five_hour_tokens_total'],
            five_hour_messages_total=calculated_usage['five_hour_messages_total'],
            seven_day_tokens_total=calculated_usage['seven_day_tokens_total'],
            seven_day_messages_total=calculated_usage['seven_day_messages_total'],
            active_sessions=list(active_sessions)
        )

        # Return complete result
        return {
            'snapshot_id': snapshot_id,
            'timestamp': timestamp,
            'api_data': {
                'five_hour': five_hour,
                'seven_day': seven_day
            },
            'calculated': calculated_usage,
            'active_sessions': list(active_sessions),
            'success': True
        }

    except Exception as e:
        # If calculation fails, snapshot still exists with API data
        # Log error and return partial result
        import sys
        print(f"Error calculating usage for snapshot {snapshot_id}: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)

        return {
            'snapshot_id': snapshot_id,
            'timestamp': timestamp,
            'api_data': {
                'five_hour': five_hour,
                'seven_day': seven_day
            },
            'calculated': None,
            'active_sessions': [],
            'success': False,
            'error': str(e)
        }


def load_jsonl_entries(
    projects_dir: str,
    verbose: bool = False
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """
    Load all entries from JSONL files in the projects directory.

    Args:
        projects_dir: Path to ~/.claude/projects directory
        verbose: Print detailed loading information

    Returns:
        Tuple of (all_entries, session_info_map)
        - all_entries: List of all log entries with _session_id and _file_path metadata
        - session_info_map: Dict mapping session_id to file path
    """
    projects_path = Path(projects_dir)
    all_entries = []
    session_info = {}

    if verbose:
        print(f"Loading entries from {projects_path}...")

    for project_dir in projects_path.iterdir():
        if not project_dir.is_dir():
            continue

        for jsonl_file in project_dir.glob("*.jsonl"):
            session_id = jsonl_file.stem
            session_info[session_id] = str(jsonl_file)

            if verbose:
                print(f"  Loading {jsonl_file.name}...")

            try:
                with open(jsonl_file, 'r', encoding='utf-8') as f:
                    for line_num, line in enumerate(f, 1):
                        line = line.strip()
                        if not line:
                            continue

                        try:
                            entry = json.loads(line)
                            # Add metadata
                            entry['_session_id'] = session_id
                            entry['_file_path'] = str(jsonl_file)
                            all_entries.append(entry)

                        except json.JSONDecodeError as e:
                            if verbose:
                                print(f"    Warning: Invalid JSON at line {line_num}: {e}")

            except Exception as e:
                if verbose:
                    print(f"  Error reading {jsonl_file}: {e}")

    if verbose:
        print(f"Loaded {len(all_entries)} entries from {len(session_info)} sessions")

    return all_entries, session_info


def calculate_usage(
    entries: List[Dict[str, Any]],
    snapshot_time: datetime,
    active_sessions: Set[str],
    previous_snapshot_time: Optional[datetime] = None
) -> Dict[str, int]:
    """
    Calculate usage for both 5-hour and 7-day windows using ccusage methodology.

    Calculates both deltas (since previous snapshot) and totals (within window).

    Args:
        entries: All JSONL entries
        snapshot_time: The snapshot timestamp
        active_sessions: Set of active session IDs (from fork-aware detection)
        previous_snapshot_time: Timestamp of previous snapshot (for delta calculation)

    Returns:
        Dictionary with:
        - five_hour_messages: Delta messages since previous snapshot (5h window)
        - five_hour_tokens: Delta tokens since previous snapshot (5h window)
        - five_hour_messages_total: Total messages in 5h window (unfiltered)
        - five_hour_tokens_total: Total tokens in 5h window (unfiltered)
        - seven_day_messages: Delta messages since previous snapshot (7d window)
        - seven_day_tokens: Delta tokens since previous snapshot (7d window)
        - seven_day_messages_total: Total messages in 7d window (unfiltered)
        - seven_day_tokens_total: Total tokens in 7d window (unfiltered)
    """
    # Define time windows
    five_hour_start = snapshot_time - timedelta(hours=5)
    seven_day_start = snapshot_time - timedelta(days=7)

    # Initialize counters for DELTAS (consumed since last snapshot)
    five_hour_delta_messages = 0
    five_hour_delta_tokens = 0
    seven_day_delta_messages = 0
    seven_day_delta_tokens = 0

    # Initialize counters for TOTALS (everything in window)
    five_hour_messages_total = 0
    five_hour_tokens_total = 0
    seven_day_messages_total = 0
    seven_day_tokens_total = 0

    # Process each entry
    for entry in entries:
        # Parse entry timestamp
        entry_timestamp_str = entry.get('timestamp')
        if not entry_timestamp_str:
            continue

        try:
            entry_time = parse_timestamp(entry_timestamp_str)
        except (ValueError, AttributeError):
            continue

        # Skip entries after snapshot time
        if entry_time > snapshot_time:
            continue

        # Get session ID
        session_id = entry.get('sessionId') or entry.get('_session_id')

        # Extract tokens using ccusage methodology
        tokens = extract_tokens_from_entry(entry)

        # Count as 1 message (each JSONL entry is a message)
        messages = 1

        # Check if this entry is in the delta range (since previous snapshot)
        in_delta_range = False
        if previous_snapshot_time:
            # Entry is in delta if: previous_time < entry_time <= current_time
            in_delta_range = previous_snapshot_time < entry_time <= snapshot_time
        else:
            # No previous snapshot - treat all entries in window as delta
            in_delta_range = True

        # Check if in 5-hour window
        if entry_time >= five_hour_start:
            # Always count towards totals (unfiltered)
            five_hour_messages_total += messages
            five_hour_tokens_total += tokens

            # Count towards delta if in range and in active session
            if in_delta_range and session_id in active_sessions:
                five_hour_delta_messages += messages
                five_hour_delta_tokens += tokens

        # Check if in 7-day window
        if entry_time >= seven_day_start:
            # Always count towards totals (unfiltered)
            seven_day_messages_total += messages
            seven_day_tokens_total += tokens

            # Count towards delta if in range and in active session
            if in_delta_range and session_id in active_sessions:
                seven_day_delta_messages += messages
                seven_day_delta_tokens += tokens

    return {
        'five_hour_messages': five_hour_delta_messages,
        'five_hour_tokens': five_hour_delta_tokens,
        'five_hour_messages_total': five_hour_messages_total,
        'five_hour_tokens_total': five_hour_tokens_total,
        'seven_day_messages': seven_day_delta_messages,
        'seven_day_tokens': seven_day_delta_tokens,
        'seven_day_messages_total': seven_day_messages_total,
        'seven_day_tokens_total': seven_day_tokens_total
    }


def detect_active_sessions(
    entries: List[Dict],
    snapshot_time: datetime,
    verbose: bool = False
) -> Set[str]:
    """
    Detect which sessions are "active" at the snapshot time.

    This implements fork-aware session detection:
    - Traces back from most recent entries to find active conversation paths
    - Excludes abandoned fork branches

    Args:
        entries: All log entries
        snapshot_time: The time to check active sessions for
        verbose: Print detection details

    Returns:
        Set of active session IDs
    """
    # Filter to entries up to snapshot time
    relevant_entries = [
        e for e in entries
        if e.get('timestamp') and
        parse_timestamp(e['timestamp']) <= snapshot_time
    ]

    if not relevant_entries:
        return set()

    # Build UUID to entry mapping
    entries_by_uuid = {}
    for entry in relevant_entries:
        uuid = entry.get('uuid')
        if uuid:
            entries_by_uuid[uuid] = entry

    # Find most recent entry
    most_recent = max(
        relevant_entries,
        key=lambda e: e.get('timestamp', ''),
        default=None
    )

    if not most_recent:
        return set()

    # Trace backward through parent chain
    active_uuids = set()
    to_visit = [most_recent.get('uuid')]

    while to_visit:
        current_uuid = to_visit.pop()
        if not current_uuid or current_uuid in active_uuids:
            continue

        active_uuids.add(current_uuid)

        entry = entries_by_uuid.get(current_uuid)
        if entry:
            # Follow both parentUuid and logicalParentUuid (for forks)
            parent_uuid = entry.get('parentUuid')
            logical_parent_uuid = entry.get('logicalParentUuid')

            if parent_uuid and parent_uuid not in active_uuids:
                to_visit.append(parent_uuid)
            if logical_parent_uuid and logical_parent_uuid not in active_uuids:
                to_visit.append(logical_parent_uuid)

    # Extract session IDs from active entries
    active_sessions = set()
    for uuid in active_uuids:
        entry = entries_by_uuid.get(uuid)
        if entry:
            session_id = entry.get('sessionId') or entry.get('_session_id')
            if session_id:
                active_sessions.add(session_id)

    if verbose and active_sessions:
        active_list = ', '.join(sorted(s[:8] for s in active_sessions))
        print(f"  Active sessions at {snapshot_time.isoformat()}: {active_list}")

    return active_sessions


def parse_timestamp(timestamp_str: str) -> datetime:
    """
    Parse ISO timestamp with timezone awareness.

    Args:
        timestamp_str: ISO format timestamp (e.g., "2025-11-12T10:00:00Z")

    Returns:
        Timezone-aware datetime object

    Examples:
        >>> parse_timestamp("2025-11-12T10:00:00Z")
        datetime.datetime(2025, 11, 12, 10, 0, tzinfo=datetime.timezone.utc)

        >>> parse_timestamp("2025-11-12T10:00:00")
        datetime.datetime(2025, 11, 12, 10, 0, tzinfo=datetime.timezone.utc)
    """
    if timestamp_str.endswith('Z'):
        return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
    else:
        dt = datetime.fromisoformat(timestamp_str)
        # If naive (no timezone info), assume UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt


if __name__ == '__main__':
    # Test the snapshot pipeline
    print("Testing snapshot_pipeline.py")
    print("=" * 80)
    print()

    # Create test usage data
    test_usage_data = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'five_hour': {
            'tokens_consumed': 12345,
            'messages_count': 67,
            'tokens_limit': 100000,
            'messages_limit': 1000,
            'pct': 12.3,
            'reset': (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
        },
        'seven_day': {
            'tokens_consumed': 234567,
            'messages_count': 890,
            'tokens_limit': 5000000,
            'messages_limit': 50000,
            'pct': 4.7,
            'reset': (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
        }
    }

    print("Test usage data:")
    print(json.dumps(test_usage_data, indent=2))
    print()

    try:
        result = trigger_snapshot_calculation(test_usage_data)

        print("Result:")
        print(json.dumps({
            'snapshot_id': result['snapshot_id'],
            'timestamp': result['timestamp'],
            'success': result['success'],
            'active_sessions': len(result.get('active_sessions', [])),
            'calculated': result.get('calculated', {})
        }, indent=2))
        print()

        if result['success']:
            print("✓ Snapshot created and calculated successfully!")
        else:
            print(f"✗ Calculation failed: {result.get('error')}")

    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()

    print()
    print("=" * 80)
