"""Language-specific adapters for trigger detection, import resolution, and layer classification.

Each adapter implements language-specific logic for:
- Detecting triggers (HTTP endpoints, Kafka consumers, scheduled jobs, etc.)
- Resolving imports to actual file paths
- Classifying functions into architectural layers
- Formatting function signatures
"""

import re
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from abc import ABC, abstractmethod

from ..utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class TriggerInfo:
    """Information about a detected trigger/entry point."""
    function_name: str
    trigger_type: str  # http/grpc/kafka/scheduled/websocket/graphql
    metadata: Dict[str, Any]  # type-specific metadata


class LanguageAdapter(ABC):
    """Base class for language-specific adapters."""

    @abstractmethod
    def detect_triggers(
        self,
        ast_tree,
        code: str,
        file_path: Path
    ) -> List[TriggerInfo]:
        """
        Detect entry point triggers in code.

        Args:
            ast_tree: Tree-sitter AST
            code: Source code
            file_path: Path to file

        Returns:
            List of detected triggers
        """
        pass

    @abstractmethod
    def resolve_import(
        self,
        import_path: str,
        current_file: Path,
        project_root: Path
    ) -> Optional[Path]:
        """
        Resolve import to actual file path.

        Args:
            import_path: Import statement path
            current_file: File containing the import
            project_root: Project root directory

        Returns:
            Resolved file path or None
        """
        pass

    @abstractmethod
    def classify_layer(
        self,
        function_name: str,
        file_path: Path,
        has_trigger: bool,
        decorators: List[str] = None
    ) -> str:
        """
        Classify function into architectural layer.

        Args:
            function_name: Name of function
            file_path: Path to file
            has_trigger: Whether function has a trigger
            decorators: List of decorator names

        Returns:
            Layer name (trigger/controller/service/provider/external)
        """
        pass

    @abstractmethod
    def format_signature(
        self,
        function_name: str,
        parameters: List[str],
        return_type: Optional[str] = None
    ) -> str:
        """
        Format function signature for display.

        Args:
            function_name: Function name
            parameters: Parameter list
            return_type: Return type annotation

        Returns:
            Formatted signature string
        """
        pass


