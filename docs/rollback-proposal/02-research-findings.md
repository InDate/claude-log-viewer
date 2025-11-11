# Research Findings: Rollback Strategies for Claude Code

## Overview

This document presents comprehensive research into various strategies for implementing reliable rollback functionality for Claude Code sessions. Research included technical analysis, industry best practices, git internals investigation, and critical evaluation of proposed approaches.

## Research Methodology

1. **Technical Documentation Review**
   - Claude Code official documentation (checkpointing, sub-agents, hooks)
   - Git documentation (reflog, worktrees, branches, stash)
   - File system features (APFS snapshots, Time Machine)

2. **Source Code Analysis**
   - claude-code-rewind tool (snapshot engine, rollback engine, file store)
   - claude-log-viewer codebase (session tracking, timeline building)

3. **Industry Research**
   - AI coding assistant patterns (Aider, Cursor, Copilot)
   - Developer community practices (blog posts, GitHub projects)
   - Git workflow strategies for AI-assisted development

4. **Critical Analysis**
   - Agent-based critical review of JSONL reversal approach
   - Edge case identification
   - Failure mode analysis

## Key Findings

### Finding 1: Claude Code Rewind Limitations

**Current Checkpoint Behavior:**

From official documentation:
> "Checkpointing does not track files modified by bash commands"

**What This Means:**
- Only tracks changes made through Claude's file editing tools (Edit, Write)
- Bash command effects are invisible to checkpoints
- External modifications not captured

**Impact:**
- Cannot reliably rollback sessions that use Bash
- Agents that use Bash (common pattern) cannot be fully rolled back
- Manual changes between Claude operations are lost on rewind

**Evidence from Documentation:**
```
Checkpoints apply to Claude's edits and not user edits or bash commands,
and they are recommended to be used in combination with version control.
```

### Finding 2: Git Worktree Strategy Analysis

**What We Found:**

Git worktrees are the **most popular strategy** in the AI coding community for managing parallel development sessions.

**Industry Adoption:**

1. **incident.io Engineering Blog**
   - Article: "How we're shipping faster with Claude Code and Git Worktrees"
   - Pattern: Each Claude session gets dedicated worktree
   - Benefits: Perfect isolation, parallel sessions, clean main branch

2. **coplane/par Project**
   - GitHub CLI tool for parallel worktree management
   - Specifically designed for agentic development workflows
   - Automates worktree creation/cleanup

3. **Gemini CLI + Worktrees Pattern**
   - Documented approach for parallel AI development
   - Multiple agents work in separate worktrees simultaneously

4. **Common Medium/Blog Posts**
   - "Git Worktrees for AI-Assisted Development"
   - "Managing Multiple Claude Sessions with Worktrees"
   - Strong community consensus on this approach

**Technical Deep Dive:**

```bash
# Worktree creation
git worktree add ../session-{id} -b claude-session-{id}

# Results in:
project/
├── main/                  # Main worktree
│   └── .git/             # Shared git object database
└── session-abc/          # Secondary worktree
    └── files...          # Separate working directory
```

**Key Insight:**
- All worktrees share the **same .git object database**
- Only working directories are duplicated
- No git history duplication (storage efficient)

**However: Critical Infrastructure Problem**

Our research identified a fatal flaw:

```
Each worktree needs:
✗ Separate dev server (different ports)
✗ Separate database instance
✗ Separate environment configuration
✗ Separate Docker containers
✗ Separate API connections
```

**Verdict:** Technically sound for git, but **impractical for real development** due to infrastructure duplication.

### Finding 3: Git Reflog Deep Dive

**What is Reflog:**

Git's "reference log" tracks every movement of HEAD and branch pointers. It's Git's safety net for recovering "lost" commits.

**Key Properties:**

1. **Local Only**
   - Never synced to remote
   - Each developer has their own reflog
   - Private history of your actions

2. **Time-Limited**
   - Default retention: 90 days for reachable entries
   - Default retention: 30 days for unreachable entries
   - Configurable: can extend to 180+ days

3. **Comprehensive**
   - Records commits, resets, checkouts, merges, rebases
   - Captures "deleted" commits (after `git reset --hard`)
   - Survives most git operations except garbage collection

**Example Reflog Output:**

```bash
$ git reflog
a1b2c3d HEAD@{0}: commit: Add feature
e4f5g6h HEAD@{1}: commit: Fix bug
i7j8k9l HEAD@{2}: reset: moving to HEAD~5  ← Reset happened here
m0n1o2p HEAD@{3}: commit: Experimental work (now "lost")
```

