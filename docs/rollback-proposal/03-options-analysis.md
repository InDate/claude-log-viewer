# Options Analysis: Comparative Evaluation of Rollback Strategies

## Overview

This document provides a comprehensive comparison of eight potential strategies for implementing Claude Code session rollback. Each option is evaluated against our requirements and scored across multiple dimensions.

## Evaluation Criteria

Each strategy is scored (1-10, 10 = best) on:

1. **Clean History** - Does it keep git log clean?
2. **Single Directory** - Works in one working directory?
3. **Reliable Rollback** - Can it handle Edit/Write/Bash?
4. **Implementation Complexity** - How hard to build?
5. **User Experience** - Easy for users to understand?
6. **Recovery Window** - How long can you recover?
7. **Agent Granularity** - Can track per-agent changes?
8. **Industry Adoption** - Proven in the wild?
9. **Fork Awareness** - Can detect and checkpoint conversation forks? (See [01-problem-statement.md] Requirement 4 and [02-research-findings.md] Finding 9)

## Option 1: Git Worktrees + Ephemeral Branches

### Description

Create separate git worktrees for each Claude Code session, each with its own branch.

```
project/
├── main/                       # Main worktree
│   └── (main development)
├── .claude-worktrees/
│   ├── session-abc123/         # Session 1 worktree
│   │   └── (branch: claude-session-abc123)
│   └── session-def456/         # Session 2 worktree
│       └── (branch: claude-session-def456)
```

### How It Works

```bash
# Create worktree for new session
git worktree add ../claude-worktrees/session-{id} -b claude-session-{id}

# Claude works in that directory
cd ../claude-worktrees/session-{id}

# Rollback: delete worktree + branch
git worktree remove ../claude-worktrees/session-{id}
git branch -D claude-session-{id}

# Merge: bring changes to main
git checkout main
git merge claude-session-{id}
git branch -d claude-session-{id}
```

### Pros

- ✅ **Perfect Isolation**: Each session completely independent
- ✅ **Parallel Sessions**: Run multiple Claude instances simultaneously
- ✅ **Context Preservation**: Working directory never changes
- ✅ **Storage Efficient**: Shares .git objects, only duplicates working files
- ✅ **Industry Proven**: Heavy adoption in AI coding community
- ✅ **Clean Main Branch**: Worktree branches never pollute main until explicitly merged

### Cons

- ❌ **Infrastructure Duplication**: Each worktree needs separate dev server, database, config
- ❌ **Port Conflicts**: Multiple servers can't use same port
- ❌ **Resource Overhead**: RAM, CPU multiplied by number of sessions
- ❌ **Directory Management**: Must track which directory you're in
- ❌ **Cleanup Overhead**: Orphaned worktrees need manual cleanup

### Critical Infrastructure Problem

```
Each worktree requires:
├── Dev Server (port 3000, 3001, 3002...)
├── Database Instance
├── Environment Variables (.env)
├── Docker Containers
├── API Connections
└── Build Artifacts
```

**For a typical web project:**
- 3 parallel sessions = 3 × dev server memory
- 3 × database file size
- 3 × build time
- Management overhead tracking everything

### Scores

| Criterion | Score | Notes |
|-----------|-------|-------|
| Clean History | 10/10 | Perfect - main never sees temp work |
| Single Directory | 1/10 | Multiple directories by design |
| Reliable Rollback | 10/10 | Git commits capture everything |
| Complexity | 6/10 | Medium - need directory management |
| User Experience | 5/10 | Confusing which directory you're in |
| Recovery Window | 10/10 | Permanent until branch deleted |
| Agent Granularity | 8/10 | Can create agent sub-branches |
| Industry Adoption | 9/10 | Documented pattern, growing adoption |
| **TOTAL** | **59/80** | |

### Verdict

✅ Technically excellent for git
❌ **REJECTED** due to infrastructure duplication requirements

---

## Option 2: Ephemeral Branches Only

### Description

Create temporary branches for each session, work on them, then delete after review.

