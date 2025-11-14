#!/usr/bin/env python3
"""
Git Rollback Manager - Handles git operations for session checkpoints and rollbacks

This module provides git-based rollback functionality for Claude Code sessions,
including automatic commits, checkpoint creation, and fork detection integration.
"""

import os
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any
import json
import threading
import re


# Global lock dictionary for repository-level locking
# Maps repo_path -> threading.Lock
_repo_locks = {}
_repo_locks_mutex = threading.Lock()


def _get_repo_lock(repo_path: Path) -> threading.Lock:
    """
    Get or create a lock for a specific repository.

    This ensures that git operations on the same repository are serialized,
    preventing race conditions when multiple sessions/threads access the same repo.

    Args:
        repo_path: Path to git repository root

    Returns:
        Threading lock for this repository
    """
    repo_path_str = str(repo_path)

    with _repo_locks_mutex:
        if repo_path_str not in _repo_locks:
            _repo_locks[repo_path_str] = threading.Lock()
        return _repo_locks[repo_path_str]


def validate_commit_hash(commit_hash: str) -> bool:
    """
    Validate that a commit hash matches the expected pattern.

    Git commit hashes are 40-character hexadecimal strings (SHA-1).

    Args:
        commit_hash: Commit hash to validate

    Returns:
        True if valid, False otherwise
    """
    if not commit_hash or not isinstance(commit_hash, str):
        return False

    # Full SHA-1 hash: 40 hex characters
    if re.match(r'^[a-f0-9]{40}$', commit_hash):
        return True

    # Short hash (7+ chars) - also acceptable
    if re.match(r'^[a-f0-9]{7,40}$', commit_hash):
        return True

    return False


