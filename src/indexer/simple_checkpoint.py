"""Simple checkpoint manager for resumable indexing."""

import sqlite3
import json
from pathlib import Path
from typing import List, Optional, Set, Dict, Any
from ..utils.logger import get_logger

logger = get_logger(__name__)


class SimpleCheckpoint:
    """
    Simple checkpoint manager for tracking indexed files.

    Stores checkpoint data in SQLite database to track which files
    have been successfully indexed, allowing resume on failure.
    """

    def __init__(self, checkpoint_dir: Path):
        """
        Initialize checkpoint manager.

        Args:
            checkpoint_dir: Directory to store checkpoint database
        """
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = self.checkpoint_dir / "checkpoints.db"
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

        self._init_schema()

    def _init_schema(self):
        """Create database schema."""
        cursor = self.conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS file_checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_path TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(project_path, file_path)
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_checkpoint_project
            ON file_checkpoints(project_path)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_checkpoint_status
            ON file_checkpoints(project_path, status)
        """)

        self.conn.commit()

    def get_completed_files(self, project_path: str) -> Set[str]:
        """
        Get set of successfully indexed file paths.

        Args:
            project_path: Project root path

        Returns:
            Set of relative file paths that were successfully indexed
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT file_path FROM file_checkpoints
            WHERE project_path = ? AND status = 'completed'
        """, (project_path,))

        return {row['file_path'] for row in cursor.fetchall()}

    def mark_file_completed(
        self,
        project_path: str,
        file_path: str,
        file_hash: str,
        error: Optional[str] = None
    ):
        """
        Mark file as completed or failed.

        Args:
            project_path: Project root path
            file_path: Relative file path
            file_hash: File content hash
            error: Error message if failed
        """
        status = 'failed' if error else 'completed'

        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO file_checkpoints
                (project_path, file_path, file_hash, status, error_message)
            VALUES (?, ?, ?, ?, ?)
        """, (project_path, file_path, file_hash, status, error))

        self.conn.commit()

    def clear_project(self, project_path: str):
        """
        Clear all checkpoints for a project.

        Args:
            project_path: Project root path
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            DELETE FROM file_checkpoints WHERE project_path = ?
        """, (project_path,))
        self.conn.commit()

        logger.info(f"Cleared checkpoints for {project_path}")

    def get_statistics(self, project_path: str) -> Dict[str, Any]:
        """
        Get checkpoint statistics for a project.

        Args:
            project_path: Project root path

        Returns:
            Dictionary with completed, failed, and total counts
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
            FROM file_checkpoints
            WHERE project_path = ?
        """, (project_path,))

        row = cursor.fetchone()
        return {
            'total': row['total'] or 0,
            'completed': row['completed'] or 0,
            'failed': row['failed'] or 0
        }

    def should_reindex_file(
        self,
        project_path: str,
        file_path: str,
        current_hash: str
    ) -> bool:
        """
        Check if file should be reindexed.

        File should be reindexed if:
        - Never indexed before
        - Previously failed
        - Content has changed (hash mismatch)

        Args:
            project_path: Project root path
            file_path: Relative file path
            current_hash: Current file content hash

        Returns:
            True if file should be indexed/reindexed
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT status, file_hash FROM file_checkpoints
            WHERE project_path = ? AND file_path = ?
        """, (project_path, file_path))

        row = cursor.fetchone()

        if not row:
            return True  # Never indexed

        if row['status'] == 'failed':
            return True  # Retry failed files

        if row['file_hash'] != current_hash:
            return True  # Content changed

        return False  # Already indexed and unchanged

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