```bash
# Start session
git checkout -b claude-session-{id}

# Work happens
git commit -m "changes"

# Rollback
git checkout main
git branch -D claude-session-{id}

# Keep
git checkout main
git merge claude-session-{id}
git branch -d claude-session-{id}
```

### How It Works

- Each Claude session creates branch: `claude-session-{uuid}`
- Commits made to session branch
- Branch deleted after session (merged or discarded)
- `.git/hooks/pre-push` prevents accidental remote push

### Pros

- ✅ **Simple Concept**: Everyone understands branches
- ✅ **Git Native**: Standard git workflows
- ✅ **Single Directory**: No worktree overhead
- ✅ **Easy Rollback**: `git branch -D` removes everything
- ✅ **Reflog Safety**: Deleted branches in reflog for 90 days
- ✅ **Flexible**: Create/delete branches on-the-fly

### Cons

- ❌ **Context Switching**: Must `git checkout` between sessions
- ❌ **Cannot Run Parallel**: One session at a time (checkout limitation)
- ❌ **Branch List Clutter**: `git branch -a` gets messy without discipline
- ❌ **Accidental Push**: Can push temp branches to remote
- ❌ **Manual Cleanup**: Requires discipline to delete
- ❌ **History Pollution Risk**: If branches not deleted, visible in `git branch`

### Auto-Cleanup Strategies

```bash
# Git hook to prevent push
# .git/hooks/pre-push
if [[ $ref =~ refs/heads/claude-session-.* ]]; then
    echo "ERROR: Cannot push temp session branches"
    exit 1
fi

# Auto-delete after merge
git config branch.autosetuprebase always

# Periodic cleanup script
git for-each-ref --format="%(refname:short)" \
    refs/heads/claude-session-* | \
    xargs -n 1 git branch -D
```

### Scores

| Criterion | Score | Notes |
|-----------|-------|-------|
| Clean History | 8/10 | Good if cleaned up properly |
| Single Directory | 10/10 | Yes, standard checkout |
| Reliable Rollback | 10/10 | Git commits capture all |
| Complexity | 8/10 | Low - simple scripts |
| User Experience | 7/10 | Familiar git workflow |
| Recovery Window | 9/10 | Reflog 90 days |
| Agent Granularity | 7/10 | Can create agent sub-branches |
| Industry Adoption | 10/10 | Standard practice |
| **TOTAL** | **69/80** | |

### Verdict

✅ Viable option
⚠️ Requires automation and discipline
❌ No parallel sessions

---

## Option 3: Reflog-Based Rollback

### Description

Commit directly to current branch, use `git reset --hard` to rollback (commits go to reflog), and cherry-pick from reflog to recover.

```bash
# Session starts - record checkpoint
CHECKPOINT=$(git rev-parse HEAD)

# Claude makes commits
git commit -m "change 1"
git commit -m "change 2"

# Rollback - commits go to reflog
git reset --hard $CHECKPOINT

# Commits now in reflog for 90-180 days
git reflog  # Shows all commits

# Recover if needed
git cherry-pick <commit-hash-from-reflog>
```

### How It Works

1. **Before Session**: Record HEAD position
2. **During Session**: Make real commits to current branch
3. **After Review**:
   - **Keep**: Push to remote (permanent)
   - **Discard**: `git reset --hard` (commits → reflog)
   - **Recover**: Cherry-pick from reflog

### Pros

- ✅ **Clean History**: Reset makes commits invisible in `git log`
- ✅ **Single Directory**: No worktrees or checkouts
- ✅ **Reliable Rollback**: Real commits capture all file changes
- ✅ **Simple Mental Model**: Commit → keep or reset → reflog backup
- ✅ **Partial Recovery**: Cherry-pick specific commits
- ✅ **No Branch Management**: Work directly on current branch
- ✅ **Atomic Operations**: Reset is instant and atomic
- ✅ **Configurable Safety**: Extend reflog retention to 180+ days
- ✅ **Fork-Aware**: Automatic checkpoints on fork creation (see [02-research-findings.md] Finding 9)
- ✅ **Fork Visualization**: Track git state per conversation branch, compare across forks

