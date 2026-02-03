"""Cross-file call resolution for building complete call graphs.

Resolves function calls across files by:
- Tracking imports and their sources
- Mapping function names to file locations
- Resolving both relative and absolute imports
"""

from pathlib import Path
from typing import Dict, List, Optional, Set
from dataclasses import dataclass

from .ast_analyzer import FunctionDefinition, FunctionCall, ImportStatement
from .language_adapters import get_language_adapter
from ..utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ResolvedCall:
    """A function call that has been resolved to a specific function."""
    caller_id: str
    callee_id: str
    caller_line: int
    arguments: List[str]
    confidence: str  # high/medium/low


class CallResolver:
    """
    Resolves cross-file function calls.

    Maintains a global map of all functions and their locations,
    then uses import statements to resolve calls to specific files.
    """

    def __init__(
        self,
        project_path: Path,
        functions_map: Dict[str, List[FunctionDefinition]],  # file_path -> functions
        imports_map: Dict[str, List[ImportStatement]]  # file_path -> imports
    ):
        """
        Initialize call resolver.

        Args:
            project_path: Root path of project
            functions_map: Map of file paths to their function definitions
            imports_map: Map of file paths to their imports
        """
        self.project_path = project_path
        self.functions_map = functions_map
        self.imports_map = imports_map

        # Build reverse index: function_name -> list of (file_path, func_def)
        self.function_index: Dict[str, List[tuple]] = {}
        self._build_function_index()

    def _build_function_index(self):
        """Build index of function names to their locations."""
        for file_path, functions in self.functions_map.items():
            for func_def in functions:
                if func_def.name not in self.function_index:
                    self.function_index[func_def.name] = []
                self.function_index[func_def.name].append((file_path, func_def))

        logger.debug(f"Indexed {len(self.function_index)} unique function names")

    def resolve_calls(
        self,
        file_path: str,
        calls: List[FunctionCall],
        language: str
    ) -> List[ResolvedCall]:
        """
        Resolve all calls from a file.

        Args:
            file_path: Source file path
            calls: List of function calls to resolve
            language: Programming language

        Returns:
            List of resolved calls
        """
        resolved = []
        imports = self.imports_map.get(file_path, [])
        adapter = get_language_adapter(language)

        for call in calls:
            resolved_call = self.resolve_call(
                call,
                file_path,
                language,
                imports,
                adapter
            )
            if resolved_call:
                resolved.append(resolved_call)

        return resolved

    def resolve_call(
        self,
        call: FunctionCall,
        caller_file: str,
        language: str,
        imports: List[ImportStatement],
        adapter
    ) -> Optional[ResolvedCall]:
        """
        Resolve a single function call.

        Args:
            call: Function call to resolve
            caller_file: File containing the call
            language: Programming language
            imports: Import statements from caller file
            adapter: Language adapter

        Returns:
            ResolvedCall or None if unresolved
        """
        # Get caller function definition line number (not call site line number)
        caller_func_line = self._get_function_line(caller_file, call.caller_function)
        if not caller_func_line:
            # Fallback to call line if function not found
            caller_func_line = call.line_number

        caller_id = f"{caller_file}::{call.caller_function}::{caller_func_line}"

        # Case 1: Call has explicit module (e.g., my_module.function)
        if call.module:
            target_file = self._resolve_module_import(
                call.module,
                caller_file,
                language,
                imports,
                adapter
            )

            if target_file:
                # Find function in target file
                callee_id = self._find_function_in_file(
                    target_file,
                    call.callee_name
                )
                if callee_id:
                    return ResolvedCall(
                        caller_id=caller_id,
                        callee_id=callee_id,
                        caller_line=call.line_number,
                        arguments=call.arguments,
                        confidence='high'
                    )

            # Case 1b: If module provided but not resolved via imports,
            # try module hint before checking same file
            global_matches = self.function_index.get(call.callee_name, [])
            module_lower = call.module.lower()

            filtered_matches = []
            for target_file, func_def in global_matches:
                file_name = Path(target_file).stem.lower()
                # Exclude same file to avoid false matches
                if target_file != caller_file and (module_lower in file_name or file_name in module_lower):
                    filtered_matches.append((target_file, func_def))

            if len(filtered_matches) == 1:
                target_file, func_def = filtered_matches[0]
                callee_id = f"{target_file}::{func_def.name}::{func_def.line_number}"
                logger.debug(f"Resolved {call.callee_name} via module hint '{call.module}' to {target_file}")
                return ResolvedCall(
                    caller_id=caller_id,
                    callee_id=callee_id,
                    caller_line=call.line_number,
                    arguments=call.arguments,
                    confidence='medium'
                )

        # Case 2: Call is in same file (only if no module specified)
        if not call.module:
            same_file_id = self._find_function_in_file(caller_file, call.callee_name)
            if same_file_id:
                return ResolvedCall(
                    caller_id=caller_id,
                    callee_id=same_file_id,
                    caller_line=call.line_number,
                    arguments=call.arguments,
                    confidence='high'
                )

        # Case 3: Search through imports
        for import_stmt in imports:
            if call.callee_name in import_stmt.imported_names or not import_stmt.imported_names:
                # Try to resolve this import
                target_file = self._resolve_module_import(
                    import_stmt.module,
                    caller_file,
                    language,
                    imports,
                    adapter
                )

                if target_file:
                    callee_id = self._find_function_in_file(target_file, call.callee_name)
                    if callee_id:
                        return ResolvedCall(
                            caller_id=caller_id,
                            callee_id=callee_id,
                            caller_line=call.line_number,
                            arguments=call.arguments,
                            confidence='medium'
                        )

        # Case 4: Search globally without module (low confidence)
        global_matches = self.function_index.get(call.callee_name, [])
        if len(global_matches) == 1:
            # Only one function with this name - probably it
            target_file, func_def = global_matches[0]
            callee_id = f"{target_file}::{func_def.name}::{func_def.line_number}"
            return ResolvedCall(
                caller_id=caller_id,
                callee_id=callee_id,
                caller_line=call.line_number,
                arguments=call.arguments,
                confidence='low'
            )

        # Unresolved - might be external library
        logger.debug(f"Could not resolve call to {call.callee_name} from {caller_file} (module: {call.module})")
        return None

    def _resolve_module_import(
        self,
        module_path: str,
        current_file: str,
        language: str,
        imports: List[ImportStatement],
        adapter
    ) -> Optional[str]:
        """
        Resolve module import to actual file path.

        Args:
            module_path: Import path (e.g., '../utils/helper')
            current_file: File containing the import
            language: Programming language
            imports: All imports from file
            adapter: Language adapter

        Returns:
            Resolved file path or None
        """
        if not adapter:
            return None

        try:
            current_path = Path(current_file)
            resolved_path = adapter.resolve_import(
                module_path,
                current_path,
                self.project_path
            )

            if resolved_path and resolved_path.exists():
                # Convert to relative path for consistency
                try:
                    rel_path = resolved_path.relative_to(self.project_path)
                    return str(rel_path)
                except ValueError:
                    return str(resolved_path)

        except Exception as e:
            logger.debug(f"Failed to resolve import {module_path}: {e}")

        return None

    def _find_function_in_file(
        self,
        file_path: str,
        function_name: str
    ) -> Optional[str]:
        """
        Find function ID in specific file.

        Args:
            file_path: Target file path
            function_name: Function name to find

        Returns:
            Function ID or None
        """
        functions = self.functions_map.get(file_path, [])

        for func_def in functions:
            if func_def.name == function_name:
                return f"{file_path}::{func_def.name}::{func_def.line_number}"

        return None

    def _get_function_line(
        self,
        file_path: str,
        function_name: str
    ) -> Optional[int]:
        """
        Get line number of function definition.

        Args:
            file_path: File path
            function_name: Function name

        Returns:
            Line number of function definition or None
        """
        functions = self.functions_map.get(file_path, [])

        for func_def in functions:
            if func_def.name == function_name:
                return func_def.line_number

        return None

    def get_resolution_stats(self, resolved_calls: List[ResolvedCall]) -> Dict[str, int]:
        """
        Get statistics about call resolution.

        Args:
            resolved_calls: List of resolved calls

        Returns:
            Statistics dict
        """
        stats = {
            'total': len(resolved_calls),
            'high_confidence': sum(1 for c in resolved_calls if c.confidence == 'high'),
            'medium_confidence': sum(1 for c in resolved_calls if c.confidence == 'medium'),
            'low_confidence': sum(1 for c in resolved_calls if c.confidence == 'low')
        }

        if stats['total'] > 0:
            stats['high_confidence_pct'] = (stats['high_confidence'] / stats['total']) * 100

        return stats
