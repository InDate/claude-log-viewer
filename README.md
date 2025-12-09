# Claude Code Log Viewer

An interactive web-based viewer for Claude Code JSONL transcript files with real-time monitoring, usage tracking, and git integration.

## 🤔 Why Did I Build This?

**Claude Code needs an observation tool.** Observing is a different activity than coding - it's about reflection, understanding, and decision-making.

This tool enables:

- **🔍 Reflection on Changes** - Review what Claude actually did, not just what you asked for
- **🗺️ Retrace Agent Actions** - See the conversation branches, timeline of decisions, and evolution of solutions
- **📋 Easy Access to Context** - Find past plans, todos, and commits without digging through files
- **🎯 Session Discovery** - Quickly locate the correct session when resuming work
- **⏮️ Rollback Capability** - Undo agent and standard changes through git integration (when enabled)

Claude Code is powerful, but without visibility into its actions, you're flying blind. This tool gives you the observation layer that makes Claude Code truly manageable for serious development work.

## ✨ Features

### 📊 **Real-Time Session Monitoring**
- Live file watching with automatic updates
- Session-based organization with color-coded cards
- Message count and token usage per session
- Last active timestamp tracking
- Configurable auto-refresh (1s to 60s intervals)

### 🔍 **Advanced Filtering & Search**
- Full-text search across all message content
- **Clickable search results** - click any result to load full file history
- **`--all` flag** - search all JSONL files on disk (e.g., `myterm --all`)
- **`file:` prefix** - filter by specific file (e.g., `file:/path/to/file.jsonl`)
- **Highlighted matches** - matching rows highlighted when viewing file
- Filter by message type (user, assistant, tool_result, file-history)
- Limit display (50, 100, 200, 500 entries)
- Session-specific filtering
- Interactive field selection

### 📈 **Usage Tracking & Analytics**
- Real-time Claude API usage monitoring
- 5-hour and 7-day usage windows
- Token consumption tracking with deltas
- Usage snapshot history
- Automatic API polling (10-second intervals)
- Backend-driven calculation pipeline

### 🎨 **Rich Content Display**
- Syntax highlighting for code blocks
- Markdown rendering for formatted text
- Screenshot display support
- Tool result visualization
- Collapsible message sections
- Dark theme optimized for readability

### 📋 **Todo & Plan Management**
- View todo lists from Claude sessions
- Track ExitPlanMode entries
- Todo file integration
- Session-specific todo filtering

### 🌳 **Git Integration** (Experimental)
- Manual checkpoint creation
- Git repository discovery
- Per-project and per-repo git controls
- Checkpoint listing and management
- Git commit tracking
- Repository status monitoring

### 📊 **Timeline Visualization**
- Conversation flow visualization
- Message relationship tracking
- Fork detection (in development)
- Interactive timeline view

### ⚙️ **Settings & Configuration**
- Persistent settings storage
- Git enable/disable per project
- Git enable/disable per repository
- Customizable refresh intervals
- View mode preferences

## 🚀 Installation

### From PyPI (recommended)

```bash
pip install claude-log-viewer
```

### From source

```bash
git clone https://github.com/InDate/claude-log-viewer.git
cd claude-log-viewer
pip install -e .
```

## 📖 Usage

### Start the server

```bash
claude-log-viewer
```

### Command-line options

```bash
# Specify project to monitor
claude-log-viewer --project my-project

# Set maximum entries to display
claude-log-viewer --max-entries 1000

# Set file age filter (days)
claude-log-viewer --file-age 7

# Set port
claude-log-viewer --port 5001
```

### Access the web interface

Open your browser to:
```
http://localhost:5001
```

### CLI Search Tools

For searching log files from the command line:

```bash
# Search for a pattern across all projects
claude-log-tools search "error" --days 7

# Search within a specific project
claude-log-tools search "TODO" --project my-project

# Count entries per session/project
claude-log-tools count --days 3

# List sessions with metadata
claude-log-tools sessions --project my-project --days 14
```

The viewer will automatically load JSONL files from:
- `~/.claude/projects/` - Claude Code session transcripts
- `~/.claude/todos/` - Todo lists

## 🎮 Controls

### Main Interface
- **Search**: Filter entries by any text content
  - Results are clickable - click to load the full file history
  - Add `--all` to search all files on disk (slower but comprehensive)
  - Use `file:/path/to/file.jsonl` to view a specific file
  - Matching rows are highlighted with a blue border
- **Type Filter**: Filter by entry type (user, assistant, tool_result, etc.)
- **Limit**: Control how many entries to display (50-500)
- **Refresh**: Manually reload all entries
- **Auto-refresh**: Enable automatic updates (1s-60s intervals)
- **Timeline**: Toggle between table and timeline visualization
- **Settings**: Configure git integration and preferences

### Session Cards
- Click session card to filter entries for that session
- View message count, token usage, and last active time
- Access todos and plans for each session
- Color-coded for easy identification

