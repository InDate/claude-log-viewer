"""
Optimized Bucket Assignment Algorithm

High-performance bucket assignment using epoch-based indexing with tuple keys.
Validates all premises and handles boundary conditions correctly.
Tracks message count and token sum per bucket and time range.
Tracks uncovered messages (in bucket window but not in any time range).
Supports both in-memory batch processing and streaming from JSONL files.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone


class BucketAssignmentError(Exception):
    """Raised when bucket assignment violates premises."""
    pass


def validate_bucket(bucket_key, bucket, duration):
    """
    Validate that a bucket satisfies all premises.
    
    Args:
        bucket_key: The bucket's key
        bucket: Bucket data with 'start', 'end', 'message_count', 'token_sum'
        duration: Expected bucket duration
        
    Raises:
        BucketAssignmentError if bucket violates premises
    """
    if "start" not in bucket or "end" not in bucket:
        raise BucketAssignmentError(
            f"Bucket {bucket_key} missing 'start' or 'end' field"
        )
    
    # Premise 2: Fixed lifespan - each bucket lives exactly its duration
    # Exception: Buckets can be truncated when reset time changes (account upgrade)
    expected_end = bucket["start"] + duration
    if bucket["end"] > expected_end:
        raise BucketAssignmentError(
            f"Premise 2 violation: Bucket {bucket_key} has end={bucket['end']}, "
            f"which is beyond expected {expected_end} (start + duration)"
        )
    # Allow bucket["end"] < expected_end (truncated due to early reset)
    
    # Initialize counters if not present
    if "message_count" not in bucket:
        bucket["message_count"] = 0
    if "token_sum" not in bucket:
        bucket["token_sum"] = 0
    if "messages" not in bucket:
        bucket["messages"] = []
    if "uncovered_message_count" not in bucket:
        bucket["uncovered_message_count"] = 0
    if "uncovered_token_sum" not in bucket:
        bucket["uncovered_token_sum"] = 0


def index_buckets_by_epoch(buckets, duration):
    """
    Index buckets by epoch for O(1) lookup.
    Uses tuple keys (duration, epoch) for faster lookups than string formatting.

    Note: Buckets are pre-validated and any overlaps have been fixed by
    fix_overlapping_buckets() before this function is called.

    Args:
        buckets: Dict of bucket_key -> bucket_data
        duration: Bucket duration

    Returns:
        Dict mapping (duration, epoch) tuple -> [(bucket_key, bucket_data), ...]
        sorted by bucket start time
    """
    index = defaultdict(list)

    for bucket_key, bucket in buckets.items():
        # Validate bucket structure
        validate_bucket(bucket_key, bucket, duration)

        # Calculate epoch from bucket start time
        epoch = bucket['start'] // duration
        index[(duration, epoch)].append((bucket_key, bucket))

    # Sort by start time within each epoch
    for epoch_key in index:
        index[epoch_key].sort(key=lambda x: x[1]["start"])

    return index


def find_bucket(message_time, duration, bucket_index):
    """
    Find the bucket containing a message without mutating state.
    Optimized with early exit since buckets never overlap (Premise 4).

    Args:
        message_time: Timestamp of the message
        duration: Bucket duration
        bucket_index: Pre-built index from index_buckets_by_epoch()

    Returns:
        (bucket_key, bucket_data, created_bucket) or (None, None, False)
        created_bucket: True if message created the bucket (start == message_time)
    """
    # Premise 7: Limited candidate window (message_time - duration, message_time]
    window_start = message_time - duration  # exclusive
    window_end = message_time  # inclusive
    
    epoch_start = window_start // duration
    epoch_end = message_time // duration

    for epoch in range(epoch_start, epoch_end + 1):
        epoch_key = (duration, epoch)  # Tuple is faster than f-string
        
        if epoch_key not in bucket_index:
            continue

        for bucket_key, bucket in bucket_index[epoch_key]:
            # Bucket must have started in the valid window: (window_start, window_end]
            if not (window_start < bucket["start"] <= window_end):
                continue

            # Verify message is within bucket's lifespan [start, end)
            # Half-open interval: bucket contains [start, end)
            if bucket["start"] <= message_time < bucket["end"]:
                created_bucket = (bucket["start"] == message_time)
                return (bucket_key, bucket, created_bucket)

    return (None, None, False)


def update_bucket(bucket, message_time, message_tokens, in_time_range, entry=None, should_count=True):
    """
    Update bucket counters with a new message.

    Args:
        bucket: Bucket data to update
        message_time: Timestamp of the message
        message_tokens: Number of tokens for this message
        in_time_range: True if message falls within a defined time range
        entry: Optional full JSONL entry (for fork detection)
        should_count: If True, count tokens/messages. If False, only store for fork detection.
    """
    # Only increment counters if message should be counted
    if should_count:
        bucket["message_count"] += 1
        bucket["token_sum"] += message_tokens

        # Track uncovered messages (in bucket but not in any time range)
        if not in_time_range:
            bucket["uncovered_message_count"] += 1
            bucket["uncovered_token_sum"] += message_tokens

    # ALWAYS store message for fork detection (regardless of should_count)
    message_data = {
        'time': message_time,
        'tokens': message_tokens,
        'in_time_range': in_time_range
    }

    # Add entry metadata if available (needed for fork detection)
    if entry:
        message_data['uuid'] = entry.get('uuid')
        message_data['parentUuid'] = entry.get('parentUuid')
        message_data['sessionId'] = entry.get('sessionId')
        message_data['timestamp'] = entry.get('timestamp')

    bucket["messages"].append(message_data)


def index_time_ranges_by_epoch(time_ranges, duration):
    """
    Index time ranges by epoch for O(1) lookup.
    Uses tuple keys (duration, epoch) for faster lookups.

    Note: Time ranges from different buckets CAN overlap. This is expected
    behavior when Claude's usage windows reset at different times.

    Args:
        time_ranges: List of dicts with 'start' and 'end' keys
        duration: Duration used for epoch calculation

    Returns:
        Dict mapping (duration, epoch) tuple -> [(range_index, range_data), ...]
    """
    index = defaultdict(list)

    # Initialize counters for all ranges
    for time_range in time_ranges:
        time_range['message_count'] = 0
        time_range['token_sum'] = 0

    # Build epoch index
    for i, time_range in enumerate(time_ranges):
        start_epoch = time_range['start'] // duration
        end_epoch = time_range['end'] // duration

        for epoch in range(start_epoch, end_epoch + 1):
            epoch_key = (duration, epoch)  # Tuple instead of f-string
            index[epoch_key].append((i, time_range))

    return index


def find_time_range(message_time, duration, time_range_index):
    """
    Find the time range containing a message without mutating state.
    Optimized with early exit since time ranges never overlap.
    
    Args:
        message_time: Timestamp of the message
        duration: Duration used for epoch calculation
        time_range_index: Pre-built index from index_time_ranges_by_epoch()

    Returns:
        (range_index, range_data) or (None, None)
    """
    epoch = message_time // duration
    epoch_key = (duration, epoch)  # Tuple instead of f-string

    if epoch_key in time_range_index:
        for range_index, time_range in time_range_index[epoch_key]:
            if time_range['start'] <= message_time < time_range['end']:
                return (range_index, time_range)
    
    return (None, None)


def update_time_range(time_range, message_tokens):
    """
    Update time range counters with a new message.
    
    Args:
        time_range: Time range data to update
        message_tokens: Number of tokens for this message
    """
    time_range['message_count'] += 1
    time_range['token_sum'] += message_tokens


def process_single_message(message_time, message_tokens, bucket_types, entry=None, cutoff_time=None):
    """
    Process a single message into all bucket types.

    Args:
        message_time: Message timestamp (epoch seconds)
        message_tokens: Number of tokens
        bucket_types: List of bucket type configurations with indices already built
        entry: Optional full JSONL entry (for fork detection)
        cutoff_time: Optional epoch timestamp - only count tokens/messages after this time.
                     Messages before cutoff are still stored for fork detection.

    Raises:
        BucketAssignmentError if message doesn't fit into expected buckets
    """
    # Determine if this message should be counted
    should_count = (cutoff_time is None) or (message_time > cutoff_time)

    # Find assignments for this message
    message_assignments = []
    missing_buckets = []

    for bucket_type in bucket_types:
        duration = bucket_type['duration']
        bucket_index = bucket_type['bucket_index']
        time_range_index = bucket_type['time_range_index']
        name = bucket_type.get('name', f"duration-{duration}")

        # Find bucket
        bucket_key, bucket, created = find_bucket(message_time, duration, bucket_index)

        if bucket is None:
            missing_buckets.append(name)
            continue

        # Find time range (if time ranges are defined)
        if time_range_index:
            range_index, time_range = find_time_range(message_time, duration, time_range_index)
        else:
            range_index, time_range = None, None

        message_assignments.append({
            'bucket': bucket,
            'time_range': time_range,
        })

    # Premise 6: All bucket types must exist for each message
    if missing_buckets:
        raise BucketAssignmentError(
            f"Premise 6 violation: Message at {message_time} missing "
            f"{', '.join(missing_buckets)} bucket(s)"
        )

    # Update immediately for better cache locality
    for assignment in message_assignments:
        bucket = assignment['bucket']
        time_range = assignment['time_range']
        in_time_range = (time_range is not None)

        # Update bucket (pass entry for fork detection and should_count for filtering)
        update_bucket(bucket, message_time, message_tokens, in_time_range, entry, should_count)

        # Update time range if found AND message should be counted
        if time_range is not None and should_count:
            update_time_range(time_range, message_tokens)


def process_messages_from_jsonl(
    claude_projects_dir,
    bucket_types,
    verbose=False,
    return_stats=True,
    callback=None,
    use_cutoff=True
):
    """
    Stream messages from JSONL files and process them into buckets without loading all into memory.

    This is a streaming version that:
    1. Loads bucket indices into memory (small)
    2. Streams through JSONL files one entry at a time
    3. Processes each message immediately
    4. Never holds all messages in memory

    Args:
        claude_projects_dir: Path to ~/.claude/projects directory (Path object or string)
        bucket_types: Pre-built bucket type configurations
        verbose: If True, print progress information
        return_stats: If True, include processing statistics in return value
        callback: Optional callback function(dict) for progress updates
                  Called with dict containing 'stage' and 'message' keys
                  Stages: 'loading', 'processing', 'complete'
        use_cutoff: If True, only count messages after cutoff time (earliest reset - 5/7 days)
                    Messages before cutoff are still stored for fork detection

    Returns:
        If return_stats=True: (coverage_stats, processing_stats)
        If return_stats=False: coverage_stats

    Raises:
        BucketAssignmentError if premises are violated (unless in streaming mode)
    """
    import json
    from pathlib import Path
    from datetime import datetime

    try:
        from .token_utils import extract_tokens_from_entry
    except ImportError:
        from token_utils import extract_tokens_from_entry

    if isinstance(claude_projects_dir, str):
        claude_projects_dir = Path(claude_projects_dir)

    # Calculate cutoff time for message filtering
    cutoff_time = None
    if use_cutoff:
        cutoff_time = get_cutoff_time()
        if verbose and cutoff_time:
            cutoff_dt = datetime.fromtimestamp(cutoff_time, tz=timezone.utc)
            print(f"Using cutoff time: {cutoff_dt.isoformat()} (messages before this will not be counted)")
        elif verbose:
            print("No cutoff time available (no usage snapshots found)")

    # Build indices for all bucket types (kept in memory, small compared to messages)
    for bucket_type in bucket_types:
        duration = bucket_type['duration']
        buckets = bucket_type['buckets']
        time_ranges = bucket_type.get('time_ranges')

        # Index buckets
        bucket_type['bucket_index'] = index_buckets_by_epoch(buckets, duration)

        # Index time ranges if provided
        if time_ranges:
            bucket_type['time_range_index'] = index_time_ranges_by_epoch(time_ranges, duration)
        else:
            bucket_type['time_range_index'] = None

    # Processing statistics
    processing_stats = {
        'total_files': 0,
        'processed_files': 0,
        'skipped_files': 0,
        'total_messages': 0,
        'processed_messages': 0,
        'skipped_messages': {
            'json_errors': 0,
            'missing_timestamps': 0,
            'premise_violations': 0,
            'parse_errors': 0,
        },
        'premise_violation_details': [],
    }

    # Stream through JSONL files
    all_files = list(claude_projects_dir.glob('**/*.jsonl'))
    processing_stats['total_files'] = len(all_files)

    if callback:
        callback({
            'stage': 'loading',
            'message': f"Found {len(all_files)} JSONL files to process"
        })

    if verbose:
        print(f"Found {len(all_files)} JSONL files to process")

    for file_idx, file_path in enumerate(all_files, 1):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                messages_in_file = 0
                
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue

                    processing_stats['total_messages'] += 1

                    # Initialize to None for error handling
                    message_time = None

                    try:
                        entry = json.loads(line)

                        # Extract timestamp
                        timestamp_str = entry.get('timestamp')
                        if not timestamp_str:
                            processing_stats['skipped_messages']['missing_timestamps'] += 1
                            continue

                        # Parse timestamp to epoch seconds
                        timestamp_dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                        message_time = int(timestamp_dt.timestamp())

                        # Extract tokens
                        message_tokens = extract_tokens_from_entry(entry, verbose=False)

                        # Process this message immediately (pass entry for fork detection and cutoff_time for filtering)
                        process_single_message(message_time, message_tokens, bucket_types, entry=entry, cutoff_time=cutoff_time)

                        processing_stats['processed_messages'] += 1
                        messages_in_file += 1

                    except json.JSONDecodeError as e:
                        processing_stats['skipped_messages']['json_errors'] += 1
                        if verbose:
                            print(f"JSON error in {file_path}:{line_num}: {e}")
                        continue

                    except BucketAssignmentError as e:
                        processing_stats['skipped_messages']['premise_violations'] += 1
                        processing_stats['premise_violation_details'].append({
                            'file': str(file_path),
                            'line': line_num,
                            'time': message_time,
                            'error': str(e)
                        })
                        if verbose:
                            print(f"Premise violation in {file_path}:{line_num}: {e}")
                        continue

                    except (ValueError, KeyError) as e:
                        processing_stats['skipped_messages']['parse_errors'] += 1
                        if verbose:
                            print(f"Parse error in {file_path}:{line_num}: {e}")
                        continue

                processing_stats['processed_files'] += 1

                # Periodic progress updates
                if file_idx % 100 == 0:
                    if callback:
                        callback({
                            'stage': 'processing',
                            'message': f"Processing files: {file_idx}/{len(all_files)} ({processing_stats['processed_messages']} messages)"
                        })
                    if verbose:
                        print(f"Progress: {file_idx}/{len(all_files)} files, "
                              f"{processing_stats['processed_messages']} messages processed")

        except (OSError, IOError) as e:
            processing_stats['skipped_files'] += 1
            if verbose:
                print(f"Cannot read file {file_path}: {e}")
            continue

    if verbose:
        print(f"\nProcessing complete:")
        print(f"  Files: {processing_stats['processed_files']}/{processing_stats['total_files']}")
        print(f"  Messages: {processing_stats['processed_messages']}/{processing_stats['total_messages']}")
        total_skipped = sum(processing_stats['skipped_messages'].values())
        if total_skipped > 0:
            print(f"  Skipped messages: {total_skipped}")
            for reason, count in processing_stats['skipped_messages'].items():
                if count > 0:
                    print(f"    {reason}: {count}")

    # Calculate coverage statistics after processing all messages
    coverage_stats = {}
    for bucket_type in bucket_types:
        name = bucket_type.get('name', f"duration-{bucket_type['duration']}")
        buckets = bucket_type['buckets']
        time_ranges = bucket_type.get('time_ranges')

        # Single pass through buckets
        total_messages = 0
        total_tokens = 0
        uncovered_messages = 0
        uncovered_tokens = 0

        for bucket in buckets.values():
            total_messages += bucket['message_count']
            total_tokens += bucket['token_sum']
            uncovered_messages += bucket['uncovered_message_count']
            uncovered_tokens += bucket['uncovered_token_sum']

        coverage_stats[name] = {
            'total_messages': total_messages,
            'total_tokens': total_tokens,
            'covered_messages': total_messages - uncovered_messages,
            'covered_tokens': total_tokens - uncovered_tokens,
            'uncovered_messages': uncovered_messages,
            'uncovered_tokens': uncovered_tokens,
            'coverage_percentage': (
                100.0 * (total_messages - uncovered_messages) / total_messages
                if total_messages > 0 else 0.0
            )
        }

        # Add time range info if available
        if time_ranges:
            coverage_stats[name]['time_ranges_defined'] = len(time_ranges)
            coverage_stats[name]['time_range_messages'] = sum(
                tr['message_count'] for tr in time_ranges
            )
            coverage_stats[name]['time_range_tokens'] = sum(
                tr['token_sum'] for tr in time_ranges
            )

    # Notify callback of completion
    if callback:
        callback({
            'stage': 'complete',
            'message': f"Processing complete: {processing_stats['processed_files']} files, {processing_stats['processed_messages']} messages"
        })

    if return_stats:
        return coverage_stats, processing_stats
    return coverage_stats


def get_bucket_ranges(window_type: str):
    """
    Get all bucket ranges for a window type from usage_snapshots.

    A bucket is defined by its reset time (end) and window duration.
    Bucket lifespan: [reset_time - window_duration, reset_time)

    Args:
        window_type: "five_hour" or "seven_day"

    Returns:
        List of dicts, each containing:
        - 'reset_time': ISO timestamp when bucket ends
        - 'start': Bucket start timestamp (epoch seconds)
        - 'end': Bucket end timestamp (epoch seconds) = reset_time
        - 'duration': Duration in seconds
    """
    from .database import get_db

    if window_type == "five_hour":
        reset_column = "five_hour_reset"
        duration_hours = 5
    elif window_type == "seven_day":
        reset_column = "seven_day_reset"
        duration_hours = 168  # 7 days
    else:
        raise ValueError(f"Invalid window_type: {window_type}")

    duration_seconds = duration_hours * 3600

    with get_db() as conn:
        cursor = conn.cursor()

        # Get unique reset times where increment count > 0 (activity occurred)
        # Only create buckets for periods with actual usage
        if window_type == "five_hour":
            consumed_column = "five_hour_tokens_consumed"
            count_column = "five_hour_messages_count"
        else:
            consumed_column = "seven_day_tokens_consumed"
            count_column = "seven_day_messages_count"

        cursor.execute(f"""
            SELECT DISTINCT {reset_column} as reset_time
            FROM usage_snapshots
            WHERE {reset_column} IS NOT NULL
              AND {reset_column} != ''
            ORDER BY reset_time ASC
        """)

        buckets = []
        for row in cursor.fetchall():
            reset_time_str = row['reset_time']

            # Parse reset time (bucket end)
            reset_dt = datetime.fromisoformat(reset_time_str.replace('Z', '+00:00'))

            # Calculate bucket start
            start_dt = reset_dt - timedelta(hours=duration_hours)

            # Convert to epoch seconds for bucket assignment algorithm
            start_epoch = int(start_dt.timestamp())
            end_epoch = int(reset_dt.timestamp())

            buckets.append({
                'reset_time': reset_time_str,
                'start': start_epoch,
                'end': end_epoch,
                'duration': duration_seconds
            })

    return buckets


def get_cutoff_time():
    """
    Calculate cutoff time for filtering messages based on earliest reset times.

    Cutoff logic:
    - For 5-hour window: earliest_5h_reset - 5 days
    - For 7-day window: earliest_7d_reset - 7 days
    - Returns min(cutoff_5h, cutoff_7d) to use the more conservative cutoff

    Messages before this cutoff are stored for fork detection but not counted
    in token/message statistics.

    Returns:
        Cutoff timestamp as epoch seconds, or None if no snapshots exist
    """
    from .database import get_db

    with get_db() as conn:
        cursor = conn.cursor()

        # Get earliest 5-hour reset
        cursor.execute("""
            SELECT MIN(five_hour_reset) as earliest
            FROM usage_snapshots
            WHERE five_hour_reset IS NOT NULL
              AND five_hour_reset != ''
        """)
        row = cursor.fetchone()
        earliest_5h = row['earliest'] if row and row['earliest'] else None

        # Get earliest 7-day reset
        cursor.execute("""
            SELECT MIN(seven_day_reset) as earliest
            FROM usage_snapshots
            WHERE seven_day_reset IS NOT NULL
              AND seven_day_reset != ''
        """)
        row = cursor.fetchone()
        earliest_7d = row['earliest'] if row and row['earliest'] else None

    # If no snapshots exist, return None (no filtering)
    if not earliest_5h and not earliest_7d:
        return None

    # Calculate cutoffs
    cutoffs = []

    if earliest_5h:
        # Parse ISO timestamp
        earliest_5h_dt = datetime.fromisoformat(earliest_5h.replace('Z', '+00:00'))
        # Subtract 5 days
        cutoff_5h_dt = earliest_5h_dt - timedelta(days=5)
        cutoffs.append(int(cutoff_5h_dt.timestamp()))

    if earliest_7d:
        # Parse ISO timestamp
        earliest_7d_dt = datetime.fromisoformat(earliest_7d.replace('Z', '+00:00'))
        # Subtract 7 days
        cutoff_7d_dt = earliest_7d_dt - timedelta(days=7)
        cutoffs.append(int(cutoff_7d_dt.timestamp()))

    # Return the minimum (earliest/most conservative) cutoff
    return min(cutoffs) if cutoffs else None


def get_time_ranges(window_type: str):
    """
    Get time ranges (snapshot deltas) grouped by bucket for a window type.

    Time ranges are the periods between consecutive snapshots within a bucket.
    All snapshots with the same reset time belong to the same bucket.

    Args:
        window_type: "five_hour" or "seven_day"

    Returns:
        Dict mapping reset_time -> list of time ranges, where each range is:
        - 'start': Range start timestamp (epoch seconds)
        - 'end': Range end timestamp (epoch seconds)
        - 'snapshot_id': ID of the snapshot at range end
    """
    from .database import get_db

    if window_type == "five_hour":
        reset_column = "five_hour_reset"
        duration_hours = 5
    elif window_type == "seven_day":
        reset_column = "seven_day_reset"
        duration_hours = 168
    else:
        raise ValueError(f"Invalid window_type: {window_type}")

    with get_db() as conn:
        cursor = conn.cursor()

        # Get all snapshots ordered by reset time, then timestamp
        cursor.execute(f"""
            SELECT id, timestamp, {reset_column} as reset_time
            FROM usage_snapshots
            WHERE {reset_column} IS NOT NULL
              AND {reset_column} != ''
            ORDER BY reset_time ASC, timestamp ASC
        """)

        snapshots = [dict(row) for row in cursor.fetchall()]

    # Group snapshots by bucket (reset_time)
    buckets_map = {}
    for snapshot in snapshots:
        reset_time = snapshot['reset_time']
        if reset_time not in buckets_map:
            buckets_map[reset_time] = []
        buckets_map[reset_time].append(snapshot)

    # Build time ranges for each bucket
    time_ranges_by_bucket = {}

    for reset_time, bucket_snapshots in buckets_map.items():
        time_ranges = []

        # Parse reset time to get bucket start
        reset_dt = datetime.fromisoformat(reset_time.replace('Z', '+00:00'))
        bucket_start_dt = reset_dt - timedelta(hours=duration_hours)
        bucket_start_epoch = int(bucket_start_dt.timestamp())

        # Create time ranges between consecutive snapshots
        prev_timestamp = bucket_start_epoch

        for snapshot in bucket_snapshots:
            snapshot_dt = datetime.fromisoformat(snapshot['timestamp'].replace('Z', '+00:00'))
            snapshot_epoch = int(snapshot_dt.timestamp())

            # Time range from previous snapshot to current snapshot
            time_ranges.append({
                'start': prev_timestamp,
                'end': snapshot_epoch,
                'snapshot_id': snapshot['id']
            })

            prev_timestamp = snapshot_epoch

        time_ranges_by_bucket[reset_time] = time_ranges

    return time_ranges_by_bucket


def fix_overlapping_buckets(buckets, duration):
    """
    Fix overlapping buckets by truncating older buckets when reset time changes.

    When Claude's API reports a new reset time (e.g., due to account upgrade),
    it means the usage window was reset early. The older bucket should be
    truncated to end when the newer bucket starts.

    Args:
        buckets: Dict of bucket_key -> bucket_data
        duration: Bucket duration in seconds

    Returns:
        Dict of bucket_key -> bucket_data with overlaps fixed
    """
    # Convert to list and sort by start time
    bucket_list = [(key, data) for key, data in buckets.items()]
    bucket_list.sort(key=lambda x: x[1]['start'])

    # Check for overlaps and fix them
    for i in range(len(bucket_list) - 1):
        curr_key, curr_bucket = bucket_list[i]
        next_key, next_bucket = bucket_list[i + 1]

        # If current bucket ends after next bucket starts, truncate it
        if curr_bucket['end'] > next_bucket['start']:
            # Truncate the older bucket to end when the newer one starts
            old_end = curr_bucket['end']
            curr_bucket['end'] = next_bucket['start']

            # Note: We don't update the reset_time since that's what the API reported
            # The bucket just ended early due to a window reset

    # Rebuild dict
    fixed_buckets = {key: data for key, data in bucket_list}
    return fixed_buckets


def prepare_snapshot_updates(bucket_types, include_current_values=False):
    """
    Prepare snapshot updates from bucket assignment results.

    Args:
        bucket_types: List of bucket_type dicts from get_bucket_types_for_assignment()
        include_current_values: If True, fetch current values from database for comparison

    Returns:
        List of update dicts with keys:
        - snapshot_id, window_type, delta_tokens, delta_messages, total_tokens, total_messages
        - If include_current_values=True, also includes: current_delta_tokens, current_delta_messages,
          current_total_tokens, current_total_messages
    """
    from .database import get_db

    updates = []

    for bucket_type in bucket_types:
        duration = bucket_type['duration']
        name = bucket_type['name']  # '5h' or '7d'
        time_ranges_by_bucket = bucket_type.get('time_ranges_by_bucket', {})
        buckets = bucket_type['buckets']

        # For each bucket (one per reset_time)
        for reset_time, time_ranges in time_ranges_by_bucket.items():
            # Find the bucket for this reset_time
            bucket_key = f"{duration}:{reset_time}"
            if bucket_key not in buckets:
                continue

            bucket = buckets[bucket_key]

            # Process each time range (= each snapshot)
            for time_range in time_ranges:
                snapshot_id = time_range['snapshot_id']
                snapshot_time = time_range['end']

                # DELTA = time range counts (activity since last snapshot)
                delta_tokens = time_range['token_sum']
                delta_messages = time_range['message_count']

                # WINDOW TOTAL = sum all messages in bucket at or before snapshot time
                total_tokens = sum(
                    msg['tokens']
                    for msg in bucket['messages']
                    if msg['time'] <= snapshot_time
                )
                total_messages = sum(
                    1
                    for msg in bucket['messages']
                    if msg['time'] <= snapshot_time
                )

                # CRITICAL FIX: Handle window reset edge case
                if delta_tokens > total_tokens:
                    delta_tokens = total_tokens
                    delta_messages = total_messages

                # Prepare update
                updates.append({
                    'snapshot_id': snapshot_id,
                    'window_type': name,
                    'delta_tokens': delta_tokens,
                    'delta_messages': delta_messages,
                    'total_tokens': total_tokens,
                    'total_messages': total_messages
                })

    # Fetch current values from database if requested
    if include_current_values:
        with get_db() as conn:
            cursor = conn.cursor()

            for update in updates:
                snapshot_id = update['snapshot_id']
                window_type = update['window_type']

                if window_type == '5h':
                    cursor.execute("""
                        SELECT five_hour_tokens_consumed, five_hour_messages_count,
                               five_hour_tokens_total, five_hour_messages_total
                        FROM usage_snapshots
                        WHERE id = ?
                    """, (snapshot_id,))
                else:  # '7d'
                    cursor.execute("""
                        SELECT seven_day_tokens_consumed, seven_day_messages_count,
                               seven_day_tokens_total, seven_day_messages_total
                        FROM usage_snapshots
                        WHERE id = ?
                    """, (snapshot_id,))

                row = cursor.fetchone()
                if row:
                    update['current_delta_tokens'] = row[0]
                    update['current_delta_messages'] = row[1]
                    update['current_total_tokens'] = row[2]
                    update['current_total_messages'] = row[3]
                else:
                    update['current_delta_tokens'] = None
                    update['current_delta_messages'] = None
                    update['current_total_tokens'] = None
                    update['current_total_messages'] = None

    return updates


def update_snapshots_with_bucket_statistics(bucket_types):
    """
    Update usage_snapshots table with statistics from bucket assignment.

    For each bucket type (5h, 7d):
      - Time ranges provide DELTAS (*_consumed, *_count)
      - Bucket messages provide WINDOW TOTALS (*_total)

    Window totals are NOT running totals (previous + delta).
    They are absolute counts of all messages in the window at each snapshot.

    Args:
        bucket_types: List of bucket_type dicts from get_bucket_types_for_assignment()

    Returns:
        Tuple of (updates_applied, snapshots_updated_count)
    """
    from .database import get_db

    # Prepare updates
    updates = prepare_snapshot_updates(bucket_types, include_current_values=False)

    # Batch update database
    with get_db() as conn:
        cursor = conn.cursor()

        for update in updates:
            if update['window_type'] == '5h':
                cursor.execute("""
                    UPDATE usage_snapshots
                    SET five_hour_tokens_consumed = ?,
                        five_hour_messages_count = ?,
                        five_hour_tokens_total = ?,
                        five_hour_messages_total = ?
                    WHERE id = ?
                """, (
                    update['delta_tokens'],
                    update['delta_messages'],
                    update['total_tokens'],
                    update['total_messages'],
                    update['snapshot_id']
                ))
            else:  # '7d'
                cursor.execute("""
                    UPDATE usage_snapshots
                    SET seven_day_tokens_consumed = ?,
                        seven_day_messages_count = ?,
                        seven_day_tokens_total = ?,
                        seven_day_messages_total = ?
                    WHERE id = ?
                """, (
                    update['delta_tokens'],
                    update['delta_messages'],
                    update['total_tokens'],
                    update['total_messages'],
                    update['snapshot_id']
                ))

        conn.commit()

    # Count unique snapshots updated
    unique_snapshots = len(set(u['snapshot_id'] for u in updates))

    return (len(updates), unique_snapshots)


def export_updates_to_csv(bucket_types, csv_path):
    """
    Export snapshot updates to CSV file matching the database table structure.

    This outputs rows in the same format as the usage_snapshots table,
    showing what would be written to each column.

    Args:
        bucket_types: List of bucket_type dicts from get_bucket_types_for_assignment()
        csv_path: Path to output CSV file

    Returns:
        Number of rows written
    """
    import csv
    from .database import get_db

    # Prepare updates
    updates = prepare_snapshot_updates(bucket_types, include_current_values=False)

    # Group updates by snapshot_id (each snapshot may have both 5h and 7d updates)
    updates_by_snapshot = {}
    for update in updates:
        sid = update['snapshot_id']
        if sid not in updates_by_snapshot:
            updates_by_snapshot[sid] = {}
        updates_by_snapshot[sid][update['window_type']] = update

    # Fetch current snapshot data from database
    snapshot_data = {}
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, timestamp,
                   five_hour_reset, seven_day_reset
            FROM usage_snapshots
            WHERE id IN ({})
        """.format(','.join('?' * len(updates_by_snapshot))),
        list(updates_by_snapshot.keys()))

        for row in cursor.fetchall():
            snapshot_data[row['id']] = {
                'timestamp': row['timestamp'],
                'five_hour_reset': row['five_hour_reset'],
                'seven_day_reset': row['seven_day_reset']
            }

    # Write to CSV matching database table structure
    with open(csv_path, 'w', newline='') as csvfile:
        fieldnames = [
            'id',
            'timestamp',
            '5h_reset',
            '5h_tokens_consumed',
            '5h_tokens_total',
            '5h_messages_count',
            '5h_messages_total',
            '7d_reset',
            '7d_tokens_consumed',
            '7d_tokens_total',
            '7d_messages_count',
            '7d_messages_total'
        ]

        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for snapshot_id in sorted(updates_by_snapshot.keys()):
            snapshot_updates = updates_by_snapshot[snapshot_id]
            snapshot_info = snapshot_data.get(snapshot_id, {})

            row = {
                'id': snapshot_id,
                'timestamp': snapshot_info.get('timestamp', ''),
                '5h_reset': snapshot_info.get('five_hour_reset', ''),
                '7d_reset': snapshot_info.get('seven_day_reset', '')
            }

            # Add 5h values
            if '5h' in snapshot_updates:
                row['5h_tokens_consumed'] = snapshot_updates['5h']['delta_tokens']
                row['5h_tokens_total'] = snapshot_updates['5h']['total_tokens']
                row['5h_messages_count'] = snapshot_updates['5h']['delta_messages']
                row['5h_messages_total'] = snapshot_updates['5h']['total_messages']
            else:
                row['5h_tokens_consumed'] = ''
                row['5h_tokens_total'] = ''
                row['5h_messages_count'] = ''
                row['5h_messages_total'] = ''

            # Add 7d values
            if '7d' in snapshot_updates:
                row['7d_tokens_consumed'] = snapshot_updates['7d']['delta_tokens']
                row['7d_tokens_total'] = snapshot_updates['7d']['total_tokens']
                row['7d_messages_count'] = snapshot_updates['7d']['delta_messages']
                row['7d_messages_total'] = snapshot_updates['7d']['total_messages']
            else:
                row['7d_tokens_consumed'] = ''
                row['7d_tokens_total'] = ''
                row['7d_messages_count'] = ''
                row['7d_messages_total'] = ''

            writer.writerow(row)

    return len(updates_by_snapshot)


