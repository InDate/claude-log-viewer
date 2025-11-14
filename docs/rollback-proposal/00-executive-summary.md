# Executive Summary: Claude Code Rollback Solution

## Project Overview

This proposal presents a comprehensive solution for implementing reliable rollback functionality for Claude Code sessions in the claude-log-viewer application. The solution enables users to undo changes made by Claude Code, including those made by agents and through Bash operations, while maintaining clean git history and working in a single directory.

## The Problem

Claude Code's built-in checkpoint/rewind feature has critical limitations:
- Does not track bash command modifications
- Cannot rewind external changes or concurrent modifications
- Agent changes may not be fully captured
- **Conversation forking not tracked** - No checkpoints at fork points
- Not suitable as primary version control

Users need a reliable way to rollback entire sessions or selectively recover specific changes without:
- Polluting git branch history with experimental commits
- Managing multiple working directories (git worktrees)
- Duplicating development infrastructure (servers, databases, configs)

**See:** [01-problem-statement.md](01-problem-statement.md)

## Research Findings

We conducted extensive research into rollback strategies:

### Investigated Approaches

1. **Git Worktrees + Ephemeral Branches** - Most popular in AI coding community
2. **Ephemeral Branches Only** - Simple but requires discipline
3. **Reflog-Based Rollback** - Leverages git's safety net
4. **Git Stash** - Quick saves, not for sessions
5. **Detached HEAD** - Too risky for beginners
6. **Git Notes / Custom Refs** - Niche, complex
7. **APFS Snapshots** - macOS only, overkill
8. **JSONL-Based Reversal** - Fundamentally flawed

### Key Research Insights

- **Industry Practice**: All AI coding tools use frequent git commits as safety net
- **Worktree Adoption**: Growing for parallel sessions, but requires infrastructure duplication
- **JSONL Reversal**: Critical analysis revealed 10+ insurmountable flaws
- **Reflog**: Enables "commit now, decide later" workflow with 90-180 day recovery window
- **Fork Detection**: Existing implementation monitors JSONL for conversation forks, proven at scale

**See:** [02-research-findings.md](02-research-findings.md)

## Options Analysis

We evaluated eight strategies across nine criteria (scored 1-10):

| Strategy | Total Score | Key Strengths | Fatal Flaws |
|----------|-------------|---------------|-------------|
| **Reflog-Based** | **87/90** | Clean history, single dir, reliable, **fork-aware** | Time-limited recovery (mitigated) |
| Ephemeral Branches | 76/90 | Simple, git-native | Requires cleanup automation |
| Worktrees | 67/90 | Perfect isolation | **Infrastructure duplication** |
| JSONL Reversal | 53/90 | Minimal storage | **Fundamentally unreliable** |
| Others | <60/90 | Various | Various fatal flaws |

### The Constraint Trilemma

Research confirmed we must choose 2 of 3:
- Clean git history
- Single working directory
- Reliable rollback

**Only the reflog-based approach satisfies all three constraints.**

**See:** [03-options-analysis.md](03-options-analysis.md)

## Selected Solution: Reflog-Based Rollback

### How It Works

```
1. Session Start → Create checkpoint (record HEAD position)
2. During Session → Auto-commit after each Edit/Write/Bash operation
3. Fork Detection → Auto-checkpoint when conversation forks (automatic)
4. User Reviews → Open checkpoint selector with bounded navigation [←] [→]
5. Browse Checkpoints → View last 30 messages for each checkpoint
6. Choose Action:
   • Preview Changes → View diff without making changes
   • Rollback to Checkpoint → Reset (non-destructive, commits → reflog)
   • View Messages Only → Read conversation context
7. All Actions Reversible → 180-day reflog window + undo rollback
```

### Why This Solution?

**Satisfies All Requirements:**
- ✅ Clean git history (`git reset` removes commits from git log)
- ✅ Single working directory (no worktrees or checkouts)
- ✅ Reliable rollback (git commits capture all changes)
- ✅ Handles all operations (Edit, Write, Bash all captured)
- ✅ **Fork awareness** (automatic checkpoints on conversation forks)
- ✅ **Fork visualization** (git state tracked per conversation branch)
- ✅ Agent granularity (commit messages track agents)
- ✅ Partial recovery (cherry-pick specific commits)

**Built on Proven Technology:**
- Git reflog has 15+ years of reliability
- No custom implementation of version control
- Well-documented and understood

**Aligns with Industry:**
- Matches AI coding tool patterns (frequent commits)
- Supports emerging best practices
- Future-compatible with worktrees if needed

**See:** [04-solution-selection.md](04-solution-selection.md)

## Implementation Plan

### Architecture

