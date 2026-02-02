"""Layer classification for architectural analysis.

Classifies functions into layers:
- trigger: Entry points (HTTP endpoints, Kafka consumers, etc.)
- controller: Request handlers and API controllers
- service: Business logic and domain services
- provider: External integrations and data access
- external: Third-party API calls
"""

from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass

from .language_adapters import get_language_adapter
from ..utils.logger import get_logger

logger = get_logger(__name__)


class LayerClassifier:
    """
    Classifies functions into architectural layers.

    Uses heuristics based on:
    - File/directory naming conventions
    - Decorators and annotations
    - Import patterns
    - Function names
    """

    # External library patterns
    EXTERNAL_PATTERNS = {
        'python': [
            'requests.', 'httpx.', 'aiohttp.',
            'firebase_admin.', 'boto3.', 'google.cloud.',
            'stripe.', 'sendgrid.', 'twilio.',
            'pymongo.', 'psycopg2.', 'redis.',
        ],
        'javascript': [
            'axios.', 'fetch(',
            'firebase.', 'aws-sdk',
            'stripe.', '@sendgrid',
            'mongoose.', 'pg.', 'redis.',
        ],
        'go': [
            'http.Client', 'grpc.Dial',
            'firebase.', 'aws.',
            'stripe.', 'sendgrid.',
            'mongo.', 'sql.', 'redis.',
        ],
        'kotlin': [
            'RestTemplate', 'WebClient',
            'FirebaseApp', 'AmazonS3',
            'Stripe', 'SendGrid',
            'MongoTemplate', 'JdbcTemplate',
        ]
    }

    def __init__(self):
        """Initialize layer classifier."""
        pass

    def classify(
        self,
        function_name: str,
        file_path: Path,
        language: str,
        has_trigger: bool,
        decorators: Optional[List[str]] = None,
        imports: Optional[List[str]] = None
    ) -> str:
        """
        Classify function into architectural layer.

        Args:
            function_name: Name of function
            file_path: Path to file containing function
            language: Programming language
            has_trigger: Whether function has a trigger decorator/annotation
            decorators: List of decorators/annotations
            imports: List of imports used in function

        Returns:
            Layer name: trigger/controller/service/provider/external
        """
        # Use language adapter if available
        adapter = get_language_adapter(language)
        if adapter:
            return adapter.classify_layer(
                function_name,
                file_path,
                has_trigger,
                decorators
            )

        # Fallback to generic classification
        return self._generic_classify(
            function_name,
            file_path,
            has_trigger,
            decorators,
            imports,
            language
        )

    def _generic_classify(
        self,
        function_name: str,
        file_path: Path,
        has_trigger: bool,
        decorators: Optional[List[str]],
        imports: Optional[List[str]],
        language: str
    ) -> str:
        """Generic classification based on common patterns."""
        path_str = str(file_path).lower()

        # Trigger layer - highest priority
        if has_trigger:
            return 'trigger'

        # Check for external API calls
        if self._uses_external_api(imports or [], language):
            return 'external'

        # Controller patterns
        controller_patterns = [
            'controller', 'controllers',
            'api', 'apis',
            'handler', 'handlers',
            'endpoint', 'endpoints',
            'view', 'views',
            'route', 'routes'
        ]
        if any(pattern in path_str for pattern in controller_patterns):
            return 'controller'

        # Service patterns
        service_patterns = [
            'service', 'services',
            'business',
            'domain',
            'usecase', 'usecases',
            'logic',
            'core'
        ]
        if any(pattern in path_str for pattern in service_patterns):
            return 'service'

        # Provider patterns
        provider_patterns = [
            'provider', 'providers',
            'adapter', 'adapters',
            'integration', 'integrations',
            'repository', 'repositories',
            'dao',
            'client', 'clients',
            'gateway', 'gateways',
            'connector', 'connectors',
            'storage',
            'database', 'db'
        ]
        if any(pattern in path_str for pattern in provider_patterns):
            return 'provider'

        # Function name patterns
        if any(prefix in function_name.lower() for prefix in ['fetch', 'get', 'load', 'find', 'query']):
            # Likely data access
            return 'provider'

        # Default to service layer
        return 'service'

    def _uses_external_api(self, imports: List[str], language: str) -> bool:
        """Check if function uses external API libraries."""
        if not imports:
            return False

        external_patterns = self.EXTERNAL_PATTERNS.get(language.lower(), [])

        for imp in imports:
            for pattern in external_patterns:
                if pattern in imp:
                    return True

        return False

    def get_layer_description(self, layer: str) -> str:
        """
        Get human-readable description of layer.

        Args:
            layer: Layer name

        Returns:
            Description string
        """
        descriptions = {
            'trigger': 'Entry point that triggers code execution (HTTP, Kafka, scheduled, etc.)',
            'controller': 'Request handler that processes inputs and coordinates responses',
            'service': 'Business logic and domain operations',
            'provider': 'Data access and external service integration',
            'external': 'Direct third-party API call'
        }
        return descriptions.get(layer, 'Unknown layer')

    def get_layer_color(self, layer: str) -> str:
        """
        Get color code for layer visualization.

        Args:
            layer: Layer name

        Returns:
            Color code (for terminal output or visualization)
        """
        colors = {
            'trigger': '\033[92m',      # Green
            'controller': '\033[94m',   # Blue
            'service': '\033[93m',      # Yellow
            'provider': '\033[95m',     # Magenta
            'external': '\033[91m'      # Red
        }
        return colors.get(layer, '\033[0m')  # Default: reset