**Recovery Demonstration:**

```bash
# After reset, commits invisible in git log
$ git log --oneline
a1b2c3d Current state

# But reflog remembers
$ git reflog
a1b2c3d HEAD@{0}: reset: moving to HEAD~5
[previous commits listed]
m0n1o2p HEAD@{5}: commit: Experimental work

# Recovery
$ git reset --hard HEAD@{5}
# Or: git cherry-pick m0n1o2p
```

**Storage Location:**
- `.git/logs/HEAD` - HEAD movements
- `.git/logs/refs/heads/<branch>` - Per-branch logs
- Plain text files, human-readable

**Garbage Collection Behavior:**

```bash
# Automatic (triggered by various git operations)
git gc --auto

# Manual
git gc --prune=now  # ⚠️ Deletes unreachable commits immediately

# Configuration
git config gc.reflogExpire "180 days"
git config gc.reflogExpireUnreachable "180 days"
```

**Critical Insight:**

Reflog enables a **"commit now, decide later"** workflow:
1. Make commits freely during Claude session
2. Review commits afterward
3. **Keep**: Push to remote (permanent)
4. **Discard**: `git reset --hard` (commits → reflog)
5. **Recover**: Cherry-pick from reflog if you change your mind

This provides **clean history** (discarded commits invisible in `git log`) while maintaining **recovery capability** (reflog access for 90-180 days).

### Finding 4: JSONL-Based Reversal Analysis

**Initial Hypothesis:**

Could we avoid storing file snapshots by using Edit tool's old_string/new_string from JSONL to reverse changes?

**Agent's Critical Analysis:**

We tasked an agent with being "ruthlessly critical" of this approach. The agent identified **10+ fatal flaws**.

**Critical Flaw #1: Non-Symmetric Reversibility**

```python
# Original file
def foo():
    return 1

# Edit #1
Edit(old="return 1", new="return 2")

# Edit #2
Edit(old="def foo():", new="def bar():")

# Current state:
def bar():
    return 2

# Try to reverse Edit #2:
Edit(old="def bar():", new="def foo():")
# ❌ FAILS if any intervening change affected indentation, added type hints, etc.
```

**Critical Flaw #2: External Changes Break Chain**

```python
# Session sequence:
Claude: Edit(old="x", new="y")  # File now has "y"
User: Manually changes "y" to "z"
Claude: Tries to reverse: Edit(old="y", new="x")
# ❌ FAILS - file contains "z", not "y"
```

**Critical Flaw #3: Bash Operations Unreversible**

```bash
rm -rf /important/directory     # How to reverse?
curl -X POST api.com/deploy     # Already deployed!
npm publish                     # Already on npm registry!
git push --force                # Remote history rewritten!
docker system prune -af         # Containers deleted!
```

**Critical Flaw #4: Context Ambiguity**

```python
# File has multiple identical blocks
if condition:
    return True
# ...
if other_condition:
    return True

# Edit operation
Edit(old="return True", new="return False")

# Which "return True" was changed?
# JSONL doesn't store enough context to know!
```

**Critical Flaw #5: Sequence Dependency**

```python
# Forward sequence
Edit #1: old="foo", new="bar"
Edit #2: old="bar", new="baz"
Edit #3: old="baz", new="qux"

# Must reverse in EXACT reverse order
# Cannot selectively undo just Edit #2
# Must undo #3, then #2, then #1

# Want to undo only #2?
# ❌ IMPOSSIBLE - file state doesn't match
```

**Agent's Verdict:**

> "The JSONL-based reversal approach suffers from false assumptions about file state persistence, cannot handle Bash operations, and attempts to build version control on top of non-versioned operations. This is fundamentally doomed."

**Verdict:** ❌ Unreliable and dangerous

### Finding 5: claude-code-rewind Tool Analysis

**What We Found:**

The claude-code-rewind tool (found at holasoymalva/claude-code-rewind) provides a snapshot-based rollback system.

**Architecture:**

```python
Snapshot Engine:
- Scans project files
- Calculates SHA-256 hash per file
- Stores changed files with compression (zstandard)
- Detects changes via hash comparison

Rollback Engine:
- Compares current state to snapshot
- Identifies files to restore/delete
- Performs three-way merge for conflicts
- Handles selective rollback (specific files only)

Storage:
- Content-addressable store (deduplicated by hash)
- SQLite for metadata
- Compression ratio: ~6.5% of original size
- Performance: <500ms snapshot for projects <1GB
```

