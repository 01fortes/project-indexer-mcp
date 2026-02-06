"""ChromaDB client wrapper for vector storage."""

import asyncio
import hashlib
from pathlib import Path
from typing import Dict, List, Optional

import chromadb

from ..config import ChromaConfig
from ..storage.models import IndexedDocument, SearchResult
from ..utils.logger import get_logger

logger = get_logger(__name__)


class ChromaManager:
    """Manages ChromaDB operations for project indexing."""

    def __init__(self, config: ChromaConfig):
        """
        Initialize ChromaDB client.

        Args:
            config: ChromaDB configuration.
        """
        self.config = config

        # Initialize client based on configuration
        if config.host and config.port:
            # Remote ChromaDB server
            self.client = chromadb.HttpClient(host=config.host, port=config.port)
            logger.info(f"Connected to ChromaDB server at {config.host}:{config.port}")
        else:
            # Local persistent storage - use PersistentClient (modern API)
            self.client = chromadb.PersistentClient(path=config.persist_directory)
            logger.info(f"Using local ChromaDB at {config.persist_directory}")

    def get_or_create_collection(self, project_path: Path, collection_type: str = 'index'):
        """
        Get or create collection for project.

        Collection name format:
        - 'index': project_index_{project_hash} (legacy/backward compatible)
        - 'graph': project_graph_{project_hash} (call graph indexing)
        - 'analysis': project_analysis_{project_hash} (Index 1 - project analysis)
        - 'files': project_files_{project_hash} (Index 2 - file indexing)
        - 'functions': project_functions_{project_hash} (Index 3 - function indexing)

        Args:
            project_path: Project root path.
            collection_type: Type of collection ('index', 'graph', 'analysis', 'files', 'functions')

        Returns:
            ChromaDB collection.
        """
        collection_name = self._get_collection_name(project_path, collection_type)

        try:
            collection = self.client.get_collection(name=collection_name)
            logger.info(f"Using existing collection: {collection_name}")
        except:
            collection = self.client.create_collection(
                name=collection_name,
                metadata={
                    "project_path": str(project_path),
                    "collection_type": collection_type
                }
            )
            logger.info(f"Created new collection: {collection_name}")

        return collection

    async def add_documents(
        self,
        collection,
        documents: List[IndexedDocument],
        timeout: int = 60
    ) -> None:
        """
        Add or update documents in collection with timeout.

        Args:
            collection: ChromaDB collection.
            documents: List of IndexedDocument objects.
            timeout: Operation timeout in seconds.
        """
        if not documents:
            return

        ids = [doc.id for doc in documents]
        contents = [doc.content for doc in documents]
        embeddings = [doc.embedding for doc in documents]
        metadatas = [doc.metadata for doc in documents]

        try:
            # Run upsert in executor with timeout
            loop = asyncio.get_event_loop()
            await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: collection.upsert(
                        ids=ids,
                        documents=contents,
                        embeddings=embeddings,
                        metadatas=metadatas
                    )
                ),
                timeout=timeout
            )
            logger.info(f"Added/updated {len(documents)} documents")
        except asyncio.TimeoutError:
            logger.error(f"ChromaDB upsert timed out after {timeout}s")
            raise
        except Exception as e:
            logger.error(f"Failed to add documents: {e}")
            raise

    async def delete_documents(
        self,
        collection,
        document_ids: List[str]
    ) -> None:
        """
        Delete documents from collection.

        Args:
            collection: ChromaDB collection.
            document_ids: List of document IDs to delete.
        """
        if not document_ids:
            return

        try:
            collection.delete(ids=document_ids)
            logger.info(f"Deleted {len(document_ids)} documents")
        except Exception as e:
            logger.error(f"Failed to delete documents: {e}")
            raise

    async def delete_files_by_path(
        self,
        collection,
        project_path: Path,
        file_paths: List[str]
    ) -> int:
        """
        Delete all chunks of specific files from collection.

        Args:
            collection: ChromaDB collection.
            project_path: Project root path.
            file_paths: List of relative file paths to delete.

        Returns:
            Number of documents deleted.
        """
        if not file_paths:
            return 0

        project_hash = hashlib.sha256(str(project_path.resolve()).encode()).hexdigest()[:12]

        # Find all document IDs for these files (including all chunks)
        all_ids = []
        for file_path in file_paths:
            # Search for all chunks of this file
            try:
                results = collection.get(
                    where={"relative_path": file_path},
                    include=["metadatas"]
                )
                if results and results['ids']:
                    all_ids.extend(results['ids'])
            except Exception as e:
                logger.warning(f"Could not find documents for {file_path}: {e}")

        if all_ids:
            await self.delete_documents(collection, all_ids)
            logger.info(f"Deleted {len(all_ids)} documents for {len(file_paths)} files")
            return len(all_ids)

        return 0

    async def search(
        self,
        collection,
        query_embedding: List[float],
        n_results: int = 5,
        metadata_filter: Optional[Dict] = None
    ) -> List[SearchResult]:
        """
        Semantic search in collection.

        Args:
            collection: ChromaDB collection.
            query_embedding: Query embedding vector.
            n_results: Number of results to return.
            metadata_filter: Optional metadata filter.

        Returns:
            List of SearchResult objects.
        """
        try:
            where = metadata_filter if metadata_filter else None

            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                where=where,
                include=["documents", "metadatas", "distances"]
            )

            search_results = []

            if results and results['ids'] and len(results['ids'][0]) > 0:
                for i in range(len(results['ids'][0])):
                    metadata = results['metadatas'][0][i]
                    document = results['documents'][0][i]
                    distance = results['distances'][0][i]

                    # DEBUG: Log metadata purpose
                    purpose_value = metadata.get('purpose', 'KEY_NOT_FOUND')
                    logger.info(f"Result {i}: relative_path={metadata.get('relative_path')}, purpose='{purpose_value}', has_purpose_key={'purpose' in metadata}")

                    # Convert distance to similarity score (0-1, higher is better)
                    score = 1 / (1 + distance)

                    result = SearchResult(
                        file_path=metadata.get('file_path', ''),
                        relative_path=metadata.get('relative_path', ''),
                        chunk_index=metadata.get('chunk_index', 0),
                        score=score,
                        purpose=metadata.get('purpose', ''),
                        dependencies=metadata.get('dependencies', []),
                        exported_symbols=metadata.get('exported_symbols', []),
                        code=document,
                        metadata=metadata
                    )
                    search_results.append(result)

            logger.info(f"Found {len(search_results)} results")
            return search_results

        except Exception as e:
            logger.error(f"Search failed: {e}")
            raise

    def delete_collection(self, project_path: Path, collection_type: str = 'index') -> None:
        """
        Delete entire project collection.

        Args:
            project_path: Project root path.
            collection_type: Type of collection ('index', 'graph', 'analysis', 'files', 'functions')
        """
        collection_name = self._get_collection_name(project_path, collection_type)

        try:
            self.client.delete_collection(name=collection_name)
            logger.info(f"Deleted collection: {collection_name}")
        except Exception as e:
            logger.warning(f"Failed to delete collection {collection_name}: {e}")

    def get_project_stats(self, project_path: Path, collection_type: str = 'index') -> Dict:
        """
        Get statistics about indexed project.

        Args:
            project_path: Project root path.
            collection_type: Type of collection ('index', 'graph', 'analysis', 'files', 'functions')

        Returns:
            Dictionary with stats.
        """
        collection_name = self._get_collection_name(project_path, collection_type)

        try:
            collection = self.client.get_collection(name=collection_name)
            count = collection.count()

            return {
                "collection_name": collection_name,
                "total_documents": count,
                "exists": True
            }
        except:
            return {
                "collection_name": collection_name,
                "total_documents": 0,
                "exists": False
            }

    def _get_collection_name(self, project_path: Path, collection_type: str = 'index') -> str:
        """
        Generate collection name from project path.

        Args:
            project_path: Project root path.
            collection_type: Type of collection ('index', 'graph', 'analysis', 'files', 'functions')

        Returns:
            Collection name.
        """
        # Generate stable hash from absolute path
        normalized = str(project_path.resolve())
        hash_digest = hashlib.sha256(normalized.encode()).hexdigest()[:12]
        return f"project_{collection_type}_{hash_digest}"

    def delete_all_project_collections(self, project_path: Path) -> Dict[str, bool]:
        """
        Delete all collections for a project across all types.

        Args:
            project_path: Project root path.

        Returns:
            Dictionary mapping collection_type to success status.
        """
        results = {}
        for coll_type in ['index', 'graph', 'analysis', 'files', 'functions']:
            try:
                self.delete_collection(project_path, coll_type)
                results[coll_type] = True
            except Exception as e:
                logger.warning(f"Failed to delete {coll_type} collection for {project_path}: {e}")
                results[coll_type] = False
        return results

    def get_all_project_stats(self, project_path: Path) -> Dict[str, Dict]:
        """
        Get statistics for all collection types for a project.

        Args:
            project_path: Project root path.

        Returns:
            Dictionary mapping collection_type to stats.
        """
        stats = {}
        for coll_type in ['index', 'analysis', 'files', 'functions']:
            stats[coll_type] = self.get_project_stats(project_path, coll_type)
        return stats

    def generate_document_id(self, project_path: Path, relative_path: Path, chunk_index: int) -> str:
        """
        Generate document ID.

        Format: {project_hash}:{relative_path}:{chunk_index}

        Args:
            project_path: Project root path.
            relative_path: Relative path to file.
            chunk_index: Chunk index.

        Returns:
            Document ID string.
        """
        project_hash = hashlib.sha256(str(project_path.resolve()).encode()).hexdigest()[:12]
        return f"{project_hash}:{relative_path}:{chunk_index}"

    def list_all_projects(self) -> List[Dict]:
        """
        List all indexed projects in ChromaDB.

        Returns:
            List of dictionaries with project information.
        """
        try:
            collections = self.client.list_collections()
            projects = []

            for collection in collections:
                # Skip non-project collections
                prefixes = [
                    "project_index_", "project_graph_",
                    "project_analysis_", "project_files_", "project_functions_"
                ]
                if not any(collection.name.startswith(p) for p in prefixes):
                    continue

                try:
                    # Get collection metadata
                    coll = self.client.get_collection(name=collection.name)
                    count = coll.count()

                    # Extract project hash and collection type from name
                    # Format: project_{type}_{hash}
                    coll_type = None
                    project_hash = None
                    for prefix in ["index", "graph", "analysis", "files", "functions"]:
                        full_prefix = f"project_{prefix}_"
                        if collection.name.startswith(full_prefix):
                            project_hash = collection.name.replace(full_prefix, "")
                            coll_type = prefix
                            break

                    if not coll_type or not project_hash:
                        continue
                    context_id = f"{project_hash}:__project_context__:0"

                    project_info = {
                        "collection_name": collection.name,
                        "project_hash": project_hash,
                        "collection_type": coll_type,
                        "total_documents": count,
                        "project_name": "Unknown",
                        "project_path": collection.metadata.get("project_path", "Unknown"),
                        "tech_stack": [],
                        "indexed_at": None
                    }

                    # Try to retrieve project context
                    try:
                        results = coll.get(
                            ids=[context_id],
                            include=["metadatas"]
                        )

                        if results and results['ids'] and len(results['ids']) > 0:
                            metadata = results['metadatas'][0]
                            project_info["project_name"] = metadata.get("project_name", "Unknown")
                            project_info["tech_stack"] = metadata.get("tech_stack", "").split(", ") if metadata.get("tech_stack") else []
                            project_info["frameworks"] = metadata.get("frameworks", "").split(", ") if metadata.get("frameworks") else []
                            project_info["architecture_type"] = metadata.get("architecture_type", "unknown")
                            project_info["indexed_at"] = metadata.get("indexed_at")

                    except Exception as e:
                        logger.warning(f"Could not retrieve context for {collection.name}: {e}")

                    projects.append(project_info)

                except Exception as e:
                    logger.warning(f"Error processing collection {collection.name}: {e}")

            return projects

        except Exception as e:
            logger.error(f"Failed to list projects: {e}")
            return []

    async def get_project_context_metadata(self, project_path: Path) -> Optional[Dict]:
        """
        Получить метаданные контекста проекта без знания внутреннего формата ID.
        Инкапсулирует знание о специальном документе "__project_context__".

        Args:
            project_path: Path to project root

        Returns:
            Dictionary with project context metadata or None if not found
        """
        try:
            collection = self.get_or_create_collection(project_path)

            # Сгенерировать специальный ID контекста
            context_id = self.generate_document_id(
                project_path,
                Path("__project_context__"),
                0
            )

            # Получить документ
            result = collection.get(ids=[context_id], include=["metadatas"])

            if result and result["metadatas"] and len(result["metadatas"]) > 0:
                metadata = result["metadatas"][0]

                # Парсинг полей-списков из строк (comma-separated → list)
                return {
                    "project_name": metadata.get("project_name"),
                    "project_description": metadata.get("project_description"),
                    "tech_stack": metadata.get("tech_stack", "").split(", ") if metadata.get("tech_stack") else [],
                    "frameworks": metadata.get("frameworks", "").split(", ") if metadata.get("frameworks") else [],
                    "architecture_type": metadata.get("architecture_type"),
                    "purpose": metadata.get("purpose"),
                    "indexed_at": metadata.get("indexed_at"),
                    "project_structure": metadata.get("project_structure"),
                    "key_entry_points": metadata.get("key_entry_points", "").split(", ") if metadata.get("key_entry_points") else [],
                    "build_system": metadata.get("build_system")
                }

            return None

        except Exception as e:
            logger.warning(f"Could not retrieve project context for {project_path}: {e}")
            return None
