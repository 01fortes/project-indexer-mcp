"""Main indexing orchestrator."""

import asyncio
import hashlib
import time
from pathlib import Path
from typing import Dict, List, Optional

from ..config import Config
from ..indexer.analyzer import analyze_code
from ..indexer.chunker import chunk_code_file
from ..indexer.context_analyzer import analyze_project_context
from ..indexer.embedder import batch_generate_embeddings, prepare_embedding_text
from ..indexer.scanner import scan_project
from ..providers.base import LLMProvider, EmbeddingProvider
from ..storage.chroma_client import ChromaManager
from ..storage.models import IndexedDocument, ProjectContext
from ..utils.logger import get_logger
from ..utils.rate_limiter import RateLimiter

logger = get_logger(__name__)


class IndexManager:
    """Manages the complete indexing pipeline."""

    def __init__(
        self,
        config: Config,
        chroma: ChromaManager,
        llm_provider: LLMProvider,
        embedding_provider: EmbeddingProvider,
        rate_limiter: RateLimiter
    ):
        """
        Initialize index manager.

        Args:
            config: Configuration object.
            chroma: ChromaDB manager.
            llm_provider: LLM provider for code analysis.
            embedding_provider: Embedding provider for vector generation.
            rate_limiter: Rate limiter for API calls.
        """
        self.config = config
        self.chroma = chroma
        self.llm_provider = llm_provider
        self.embedding_provider = embedding_provider
        self.rate_limiter = rate_limiter

        # DEPRECATED - kept for backward compatibility if needed
        self.openai_client = None

    async def index_project(
        self,
        project_path: Path,
        force_reindex: bool = False
    ) -> Dict:
        """
        Index entire project.

        Pipeline:
        1. Analyze project context
        2. Scan files
        3. Analyze files with context
        4. Generate embeddings
        5. Store in ChromaDB

        Args:
            project_path: Path to project root.
            force_reindex: Force reindex even if already indexed.

        Returns:
            Dictionary with indexing results.
        """
        start_time = time.time()
        logger.info(f"Starting indexing of {project_path}")

        stats = {
            "total_files": 0,
            "indexed_files": 0,
            "failed_files": 0,
            "total_chunks": 0,
            "total_tokens": 0,
            "duration_seconds": 0,
            "context_analysis_seconds": 0
        }

        errors = []

        try:
            # Step 1: Analyze project context
            context_start = time.time()
            logger.info("Step 1: Analyzing project context")

            project_context = await self.rate_limiter.execute_with_retry(
                lambda: analyze_project_context(project_path, self.llm_provider)
            )

            stats["context_analysis_seconds"] = time.time() - context_start
            logger.info(f"Project context analyzed: {project_context.project_name}")

            # Get or create collection
            collection = self.chroma.get_or_create_collection(project_path)

            # Store project context as special document
            await self._store_project_context(collection, project_path, project_context)

            # Step 2: Scan files
            logger.info("Step 2: Scanning files")
            file_metadatas = await scan_project(
                project_path,
                self.config.patterns.include,
                self.config.patterns.exclude,
                max_file_size_mb=self.config.indexing.max_file_size_mb
            )

            stats["total_files"] = len(file_metadatas)
            logger.info(f"Found {stats['total_files']} files")

            # Step 3-5: Process files (analyze, embed, store)
            logger.info(f"Step 3-5: Processing {stats['total_files']} files...")
            indexed_docs = []

            # Process files with limited concurrency
            sem = asyncio.Semaphore(self.config.indexing.max_concurrent_files)
            processed_count = 0
            progress_lock = asyncio.Lock()

            async def process_file(file_meta):
                nonlocal processed_count
                async with sem:
                    try:
                        # Log start with progress
                        async with progress_lock:
                            processed_count += 1
                            current = processed_count
                        logger.info(f"[{current}/{stats['total_files']}] Processing: {file_meta.relative_path}")

                        docs = await self._process_file(file_meta, project_path, project_context)
                        return docs, None
                    except Exception as e:
                        logger.error(f"✗ Failed: {file_meta.relative_path} - {e}")
                        return [], str(e)

            tasks = [process_file(fm) for fm in file_metadatas]
            results = await asyncio.gather(*tasks)

            for docs, error in results:
                if docs:
                    indexed_docs.extend(docs)
                    stats["indexed_files"] += 1
                    stats["total_chunks"] += len(docs)
                if error:
                    stats["failed_files"] += 1
                    errors.append({"file": "", "error": error})

            # Store all documents in ChromaDB
            if indexed_docs:
                logger.info(f"Storing {len(indexed_docs)} chunks in ChromaDB...")
                await self.chroma.add_documents(collection, indexed_docs)
                logger.info("✓ All chunks stored")

            stats["duration_seconds"] = time.time() - start_time

            logger.info(f"✅ Indexing completed: {stats['indexed_files']}/{stats['total_files']} files in {stats['duration_seconds']:.1f}s")

            return {
                "status": "success" if stats["failed_files"] == 0 else "partial",
                "project_id": self.chroma._get_collection_name(project_path),
                "project_context": {
                    "project_name": project_context.project_name,
                    "tech_stack": project_context.tech_stack,
                    "frameworks": project_context.frameworks,
                    "architecture_type": project_context.architecture_type,
                    "purpose": project_context.purpose
                },
                "stats": stats,
                "errors": errors[:10]  # Limit to first 10 errors
            }

        except Exception as e:
            logger.error(f"Indexing failed: {e}")
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
        """
        Process single file through pipeline.

        Args:
            file_meta: FileMetadata object.
            project_path: Project root path.
            project_context: Project context.

        Returns:
            List of IndexedDocument objects.
        """
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

            # Analyze with LLM provider (with rate limiting)
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

            logger.info(f"  ✓ Analyzed{chunk_info}")

            # Prepare text for embedding
            embedding_text = prepare_embedding_text(
                chunk.content,
                file_meta.relative_path,
                analysis,
                project_context
            )

            # Generate embedding (with rate limiting)
            await self.rate_limiter.acquire(tokens=500, request_count=1)

            embedding_vector = await self.rate_limiter.execute_with_retry(
                lambda: self.embedding_provider.create_embedding(embedding_text)
            )

            logger.info(f"  ✓ Embedded{chunk_info}")

            # Create indexed document
            doc_id = self.chroma.generate_document_id(
                project_path,
                file_meta.relative_path,
                chunk.chunk_index
            )

            metadata = {
                "file_path": str(file_meta.file_path),
                "relative_path": str(file_meta.relative_path),
                "chunk_index": chunk.chunk_index,
                "total_chunks": chunk.total_chunks,
                "language": file_meta.language,
                "file_type": file_meta.file_type,
                "last_modified": file_meta.last_modified,
                "file_size": file_meta.file_size,
                # Convert lists to comma-separated strings for ChromaDB
                "dependencies": ", ".join(analysis.dependencies) if analysis.dependencies else "",
                "exported_symbols": ", ".join(analysis.exported_symbols) if analysis.exported_symbols else "",
                "purpose": analysis.purpose,
                "indexed_at": time.time(),
                "project_root": str(project_path),
                "hash": file_meta.hash
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
        """
        Store project context as special document.

        Args:
            collection: ChromaDB collection.
            project_path: Project root path.
            context: ProjectContext object.
        """
        # Create embedding for project context
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

        # Create document ID
        doc_id = self.chroma.generate_document_id(project_path, Path("__project_context__"), 0)

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
                # Convert lists to comma-separated strings for ChromaDB
                "tech_stack": ", ".join(context.tech_stack) if context.tech_stack else "",
                "frameworks": ", ".join(context.frameworks) if context.frameworks else "",
                "dependencies": ", ".join(context.dependencies[:50]) if context.dependencies else "",
                "architecture_type": context.architecture_type,
                "project_structure": context.project_structure,
                "key_entry_points": ", ".join(context.key_entry_points) if context.key_entry_points else "",
                "build_system": context.build_system,
                "purpose": context.purpose
            }
        )

        await self.chroma.add_documents(collection, [doc])
        logger.info("Project context stored")

    async def update_files(
        self,
        project_path: Path,
        file_paths: List[str]
    ) -> Dict:
        """
        Update or add specific files/directories to the index.

        Args:
            project_path: Path to project root.
            file_paths: List of relative file/directory paths to update.
                       If directory, all files in it will be indexed.

        Returns:
            Dictionary with update results.
        """
        logger.info(f"Processing {len(file_paths)} paths in {project_path}")

        # Expand directories to file lists
        expanded_files = []
        for path_str in file_paths:
            full_path = project_path / path_str

            if full_path.is_dir():
                # It's a directory - scan it for files
                logger.info(f"Scanning directory: {path_str}")
                dir_files = await self._scan_directory(
                    project_path,
                    Path(path_str)
                )
                expanded_files.extend(dir_files)
                logger.info(f"Found {len(dir_files)} files in {path_str}")
            elif full_path.is_file():
                # It's a file - add directly
                expanded_files.append(path_str)
            else:
                logger.warning(f"Path not found: {path_str}")

        logger.info(f"Total files to update: {len(expanded_files)}")

        stats = {
            "updated_files": 0,
            "failed_files": 0,
            "total_chunks": 0
        }
        errors = []

        try:
            # Get or create collection
            collection = self.chroma.get_or_create_collection(project_path)

            # Get project context (should already exist)
            project_hash = hashlib.sha256(str(project_path.resolve()).encode()).hexdigest()[:12]
            context_id = f"{project_hash}:__project_context__:0"

            try:
                result = collection.get(ids=[context_id], include=["metadatas"])
                if result and result["metadatas"]:
                    metadata = result["metadatas"][0]
                    project_context = ProjectContext(
                        project_name=metadata.get("project_name", project_path.name),
                        project_description=metadata.get("project_description", ""),
                        tech_stack=metadata.get("tech_stack", "").split(", ") if metadata.get("tech_stack") else [],
                        frameworks=metadata.get("frameworks", "").split(", ") if metadata.get("frameworks") else [],
                        dependencies=[],
                        architecture_type=metadata.get("architecture_type", "unknown"),
                        purpose=metadata.get("purpose", "")
                    )
                else:
                    raise ValueError("Project context not found")
            except Exception as e:
                logger.error(f"Could not load project context: {e}")
                return {
                    "status": "failed",
                    "error": "Project not indexed. Please run index_project first."
                }

            # Delete old versions of these files
            deleted_count = await self.chroma.delete_files_by_path(collection, project_path, expanded_files)
            logger.info(f"Deleted {deleted_count} old documents")

            # Scan and process the specified files
            from ..indexer.scanner import detect_language, classify_file_type
            import hashlib as hash_module

            indexed_docs = []

            for file_path_str in expanded_files:
                file_path = project_path / file_path_str

                if not file_path.exists():
                    logger.warning(f"File not found: {file_path_str}")
                    errors.append({"file": file_path_str, "error": "File not found"})
                    stats["failed_files"] += 1
                    continue

                try:
                    # Create file metadata
                    from ..storage.models import FileMetadata

                    content = file_path.read_bytes()
                    file_hash = hash_module.sha256(content).hexdigest()

                    file_meta = FileMetadata(
                        file_path=file_path,
                        relative_path=Path(file_path_str),
                        language=detect_language(file_path),
                        file_type=classify_file_type(file_path),
                        file_size=file_path.stat().st_size,
                        last_modified=file_path.stat().st_mtime,
                        hash=file_hash
                    )

                    # Process file
                    logger.info(f"Processing: {file_path_str}")
                    docs = await self._process_file(file_meta, project_path, project_context)
                    indexed_docs.extend(docs)
                    stats["updated_files"] += 1
                    stats["total_chunks"] += len(docs)

                except Exception as e:
                    logger.error(f"Failed to process {file_path_str}: {e}")
                    errors.append({"file": file_path_str, "error": str(e)})
                    stats["failed_files"] += 1

            # Store updated documents
            if indexed_docs:
                await self.chroma.add_documents(collection, indexed_docs)
                logger.info(f"✅ Updated {stats['updated_files']} files ({stats['total_chunks']} chunks)")

            return {
                "status": "success" if stats["failed_files"] == 0 else "partial",
                "stats": stats,
                "errors": errors[:10]
            }

        except Exception as e:
            logger.error(f"Update failed: {e}")
            return {
                "status": "failed",
                "error": str(e),
                "stats": stats
            }

    async def remove_files(
        self,
        project_path: Path,
        file_paths: List[str]
    ) -> Dict:
        """
        Remove specific files or directories from the index.

        Args:
            project_path: Path to project root.
            file_paths: List of relative file/directory paths to remove.
                       If directory, all files in it will be removed.

        Returns:
            Dictionary with removal results.
        """
        logger.info(f"Processing {len(file_paths)} paths for removal from {project_path}")

        # Expand directories to file lists
        expanded_files = []
        for path_str in file_paths:
            full_path = project_path / path_str

            if full_path.is_dir():
                # It's a directory - scan it for files
                logger.info(f"Scanning directory for removal: {path_str}")
                dir_files = await self._scan_directory(
                    project_path,
                    Path(path_str)
                )
                expanded_files.extend(dir_files)
                logger.info(f"Found {len(dir_files)} files in {path_str}")
            elif full_path.is_file():
                # It's a file - add directly
                expanded_files.append(path_str)
            else:
                # Path doesn't exist - might be already deleted, still try to remove from index
                logger.info(f"Path not found (may be already deleted): {path_str}, will try to remove from index")
                expanded_files.append(path_str)

        logger.info(f"Total files to remove: {len(expanded_files)}")

        try:
            collection = self.chroma.get_or_create_collection(project_path)

            deleted_count = await self.chroma.delete_files_by_path(
                collection,
                project_path,
                expanded_files
            )

            return {
                "status": "success",
                "removed_paths": len(file_paths),
                "removed_files": len(expanded_files),
                "removed_chunks": deleted_count
            }

        except Exception as e:
            logger.error(f"Remove files failed: {e}")
            return {
                "status": "failed",
                "error": str(e)
            }

    async def _scan_directory(
        self,
        project_path: Path,
        relative_dir: Path
    ) -> List[str]:
        """
        Scan directory and return list of relative file paths.

        Args:
            project_path: Project root path.
            relative_dir: Relative directory path to scan.

        Returns:
            List of relative file paths.
        """
        from ..indexer.scanner import scan_project

        full_dir = project_path / relative_dir

        if not full_dir.is_dir():
            return []

        # Scan the directory using existing scanner
        file_metadatas = await scan_project(
            full_dir,
            self.config.patterns.include,
            self.config.patterns.exclude,
            max_file_size_mb=self.config.indexing.max_file_size_mb
        )

        # Convert to relative paths from project root
        relative_paths = []
        for file_meta in file_metadatas:
            # Calculate path relative to project root
            try:
                rel_path = file_meta.file_path.relative_to(project_path)
                relative_paths.append(str(rel_path))
            except ValueError:
                # File is outside project root, skip
                logger.warning(f"Skipping file outside project: {file_meta.file_path}")

        return relative_paths

    async def generate_query_embedding(self, query: str) -> List[float]:
        """
        Генерация embedding для поискового запроса с rate limiting.

        Args:
            query: Текст запроса

        Returns:
            Список float - embedding вектор
        """
        await self.rate_limiter.acquire(tokens=500, request_count=1)

        embedding = await self.rate_limiter.execute_with_retry(
            lambda: self.embedding_provider.create_embedding(query)
        )

        return embedding

    async def search_code(
        self,
        project_path: Path,
        query: str,
        n_results: int = 5,
        file_type: Optional[str] = None,
        language: Optional[str] = None,
        include_code: bool = True
    ) -> Dict:
        """
        Высокоуровневый API семантического поиска.

        Args:
            project_path: Path to project root
            query: Search query
            n_results: Number of results to return
            file_type: Optional file type filter (code|documentation|config|test)
            language: Optional language filter
            include_code: Whether to include code content in results

        Returns:
            Dictionary with search results
        """
        try:
            # Get collection
            collection = self.chroma.get_or_create_collection(project_path)

            # Generate embedding
            query_embedding = await self.generate_query_embedding(query)

            # Build metadata filters
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
                formatted_result = {
                    "relative_path": result.relative_path,
                    "chunk_index": result.chunk_index,
                    "total_chunks": result.metadata.get("total_chunks"),
                    "language": result.metadata.get("language"),
                    "file_type": result.metadata.get("file_type"),
                    "purpose": result.purpose,
                    "score": result.score
                }

                if include_code:
                    formatted_result["code"] = result.code

                formatted_results.append(formatted_result)

            return {
                "status": "success",
                "results": formatted_results,
                "query": query
            }

        except Exception as e:
            logger.error(f"Search code failed: {e}")
            return {
                "status": "failed",
                "error": str(e),
                "query": query
            }

    async def search_files(
        self,
        project_path: Path,
        query: str,
        n_results: int = 10
    ) -> Dict:
        """
        Поиск файлов с дедупликацией.

        Args:
            project_path: Path to project root
            query: Search query
            n_results: Number of unique files to return

        Returns:
            Dictionary with file search results
        """
        try:
            # Get collection
            collection = self.chroma.get_or_create_collection(project_path)

            # Generate embedding
            query_embedding = await self.generate_query_embedding(query)

            # Search with extra results for deduplication
            results = await self.chroma.search(
                collection=collection,
                query_embedding=query_embedding,
                n_results=n_results * 3  # Get more to account for duplicates
            )

            # Deduplicate by relative_path, keep best score
            files_dict = {}
            for result in results:
                rel_path = result.relative_path
                if rel_path and rel_path != "__project_context__":
                    if rel_path not in files_dict or result.score > files_dict[rel_path]["score"]:
                        files_dict[rel_path] = {
                            "relative_path": rel_path,
                            "language": result.metadata.get("language"),
                            "file_type": result.metadata.get("file_type"),
                            "purpose": result.purpose,
                            "score": result.score
                        }

            # Sort by score and limit
            files_list = sorted(files_dict.values(), key=lambda x: x["score"])[:n_results]

            return {
                "status": "success",
                "query": query,
                "total_files": len(files_list),
                "files": files_list
            }

        except Exception as e:
            logger.error(f"Search files failed: {e}")
            return {
                "status": "failed",
                "error": str(e),
                "query": query
            }

    async def get_project_context(self, project_path: Path) -> Optional[Dict]:
        """
        Получение метаданных контекста проекта.

        Args:
            project_path: Path to project root

        Returns:
            Dictionary with project context or None if not found
        """
        return await self.chroma.get_project_context_metadata(project_path)