### Content Viewer
- Click message content to open in modal
- Syntax highlighting for code
- Markdown rendering for formatted text
- Screenshot display support
- Copy content to clipboard

## 🔧 Technical Details

### Backend
- **Framework**: Flask (Python 3.9+)
- **File Watching**: Watchdog for real-time monitoring
- **Database**: SQLite with WAL mode for concurrency
- **API Polling**: Background thread for usage updates
- **Token Counting**: tiktoken for accurate token calculation

### Frontend
- **Vanilla JavaScript** (ES6 modules)
- **Markdown**: markdown-it for rendering
- **Syntax Highlighting**: highlight.js
- **No framework dependencies** - lightweight and fast

### Architecture
- **Async file processing**: Queue-based worker thread
- **Backend-driven calculations**: Snapshot pipeline
- **Bucket assignment algorithm**: Efficient usage tracking
- **Git integration**: GitRollbackManager for checkpoints

## 📁 Data Storage

- **Database**: `~/.claude/logviewer.db` (SQLite)
- **JSONL Files**: `~/.claude/projects/*/agent-*.jsonl`
- **Screenshots**: `~/.claude/projects/*/.claude/screenshots/`
- **Todos**: `~/.claude/todos/`

### Database Management

The application stores usage snapshots, session metadata, and git checkpoints in `~/.claude/logviewer.db`.

#### Rebuild Database

If you need to rebuild the database (⚠️ **this will delete all usage snapshot history**):

```bash
# Stop the application first
# Then remove the database file
rm ~/.claude/logviewer.db

# Restart the application - it will create a fresh database
claude-log-viewer
```

The database will be recreated with:
- ✅ Empty usage_snapshots table (history lost)
- ✅ Fresh sessions table
- ✅ Empty git checkpoints
- ✅ All settings reset to defaults

**Note**: JSONL transcript files are NOT affected - only the viewer's internal database is deleted.

#### Backup Database

To preserve your usage history:

```bash
# Create backup
cp ~/.claude/logviewer.db ~/.claude/logviewer.db.backup

# Restore from backup
cp ~/.claude/logviewer.db.backup ~/.claude/logviewer.db
```

#### Database Schema

The database includes:
- `usage_snapshots` - API usage tracking over time
- `sessions` - Session metadata and statistics  
- `git_checkpoints` - Manual and automatic checkpoints
- `git_commits` - Git commit tracking
- `conversation_forks` - Fork detection data
- `settings` - Application settings
- `project_git_settings` - Per-project git configuration
- `repo_git_settings` - Per-repository git configuration
- `discovered_repos` - Git repository discovery cache

## 🚧 Planned Features

See [docs/rollback-proposal/](docs/rollback-proposal/) for detailed design documentation of upcoming features:

- **Full Checkpoint Selector UI** - Navigate through conversation checkpoints with context
- **Fork Detection & Navigation** - Automatic detection and visualization of conversation branches
- **Session Branching** - Visual representation of conversation forks
- **Enhanced Session Management** - Delete, rename, and resume sessions from UI
- **Markdown Tool Results** - Rich rendering of tool outputs
- **Image Display** - Inline image viewing in sessions

## 🐛 Known Issues

- **Cross-Platform Testing** - Only tested on macOS, needs Windows/Linux verification ([Issue #5](https://github.com/InDate/claude-log-viewer/issues/5))

### Recently Fixed

- ✅ **Token Delta Calculation** - Fixed in v1.0.1 ([Issue #9](https://github.com/InDate/claude-log-viewer/issues/9))

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

### Development Setup

```bash
# Clone repository
git clone https://github.com/InDate/claude-log-viewer.git
cd claude-log-viewer

# Install in development mode
pip install -e .

# Run tests
pytest

# Run with development settings
python -m claude_log_viewer.app --max-entries 1000
```

### Areas for Contribution

- Cross-platform testing (Windows, Linux)
- Git rollback feature implementation ([Milestones #1-6](https://github.com/InDate/claude-log-viewer/issues))
- UI/UX improvements
- Performance optimization
- Documentation improvements

## 📝 License

MIT License - see [LICENSE](LICENSE) file for details.

## 🔗 Links

- **Repository**: https://github.com/InDate/claude-log-viewer
- **Issues**: https://github.com/InDate/claude-log-viewer/issues
- **PyPI**: https://pypi.org/project/claude-log-viewer/
- **Release**: https://github.com/InDate/claude-log-viewer/releases/tag/v1.0.0

## 📚 Documentation

- [Installation Guide](INSTALL.md)
- [Usage Tracking Architecture](docs/usage-tracking-architecture.md)
- [Rollback Proposal](docs/rollback-proposal/README.md) (planned feature)

---

**Note**: This tool is for viewing Claude Code session transcripts. It requires Claude Code to be installed and have created session files in `~/.claude/projects/`.
