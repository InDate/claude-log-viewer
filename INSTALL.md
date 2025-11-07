# Installation Guide for Claude Log Viewer

## Prerequisites

- Python 3.8 or higher
- `pipx` (recommended) or `pip`

## Installing pipx (if not already installed)

```bash
brew install pipx
pipx ensurepath
```

## Installation Methods

### Method 1: Using pipx (Recommended)

pipx installs the application in its own isolated virtual environment and makes it globally available:

```bash
cd /path/to/logviewer
pipx install .
```

For development (editable install):
```bash
pipx install -e .
```

### Method 2: Using pip with virtual environment

```bash
# Create a virtual environment
python3 -m venv ~/.venvs/claude-log-viewer
source ~/.venvs/claude-log-viewer/bin/activate

# Install the package
pip install /path/to/logviewer

# To make it globally accessible, create a symlink
ln -s ~/.venvs/claude-log-viewer/bin/claude-log-viewer /usr/local/bin/claude-log-viewer
```

### Method 3: Direct pip install (system-wide)

```bash
pip3 install --user /path/to/logviewer
```

## Running the Application

Once installed, you can run the log viewer from anywhere:

```bash
claude-log-viewer
```

The web interface will be available at: http://localhost:5001

## Updating

### With pipx:
```bash
pipx upgrade claude-log-viewer
```

Or if installed from local directory:
```bash
cd /path/to/logviewer
pipx reinstall .
```

### With pip:
```bash
pip install --upgrade /path/to/logviewer
```

## Uninstalling

### With pipx:
```bash
pipx uninstall claude-log-viewer
```

### With pip:
```bash
pip uninstall claude-log-viewer
```

## Publishing to PyPI (Optional)

If you want to publish this package to PyPI so anyone can install it with `pipx install claude-log-viewer`:

1. Install build tools:
   ```bash
   pip install build twine
   ```

2. Build the package:
   ```bash
   cd /path/to/logviewer
   python -m build
   ```

3. Upload to PyPI:
   ```bash
   twine upload dist/*
   ```

## Troubleshooting

### Command not found after installation

Make sure the pipx bin directory is in your PATH:
```bash
pipx ensurepath
```

Then restart your terminal or run:
```bash
source ~/.zshrc  # or ~/.bashrc
```

### Import errors

If you get import errors, make sure all dependencies are installed:
```bash
pip install -r requirements.txt
```

### Permission errors

If you get permission errors with pip, use `--user` flag:
```bash
pip install --user /path/to/logviewer
```
