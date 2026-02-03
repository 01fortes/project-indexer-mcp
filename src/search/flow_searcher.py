"""Flow searcher for tracing code execution paths from triggers to external APIs.

Combines:
- ChromaDB: Semantic search to find relevant entry points
- SQLite: Graph traversal to build complete call stacks
"""

from pathlib import Path
from typing import Dict, List, Optional, Any
from collections import defaultdict

from ..providers.base import EmbeddingProvider
from ..storage.chroma_client import ChromaManager
from ..storage.call_graph_store import CallGraphStore
from ..utils.logger import get_logger

logger = get_logger(__name__)


class FlowSearcher:
    """
    Searches and traces code execution flows.

    Workflow:
    1. Semantic search in ChromaDB for relevant entry points
    2. Build call stacks through SQLite graph traversal
    3. Group by architectural layers
    4. Format for display
    """

    def __init__(
        self,
        chroma: ChromaManager,
        graph_store: CallGraphStore,
        embedding_provider: EmbeddingProvider
    ):
        """
        Initialize flow searcher.

        Args:
            chroma: ChromaDB manager for semantic search
            graph_store: SQLite graph store for traversal
            embedding_provider: Embedding provider
        """
        self.chroma = chroma
        self.graph_store = graph_store
        self.embedding_provider = embedding_provider

    async def search_flows(
        self,
        project_path: Path,
        query: str,
        max_depth: int = 10,
        max_flows: int = 10
    ) -> Dict[str, Any]:
        """
        Search for code flows matching query.

        Args:
            project_path: Root path of project
            query: Natural language query (e.g., "How is notification sent?")
            max_depth: Maximum call stack depth
            max_flows: Maximum number of flows to return

        Returns:
            Dict with query results and flows
        """
        logger.info(f"Searching flows for: {query}")

        # Step 1: Generate query embedding
        logger.info("Step 1: Generating query embedding")
        query_embedding = await self.embedding_provider.create_embedding(query)

        # Step 2: Search ChromaDB for relevant entry points
        logger.info("Step 2: Searching for relevant entry points")
        collection = self.chroma.get_or_create_collection(project_path)
        search_results = await self.chroma.search(
            collection=collection,
            query_embedding=query_embedding,
            n_results=50,  # Get more candidates
            metadata_filter={'type': 'function'}  # Only functions
        )

        # Filter to entry points only
        entry_point_ids = []
        for result in search_results:
            metadata = result.metadata
            if metadata.get('is_entry_point') and metadata.get('project_path') == str(project_path):
                entry_point_ids.append(metadata.get('function_id'))

        logger.info(f"Found {len(entry_point_ids)} entry point candidates")

        if not entry_point_ids:
            return {
                'query': query,
                'found_flows': 0,
                'flows': [],
                'message': 'No entry points found matching query'
            }

        # Step 3: Build flows for each entry point
        logger.info("Step 3: Building call stacks")
        flows = []

        for entry_id in entry_point_ids[:max_flows]:
            try:
                flow = await self._build_flow(entry_id, max_depth, project_path)
                if flow:
                    flows.append(flow)
            except Exception as e:
                logger.warning(f"Failed to build flow for {entry_id}: {e}")

        logger.info(f"Built {len(flows)} complete flows")

        return {
            'query': query,
            'found_flows': len(flows),
            'flows': flows
        }

    async def _build_flow(
        self,
        entry_point_id: str,
        max_depth: int,
        project_path: Path
    ) -> Optional[Dict[str, Any]]:
        """
        Build complete flow from entry point.

        Args:
            entry_point_id: Entry point function ID
            max_depth: Maximum traversal depth
            project_path: Project root path

        Returns:
            Flow dict with layers and call stack
        """
        # Get entry point function
        entry_func = self.graph_store.get_function(entry_point_id)
        if not entry_func:
            return None

        # Build call stack using DFS
        call_stack = self.graph_store.build_call_stack(
            entry_point_id,
            max_depth
        )

        if not call_stack:
            return None

        # Group by layers
        layers = self._group_by_layers(call_stack)

        # Format trigger info
        trigger = self._format_trigger(entry_func)

        # Generate flow name
        flow_name = self._generate_flow_name(entry_func, layers)

        return {
            'flow_id': entry_point_id,
            'flow_name': flow_name,
            'trigger': trigger,
            'layers': layers,
            'full_call_stack': self._format_call_stack(call_stack),
            'depth': self._calculate_depth(call_stack),
            'function_count': self._count_functions(call_stack)
        }

    def _group_by_layers(self, call_stack: List[Dict]) -> List[Dict[str, Any]]:
        """
        Group call stack by architectural layers.

        Args:
            call_stack: Raw call stack from graph traversal

        Returns:
            List of layer dicts with functions
        """
        layers_map = defaultdict(list)

        def traverse(stack_item, depth=0):
            func = stack_item.get('function', {})
            layer = func.get('layer', 'unknown')

            # Add function to layer
            layers_map[layer].append({
                'function_name': func.get('function_name'),
                'file_path': func.get('file_path'),
                'line_number': func.get('line_number'),
                'signature': func.get('signature'),
                'depth': depth,
                'description': func.get('description')
            })

            # Recurse into calls
            for call_info in stack_item.get('calls', []):
                sub_stack = call_info.get('sub_stack', [])
                for sub_item in sub_stack:
                    traverse(sub_item, depth + 1)

        for item in call_stack:
            traverse(item)

        # Order layers by typical architecture
        layer_order = ['trigger', 'controller', 'service', 'provider', 'external']
        layers = []

        for layer_name in layer_order:
            if layer_name in layers_map:
                layers.append({
                    'layer': layer_name,
                    'functions': layers_map[layer_name]
                })

        # Add any remaining layers
        for layer_name, functions in layers_map.items():
            if layer_name not in layer_order:
                layers.append({
                    'layer': layer_name,
                    'functions': functions
                })

        return layers

    def _format_trigger(self, func: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format trigger information.

        Args:
            func: Function record

        Returns:
            Trigger info dict
        """
        trigger_type = func.get('trigger_type', 'unknown')

        import json
        trigger_metadata = {}
        if func.get('trigger_metadata'):
            try:
                trigger_metadata = json.loads(func['trigger_metadata'])
            except:
                pass

        result = {
            'type': trigger_type,
            'function_name': func.get('function_name'),
            'file_path': func.get('file_path'),
            'line_number': func.get('line_number')
        }

        # Add type-specific info
        if trigger_type == 'http':
            result['method'] = trigger_metadata.get('method', 'GET')
            result['path'] = trigger_metadata.get('path', '/')
            result['display'] = f"HTTP {result['method']} {result['path']}"

        elif trigger_type == 'kafka':
            result['topic'] = trigger_metadata.get('topic', 'unknown')
            result['display'] = f"Kafka Consumer: {result['topic']}"

        elif trigger_type == 'scheduled':
            result['schedule'] = trigger_metadata.get('schedule', 'unknown')
            result['display'] = f"Scheduled Task: {result['schedule']}"

        elif trigger_type == 'grpc':
            result['method'] = trigger_metadata.get('method', 'unknown')
            result['display'] = f"gRPC: {result['method']}"

        elif trigger_type == 'websocket':
            result['path'] = trigger_metadata.get('path', '/')
            result['display'] = f"WebSocket: {result['path']}"

        else:
            result['display'] = f"{trigger_type}: {func.get('function_name')}"

        return result

    def _format_call_stack(self, call_stack: List[Dict]) -> List[str]:
        """
        Format call stack as list of strings for display.

        Args:
            call_stack: Raw call stack

        Returns:
            List of formatted call strings
        """
        lines = []

        def traverse(stack_item, depth=0):
            func = stack_item.get('function', {})
            indent = "  " * depth

            # Format function line
            func_name = func.get('function_name', 'unknown')
            file_path = func.get('file_path', '')
            line_num = func.get('line_number', 0)
            layer = func.get('layer', 'unknown')

            line = f"{indent}[{layer}] {func_name}() at {file_path}:{line_num}"
            lines.append(line)

            # Recurse into calls
            for call_info in stack_item.get('calls', []):
                sub_stack = call_info.get('sub_stack', [])
                for sub_item in sub_stack:
                    traverse(sub_item, depth + 1)

        for item in call_stack:
            traverse(item)

        return lines

    def _generate_flow_name(self, entry_func: Dict, layers: List[Dict]) -> str:
        """
        Generate descriptive flow name.

        Args:
            entry_func: Entry point function
            layers: Layers in flow

        Returns:
            Flow name string
        """
        trigger_type = entry_func.get('trigger_type', 'unknown')
        func_name = entry_func.get('function_name', 'unknown')

        layer_names = [l['layer'] for l in layers]
        layer_str = ' → '.join(layer_names)

        return f"{trigger_type.upper()}: {func_name}() → {layer_str}"

    def _calculate_depth(self, call_stack: List[Dict]) -> int:
        """Calculate maximum depth of call stack."""
        max_depth = 0

        def traverse(stack_item, depth=0):
            nonlocal max_depth
            max_depth = max(max_depth, depth)

            for call_info in stack_item.get('calls', []):
                sub_stack = call_info.get('sub_stack', [])
                for sub_item in sub_stack:
                    traverse(sub_item, depth + 1)

        for item in call_stack:
            traverse(item)

        return max_depth

    def _count_functions(self, call_stack: List[Dict]) -> int:
        """Count total functions in call stack."""
        count = 0

        def traverse(stack_item):
            nonlocal count
            count += 1

            for call_info in stack_item.get('calls', []):
                sub_stack = call_info.get('sub_stack', [])
                for sub_item in sub_stack:
                    traverse(sub_item)

        for item in call_stack:
            traverse(item)

        return count