### Cons

- ⚠️ **Time-Limited Recovery**: Default 30-90 days (configurable)
- ⚠️ **Local Only**: Reflog not synced to remote
- ⚠️ **Vulnerable to GC**: Garbage collection can delete commits
- ⚠️ **Learning Curve**: Reflog less familiar than branches
- ⚠️ **Multi-Machine Issues**: Reflog doesn't transfer across clones

### Mitigation Strategies

```bash
# Extend reflog retention
git config gc.reflogExpire "180 days"
git config gc.reflogExpireUnreachable "180 days"

# Optional: Tag important checkpoints
git tag checkpoint-{session-id} HEAD

# Optional: Push to recovery branch before rollback
git push origin HEAD:refs/recovery/session-{id}
```

### Scores

| Criterion | Score | Notes |
|-----------|-------|-------|
| Clean History | 10/10 | Perfect - reset removes from log |
| Single Directory | 10/10 | Yes, work on current branch |
| Reliable Rollback | 10/10 | Git commits capture all |
| Complexity | 7/10 | Medium - need reflog understanding |
| User Experience | 8/10 | Simple once understood |
| Recovery Window | 7/10 | 90-180 days (configurable) |
| Agent Granularity | 9/10 | Commit messages track agents |
| Industry Adoption | 6/10 | Emerging pattern |
| Fork Awareness | 10/10 | Auto-checkpoint on forks, fork tree visualization |
| **TOTAL** | **87/90** | |

### Verdict

✅ **RECOMMENDED** - Meets all three constraints
✅ Clean history + single directory + reliable rollback
✅ Configurable safety mechanisms

---

## Option 4: Git Stash for Session State

### Description

Use git stash to save session snapshots without creating commits.

```bash
# Save checkpoint
git stash save "claude-session-{id}-checkpoint"

# Work happens

# Rollback
git stash pop  # Restore previous state

# Keep
git stash drop  # Discard stash
```

### Pros

- ✅ **Fast**: Instant snapshot
- ✅ **No Commits**: Doesn't pollute history
- ✅ **Stack-Based**: Multiple stashes possible
- ✅ **Built-in**: No extra tools

### Cons

- ❌ **Not for Commits**: Can't stash committed history
- ❌ **Confusing Syntax**: `stash@{3}` not intuitive
- ❌ **Limited Naming**: Poor discoverability
- ❌ **Merge Conflicts**: Applying stash can conflict
- ❌ **Not Persistent**: Local-only, can be lost
- ❌ **No Branching**: Can't have parallel stashed sessions

### Scores

| Criterion | Score | Notes |
|-----------|-------|-------|
| Clean History | 8/10 | Stashes don't pollute git log |
| Single Directory | 10/10 | Yes |
| Reliable Rollback | 3/10 | Only for uncommitted work |
| Complexity | 7/10 | Simple but limited |
| User Experience | 4/10 | Confusing for users |
| Recovery Window | 4/10 | No automatic expiration, manual cleanup |
| Agent Granularity | 2/10 | Can't track per-agent |
| Industry Adoption | 3/10 | Not used for session management |
| **TOTAL** | **41/80** | |

### Verdict

❌ **REJECTED** - Not suitable for session management
✓ Better for quick context switches only

---

## Option 5: Detached HEAD Strategy

### Description

Work in detached HEAD state during sessions, create branch to keep or discard commits.

```bash
# Start session in detached HEAD
git checkout HEAD~0

# Make commits (not on any branch)
git commit -m "work"

# Keep: create branch
git checkout -b claude-session-{id}

# Discard: checkout away
git checkout main  # Commits become unreachable
```

### Pros

- ✅ **Zero Branch Pollution**: Commits exist but aren't on branches
- ✅ **Reversible**: Can create branch from detached commits
- ✅ **Clean Discard**: Just checkout away
- ✅ **No Cleanup**: GC handles unreachable commits