class GitRollbackManager:
    """
    Manages git operations for Claude Code session rollback.

    Supports project-scoped operations when project_dir is specified,
    ensuring git operations are isolated to a specific project directory.
    """

    def __init__(self, project_dir: Optional[Path] = None, db_connection=None):
        """
        Initialize GitRollbackManager.

        Args:
            project_dir: Optional path to project directory. If specified,
                        all git operations are restricted to this directory.
            db_connection: Database connection for storing checkpoint metadata
        """
        self.project_dir = Path(project_dir) if project_dir else None
        self.db = db_connection
        self.repo_path = self._detect_repo()
        self.is_git_repo = self.repo_path is not None

    def _detect_repo(self) -> Optional[Path]:
        """
        Detect git repository starting from project_dir or current directory.

        Returns:
            Path to .git directory, or None if not in a git repo
        """
        search_path = self.project_dir if self.project_dir else Path.cwd()

        # Handle case where search_path doesn't exist
        if not search_path.exists():
            return None

        try:
            # Use git rev-parse to find repo root
            result = subprocess.run(
                ['git', 'rev-parse', '--show-toplevel'],
                cwd=str(search_path),
                capture_output=True,
                text=True,
                check=False
            )

            if result.returncode == 0:
                repo_root = Path(result.stdout.strip())

                # If project_dir specified, validate that repo_root is within it
                if self.project_dir:
                    try:
                        # Check if repo_root is the same as or parent of project_dir
                        self.project_dir.resolve().relative_to(repo_root.resolve())
                        return repo_root
                    except ValueError:
                        # project_dir is not within this repo
                        print(f"Warning: Git repo found at {repo_root}, but project_dir {self.project_dir} is outside it")
                        return None

                return repo_root

            return None

        except (subprocess.SubprocessError, FileNotFoundError):
            return None

    def get_repo_status(self) -> Dict[str, Any]:
        """
        Get current git repository status.

        Returns:
            Dict with repo info: {
                'is_git_repo': bool,
                'repo_path': str | None,
                'current_branch': str | None,
                'current_commit': str | None,
                'has_uncommitted_changes': bool,
                'project_dir': str | None
            }
        """
        status = {
            'is_git_repo': self.is_git_repo,
            'repo_path': str(self.repo_path) if self.repo_path else None,
            'current_branch': None,
            'current_commit': None,
            'has_uncommitted_changes': False,
            'project_dir': str(self.project_dir) if self.project_dir else None
        }

        if not self.is_git_repo:
            return status

        try:
            # Get current branch
            result = subprocess.run(
                ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
                check=True
            )
            status['current_branch'] = result.stdout.strip()

            # Get current commit hash
            result = subprocess.run(
                ['git', 'rev-parse', 'HEAD'],
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
                check=True
            )
            status['current_commit'] = result.stdout.strip()

            # Check for uncommitted changes
            result = subprocess.run(
                ['git', 'status', '--porcelain'],
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
                check=True
            )
            status['has_uncommitted_changes'] = bool(result.stdout.strip())

        except subprocess.CalledProcessError as e:
            print(f"Error getting git status: {e}")

        return status

    def create_checkpoint(
        self,
        session_uuid: str,
        checkpoint_type: str = 'manual',
        message_uuid: Optional[str] = None,
        parent_uuid: Optional[str] = None,
        description: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a checkpoint at the current git HEAD.

        Args:
            session_uuid: Session identifier
            checkpoint_type: Type of checkpoint ('session_start', 'manual', 'fork_point')
            message_uuid: Optional message UUID this checkpoint is associated with
            parent_uuid: Optional parent message UUID (for fork checkpoints)
            description: Optional description for the checkpoint

        Returns:
            Dict with checkpoint info: {
                'success': bool,
                'checkpoint_id': int | None,
                'commit_hash': str | None,
                'error': str | None
            }
        """
        if not self.is_git_repo:
            return {
                'success': False,
                'checkpoint_id': None,
                'commit_hash': None,
                'error': 'Not in a git repository'
            }

        if not self.db:
            return {
                'success': False,
                'checkpoint_id': None,
                'commit_hash': None,
                'error': 'Database connection not available'
            }

        # Acquire repository lock to prevent race conditions
        repo_lock = _get_repo_lock(self.repo_path)

        with repo_lock:
            try:
                # Get current commit hash
                result = subprocess.run(
                    ['git', 'rev-parse', 'HEAD'],
                    cwd=str(self.repo_path),
                    capture_output=True,
                    text=True,
                    check=True
                )
                commit_hash = result.stdout.strip()

                # Validate commit hash
                if not validate_commit_hash(commit_hash):
                    return {
                        'success': False,
                        'checkpoint_id': None,
                        'commit_hash': None,
                        'error': f'Invalid commit hash format: {commit_hash}'
                    }

                # Insert checkpoint into database
                timestamp = datetime.now().isoformat()

                cursor = self.db.cursor()
                cursor.execute('''
                    INSERT INTO git_checkpoints (
                        session_uuid, checkpoint_type, commit_hash,
                        message_uuid, parent_uuid, timestamp, status,
                        description
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    session_uuid, checkpoint_type, commit_hash,
                    message_uuid, parent_uuid, timestamp, 'active',
                    description
                ))
                self.db.commit()

                checkpoint_id = cursor.lastrowid

                print(f"✓ Created {checkpoint_type} checkpoint: {commit_hash[:8]} (id: {checkpoint_id})")

                return {
                    'success': True,
                    'checkpoint_id': checkpoint_id,
                    'commit_hash': commit_hash,
                    'error': None
                }

            except Exception as e:
                return {
                    'success': False,
                    'checkpoint_id': None,
                    'commit_hash': None,
                    'error': str(e)
                }

    def list_commits(
        self,
        session_uuid: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        List git commits, optionally filtered by session.

        Args:
            session_uuid: Optional session filter
            limit: Maximum number of commits to return

        Returns:
            List of commit dicts with metadata
        """
        if not self.db:
            return []

        try:
            cursor = self.db.cursor()

            if session_uuid:
                cursor.execute('''
                    SELECT
                        id, session_uuid, agent_id, commit_hash,
                        tool_name, tool_use_id, description, timestamp
                    FROM git_commits
                    WHERE session_uuid = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                ''', (session_uuid, limit))
            else:
                cursor.execute('''
                    SELECT
                        id, session_uuid, agent_id, commit_hash,
                        tool_name, tool_use_id, description, timestamp
                    FROM git_commits
                    ORDER BY timestamp DESC
                    LIMIT ?
                ''', (limit,))

            commits = []
            for row in cursor.fetchall():
                commits.append({
                    'id': row[0],
                    'session_uuid': row[1],
                    'agent_id': row[2],
                    'commit_hash': row[3],
                    'tool_name': row[4],
                    'tool_use_id': row[5],
                    'description': row[6],
                    'timestamp': row[7]
                })

            return commits

        except Exception as e:
            print(f"Error listing commits: {e}")
            return []

    def list_checkpoints(
        self,
        session_uuid: Optional[str] = None,
        message_uuid: Optional[str] = None,
        checkpoint_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List checkpoints with optional filtering.

        Args:
            session_uuid: Filter by session
            message_uuid: Filter by message
            checkpoint_type: Filter by type

        Returns:
            List of checkpoint dicts
        """
        if not self.db:
            return []

        try:
            cursor = self.db.cursor()

            # Build query dynamically based on filters
            query = '''
                SELECT
                    id, session_uuid, checkpoint_type, commit_hash,
                    message_uuid, parent_uuid, timestamp, status,
                    description
                FROM git_checkpoints
                WHERE 1=1
            '''
            params = []

            if session_uuid:
                query += ' AND session_uuid = ?'
                params.append(session_uuid)

            if message_uuid:
                query += ' AND message_uuid = ?'
                params.append(message_uuid)

            if checkpoint_type:
                query += ' AND checkpoint_type = ?'
                params.append(checkpoint_type)

            query += ' ORDER BY timestamp DESC'

            cursor.execute(query, params)

            checkpoints = []
            for row in cursor.fetchall():
                checkpoints.append({
                    'id': row[0],
                    'session_uuid': row[1],
                    'checkpoint_type': row[2],
                    'commit_hash': row[3],
                    'message_uuid': row[4],
                    'parent_uuid': row[5],
                    'timestamp': row[6],
                    'status': row[7],
                    'description': row[8]
                })

            return checkpoints

        except Exception as e:
            print(f"Error listing checkpoints: {e}")
            return []

    def should_commit(self) -> bool:
        """
        Check if there are changes to commit.

        Returns:
            True if there are uncommitted changes
        """
        if not self.is_git_repo:
            return False

        try:
            result = subprocess.run(
                ['git', 'status', '--porcelain'],
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
                check=True
            )
            return bool(result.stdout.strip())

        except subprocess.CalledProcessError:
            return False

    def auto_commit(
        self,
        session_uuid: str,
        tool_name: str,
        description: str,
        tool_use_id: Optional[str] = None,
        agent_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Automatically commit changes from a tool use.

        Args:
            session_uuid: Session identifier
            tool_name: Name of tool (Edit, Write, Bash)
            description: Commit message description
            tool_use_id: Tool use identifier
            agent_id: Agent identifier if from sub-agent

        Returns:
            Dict with commit info: {
                'success': bool,
                'commit_hash': str | None,
                'error': str | None
            }
        """
        if not self.is_git_repo:
            return {
                'success': False,
                'commit_hash': None,
                'error': 'Not in a git repository'
            }

        if not self.should_commit():
            return {
                'success': False,
                'commit_hash': None,
                'error': 'No changes to commit'
            }

        # Acquire repository lock to prevent race conditions
        repo_lock = _get_repo_lock(self.repo_path)

        with repo_lock:
            try:
                # Stage all changes
                subprocess.run(
                    ['git', 'add', '-A'],
                    cwd=str(self.repo_path),
                    check=True,
                    capture_output=True
                )

                # Create commit message
                commit_msg = f"[Claude Auto-Commit] {tool_name}: {description[:100]}"
                if agent_id:
                    commit_msg += f"\n\nAgent: {agent_id}"
                commit_msg += f"\nTool: {tool_name}"
                if tool_use_id:
                    commit_msg += f"\nTool Use ID: {tool_use_id}"
                commit_msg += f"\nSession: {session_uuid}"

                # Commit
                subprocess.run(
                    ['git', 'commit', '-m', commit_msg],
                    cwd=str(self.repo_path),
                    check=True,
                    capture_output=True
                )

                # Get commit hash
                result = subprocess.run(
                    ['git', 'rev-parse', 'HEAD'],
                    cwd=str(self.repo_path),
                    capture_output=True,
                    text=True,
                    check=True
                )
                commit_hash = result.stdout.strip()

                # Validate commit hash
                if not validate_commit_hash(commit_hash):
                    return {
                        'success': False,
                        'commit_hash': None,
                        'error': f'Invalid commit hash format: {commit_hash}'
                    }

                # Store in database if connection available
                if self.db:
                    timestamp = datetime.now().isoformat()
                    cursor = self.db.cursor()
                    cursor.execute('''
                        INSERT INTO git_commits (
                            session_uuid, agent_id, commit_hash,
                            tool_name, tool_use_id, description, timestamp
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        session_uuid, agent_id, commit_hash,
                        tool_name, tool_use_id, description, timestamp
                    ))
                    self.db.commit()

                print(f"✓ Auto-committed: {commit_hash[:8]} ({tool_name})")

                return {
                    'success': True,
                    'commit_hash': commit_hash,
                    'error': None
                }

            except subprocess.CalledProcessError as e:
                return {
                    'success': False,
                    'commit_hash': None,
                    'error': f'Git command failed: {e}'
                }
            except Exception as e:
                return {
                    'success': False,
                    'commit_hash': None,
                    'error': str(e)
                }
