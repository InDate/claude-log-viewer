#!/usr/bin/env python3
"""
Git Repository Discovery - Smart detection from JSONL file paths

Analyzes Claude Code session logs to discover which git repositories
are being worked on, handling nested repos correctly.
"""

import re
from pathlib import Path
from typing import List, Dict, Optional, Set
from collections import defaultdict


def discover_git_repo(file_path: str) -> Optional[str]:
    """
    Walk up directory tree from file_path to find .git directory.

    Handles nested git repositories correctly by stopping at the first .git found.

    Args:
        file_path: Absolute path to a file

    Returns:
        Absolute path to git repository root, or None if not in a git repo

    Example:
        /path/to/project/src/file.py -> /path/to/project (if .git exists there)
        /path/to/project/nested/.git/config -> /path/to/project/nested
    """
    if not file_path:
        return None

    try:
        current = Path(file_path).resolve().parent

        # Walk up until we find .git or hit root
        while current != current.parent:
            git_dir = current / '.git'
            if git_dir.exists() and git_dir.is_dir():
                return str(current)
            current = current.parent

        return None

    except (ValueError, OSError):
        # Invalid path or permission error
        return None


def extract_file_paths_from_entry(entry: Dict) -> List[str]:
    """
    Extract file paths from a single JSONL entry.

    Looks for:
    - Edit/Write/Read tool file_path parameters
    - Bash commands with cd or file paths
    - NotebookEdit notebook_path parameters

    Args:
        entry: Parsed JSONL entry dict

    Returns:
        List of absolute file paths found in this entry
    """
    paths = []

    # Get message content
    message = entry.get('message', {})
    if not isinstance(message, dict):
        return paths

    content = message.get('content', [])
    if not isinstance(content, list):
        return paths

    # Scan all content blocks
    for block in content:
        if not isinstance(block, dict):
            continue

        block_type = block.get('type')

        # Tool use blocks
        if block_type == 'tool_use':
            tool_name = block.get('name', '')
            tool_input = block.get('input', {})

            # File editing tools
            if tool_name in ['Edit', 'Write', 'Read']:
                if 'file_path' in tool_input:
                    path = tool_input['file_path']
                    if path and isinstance(path, str):
                        paths.append(path)

            # Notebook editing
            elif tool_name == 'NotebookEdit':
                if 'notebook_path' in tool_input:
                    path = tool_input['notebook_path']
                    if path and isinstance(path, str):
                        paths.append(path)

            # Bash commands
            elif tool_name == 'Bash':
                if 'command' in tool_input:
                    command = tool_input['command']
                    if command and isinstance(command, str):
                        paths.extend(parse_bash_for_paths(command))

    return paths


def parse_bash_for_paths(command: str) -> List[str]:
    """
    Extract file paths from bash commands.

    Looks for:
    - cd commands
    - Absolute paths (starting with /)
    - Common file operations (git, cat, ls, etc.)

    Args:
        command: Bash command string

    Returns:
        List of paths found in command
    """
    paths = []

    # Extract cd commands
    cd_pattern = r'cd\s+([^\s&|;]+)'
    for match in re.finditer(cd_pattern, command):
        path = match.group(1).strip('"\'')
        if path:
            paths.append(path)

    # Extract absolute paths (conservative - must start with /)
    # Avoid matching things like timestamps or flags
    abs_path_pattern = r'(?:^|\s)(/[a-zA-Z0-9/_.-]+)'
    for match in re.finditer(abs_path_pattern, command):
        path = match.group(1)
        # Filter out common non-path patterns
        if not any(path.startswith(x) for x in ['/dev/', '/proc/', '/sys/']):
            # Only include if it looks like a real path (has multiple segments or file extension)
            if '/' in path[1:] or '.' in Path(path).name:
                paths.append(path)

    return paths


