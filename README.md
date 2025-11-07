# Claude Code Log Viewer

An interactive web-based viewer for Claude Code JSONL transcript files.

## Features

- 🔄 Real-time monitoring of JSONL files
- 🎛️ Interactive field selection - choose which fields to display
- 🔍 Search and filter entries
- 🎨 Syntax highlighting and color-coded entry types
- ⚡ Auto-refresh with 5-second intervals
- 📊 Entry statistics and counts
- 🌙 Dark theme optimized for readability
- 📈 Usage tracking and snapshot history

## Installation

### From PyPI (recommended)

```bash
pip install claude-log-viewer
```

### From source

```bash
git clone https://github.com/indate/claude-log-viewer.git
cd claude-log-viewer
pip install -e .
```

## Usage

Start the server:
```bash
claude-log-viewer
```

Or if running from source:
```bash
python -m claude_log_viewer.app
```

Then open your browser to:
```
http://localhost:5001
```

The viewer will automatically load JSONL files from your Claude projects directory.

## Controls

- **Search**: Filter entries by any text content
- **Type Filter**: Filter by entry type (user, assistant, tool_result, etc.)
- **Limit**: Control how many entries to display
- **Refresh**: Manually reload all entries
- **Auto-refresh**: Enable 5-second automatic updates
- **Field Checkboxes**: Select which fields to display for each entry

## Tips

- Click the field checkboxes at the top to show/hide specific fields
- Enable auto-refresh to see new entries as they come in
- Use the type filter to focus on specific message types
- Search works across all fields in the entries
- Hover over entries to highlight them

## Technical Details

- Built with Flask (backend) and vanilla JavaScript (frontend)
- Uses Watchdog for file system monitoring
- Displays up to 500 most recent entries
- Reads all `.jsonl` files in the Claude projects directory