class PythonAdapter(LanguageAdapter):
    """Python-specific adapter."""

    HTTP_DECORATORS = [
        'app.get', 'app.post', 'app.put', 'app.delete', 'app.patch',
        'route', 'get', 'post', 'put', 'delete', 'patch',
        'api_view', 'require_http_methods'
    ]

    KAFKA_DECORATORS = [
        'kafka.consumer', 'consumer', 'kafka_consumer'
    ]

    CELERY_DECORATORS = [
        'celery.task', 'task', 'shared_task', 'periodic_task'
    ]

    GRAPHQL_DECORATORS = [
        'query', 'mutation', 'subscription', 'field'
    ]

    def detect_triggers(
        self,
        ast_tree,
        code: str,
        file_path: Path
    ) -> List[TriggerInfo]:
        """Detect triggers in Python code."""
        triggers = []

        if not ast_tree:
            # Fallback to regex-based detection
            return self._detect_triggers_regex(code)

        code_bytes = bytes(code, "utf8")

        def get_text(node):
            return code_bytes[node.start_byte:node.end_byte].decode('utf8')

        def traverse(node):
            if node.type == 'function_definition':
                name_node = node.child_by_field_name('name')
                if not name_node:
                    return

                func_name = get_text(name_node)

                # Check decorators
                decorators = []
                for child in node.children:
                    if child.type == 'decorator':
                        dec_text = get_text(child).strip('@').strip()
                        decorators.append(dec_text)

                # Detect HTTP triggers
                for dec in decorators:
                    if any(http_dec in dec for http_dec in self.HTTP_DECORATORS):
                        method, path = self._parse_http_decorator(dec)
                        triggers.append(TriggerInfo(
                            function_name=func_name,
                            trigger_type='http',
                            metadata={'method': method, 'path': path, 'decorator': dec}
                        ))

                    # Kafka consumers
                    elif any(kafka_dec in dec for kafka_dec in self.KAFKA_DECORATORS):
                        topic = self._parse_kafka_decorator(dec)
                        triggers.append(TriggerInfo(
                            function_name=func_name,
                            trigger_type='kafka',
                            metadata={'topic': topic, 'decorator': dec}
                        ))

                    # Scheduled tasks
                    elif any(celery_dec in dec for celery_dec in self.CELERY_DECORATORS):
                        schedule = self._parse_celery_decorator(dec)
                        triggers.append(TriggerInfo(
                            function_name=func_name,
                            trigger_type='scheduled',
                            metadata={'schedule': schedule, 'decorator': dec}
                        ))

                    # GraphQL
                    elif any(gql_dec in dec for gql_dec in self.GRAPHQL_DECORATORS):
                        triggers.append(TriggerInfo(
                            function_name=func_name,
                            trigger_type='graphql',
                            metadata={'decorator': dec}
                        ))

            # Recurse
            for child in node.children:
                traverse(child)

        traverse(ast_tree.root_node)
        return triggers

    def _detect_triggers_regex(self, code: str) -> List[TriggerInfo]:
        """Fallback regex-based trigger detection."""
        triggers = []

        # HTTP decorators
        http_pattern = r'@(?:app\.)?(get|post|put|delete|patch)\(["\']([^"\']+)["\']\)'
        for match in re.finditer(http_pattern, code, re.IGNORECASE):
            method = match.group(1).upper()
            path = match.group(2)
            # Extract function name from next line
            func_match = re.search(r'def\s+(\w+)', code[match.end():match.end()+100])
            if func_match:
                triggers.append(TriggerInfo(
                    function_name=func_match.group(1),
                    trigger_type='http',
                    metadata={'method': method, 'path': path}
                ))

        return triggers

    def _parse_http_decorator(self, decorator: str) -> tuple:
        """Parse HTTP method and path from decorator."""
        # Examples: @app.post('/users'), @route('/users', methods=['POST'])
        method_match = re.search(r'\.(get|post|put|delete|patch)', decorator)
        method = method_match.group(1).upper() if method_match else 'GET'

        path_match = re.search(r'["\']([^"\']+)["\']', decorator)
        path = path_match.group(1) if path_match else '/'

        return method, path

    def _parse_kafka_decorator(self, decorator: str) -> str:
        """Parse Kafka topic from decorator."""
        topic_match = re.search(r'["\']([^"\']+)["\']', decorator)
        return topic_match.group(1) if topic_match else 'unknown'

    def _parse_celery_decorator(self, decorator: str) -> str:
        """Parse Celery schedule from decorator."""
        # Look for cron or interval
        if 'cron' in decorator:
            return 'cron'
        elif 'interval' in decorator:
            return 'interval'
        return 'task'

    def resolve_import(
        self,
        import_path: str,
        current_file: Path,
        project_root: Path
    ) -> Optional[Path]:
        """Resolve Python import to file path."""
        # Handle relative imports
        if import_path.startswith('.'):
            # Relative to current file
            current_dir = current_file.parent
            parts = import_path.lstrip('.').split('.')

            # Count leading dots for parent traversal
            parent_count = len(import_path) - len(import_path.lstrip('.'))
            for _ in range(parent_count - 1):
                current_dir = current_dir.parent

            # Build path
            module_path = current_dir / '/'.join(parts)
            candidates = [
                module_path.with_suffix('.py'),
                module_path / '__init__.py'
            ]

        else:
            # Absolute import from project root
            parts = import_path.split('.')
            module_path = project_root / '/'.join(parts)
            candidates = [
                module_path.with_suffix('.py'),
                module_path / '__init__.py'
            ]

        # Return first existing candidate
        for candidate in candidates:
            if candidate.exists():
                return candidate

        return None

    def classify_layer(
        self,
        function_name: str,
        file_path: Path,
        has_trigger: bool,
        decorators: List[str] = None
    ) -> str:
        """Classify Python function into layer."""
        path_str = str(file_path).lower()

        # Trigger layer
        if has_trigger:
            return 'trigger'

        # Controller layer
        if any(p in path_str for p in ['controller', 'api', 'handler', 'view', 'endpoint']):
            return 'controller'

        # Service layer
        if any(p in path_str for p in ['service', 'business', 'domain', 'usecase', 'logic']):
            return 'service'

        # Provider/adapter layer
        if any(p in path_str for p in ['provider', 'adapter', 'integration', 'repository', 'dao', 'client']):
            return 'provider'

        # External detection
        external_patterns = ['requests.', 'httpx.', 'aiohttp.', 'firebase_admin.', 'stripe.', 'sendgrid.']
        if decorators and any(any(pattern in dec for pattern in external_patterns) for dec in decorators):
            return 'external'

        # Default to service
        return 'service'

    def format_signature(
        self,
        function_name: str,
        parameters: List[str],
        return_type: Optional[str] = None
    ) -> str:
        """Format Python function signature."""
        params = ', '.join(parameters)
        return_annotation = f" -> {return_type}" if return_type else ""
        return f"{function_name}({params}){return_annotation}"


