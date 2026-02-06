"""Function Index Manager (Index 3) - Extracts and indexes functions via AST + LLM."""

import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import Config
from ..providers.base import ChatMessage, EmbeddingProvider, LLMProvider
from ..storage.analysis_repository import AnalysisRepository
from ..storage.checkpoint_manager import CheckpointManager
from ..storage.chroma_client import ChromaManager
from ..storage.models import AnalyzedFunction, ExtractedFunction, IndexedDocument
from ..utils.logger import get_logger
from ..utils.rate_limiter import RateLimiter
from .ast_analyzer import ASTAnalyzer
from .scanner import scan_project

logger = get_logger(__name__)


class FunctionIndexManager:
    """
    Manages function extraction and indexing (Index 3).

    Pipeline:
    1. Load project analysis from Index 1
    2. Scan source files
    3. For each file:
       a. Extract functions via AST
       b. Analyze each function with LLM
       c. Generate embeddings
    4. Store in ChromaDB (project_functions_{hash})
    """

    def __init__(
        self,
        config: Config,
        chroma: ChromaManager,
        llm_provider: LLMProvider,
        embedding_provider: EmbeddingProvider,
        rate_limiter: RateLimiter,
        checkpoint_manager: CheckpointManager,
        analysis_repository: AnalysisRepository
    ):
        """
        Initialize function index manager.

        Args:
            config: Configuration object
            chroma: ChromaDB manager
            llm_provider: LLM provider for function analysis
            embedding_provider: Embedding provider for vector generation
            rate_limiter: Rate limiter for API calls
            checkpoint_manager: Unified checkpoint manager
            analysis_repository: Repository for Index 1 data
        """
        self.config = config
        self.chroma = chroma
        self.llm_provider = llm_provider
        self.embedding_provider = embedding_provider
        self.rate_limiter = rate_limiter
        self.checkpoint_manager = checkpoint_manager
        self.analysis_repo = analysis_repository
        self.ast_analyzer = ASTAnalyzer()

    async def index_functions(
        self,
        project_path: Path,
        force_reindex: bool = False,
        file_patterns: Optional[List[str]] = None,
        exclude_patterns: Optional[List[str]] = None
    ) -> Dict:
        """
        Index functions in a project.

        Requires completed project analysis (Index 1).

        Args:
            project_path: Path to project root
            force_reindex: Force reindex all files
            file_patterns: Optional glob patterns to include
            exclude_patterns: Optional glob patterns to exclude

        Returns:
            Dictionary with indexing results
        """
        start_time = time.time()
        project_path = project_path.resolve()
        project_str = str(project_path)

        logger.info(f"Starting function indexing for {project_path}")

        # Step 1: Load project analysis from Index 1
        analysis = self.analysis_repo.get_analysis(project_str)
        if not analysis:
            return {
                "status": "failed",
                "error": "No project analysis found. Run load_project_info first."
            }

        # Allow indexing if completed=True OR min_confidence >= 70%
        if not analysis.completed and analysis.min_confidence() < 70:
            return {
                "status": "failed",
                "error": f"Project analysis incomplete (min_confidence={analysis.min_confidence()}%). "
                         f"Run load_project_info first."
            }

        # Step 1b: Check file index exists (Index 2)
        file_index_stats = self.checkpoint_manager.get_file_index_stats(project_str)
        if file_index_stats["completed"] == 0:
            return {
                "status": "failed",
                "error": "File index not found. Run index_project_files first before indexing functions."
            }

        project_context = analysis.to_project_context()
        logger.info(f"Using project analysis: {analysis.min_confidence()}% confidence")

        # Step 2: Handle force_reindex
        checkpoint_stats = self.checkpoint_manager.get_function_index_stats(project_str)
        is_resume = checkpoint_stats['completed'] > 0

        if force_reindex:
            logger.info("Force reindex: clearing function index")
            self.chroma.delete_collection(project_path, collection_type='functions')
            self.checkpoint_manager.clear_function_index(project_str)
            is_resume = False

        stats = {
            "total_files": 0,
            "processed_files": 0,
            "failed_files": 0,
            "skipped_files": 0,
            "resumed": is_resume,
            "total_functions": 0,
            "analyzed_functions": 0,
            "duration_seconds": 0
        }
        errors = []

        try:
            # Step 3: Get or create collection
            collection = self.chroma.get_or_create_collection(project_path, collection_type='functions')

            # Step 4: Scan files (only code files)
            include_patterns = file_patterns if file_patterns else [
                "**/*.py", "**/*.js", "**/*.ts", "**/*.tsx", "**/*.jsx",
                "**/*.java", "**/*.kt", "**/*.go", "**/*.rs", "**/*.rb",
                "**/*.c", "**/*.cpp", "**/*.h", "**/*.hpp"
            ]
            exclude_pats = list(self.config.patterns.exclude)
            if exclude_patterns:
                exclude_pats.extend(exclude_patterns)

            file_metadatas = await scan_project(
                project_path,
                include_patterns,
                exclude_pats,
                max_file_size_mb=self.config.indexing.max_file_size_mb
            )

            # Filter to only code files
            code_files = [f for f in file_metadatas if f.file_type == 'code']
            stats["total_files"] = len(code_files)
            logger.info(f"Found {stats['total_files']} code files")

            # Step 5: Filter by checkpoints
            files_to_process = []
            for file_meta in code_files:
                rel_path = str(file_meta.relative_path)
                if self.checkpoint_manager.should_reindex_functions(project_str, rel_path, file_meta.hash):
                    files_to_process.append(file_meta)
                else:
                    stats["skipped_files"] += 1

            logger.info(f"Processing {len(files_to_process)} files (skipped {stats['skipped_files']})")

            # Step 6: Process files
            sem = asyncio.Semaphore(self.config.indexing.max_concurrent_files)
            all_docs = []

            async def process_file(file_meta):
                async with sem:
                    try:
                        logger.info(f"Processing: {file_meta.relative_path}")

                        docs, func_count = await self._process_file(
                            file_meta, project_path, project_context
                        )

                        # Mark completed
                        self.checkpoint_manager.mark_functions_indexed(
                            project_str,
                            str(file_meta.relative_path),
                            file_meta.hash,
                            functions_count=func_count
                        )

                        return docs, func_count, None

                    except Exception as e:
                        logger.error(f"Failed: {file_meta.relative_path} - {e}")

                        self.checkpoint_manager.mark_functions_indexed(
                            project_str,
                            str(file_meta.relative_path),
                            file_meta.hash,
                            error=str(e)
                        )

                        return [], 0, str(e)

            # Process in chunks
            CHUNK_SIZE = 20
            for chunk_start in range(0, len(files_to_process), CHUNK_SIZE):
                chunk_end = min(chunk_start + CHUNK_SIZE, len(files_to_process))
                chunk_files = files_to_process[chunk_start:chunk_end]

                logger.info(f"Processing files {chunk_start + 1}-{chunk_end}/{len(files_to_process)}")

                tasks = [process_file(fm) for fm in chunk_files]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for result in results:
                    if isinstance(result, Exception):
                        errors.append({"error": str(result)})
                        stats["failed_files"] += 1
                    else:
                        docs, func_count, error = result
                        if error:
                            stats["failed_files"] += 1
                            errors.append({"error": error})
                        else:
                            all_docs.extend(docs)
                            stats["processed_files"] += 1
                            stats["total_functions"] += func_count

            # Step 7: Store documents
            if all_docs:
                logger.info(f"Storing {len(all_docs)} function documents in ChromaDB...")
                # Store in batches
                BATCH_SIZE = 100
                for i in range(0, len(all_docs), BATCH_SIZE):
                    batch = all_docs[i:i + BATCH_SIZE]
                    await self.chroma.add_documents(collection, batch)
                logger.info("All function documents stored")
                stats["analyzed_functions"] = len(all_docs)

            stats["duration_seconds"] = time.time() - start_time

            logger.info(f"Function indexing completed: {stats['processed_files']}/{stats['total_files']} files, "
                       f"{stats['total_functions']} functions in {stats['duration_seconds']:.1f}s")

            return {
                "status": "success" if stats["failed_files"] == 0 else "partial",
                "project_id": self.chroma._get_collection_name(project_path, 'functions'),
                "stats": stats,
                "errors": errors[:10]
            }

        except Exception as e:
            logger.error(f"Function indexing failed: {e}")
            return {
                "status": "failed",
                "error": str(e),
                "stats": stats
            }

    async def _process_file(
        self,
        file_meta,
        project_path: Path,
        project_context
    ) -> tuple[List[IndexedDocument], int]:
        """Process a single file: extract functions and analyze with LLM."""

        # Read file content
        try:
            content = file_meta.file_path.read_text(encoding='utf-8', errors='ignore')
        except Exception as e:
            logger.warning(f"Failed to read {file_meta.relative_path}: {e}")
            raise

        # Extract functions via AST
        extracted_functions = self._extract_functions(
            content,
            file_meta.language,
            file_meta.file_path
        )

        if not extracted_functions:
            logger.debug(f"No functions found in {file_meta.relative_path}")
            return [], 0

        logger.info(f"  Found {len(extracted_functions)} functions")

        # Analyze functions in parallel with semaphore for rate limiting
        max_concurrent = self.config.indexing.max_concurrent_functions
        sem = asyncio.Semaphore(max_concurrent)

        async def analyze_single_function(func, index):
            """Analyze a single function with rate limiting."""
            async with sem:
                try:
                    # Analyze function
                    analysis = await self._analyze_function(func, project_context, file_meta)

                    # Generate embedding
                    embedding_text = self._prepare_embedding_text(func, analysis, project_context)
                    await self.rate_limiter.acquire(tokens=500, request_count=1)
                    embedding = await self.embedding_provider.create_embedding(embedding_text)

                    # Create document
                    doc_id = self._generate_function_id(project_path, func)

                    metadata = {
                        "function_name": func.name,
                        "file_path": func.file_path,
                        "relative_path": str(file_meta.relative_path),
                        "line_start": func.line_start,
                        "line_end": func.line_end,
                        "parameters": ", ".join(func.parameters),
                        "return_type": func.return_type or "",
                        "is_async": func.is_async,
                        "is_method": func.is_method,
                        "class_name": func.class_name or "",
                        "decorators": ", ".join(func.decorators),
                        "docstring": func.docstring or "",
                        "language": file_meta.language,
                        "description": analysis.get("description", ""),
                        "purpose": analysis.get("purpose", ""),
                        "input_description": analysis.get("input_description", ""),
                        "output_description": analysis.get("output_description", ""),
                        "side_effects": ", ".join(analysis.get("side_effects", [])),
                        "complexity": analysis.get("complexity", "medium"),
                        "indexed_at": time.time(),
                        "project_root": str(project_path),
                        "index_type": "functions"
                    }

                    doc = IndexedDocument(
                        id=doc_id,
                        content=func.code,
                        embedding=embedding,
                        metadata=metadata
                    )

                    if (index + 1) % 10 == 0:
                        logger.info(f"  Analyzed {index + 1}/{len(extracted_functions)} functions")

                    return doc, None

                except Exception as e:
                    logger.warning(f"  Failed to analyze function {func.name}: {e}")
                    return None, str(e)

        # Process all functions in parallel
        tasks = [analyze_single_function(func, i) for i, func in enumerate(extracted_functions)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect successful documents
        indexed_docs = []
        failed_count = 0
        for result in results:
            if isinstance(result, Exception):
                failed_count += 1
                logger.warning(f"  Function analysis exception: {result}")
            else:
                doc, error = result
                if error:
                    failed_count += 1
                elif doc:
                    indexed_docs.append(doc)

        if failed_count > 0:
            logger.warning(f"  {failed_count}/{len(extracted_functions)} functions failed to analyze")

        return indexed_docs, len(extracted_functions)

    def _extract_functions(
        self,
        code: str,
        language: str,
        file_path: Path
    ) -> List[ExtractedFunction]:
        """Extract functions from code using AST."""
        if not self.ast_analyzer.tree_sitter_available:
            logger.warning("tree-sitter not available, skipping function extraction")
            return []

        try:
            # Normalize language
            lang_key = self.ast_analyzer._normalize_language(language)

            if lang_key not in self.ast_analyzer.parsers:
                logger.debug(f"No parser for {language}, skipping")
                return []

            parser = self.ast_analyzer.parsers[lang_key]
            tree = parser.parse(bytes(code, "utf8"))

            # Get language-specific analyzer
            from .analyzers import get_analyzer
            analyzer = get_analyzer(lang_key)

            # Extract functions
            return analyzer.extract_functions(tree, code, file_path)

        except Exception as e:
            logger.error(f"Function extraction failed for {file_path}: {e}")
            return []

    async def _analyze_function(
        self,
        func: ExtractedFunction,
        project_context,
        file_meta
    ) -> Dict[str, Any]:
        """Analyze a function with LLM."""

        # Rate limit
        await self.rate_limiter.acquire(tokens=1500, request_count=1)

        prompt = self._build_function_prompt(func, project_context, file_meta)
        schema = self._get_function_schema()

        try:
            response = await self.llm_provider.chat_completion(
                messages=[
                    ChatMessage(
                        role="system",
                        content="You are a code analysis expert. Analyze the function and return JSON."
                    ),
                    ChatMessage(role="user", content=prompt)
                ],
                response_format={"type": "json_schema", "json_schema": schema},
                use_reasoning=False  # Faster analysis for functions
            )

            return json.loads(response.content)

        except Exception as e:
            logger.warning(f"LLM analysis failed for {func.name}: {e}")
            # Return minimal analysis
            return {
                "description": func.docstring or f"Function {func.name}",
                "purpose": "",
                "input_description": "",
                "output_description": "",
                "side_effects": [],
                "complexity": "medium"
            }

    def _build_function_prompt(
        self,
        func: ExtractedFunction,
        project_context,
        file_meta
    ) -> str:
        """Build prompt for function analysis."""
        return f"""Analyze this function from a {project_context.project_name} project.

PROJECT CONTEXT:
- Name: {project_context.project_name}
- Tech Stack: {', '.join(project_context.tech_stack)}
- Frameworks: {', '.join(project_context.frameworks)}
- Purpose: {project_context.purpose}

FILE: {file_meta.relative_path}
LANGUAGE: {file_meta.language}

FUNCTION:
```{file_meta.language}
{func.code}
```

{"DOCSTRING: " + func.docstring if func.docstring else ""}
{"CLASS: " + func.class_name if func.class_name else ""}
{"DECORATORS: " + ", ".join(func.decorators) if func.decorators else ""}

Analyze and return JSON:
{{
  "description": "Brief description of what this function does (1-2 sentences)",
  "purpose": "Why does this function exist in the project context?",
  "input_description": "What are the inputs and their expected types/formats?",
  "output_description": "What is returned and when?",
  "side_effects": ["list of side effects like database writes, API calls, etc."],
  "complexity": "low|medium|high (based on logic complexity)"
}}
"""

    def _get_function_schema(self) -> Dict[str, Any]:
        """Get JSON schema for function analysis."""
        return {
            "name": "function_analysis",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "purpose": {"type": "string"},
                    "input_description": {"type": "string"},
                    "output_description": {"type": "string"},
                    "side_effects": {"type": "array", "items": {"type": "string"}},
                    "complexity": {"type": "string", "enum": ["low", "medium", "high"]}
                },
                "required": ["description", "purpose", "input_description",
                            "output_description", "side_effects", "complexity"],
                "additionalProperties": False
            }
        }

    def _prepare_embedding_text(
        self,
        func: ExtractedFunction,
        analysis: Dict[str, Any],
        project_context
    ) -> str:
        """Prepare text for embedding generation."""
        parts = [
            f"Function: {func.name}",
            f"Project: {project_context.project_name}",
            f"Description: {analysis.get('description', '')}",
            f"Purpose: {analysis.get('purpose', '')}",
        ]

        if func.class_name:
            parts.append(f"Class: {func.class_name}")

        if func.parameters:
            parts.append(f"Parameters: {', '.join(func.parameters)}")

        if analysis.get('input_description'):
            parts.append(f"Input: {analysis['input_description']}")

        if analysis.get('output_description'):
            parts.append(f"Output: {analysis['output_description']}")

        # Include some code context
        code_snippet = func.code[:500] if len(func.code) > 500 else func.code
        parts.append(f"Code:\n{code_snippet}")

        return "\n".join(parts)

    def _generate_function_id(self, project_path: Path, func: ExtractedFunction) -> str:
        """Generate unique ID for a function."""
        project_hash = hashlib.sha256(str(project_path.resolve()).encode()).hexdigest()[:12]
        # Include line numbers to handle function name collisions
        func_key = f"{func.file_path}:{func.name}:{func.line_start}"
        func_hash = hashlib.sha256(func_key.encode()).hexdigest()[:8]
        return f"func:{project_hash}:{func_hash}"

    async def search_functions(
        self,
        project_path: Path,
        query: str,
        n_results: int = 10,
        language: Optional[str] = None,
        class_name: Optional[str] = None
    ) -> Dict:
        """
        Semantic search across indexed functions.

        Args:
            project_path: Path to project root
            query: Search query
            n_results: Number of results
            language: Filter by language
            class_name: Filter by class name

        Returns:
            Dictionary with search results
        """
        try:
            collection = self.chroma.get_or_create_collection(project_path, collection_type='functions')

            # Generate query embedding
            await self.rate_limiter.acquire(tokens=500, request_count=1)
            query_embedding = await self.embedding_provider.create_embedding(query)

            # Build filter
            metadata_filter = {}
            if language:
                metadata_filter["language"] = language
            if class_name:
                metadata_filter["class_name"] = class_name

            # Search
            results = await self.chroma.search(
                collection=collection,
                query_embedding=query_embedding,
                n_results=n_results,
                metadata_filter=metadata_filter if metadata_filter else None
            )

            # Format results
            formatted_results = []
            for result in results:
                formatted_results.append({
                    "function_name": result.metadata.get("function_name"),
                    "relative_path": result.metadata.get("relative_path"),
                    "line_start": result.metadata.get("line_start"),
                    "line_end": result.metadata.get("line_end"),
                    "class_name": result.metadata.get("class_name"),
                    "is_method": result.metadata.get("is_method"),
                    "is_async": result.metadata.get("is_async"),
                    "language": result.metadata.get("language"),
                    "description": result.metadata.get("description"),
                    "purpose": result.metadata.get("purpose"),
                    "complexity": result.metadata.get("complexity"),
                    "score": result.score,
                    "code": result.code
                })

            return {
                "status": "success",
                "query": query,
                "results": formatted_results
            }

        except Exception as e:
            logger.error(f"Function search failed: {e}")
            return {
                "status": "failed",
                "error": str(e),
                "query": query
            }

    async def get_function_info(
        self,
        project_path: Path,
        function_id: str
    ) -> Dict:
        """
        Get detailed information about a specific function.

        Args:
            project_path: Path to project root
            function_id: Function document ID

        Returns:
            Dictionary with function details
        """
        try:
            collection = self.chroma.get_or_create_collection(project_path, collection_type='functions')

            result = collection.get(
                ids=[function_id],
                include=["documents", "metadatas"]
            )

            if not result or not result["ids"]:
                return {
                    "status": "failed",
                    "error": "Function not found"
                }

            metadata = result["metadatas"][0]
            code = result["documents"][0]

            return {
                "status": "success",
                "function": {
                    "id": function_id,
                    "name": metadata.get("function_name"),
                    "file_path": metadata.get("relative_path"),
                    "line_start": metadata.get("line_start"),
                    "line_end": metadata.get("line_end"),
                    "class_name": metadata.get("class_name"),
                    "is_method": metadata.get("is_method"),
                    "is_async": metadata.get("is_async"),
                    "parameters": metadata.get("parameters", "").split(", ") if metadata.get("parameters") else [],
                    "return_type": metadata.get("return_type"),
                    "decorators": metadata.get("decorators", "").split(", ") if metadata.get("decorators") else [],
                    "docstring": metadata.get("docstring"),
                    "language": metadata.get("language"),
                    "description": metadata.get("description"),
                    "purpose": metadata.get("purpose"),
                    "input_description": metadata.get("input_description"),
                    "output_description": metadata.get("output_description"),
                    "side_effects": metadata.get("side_effects", "").split(", ") if metadata.get("side_effects") else [],
                    "complexity": metadata.get("complexity"),
                    "code": code
                }
            }

        except Exception as e:
            logger.error(f"Get function info failed: {e}")
            return {"status": "failed", "error": str(e)}

    async def update_files(
        self,
        project_path: Path,
        file_paths: List[str]
    ) -> Dict:
        """
        Update function index for specific files.

        Args:
            project_path: Path to project root
            file_paths: List of relative file paths to update

        Returns:
            Dictionary with update results
        """
        # For now, mark files for reindexing and run index_functions
        # A more sophisticated implementation would selectively update
        project_str = str(project_path.resolve())

        for file_path in file_paths:
            # Clear checkpoint for this file to force reindex
            self.checkpoint_manager.conn.cursor().execute("""
                DELETE FROM function_index_checkpoints
                WHERE project_path = ? AND file_path = ?
            """, (project_str, file_path))
        self.checkpoint_manager.conn.commit()

        # Re-index (will only process the cleared files)
        return await self.index_functions(project_path, force_reindex=False)

    async def remove_files(
        self,
        project_path: Path,
        file_paths: List[str]
    ) -> Dict:
        """
        Remove functions from specific files from the index.

        Args:
            project_path: Path to project root
            file_paths: List of relative file paths

        Returns:
            Dictionary with removal results
        """
        try:
            collection = self.chroma.get_or_create_collection(project_path, collection_type='functions')

            total_removed = 0
            for file_path in file_paths:
                # Find all functions from this file
                results = collection.get(
                    where={"relative_path": file_path},
                    include=["metadatas"]
                )

                if results and results["ids"]:
                    collection.delete(ids=results["ids"])
                    total_removed += len(results["ids"])

            return {
                "status": "success",
                "removed_files": len(file_paths),
                "removed_functions": total_removed
            }

        except Exception as e:
            logger.error(f"Remove functions failed: {e}")
            return {"status": "failed", "error": str(e)}