### Cons

- ❌ **Easy to Lose Work**: Forget to create branch = commits lost
- ❌ **Confusing UX**: Git warnings scare users
- ❌ **Not Beginner Friendly**: Requires git internals knowledge
- ❌ **Accidental Discard**: One wrong command loses everything
- ❌ **No Branch Name**: Hard to track sessions

### Scores

| Criterion | Score | Notes |
|-----------|-------|-------|
| Clean History | 10/10 | No branches created |
| Single Directory | 10/10 | Yes |
| Reliable Rollback | 5/10 | High risk of accidental loss |
| Complexity | 4/10 | Complex, requires education |
| User Experience | 2/10 | Very confusing for most users |
| Recovery Window | 6/10 | 30 days in reflog |
| Agent Granularity | 5/10 | Commit messages only |
| Industry Adoption | 2/10 | Rarely recommended |
| **TOTAL** | **44/80** | |

### Verdict

❌ **REJECTED** - Too risky for session management
✓ Better for quick code exploration only

---

## Option 6: Git Notes / Custom Refs

### Description

Use git notes for metadata or custom refs (`refs/claude-sessions/{id}`) outside normal branch namespace.

```bash
# Git notes
git notes add -m "Session metadata" HEAD

# Custom refs
git update-ref refs/claude-sessions/{id} HEAD
git show refs/claude-sessions/{id}

# Cleanup
git update-ref -d refs/claude-sessions/{id}
```

### Pros

- ✅ **Non-Invasive**: Notes don't modify commits
- ✅ **Hidden Refs**: Custom refs don't clutter `git branch`
- ✅ **Metadata Storage**: Perfect for session tracking
- ✅ **Separate Cleanup**: Can GC independently

### Cons

- ❌ **Not for Code**: Notes are metadata, not for storing changes
- ❌ **Limited Tooling**: Few UIs support git notes
- ❌ **Sync Issues**: Notes don't push by default
- ❌ **Complexity**: Requires low-level git knowledge
- ❌ **Not Complete**: Still need branches/worktrees for actual work
- ❌ **Obscure**: Most developers unfamiliar

### Scores

| Criterion | Score | Notes |
|-----------|-------|-------|
| Clean History | 9/10 | Can hide experimental refs |
| Single Directory | 10/10 | Yes |
| Reliable Rollback | 3/10 | Not for storing code changes |
| Complexity | 3/10 | High - requires deep git knowledge |
| User Experience | 2/10 | Too obscure |
| Recovery Window | 7/10 | Refs persist until deleted |
| Agent Granularity | 7/10 | Can tag with agent metadata |
| Industry Adoption | 2/10 | Niche use (DVC, Gerrit) |
| **TOTAL** | **43/80** | |

### Verdict

❌ **REJECTED** as primary strategy
✓ Could augment another approach (metadata storage)

---

## Option 7: APFS Snapshots + Git (macOS Only)

### Description

Combine APFS filesystem snapshots with git for two-layer safety net.

```bash
# Create APFS snapshot before session
tmutil localsnapshot

# Git operations happen normally
git commit -m "work"

# Rollback filesystem to snapshot if needed
# (Requires macOS Recovery Mode)

# Or restore specific files
cp /Volumes/.timemachine/{snapshot}/file.txt .
```

### Pros

- ✅ **Filesystem-Level**: Captures entire working directory state
- ✅ **Fast**: Copy-on-write is instant
- ✅ **Automatic**: Time Machine creates hourly snapshots
- ✅ **Full Recovery**: Even if git repo corrupted

### Cons

- ❌ **macOS Only**: Not cross-platform
- ❌ **Coarse-Grained**: Snapshots entire volume, not just repo
- ❌ **Manual Restore**: Requires Recovery Mode or manual file copying
- ❌ **Overkill**: Filesystem snapshots for git is excessive
- ❌ **No Integration**: No existing tools coordinate with git
- ❌ **Storage Overhead**: Snapshots consume disk space

### Scores

