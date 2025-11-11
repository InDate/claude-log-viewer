# Problem Statement: Claude Code Session Rollback

## Executive Summary

Claude Code lacks a reliable mechanism to rollback changes made during sessions, particularly when agents make modifications. The built-in checkpoint/rewind feature has critical limitations that prevent comprehensive rollback, and traditional git-based approaches create unacceptable complexity or infrastructure overhead.

## The Core Problem

### Claude Code's Current Limitations

Claude Code provides a built-in checkpoint/rewind feature, but it has significant gaps:

1. **Bash Command Changes Not Tracked**
   - Files modified by bash commands cannot be rewound
   - This includes: deletions, moves, copies, and any shell operations
   - Example: `rm file.txt`, `mv old.txt new.txt`, `chmod +x script.sh`

2. **External Modifications Not Captured**
   - Changes made outside Claude Code aren't tracked
   - Concurrent sessions can make untracked modifications
   - Build tools, formatters, and other processes are invisible to checkpoints

3. **Agent Changes Ambiguity**
   - Documentation doesn't specify if agent/sub-agent changes are checkpointed
   - Agent operations may use Bash (which isn't tracked)
   - No granular rollback per-agent

4. **Not a Version Control System**
   - Checkpoints are explicitly "local undo, not permanent version control"
   - Recommended to use Git alongside checkpoints
   - Checkpoints don't persist across sessions reliably

### Real-World Impact

**Scenario 1: Agent Uses Bash**
```
User: "Claude, refactor the codebase"
Claude: Spawns agent
Agent: Runs `find . -name "*.old" -delete`  ← Bash command
Agent: Modifies 50 files

User tries to rewind
Result: ❌ Deleted files are gone forever (Bash not tracked)
```

**Scenario 2: Multi-File Refactor Gone Wrong**
```
Session modifies:
- file1.py (Edit tool) ✓ Can rewind
- file2.py (Edit tool) ✓ Can rewind
- config.json (Write tool) ✓ Can rewind
- old_files/ (Bash: rm -rf) ✗ Cannot rewind

User rewinds to checkpoint
Result: ❌ Partial rollback - 3 files restored, directory still deleted
```

**Scenario 3: Concurrent Activity**
```
Time 0: Claude starts session, creates checkpoint
Time 1: Claude edits file.py
Time 2: User manually edits file.py (different section)
Time 3: Build tool regenerates config.json
Time 4: Claude edits file.py again
Time 5: User tries to rewind

Result: ❌ Manual changes and build outputs are lost
```

## User Requirements

Based on discussion and analysis, the solution must satisfy:

### Primary Requirements

1. **Clean Git History**
   - Main branch should not be "polluted" with experimental commits
   - Rolled-back sessions should disappear from git log
   - No orphan branches or temporary branches cluttering `git branch -a`
   - History should look clean to external viewers (code review, git blame)

2. **Single Working Directory**
   - Cannot use git worktrees (requires duplicate infrastructure)
   - Servers, databases, and integrations run in one location
   - No managing multiple directories
   - No port conflicts or resource duplication

3. **Reliable Rollback**
   - Must handle Edit, Write, AND Bash operations
   - Should work regardless of external file modifications
   - Recovery window must be reasonable (weeks/months, not hours/days)
   - Partial recovery should be possible (cherry-pick specific changes)

### Secondary Requirements

4. **Agent Granularity**
   - Track which changes came from which agent
   - Option to rollback specific agent's work
   - Option to keep agent changes while rolling back main session

5. **Ease of Use**
   - Visual UI for rollback (not just CLI)
   - Preview changes before rollback
   - Clear status indicators
   - Undo/redo capability

6. **No Manual Git Management**
   - Automation should handle git operations
   - Users shouldn't need to remember branch names
   - Cleanup should be automatic
   - No orphaned state that requires manual fix

## Why Existing Solutions Don't Work

### Option 1: Git Worktrees
**Problem: Duplicate Infrastructure**

```
project/
├── main/                    ← Main worktree
│   ├── server (port 3000)   ← Dev server #1
│   ├── db.sqlite            ← Database #1
│   └── .env                 ← Config #1
├── .claude-worktrees/
│   ├── session-1/           ← Worktree #1
│   │   ├── server (port 3001) ← Dev server #2 ✗
│   │   ├── db.sqlite        ← Database #2 ✗
│   │   └── .env             ← Config #2 ✗
│   └── session-2/           ← Worktree #2
│       ├── server (port 3002) ← Dev server #3 ✗
│       └── ...              ← Everything duplicated ✗
```

**Issues:**
- Need separate dev servers per worktree
- Databases don't sync across worktrees
- Port conflicts (can't all use :3000)
- API keys and integrations multiplied
- Resource overhead (RAM, CPU, disk)

**Verdict:** ❌ Unacceptable complexity

### Option 2: JSONL-Based Reversal
**Problem: Fundamentally Flawed**

The idea: Parse JSONL logs and reverse operations using stored old_string/new_string.

**Critical Flaw #1: File State Dependencies**
```python
# Edit #1: Change line 10
Edit(old="foo", new="bar")

# Edit #2: Change line 10 again
Edit(old="bar", new="baz")

# External: User manually edits line 10
# File now contains: "qux"

# Try to reverse Edit #2:
Edit(old="baz", new="bar")  ← ❌ FAILS - "baz" not found (file has "qux")
```

**Critical Flaw #2: Bash Operations Cannot Be Reversed**
```bash
rm -rf /tmp/cache/*          # How do you reverse this?
curl -X POST api.com/deploy  # Already deployed!
npm publish                  # Already published to registry!
git push --force             # Remote history rewritten!
```

**Critical Flaw #3: Context Ambiguity**
```python
# File has multiple identical lines
return True  # Line 10
return True  # Line 20
return True  # Line 30

# Edit one of them
Edit(old="return True", new="return False")

# Which one was changed? JSONL doesn't store enough context
```

**Verdict:** ❌ Unreliable and dangerous

### Option 3: Ephemeral Branches
**Problem: Pollutes History if Not Careful**

```bash
# Create temp branch
git checkout -b claude-session-abc123

# Claude makes commits
git commit -m "change 1"
git commit -m "change 2"

# User accidentally:
git push origin claude-session-abc123  ← ❌ Now in remote history

# Or user forgets to delete:
git branch -a
  main
  claude-session-abc123  ← ❌ Clutters branch list
  claude-session-def456  ← ❌
  claude-session-ghi789  ← ❌
  ... (dozens of old sessions)
```

**Issues:**
- Requires discipline to delete branches
- Can accidentally push temp branches
- Branch list gets cluttered
- Manual cleanup required

**Verdict:** ❌ Doesn't meet "clean history" requirement

### Option 4: File Snapshots (à la claude-code-rewind)
**Problem: Still Can't Handle Bash**

The claude-code-rewind tool snapshots files before changes, but:

```bash
# Snapshot file.txt before edit ✓
snapshot("file.txt")
Edit file.txt  ← Can restore ✓

# But Bash operations:
rm -rf directory/  ← ❌ Directory already gone, can't snapshot after-the-fact
mv old.txt new.txt  ← ❌ Need to snapshot BEFORE move (but how to predict?)
chmod +x script.sh  ← ❌ Permission change not captured
```

**Verdict:** ❌ Partial solution only

## The Trilemma

Based on analysis, we face a trilemma - pick any 2 of 3:

```
         Clean Git History
                △
               ╱ ╲
              ╱   ╲
             ╱     ╲
            ╱       ╲
           ╱         ╲
          ╱           ╲
         ╱             ╲
        ╱               ╲
Single Working Dir ─────── Reliable Rollback
```

- **Worktrees**: Single dir ✗, Clean history ✓, Reliable ✓
- **JSONL Reversal**: Single dir ✓, Clean history ✓, Reliable ✗
- **Branches**: Single dir ✓, Clean history ✗, Reliable ✓

## What We Need

A solution that:
1. ✅ Works in single directory (no worktrees)
2. ✅ Keeps git history clean (no branch pollution)
3. ✅ Provides reliable rollback (handles Edit/Write/Bash)
4. ✅ Tracks agent changes separately
5. ✅ Offers recovery window (weeks/months)
6. ✅ Enables partial recovery (cherry-pick)
7. ✅ Automates complexity (users don't manage branches/refs)

The solution must balance these constraints without requiring users to become git experts or maintain complex infrastructure.

## Success Criteria

The solution will be considered successful if:

1. **User can rollback any Claude Code session**, including:
   - All Edit operations
   - All Write operations
   - Effects of Bash operations (via file snapshots)
   - Changes made by agents

2. **Git history stays clean**:
   - `git log main` shows only accepted/merged work
   - No temporary branches visible in `git branch -a`
   - External viewers see clean history

3. **Single working directory maintained**:
   - Dev server runs once (one port)
   - One database instance
   - One set of environment variables
   - No directory management overhead

4. **Recovery is reliable**:
   - At least 30-day recovery window (preferably 90-180 days)
   - Can recover entire sessions or specific commits
   - Recovery survives crashes and restarts
   - Clear UI showing what can be recovered

5. **Agent changes are traceable**:
   - Can identify which agent made which changes
   - Can rollback specific agent's work
   - Can keep agent changes while rolling back main session

This problem statement sets the foundation for evaluating potential solutions against clear, measurable criteria.
