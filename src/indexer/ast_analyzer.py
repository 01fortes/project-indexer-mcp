"""Universal AST analysis using tree-sitter for call graph extraction.

This module provides language-agnostic code analysis by using tree-sitter parsers.
Tree-sitter supports 50+ languages with a unified API.
"""

from pathlib import Path
from typing import Dict, List, Optional, Set
from dataclasses import dataclass

from ..utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class FunctionCall:
    """Represents a function call in code."""
    caller_function: str  # Function making the call
    callee_name: str  # Function being called
    line_number: int
    arguments: List[str]  # Argument names/expressions
    module: Optional[str] = None  # For imported functions


@dataclass
class FunctionDefinition:
    """Represents a function/method definition."""
    name: str
    parameters: List[str]
    return_type: Optional[str]
    line_number: int
    is_async: bool = False
    is_method: bool = False
    class_name: Optional[str] = None


@dataclass
class ImportStatement:
    """Represents an import."""
    module: str
    imported_names: List[str]  # Empty if import *
    alias: Optional[str] = None


@dataclass
class CallGraph:
    """Complete call graph for a file."""
    functions: List[FunctionDefinition]
    calls: List[FunctionCall]
    imports: List[ImportStatement]
    exports: List[str]  # Exported symbols

    def get_callers(self, function_name: str) -> List[str]:
        """Get all functions that call this function."""
        return [call.caller_function for call in self.calls if call.callee_name == function_name]

    def get_callees(self, function_name: str) -> List[str]:
        """Get all functions called by this function."""
        return [call.callee_name for call in self.calls if call.caller_function == function_name]