def legacy_update_snapshots_with_bucket_statistics(bucket_types):
    """
    LEGACY VERSION - kept for reference.
    Use update_snapshots_with_bucket_statistics() instead.
    """
    from .database import get_db

    updates = []

    for bucket_type in bucket_types:
        duration = bucket_type['duration']
        name = bucket_type['name']  # '5h' or '7d'
        time_ranges_by_bucket = bucket_type.get('time_ranges_by_bucket', {})
        buckets = bucket_type['buckets']

        # For each bucket (one per reset_time)
        for reset_time, time_ranges in time_ranges_by_bucket.items():
            # Find the bucket for this reset_time
            bucket_key = f"{duration}:{reset_time}"
            if bucket_key not in buckets:
                continue

            bucket = buckets[bucket_key]

            # Process each time range (= each snapshot)
            for time_range in time_ranges:
                snapshot_id = time_range['snapshot_id']
                snapshot_time = time_range['end']

                # DELTA = time range counts (activity since last snapshot)
                delta_tokens = time_range['token_sum']
                delta_messages = time_range['message_count']

                # WINDOW TOTAL = sum all messages in bucket at or before snapshot time
                # The bucket already contains only messages in the correct window
                # (bucket assignment ensures messages are only in the correct bucket)
                # We just need to count messages at or before the snapshot time
                total_tokens = sum(
                    msg['tokens']
                    for msg in bucket['messages']
                    if msg['time'] <= snapshot_time
                )
                total_messages = sum(
                    1
                    for msg in bucket['messages']
                    if msg['time'] <= snapshot_time
                )

                # CRITICAL FIX: Handle window reset edge case
                # When delta > total, the time range spans a window reset:
                # - Time range includes activity from OLD window (large delta)
                # - Bucket only contains NEW window messages (small total)
                # Fix: Cap delta to total to maintain invariant (delta <= total)
                if delta_tokens > total_tokens:
                    delta_tokens = total_tokens
                    delta_messages = total_messages

                # Prepare update
                updates.append({
                    'snapshot_id': snapshot_id,
                    'window_type': name,
                    'delta_tokens': delta_tokens,
                    'delta_messages': delta_messages,
                    'total_tokens': total_tokens,
                    'total_messages': total_messages
                })

    # Batch update database
    with get_db() as conn:
        cursor = conn.cursor()

        for update in updates:
            if update['window_type'] == '5h':
                cursor.execute("""
                    UPDATE usage_snapshots
                    SET five_hour_tokens_consumed = ?,
                        five_hour_messages_count = ?,
                        five_hour_tokens_total = ?,
                        five_hour_messages_total = ?
                    WHERE id = ?
                """, (
                    update['delta_tokens'],
                    update['delta_messages'],
                    update['total_tokens'],
                    update['total_messages'],
                    update['snapshot_id']
                ))
            else:  # '7d'
                cursor.execute("""
                    UPDATE usage_snapshots
                    SET seven_day_tokens_consumed = ?,
                        seven_day_messages_count = ?,
                        seven_day_tokens_total = ?,
                        seven_day_messages_total = ?
                    WHERE id = ?
                """, (
                    update['delta_tokens'],
                    update['delta_messages'],
                    update['total_tokens'],
                    update['total_messages'],
                    update['snapshot_id']
                ))

        conn.commit()

    # Count unique snapshots updated
    unique_snapshots = len(set(u['snapshot_id'] for u in updates))

    return (len(updates), unique_snapshots)


