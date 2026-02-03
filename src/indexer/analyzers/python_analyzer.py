"""Python-specific AST analyzer."""

from pathlib import Path
from typing import Optional

from .base import BaseLanguageAnalyzer
from ..ast_analyzer import CallGraph, FunctionDefinition, FunctionCall, ImportStatement
from ...utils.logger import get_logger

logger = get_logger(__name__)


class PythonAnalyzer(BaseLanguageAnalyzer):
    """
    Python AST analyzer with support for:
    - async/await functions
    - Decorators
    - Class methods
    - Import variations (from X import Y, import X as Y)
    """

    def get_function_types(self) -> set:
        """Python function definition node types."""
        return {'function_definition'}

    def get_call_types(self) -> set:
        """Python function call node types."""
        return {'call'}

    def analyze(self, tree, code: str, file_path: Path) -> CallGraph:
        """
        Analyze Python AST tree.

        Args:
            tree: Tree-sitter AST tree
            code: Python source code
            file_path: Path to Python file

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

        def traverse(node, parent_function=None):
            """Recursively traverse AST."""
            nonlocal current_function, current_class

            # Handle class definitions
            if node.type == 'class_definition':
                class_name = None
                for child in node.children:
                    if child.type == 'identifier':
                        class_name = self.get_text(child, code_bytes)
                        break

                prev_class = current_class
                current_class = class_name

                for child in node.children:
                    traverse(child, parent_function)

                current_class = prev_class
                return

            # Handle function definitions
            if node.type == 'function_definition':
                func_name = None
                for child in node.children:
                    if child.type == 'identifier':
                        func_name = self.get_text(child, code_bytes)
                        break

                if func_name:
                    # Extract parameters
                    params = []
                    params_node = node.child_by_field_name('parameters')
                    if params_node:
                        for child in params_node.named_children:
                            if child.type == 'identifier':
                                params.append(self.get_text(child, code_bytes))

                    # Check if async
                    is_async = any(child.type == 'async' for child in node.children)

                    func_def = FunctionDefinition(
                        name=func_name,
                        parameters=params,
                        return_type=None,
                        line_number=node.start_point[0] + 1,
                        is_async=is_async,
                        is_method=current_class is not None,
                        class_name=current_class
                    )

                    functions.append(func_def)
                    exports.append(func_name)

                    # Update context
                    prev_function = current_function
                    current_function = func_name

                    # Traverse function body
                    for child in node.children:
                        traverse(child, func_name)

                    current_function = prev_function
                    return

            # Handle function calls
            elif node.type == 'call':
                function_node = node.child_by_field_name('function')
                if function_node and current_function:
                    callee_name = self.get_text(function_node, code_bytes)

                    # Extract module if present (e.g., module.function)
                    module_name = None
                    if '.' in callee_name:
                        parts = callee_name.split('.')
                        module_name = '.'.join(parts[:-1])
                        callee_name = parts[-1]

                    # Extract arguments
                    args = []
                    args_node = node.child_by_field_name('arguments')
                    if args_node:
                        for child in args_node.named_children:
                            args.append(self.get_text(child, code_bytes)[:50])

                    call = FunctionCall(
                        caller_function=current_function,
                        callee_name=callee_name,
                        line_number=node.start_point[0] + 1,
                        arguments=args,
                        module=module_name
                    )
                    calls.append(call)

            # Handle imports
            elif node.type in ('import_statement', 'import_from_statement'):
                import_stmt = self._extract_import(node, code_bytes)
                if import_stmt:
                    imports.append(import_stmt)

            # Continue traversing
            for child in node.children:
                traverse(child, parent_function)

        # Start traversal
        traverse(root_node)

        logger.debug(f"Python analyzer: found {len(functions)} functions, {len(calls)} calls")

        return CallGraph(
            functions=functions,
            calls=calls,
            imports=imports,
            exports=exports
        )

    def _extract_import(self, node, code_bytes: bytes) -> Optional[ImportStatement]:
        """
        Extract import statement from Python.

        Handles:
        - import module
        - import module as alias
        - from module import name
        - from module import name as alias

        Args:
            node: Import node
            code_bytes: Source code bytes

        Returns:
            ImportStatement or None
        """
        if node.type == 'import_statement':
            # import X or import X as Y
            module_name = None
            alias = None

            for child in node.children:
                if child.type == 'dotted_name':
                    module_name = self.get_text(child, code_bytes)
                elif child.type == 'aliased_import':
                    # import X as Y
                    name_node = child.child_by_field_name('name')
                    alias_node = child.child_by_field_name('alias')
                    if name_node:
                        module_name = self.get_text(name_node, code_bytes)
                    if alias_node:
                        alias = self.get_text(alias_node, code_bytes)

            if module_name:
                return ImportStatement(module=module_name, imported_names=[], alias=alias)

        elif node.type == 'import_from_statement':
            # from X import Y
            module_name = None
            imported_names = []

            module_node = node.child_by_field_name('module_name')
            if module_node:
                module_name = self.get_text(module_node, code_bytes)

            for child in node.children:
                if child.type == 'dotted_name' and not module_name:
                    module_name = self.get_text(child, code_bytes)
                elif child.type == 'identifier':
                    imported_names.append(self.get_text(child, code_bytes))

            if module_name:
                return ImportStatement(module=module_name, imported_names=imported_names, alias=None)

        return None
