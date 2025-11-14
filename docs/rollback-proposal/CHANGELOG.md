# Rollback Proposal Changelog

## v2.1 (November 2025) - Checkpoint Selection Workflow

### Summary

Updated all 6 main rollback proposal documents to implement a comprehensive **checkpoint selection workflow** that replaced the original modal-based fork detection workflow with a non-destructive, user-friendly approach.

### Major Changes

#### 1. Non-Destructive Default Behavior
- **Before**: Modal prompts user when fork detected (blocking workflow)
- **After**: Silent checkpoint creation, code always continues
- **Impact**: No interruption to user workflow, decision made later in UI

#### 2. Multiple Checkpoints Per Message
- **Before**: One checkpoint per fork event
- **After**: Multiple checkpoints can exist for same message (when user returns multiple times)
- **Impact**: Full history preserved, all fork paths accessible

#### 3. Checkpoint Selector UI
- **Before**: Simple fork point restoration
- **After**: Bounded navigation with [←] [→] arrows through checkpoints
- **Impact**: Easy browsing of all available checkpoints per message

#### 4. Conversation Context Display
- **Before**: No context shown
- **After**: Last 30 messages displayed for each checkpoint
- **Impact**: User can see what happened in each conversation path

#### 5. Three Restore Actions
- **Before**: Single "rollback" action
- **After**: Three options:
  1. Restore Code & Continue Conversation (`claude --resume {session_uuid}`)
  2. Restore Code & Start New Conversation
  3. Restore Code Only (stay in current session)
- **Impact**: Flexible restoration to match user intent

#### 6. Reversibility Emphasis
- **Before**: "Destructive" warnings
- **After**: "Non-destructive" messaging with reflog preservation (180 days)
- **Impact**: User confidence in exploring checkpoints without fear

### Documents Updated

All updates maintain consistency across documents with identical terminology and design.

#### 00-executive-summary.md (~40 lines)
- Updated "How It Works" section (steps 4-7)
- Updated "Key Features" bullet points
- Added checkpoint selector and three restore actions

#### 01-problem-statement.md (~30 lines)
- Rewrote Scenario 4 from negative to positive outcome
- Updated Success Criteria #6 with checkpoint selector requirements
- Added bounded navigation and message context requirements

#### 02-research-findings.md (~50 lines)
- Completely rewrote Finding 9 fork detection workflow
- Changed from modal-based to silent checkpoint creation
- Added checkpoint selector UI details
- Added three restore actions explanation

#### 05-implementation-plan.md (~80 lines)
- Extended Phase 2.5 (Fork Detection) with database schema changes
- Extended Phase 4 (Web UI) with checkpoint selector component
- Added React component design example
- Added API endpoint specifications

#### 06-system-design.md (~150 lines)
- Added `message_uuid` column to database schemas
- Added new API endpoints for checkpoint selection
- Added `get_checkpoints_with_context()` method to ForkManager
- Added `get_checkpoint_messages()` method
- Added complete checkpoint selector UI mockup
- Added bounded navigation implementation details

#### 07-fork-integration.md (~400 lines)
- Completely rewrote Section 1.2 (Fork Detection Workflow)
- Completely rewrote Section 7.1 (User Interaction Flow)
- Replaced Section 5.3 (Fork Comparison) with checkpoint selector
- Updated workflow diagrams throughout
- Added emphasis on non-destructive operations
- Added implementation checklist updates

### Database Schema Changes

```sql
-- conversation_forks table
ALTER TABLE conversation_forks ADD COLUMN message_uuid TEXT;

-- git_checkpoints table
ALTER TABLE git_checkpoints ADD COLUMN message_uuid TEXT;
ALTER TABLE git_checkpoints ADD COLUMN checkpoint_type TEXT DEFAULT 'manual';

-- Indexes
CREATE INDEX idx_git_checkpoints_message ON git_checkpoints(message_uuid);
```

### New API Endpoints

```
GET /api/sessions/{id}/checkpoints
    Returns: List of checkpoints with conversation context

GET /api/checkpoints/{id}/messages?count=30
    Returns: Last N messages for checkpoint's conversation path

GET /api/checkpoints/{id}/preview
    Returns: Git diff preview without making changes
```

### Key Design Principles

1. **Non-blocking**: No modals during normal workflow
2. **Non-destructive**: All operations reversible via reflog
3. **Context-rich**: Show conversation history for each checkpoint
4. **Flexible**: Three restore actions to match user intent
5. **Discoverable**: Bounded navigation with clear disabled states
6. **Reversible**: 180-day reflog window for recovery

### Implementation Timeline

No change to overall 9-week timeline. Checkpoint selector UI work absorbed into existing Phase 4 (Web UI).

### Compatibility

- Backward compatible with v2.0 fork detection
- Uses existing JSONL parsing code
- No breaking changes to database schema (additive only)
- Integrates with existing `claude --resume` functionality

### Testing Requirements

- [ ] Multiple checkpoints per message
- [ ] Bounded navigation (disabled states at edges)
- [ ] Last 30 messages retrieval from JSONL
- [ ] Three restore actions execute correctly
- [ ] Reflog preservation after rollback
- [ ] Cross-session fork detection still works
- [ ] UI performance with 10+ checkpoints per message

### Migration Notes

For implementers upgrading from v2.0 to v2.1:

1. Run database migrations (add `message_uuid` columns)
2. Update ForkManager with new methods
3. Add checkpoint selector React component
4. Add new API endpoints
5. Update fork detection to record `message_uuid`
6. Test bounded navigation with existing checkpoints

---

**Version**: v2.1
**Date**: November 2025
**Total Changes**: ~750 lines across 6 documents
**Breaking Changes**: None (additive only)
**Status**: Ready for implementation
