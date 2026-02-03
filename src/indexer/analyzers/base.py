"""Base classes for language-specific AST analyzers."""

from abc import ABC, abstractmethod
from typing import List, Optional
from pathlib import Path

from ..ast_analyzer import CallGraph, FunctionDefinition, FunctionCall, ImportStatement


class BaseLanguageAnalyzer(ABC):
    """
    Base class for language-specific AST analyzers.

    Each language analyzer implements its own logic for:
    - Extracting function definitions
    - Finding function calls
    - Parsing imports
    - Handling language-specific syntax
    """

    @abstractmethod
    def analyze(self, tree, code: str, file_path: Path) -> CallGraph:
        """
        Analyze AST tree and extract call graph.

        Args:
            tree: Tree-sitter AST tree
            code: Source code string
            file_path: Path to source file

        Returns:
            CallGraph with functions, calls, imports
        """
        pass

    @abstractmethod
    def get_function_types(self) -> set:
        """
        Get AST node types that represent function/method definitions.

        Returns:
            Set of node type strings
        """
        pass

    @abstractmethod
    def get_call_types(self) -> set:
        """
        Get AST node types that represent function calls.

        Returns:
            Set of node type strings
        """
        pass

    def get_text(self, node, code_bytes: bytes) -> str:
        """
        Extract text from AST node.

        Args:
            node: Tree-sitter node
            code_bytes: Source code as bytes

        Returns:
            Text content of node
        """
        return code_bytes[node.start_byte:node.end_byte].decode('utf8')

    def extract_function_name(self, node, code_bytes: bytes) -> Optional[str]:
        """
        Extract function name from function definition node.

        Default implementation - can be overridden.

        Args:
            node: Function definition node
            code_bytes: Source code as bytes

        Returns:
            Function name or None
        """
        for child in node.children:
            if child.type in ('identifier', 'property_identifier', 'simple_identifier'):
                return self.get_text(child, code_bytes)
        return None

    def extract_parameters(self, node, code_bytes: bytes) -> List[str]:
        """
        Extract parameter names from function definition.

        Default implementation - can be overridden.

        Args:
            node: Function definition node
            code_bytes: Source code as bytes

        Returns:
            List of parameter names
        """
        params = []
        for child in node.children:
            if 'parameter' in child.type.lower():
                params.append(self.get_text(child, code_bytes))
        return params
