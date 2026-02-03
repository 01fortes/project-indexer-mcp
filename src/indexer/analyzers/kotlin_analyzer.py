"""Kotlin-specific AST analyzer."""

from pathlib import Path
from typing import Optional

from .base import BaseLanguageAnalyzer
from ..ast_analyzer import CallGraph, FunctionDefinition, FunctionCall, ImportStatement
from ...utils.logger import get_logger

logger = get_logger(__name__)


class KotlinAnalyzer(BaseLanguageAnalyzer):
    """
    Kotlin AST analyzer with support for:
    - Suspend functions
    - Extension functions
    - Property access syntax
    - Navigation expressions (object.method calls)
    - Lambda expressions
    """

    def get_function_types(self) -> set:
        """Kotlin function definition node types."""
        return {
            'function_declaration',
            'class_method',
            'function_definition'
        }

    def get_call_types(self) -> set:
        """Kotlin function call node types."""
        return {
            'call_expression',
            'navigation_expression'
        }

    def analyze(self, tree, code: str, file_path: Path) -> CallGraph:
        """
        Analyze Kotlin AST tree.

        Args:
            tree: Tree-sitter AST tree
            code: Kotlin source code
            file_path: Path to Kotlin file

        Returns:
            CallGraph with functions, calls, imports
        """
        functions = []
        calls = []
        imports = []
        exports = []

        root_node = tree.root_node
        code_bytes = bytes(code, "utf8")
        current_function = None
        current_class = None

        def traverse(node, parent_function=None, parent_class=None):
            """Recursively traverse AST."""
            nonlocal current_function, current_class

            # Check if this is a class declaration
            if node.type == 'class_declaration':
                class_name = None
                for child in node.children:
                    if child.type == 'simple_identifier':
                        class_name = self.get_text(child, code_bytes)
                        break

                prev_class = current_class
                current_class = class_name

                # Continue traversing children
                for child in node.children:
                    traverse(child, parent_function, class_name)

                current_class = prev_class
                return

            # Check if this is a function definition
            if node.type in self.get_function_types():
                func_name = self.extract_function_name(node, code_bytes)

                if func_name:
                    # Check if suspend function
                    is_async = any(
                        child.type == 'suspend' or self.get_text(child, code_bytes) == 'suspend'
                        for child in node.children
                    )

                    # Extract parameters
                    params = self.extract_parameters(node, code_bytes)

                    # Extract return type
                    return_type = self._extract_return_type(node, code_bytes)

                    func_def = FunctionDefinition(
                        name=func_name,
                        parameters=params,
                        return_type=return_type,
                        line_number=node.start_point[0] + 1,
                        is_async=is_async,
                        is_method=parent_class is not None,
                        class_name=current_class
                    )

                    functions.append(func_def)
                    exports.append(func_name)

                    # Update current function context
                    prev_function = current_function
                    current_function = func_name

                    # Traverse function body
                    for child in node.children:
                        traverse(child, func_name, parent_class)

                    current_function = prev_function
                    return

            # Check if this is a function call
            if node.type == 'call_expression':
                call = self._extract_call(node, code_bytes, current_function)
                if call:
                    calls.append(call)

            # Check for navigation expressions (object.method calls)
            elif node.type == 'navigation_expression':
                call = self._extract_navigation_call(node, code_bytes, current_function)
                if call:
                    calls.append(call)

            # Parse imports
            if node.type == 'import_header':
                import_stmt = self._extract_import(node, code_bytes)
                if import_stmt:
                    imports.append(import_stmt)

            # Continue traversing children
            for child in node.children:
                traverse(child, parent_function, parent_class)

        # Start traversal
        traverse(root_node)

        logger.debug(f"Kotlin analyzer: found {len(functions)} functions, {len(calls)} calls")

        return CallGraph(
            functions=functions,
            calls=calls,
            imports=imports,
            exports=exports
        )

    def _extract_call(self, node, code_bytes: bytes, current_function: Optional[str]) -> Optional[FunctionCall]:
        """
        Extract function call from call_expression node.

        Handles:
        - Simple calls: functionName()
        - Method calls: object.method()
        - Chain calls: obj.method1().method2()

        Args:
            node: call_expression node
            code_bytes: Source code bytes
            current_function: Current function context

        Returns:
            FunctionCall or None
        """
        if not current_function:
            return None

        callee_name = None
        module_name = None

        # Look for the expression being called (before parentheses)
        for child in node.children:
            if child.type == 'navigation_expression':
                # This is object.method() call
                full_expr = self.get_text(child, code_bytes)
                if '.' in full_expr:
                    parts = full_expr.split('.')
                    module_name = '.'.join(parts[:-1])
                    callee_name = parts[-1]
                else:
                    callee_name = full_expr
                break
            elif child.type == 'simple_identifier':
                # Simple function call
                callee_name = self.get_text(child, code_bytes)
                break

        if callee_name:
            return FunctionCall(
                caller_function=current_function,
                callee_name=callee_name,
                line_number=node.start_point[0] + 1,
                arguments=[],
                module=module_name
            )

        return None

    def _extract_navigation_call(self, node, code_bytes: bytes, current_function: Optional[str]) -> Optional[FunctionCall]:
        """
        Extract call from navigation_expression (dot notation).

        This handles cases where the navigation itself represents a callable.

        Args:
            node: navigation_expression node
            code_bytes: Source code bytes
            current_function: Current function context

        Returns:
            FunctionCall or None
        """
        # Check if parent is call_expression - if yes, skip (handled by _extract_call)
        if node.parent and node.parent.type == 'call_expression':
            return None

        # This might be a property access or method reference, not a call
        return None

    def _extract_import(self, node, code_bytes: bytes) -> Optional[ImportStatement]:
        """
        Extract import statement.

        Kotlin imports: import com.example.MyClass

        Args:
            node: import_header node
            code_bytes: Source code bytes

        Returns:
            ImportStatement or None
        """
        import_text = self.get_text(node, code_bytes)

        # Remove "import " prefix
        if import_text.startswith('import '):
            import_path = import_text[7:].strip()

            # Handle wildcard imports
            if import_path.endswith('.*'):
                module = import_path[:-2]
                return ImportStatement(module=module, imported_names=[], alias=None)

            # Regular import
            parts = import_path.split('.')
            if len(parts) > 1:
                module = '.'.join(parts[:-1])
                name = parts[-1]
                return ImportStatement(module=module, imported_names=[name], alias=None)
            else:
                return ImportStatement(module=import_path, imported_names=[], alias=None)

        return None

    def _extract_return_type(self, node, code_bytes: bytes) -> Optional[str]:
        """
        Extract return type from function declaration.

        Kotlin syntax: fun methodName(): ReturnType

        Args:
            node: Function node
            code_bytes: Source code bytes

        Returns:
            Return type string or None
        """
        for child in node.children:
            if child.type == 'type':
                return self.get_text(child, code_bytes)
        return None