def discover_repos_for_entries(entries: List[Dict]) -> Dict[str, int]:
    """
    Discover all git repositories referenced in a list of entries.

    Args:
        entries: List of parsed JSONL entries

    Returns:
        Dict mapping repo paths to file counts:
        {
            '/path/to/repo1': 45,  # 45 files touched in this repo
            '/path/to/repo2': 3
        }
    """
    repo_file_counts = defaultdict(int)

    for entry in entries:
        file_paths = extract_file_paths_from_entry(entry)

        for file_path in file_paths:
            repo = discover_git_repo(file_path)
            if repo:
                repo_file_counts[repo] += 1

    return dict(repo_file_counts)


def get_primary_repo(repo_file_counts: Dict[str, int]) -> Optional[str]:
    """
    Determine the primary git repository from file counts.

    The primary repo is the one with the most file operations.

    Args:
        repo_file_counts: Dict of {repo_path: file_count}

    Returns:
        Path to primary repo, or None if no repos found
    """
    if not repo_file_counts:
        return None

    return max(repo_file_counts, key=repo_file_counts.get)


def discover_repos_for_project(entries: List[Dict], project_name: str) -> Dict:
    """
    Discover git repositories for a specific project.

    Filters entries to only include those for the given project,
    then discovers all git repos involved.

    Args:
        entries: All JSONL entries
        project_name: Project name to filter by (matches sessionId or file paths)

    Returns:
        Dict with discovery results:
        {
            'repos': ['/path/to/repo1', '/path/to/repo2'],
            'file_counts': {'/path/to/repo1': 45, '/path/to/repo2': 3},
            'primary_repo': '/path/to/repo1',
            'total_files': 48
        }
    """
    # Filter entries by project (sessionId contains project name or file paths)
    project_entries = []
    for entry in entries:
        session_id = entry.get('sessionId', '')
        # Simple heuristic: sessionId or _file contains project name
        if project_name.lower() in session_id.lower():
            project_entries.append(entry)
            continue

        # Also check if file paths contain project name
        file_paths = extract_file_paths_from_entry(entry)
        if any(project_name.lower() in path.lower() for path in file_paths):
            project_entries.append(entry)

    # Discover repos
    repo_file_counts = discover_repos_for_entries(project_entries)
    primary_repo = get_primary_repo(repo_file_counts)

    return {
        'repos': list(repo_file_counts.keys()),
        'file_counts': repo_file_counts,
        'primary_repo': primary_repo,
        'total_files': sum(repo_file_counts.values()),
        'entries_scanned': len(project_entries)
    }


def extract_project_names_from_entries(entries: List[Dict]) -> List[str]:
    """
    Extract unique project names from JSONL entries.

    Analyzes sessionId and file paths to identify distinct projects.

    Args:
        entries: List of parsed JSONL entries

    Returns:
        List of unique project names (sorted)

    Example:
        Input: entries with sessionIds containing project paths
        Output: ['-Volumes-Application-Data-Code-project1',
                 '-Volumes-Application-Data-Code-project2']
    """
    project_names = set()

    for entry in entries:
        # Try to extract project from sessionId
        session_id = entry.get('sessionId', '')
        if session_id:
            # SessionId often contains the project name
            # Example: "f780e6fc-7ab3-4268-b3c5-7925c87dde77"
            # Or the _file field might contain project path
            project_names.add(session_id)

        # Try to extract from _file field (directory name)
        file_path = entry.get('_file', '')
        if file_path:
            # Extract project directory name from path
            # Example: "/path/to/.claude/projects/project-name/file.jsonl"
            path_obj = Path(file_path)
            # Get parent directory name (should be project name)
            if path_obj.parent.name:
                project_names.add(path_obj.parent.name)

    return sorted(list(project_names))


def validate_repo_path(repo_path: str) -> bool:
    """
    Validate that a path is actually a git repository.

    Args:
        repo_path: Path to check

    Returns:
        True if path exists and contains .git directory
    """
    try:
        repo = Path(repo_path)
        return repo.exists() and (repo / '.git').exists()
    except (ValueError, OSError):
        return False
