"""Trigger detection for identifying entry points in codebases.

Detects various types of triggers:
- HTTP endpoints (REST APIs)
- gRPC methods
- Kafka consumers
- Scheduled jobs
- WebSocket handlers
- GraphQL resolvers
"""

from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass

from .language_adapters import get_language_adapter, TriggerInfo
from ..utils.logger import get_logger

logger = get_logger(__name__)


class TriggerDetector:
    """
    Detects entry point triggers across multiple languages.

    Uses language-specific adapters to identify different trigger types.
    """

    def __init__(self):
        """Initialize trigger detector."""
        pass

    def detect_triggers(
        self,
        file_path: Path,
        ast_tree,
        code: str,
        language: str
    ) -> List[TriggerInfo]:
        """
        Detect all triggers in a file.

        Args:
            file_path: Path to file
            ast_tree: Tree-sitter AST (optional)
            code: Source code
            language: Programming language

        Returns:
            List of detected triggers
        """
        adapter = get_language_adapter(language)
        if not adapter:
            logger.debug(f"No adapter for language: {language}")
            return []

        try:
            triggers = adapter.detect_triggers(ast_tree, code, file_path)
            logger.debug(f"Detected {len(triggers)} triggers in {file_path}")
            return triggers
        except Exception as e:
            logger.error(f"Failed to detect triggers in {file_path}: {e}")
            return []

    def is_http_endpoint(self, trigger_info: TriggerInfo) -> bool:
        """Check if trigger is an HTTP endpoint."""
        return trigger_info.trigger_type == 'http'

    def is_grpc_method(self, trigger_info: TriggerInfo) -> bool:
        """Check if trigger is a gRPC method."""
        return trigger_info.trigger_type == 'grpc'

    def is_kafka_consumer(self, trigger_info: TriggerInfo) -> bool:
        """Check if trigger is a Kafka consumer."""
        return trigger_info.trigger_type == 'kafka'

    def is_scheduled_job(self, trigger_info: TriggerInfo) -> bool:
        """Check if trigger is a scheduled job."""
        return trigger_info.trigger_type == 'scheduled'

    def is_websocket_handler(self, trigger_info: TriggerInfo) -> bool:
        """Check if trigger is a WebSocket handler."""
        return trigger_info.trigger_type == 'websocket'

    def is_graphql_resolver(self, trigger_info: TriggerInfo) -> bool:
        """Check if trigger is a GraphQL resolver."""
        return trigger_info.trigger_type == 'graphql'

    def get_trigger_summary(self, triggers: List[TriggerInfo]) -> Dict[str, int]:
        """
        Get summary of triggers by type.

        Args:
            triggers: List of triggers

        Returns:
            Dict mapping trigger type to count
        """
        summary = {}
        for trigger in triggers:
            trigger_type = trigger.trigger_type
            summary[trigger_type] = summary.get(trigger_type, 0) + 1
        return summary

    def format_trigger_display(self, trigger: TriggerInfo) -> str:
        """
        Format trigger for human-readable display.

        Args:
            trigger: Trigger info

        Returns:
            Formatted string
        """
        if trigger.trigger_type == 'http':
            method = trigger.metadata.get('method', 'GET')
            path = trigger.metadata.get('path', '/')
            return f"HTTP {method} {path} → {trigger.function_name}()"

        elif trigger.trigger_type == 'kafka':
            topic = trigger.metadata.get('topic', 'unknown')
            return f"Kafka Consumer '{topic}' → {trigger.function_name}()"

        elif trigger.trigger_type == 'scheduled':
            schedule = trigger.metadata.get('schedule', 'unknown')
            return f"Scheduled Task ({schedule}) → {trigger.function_name}()"

        elif trigger.trigger_type == 'grpc':
            method = trigger.metadata.get('method', 'unknown')
            return f"gRPC {method} → {trigger.function_name}()"

        elif trigger.trigger_type == 'websocket':
            path = trigger.metadata.get('path', '/')
            return f"WebSocket {path} → {trigger.function_name}()"

        elif trigger.trigger_type == 'graphql':
            return f"GraphQL Resolver → {trigger.function_name}()"

        else:
            return f"{trigger.trigger_type} → {trigger.function_name}()"