**Key Features:**

1. **Incremental Snapshots**
   - Only stores changed files
   - Hash-based change detection
   - Parallel file processing for speed

2. **Smart Conflict Resolution**
   - Three-way merge attempts
   - Heuristics for comment-only/whitespace-only changes
   - Fallback strategies for conflicts

3. **Performance Optimizations**
   - Hash caching (file path + mtime + size)
   - Parallel file scanning
   - Lazy content loading
   - Configurable compression levels

**Limitations Discovered:**

1. **No JSONL Integration**
   - The `hooks/__init__.py` file is **empty**
   - No actual Claude Code integration exists
   - It's a framework/concept, not working integration

2. **Still Can't Prevent Bash Issues**
   - Can snapshot before operations
   - But how to know WHEN to snapshot?
   - Cannot predict future Bash commands

3. **Storage Requirements**
   - Write operations require storing entire file
   - Large binaries (images, videos, bundles) add up quickly
   - For 1GB project with frequent writes: potentially hundreds of MB

**Verdict:** ✓ Solid approach for file snapshots, but incomplete solution (Bash handling, integration)

### Finding 6: Ephemeral Branch Strategies

**Pattern: Temporary Branches with Auto-Deletion**

```bash
# Create session branch
git checkout -b claude-session-{uuid}

# Work happens...

# Cleanup options:
git branch -D claude-session-{uuid}          # Delete immediately
git branch -d claude-session-{uuid}          # Delete if merged
git push origin :claude-session-{uuid}       # Delete remote
```

**Industry Usage:**

1. **GitHub: "Automatically delete head branches"**
   - Built-in feature for PRs
   - Deletes branch after merge
   - Industry standard practice

2. **Aider AI**
   - Creates temporary review branches
   - Pattern: `aider-review-branch`
   - User manually deletes after review

3. **GitLab/GitHub CI**
   - Temporary branches for CI runs
   - Auto-deleted after pipeline complete

**Advantages:**
- ✅ Simple concept (everyone knows branches)
- ✅ Git-native (no special tools)
- ✅ Reflog provides safety net
- ✅ Easy rollback (`git branch -D`)

**Disadvantages:**
- ❌ Branch list clutter if not cleaned
- ❌ Risk of accidental push to remote
- ❌ Requires discipline to delete
- ❌ Can't run parallel sessions (must checkout)

**Git Hooks for Prevention:**

```bash
# .git/hooks/pre-push
#!/bin/bash
# Prevent pushing claude-session branches
if [[ $ref =~ refs/heads/claude-session-.* ]]; then
    echo "ERROR: Don't push temporary Claude session branches!"
    exit 1
fi
```

**Verdict:** ✓ Viable, but requires automation and discipline

### Finding 7: AI Coding Assistant Patterns

**Research Question:** How do other AI coding tools handle this?

**Aider AI:**
- **Strategy**: Auto-commits each changeset
- **Commit Messages**: Descriptive, generated by AI
- **Branch Management**: Leaves to user
- **Rollback**: Via standard git (revert, reset)
- **Philosophy**: "Commit frequently, git is your safety net"

**Cursor IDE:**
- **Strategy**: Generates AI commit messages
- **Git Integration**: Standard git panel in editor
- **Branch Management**: User handles manually
- **Philosophy**: Traditional git workflows

**GitHub Copilot:**
- **Strategy**: No git integration (autocomplete-focused)
- **Copilot Workspace**: PR refinement tool
- **No session management**: Copilot doesn't manage sessions

**Common Patterns Across All Tools:**

1. ✅ **Commit frequently** (small, atomic commits)
2. ✅ **Descriptive messages** (AI-generated or manual)
3. ✅ **Branch per feature** (standard git workflow)
4. ✅ **Review before commit** (show diffs, user approves)
5. ✅ **Git as safety net** (rely on git for undo)

**Key Insight:**

**NO AI coding tool prescribes a specific branching strategy** - they all adapt to user's existing workflow. The community consensus is:
- Use branches liberally
- Commit frequently
- Git worktrees for parallel work (emerging pattern)

### Finding 8: macOS APFS Snapshots

**Technical Investigation:**

APFS (Apple File System) supports copy-on-write snapshots similar to Volume Shadow Copy (VSS) on Windows.

**Capabilities:**

