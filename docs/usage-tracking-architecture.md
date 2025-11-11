# Usage Tracking System Architecture

**Version:** 1.0
**Date:** November 2025
**Status:** Design Specification

---

## Table of Contents

1. [Overview](#1-overview)
2. [Requirements](#2-requirements)
3. [Constraints](#3-constraints)
4. [Core Concepts](#4-core-concepts)
5. [System Architecture](#5-system-architecture)
6. [Data Flow](#6-data-flow)
7. [Algorithms](#7-algorithms)
8. [Edge Cases](#8-edge-cases)
9. [Database Schema](#9-database-schema)
10. [Repopulation Strategy](#10-repopulation-strategy)
11. [Testing Strategy](#11-testing-strategy)
12. [Future Improvements](#12-future-improvements)

---

## 1. Overview

### Purpose

The Usage Tracking System monitors API consumption of Claude Code users by tracking token usage and message counts over sliding time windows. It provides users with visibility into their consumption patterns to help manage usage limits and understand billing.

### What It Does

- **Polls** the Anthropic OAuth API periodically to fetch current usage percentages
- **Counts** tokens and messages from local JSONL conversation logs
- **Stores** snapshots of usage data whenever consumption increases
- **Displays** historical usage trends in a web interface

### What It Does NOT Do

- Does not enforce rate limits (API handles that)
- Does not predict future usage
- Does not track costs (only tokens and messages)
- Does not sync across multiple machines

---

## 2. Requirements

### User Story

**As a** Claude Code user
**I want to** see my API usage (tokens and messages) over time
**So that** I can understand my consumption patterns and avoid hitting rate limits

### Functional Requirements

#### FR1: Display Historical Usage
- Show table of usage snapshots with timestamps
- Each row displays 5-hour and 7-day window data
- For each window show: percentage utilization, token counts, message counts

#### FR2: Track Incremental Consumption
- Capture "delta" - tokens/messages consumed since last snapshot
- Capture "total" - tokens/messages currently in the sliding window

#### FR3: Detect Window Resets
- Identify when sliding windows reset (resets_at timestamp changes)
- Handle reset correctly in calculations

#### FR4: Handle Partial Data
- Function correctly when JSONL logs don't cover full window period
- Handle gracefully when logs are deleted or unavailable

#### FR5: Survive Restarts
- Persist snapshots to SQLite database
- Resume tracking correctly after application restart

#### FR6: Offline Recalculation (CRITICAL)
- **Must be able to recalculate all totals offline** as far back as we have API usage results
- Given: database with historical snapshots containing timestamps, percentages, and reset_at times
- Given: JSONL logs on disk with message content and timestamps
- Output: Recalculated token totals and message totals for all historical snapshots
- Purpose: Fix bugs in calculation logic, apply algorithm changes, handle data corruption
- Constraint: Cannot query API for historical data (API only returns current state)
- Requirement: The algorithm must be deterministic and reproducible from stored data alone

**Why This Is Critical:**
- API only provides current percentages, not historical absolute counts
- We must be able to reconstruct the entire history from what we've recorded
- Bug fixes in calculation logic must be applicable to old data
- Users need accurate historical data for billing analysis and auditing

**What This Means for Design:**
- Every snapshot must store sufficient data for recalculation: timestamp, percentage, reset_at
- Calculation algorithm must be based only on: API data we stored + JSONL logs
- Cannot rely on "previous total" being correct (it might have been calculated with buggy logic)
- Must be able to detect resets from stored reset_at timestamps alone

### Non-Functional Requirements

#### NFR1: Accuracy
- Token counts must match actual API consumption within ±5%
- No double-counting of tokens across snapshots

#### NFR2: Performance
- Polling overhead < 200ms
- Calculation overhead < 100ms
- Database queries < 50ms

#### NFR3: Reliability
- Handle API failures gracefully (timeouts, rate limits)
- Recover from incomplete JSONL files
- Maintain data integrity across crashes

---

## 3. Constraints

### API Constraints

The Anthropic OAuth API provides limited information:

**What the API Gives Us:**
- `utilization`: Percentage (0.0 to 100.0) of limit consumed
- `resets_at`: ISO timestamp when window will reset

**What the API Does NOT Give Us:**
- Absolute token counts
- Message counts
- Historical snapshots
- Change events

**Implications:**
- We must calculate counts ourselves from local JSONL logs
- We cannot know exact limits (only percentages)
- We cannot backfill historical data if logs are missing

### Window Semantics

Usage windows are **SLIDING** (also called ROLLING):

**5-Hour Window:**
- Covers the 5 hours immediately preceding `resets_at`
- Window start: `resets_at - 5 hours`
- Window end: `resets_at`

**7-Day Window:**
- Covers the 7 days immediately preceding `resets_at`
- Window start: `resets_at - 7 days`
- Window end: `resets_at`

**Window Reset Behavior:**
When a window resets:
1. Old `resets_at` is discarded
2. New `resets_at` is set to current time + window duration
3. Tokens older than new window start fall out of the window
4. Percentage drops to only include recent consumption

**Critical Insight:** Windows are NOT fixed intervals like "1pm to 6pm". They slide forward continuously. When the API says "5-hour window resets at 2pm", it means the window currently covers "9am to 2pm", and will start sliding forward after 2pm.

### Polling Behavior

**When Polling Occurs:**
- When user makes Claude API calls (triggers usage check)
- Application polls API in response to user activity
- NO background polling when user is idle

**Snapshot Creation Triggers:**
- API returns different percentage than last poll
- API returns different `resets_at` than last poll

**What This Means:**
- We only see usage at discrete polling moments
- We might miss the exact moment a reset happens
- Long gaps between polls (hours/days) are normal during inactivity

### Data Availability

**JSONL Logs:**
- Stored in `~/.claude/projects/*/transcript.jsonl`
- One file per conversation session
- May be deleted by user at any time
- May only go back days/weeks, not months

**In-Memory Cache:**
- Holds last N entries (default 500)
- Cleared on application restart
- May not contain full 7-day history

**Implication:** We must gracefully handle missing data. If logs only go back 2 days, 7-day totals will be underestimated.

---

## 4. Core Concepts

### Snapshot

**Definition:** A point-in-time record of usage data captured when we poll the API.

**Contains:**
- **Timestamp:** When this snapshot was created (ISO 8601)
- **Percentages:** API-reported utilization for both windows
- **Reset Times:** When each window will reset
- **Deltas:** Tokens/messages consumed since previous snapshot
- **Totals:** Tokens/messages currently in the window

**When Created:**
- Percentage increased since last snapshot
- Window reset detected (resets_at changed)

**NOT Created When:**
- Percentage unchanged
- No polling activity (user idle)

### Delta

**Definition:** The consumption that occurred BETWEEN two snapshots.

**Time Range:**
```
Delta(N) = consumption from timestamp(N-1) to timestamp(N)
```

**What It Measures:**
"How much did I consume since the last time we checked?"

**Calculation:**
1. Start: timestamp of previous snapshot (N-1)
2. End: timestamp of current snapshot (N)
3. Count all messages/tokens with timestamps in range [start, end)

**Important:** Delta includes ALL tokens in that time range, regardless of which window they fall into. If a reset happened between snapshots, delta includes tokens from both old and new windows.

**Example:**
```
Snapshot N-1: 2025-11-10T10:00:00Z
Snapshot N:   2025-11-10T10:05:00Z

Delta = tokens from messages timestamped 10:00:00 to 10:05:00
```

### Total

**Definition:** The amount of consumption CURRENTLY IN THE WINDOW at snapshot time.

**Time Range:**
```
Total(N) = consumption within window boundaries at timestamp(N)
Window start = resets_at - window_duration
Window end = timestamp(N)
```

**What It Measures:**
"How much is in the sliding window right now?"

**Calculation Method 1 (Incremental):**
```
If no reset:
  Total(N) = Total(N-1) + Delta(N)

If reset occurred:
  Total(N) = count tokens in new window
  Window start = new_resets_at - window_duration
  Window end = timestamp(N)
```

**Calculation Method 2 (From Scratch):**
```
Total(N) = count all tokens where:
  timestamp >= (resets_at - window_duration)
  AND timestamp <= snapshot_timestamp
```

**Important:** Total only includes tokens within window boundaries. Old tokens outside the window are excluded.

### Reset

**Definition:** Event when the sliding window moves forward, discarding old consumption.

**Detection:**
```python
reset_occurred = (current_resets_at != previous_resets_at)
```

**Effects:**
1. Old tokens fall out of window
2. Percentage drops (only recent consumption remains)
3. Total must be recalculated from new window start
4. Delta still counts ALL tokens since last snapshot (including pre-reset)

**Why Delta Includes Pre-Reset Tokens:**
Delta measures "what did I consume since last check", not "what's in the window". If I consumed 1000 tokens right before a reset, and 500 tokens after, my delta is 1500 (what I consumed), but my total is 500 (what's in the new window).

---

## 5. System Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     Flask Web Application                    │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐      ┌───────────────┐                    │
│  │  API Poller  │─────>│   Snapshot    │                    │
│  │              │      │   Creator     │                    │
│  └──────────────┘      └───────────────┘                    │
│         │                      │                             │
│         │                      v                             │
│         │              ┌───────────────┐                    │
│         │              │     Reset     │                    │
│         │              │   Detector    │                    │
│         │              └───────────────┘                    │
│         │                      │                             │
│         v                      v                             │
│  ┌──────────────┐      ┌───────────────┐                    │
│  │   Anthropic  │      │     Delta     │                    │
│  │  OAuth API   │      │  Calculator   │                    │
│  └──────────────┘      └───────────────┘                    │
│                                │                             │
│                                v                             │
│                        ┌───────────────┐                    │
│                        │     Total     │                    │
│                        │  Calculator   │                    │
│                        └───────────────┘                    │
│                                │                             │
│                                v                             │
│                        ┌───────────────┐                    │
│                        │  Data Loader  │                    │
│                        └───────────────┘                    │
│                                │                             │
└────────────────────────────────┼─────────────────────────────┘
                                 │
                                 v
                    ┌────────────────────────┐
                    │   SQLite Database      │
                    │  usage_snapshots table │
                    └────────────────────────┘
                                 ^
                                 │
                    ┌────────────────────────┐
                    │   JSONL Log Files      │
                    │ ~/.claude/projects/*   │
                    └────────────────────────┘
```

### Component Responsibilities

#### 1. API Poller

**Purpose:** Fetch current usage data from Anthropic OAuth API

**Inputs:** None (triggered by application events)

**Outputs:**
- `utilization` percentages for both windows
- `resets_at` timestamps for both windows

**Behavior:**
```python
def poll_api():
    response = requests.get(
        'https://api.anthropic.com/api/oauth/usage',
        headers={'Authorization': f'Bearer {token}'}
    )
    return {
        'five_hour': {
            'utilization': float,
            'resets_at': str  # ISO 8601
        },
        'seven_day': {
            'utilization': float,
            'resets_at': str
        }
    }
```

**Error Handling:**
- HTTP timeout: Return cached data, log warning
- 401 Unauthorized: Prompt for re-authentication
- 429 Rate Limited: Backoff and retry
- 5xx Server Error: Return cached data, log error

#### 2. Snapshot Creator

**Purpose:** Decide if a new snapshot is needed and coordinate its creation

**Inputs:**
- Current API data (percentages, reset times)
- Previous snapshot (from database)

**Outputs:**
- Boolean: should_create_snapshot
- If true: triggers Delta/Total calculations

**Logic:**
```python
def should_create_snapshot(current_data, previous_snapshot):
    if previous_snapshot is None:
        return True  # First snapshot ever

    # Check 5-hour window
    if (current_data['five_hour']['utilization'] !=
        previous_snapshot['five_hour_pct']):
        return True

    if (current_data['five_hour']['resets_at'] !=
        previous_snapshot['five_hour_reset']):
        return True

    # Check 7-day window
    if (current_data['seven_day']['utilization'] !=
        previous_snapshot['seven_day_pct']):
        return True

    if (current_data['seven_day']['resets_at'] !=
        previous_snapshot['seven_day_reset']):
        return True

    return False  # No changes
```

#### 3. Reset Detector

**Purpose:** Determine if a window reset occurred

**Inputs:**
- `current_resets_at`: timestamp from current API response
- `previous_resets_at`: timestamp from previous snapshot

**Outputs:**
- Boolean: reset_occurred

**Logic:**
```python
def detect_reset(current_resets_at, previous_resets_at):
    if previous_resets_at is None:
        return False  # First snapshot, no reset

    return current_resets_at != previous_resets_at
```

**Special Cases:**
- First snapshot: No previous reset time → not a reset
- Missing data: previous_resets_at is None → treat as no reset

#### 4. Delta Calculator

**Purpose:** Count tokens and messages consumed since last snapshot

**Inputs:**
- `baseline_timestamp`: timestamp of previous snapshot
- `current_timestamp`: timestamp of current snapshot
- JSONL entries (from memory or disk)

**Outputs:**
```python
{
    'tokens': int,      # Total tokens in time range
    'messages': int,    # Total messages in time range
}
```

**Algorithm:**
```python
def calculate_delta(baseline_timestamp, current_timestamp):
    tokens = 0
    messages = 0

    for entry in load_entries_in_range(baseline_timestamp, current_timestamp):
        if entry['type'] in ['user', 'assistant']:
            messages += 1

            usage = entry.get('usage', {})
            tokens += usage.get('inputTokens', 0)
            tokens += usage.get('outputTokens', 0)

    return {'tokens': tokens, 'messages': messages}
```

**Data Loading:**
- Check in-memory cache first
- If entry not in cache, load from JSONL file
- Filter entries by timestamp range
- Handle missing files gracefully (return 0, log warning)

#### 5. Total Calculator

**Purpose:** Calculate tokens and messages currently in the window

**Inputs:**
- `reset_occurred`: Boolean from Reset Detector
- `window_duration_hours`: 5 or 168 (7 days)
- `resets_at`: Current window reset time
- `current_timestamp`: Current snapshot timestamp
- Previous total (if no reset)
- Current delta

**Outputs:**
```python
{
    'total_tokens': int,
    'total_messages': int
}
```

**Algorithm:**

**Method 1: Incremental (Preferred)**
```python
def calculate_total_incremental(reset_occurred, previous_total, delta):
    if reset_occurred:
        # Cannot trust previous total - must recalculate
        return calculate_total_from_scratch()
    else:
        # Add delta to previous total
        return {
            'total_tokens': previous_total['tokens'] + delta['tokens'],
            'total_messages': previous_total['messages'] + delta['messages']
        }
```

**Method 2: From Scratch (Reset Case)**
```python
def calculate_total_from_scratch(resets_at, window_duration_hours, current_timestamp):
    window_start = resets_at - timedelta(hours=window_duration_hours)

    tokens = 0
    messages = 0

    for entry in load_entries_in_range(window_start, current_timestamp):
        if entry['type'] in ['user', 'assistant']:
            messages += 1

            usage = entry.get('usage', {})
            tokens += usage.get('inputTokens', 0)
            tokens += usage.get('outputTokens', 0)

    return {'total_tokens': tokens, 'total_messages': messages}
```

**Which Method to Use:**
- No reset: Use incremental (faster, no I/O)
- Reset occurred: Use from-scratch (accurate, handles window shift)

#### 6. Data Loader

**Purpose:** Load JSONL entries for a given time range

**Inputs:**
- `start_timestamp`: ISO 8601 string
- `end_timestamp`: ISO 8601 string

**Outputs:**
- List of entry dictionaries

**Algorithm:**
```python
def load_entries_in_range(start_timestamp, end_timestamp):
    entries = []

    # Convert timestamps to datetime
    start_dt = datetime.fromisoformat(start_timestamp.replace('Z', '+00:00'))
    end_dt = datetime.fromisoformat(end_timestamp.replace('Z', '+00:00'))

    # Check in-memory cache
    for entry in memory_cache:
        entry_dt = datetime.fromisoformat(entry['timestamp'].replace('Z', '+00:00'))
        if start_dt <= entry_dt <= end_dt:
            entries.append(entry)

    # If cache doesn't cover range, load from disk
    if not has_complete_coverage(entries, start_dt, end_dt):
        disk_entries = load_from_jsonl_files(start_dt, end_dt)
        entries.extend(disk_entries)

    # Sort by timestamp
    entries.sort(key=lambda e: e['timestamp'])

    return entries
```

**File Discovery:**
```python
def load_from_jsonl_files(start_dt, end_dt):
    projects_dir = Path.home() / '.claude' / 'projects'
    entries = []

    for jsonl_file in projects_dir.glob('**/*.jsonl'):
        # Check file modification time to avoid reading old files
        if jsonl_file.stat().st_mtime < start_dt.timestamp():
            continue

        with open(jsonl_file) as f:
            for line in f:
                entry = json.loads(line)
                entry_dt = datetime.fromisoformat(entry['timestamp'].replace('Z', '+00:00'))

                if start_dt <= entry_dt <= end_dt:
                    entries.append(entry)

    return entries
```

---

## 6. Data Flow

### Critical Design Decision: When to Calculate Deltas

**IMPORTANT:** Delta and total calculations must happen **AFTER** recording the new API tick (snapshot) to the database, not before.

**Why This Matters:**

1. **API Data is the Source of Truth**
   - The percentage and reset_at from the API are the authoritative values
   - These must be persisted immediately, before any calculations
   - If calculations fail, we still have the raw API data

2. **Calculations Can Be Redone**
   - Given: timestamps and reset_at values in database
   - Given: JSONL logs on disk
   - We can recalculate deltas and totals at any time
   - This enables offline recalculation (FR6)

3. **Separation of Concerns**
   - Polling: Record what the API said
   - Calculation: Derive deltas and totals from recorded data
   - These are independent operations

**Correct Flow:**
```
1. Poll API → get percentage, reset_at
2. Store snapshot with: timestamp, percentage, reset_at
3. THEN calculate delta from previous snapshot
4. THEN calculate total (incremental or from-scratch)
5. Update snapshot with: delta, total
```

**Wrong Flow (Don't Do This):**
```
1. Poll API → get percentage, reset_at
2. Calculate delta and total
3. Store snapshot with everything at once
   ❌ If calculation fails, we lose the API data
   ❌ Can't recalculate later with different logic
```

**Implementation Implication:**
The `/api/usage` endpoint should:
1. Record the API response as a "tick" (timestamp + percentages + reset_at)
2. Return success immediately
3. Trigger async calculation job to fill in deltas and totals
4. The calculation job can fail/retry without losing the tick data

**Database Implications:**
- Deltas and totals should be NULLABLE columns
- A snapshot with NULL deltas means "tick recorded, calculations pending"
- Repopulation script can fill in NULLs by recalculating

### Scenario 1: Normal Increment (No Reset)

```
Time: 10:00 AM
Previous Snapshot:
  - timestamp: 2025-11-10T09:50:00Z
  - five_hour_pct: 15.0%
  - five_hour_tokens_total: 5000
  - five_hour_reset: 2025-11-10T14:00:00Z

User sends message (500 tokens)

API Poll at 10:00 AM:
  - five_hour_pct: 16.5%
  - five_hour_reset: 2025-11-10T14:00:00Z

Step 1: Snapshot Creator
  → Percentage changed (15.0% → 16.5%)
  → Create new snapshot

Step 2: Reset Detector
  → resets_at unchanged
  → NO reset

Step 3: Delta Calculator
  → baseline: 09:50:00
  → current: 10:00:00
  → Count tokens in range
  → Result: 500 tokens, 1 message

Step 4: Total Calculator (Incremental)
  → previous_total: 5000 tokens
  → delta: 500 tokens
  → total = 5000 + 500 = 5500 tokens

Step 5: Save Snapshot
  - timestamp: 2025-11-10T10:00:00Z
  - five_hour_pct: 16.5%
  - five_hour_tokens_consumed: 500 (delta)
  - five_hour_tokens_total: 5500 (total)
  - five_hour_reset: 2025-11-10T14:00:00Z
```

### Scenario 2: Window Reset

```
Time: 2:00 PM (window reset time)
Previous Snapshot:
  - timestamp: 2025-11-10T13:55:00Z
  - five_hour_pct: 45.0%
  - five_hour_tokens_total: 15000
  - five_hour_reset: 2025-11-10T14:00:00Z

Window resets at 2:00 PM

User sends message at 2:05 PM (500 tokens)

API Poll at 2:05 PM:
  - five_hour_pct: 2.0%  (dropped!)
  - five_hour_reset: 2025-11-10T19:00:00Z  (changed!)

Step 1: Snapshot Creator
  → Percentage changed (45.0% → 2.0%)
  → resets_at changed
  → Create new snapshot

Step 2: Reset Detector
  → resets_at changed (14:00 → 19:00)
  → RESET OCCURRED

Step 3: Delta Calculator
  → baseline: 13:55:00
  → current: 14:05:00
  → Count ALL tokens in range (includes pre-reset)
  → Result: 500 tokens, 1 message

Step 4: Total Calculator (From Scratch)
  → window_start = 19:00:00 - 5h = 14:00:00
  → window_end = 14:05:00
  → Count tokens in [14:00:00, 14:05:00]
  → Result: 500 tokens (only post-reset)

Step 5: Save Snapshot
  - timestamp: 2025-11-10T14:05:00Z
  - five_hour_pct: 2.0%
  - five_hour_tokens_consumed: 500 (delta - what I consumed)
  - five_hour_tokens_total: 500 (total - what's in new window)
  - five_hour_reset: 2025-11-10T19:00:00Z (new reset time)
```

### Scenario 3: First Snapshot Ever

```
Time: 10:00 AM (application first run)

API Poll:
  - five_hour_pct: 25.0%
  - five_hour_reset: 2025-11-10T14:00:00Z

Step 1: Snapshot Creator
  → No previous snapshot
  → Create first snapshot

Step 2: Reset Detector
  → No previous reset time
  → NOT a reset (just initialization)

Step 3: Delta Calculator
  → No baseline timestamp
  → Cannot calculate delta
  → Result: None

Step 4: Total Calculator (From Scratch)
  → window_start = 14:00:00 - 5h = 09:00:00
  → window_end = 10:00:00
  → Count all tokens in [09:00:00, 10:00:00]
  → Result: 8000 tokens, 12 messages

Step 5: Save Snapshot
  - timestamp: 2025-11-10T10:00:00Z
  - five_hour_pct: 25.0%
  - five_hour_tokens_consumed: None (no delta)
  - five_hour_tokens_total: 8000
  - five_hour_reset: 2025-11-10T14:00:00Z
```

---

## 7. Algorithms

### Master Algorithm: Process API Response

```python
def process_api_response(api_data):
    """
    Main entry point for usage tracking.
    Called whenever API returns new data.
    """
    current_timestamp = datetime.utcnow().isoformat() + 'Z'
    previous_snapshot = get_latest_snapshot()

    # Check if we need a snapshot
    if not should_create_snapshot(api_data, previous_snapshot):
        return  # No changes, exit

    # Process each window independently
    for window in ['five_hour', 'seven_day']:
        process_window(window, api_data, previous_snapshot, current_timestamp)


def process_window(window_name, api_data, previous_snapshot, current_timestamp):
    """
    Process a single usage window (5-hour or 7-day).
    """
    window_hours = 5 if window_name == 'five_hour' else 168

    # Extract current data
    current_pct = api_data[window_name]['utilization']
    current_reset = api_data[window_name]['resets_at']

    # Extract previous data
    if previous_snapshot:
        previous_pct = previous_snapshot[f'{window_name}_pct']
        previous_reset = previous_snapshot[f'{window_name}_reset']
        previous_total_tokens = previous_snapshot[f'{window_name}_tokens_total']
        previous_total_messages = previous_snapshot[f'{window_name}_messages_total']
        baseline_timestamp = previous_snapshot['timestamp']
    else:
        previous_pct = None
        previous_reset = None
        previous_total_tokens = 0
        previous_total_messages = 0
        baseline_timestamp = None

    # Detect if percentage or reset changed
    pct_changed = (previous_pct is None or current_pct != previous_pct)
    reset_changed = (previous_reset is None or current_reset != previous_reset)

    if not (pct_changed or reset_changed):
        return  # This window hasn't changed

    # Detect reset
    reset_occurred = detect_reset(current_reset, previous_reset)

    # Calculate delta (if we have baseline)
    if baseline_timestamp:
        delta = calculate_delta(baseline_timestamp, current_timestamp)
    else:
        delta = {'tokens': None, 'messages': None}

    # Calculate total
    if reset_occurred:
        # Recalculate from scratch
        total = calculate_total_from_scratch(
            current_reset,
            window_hours,
            current_timestamp
        )
    else:
        # Incremental update
        if previous_total_tokens is not None and delta['tokens'] is not None:
            total = {
                'total_tokens': previous_total_tokens + delta['tokens'],
                'total_messages': previous_total_messages + delta['messages']
            }
        else:
            # First snapshot - calculate from scratch
            total = calculate_total_from_scratch(
                current_reset,
                window_hours,
                current_timestamp
            )

    # Store results
    save_window_data(
        window_name,
        current_timestamp,
        current_pct,
        current_reset,
        delta,
        total
    )
```

### Algorithm: Calculate Delta

```python
def calculate_delta(baseline_timestamp, current_timestamp):
    """
    Count tokens and messages consumed in time range.

    Args:
        baseline_timestamp: Start of range (ISO 8601 string)
        current_timestamp: End of range (ISO 8601 string)

    Returns:
        {'tokens': int, 'messages': int}
    """
    # Load entries in range
    entries = load_entries_in_range(baseline_timestamp, current_timestamp)

    # Count tokens and messages
    total_tokens = 0
    total_messages = 0

    for entry in entries:
        # Only count user and assistant messages
        if entry.get('type') not in ['user', 'assistant']:
            continue

        # Count message
        total_messages += 1

        # Count tokens
        usage = entry.get('usage', {})
        input_tokens = usage.get('inputTokens', 0)
        output_tokens = usage.get('outputTokens', 0)
        total_tokens += input_tokens + output_tokens

    return {
        'tokens': total_tokens,
        'messages': total_messages
    }
```

### Algorithm: Calculate Total (From Scratch)

```python
def calculate_total_from_scratch(resets_at, window_duration_hours, current_timestamp):
    """
    Count tokens and messages currently in window.

    Args:
        resets_at: When window will reset (ISO 8601 string)
        window_duration_hours: Window size in hours (5 or 168)
        current_timestamp: Current time (ISO 8601 string)

    Returns:
        {'total_tokens': int, 'total_messages': int}
    """
    # Calculate window boundaries
    reset_dt = datetime.fromisoformat(resets_at.replace('Z', '+00:00'))
    window_start_dt = reset_dt - timedelta(hours=window_duration_hours)
    window_start = window_start_dt.isoformat().replace('+00:00', 'Z')

    # Count tokens in window
    return calculate_delta(window_start, current_timestamp)
```

### Algorithm: Detect Reset

```python
def detect_reset(current_resets_at, previous_resets_at):
    """
    Determine if window reset occurred.

    Args:
        current_resets_at: Current reset timestamp from API
        previous_resets_at: Previous reset timestamp from database

    Returns:
        Boolean
    """
    if previous_resets_at is None:
        return False  # First snapshot, not a reset

    return current_resets_at != previous_resets_at
```

---

## 8. Edge Cases

### Edge Case 1: First Snapshot Ever

**Scenario:** Application first run, no previous snapshots exist.

**Behavior:**
- Delta: Cannot calculate (no baseline) → store None
- Total: Calculate from window start to now
- Window start: `resets_at - window_duration`

**Handling:**
```python
if previous_snapshot is None:
    delta = None
    total = calculate_total_from_scratch(resets_at, window_hours, now)
```

### Edge Case 2: Missing JSONL Data

**Scenario:** User deleted old log files, data not available for full window.

**Behavior:**
- Calculate with available data
- Totals will be underestimated
- Log warning about missing data

**Handling:**
```python
try:
    entries = load_entries_in_range(start, end)
except FileNotFoundError:
    logger.warning(f"JSONL files missing for range {start} to {end}")
    entries = []  # Return 0 counts
```

**Mitigation:**
- Document that accuracy requires preserving JSONL files
- Provide warning in UI if data is incomplete
- Consider caching historical token counts in database

### Edge Case 3: Percentage Unchanged

**Scenario:** API returns same percentage as last poll.

**Behavior:**
- No snapshot created
- Exit early

**Handling:**
```python
if (current_pct == previous_pct and
    current_reset == previous_reset):
    return  # No changes, don't create snapshot
```

**Note:** This is not an error - it's normal when no consumption occurred.

### Edge Case 4: Multiple Resets Between Snapshots

**Scenario:** User idle for 10 hours, multiple resets occurred.

**Example:**
```
Last snapshot: 2025-11-10T08:00:00Z (reset at 13:00:00)
Next poll:     2025-11-10T18:00:00Z (reset at 23:00:00)

Window reset at 13:00, then again at 18:00
```

**Behavior:**
- We only see final state (reset at 23:00)
- Cannot reconstruct intermediate states
- Delta covers entire gap (8am to 6pm)
- Total only includes tokens since last reset (6pm to 6pm = 0)

**Handling:**
```python
# Detection works normally
reset_occurred = (current_reset != previous_reset)  # True

# Delta counts ALL tokens in gap
delta = calculate_delta('08:00:00Z', '18:00:00Z')

# Total only counts tokens in current window
window_start = '18:00:00Z'  # Last reset
total = calculate_delta('18:00:00Z', '18:00:00Z')  # 0 tokens
```

**Impact:** This is correct behavior. We accurately count consumption (delta) but total reflects current window state.

### Edge Case 5: Percentage Decreased Without Reset

**Scenario:** Percentage drops but `resets_at` unchanged.

**Example:**
```
Previous: 45.0%, reset at 14:00:00
Current:  30.0%, reset at 14:00:00
```

**Cause:** Tokens fell out of sliding window naturally (time passed).

**Behavior:**
- Percentage changed → create snapshot
- No reset detected → incremental calculation
- Delta may be 0 (no new tokens)
- Total = previous_total + delta (might be less than previous_total if we recalculate)

**Handling:**
```python
# This reveals a flaw in incremental approach!
# If tokens fall out naturally, incremental doesn't detect it.

# Solution: Always recalculate total from scratch
total = calculate_total_from_scratch(resets_at, window_hours, now)
```

**Important:** This edge case reveals that **incremental calculation is unreliable** for totals. We should always calculate total from scratch, not incrementally.

### Edge Case 6: Reset Detected But Percentage Increased

**Scenario:** Window reset AND user consumed tokens, both happened.

**Example:**
```
Previous: 45.0%, reset at 14:00:00
Current:  10.0%, reset at 19:00:00
```

**Behavior:**
- Reset detected: Yes
- Delta: Count ALL tokens since last snapshot (pre + post reset)
- Total: Count only tokens in NEW window

**Handling:**
```python
reset_occurred = True
delta = calculate_delta(previous_timestamp, current_timestamp)
total = calculate_total_from_scratch(new_reset, window_hours, now)
```

### Edge Case 7: Clock Skew

**Scenario:** System clock changes (DST, manual adjustment, NTP sync).

**Impact:**
- Timestamps become non-monotonic
- Range queries might exclude data

**Handling:**
```python
# Use ISO 8601 with timezone
# Convert to UTC before comparisons
dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))

# Handle negative ranges
if end_dt < start_dt:
    logger.error(f"Invalid time range: {start} to {end}")
    return []
```

### Edge Case 8: Concurrent Sessions

**Scenario:** User has multiple Claude Code windows open.

**Impact:**
- Multiple applications polling same API
- Race conditions in database writes
- May create duplicate snapshots with same timestamp

**Handling:**
```python
# Use database transaction with conflict resolution
with db.transaction():
    existing = get_snapshot_at_timestamp(timestamp)
    if existing:
        logger.warning(f"Snapshot already exists at {timestamp}")
        return existing.id

    return insert_snapshot(...)
```

**Better Solution:** Add UNIQUE constraint on timestamp in database schema.

---

## 9. Database Schema

### Table: usage_snapshots

```sql
CREATE TABLE usage_snapshots (
    -- Primary key
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Snapshot metadata
    timestamp TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,

    -- API data (percentages)
    five_hour_used INTEGER NOT NULL,      -- Stored as integer 0-100
    five_hour_limit INTEGER NOT NULL,     -- Always 100 (percentage)
    five_hour_pct REAL,                   -- Stored as float 0.0-100.0

    seven_day_used INTEGER NOT NULL,      -- Stored as integer 0-100
    seven_day_limit INTEGER NOT NULL,     -- Always 100 (percentage)
    seven_day_pct REAL,                   -- Stored as float 0.0-100.0

    -- Window reset times
    five_hour_reset TEXT,                 -- ISO 8601 timestamp
    seven_day_reset TEXT,                 -- ISO 8601 timestamp

    -- Delta (consumption since last snapshot)
    five_hour_tokens_consumed INTEGER,    -- Can be NULL (first snapshot)
    five_hour_messages_count INTEGER,     -- Can be NULL (first snapshot)

    seven_day_tokens_consumed INTEGER,    -- Can be NULL (first snapshot)
    seven_day_messages_count INTEGER,     -- Can be NULL (first snapshot)

    -- Total (consumption in current window)
    five_hour_tokens_total INTEGER,       -- Can be NULL (no data)
    five_hour_messages_total INTEGER,     -- Can be NULL (no data)

    seven_day_tokens_total INTEGER,       -- Can be NULL (no data)
    seven_day_messages_total INTEGER,     -- Can be NULL (no data)

    UNIQUE(timestamp)                     -- Prevent duplicate snapshots
);

-- Index for efficient time-range queries
CREATE INDEX idx_snapshots_timestamp ON usage_snapshots(timestamp);
```

### Field Descriptions

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `id` | INTEGER | No | Auto-incrementing primary key |
| `timestamp` | TEXT | No | ISO 8601 timestamp when snapshot was created |
| `five_hour_pct` | REAL | Yes | Percentage utilization (0.0-100.0) from API |
| `seven_day_pct` | REAL | Yes | Percentage utilization (0.0-100.0) from API |
| `five_hour_reset` | TEXT | Yes | ISO 8601 timestamp when 5h window resets |
| `seven_day_reset` | TEXT | Yes | ISO 8601 timestamp when 7d window resets |
| `five_hour_tokens_consumed` | INTEGER | Yes | Tokens consumed since last snapshot (delta) |
| `five_hour_messages_count` | INTEGER | Yes | Messages sent since last snapshot (delta) |
| `five_hour_tokens_total` | INTEGER | Yes | Total tokens in current 5h window |
| `five_hour_messages_total` | INTEGER | Yes | Total messages in current 5h window |
| `seven_day_tokens_consumed` | INTEGER | Yes | Tokens consumed since last snapshot (delta) |
| `seven_day_messages_count` | INTEGER | Yes | Messages sent since last snapshot (delta) |
| `seven_day_tokens_total` | INTEGER | Yes | Total tokens in current 7d window |
| `seven_day_messages_total` | INTEGER | Yes | Total messages in current 7d window |

### Queries

**Insert Snapshot:**
```sql
INSERT INTO usage_snapshots (
    timestamp,
    five_hour_pct, five_hour_reset,
    five_hour_tokens_consumed, five_hour_messages_count,
    five_hour_tokens_total, five_hour_messages_total,
    seven_day_pct, seven_day_reset,
    seven_day_tokens_consumed, seven_day_messages_count,
    seven_day_tokens_total, seven_day_messages_total
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
```

**Get Latest Snapshot:**
```sql
SELECT * FROM usage_snapshots
ORDER BY timestamp DESC
LIMIT 1;
```

**Get Snapshots in Range:**
```sql
SELECT * FROM usage_snapshots
WHERE timestamp >= ? AND timestamp <= ?
ORDER BY timestamp DESC;
```

**Get Snapshot Count:**
```sql
SELECT COUNT(*) FROM usage_snapshots;
```

---

## 10. Repopulation Strategy

### Problem

Existing snapshots may have incorrect totals due to:
1. Bugs in original implementation (double-counting, fork issues)
2. Incremental calculation drift
3. Missing reset detection

### Goal

Recalculate all historical snapshots using correct algorithm.

### Approach: Replay History

```python
def repopulate_usage_snapshots():
    """
    Recalculate all usage snapshots from JSONL logs.
    """
    # Load all snapshots chronologically
    snapshots = get_all_snapshots_ordered_by_time()

    # Load all JSONL entries into memory
    all_entries = load_all_jsonl_entries()

    # Process each snapshot
    for i, snapshot in enumerate(snapshots):
        # Get previous snapshot
        prev_snapshot = snapshots[i-1] if i > 0 else None

        # Recalculate for each window
        for window in ['five_hour', 'seven_day']:
            recalculate_snapshot_window(
                snapshot,
                prev_snapshot,
                window,
                all_entries
            )

        # Update database
        update_snapshot(snapshot)

    print(f"Repopulated {len(snapshots)} snapshots")


def recalculate_snapshot_window(snapshot, prev_snapshot, window_name, all_entries):
    """
    Recalculate delta and total for one window in one snapshot.
    """
    window_hours = 5 if window_name == 'five_hour' else 168

    current_timestamp = snapshot['timestamp']
    current_reset = snapshot[f'{window_name}_reset']

    # Detect reset
    if prev_snapshot:
        prev_reset = prev_snapshot[f'{window_name}_reset']
        reset_occurred = (current_reset != prev_reset)
        baseline_timestamp = prev_snapshot['timestamp']
    else:
        reset_occurred = False
        baseline_timestamp = None

    # Calculate delta
    if baseline_timestamp:
        delta = calculate_delta_from_entries(
            all_entries,
            baseline_timestamp,
            current_timestamp
        )
    else:
        delta = {'tokens': None, 'messages': None}

    # Calculate total
    window_start = calculate_window_start(current_reset, window_hours)
    total = calculate_delta_from_entries(
        all_entries,
        window_start,
        current_timestamp
    )

    # Update snapshot object
    snapshot[f'{window_name}_tokens_consumed'] = delta['tokens']
    snapshot[f'{window_name}_messages_count'] = delta['messages']
    snapshot[f'{window_name}_tokens_total'] = total['tokens']
    snapshot[f'{window_name}_messages_total'] = total['messages']


def calculate_delta_from_entries(entries, start_timestamp, end_timestamp):
    """
    Calculate delta from pre-loaded entry list.
    """
    start_dt = datetime.fromisoformat(start_timestamp.replace('Z', '+00:00'))
    end_dt = datetime.fromisoformat(end_timestamp.replace('Z', '+00:00'))

    tokens = 0
    messages = 0

    for entry in entries:
        entry_dt = datetime.fromisoformat(entry['timestamp'].replace('Z', '+00:00'))

        if start_dt <= entry_dt <= end_dt:
            if entry.get('type') in ['user', 'assistant']:
                messages += 1
                usage = entry.get('usage', {})
                tokens += usage.get('inputTokens', 0) + usage.get('outputTokens', 0)

    return {'tokens': tokens, 'messages': messages}
```

### Safety Measures

**1. Backup Database:**
```python
import shutil
from datetime import datetime

timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
backup_path = f'logviewer_backup_{timestamp}.db'
shutil.copy('logviewer.db', backup_path)
print(f"Backup created: {backup_path}")
```

**2. Dry Run Mode:**
```python
def repopulate_usage_snapshots(dry_run=True):
    changes = []

    for snapshot in snapshots:
        old_values = snapshot.copy()
        recalculate_snapshot(snapshot)

        if snapshot != old_values:
            changes.append({
                'timestamp': snapshot['timestamp'],
                'old': old_values,
                'new': snapshot
            })

    if dry_run:
        print(f"Would change {len(changes)} snapshots")
        for change in changes[:5]:  # Show first 5
            print_change(change)
        return changes
    else:
        # Actually update database
        for snapshot in snapshots:
            update_snapshot(snapshot)
        print(f"Updated {len(changes)} snapshots")
```

**3. Validation:**
```python
def validate_repopulation():
    """
    Check that repopulated data makes sense.
    """
    snapshots = get_all_snapshots_ordered_by_time()

    for i, snapshot in enumerate(snapshots):
        # Check totals are non-negative
        assert snapshot['five_hour_tokens_total'] >= 0
        assert snapshot['seven_day_tokens_total'] >= 0

        # Check totals don't exceed reasonable limits
        # (Assuming 100M tokens/window is unrealistic)
        assert snapshot['five_hour_tokens_total'] < 100_000_000
        assert snapshot['seven_day_tokens_total'] < 100_000_000

        # Check deltas match totals direction
        if i > 0:
            prev = snapshots[i-1]

            # If reset didn't occur, total should increase or stay same
            if snapshot['five_hour_reset'] == prev['five_hour_reset']:
                # Allow small decreases due to natural token expiry
                # but large decreases indicate bug
                diff = snapshot['five_hour_tokens_total'] - prev['five_hour_tokens_total']
                assert diff > -1000, f"Unexpected total decrease: {diff}"
```

---

## 11. Testing Strategy

### Unit Tests

**Test: Delta Calculation**
```python
def test_calculate_delta():
    entries = [
        {
            'timestamp': '2025-11-10T10:00:00Z',
            'type': 'user',
            'usage': {'inputTokens': 100, 'outputTokens': 0}
        },
        {
            'timestamp': '2025-11-10T10:01:00Z',
            'type': 'assistant',
            'usage': {'inputTokens': 0, 'outputTokens': 200}
        },
        {
            'timestamp': '2025-11-10T10:02:00Z',
            'type': 'system',  # Should be ignored
            'usage': {'inputTokens': 500, 'outputTokens': 500}
        }
    ]

    result = calculate_delta_from_entries(
        entries,
        '2025-11-10T10:00:00Z',
        '2025-11-10T10:03:00Z'
    )

    assert result['tokens'] == 300  # 100 + 200, not 1300
    assert result['messages'] == 2  # Only user + assistant
```

**Test: Reset Detection**
```python
def test_detect_reset():
    # No reset
    assert not detect_reset('2025-11-10T14:00:00Z', '2025-11-10T14:00:00Z')

    # Reset occurred
    assert detect_reset('2025-11-10T19:00:00Z', '2025-11-10T14:00:00Z')

    # First snapshot
    assert not detect_reset('2025-11-10T14:00:00Z', None)
```

**Test: Total Calculation (No Reset)**
```python
def test_total_incremental():
    prev_total = 5000
    delta = 500

    result = calculate_total_incremental(
        reset_occurred=False,
        previous_total={'tokens': prev_total},
        delta={'tokens': delta}
    )

    assert result['total_tokens'] == 5500
```

**Test: Total Calculation (With Reset)**
```python
def test_total_after_reset():
    entries = [
        {'timestamp': '2025-11-10T13:55:00Z', 'type': 'user',
         'usage': {'inputTokens': 1000, 'outputTokens': 0}},  # Before reset
        {'timestamp': '2025-11-10T14:05:00Z', 'type': 'user',
         'usage': {'inputTokens': 500, 'outputTokens': 0}}   # After reset
    ]

    result = calculate_total_from_scratch_from_entries(
        entries,
        resets_at='2025-11-10T19:00:00Z',  # Reset at 2pm + 5h
        window_duration_hours=5,
        current_timestamp='2025-11-10T14:10:00Z'
    )

    # Should only count post-reset token
    # Window: 14:00 to 14:10
    assert result['total_tokens'] == 500
```

### Integration Tests

**Test: End-to-End Normal Increment**
```python
def test_e2e_normal_increment():
    # Setup: Create first snapshot
    db = setup_test_database()
    insert_snapshot(
        timestamp='2025-11-10T10:00:00Z',
        five_hour_pct=15.0,
        five_hour_reset='2025-11-10T14:00:00Z',
        five_hour_tokens_total=5000,
        ...
    )

    # Create JSONL entries
    create_test_jsonl([
        {'timestamp': '2025-11-10T10:05:00Z', 'type': 'user',
         'usage': {'inputTokens': 500, 'outputTokens': 0}}
    ])

    # Simulate API response
    api_data = {
        'five_hour': {
            'utilization': 16.5,
            'resets_at': '2025-11-10T14:00:00Z'
        }
    }

    # Process
    process_api_response(api_data)

    # Verify
    latest = get_latest_snapshot()
    assert latest['five_hour_pct'] == 16.5
    assert latest['five_hour_tokens_consumed'] == 500
    assert latest['five_hour_tokens_total'] == 5500
```

**Test: End-to-End Window Reset**
```python
def test_e2e_window_reset():
    # Similar to above but with reset_at change
    # Verify delta counts all tokens
    # Verify total only counts post-reset tokens
    ...
```

### Manual Test Scenarios

**Scenario 1: First Run**
1. Delete database: `rm ~/.claude-log-viewer/logviewer.db`
2. Start application
3. Send a message in Claude Code
4. Verify first snapshot created with total but no delta

**Scenario 2: Multiple Messages**
1. Start with existing snapshot
2. Send 3 messages in Claude Code
3. Verify delta = sum of 3 messages
4. Verify total = previous total + delta

**Scenario 3: Window Reset**
1. Wait for window to reset (or mock system time)
2. Send a message
3. Verify reset detected in logs
4. Verify total recalculated from new window start

**Scenario 4: Long Idle Period**
1. Don't use Claude Code for 24 hours
2. Send a message
3. Verify delta covers full 24-hour gap
4. Verify total is accurate

**Scenario 5: Missing JSONL Files**
1. Delete old JSONL files
2. Trigger snapshot creation
3. Verify graceful handling (warnings logged)
4. Verify totals are underestimated but don't crash

---

## 12. Future Improvements

### 1. Predictive Usage Alerts

**Goal:** Warn users before hitting rate limits.

**Approach:**
- Track usage velocity (tokens per hour)
- Extrapolate to window reset time
- Alert if projected to exceed 80% of limit

**Implementation:**
```python
def predict_usage_at_reset():
    recent_snapshots = get_snapshots_in_last_hour()
    tokens_per_hour = calculate_velocity(recent_snapshots)

    hours_until_reset = (reset_time - now).total_seconds() / 3600
    projected_tokens = current_total + (tokens_per_hour * hours_until_reset)

    # Assuming 100% = some known limit
    projected_pct = (projected_tokens / estimated_limit) * 100

    if projected_pct > 80:
        show_warning(f"Projected to reach {projected_pct}% by reset")
```

### 2. Multi-Window Visualization

**Goal:** Show historical trends beyond current windows.

**Approach:**
- Store all snapshots indefinitely
- Provide graphs of usage over 30 days, 90 days, etc.
- Show patterns (weekdays vs weekends, time of day)

### 3. Per-Project Usage Tracking

**Goal:** Break down usage by project/session.

**Approach:**
- Tag snapshots with active projects
- Calculate per-project token consumption
- Show which projects consume most tokens

**Challenge:** Requires session-to-project mapping.

### 4. Cost Estimation

**Goal:** Show approximate costs based on token usage.

**Approach:**
- Maintain pricing table (per-token costs for each model)
- Multiply tokens by price
- Show estimated monthly cost

**Challenge:** Pricing changes, different models have different prices.

### 5. Export and Reporting

**Goal:** Generate usage reports for team/billing purposes.

**Features:**
- CSV export of all snapshots
- PDF report with graphs
- Email digest (daily/weekly summaries)

### 6. Real-Time Total Tracking

**Goal:** Show current window total without waiting for API poll.

**Approach:**
- Maintain running total in memory
- Increment on every message
- Sync with API on next poll

**Benefit:** Immediate feedback to user.

### 7. Anomaly Detection

**Goal:** Alert on unusual usage patterns.

**Approach:**
- Baseline normal usage (e.g., 1000 tokens/hour)
- Detect spikes (e.g., 10,000 tokens in 5 minutes)
- Alert user to potential runaway agents or bugs

### 8. Window Total Caching

**Goal:** Reduce JSONL I/O by caching window totals.

**Current Problem:** We recalculate total from scratch on every reset.

**Approach:**
```python
# Instead of recalculating from JSONL:
# 1. Sum all deltas within window from database
# 2. Only read JSONL if data missing

def calculate_total_from_cached_deltas(window_start, current_time):
    snapshots_in_window = get_snapshots_in_range(window_start, current_time)
    total_tokens = sum(s['tokens_consumed'] for s in snapshots_in_window)
    return total_tokens
```

**Benefit:** Faster, no disk I/O.

**Caveat:** Requires all snapshots in window to exist (no gaps).

### 9. Differential Snapshots

**Goal:** Reduce database storage by only storing changes.

**Current:** Every snapshot stores full total.

**Future:** Only store delta, compute total on demand.

**Benefit:** Smaller database, but slower queries.

### 10. API Limit Discovery

**Goal:** Determine actual token limits, not just percentages.

**Approach:**
- Correlate percentage with token counts
- Solve: `percentage = (tokens / limit) * 100`
- Example: 50% = 10,000 tokens → limit = 20,000 tokens

**Benefit:** Show absolute limits in UI ("15,234 / 20,000 tokens").

---

## Appendix A: Glossary

| Term | Definition |
|------|------------|
| **API** | Anthropic OAuth API that provides usage data |
| **Snapshot** | A point-in-time record of usage data |
| **Delta** | Consumption that occurred between two snapshots |
| **Total** | Consumption currently within a sliding window |
| **Window** | A sliding time period (5 hours or 7 days) |
| **Reset** | Event when window boundary moves forward |
| **Polling** | Fetching current usage data from API |
| **JSONL** | JSON Lines format used for conversation logs |
| **Utilization** | Percentage of limit consumed (0-100%) |
| **Baseline** | Starting timestamp for delta calculation |

## Appendix B: Assumptions

1. **System clock is accurate** - Timestamps are trustworthy
2. **JSONL files are append-only** - No editing of historical logs
3. **Token counts are accurate** - `usage` field in JSONL is correct
4. **API is authoritative** - Percentage from API is ground truth
5. **Single-machine usage** - Database not shared across machines
6. **Sequential processing** - Only one snapshot created at a time
7. **No backdating** - Snapshots always created "now", not in past

## Appendix C: References

- **Anthropic API Documentation:** https://docs.anthropic.com/
- **Claude Code Architecture:** (internal documentation)
- **SQLite Documentation:** https://www.sqlite.org/docs.html
- **ISO 8601 Timestamps:** https://en.wikipedia.org/wiki/ISO_8601

---

**Document End**

This architecture document defines the complete usage tracking system from first principles. It provides sufficient detail for a developer to implement the system from scratch without referring to existing buggy code.

**Key Principle:** Calculate totals from scratch on every snapshot using window boundaries, don't trust incremental accumulation. This handles all edge cases (resets, natural token expiry, missing data) correctly.
