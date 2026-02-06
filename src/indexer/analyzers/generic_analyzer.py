"""Generic AST analyzer for languages without specific implementation."""

from pathlib import Path
from typing import List, Optional

from .base import BaseLanguageAnalyzer
from ..ast_analyzer import CallGraph, FunctionDefinition, FunctionCall
from ...storage.models import ExtractedFunction
from ...utils.logger import get_logger

logger = get_logger(__name__)


class GenericAnalyzer(BaseLanguageAnalyzer):
    """
    Generic AST analyzer for languages without specific handlers.

    Uses common node types that work across multiple languages.
    """

    def __init__(self, language: str):
        """
        Initialize generic analyzer.

        Args:
            language: Programming language name
        """
        self.language = language

    def get_function_types(self) -> set:
        """Common function definition node types across languages."""
        return {
            'function_declaration', 'function_definition', 'method_declaration',
            'function_item',  # Rust
            'function', 'func_literal',  # Go
            'class_method', 'function_definition',  # Kotlin/Java
        }

    def get_call_types(self) -> set:
        """Common call node types across languages."""
        return {
            'call_expression', 'function_call', 'method_invocation',
            'call', 'invocation_expression'
        }

    def analyze(self, tree, code: str, file_path: Path) -> CallGraph:
        """
        Generic AST analysis.

        Args:
            tree: Tree-sitter AST tree
            code: Source code
            file_path: Path to source file

        Returns:
            CallGraph with functions and calls
        """
        functions = []
        calls = []
        imports = []
        exports = []

        root_node = tree.root_node
        code_bytes = bytes(code, "utf8")
        current_function = None

        def traverse(node, parent_function=None):
            """Recursively traverse AST tree."""
            nonlocal current_function

            # Check if this is a function/method definition
            if node.type in self.get_function_types():
                func_name = self.extract_function_name(node, code_bytes)

                if func_name:
                    params = self.extract_parameters(node, code_bytes)

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
            elif node.type in self.get_call_types():
                callee_name = None
                for child in node.children:
                    if child.type in ('identifier', 'property_identifier', 'simple_identifier', 'field_identifier'):
                        callee_name = self.get_text(child, code_bytes)
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

        logger.debug(f"Generic analyzer for {self.language}: found {len(functions)} functions, {len(calls)} calls")

        return CallGraph(functions=functions, calls=calls, imports=imports, exports=exports)

    def extract_functions(self, tree, code: str, file_path: Path) -> List[ExtractedFunction]:
        """
        Extract all functions from code with full details.

        Generic implementation that works across multiple languages.

        Args:
            tree: Tree-sitter AST tree
            code: Source code
            file_path: Path to source file

        Returns:
            List of ExtractedFunction objects
        """
        functions = []
        root_node = tree.root_node
        code_bytes = bytes(code, "utf8")
        code_lines = code.split('\n')

        def get_function_code(start_line: int, end_line: int) -> str:
            """Extract function source code from line numbers."""
            return '\n'.join(code_lines[start_line:end_line + 1])

        def traverse(node, current_class=None):
            """Recursively traverse AST and extract functions."""

            # Check for class-like definitions
            if node.type in ('class_declaration', 'class_definition', 'class_specifier'):
                class_name = None
                for child in node.children:
                    if child.type in ('identifier', 'simple_identifier', 'type_identifier'):
                        class_name = self.get_text(child, code_bytes)
                        break

                for child in node.children:
                    traverse(child, current_class=class_name)
                return

            # Check if this is a function/method definition
            if node.type in self.get_function_types():
                func_name = self.extract_function_name(node, code_bytes)

                if func_name:
                    start_line = node.start_point[0]
                    end_line = node.end_point[0]

                    params = self.extract_parameters(node, code_bytes)
                    func_code = get_function_code(start_line, end_line)

                    extracted = ExtractedFunction(
                        name=func_name,
                        file_path=str(file_path),
                        line_start=start_line + 1,
                        line_end=end_line + 1,
                        code=func_code,
                        parameters=params,
                        return_type=None,
                        is_async=False,
                        is_method=current_class is not None,
                        class_name=current_class,
                        decorators=[],
                        docstring=self._extract_docstring(node, code_bytes)
                    )

                    functions.append(extracted)

            # Continue traversing children
            for child in node.children:
                traverse(child, current_class)

        # Start traversal
        traverse(root_node)

        logger.debug(f"Generic extractor for {self.language}: found {len(functions)} functions in {file_path}")
        return functions
