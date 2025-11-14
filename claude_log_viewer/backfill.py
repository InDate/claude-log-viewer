"""
Backfill module for recalculating NULL usage snapshots.

This module uses the bucket assignment algorithm:
1. Load bucket types and time ranges from database
2. Stream through JSONL files once
3. Assign messages to buckets in a single pass
4. Calculate deltas and window totals
5. Detect conversation forks
6. Update database with calculated statistics
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from .activities_to_buckets import (
    get_bucket_types_for_assignment,
    process_messages_from_jsonl,
    update_snapshots_with_bucket_statistics,
    detect_forks_from_buckets
)

logger = logging.getLogger(__name__)


def check_null_snapshots() -> Dict[str, int]:
    """
    Count snapshots with NULL calculated fields.

    Returns:
        dict with:
        - five_hour_nulls: Count of 5h snapshots with NULLs
        - seven_day_nulls: Count of 7d snapshots with NULLs
        - total_nulls: Total count
    """
    from .database import get_db

    with get_db() as conn:
        cursor = conn.cursor()

        # Count 5-hour NULLs
        cursor.execute("""
            SELECT COUNT(*) FROM usage_snapshots
            WHERE five_hour_tokens_consumed IS NULL
        """)
        five_hour_nulls = cursor.fetchone()[0]

        # Count 7-day NULLs
        cursor.execute("""
            SELECT COUNT(*) FROM usage_snapshots
            WHERE seven_day_tokens_consumed IS NULL
        """)
        seven_day_nulls = cursor.fetchone()[0]

    return {
        'five_hour_nulls': five_hour_nulls,
        'seven_day_nulls': seven_day_nulls,
        'total_nulls': five_hour_nulls + seven_day_nulls
    }


def backfill_all_snapshots_async(
    claude_projects_dir: Path,
    callback=None
) -> Dict[str, any]:
    """
    Backfill all NULL snapshots using bucket assignment algorithm.

    Algorithm:
    1. Load bucket types and time ranges from database
    2. Stream through JSONL files once
    3. Assign messages to buckets in a single pass
    4. Calculate deltas and window totals from buckets
    5. Detect conversation forks from message metadata
    6. Update usage_snapshots table with calculated statistics

    Args:
        claude_projects_dir: Path to ~/.claude/projects directory
        callback: Optional callback function called with progress updates
                  Called with dict containing 'stage' and 'message' keys
                  Stages: 'loading', 'processing', 'complete'

    Returns:
        dict with:
        - success: True if backfill completed
        - snapshots_updated: Number of snapshot records updated
        - forks_detected: Number of conversation forks detected
        - total_time_seconds: Time taken
        - messages_processed: Number of messages processed
    """
    start_time = datetime.now()
    logger.info("Starting backfill process...")

    # Step 1: Check for NULL snapshots
    null_counts = check_null_snapshots()

    logger.info(
        f"Found {null_counts['total_nulls']} snapshots needing backfill "
        f"(5h: {null_counts['five_hour_nulls']}, 7d: {null_counts['seven_day_nulls']})"
    )

    if null_counts['total_nulls'] == 0:
        logger.info("No snapshots need backfill")
        return {
            'success': True,
            'snapshots_updated': 0,
            'forks_detected': 0,
            'total_time_seconds': 0,
            'messages_processed': 0
        }

    if callback:
        callback({
            'stage': 'loading',
            'message': f"Loading bucket types and time ranges from database..."
        })

    # Step 2: Load bucket types from database
    try:
        bucket_types = get_bucket_types_for_assignment(['five_hour', 'seven_day'])
        logger.info(f"Loaded {len(bucket_types)} bucket types")
    except Exception as e:
        logger.error(f"Error loading bucket types: {e}")
        return {
            'success': False,
            'error': str(e),
            'total_time_seconds': (datetime.now() - start_time).total_seconds()
        }

    # Step 3: Process JSONL files with bucket assignment
    try:
        coverage_stats, processing_stats = process_messages_from_jsonl(
            claude_projects_dir=claude_projects_dir,
            bucket_types=bucket_types,
            verbose=False,
            return_stats=True,
            callback=callback
        )

        messages_processed = processing_stats['processed_messages']
        logger.info(f"Processed {messages_processed} messages from {processing_stats['processed_files']} files")

    except Exception as e:
        logger.error(f"Error processing messages: {e}")
        return {
            'success': False,
            'error': str(e),
            'total_time_seconds': (datetime.now() - start_time).total_seconds()
        }

    if callback:
        callback({
            'stage': 'processing',
            'message': f"Updating database with calculated statistics..."
        })

    # Step 4: Update database with calculated statistics
    try:
        updates_applied, snapshots_updated = update_snapshots_with_bucket_statistics(bucket_types)
        logger.info(f"Updated {snapshots_updated} snapshot records ({updates_applied} total updates)")
    except Exception as e:
        logger.error(f"Error updating database: {e}")
        return {
            'success': False,
            'error': str(e),
            'messages_processed': messages_processed,
            'total_time_seconds': (datetime.now() - start_time).total_seconds()
        }

    if callback:
        callback({
            'stage': 'processing',
            'message': f"Detecting conversation forks..."
        })

    # Step 5: Detect and store conversation forks
    try:
        forks_detected = detect_forks_from_buckets(bucket_types)
        logger.info(f"Detected and stored {forks_detected} conversation forks")
    except Exception as e:
        logger.error(f"Error detecting forks: {e}")
        forks_detected = 0  # Continue even if fork detection fails

    end_time = datetime.now()
    total_time = (end_time - start_time).total_seconds()

    logger.info(f"Backfill completed in {total_time:.2f} seconds")

    if callback:
        callback({
            'stage': 'complete',
            'message': f"Backfill complete in {total_time:.2f}s"
        })

    return {
        'success': True,
        'snapshots_updated': snapshots_updated,
        'forks_detected': forks_detected,
        'total_time_seconds': total_time,
        'messages_processed': messages_processed,
        'updates_applied': updates_applied
    }
