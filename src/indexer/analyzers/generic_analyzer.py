"""Generic AST analyzer for languages without specific implementation."""

from pathlib import Path
from typing import Optional

from .base import BaseLanguageAnalyzer
from ..ast_analyzer import CallGraph, FunctionDefinition, FunctionCall
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
