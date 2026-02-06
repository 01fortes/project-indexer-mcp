"""Python-specific AST analyzer."""

from pathlib import Path
from typing import List, Optional

from .base import BaseLanguageAnalyzer
from ..ast_analyzer import CallGraph, FunctionDefinition, FunctionCall, ImportStatement
from ...storage.models import ExtractedFunction
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

    def extract_functions(self, tree, code: str, file_path: Path) -> List[ExtractedFunction]:
        """
        Extract all functions from Python code with full details.

        Handles:
        - Regular functions (def)
        - Async functions (async def)
        - Class methods
        - Decorators
        - Docstrings

        Args:
            tree: Tree-sitter AST tree
            code: Python source code
            file_path: Path to Python file

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

        def extract_decorators(node) -> List[str]:
            """Extract decorators from function node or its decorated_definition parent."""
            decorators = []

            # Check if parent is decorated_definition
            if node.parent and node.parent.type == 'decorated_definition':
                for child in node.parent.children:
                    if child.type == 'decorator':
                        dec_text = self.get_text(child, code_bytes)
                        # Remove @ and newlines
                        dec_text = dec_text.strip().lstrip('@').strip()
                        decorators.append(dec_text)

            return decorators

        def extract_docstring(node) -> Optional[str]:
            """Extract docstring from function body."""
            body = node.child_by_field_name('body')
            if body:
                for child in body.children:
                    if child.type == 'expression_statement':
                        for sub in child.children:
                            if sub.type == 'string':
                                doc = self.get_text(sub, code_bytes)
                                # Clean up triple quotes
                                doc = doc.strip()
                                for quote in ['"""', "'''"]:
                                    if doc.startswith(quote) and doc.endswith(quote):
                                        doc = doc[3:-3].strip()
                                        break
                                return doc
                        break  # Only check first statement
            return None

        def extract_return_type(node) -> Optional[str]:
            """Extract return type annotation."""
            return_type = node.child_by_field_name('return_type')
            if return_type:
                return self.get_text(return_type, code_bytes)
            return None

        def traverse(node, current_class=None):
            """Recursively traverse AST and extract functions."""

            # Handle class definitions
            if node.type == 'class_definition':
                class_name = None
                for child in node.children:
                    if child.type == 'identifier':
                        class_name = self.get_text(child, code_bytes)
                        break

                for child in node.children:
                    traverse(child, current_class=class_name)
                return

            # Handle decorated definitions
            if node.type == 'decorated_definition':
                for child in node.children:
                    if child.type == 'function_definition':
                        # Process the function with decorators
                        extract_function(child, current_class, node)
                return

            # Handle function definitions
            if node.type == 'function_definition':
                extract_function(node, current_class, None)
                return

            # Continue traversal
            for child in node.children:
                traverse(child, current_class)

        def extract_function(node, current_class, decorated_parent):
            """Extract a single function definition."""
            func_name = None
            for child in node.children:
                if child.type == 'identifier':
                    func_name = self.get_text(child, code_bytes)
                    break

            if not func_name:
                return

            # Get line numbers
            if decorated_parent:
                # Include decorator lines
                start_line = decorated_parent.start_point[0]
            else:
                start_line = node.start_point[0]
            end_line = node.end_point[0]

            # Extract parameters
            params = []
            params_node = node.child_by_field_name('parameters')
            if params_node:
                for child in params_node.named_children:
                    if child.type == 'identifier':
                        params.append(self.get_text(child, code_bytes))
                    elif child.type in ('typed_parameter', 'typed_default_parameter', 'default_parameter'):
                        # Get the parameter name
                        for sub in child.children:
                            if sub.type == 'identifier':
                                params.append(self.get_text(sub, code_bytes))
                                break

            # Check if async
            is_async = any(child.type == 'async' for child in node.children)

            # Get decorators
            decorators = extract_decorators(node)

            # Get docstring
            docstring = extract_docstring(node)

            # Get return type
            return_type = extract_return_type(node)

            # Get full function code
            func_code = get_function_code(start_line, end_line)

            extracted = ExtractedFunction(
                name=func_name,
                file_path=str(file_path),
                line_start=start_line + 1,  # 1-indexed
                line_end=end_line + 1,
                code=func_code,
                parameters=params,
                return_type=return_type,
                is_async=is_async,
                is_method=current_class is not None,
                class_name=current_class,
                decorators=decorators,
                docstring=docstring
            )

            functions.append(extracted)

            # Also traverse into nested functions
            for child in node.children:
                traverse(child, None)

        # Start traversal
        traverse(root_node)

        logger.debug(f"Python extractor: found {len(functions)} functions in {file_path}")
        return functions
