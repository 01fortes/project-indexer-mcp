"""File Index Manager (Index 2) - Indexes files using project analysis."""

import asyncio
import hashlib
import time
from pathlib import Path
from typing import Dict, List, Optional

from ..config import Config
from ..providers.base import EmbeddingProvider, LLMProvider
from ..storage.analysis_repository import AnalysisRepository
from ..storage.checkpoint_manager import CheckpointManager
from ..storage.chroma_client import ChromaManager
from ..storage.models import IndexedDocument, ProjectContext
from ..utils.logger import get_logger
from ..utils.rate_limiter import RateLimiter
from .analyzer import analyze_code
from .chunker import chunk_code_file
from .embedder import prepare_embedding_text
from .scanner import scan_project

logger = get_logger(__name__)


class FileIndexManager:
    """
    Manages file indexing (Index 2).

    Key differences from existing IndexManager:
    - Does NOT call analyze_project_context() - uses Index 1 results
    - Uses separate checkpoint table (file_index_checkpoints)
    - Uses separate ChromaDB collection (project_files_{hash})
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
        Initialize file index manager.

        Args:
            config: Configuration object
            chroma: ChromaDB manager
            llm_provider: LLM provider for code analysis
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

    async def index_files(
        self,
        project_path: Path,
        force_reindex: bool = False,
        file_patterns: Optional[List[str]] = None,
        exclude_patterns: Optional[List[str]] = None
    ) -> Dict:
        """
        Index files in a project.

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

        logger.info(f"Starting file indexing for {project_path}")

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
                         f"Run load_project_info with force_reindex=true or wait for higher confidence."
            }

        # Convert to ProjectContext for backward compatibility
        project_context = analysis.to_project_context()
        logger.info(f"Using project analysis: {analysis.min_confidence()}% confidence")

        # Step 2: Handle force_reindex
        checkpoint_stats = self.checkpoint_manager.get_file_index_stats(project_str)
        is_resume = checkpoint_stats['completed'] > 0

        if force_reindex:
            logger.info("Force reindex: clearing file index")
            self.chroma.delete_collection(project_path, collection_type='files')
            self.checkpoint_manager.clear_file_index(project_str)
            is_resume = False

        stats = {
            "total_files": 0,
            "indexed_files": 0,
            "failed_files": 0,
            "skipped_files": 0,
            "resumed": is_resume,
            "total_chunks": 0,
            "duration_seconds": 0
        }
        errors = []

        try:
            # Step 3: Get or create collection (using 'files' type)
            collection = self.chroma.get_or_create_collection(project_path, collection_type='files')

            # Store project context as special document
            await self._store_project_context(collection, project_path, project_context)

            # Step 4: Scan files
            include_patterns = file_patterns if file_patterns else self.config.patterns.include
            exclude_pats = list(self.config.patterns.exclude)
            if exclude_patterns:
                exclude_pats.extend(exclude_patterns)

            logger.info(f"Scanning with patterns: include={include_patterns[:3]}...")

            file_metadatas = await scan_project(
                project_path,
                include_patterns,
                exclude_pats,
                max_file_size_mb=self.config.indexing.max_file_size_mb
            )

            stats["total_files"] = len(file_metadatas)
            logger.info(f"Found {stats['total_files']} files")

            # Step 5: Filter by checkpoints
            files_to_process = []
            for file_meta in file_metadatas:
                rel_path = str(file_meta.relative_path)
                if self.checkpoint_manager.should_reindex_file(project_str, rel_path, file_meta.hash):
                    files_to_process.append(file_meta)
                else:
                    stats["skipped_files"] += 1

            logger.info(f"Processing {len(files_to_process)} files (skipped {stats['skipped_files']} already indexed)")

            # Step 6: Process files
            sem = asyncio.Semaphore(self.config.indexing.max_concurrent_files)
            processed_count = 0
            progress_lock = asyncio.Lock()
            indexed_docs = []

            async def process_file(file_meta):
                nonlocal processed_count
                async with sem:
                    try:
                        async with progress_lock:
                            processed_count += 1
                            current = processed_count
                        logger.info(f"[{current}/{len(files_to_process)}] Processing: {file_meta.relative_path}")

                        docs = await self._process_file(file_meta, project_path, project_context)

                        # Mark completed
                        self.checkpoint_manager.mark_file_indexed(
                            project_str,
                            str(file_meta.relative_path),
                            file_meta.hash,
                            chunks_count=len(docs)
                        )

                        return docs, None
                    except Exception as e:
                        logger.error(f"Failed: {file_meta.relative_path} - {e}")

                        self.checkpoint_manager.mark_file_indexed(
                            project_str,
                            str(file_meta.relative_path),
                            file_meta.hash,
                            error=str(e)
                        )

                        return [], str(e)

            # Process in chunks
            CHUNK_SIZE = 50
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
                        docs, error = result
                        if docs:
                            indexed_docs.extend(docs)
                            stats["indexed_files"] += 1
                            stats["total_chunks"] += len(docs)
                        if error:
                            stats["failed_files"] += 1
                            errors.append({"error": error})

            # Step 7: Store documents
            if indexed_docs:
                logger.info(f"Storing {len(indexed_docs)} chunks in ChromaDB...")
                await self.chroma.add_documents(collection, indexed_docs)
                logger.info("All chunks stored")

            stats["duration_seconds"] = time.time() - start_time

            logger.info(f"File indexing completed: {stats['indexed_files']}/{stats['total_files']} files "
                       f"in {stats['duration_seconds']:.1f}s")

            return {
                "status": "success" if stats["failed_files"] == 0 else "partial",
                "project_id": self.chroma._get_collection_name(project_path, 'files'),
                "stats": stats,
                "errors": errors[:10]
            }

        except Exception as e:
            logger.error(f"File indexing failed: {e}")
            return {
                "status": "failed",
                "error": str(e),
                "stats": stats
            }

    async def _process_file(
        self,
        file_meta,
        project_path: Path,
        project_context: ProjectContext
    ) -> List[IndexedDocument]:
        """Process a single file through the indexing pipeline."""
        # Read file
        try:
            content = file_meta.file_path.read_text(encoding='utf-8', errors='ignore')
        except Exception as e:
            logger.warning(f"Failed to read {file_meta.relative_path}: {e}")
            raise

        # Chunk if necessary
        chunks = await chunk_code_file(
            content,
            file_meta.file_path,
            file_meta.language,
            max_tokens=self.config.indexing.max_chunk_size_tokens,
            overlap_tokens=self.config.indexing.chunk_overlap_tokens
        )

        indexed_docs = []

        for i, chunk in enumerate(chunks, 1):
            chunk_info = f" [{i}/{len(chunks)}]" if len(chunks) > 1 else ""

            # Analyze with LLM
            await self.rate_limiter.acquire(tokens=1000, request_count=1)

            analysis = await self.rate_limiter.execute_with_retry(
                lambda: analyze_code(
                    chunk.content,
                    file_meta.file_path,
                    file_meta.language,
                    file_meta.file_type,
                    project_context,
                    self.llm_provider
                )
            )

            logger.info(f"  Analyzed{chunk_info}")

            # Prepare embedding text
            embedding_text = prepare_embedding_text(
                chunk.content,
                file_meta.relative_path,
                analysis,
                project_context
            )

            # Generate embedding
            await self.rate_limiter.acquire(tokens=500, request_count=1)

            embedding_vector = await self.rate_limiter.execute_with_retry(
                lambda: self.embedding_provider.create_embedding(embedding_text)
            )

            logger.info(f"  Embedded{chunk_info}")

            # Create document
            doc_id = self._generate_document_id(project_path, file_meta.relative_path, chunk.chunk_index)

            metadata = {
                "file_path": str(file_meta.file_path),
                "relative_path": str(file_meta.relative_path),
                "chunk_index": chunk.chunk_index,
                "total_chunks": chunk.total_chunks,
                "language": file_meta.language,
                "file_type": file_meta.file_type,
                "last_modified": file_meta.last_modified,
                "file_size": file_meta.file_size,
                "dependencies": ", ".join(analysis.dependencies) if analysis.dependencies else "",
                "exported_symbols": ", ".join(analysis.exported_symbols) if analysis.exported_symbols else "",
                "purpose": analysis.purpose,
                "indexed_at": time.time(),
                "project_root": str(project_path),
                "hash": file_meta.hash,
                "index_type": "files"  # Mark as Index 2
            }

            doc = IndexedDocument(
                id=doc_id,
                content=chunk.content,
                embedding=embedding_vector,
                metadata=metadata
            )

            indexed_docs.append(doc)

        return indexed_docs

    async def _store_project_context(
        self,
        collection,
        project_path: Path,
        context: ProjectContext
    ) -> None:
        """Store project context as special document."""
        context_text = f"""
Project: {context.project_name}
Description: {context.project_description}
Tech Stack: {', '.join(context.tech_stack)}
Frameworks: {', '.join(context.frameworks)}
Architecture: {context.architecture_type}
Purpose: {context.purpose}
"""

        await self.rate_limiter.acquire(tokens=200, request_count=1)
        embedding = await self.embedding_provider.create_embedding(context_text)

        doc_id = self._generate_document_id(project_path, Path("__project_context__"), 0)

        doc = IndexedDocument(
            id=doc_id,
            content=context_text,
            embedding=embedding,
            metadata={
                "file_path": "__project_context__",
                "relative_path": "__project_context__",
                "chunk_index": 0,
                "total_chunks": 1,
                "file_type": "project_context",
                "project_root": str(project_path),
                "indexed_at": time.time(),
                "project_name": context.project_name,
                "project_description": context.project_description,
                "tech_stack": ", ".join(context.tech_stack) if context.tech_stack else "",
                "frameworks": ", ".join(context.frameworks) if context.frameworks else "",
                "architecture_type": context.architecture_type,
                "purpose": context.purpose,
                "index_type": "files"
            }
        )

        await self.chroma.add_documents(collection, [doc])
        logger.info("Project context stored in files collection")

    def _generate_document_id(self, project_path: Path, relative_path: Path, chunk_index: int) -> str:
        """Generate document ID for file index."""
        project_hash = hashlib.sha256(str(project_path.resolve()).encode()).hexdigest()[:12]
        return f"files:{project_hash}:{relative_path}:{chunk_index}"

    async def search_files(
        self,
        project_path: Path,
        query: str,
        n_results: int = 10,
        file_type: Optional[str] = None,
        language: Optional[str] = None,
        include_code: bool = True
    ) -> Dict:
        """
        Semantic search across indexed files.

        Args:
            project_path: Path to project root
            query: Search query
            n_results: Number of results
            file_type: Filter by file type
            language: Filter by language
            include_code: Include code in results

        Returns:
            Dictionary with search results
        """
        try:
            collection = self.chroma.get_or_create_collection(project_path, collection_type='files')

            # Generate query embedding
            await self.rate_limiter.acquire(tokens=500, request_count=1)
            query_embedding = await self.embedding_provider.create_embedding(query)

            # Build filter
            metadata_filter = {}
            if file_type:
                metadata_filter["file_type"] = file_type
            if language:
                metadata_filter["language"] = language

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
                if result.relative_path == "__project_context__":
                    continue

                item = {
                    "project_path": str(project_path),
                    "relative_path": result.relative_path,
                    "chunk_index": result.chunk_index,
                    "total_chunks": result.metadata.get("total_chunks"),
                    "language": result.metadata.get("language"),
                    "file_type": result.metadata.get("file_type"),
                    "purpose": result.purpose or result.metadata.get("purpose", ""),
                    "score": result.score
                }

                if include_code:
                    item["code"] = result.code

                formatted_results.append(item)

            return {
                "status": "success",
                "query": query,
                "results": formatted_results
            }

        except Exception as e:
            logger.error(f"File search failed: {e}")
            return {
                "status": "failed",
                "error": str(e),
                "query": query
            }

    async def update_files(
        self,
        project_path: Path,
        file_paths: List[str]
    ) -> Dict:
        """
        Update specific files in the index.

        Args:
            project_path: Path to project root
            file_paths: List of relative file paths to update

        Returns:
            Dictionary with update results
        """
        project_path = project_path.resolve()
        project_str = str(project_path)

        # Load project analysis
        analysis = self.analysis_repo.get_analysis(project_str)
        if not analysis:
            return {
                "status": "failed",
                "error": "No project analysis found. Run load_project_info first."
            }

        # Allow update if completed=True OR min_confidence >= 70%
        if not analysis.completed and analysis.min_confidence() < 70:
            return {
                "status": "failed",
                "error": f"Project analysis incomplete (min_confidence={analysis.min_confidence()}%). "
                         f"Run load_project_info first."
            }

        project_context = analysis.to_project_context()

        stats = {"updated_files": 0, "failed_files": 0, "total_chunks": 0}
        errors = []

        try:
            collection = self.chroma.get_or_create_collection(project_path, collection_type='files')

            # Delete old versions
            deleted = await self.chroma.delete_files_by_path(collection, project_path, file_paths)
            logger.info(f"Deleted {deleted} old documents")

            # Process each file
            from .scanner import detect_language, classify_file_type
            from ..storage.models import FileMetadata

            indexed_docs = []

            for file_path_str in file_paths:
                file_path = project_path / file_path_str

                if not file_path.exists():
                    errors.append({"file": file_path_str, "error": "File not found"})
                    stats["failed_files"] += 1
                    continue

                try:
                    content = file_path.read_bytes()
                    file_hash = hashlib.sha256(content).hexdigest()

                    file_meta = FileMetadata(
                        file_path=file_path,
                        relative_path=Path(file_path_str),
                        language=detect_language(file_path),
                        file_type=classify_file_type(file_path),
                        file_size=file_path.stat().st_size,
                        last_modified=file_path.stat().st_mtime,
                        hash=file_hash
                    )

                    logger.info(f"Processing: {file_path_str}")
                    docs = await self._process_file(file_meta, project_path, project_context)
                    indexed_docs.extend(docs)

                    # Update checkpoint
                    self.checkpoint_manager.mark_file_indexed(
                        project_str,
                        file_path_str,
                        file_hash,
                        chunks_count=len(docs)
                    )

                    stats["updated_files"] += 1
                    stats["total_chunks"] += len(docs)

                except Exception as e:
                    logger.error(f"Failed to process {file_path_str}: {e}")
                    errors.append({"file": file_path_str, "error": str(e)})
                    stats["failed_files"] += 1

            # Store updated documents
            if indexed_docs:
                await self.chroma.add_documents(collection, indexed_docs)
                logger.info(f"Updated {stats['updated_files']} files ({stats['total_chunks']} chunks)")

            return {
                "status": "success" if stats["failed_files"] == 0 else "partial",
                "stats": stats,
                "errors": errors[:10]
            }

        except Exception as e:
            logger.error(f"Update files failed: {e}")
            return {"status": "failed", "error": str(e), "stats": stats}

    async def remove_files(
        self,
        project_path: Path,
        file_paths: List[str]
    ) -> Dict:
        """
        Remove files from the index.

        Args:
            project_path: Path to project root
            file_paths: List of relative file paths to remove

        Returns:
            Dictionary with removal results
        """
        try:
            collection = self.chroma.get_or_create_collection(project_path, collection_type='files')

            deleted_count = await self.chroma.delete_files_by_path(
                collection, project_path, file_paths
            )

            return {
                "status": "success",
                "removed_files": len(file_paths),
                "removed_chunks": deleted_count
            }

        except Exception as e:
            logger.error(f"Remove files failed: {e}")
            return {"status": "failed", "error": str(e)}
