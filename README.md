# Claude Code Log Viewer

An interactive web-based viewer for Claude Code JSONL transcript files with real-time monitoring, usage tracking, and git integration.

## ✨ Features

### 📊 **Real-Time Session Monitoring**
- Live file watching with automatic updates
- Session-based organization with color-coded cards
- Message count and token usage per session
- Last active timestamp tracking
- Configurable auto-refresh (1s to 60s intervals)

### 🔍 **Advanced Filtering & Search**
- Full-text search across all message content
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

The viewer will automatically load JSONL files from:
- `~/.claude/projects/` - Claude Code session transcripts
- `~/.claude/todos/` - Todo lists

## 🎮 Controls

### Main Interface
- **Search**: Filter entries by any text content
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

## 🚧 Planned Features

See [docs/rollback-proposal/](docs/rollback-proposal/) for detailed design documentation of upcoming features:

- **Full Checkpoint Selector UI** - Navigate through conversation checkpoints with context
- **Fork Detection & Navigation** - Automatic detection and visualization of conversation branches
- **Session Branching** - Visual representation of conversation forks
- **Enhanced Session Management** - Delete, rename, and resume sessions from UI
- **Markdown Tool Results** - Rich rendering of tool outputs
- **Image Display** - Inline image viewing in sessions

## 🐛 Known Issues

- **Token Delta Calculation** - Reset time jitter from API causes unstable deltas ([Issue #9](https://github.com/InDate/claude-log-viewer/issues/9))
- **Cross-Platform Testing** - Only tested on macOS, needs Windows/Linux verification ([Issue #5](https://github.com/InDate/claude-log-viewer/issues/5))

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