def detect_forks_from_buckets(bucket_types):
    """
    Detect conversation forks from messages stored in buckets.

    This function:
    1. Collects all messages with metadata from all buckets
    2. Builds a parent_uuid -> children map
    3. Detects parents with 2+ children (forks)
    4. Stores detected forks in conversation_forks table

    Args:
        bucket_types: List of bucket type dicts with processed messages

    Returns:
        Number of forks detected and stored
    """
    try:
        from .database import get_db
    except ImportError:
        from database import get_db

    # Build parent -> children map and uuid -> message map
    parent_to_children = {}
    message_by_uuid = {}

    # Collect all messages from all buckets
    for bucket_type in bucket_types:
        buckets = bucket_type.get('buckets', {})

        for bucket_key, bucket in buckets.items():
            messages = bucket.get('messages', [])

            for msg in messages:
                # Only process messages with full metadata
                if 'uuid' not in msg or 'parentUuid' not in msg:
                    continue

                uuid = msg['uuid']
                parent_uuid = msg['parentUuid']

                # Store message data for later lookup
                message_by_uuid[uuid] = msg

                # Build parent -> children map
                if parent_uuid:
                    if parent_uuid not in parent_to_children:
                        parent_to_children[parent_uuid] = []

                    # Only add child if not already in list (deduplication)
                    if uuid not in parent_to_children[parent_uuid]:
                        parent_to_children[parent_uuid].append(uuid)

    # Detect forks (parents with 2+ children)
    detected_forks = set()
    forks_stored = 0

    with get_db() as conn:
        cursor = conn.cursor()

        for parent_uuid, children_uuids in parent_to_children.items():
            # Fork detected: parent has 2+ children
            if len(children_uuids) < 2:
                continue

            # Skip if already processed
            if parent_uuid in detected_forks:
                continue

            detected_forks.add(parent_uuid)

            # Get parent and second child (the fork point)
            parent_msg = message_by_uuid.get(parent_uuid, {})
            second_child_msg = message_by_uuid.get(children_uuids[1], {}) if len(children_uuids) > 1 else {}

            parent_session_id = parent_msg.get('sessionId')
            child_session_id = second_child_msg.get('sessionId')
            fork_timestamp = second_child_msg.get('timestamp')

            # Validate required fields
            if not all([parent_session_id, child_session_id, fork_timestamp]):
                continue

            try:
                # Store fork in database
                cursor.execute("""
                    INSERT OR IGNORE INTO conversation_forks (
                        parent_uuid, parent_session_id,
                        child_uuid, child_session_id,
                        fork_timestamp, message_uuid
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    parent_uuid, parent_session_id,
                    children_uuids[1], child_session_id,
                    fork_timestamp, parent_uuid
                ))

                if cursor.rowcount > 0:
                    forks_stored += 1

            except Exception as e:
                # Log error but continue processing other forks
                print(f"Error storing fork {parent_uuid[:8]}: {e}")
                continue

        conn.commit()

    return forks_stored


def get_bucket_types_for_assignment(window_types=None):
    """
    Get bucket type configurations for the assignment algorithm.

    Converts database snapshot data into the format expected by
    process_messages_from_jsonl().

    Args:
        window_types: List of window types to include (default: ["five_hour", "seven_day"])

    Returns:
        List of bucket_type dicts, each containing:
        - 'name': Window type name (e.g., "5h", "7d")
        - 'duration': Bucket duration in seconds
        - 'buckets': Dict of bucket_key -> bucket_data
        - 'time_ranges': List of time range dicts
    """
    if window_types is None:
        window_types = ["five_hour", "seven_day"]

    bucket_types = []

    for window_type in window_types:
        # Get bucket ranges
        bucket_ranges = get_bucket_ranges(window_type)

        if not bucket_ranges:
            continue

        # Build buckets dict with keys that uniquely identify each bucket
        # Key format: "duration:reset_time" - uniquely identifies each 5h/7d window
        # Each unique reset_time creates exactly ONE bucket
        duration_seconds = bucket_ranges[0]['duration']
        buckets = {}

        for bucket_range in bucket_ranges:
            start = bucket_range['start']
            end = bucket_range['end']
            reset_time = bucket_range['reset_time']

            # Use reset_time in key to ensure uniqueness across overlapping buckets
            bucket_key = f"{duration_seconds}:{reset_time}"
            buckets[bucket_key] = {
                'start': start,
                'end': end,
                'reset_time': reset_time
            }

        # Fix overlapping buckets: When reset time changes (e.g., account upgrade),
        # truncate the older bucket to end when the newer one starts
        buckets = fix_overlapping_buckets(buckets, duration_seconds)

        # Get time ranges grouped by bucket
        time_ranges_by_bucket = get_time_ranges(window_type)

        # Validate each bucket's time ranges individually for overlaps
        # (Ranges from different buckets CAN overlap, but ranges within
        # the same bucket should not)
        for reset_time, ranges in time_ranges_by_bucket.items():
            ranges.sort(key=lambda x: x['start'])
            for i in range(len(ranges) - 1):
                curr = ranges[i]
                next_range = ranges[i + 1]
                if curr['end'] > next_range['start']:
                    raise BucketAssignmentError(
                        f"Time range overlap within bucket {reset_time}! "
                        f"Range {i} [{curr['start']}, {curr['end']}) "
                        f"overlaps with Range {i+1} [{next_range['start']}, {next_range['end']})"
                    )

        # Flatten time ranges (all ranges across all buckets for this window type)
        # Note: Ranges from different buckets CAN overlap - this is expected!
        all_time_ranges = []
        for reset_time, ranges in time_ranges_by_bucket.items():
            all_time_ranges.extend(ranges)

        # Sort by start time
        all_time_ranges.sort(key=lambda x: x['start'])

        # Determine name
        name = "5h" if window_type == "five_hour" else "7d"

        bucket_types.append({
            'name': name,
            'duration': duration_seconds,
            'buckets': buckets,
            'time_ranges': all_time_ranges,
            'time_ranges_by_bucket': time_ranges_by_bucket  # Extra metadata
        })

    return bucket_types