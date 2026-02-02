"""Enhanced indexer with two-pass call graph construction.

Two-Pass Architecture:
1. Pass 1 (Structural): AST parsing for call graph extraction
2. Pass 2 (Semantic): LLM enrichment with descriptions

Stores in dual storage:
- ChromaDB: Semantic search
- SQLite: Graph traversal
"""

import asyncio
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

from ..config import Config
from ..providers.base import LLMProvider, EmbeddingProvider
from ..storage.chroma_client import ChromaManager
from ..storage.call_graph_store import CallGraphStore
from ..storage.models import IndexedDocument, ProjectContext
from ..utils.logger import get_logger
from ..utils.rate_limiter import RateLimiter

from .ast_analyzer import ASTAnalyzer, FunctionDefinition, FunctionCall, CallGraph
from .scanner import scan_project
from .context_analyzer import analyze_project_context
from .trigger_detector import TriggerDetector
from .layer_classifier import LayerClassifier
from .call_resolver import CallResolver
from .language_adapters import get_language_adapter
from ..utils.file_types import detect_language

logger = get_logger(__name__)


class EnhancedIndexManager:
    """
    Enhanced indexing manager with call graph support.

    Implements two-pass indexing:
    - Pass 1: Fast structural analysis (AST only)
    - Pass 2: Semantic enrichment (LLM descriptions)
    """

    def __init__(
        self,
        config: Config,
        chroma: ChromaManager,
        graph_store: CallGraphStore,
        llm_provider: LLMProvider,
        embedding_provider: EmbeddingProvider,
        rate_limiter: RateLimiter
    ):
        """
        Initialize enhanced index manager.

        Args:
            config: Configuration
            chroma: ChromaDB manager for semantic search
            graph_store: SQLite call graph store for graph traversal
            llm_provider: LLM for semantic analysis
            embedding_provider: Embedding provider
            rate_limiter: Rate limiter for API calls
        """
        self.config = config
        self.chroma = chroma
        self.graph_store = graph_store
        self.llm_provider = llm_provider
        self.embedding_provider = embedding_provider
        self.rate_limiter = rate_limiter

        # Analyzers
        self.ast_analyzer = ASTAnalyzer()
        self.trigger_detector = TriggerDetector()
        self.layer_classifier = LayerClassifier()

    async def index_project_with_call_graph(
        self,
        project_path: Path,
        force_reindex: bool = False
    ) -> Dict[str, Any]:
        """
        Index project with call graph construction.

        Args:
            project_path: Root path of project
            force_reindex: Force reindex even if already indexed

        Returns:
            Indexing statistics
        """
        start_time = time.time()
        logger.info(f"Starting enhanced indexing with call graph: {project_path}")

        # Check if already indexed
        if not force_reindex and self.graph_store.has_project(str(project_path)):
            logger.info("Project already indexed. Use force_reindex=True to reindex.")
            stats = self.graph_store.get_statistics(str(project_path))
            stats['status'] = 'already_indexed'
            return stats

        # Clear existing data if force reindex
        if force_reindex:
            logger.info("Force reindex: clearing existing data")
            self.graph_store.clear_project(str(project_path))

        stats = {
            'project_path': str(project_path),
            'total_files': 0,
            'indexed_files': 0,
            'failed_files': 0,
            'total_functions': 0,
            'total_calls': 0,
            'entry_points': 0,
            'pass1_duration': 0,
            'pass2_duration': 0,
            'total_duration': 0,
            'layer_distribution': {},
            'trigger_types': {}
        }

        try:
            # Step 0: Analyze project context
            logger.info("Step 0: Analyzing project context")
            project_context = await self._analyze_project_context(project_path)

            # Step 1: Scan project files
            logger.info("Step 1: Scanning project files")
            files = await scan_project(
                project_path,
                self.config.patterns.include,
                self.config.patterns.exclude
            )
            stats['total_files'] = len(files)
            logger.info(f"Found {len(files)} files to index")

            # PASS 1: Structural Analysis (AST only)
            logger.info("=" * 60)
            logger.info("PASS 1: Structural Analysis (AST parsing)")
            logger.info("=" * 60)
            pass1_start = time.time()

            all_functions = []
            all_calls = []
            imports_by_file = {}
            functions_by_file = {}

            for file_metadata in files:
                try:
                    # Extract actual file path from FileMetadata
                    file_path = file_metadata.file_path

                    result = await self._analyze_file_structure(
                        file_path,
                        project_path,
                        project_context
                    )

                    if result:
                        all_functions.extend(result['functions'])
                        all_calls.extend(result['calls'])
                        imports_by_file[result['file_path']] = result['imports']
                        functions_by_file[result['file_path']] = result['func_defs']
                        stats['indexed_files'] += 1

                except Exception as e:
                    logger.error(f"Failed to analyze {file_metadata.file_path}: {e}")
                    stats['failed_files'] += 1

            stats['pass1_duration'] = time.time() - pass1_start
            stats['total_functions'] = len(all_functions)
            logger.info(f"Pass 1 complete: {stats['total_functions']} functions, {len(all_calls)} calls")

            # Resolve cross-file calls
            logger.info("Resolving cross-file calls...")
            call_resolver = CallResolver(
                project_path,
                functions_by_file,
                imports_by_file
            )

            resolved_calls = []
            for file_path, calls in imports_by_file.items():
                # Get language for this file
                language = detect_language(Path(file_path))
                if language:
                    file_calls = [c for c in all_calls if c.get('file_path') == file_path]
                    call_objs = [FunctionCall(
                        caller_function=c['caller_function'],
                        callee_name=c['callee_name'],
                        line_number=c['line_number'],
                        arguments=c.get('arguments', []),
                        module=c.get('module')
                    ) for c in file_calls]

                    resolved = call_resolver.resolve_calls(file_path, call_objs, language)
                    resolved_calls.extend([{
                        'caller_id': r.caller_id,
                        'callee_id': r.callee_id,
                        'caller_line': r.caller_line,
                        'arguments': r.arguments
                    } for r in resolved])

            stats['total_calls'] = len(resolved_calls)
            logger.info(f"Resolved {len(resolved_calls)} cross-file calls")

            # PASS 2: Semantic Enrichment (LLM)
            logger.info("=" * 60)
            logger.info("PASS 2: Semantic Enrichment (LLM descriptions)")
            logger.info("=" * 60)
            pass2_start = time.time()

            # Batch functions for LLM analysis
            batch_size = 20
            enriched_functions = []

            for i in range(0, len(all_functions), batch_size):
                batch = all_functions[i:i + batch_size]
                logger.info(f"Enriching batch {i // batch_size + 1}/{(len(all_functions) + batch_size - 1) // batch_size}")

                descriptions = await self._generate_batch_descriptions(batch)

                for j, func_data in enumerate(batch):
                    func_data['description'] = descriptions[j] if j < len(descriptions) else None
                    enriched_functions.append(func_data)

            stats['pass2_duration'] = time.time() - pass2_start
            logger.info(f"Pass 2 complete: enriched {len(enriched_functions)} functions")

            # Save to SQLite (graph store)
            logger.info("Saving to SQLite call graph store...")
            self.graph_store.save_functions(str(project_path), enriched_functions)
            self.graph_store.save_calls(str(project_path), resolved_calls)

            # Save to ChromaDB (semantic search)
            logger.info("Saving to ChromaDB for semantic search...")
            await self._save_to_chroma(enriched_functions, resolved_calls, project_path)

            # Compute statistics
            layer_dist = {}
            trigger_types = {}
            for func in enriched_functions:
                layer = func.get('layer', 'unknown')
                layer_dist[layer] = layer_dist.get(layer, 0) + 1

                if func.get('is_entry_point'):
                    stats['entry_points'] += 1
                    trigger_type = func.get('trigger_type', 'unknown')
                    trigger_types[trigger_type] = trigger_types.get(trigger_type, 0) + 1

            stats['layer_distribution'] = layer_dist
            stats['trigger_types'] = trigger_types
            stats['total_duration'] = time.time() - start_time
            stats['status'] = 'success'

            logger.info("=" * 60)
            logger.info("Indexing complete!")
            logger.info(f"Total duration: {stats['total_duration']:.2f}s")
            logger.info(f"Functions: {stats['total_functions']}")
            logger.info(f"Calls: {stats['total_calls']}")
            logger.info(f"Entry points: {stats['entry_points']}")
            logger.info(f"Layers: {stats['layer_distribution']}")
            logger.info("=" * 60)

            return stats

        except Exception as e:
            logger.error(f"Indexing failed: {e}", exc_info=True)
            stats['status'] = 'error'
            stats['error'] = str(e)
            stats['total_duration'] = time.time() - start_time
            return stats

    async def _analyze_project_context(self, project_path: Path) -> Optional[ProjectContext]:
        """Analyze project context."""
        try:
            return await self.rate_limiter.execute_with_retry(
                lambda: analyze_project_context(project_path, self.llm_provider)
            )
        except Exception as e:
            logger.warning(f"Failed to analyze project context: {e}")
            return None

    async def _analyze_file_structure(
        self,
        file_path: Path,
        project_path: Path,
        project_context: Optional[ProjectContext]
    ) -> Optional[Dict[str, Any]]:
        """
        Analyze file structure (Pass 1).

        Returns dict with:
        - functions: List of function metadata
        - calls: List of call metadata
        - imports: List of imports
        - func_defs: List of FunctionDefinition objects
        """
        # Read file
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                code = f.read()
        except Exception as e:
            logger.debug(f"Could not read {file_path}: {e}")
            return None

        # Detect language
        language = detect_language(file_path)
        if not language:
            logger.debug(f"Could not detect language for {file_path}")
            return None

        logger.debug(f"Analyzing {file_path.name} as {language}")

        # Parse AST
        call_graph = self.ast_analyzer.analyze_file(file_path, language, code)
        if not call_graph:
            logger.warning(f"AST analysis returned None for {file_path.name} (language: {language})")
            return None

        logger.debug(f"Found {len(call_graph.functions)} functions in {file_path.name}")

        # Detect triggers
        ast_tree = None
        if self.ast_analyzer.tree_sitter_available and language in self.ast_analyzer.parsers:
            parser = self.ast_analyzer.parsers.get(self.ast_analyzer._normalize_language(language))
            if parser:
                ast_tree = parser.parse(bytes(code, "utf8"))

        triggers = self.trigger_detector.detect_triggers(file_path, ast_tree, code, language)
        trigger_map = {t.function_name: t for t in triggers}

        # Process functions
        rel_path = str(file_path.relative_to(project_path))
        functions = []

        for func_def in call_graph.functions:
            trigger_info = trigger_map.get(func_def.name)
            has_trigger = trigger_info is not None

            # Classify layer
            layer = self.layer_classifier.classify(
                func_def.name,
                file_path,
                language,
                has_trigger
            )

            functions.append({
                'file_path': rel_path,
                'func_def': func_def,
                'layer': layer,
                'is_entry_point': has_trigger,
                'trigger_type': trigger_info.trigger_type if trigger_info else None,
                'trigger_metadata': trigger_info.metadata if trigger_info else None
            })

        # Process calls
        calls = []
        for call in call_graph.calls:
            calls.append({
                'file_path': rel_path,
                'caller_function': call.caller_function,
                'callee_name': call.callee_name,
                'line_number': call.line_number,
                'arguments': call.arguments,
                'module': call.module
            })

        return {
            'file_path': rel_path,
            'functions': functions,
            'calls': calls,
            'imports': call_graph.imports,
            'func_defs': call_graph.functions
        }

    async def _generate_batch_descriptions(self, batch: List[Dict]) -> List[str]:
        """Generate descriptions for batch of functions using LLM."""
        if not batch:
            return []

        # Build prompt
        functions_text = []
        for i, func_data in enumerate(batch):
            func_def = func_data['func_def']
            signature = f"{func_def.name}({', '.join(func_def.parameters)})"
            functions_text.append(f"{i + 1}. {signature} in {func_data['file_path']} (layer: {func_data['layer']})")

        prompt = f"""Analyze the following functions and provide a brief description (1 sentence) for each:

{chr(10).join(functions_text)}

Return as JSON array of strings: ["description1", "description2", ...]
Keep descriptions concise and focus on the function's purpose."""

        try:
            from ..providers.base import ChatMessage
            import json

            # Define JSON schema for response
            schema = {
                "name": "function_descriptions",
                "schema": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Array of function descriptions"
                }
            }

            response = await self.rate_limiter.execute_with_retry(
                lambda: self.llm_provider.chat_completion(
                    messages=[
                        ChatMessage(role="system", content="You are a code analyst."),
                        ChatMessage(role="user", content=prompt)
                    ],
                    response_format={"type": "json_schema", "json_schema": schema}
                )
            )

            descriptions = json.loads(response.content)

            if not isinstance(descriptions, list):
                descriptions = [str(descriptions)] * len(batch)

            # Pad if needed
            while len(descriptions) < len(batch):
                descriptions.append("Function implementation")

            return descriptions[:len(batch)]

        except Exception as e:
            logger.warning(f"Failed to generate descriptions: {e}")
            return ["Function implementation" for _ in batch]

    async def _save_to_chroma(
        self,
        functions: List[Dict],
        calls: List[Dict],
        project_path: Path
    ):
        """Save functions and calls to ChromaDB for semantic search."""
        documents = []

        # Save functions
        for func_data in functions:
            func_def = func_data['func_def']

            # Format text for embedding
            text_parts = [
                f"Function: {func_def.name}",
                f"File: {func_data['file_path']}",
                f"Layer: {func_data['layer']}",
            ]

            if func_data.get('description'):
                text_parts.append(f"Description: {func_data['description']}")

            if func_data.get('trigger_type'):
                trigger_meta = func_data.get('trigger_metadata', {})
                text_parts.append(f"Trigger: {func_data['trigger_type']} - {trigger_meta}")

            text = "\n".join(text_parts)

            # Generate embedding
            try:
                embedding = await self.rate_limiter.execute_with_retry(
                    lambda: self.embedding_provider.create_embedding(text)
                )

                func_id = f"{func_data['file_path']}::{func_def.name}::{func_def.line_number}"

                doc = IndexedDocument(
                    id=func_id,
                    content=text,
                    embedding=embedding,  # embedding is already a List[float]
                    metadata={
                        'type': 'function',
                        'function_id': func_id,
                        'function_name': func_def.name,
                        'file_path': func_data['file_path'],
                        'layer': func_data['layer'],
                        'is_entry_point': func_data.get('is_entry_point', False),
                        'trigger_type': func_data.get('trigger_type', ''),
                        'project_path': str(project_path)
                    }
                )
                documents.append(doc)

            except Exception as e:
                logger.warning(f"Failed to generate embedding for {func_def.name}: {e}")

        # Save to ChromaDB
        if documents:
            collection = self.chroma.get_or_create_collection(project_path)
            await self.chroma.add_documents(collection, documents)
            logger.info(f"Saved {len(documents)} function embeddings to ChromaDB")
