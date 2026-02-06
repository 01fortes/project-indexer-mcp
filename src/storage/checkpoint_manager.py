"""Unified checkpoint manager for all three index types."""

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from ..utils.logger import get_logger

logger = get_logger(__name__)


class CheckpointManager:
    """
    Unified checkpoint manager for tracking indexing progress across all three indices.

    Tables:
    - project_analysis: Stores iterative project analysis results (Index 1)
    - analysis_iterations: Stores snapshots of each analysis iteration (Index 1)
    - file_index_checkpoints: Tracks file indexing progress (Index 2)
    - function_index_checkpoints: Tracks function indexing progress (Index 3)
    """

    def __init__(self, checkpoint_dir: Path):
        """
        Initialize checkpoint manager.

        Args:
            checkpoint_dir: Directory to store checkpoint database
        """
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = self.checkpoint_dir / "unified_checkpoints.db"
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

        self._init_schema()

    def _init_schema(self):
        """Create database schema for all three indices."""
        cursor = self.conn.cursor()

        # =================================================================
        # Index 1: Project Analysis Tables
        # =================================================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS project_analysis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_path TEXT NOT NULL UNIQUE,
                project_description TEXT,
                project_description_confidence INTEGER DEFAULT 0,
                languages TEXT,
                languages_confidence INTEGER DEFAULT 0,
                frameworks TEXT,
                frameworks_confidence INTEGER DEFAULT 0,
                modules TEXT,
                modules_confidence INTEGER DEFAULT 0,
                entry_points TEXT,
                entry_points_confidence INTEGER DEFAULT 0,
                architecture TEXT,
                architecture_confidence INTEGER DEFAULT 0,
                iteration_count INTEGER DEFAULT 0,
                files_analyzed TEXT,
                completed BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analysis_iterations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_path TEXT NOT NULL,
                iteration INTEGER NOT NULL,
                files_requested TEXT,
                files_read TEXT,
                snapshot TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(project_path, iteration)
            )
        """)

        # =================================================================
        # Index 2: File Index Checkpoints
        # =================================================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS file_index_checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_path TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                chunks_count INTEGER DEFAULT 0,
                status TEXT NOT NULL,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(project_path, file_path)
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_file_checkpoint_project
            ON file_index_checkpoints(project_path)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_file_checkpoint_status
            ON file_index_checkpoints(project_path, status)
        """)

        # =================================================================
        # Index 3: Function Index Checkpoints
        # =================================================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS function_index_checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_path TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                functions_count INTEGER DEFAULT 0,
                status TEXT NOT NULL,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(project_path, file_path)
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_function_checkpoint_project
            ON function_index_checkpoints(project_path)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_function_checkpoint_status
            ON function_index_checkpoints(project_path, status)
        """)

        self.conn.commit()
        logger.info(f"Checkpoint database initialized at {self.db_path}")

    # =========================================================================
    # Index 1: Project Analysis Methods
    # =========================================================================

    def save_project_analysis(
        self,
        project_path: str,
        project_description: Optional[str],
        project_description_confidence: int,
        languages: List[str],
        languages_confidence: int,
        frameworks: List[str],
        frameworks_confidence: int,
        modules: List[str],
        modules_confidence: int,
        entry_points: List[str],
        entry_points_confidence: int,
        architecture: Optional[str],
        architecture_confidence: int,
        iteration_count: int,
        files_analyzed: List[str],
        completed: bool
    ):
        """Save or update project analysis result."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO project_analysis (
                project_path, project_description, project_description_confidence,
                languages, languages_confidence, frameworks, frameworks_confidence,
                modules, modules_confidence, entry_points, entry_points_confidence,
                architecture, architecture_confidence, iteration_count,
                files_analyzed, completed, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(project_path) DO UPDATE SET
                project_description = excluded.project_description,
                project_description_confidence = excluded.project_description_confidence,
                languages = excluded.languages,
                languages_confidence = excluded.languages_confidence,
                frameworks = excluded.frameworks,
                frameworks_confidence = excluded.frameworks_confidence,
                modules = excluded.modules,
                modules_confidence = excluded.modules_confidence,
                entry_points = excluded.entry_points,
                entry_points_confidence = excluded.entry_points_confidence,
                architecture = excluded.architecture,
                architecture_confidence = excluded.architecture_confidence,
                iteration_count = excluded.iteration_count,
                files_analyzed = excluded.files_analyzed,
                completed = excluded.completed,
                updated_at = CURRENT_TIMESTAMP
        """, (
            project_path, project_description, project_description_confidence,
            json.dumps(languages), languages_confidence,
            json.dumps(frameworks), frameworks_confidence,
            json.dumps(modules), modules_confidence,
            json.dumps(entry_points), entry_points_confidence,
            architecture, architecture_confidence, iteration_count,
            json.dumps(files_analyzed), completed
        ))
        self.conn.commit()

    def get_project_analysis(self, project_path: str) -> Optional[Dict[str, Any]]:
        """Get project analysis result."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM project_analysis WHERE project_path = ?
        """, (project_path,))
        row = cursor.fetchone()

        if not row:
            return None

        return {
            "project_path": row["project_path"],
            "project_description": row["project_description"],
            "project_description_confidence": row["project_description_confidence"],
            "languages": json.loads(row["languages"]) if row["languages"] else [],
            "languages_confidence": row["languages_confidence"],
            "frameworks": json.loads(row["frameworks"]) if row["frameworks"] else [],
            "frameworks_confidence": row["frameworks_confidence"],
            "modules": json.loads(row["modules"]) if row["modules"] else [],
            "modules_confidence": row["modules_confidence"],
            "entry_points": json.loads(row["entry_points"]) if row["entry_points"] else [],
            "entry_points_confidence": row["entry_points_confidence"],
            "architecture": row["architecture"],
            "architecture_confidence": row["architecture_confidence"],
            "iteration_count": row["iteration_count"],
            "files_analyzed": json.loads(row["files_analyzed"]) if row["files_analyzed"] else [],
            "completed": bool(row["completed"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"]
        }

    def save_analysis_iteration(
        self,
        project_path: str,
        iteration: int,
        files_requested: List[str],
        files_read: List[str],
        snapshot: Dict[str, Any]
    ):
        """Save analysis iteration snapshot."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO analysis_iterations (
                project_path, iteration, files_requested, files_read, snapshot
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(project_path, iteration) DO UPDATE SET
                files_requested = excluded.files_requested,
                files_read = excluded.files_read,
                snapshot = excluded.snapshot
        """, (
            project_path, iteration,
            json.dumps(files_requested),
            json.dumps(files_read),
            json.dumps(snapshot)
        ))
        self.conn.commit()

    def get_last_iteration(self, project_path: str) -> Optional[Dict[str, Any]]:
        """Get the last analysis iteration for a project."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM analysis_iterations
            WHERE project_path = ?
            ORDER BY iteration DESC LIMIT 1
        """, (project_path,))
        row = cursor.fetchone()

        if not row:
            return None

        return {
            "iteration": row["iteration"],
            "files_requested": json.loads(row["files_requested"]) if row["files_requested"] else [],
            "files_read": json.loads(row["files_read"]) if row["files_read"] else [],
            "snapshot": json.loads(row["snapshot"]) if row["snapshot"] else {}
        }

    def clear_project_analysis(self, project_path: str):
        """Clear all analysis data for a project."""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM project_analysis WHERE project_path = ?", (project_path,))
        cursor.execute("DELETE FROM analysis_iterations WHERE project_path = ?", (project_path,))
        self.conn.commit()
        logger.info(f"Cleared project analysis for {project_path}")

    # =========================================================================
    # Index 2: File Index Checkpoint Methods
    # =========================================================================

    def get_file_completed_files(self, project_path: str) -> Set[str]:
        """Get set of successfully indexed file paths for file index."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT file_path FROM file_index_checkpoints
            WHERE project_path = ? AND status = 'completed'
        """, (project_path,))
        return {row['file_path'] for row in cursor.fetchall()}

    def mark_file_indexed(
        self,
        project_path: str,
        file_path: str,
        file_hash: str,
        chunks_count: int = 0,
        error: Optional[str] = None
    ):
        """Mark file as indexed or failed in file index."""
        status = 'failed' if error else 'completed'
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO file_index_checkpoints
                (project_path, file_path, file_hash, chunks_count, status, error_message)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (project_path, file_path, file_hash, chunks_count, status, error))
        self.conn.commit()

    def should_reindex_file(
        self,
        project_path: str,
        file_path: str,
        current_hash: str
    ) -> bool:
        """Check if file should be reindexed in file index."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT status, file_hash FROM file_index_checkpoints
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

    def clear_file_index(self, project_path: str):
        """Clear all file index checkpoints for a project."""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM file_index_checkpoints WHERE project_path = ?", (project_path,))
        self.conn.commit()
        logger.info(f"Cleared file index checkpoints for {project_path}")

    def get_file_index_stats(self, project_path: str) -> Dict[str, int]:
        """Get file index statistics."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(chunks_count) as total_chunks
            FROM file_index_checkpoints
            WHERE project_path = ?
        """, (project_path,))
        row = cursor.fetchone()
        return {
            'total': row['total'] or 0,
            'completed': row['completed'] or 0,
            'failed': row['failed'] or 0,
            'total_chunks': row['total_chunks'] or 0
        }

    # =========================================================================
    # Index 3: Function Index Checkpoint Methods
    # =========================================================================

    def get_function_completed_files(self, project_path: str) -> Set[str]:
        """Get set of files with extracted functions."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT file_path FROM function_index_checkpoints
            WHERE project_path = ? AND status = 'completed'
        """, (project_path,))
        return {row['file_path'] for row in cursor.fetchall()}

    def mark_functions_indexed(
        self,
        project_path: str,
        file_path: str,
        file_hash: str,
        functions_count: int = 0,
        error: Optional[str] = None
    ):
        """Mark file as processed for function extraction."""
        status = 'failed' if error else 'completed'
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO function_index_checkpoints
                (project_path, file_path, file_hash, functions_count, status, error_message)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (project_path, file_path, file_hash, functions_count, status, error))
        self.conn.commit()

    def should_reindex_functions(
        self,
        project_path: str,
        file_path: str,
        current_hash: str
    ) -> bool:
        """Check if functions should be re-extracted from file."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT status, file_hash FROM function_index_checkpoints
            WHERE project_path = ? AND file_path = ?
        """, (project_path, file_path))
        row = cursor.fetchone()

        if not row:
            return True
        if row['status'] == 'failed':
            return True
        if row['file_hash'] != current_hash:
            return True
        return False

    def clear_function_index(self, project_path: str):
        """Clear all function index checkpoints for a project."""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM function_index_checkpoints WHERE project_path = ?", (project_path,))
        self.conn.commit()
        logger.info(f"Cleared function index checkpoints for {project_path}")

    def get_function_index_stats(self, project_path: str) -> Dict[str, int]:
        """Get function index statistics."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(functions_count) as total_functions
            FROM function_index_checkpoints
            WHERE project_path = ?
        """, (project_path,))
        row = cursor.fetchone()
        return {
            'total': row['total'] or 0,
            'completed': row['completed'] or 0,
            'failed': row['failed'] or 0,
            'total_functions': row['total_functions'] or 0
        }

    # =========================================================================
    # Combined Index Status
    # =========================================================================

    def get_all_index_stats(self, project_path: str) -> Dict[str, Any]:
        """Get combined statistics for all three indices."""
        analysis = self.get_project_analysis(project_path)

        return {
            "analysis": {
                "status": "completed" if (analysis and analysis.get("completed")) else "pending",
                "iteration_count": analysis.get("iteration_count", 0) if analysis else 0,
                "min_confidence": min(
                    analysis.get("project_description_confidence", 0),
                    analysis.get("languages_confidence", 0),
                    analysis.get("frameworks_confidence", 0),
                    analysis.get("modules_confidence", 0),
                    analysis.get("entry_points_confidence", 0),
                    analysis.get("architecture_confidence", 0)
                ) if analysis else 0,
                "files_analyzed": len(analysis.get("files_analyzed", [])) if analysis else 0
            },
            "files": self.get_file_index_stats(project_path),
            "functions": self.get_function_index_stats(project_path)
        }

    def clear_all_project_data(self, project_path: str):
        """Clear all data for a project across all indices."""
        self.clear_project_analysis(project_path)
        self.clear_file_index(project_path)
        self.clear_function_index(project_path)
        logger.info(f"Cleared all index data for {project_path}")

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