```bash
# Create snapshot
tmutil localsnapshot

# List snapshots
tmutil listlocalsnapshots /

# Mount snapshot (read-only)
tmutil mount /Volumes/.timemachine/{snapshot-name}

# Delete snapshot
tmutil deletelocalsnapshots {date}
```

**How It Works:**
- Copy-on-write at filesystem level
- Instant snapshot creation
- Space-efficient (only changed blocks stored)
- Integrated with Time Machine

**Pros:**
- ✅ Captures entire filesystem state atomically
- ✅ Fast (CoW technology)
- ✅ Works regardless of how files changed
- ✅ Can restore even if git repo corrupted

**Cons:**
- ❌ macOS only (not cross-platform)
- ❌ Coarse-grained (entire volume, not just repo)
- ❌ Read-only (can't modify past snapshots)
- ❌ Restore requires copying files back manually
- ❌ No tooling for git integration

**Verdict:** ❌ Overkill for session management, better for disaster recovery

## Synthesis of Findings

### What Works

1. **Git Worktrees** - Perfect for parallel sessions, but impractical due to infrastructure duplication
2. **Git Reflog** - Excellent safety net, enables "commit now, decide later" workflow
3. **Ephemeral Branches** - Simple and effective, but requires discipline
4. **File Snapshots** - Reliable for file state, but incomplete (Bash handling)

### What Doesn't Work

1. **JSONL Reversal** - Fundamentally flawed, unreliable
2. **Checkpoints Alone** - Incomplete coverage (misses Bash)
3. **Git Stash** - Not designed for session management
4. **Detached HEAD** - Too risky, easy to lose work

### The Constraint Trilemma

Research confirms we must choose 2 of 3:
- **Clean git history**
- **Single working directory**
- **Reliable rollback**

**Evidence:**
- Worktrees sacrifice single directory
- JSONL sacrifice reliability
- Branches sacrifice clean history (without automation)

### The Reflog Insight

**Key Discovery:** Reflog enables all three constraints:

1. **Clean History**: `git reset --hard` removes commits from git log
2. **Single Directory**: No worktrees, work on main branch
3. **Reliable Rollback**: Commits are real git commits (capture all changes)

**With the addition of:**
- Extended reflog retention (180 days)
- Optional recovery branches for permanent backup
- Database tracking for session → commit mapping

## Recommendations from Research

Based on comprehensive analysis:

### Primary Recommendation: Reflog-Based Approach

**Rationale:**
1. Meets all three constraints (clean history, single dir, reliable)
2. Proven technology (git reflog has 15+ year track record)
3. Simple mental model (commit, keep or reset, reflog backup)
4. Configurable safety (extend retention, create recovery branches)
5. Handles all operation types (Edit, Write, Bash - all captured in commits)

### Supporting Strategies:

1. **Auto-Commits on Tool Use**
   - Commit after each Edit/Write/Bash operation
   - Descriptive messages with metadata
   - Linked to JSONL tool_use_id

2. **Session Checkpoint System**
   - Record HEAD before session starts
   - Track all commits during session
   - Enable session-granular rollback

3. **Agent Sub-Session Tracking**
   - Tag commits with agent_id
   - Enable per-agent rollback
   - Commit messages include agent context

4. **Optional Recovery Branches**
   - Push to `refs/recovery/{session-id}` before rollback
   - Permanent backup on remote
   - For important/risky sessions

## Research Gaps

Areas requiring further investigation:

1. **Performance Impact**
   - How does frequent auto-committing affect git performance?
   - What's the overhead of reflog lookups?
   - Storage growth over time?

2. **Team Workflows**
   - How does this work with multiple developers?
   - Do reflog-based rollbacks confuse collaborators?
   - Best practices for shared repositories?

3. **Large Repositories**
   - Does this scale to monorepos?
   - Impact on git operations (gc, fsck, etc.)?

4. **Recovery UX**
   - What's the optimal UI for browsing reflog?
   - How to make recovery intuitive for non-git-experts?

## Conclusion

Research strongly supports a **reflog-based rollback strategy** as the optimal solution:

- ✅ Addresses all user requirements
- ✅ Backed by proven git technology
- ✅ Supported by industry patterns (frequent commits)
- ✅ Avoids pitfalls of other approaches (worktree overhead, JSONL unreliability)
- ✅ Provides flexibility (recovery window, partial recovery, permanent backup options)

The next document will analyze all options comparatively to justify this selection.