| Criterion | Score | Notes |
|-----------|-------|-------|
| Clean History | 10/10 | Doesn't affect git |
| Single Directory | 10/10 | Yes |
| Reliable Rollback | 9/10 | Very reliable for what it does |
| Complexity | 2/10 | Very high - requires custom tooling |
| User Experience | 2/10 | Complex recovery process |
| Recovery Window | 8/10 | Until manually deleted |
| Agent Granularity | 1/10 | No granularity (whole volume) |
| Industry Adoption | 1/10 | No AI tools use this |
| **TOTAL** | **43/80** | |

### Verdict

❌ **REJECTED** - Overkill for session management
✓ Better for disaster recovery

---

## Option 8: JSONL-Based Reversal

### Description

Parse JSONL logs and reverse operations using Edit tool's old_string/new_string.

```python
# From JSONL
{
  "tool": "Edit",
  "input": {
    "old_string": "foo",
    "new_string": "bar"
  }
}

# Reverse operation
Edit(old_string="bar", new_string="foo")
```

### Pros

- ✅ **Minimal Storage**: Reuses JSONL data
- ✅ **Fast Reversal**: Direct string replacement
- ✅ **Already Have Data**: JSONL logs exist

### Cons

- ❌ **File State Dependencies**: Breaks if file changed externally
- ❌ **Bash Unreversible**: Cannot reverse bash operations
- ❌ **Context Ambiguity**: Multiple matches of same string
- ❌ **Sequence Dependent**: Must reverse in exact order
- ❌ **Indentation Fragile**: Formatting changes break reversal
- ❌ **Fundamentally Flawed**: Trying to build version control from operation logs

### Critical Agent Analysis

An agent tasked with critically analyzing this approach identified 10+ fatal flaws. Key finding:

> "The JSONL-based reversal approach suffers from false assumptions about file state persistence... attempting to build version control on top of non-versioned operations. This is fundamentally doomed."

### Scores

| Criterion | Score | Notes |
|-----------|-------|-------|
| Clean History | 10/10 | No git pollution |
| Single Directory | 10/10 | Yes |
| Reliable Rollback | 1/10 | **Fundamentally unreliable** |
| Complexity | 6/10 | Simple in theory, impossible in practice |
| User Experience | 3/10 | Unpredictable failures |
| Recovery Window | 10/10 | JSONL persists indefinitely |
| Agent Granularity | 8/10 | JSONL tracks tool_use_id |
| Industry Adoption | 1/10 | No one uses this (for good reason) |
| **TOTAL** | **49/80** | |

### Verdict

❌ **REJECTED** - Fundamentally flawed and unreliable
❌ Critical analysis identified insurmountable problems

---

## Comparative Summary

### Scoring Matrix

| Strategy | Clean | Single Dir | Reliable | Complexity | UX | Recovery | Agents | Adoption | Fork Awareness | **TOTAL** |
|----------|-------|------------|----------|------------|-----|----------|--------|----------|----------------|-----------|
| **Reflog-Based** | 10 | 10 | 10 | 7 | 8 | 7 | 9 | 6 | 10 | **87** ⭐ |
| Ephemeral Branches | 8 | 10 | 10 | 8 | 7 | 9 | 7 | 10 | 7 | **76** |
| Worktrees | 10 | 1 | 10 | 6 | 5 | 10 | 8 | 9 | 8 | **67** |
| JSONL Reversal | 10 | 10 | 1 | 6 | 3 | 10 | 8 | 1 | 4 | **53** |
| Detached HEAD | 10 | 10 | 5 | 4 | 2 | 6 | 5 | 2 | 3 | **47** |
| Git Notes | 9 | 10 | 3 | 3 | 2 | 7 | 7 | 2 | 6 | **49** |
| APFS Snapshots | 10 | 10 | 9 | 2 | 2 | 8 | 1 | 1 | 9 | **52** |
| Git Stash | 8 | 10 | 3 | 7 | 4 | 4 | 2 | 3 | 5 | **46** |

### Decision Matrix by Constraint