**New Components:**
1. **GitRollbackManager** - Core git operations and reflog management
2. **ForkManager** - Fork detection and checkpoint automation
3. **Database Extensions** - Track checkpoints, commits, and fork relationships
4. **Auto-Commit Integration** - Hook into JSONL processing
5. **Web UI** - Rollback controls, commit timeline, fork tree visualization, diff viewer

**Integration Points:**
- Existing JSONL processing
- Session tracking
- Database schema
- Flask API
- React UI

### Timeline

| Phase | Duration | Deliverables |
|-------|----------|--------------|
| Core Git Module | 2 weeks | GitRollbackManager, tests |
| Database Schema | 1 week | Migrations, new tables/methods |
| **Fork Detection** | **1 week** | **ForkManager, auto-checkpoint on forks** |
| Auto-Commit | 1 week | JSONL integration |
| Web UI | 2 weeks | API routes, React components, fork visualization |
| Docs & Tests | 1 week | Documentation, test suite |
| Polish & Launch | 1 week | Final testing, release |
| **Total** | **9 weeks** | **Full implementation with fork awareness** |

### Key Features

**User-Facing:**
- "Create Checkpoint" button before sessions
- **Automatic fork detection** with checkpoint creation (no user action required)
- **Checkpoint selector UI** with bounded navigation [←] [→]
- **Last 30 messages** shown for each checkpoint (conversation context)
- **Three restore actions** for each checkpoint:
  - Preview Changes (view diff without making changes)
  - Rollback to Checkpoint (non-destructive, commits → reflog)
  - View Messages Only (read conversation context)
- **All rollback actions reversible** via reflog (180-day window)
- **Fork tree visualization** showing git state per branch
- **Fork comparison** (diff between conversation branches)
- "Recover Commit" for selective recovery
- Color-coded agent vs main session commits
- Diff viewer with syntax highlighting
- Optional recovery branch creation

**Developer-Facing:**
- Simple API (`create_checkpoint`, `rollback_session`, etc.)
- Automatic reflog configuration (180-day retention)
- Error handling and logging
- Comprehensive test suite

**See:** [05-implementation-plan.md](05-implementation-plan.md)

## Risk Assessment

### Low Risk
- ✅ Technical feasibility (proven git technology)
- ✅ User comprehension (simple mental model)
- ✅ Data loss (180-day recovery + optional permanent backup)

### Medium Risk
- ⚠️ Multi-machine workflows (mitigation: recovery branches)
- ⚠️ Team collaboration (mitigation: document patterns)
- ⚠️ Git expertise (mitigation: UI abstracts complexity)

### High Risk
- None identified

**Mitigation Strategies:**
- Extended reflog retention (configurable)
- Recovery branch option (permanent backup before rollback)
- UI abstracts git commands (tooltips and documentation)
- Comprehensive error handling

## Success Metrics

Post-implementation tracking:

1. **Rollback Success Rate**: Target >90%
2. **User Adoption**: Target >50% create checkpoints
3. **Fork Detection Rate**: Target >95% of forks automatically detected
4. **Recovery Window**: 99% of recoveries within 180 days
5. **Performance**: Auto-commit adds <100ms overhead, fork detection <115ms
6. **Storage**: Reflog overhead <5% of project size

## Recommendation

**Proceed with reflog-based rollback implementation.**

**Justification:**
- Only solution meeting all requirements (including fork awareness)
- Highest score in comparative analysis (87/90)
- Built on proven, reliable technology
- Fork detection already proven with existing implementation
- Clear 9-week implementation path
- Low-to-medium risk profile with mitigations

**Next Steps:**
1. Review this proposal
2. Approve for implementation
3. Begin Phase 1 (Core Git Module)
4. Track progress against 9-week timeline

## Document Index

This proposal consists of the following documents:

1. **[01-problem-statement.md](01-problem-statement.md)** - Detailed problem analysis, user requirements (including fork detection), why existing solutions fail
2. **[02-research-findings.md](02-research-findings.md)** - Comprehensive research into rollback strategies, industry practices, git internals, **fork detection patterns**
3. **[03-options-analysis.md](03-options-analysis.md)** - Comparative evaluation of 8 approaches with scoring matrix (9 criteria including fork awareness)
4. **[04-solution-selection.md](04-solution-selection.md)** - Rationale for selecting reflog approach, **fork integration**, risk assessment
5. **[05-implementation-plan.md](05-implementation-plan.md)** - Detailed implementation guide with timeline, testing, **fork detection phase**
6. **[06-system-design.md](06-system-design.md)** - Complete technical design including **ForkManager component, fork visualization, fork APIs**
7. **[07-fork-integration.md](07-fork-integration.md)** - Comprehensive fork detection integration guide

---

**Prepared:** November 2025
**Status:** Proposal - Awaiting Approval
**Estimated Implementation:** 9 weeks (single developer)