class JavaScriptAdapter(LanguageAdapter):
    """JavaScript/TypeScript adapter."""

    HTTP_PATTERNS = [
        r'app\.(get|post|put|delete|patch)\(',
        r'router\.(get|post|put|delete|patch)\(',
        r'@(Get|Post|Put|Delete|Patch)\(',  # NestJS
    ]

    def detect_triggers(
        self,
        ast_tree,
        code: str,
        file_path: Path
    ) -> List[TriggerInfo]:
        """Detect triggers in JavaScript code."""
        triggers = []

        # Regex-based for now
        for pattern in self.HTTP_PATTERNS:
            for match in re.finditer(pattern, code):
                method_match = re.search(r'(get|post|put|delete|patch)', match.group(0), re.IGNORECASE)
                method = method_match.group(1).upper() if method_match else 'GET'

                # Look for path in next 50 chars
                context = code[match.start():match.start() + 100]
                path_match = re.search(r'["\']([^"\']+)["\']', context)
                path = path_match.group(1) if path_match else '/'

                # Find function name
                func_match = re.search(r'(?:function\s+(\w+)|(\w+)\s*(?:=|:)\s*(?:async\s+)?(?:function|\([^)]*\)\s*=>))', code[match.end():match.end()+200])
                func_name = (func_match.group(1) or func_match.group(2)) if func_match else 'anonymous'

                triggers.append(TriggerInfo(
                    function_name=func_name,
                    trigger_type='http',
                    metadata={'method': method, 'path': path}
                ))

        return triggers

    def resolve_import(
        self,
        import_path: str,
        current_file: Path,
        project_root: Path
    ) -> Optional[Path]:
        """Resolve JavaScript import to file path."""
        # Relative import
        if import_path.startswith('.'):
            base = current_file.parent
            # Remove ./ or ../
            clean_path = import_path.lstrip('./')

            # Handle parent directory traversal
            parent_count = import_path.count('../')
            for _ in range(parent_count):
                base = base.parent

            # Try different extensions
            for ext in ['.js', '.ts', '.jsx', '.tsx', '/index.js', '/index.ts']:
                candidate = base / (clean_path + ext)
                if candidate.exists():
                    return candidate

        # Absolute from project root (less common)
        else:
            candidate = project_root / import_path
            if candidate.exists():
                return candidate

        return None

    def classify_layer(
        self,
        function_name: str,
        file_path: Path,
        has_trigger: bool,
        decorators: List[str] = None
    ) -> str:
        """Classify JavaScript function into layer."""
        path_str = str(file_path).lower()

        if has_trigger:
            return 'trigger'

        if any(p in path_str for p in ['controller', 'api', 'handler', 'route']):
            return 'controller'

        if any(p in path_str for p in ['service', 'business', 'domain', 'usecase']):
            return 'service'

        if any(p in path_str for p in ['provider', 'adapter', 'integration', 'repository', 'client']):
            return 'provider'

        return 'service'

    def format_signature(
        self,
        function_name: str,
        parameters: List[str],
        return_type: Optional[str] = None
    ) -> str:
        """Format JavaScript function signature."""
        params = ', '.join(parameters)
        return_annotation = f": {return_type}" if return_type else ""
        return f"{function_name}({params}){return_annotation}"