**If you must have: Single Working Directory**
- ✅ Reflog-Based (77 points)
- ✅ Ephemeral Branches (69 points)
- ❌ Worktrees (59 points - fails this constraint)

**If you must have: Clean History**
- ✅ Reflog-Based (77 points)
- ✅ Worktrees (59 points)
- ⚠️ Ephemeral Branches (69 points - requires automation)

**If you must have: Reliable Rollback**
- ✅ Reflog-Based (77 points)
- ✅ Ephemeral Branches (69 points)
- ✅ Worktrees (59 points)
- ❌ JSONL Reversal (49 points - fails this constraint)

**If you must have: All Three + Fork Awareness**
- ✅ **Reflog-Based (87 points) - ONLY OPTION**

## Feature Comparison

### Parallel Sessions

| Strategy | Supports? | Notes |
|----------|-----------|-------|
| Worktrees | ✅ Yes | Primary use case |
| Reflog-Based | ⚠️ Sequential | One at a time on current branch |
| Ephemeral Branches | ⚠️ Sequential | Must checkout between |
| Others | ❌ No | Not designed for this |

### Agent Granularity

| Strategy | Granularity | Method |
|----------|-------------|--------|
| Reflog-Based | ⭐⭐⭐⭐ High | Commit messages + database tracking |
| Worktrees | ⭐⭐⭐ Good | Agent sub-branches possible |
| Ephemeral Branches | ⭐⭐⭐ Good | Agent sub-branches |
| JSONL Reversal | ⭐⭐⭐⭐ High | tool_use_id tracking |
| Others | ⭐⭐ Low | Limited tracking |

### Recovery Options

| Strategy | Full Session | Partial | Permanent Backup |
|----------|--------------|---------|------------------|
| Reflog-Based | ✅ Yes | ✅ Cherry-pick | ✅ Recovery branch |
| Ephemeral Branches | ✅ Yes | ✅ Cherry-pick | ✅ Keep branch |
| Worktrees | ✅ Yes | ✅ Cherry-pick | ✅ Keep branch |
| JSONL Reversal | ⚠️ Unreliable | ❌ Sequence-dependent | ✅ JSONL persists |
| Others | Varies | Varies | Varies |

## Recommendation

Based on comprehensive analysis:

### Primary Recommendation: Reflog-Based Rollback

**Justification:**
1. **Highest Score**: 87/90 points
2. **Meets All Constraints**: Only option that satisfies clean history + single directory + reliable rollback + fork awareness
3. **Fork-Aware Design**: Automatic checkpoints on conversation forks (see [02-research-findings.md] Finding 9)
4. **Proven Technology**: Built on 15+ years of git reflog reliability
5. **Configurable Safety**: Can extend retention, create recovery branches
6. **Simple Mental Model**: Commit → keep or reset → reflog backup
7. **Handles All Operations**: Git commits capture Edit, Write, and Bash changes
8. **Fork Visualization**: Track git state per conversation branch, enable fork tree display

### Implementation Approach

1. **Auto-commit on tool use** (Edit/Write/Bash)
2. **Record checkpoint** before session
3. **Auto-checkpoint on fork** (when conversation forks detected via JSONL - see [02-research-findings.md] Finding 9)
4. **Track commits** in database (session_id, agent_id, fork relationships)
5. **Track fork tree** (parent_uuid, child_uuid, fork_point_commit)
6. **Rollback via reset** (`git reset --hard`)
7. **Recovery via cherry-pick** (from reflog or recovery branch)
8. **Optional recovery branches** (permanent backup before rollback)
9. **Fork visualization** (show git state per conversation branch)

### Why Not the Others?

- **Worktrees** (59 pts): Infrastructure duplication unacceptable
- **Ephemeral Branches** (69 pts): Good, but reflog is cleaner (no branch management)
- **JSONL Reversal** (49 pts): Fundamentally unreliable
- **Others** (<50 pts): Various fatal flaws

## Next Steps

The next document will detail the rationale for selecting the reflog-based approach and address potential concerns.
