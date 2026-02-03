"""SQLite-based call graph storage for graph traversal and querying.

This provides graph-based storage complementing ChromaDB's semantic search.
SQLite is used for efficient graph traversal and relationship queries.
"""

import sqlite3
import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import asdict

from ..indexer.ast_analyzer import FunctionDefinition, FunctionCall
from ..utils.logger import get_logger

logger = get_logger(__name__)


class CallGraphStore:
    """
    SQLite storage for call graph with efficient graph traversal.

    This complements ChromaDB by providing:
    - Fast graph traversal (DFS/BFS)
    - Entry point detection
    - Layer-based filtering
    - Call stack reconstruction
    """

    def __init__(self, db_path: Path):
        """
        Initialize SQLite database.

        Args:
            db_path: Path to SQLite database file
        """
        # Ensure db_path is a Path object
        self.db_path = Path(db_path) if not isinstance(db_path, Path) else db_path
        # Convert to absolute path to avoid issues with relative paths
        self.db_path = self.db_path.resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Initializing CallGraphStore with database at: {self.db_path}")

        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        """Create database schema."""
        cursor = self.conn.cursor()

        # Functions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS functions (
                id TEXT PRIMARY KEY,
                project_path TEXT NOT NULL,
                file_path TEXT NOT NULL,
                function_name TEXT NOT NULL,
                line_number INTEGER,
                signature TEXT,
                layer TEXT,
                is_entry_point BOOLEAN DEFAULT FALSE,
                trigger_type TEXT,
                trigger_metadata TEXT,
                description TEXT,
                parameters TEXT,
                return_type TEXT,
                is_async BOOLEAN DEFAULT FALSE,
                is_method BOOLEAN DEFAULT FALSE,
                class_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Call relations table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS call_relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_path TEXT NOT NULL,
                caller_id TEXT NOT NULL,
                callee_id TEXT NOT NULL,
                caller_line INTEGER,
                arguments TEXT,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (caller_id) REFERENCES functions(id),
                FOREIGN KEY (callee_id) REFERENCES functions(id)
            )
        """)

        # Indexes for fast queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_functions_project ON functions(project_path)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_functions_file ON functions(file_path)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_functions_name ON functions(function_name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_functions_entry ON functions(is_entry_point) WHERE is_entry_point = 1")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_functions_layer ON functions(layer)")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_calls_project ON call_relations(project_path)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_calls_caller ON call_relations(caller_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_calls_callee ON call_relations(callee_id)")

        self.conn.commit()

    def save_function(
        self,
        project_path: str,
        file_path: str,
        func_def: FunctionDefinition,
        layer: Optional[str] = None,
        is_entry_point: bool = False,
        trigger_type: Optional[str] = None,
        trigger_metadata: Optional[Dict] = None,
        description: Optional[str] = None
    ) -> str:
        """
        Save a single function definition.

        Args:
            project_path: Root path of project
            file_path: Relative path to file
            func_def: Function definition
            layer: Layer classification (trigger/controller/service/provider/external)
            is_entry_point: Whether this is an entry point
            trigger_type: Type of trigger (http/grpc/kafka/scheduled/websocket)
            trigger_metadata: Additional trigger metadata
            description: LLM-generated description

        Returns:
            Function ID
        """
        func_id = f"{file_path}::{func_def.name}::{func_def.line_number}"

        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO functions (
                id, project_path, file_path, function_name, line_number,
                signature, layer, is_entry_point, trigger_type, trigger_metadata,
                description, parameters, return_type, is_async, is_method, class_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            func_id,
            project_path,
            file_path,
            func_def.name,
            func_def.line_number,
            self._format_signature(func_def),
            layer,
            is_entry_point,
            trigger_type,
            json.dumps(trigger_metadata) if trigger_metadata else None,
            description,
            json.dumps(func_def.parameters),
            func_def.return_type,
            func_def.is_async,
            func_def.is_method,
            func_def.class_name
        ))

        self.conn.commit()
        return func_id

    def save_functions(
        self,
        project_path: str,
        functions: List[Dict[str, Any]]
    ):
        """
        Batch save multiple functions.

        Args:
            project_path: Root path of project
            functions: List of function dicts with all fields
        """
        logger.info(f"save_functions called with {len(functions)} functions for project: {project_path}")
        cursor = self.conn.cursor()

        saved_count = 0
        skipped_count = 0

        for func_data in functions:
            func_def = func_data.get('func_def')
            if not func_def:
                skipped_count += 1
                logger.warning(f"Skipping function - no func_def in data: {list(func_data.keys())}")
                continue

            func_id = f"{func_data['file_path']}::{func_def.name}::{func_def.line_number}"

            try:
                cursor.execute("""
                    INSERT OR REPLACE INTO functions (
                        id, project_path, file_path, function_name, line_number,
                        signature, layer, is_entry_point, trigger_type, trigger_metadata,
                        description, parameters, return_type, is_async, is_method, class_name
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    func_id,
                    project_path,
                    func_data['file_path'],
                    func_def.name,
                    func_def.line_number,
                    self._format_signature(func_def),
                    func_data.get('layer'),
                    func_data.get('is_entry_point', False),
                    func_data.get('trigger_type'),
                    json.dumps(func_data['trigger_metadata']) if func_data.get('trigger_metadata') else None,
                    func_data.get('description'),
                    json.dumps(func_def.parameters),
                    func_def.return_type,
                    func_def.is_async,
                    func_def.is_method,
                    func_def.class_name
                ))
                saved_count += 1
            except Exception as e:
                logger.error(f"Failed to save function {func_id}: {e}", exc_info=True)
                skipped_count += 1

        logger.info(f"Committing {saved_count} functions (skipped {skipped_count})")
        self.conn.commit()

        # Force flush to disk
        self.conn.execute("PRAGMA wal_checkpoint(FULL)")

        # Verify the save
        cursor.execute("SELECT COUNT(*) FROM functions WHERE project_path = ?", (project_path,))
        count_after = cursor.fetchone()[0]
        logger.info(f"After commit: {count_after} functions in database for this project")
        logger.info(f"Database file: {self.db_path}")

    def save_call(
        self,
        project_path: str,
        caller_id: str,
        callee_id: str,
        caller_line: int,
        arguments: Optional[List[str]] = None,
        description: Optional[str] = None
    ):
        """
        Save a single call relation.

        Args:
            project_path: Root path of project
            caller_id: ID of calling function
            callee_id: ID of called function
            caller_line: Line number of call
            arguments: Call arguments
            description: LLM-generated description
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO call_relations (
                project_path, caller_id, callee_id, caller_line, arguments, description
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            project_path,
            caller_id,
            callee_id,
            caller_line,
            json.dumps(arguments) if arguments else None,
            description
        ))

        self.conn.commit()

    def save_calls(self, project_path: str, calls: List[Dict[str, Any]]):
        """
        Batch save multiple call relations.

        Args:
            project_path: Root path of project
            calls: List of call relation dicts
        """
        logger.info(f"save_calls called with {len(calls)} calls for project: {project_path}")
        cursor = self.conn.cursor()

        saved_count = 0
        failed_count = 0

        for call_data in calls:
            try:
                cursor.execute("""
                    INSERT INTO call_relations (
                        project_path, caller_id, callee_id, caller_line, arguments, description
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    project_path,
                    call_data['caller_id'],
                    call_data['callee_id'],
                    call_data.get('caller_line'),
                    json.dumps(call_data.get('arguments')) if call_data.get('arguments') else None,
                    call_data.get('description')
                ))
                saved_count += 1
            except Exception as e:
                logger.error(f"Failed to save call {call_data.get('caller_id')} -> {call_data.get('callee_id')}: {e}")
                failed_count += 1

        logger.info(f"Committing {saved_count} calls (failed {failed_count})")
        self.conn.commit()

        # Force flush to disk
        self.conn.execute("PRAGMA wal_checkpoint(FULL)")

        # Verify the save
        cursor.execute("SELECT COUNT(*) FROM call_relations WHERE project_path = ?", (project_path,))
        count_after = cursor.fetchone()[0]
        logger.info(f"After commit: {count_after} call relations in database for this project")

    def get_entry_points(self, project_path: str) -> List[Dict[str, Any]]:
        """
        Get all entry point functions.

        Args:
            project_path: Root path of project

        Returns:
            List of entry point function records
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM functions
            WHERE project_path = ? AND is_entry_point = 1
            ORDER BY trigger_type, file_path, line_number
        """, (project_path,))

        return [dict(row) for row in cursor.fetchall()]

    def get_function(self, func_id: str) -> Optional[Dict[str, Any]]:
        """
        Get function by ID.

        Args:
            func_id: Function identifier

        Returns:
            Function record or None
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM functions WHERE id = ?", (func_id,))

        row = cursor.fetchone()
        return dict(row) if row else None

    def get_calls_from(self, func_id: str) -> List[Dict[str, Any]]:
        """
        Get all functions called by this function.

        Args:
            func_id: Function identifier

        Returns:
            List of call relation records
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT cr.*, f.function_name as callee_name, f.file_path as callee_file, f.layer as callee_layer
            FROM call_relations cr
            JOIN functions f ON cr.callee_id = f.id
            WHERE cr.caller_id = ?
            ORDER BY cr.caller_line
        """, (func_id,))

        return [dict(row) for row in cursor.fetchall()]

    def get_calls_to(self, func_id: str) -> List[Dict[str, Any]]:
        """
        Get all functions that call this function.

        Args:
            func_id: Function identifier

        Returns:
            List of call relation records
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT cr.*, f.function_name as caller_name, f.file_path as caller_file, f.layer as caller_layer
            FROM call_relations cr
            JOIN functions f ON cr.caller_id = f.id
            WHERE cr.callee_id = ?
            ORDER BY f.file_path, cr.caller_line
        """, (func_id,))

        return [dict(row) for row in cursor.fetchall()]

    def build_call_stack(
        self,
        entry_point_id: str,
        max_depth: int = 10,
        visited: Optional[set] = None
    ) -> List[Dict[str, Any]]:
        """
        Build complete call stack from entry point using DFS.

        Args:
            entry_point_id: Starting function ID
            max_depth: Maximum traversal depth
            visited: Set of visited function IDs (for cycle detection)

        Returns:
            List of call steps with full context
        """
        if visited is None:
            visited = set()

        if entry_point_id in visited or max_depth <= 0:
            return []

        visited.add(entry_point_id)

        # Get function info
        func = self.get_function(entry_point_id)
        if not func:
            return []

        # Get all calls from this function
        calls = self.get_calls_from(entry_point_id)

        stack = [{
            'function': func,
            'calls': []
        }]

        # Recursively build stack for each call
        for call in calls:
            callee_stack = self.build_call_stack(
                call['callee_id'],
                max_depth - 1,
                visited.copy()
            )

            stack[0]['calls'].append({
                'call_info': call,
                'sub_stack': callee_stack
            })

        return stack

    def get_functions_by_layer(
        self,
        project_path: str,
        layer: str
    ) -> List[Dict[str, Any]]:
        """
        Get all functions in a specific layer.

        Args:
            project_path: Root path of project
            layer: Layer name (trigger/controller/service/provider/external)

        Returns:
            List of function records
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM functions
            WHERE project_path = ? AND layer = ?
            ORDER BY file_path, line_number
        """, (project_path, layer))

        return [dict(row) for row in cursor.fetchall()]

    def has_project(self, project_path: str) -> bool:
        """
        Check if project has been indexed.

        Args:
            project_path: Root path of project

        Returns:
            True if project exists in database
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) as count FROM functions WHERE project_path = ?
        """, (project_path,))

        result = cursor.fetchone()
        return result['count'] > 0

    def clear_project(self, project_path: str):
        """
        Remove all data for a project.

        Args:
            project_path: Root path of project
        """
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM call_relations WHERE project_path = ?", (project_path,))
        cursor.execute("DELETE FROM functions WHERE project_path = ?", (project_path,))
        self.conn.commit()

    def get_all_functions(self, project_path: str) -> List[Dict[str, Any]]:
        """
        Get all functions in a project.

        Args:
            project_path: Project path

        Returns:
            List of function dictionaries
        """
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT
                f.id,
                f.function_name,
                f.file_path,
                f.line_number,
                f.signature,
                f.layer,
                f.is_entry_point,
                f.trigger_type,
                f.trigger_metadata,
                f.description,
                f.parameters,
                f.return_type
            FROM functions f
            WHERE f.project_path = ?
            ORDER BY f.function_name
        """, (project_path,))

        functions = []
        for row in cursor.fetchall():
            functions.append({
                'id': row[0],
                'name': row[1],
                'file_path': row[2],
                'line_number': row[3],
                'signature': row[4],
                'layer': row[5],
                'is_entry_point': bool(row[6]),
                'trigger_type': row[7],
                'trigger_metadata': json.loads(row[8]) if row[8] else {},
                'description': row[9],
                'parameters': json.loads(row[10]) if row[10] else [],
                'return_type': row[11]
            })

        return functions

    def get_all_calls(self, project_path: str) -> List[Dict[str, Any]]:
        """
        Get all calls in a project.

        Args:
            project_path: Project path

        Returns:
            List of call dictionaries
        """
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT
                cr.id,
                cr.caller_id,
                cr.callee_id,
                cr.caller_line,
                caller.function_name as caller_name,
                callee.function_name as callee_name
            FROM call_relations cr
            LEFT JOIN functions caller ON cr.caller_id = caller.id
            LEFT JOIN functions callee ON cr.callee_id = callee.id
            WHERE cr.project_path = ?
        """, (project_path,))

        calls = []
        for row in cursor.fetchall():
            calls.append({
                'id': row[0],
                'caller_id': row[1],
                'callee_id': row[2],
                'line_number': row[3],
                'caller_name': row[4],
                'callee_name': row[5]
            })

        return calls

    def get_function_calls(self, project_path: str, function_id: str) -> List[Dict[str, Any]]:
        """
        Get all calls made by a function (what this function calls).

        Args:
            project_path: Project path
            function_id: Function ID

        Returns:
            List of calls with target function details
        """
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT
                cr.id,
                cr.callee_id,
                cr.caller_line,
                callee.function_name as callee_name,
                callee.file_path as callee_file,
                callee.layer as callee_layer
            FROM call_relations cr
            LEFT JOIN functions callee ON cr.callee_id = callee.id
            WHERE cr.project_path = ? AND cr.caller_id = ?
            ORDER BY cr.caller_line
        """, (project_path, function_id))

        calls = []
        for row in cursor.fetchall():
            calls.append({
                'id': row[0],
                'target_function_id': row[1],
                'line_number': row[2],
                'target_name': row[3],
                'target_file': row[4],
                'target_layer': row[5]
            })

        return calls

    def get_function_callers(self, project_path: str, function_id: str) -> List[Dict[str, Any]]:
        """
        Get all functions that call this function (who calls this function).

        Args:
            project_path: Project path
            function_id: Function ID

        Returns:
            List of callers with function details
        """
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT
                cr.id,
                cr.caller_id,
                cr.caller_line,
                caller.function_name as caller_name,
                caller.file_path as caller_file,
                caller.layer as caller_layer
            FROM call_relations cr
            JOIN functions caller ON cr.caller_id = caller.id
            WHERE cr.project_path = ? AND cr.callee_id = ?
            ORDER BY caller.function_name, cr.caller_line
        """, (project_path, function_id))

        callers = []
        for row in cursor.fetchall():
            callers.append({
                'id': row[0],
                'caller_function_id': row[1],
                'line_number': row[2],
                'caller_name': row[3],
                'caller_file': row[4],
                'caller_layer': row[5]
            })

        return callers

    def get_statistics(self, project_path: str) -> Dict[str, Any]:
        """
        Get statistics about indexed project.

        Args:
            project_path: Root path of project

        Returns:
            Statistics dict
        """
        cursor = self.conn.cursor()

        # Function counts
        cursor.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN is_entry_point = 1 THEN 1 ELSE 0 END) as entry_points
            FROM functions WHERE project_path = ?
        """, (project_path,))
        func_stats = dict(cursor.fetchone())

        # Layer distribution
        cursor.execute("""
            SELECT layer, COUNT(*) as count
            FROM functions
            WHERE project_path = ?
            GROUP BY layer
        """, (project_path,))
        layers = {row['layer']: row['count'] for row in cursor.fetchall()}

        # Call counts
        cursor.execute("""
            SELECT COUNT(*) as total FROM call_relations WHERE project_path = ?
        """, (project_path,))
        call_stats = dict(cursor.fetchone())

        return {
            'functions': func_stats,
            'layers': layers,
            'calls': call_stats
        }

    def _format_signature(self, func_def: FunctionDefinition) -> str:
        """Format function signature for display."""
        params = ', '.join(func_def.parameters)
        return_type = f" -> {func_def.return_type}" if func_def.return_type else ""
        async_prefix = "async " if func_def.is_async else ""
        return f"{async_prefix}{func_def.name}({params}){return_type}"

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