class ASTAnalyzer:
    """
    Universal AST analyzer using tree-sitter.

    Supports multiple languages through tree-sitter grammars:
    - Python, JavaScript, TypeScript, Go, Rust, Java, C/C++, etc.
    """

    def __init__(self):
        """Initialize tree-sitter parsers for supported languages."""
        self.parsers = {}
        self.language_configs = {}

        # Try to load tree-sitter (optional dependency)
        try:
            import tree_sitter
            self.tree_sitter_available = True
            self._init_parsers()
        except ImportError:
            self.tree_sitter_available = False
            logger.warning(
                "tree-sitter not available. AST analysis will be limited. "
                "Install with: pip install tree-sitter tree-sitter-languages"
            )

    def _init_parsers(self):
        """Initialize tree-sitter parsers for each language."""
        try:
            from tree_sitter_languages import get_language, get_parser

            # Languages we support
            languages = [
                'python', 'javascript', 'typescript', 'go', 'rust',
                'java', 'kotlin', 'c', 'cpp', 'c_sharp', 'ruby', 'php',
                'swift', 'scala'
            ]

            for lang in languages:
                try:
                    self.parsers[lang] = get_parser(lang)
                    logger.debug(f"Loaded tree-sitter parser for {lang}")
                except Exception as e:
                    logger.warning(f"Could not load parser for {lang}: {e}")

        except ImportError:
            logger.warning("tree-sitter-languages not installed. Install: pip install tree-sitter-languages")

    def analyze_file(self, file_path: Path, language: str, code: str) -> Optional[CallGraph]:
        """
        Analyze a code file and extract call graph.

        Args:
            file_path: Path to file
            language: Programming language
            code: Source code content

        Returns:
            CallGraph object or None if analysis failed
        """
        if not self.tree_sitter_available:
            logger.warning("tree-sitter not available, skipping AST analysis")
            return None

        # Normalize language name
        lang_key = self._normalize_language(language)
        logger.debug(f"Normalized {language} -> {lang_key}")

        if lang_key not in self.parsers:
            logger.warning(f"No parser available for {language} (normalized: {lang_key}). Available: {list(self.parsers.keys())}")
            return None

        try:
            parser = self.parsers[lang_key]
            tree = parser.parse(bytes(code, "utf8"))

            # Use strategy pattern: get appropriate analyzer for language
            from .analyzers import get_analyzer
            analyzer = get_analyzer(lang_key)

            # Delegate analysis to language-specific analyzer
            return analyzer.analyze(tree, code, file_path)

        except Exception as e:
            logger.error(f"AST analysis failed for {file_path}: {e}")
            return None

    def _normalize_language(self, language: str) -> str:
        """Normalize language name to tree-sitter format."""
        mapping = {
            'py': 'python',
            'js': 'javascript',
            'ts': 'typescript',
            'tsx': 'typescript',
            'jsx': 'javascript',
            'rs': 'rust',
            'cs': 'c_sharp',
            'rb': 'ruby',
            'kt': 'kotlin',
            'kts': 'kotlin',
        }
        return mapping.get(language.lower(), language.lower())

    def _analyze_python(self, tree, code: str) -> CallGraph:
        """Extract call graph from Python code."""
        functions = []
        calls = []
        imports = []
        exports = []

        root_node = tree.root_node
        code_bytes = bytes(code, "utf8")

        # Helper to get text from node
        def get_text(node):
            return code_bytes[node.start_byte:node.end_byte].decode('utf8')

        # Current function context
        current_function = None

        # Traverse AST
        def traverse(node):
            nonlocal current_function

            if node.type == 'function_definition':
                # Extract function info
                name_node = node.child_by_field_name('name')
                params_node = node.child_by_field_name('parameters')

                if name_node:
                    func_name = get_text(name_node)

                    # Extract parameters
                    params = []
                    if params_node:
                        for child in params_node.named_children:
                            if child.type == 'identifier':
                                params.append(get_text(child))

                    # Check if async
                    is_async = any(child.type == 'async' for child in node.children)

                    func_def = FunctionDefinition(
                        name=func_name,
                        parameters=params,
                        return_type=None,  # TODO: extract from annotations
                        line_number=node.start_point[0] + 1,
                        is_async=is_async
                    )

                    functions.append(func_def)
                    exports.append(func_name)  # Assume exported unless private

                    # Set current context
                    old_function = current_function
                    current_function = func_name

                    # Traverse function body
                    for child in node.children:
                        traverse(child)

                    current_function = old_function
                    return

            elif node.type == 'call':
                # Extract function call
                function_node = node.child_by_field_name('function')
                args_node = node.child_by_field_name('arguments')

                if function_node:
                    callee_name = get_text(function_node)

                    # Extract argument names
                    args = []
                    if args_node:
                        for child in args_node.named_children:
                            args.append(get_text(child)[:50])  # Truncate long args

                    call = FunctionCall(
                        caller_function=current_function or '<module>',
                        callee_name=callee_name,
                        line_number=node.start_point[0] + 1,
                        arguments=args
                    )
                    calls.append(call)

            elif node.type == 'import_statement' or node.type == 'import_from_statement':
                # Extract imports
                module_node = node.child_by_field_name('module_name') or node.child_by_field_name('name')

                if module_node:
                    module_name = get_text(module_node)

                    # Extract imported names
                    imported = []
                    for child in node.named_children:
                        if child.type == 'dotted_name' or child.type == 'identifier':
                            if child != module_node:
                                imported.append(get_text(child))

                    import_stmt = ImportStatement(
                        module=module_name,
                        imported_names=imported
                    )
                    imports.append(import_stmt)

            # Recurse into children
            for child in node.children:
                traverse(child)

        traverse(root_node)

        return CallGraph(
            functions=functions,
            calls=calls,
            imports=imports,
            exports=exports
        )

    def _analyze_javascript(self, tree, code: str) -> CallGraph:
        """Extract call graph from JavaScript/TypeScript code."""
        # Similar to Python but with JS-specific syntax
        functions = []
        calls = []
        imports = []
        exports = []

        # TODO: Implement JS-specific analysis
        # Handle: function, arrow functions, async/await, import/export

        return CallGraph(
            functions=functions,
            calls=calls,
            imports=imports,
            exports=exports
        )

    def _analyze_go(self, tree, code: str) -> CallGraph:
        """Extract call graph from Go code."""
        # TODO: Implement Go-specific analysis
        return CallGraph(functions=[], calls=[], imports=[], exports=[])

    def _analyze_generic(self, tree, code: str, language: str) -> CallGraph:
        """Generic analysis for languages without specific handlers."""
        functions = []
        calls = []
        imports = []
        exports = []

        root_node = tree.root_node
        code_bytes = bytes(code, "utf8")

        def get_text(node):
            """Extract text from AST node."""
            return code_bytes[node.start_byte:node.end_byte].decode('utf8')

        # Common function/method node types across languages
        function_types = {
            'function_declaration', 'function_definition', 'method_declaration',
            'function_item',  # Rust
            'function', 'func_literal',  # Go
            'class_method', 'function_definition',  # Kotlin/Java
        }

        # Common call node types
        call_types = {
            'call_expression', 'function_call', 'method_invocation',
            'call', 'invocation_expression'
        }

        current_function = None

        def traverse(node, parent_function=None):
            """Recursively traverse AST tree."""
            nonlocal current_function

            # Check if this is a function/method definition
            if node.type in function_types:
                # Try to extract function name
                func_name = None
                for child in node.children:
                    if child.type in ('identifier', 'property_identifier', 'simple_identifier'):
                        func_name = get_text(child)
                        break

                if func_name:
                    # Extract parameters
                    params = []
                    for child in node.children:
                        if 'parameter' in child.type.lower():
                            params.append(get_text(child))

                    functions.append(FunctionDefinition(
                        name=func_name,
                        parameters=params,
                        return_type=None,
                        line_number=node.start_point[0] + 1,
                        is_async=False,
                        is_method=parent_function is not None
                    ))

                    # Update current function context
                    prev_function = current_function
                    current_function = func_name

                    # Traverse children
                    for child in node.children:
                        traverse(child, func_name)

                    current_function = prev_function
                    return

            # Check if this is a function call
            elif node.type in call_types:
                callee_name = None
                for child in node.children:
                    if child.type in ('identifier', 'property_identifier', 'simple_identifier', 'field_identifier'):
                        callee_name = get_text(child)
                        break

                if callee_name and current_function:
                    calls.append(FunctionCall(
                        caller_function=current_function,
                        callee_name=callee_name,
                        line_number=node.start_point[0] + 1,
                        arguments=[]
                    ))

            # Continue traversing children
            for child in node.children:
                traverse(child, parent_function)

        # Start traversal
        traverse(root_node)

        logger.debug(f"Generic analyzer for {language}: found {len(functions)} functions, {len(calls)} calls")

        return CallGraph(functions=functions, calls=calls, imports=imports, exports=exports)


# Factory function
def create_ast_analyzer() -> ASTAnalyzer:
    """Create and initialize AST analyzer."""
    return ASTAnalyzer()


# Example usage for testing
async def test_ast_analysis():
    """Test AST analysis on sample code."""
    analyzer = create_ast_analyzer()

    sample_python = """
import os
from typing import List

def process_data(items: List[str]) -> None:
    for item in items:
        result = transform_item(item)
        save_result(result)

def transform_item(item: str) -> dict:
    return {"value": item.upper()}

async def save_result(data: dict):
    await db.save(data)
"""

    graph = analyzer.analyze_file(
        Path("test.py"),
        "python",
        sample_python
    )

    if graph:
        print(f"Functions: {[f.name for f in graph.functions]}")
        print(f"Calls: {[(c.caller_function, c.callee_name) for c in graph.calls]}")
        print(f"Imports: {[i.module for i in graph.imports]}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_ast_analysis())