class GoAdapter(LanguageAdapter):
    """Go adapter."""

    HTTP_PATTERNS = [
        r'router\.(GET|POST|PUT|DELETE|PATCH)\(',
        r'http\.HandleFunc\(',
        r'mux\.HandleFunc\(',
    ]

    def detect_triggers(
        self,
        ast_tree,
        code: str,
        file_path: Path
    ) -> List[TriggerInfo]:
        """Detect triggers in Go code."""
        triggers = []

        for pattern in self.HTTP_PATTERNS:
            for match in re.finditer(pattern, code):
                method_match = re.search(r'(GET|POST|PUT|DELETE|PATCH)', match.group(0))
                method = method_match.group(1) if method_match else 'GET'

                # Look for path
                context = code[match.start():match.start() + 150]
                path_match = re.search(r'["\']([^"\']+)["\']', context)
                path = path_match.group(1) if path_match else '/'

                # Find handler function name
                func_match = re.search(r',\s*(\w+)\)', context)
                func_name = func_match.group(1) if func_match else 'handler'

                triggers.append(TriggerInfo(
                    function_name=func_name,
                    trigger_type='http',
                    metadata={'method': method, 'path': path}
                ))

        return triggers

    def resolve_import(
        self,
        import_path: str,
        current_file: Path,
        project_root: Path
    ) -> Optional[Path]:
        """Resolve Go import to file path."""
        # Go uses module paths, harder to resolve without go.mod parsing
        # Simple heuristic: look for matching directory structure
        parts = import_path.split('/')
        if len(parts) > 1:
            # Take last part as directory
            dir_name = parts[-1]
            candidates = list(project_root.rglob(f'{dir_name}/*.go'))
            if candidates:
                return candidates[0]

        return None

    def classify_layer(
        self,
        function_name: str,
        file_path: Path,
        has_trigger: bool,
        decorators: List[str] = None
    ) -> str:
        """Classify Go function into layer."""
        path_str = str(file_path).lower()

        if has_trigger:
            return 'trigger'

        if any(p in path_str for p in ['handler', 'controller', 'api', 'http']):
            return 'controller'

        if any(p in path_str for p in ['service', 'usecase', 'business', 'domain']):
            return 'service'

        if any(p in path_str for p in ['repository', 'repo', 'storage', 'db', 'client']):
            return 'provider'

        return 'service'

    def format_signature(
        self,
        function_name: str,
        parameters: List[str],
        return_type: Optional[str] = None
    ) -> str:
        """Format Go function signature."""
        params = ', '.join(parameters)
        return_annotation = f" {return_type}" if return_type else ""
        return f"func {function_name}({params}){return_annotation}"


class KotlinAdapter(LanguageAdapter):
    """Kotlin adapter."""

    HTTP_ANNOTATIONS = [
        '@GetMapping', '@PostMapping', '@PutMapping', '@DeleteMapping', '@PatchMapping',
        '@RequestMapping'
    ]

    def detect_triggers(
        self,
        ast_tree,
        code: str,
        file_path: Path
    ) -> List[TriggerInfo]:
        """Detect triggers in Kotlin code."""
        triggers = []

        # Detect HTTP endpoints (Spring)
        for annotation in self.HTTP_ANNOTATIONS:
            for match in re.finditer(rf'{annotation}\s*\([^)]*\)', code):
                method_match = re.search(r'(Get|Post|Put|Delete|Patch)', annotation)
                method = method_match.group(1).upper() if method_match else 'GET'

                # Extract path from annotation
                path_match = re.search(r'["\']([^"\']+)["\']', match.group(0))
                path = path_match.group(1) if path_match else '/'

                # Find function name after annotation
                func_match = re.search(r'fun\s+(\w+)', code[match.end():match.end()+200])
                func_name = func_match.group(1) if func_match else 'handler'

                triggers.append(TriggerInfo(
                    function_name=func_name,
                    trigger_type='http',
                    metadata={'method': method, 'path': path, 'annotation': annotation}
                ))

        # Detect gRPC service methods (Kotlin Coroutines)
        # Pattern: class ServiceName(...) : SomeServiceCoroutineImplBase()
        grpc_class_pattern = r'class\s+(\w+)\s*\([^)]*\)\s*:\s*([\w.]+CoroutineImplBase)\(\)'
        for class_match in re.finditer(grpc_class_pattern, code):
            class_name = class_match.group(1)
            base_class = class_match.group(2)

            # Extract service name from base class (e.g., "ConfigServiceGrpcKt.ConfigServiceCoroutineImplBase" -> "ConfigService")
            service_match = re.search(r'(\w+)(?:Grpc)?(?:Kt)?\.?(\w+)?CoroutineImplBase', base_class)
            service_name = service_match.group(1) if service_match else class_name

            # Find the class body (everything until the next top-level class or end of file)
            class_start = class_match.end()
            # Find matching closing brace for class body
            brace_count = 0
            class_end = class_start
            found_open = False
            for i in range(class_start, len(code)):
                if code[i] == '{':
                    brace_count += 1
                    found_open = True
                elif code[i] == '}':
                    brace_count -= 1
                    if found_open and brace_count == 0:
                        class_end = i
                        break

            class_body = code[class_start:class_end]

            # Find all override suspend fun methods in this class
            method_pattern = r'override\s+suspend\s+fun\s+(\w+)\s*\('
            for method_match in re.finditer(method_pattern, class_body):
                method_name = method_match.group(1)

                triggers.append(TriggerInfo(
                    function_name=method_name,
                    trigger_type='grpc',
                    metadata={'service': service_name, 'method': method_name, 'class': class_name}
                ))

        return triggers

    def resolve_import(
        self,
        import_path: str,
        current_file: Path,
        project_root: Path
    ) -> Optional[Path]:
        """Resolve Kotlin import to file path."""
        # Kotlin uses package structure
        parts = import_path.split('.')
        # Convert package to file path
        file_path = project_root / 'src' / 'main' / 'kotlin' / '/'.join(parts[:-1]) / f'{parts[-1]}.kt'
        if file_path.exists():
            return file_path

        return None

    def classify_layer(
        self,
        function_name: str,
        file_path: Path,
        has_trigger: bool,
        decorators: List[str] = None
    ) -> str:
        """Classify Kotlin function into layer."""
        path_str = str(file_path).lower()

        if has_trigger:
            return 'trigger'

        # Check for Spring annotations
        if decorators:
            if any('@Controller' in d or '@RestController' in d for d in decorators):
                return 'controller'
            if any('@Service' in d for d in decorators):
                return 'service'
            if any('@Repository' in d for d in decorators):
                return 'provider'

        # Fallback to path-based
        if any(p in path_str for p in ['controller', 'api', 'handler']):
            return 'controller'

        if any(p in path_str for p in ['service', 'usecase', 'business']):
            return 'service'

        if any(p in path_str for p in ['repository', 'dao', 'client']):
            return 'provider'

        return 'service'

    def format_signature(
        self,
        function_name: str,
        parameters: List[str],
        return_type: Optional[str] = None
    ) -> str:
        """Format Kotlin function signature."""
        params = ', '.join(parameters)
        return_annotation = f": {return_type}" if return_type else ""
        return f"fun {function_name}({params}){return_annotation}"


# Factory function
def get_language_adapter(language: str) -> Optional[LanguageAdapter]:
    """
    Get appropriate language adapter.

    Args:
        language: Language name (python, javascript, go, kotlin, etc.)

    Returns:
        LanguageAdapter instance or None
    """
    language = language.lower()

    adapters = {
        'python': PythonAdapter,
        'py': PythonAdapter,
        'javascript': JavaScriptAdapter,
        'js': JavaScriptAdapter,
        'typescript': JavaScriptAdapter,
        'ts': JavaScriptAdapter,
        'tsx': JavaScriptAdapter,
        'jsx': JavaScriptAdapter,
        'go': GoAdapter,
        'kotlin': KotlinAdapter,
        'kt': KotlinAdapter,
    }

    adapter_class = adapters.get(language)
    return adapter_class() if adapter_class else None
