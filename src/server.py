"""MCP Server for project indexing."""

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

from mcp.server.fastmcp import FastMCP
from openai import AsyncOpenAI

from .config import load_config
from .indexer.index_manager import IndexManager
from .storage.chroma_client import ChromaManager
from .utils.logger import setup_logger
from .utils.rate_limiter import RateLimiter

# Initialize MCP server
mcp = FastMCP("project-indexer")

# Global state
config = None
chroma = None
indexer = None
logger = None


@mcp.tool()
async def index_project(
    project_path: str,
    force_reindex: bool = False,
    file_patterns: Optional[List[str]] = None,
    exclude_patterns: Optional[List[str]] = None
) -> dict:
    """
    Index entire project with AI analysis.

    This tool scans a project, analyzes its structure and code with OpenAI,
    and stores semantic embeddings in ChromaDB for intelligent search.

    Args:
        project_path: Absolute path to project root directory
        force_reindex: Force reindex even if already indexed
        file_patterns: Optional list of glob patterns to include (overrides config)
        exclude_patterns: Optional list of glob patterns to exclude (additional to config)

    Returns:
        Dictionary with indexing results including stats and any errors
    """
    try:
        path = Path(project_path).resolve()

        if not path.exists():
            return {"status": "failed", "error": "Project path does not exist"}

        if not path.is_dir():
            return {"status": "failed", "error": "Project path is not a directory"}

        # TODO: Handle custom patterns if provided
        result = await indexer.index_project(path, force_reindex)

        return result

    except Exception as e:
        logger.error(f"index_project failed: {e}")
        return {"status": "failed", "error": str(e)}


@mcp.tool()
async def search_code(
    project_path: str,
    query: str,
    n_results: int = 5,
    file_type: Optional[str] = None,
    language: Optional[str] = None,
    include_code: bool = True
) -> dict:
    """
    Semantic search across indexed code.

    Uses AI embeddings for intelligent code search that understands intent,
    not just keyword matching.

    Args:
        project_path: Absolute path to project root
        query: Natural language query or code snippet to search for
        n_results: Number of results to return (1-50)
        file_type: Filter by file type: code|documentation|config|test
        language: Filter by programming language
        include_code: Include full code in results

    Returns:
        Dictionary with search results and metadata
    """
    try:
        path = Path(project_path).resolve()
        collection = chroma.get_or_create_collection(path)

        # Generate query embedding
        embedding_response = await indexer.openai_client.embeddings.create(
            input=query,
            model=config.openai.embedding_model
        )
        query_embedding = embedding_response.data[0].embedding

        # Build metadata filter
        metadata_filter = {}
        if file_type:
            metadata_filter["file_type"] = file_type
        if language:
            metadata_filter["language"] = language

        # Search
        results = await chroma.search(
            collection,
            query_embedding,
            n_results=min(n_results, 50),
            metadata_filter=metadata_filter if metadata_filter else None
        )

        # Format results
        formatted_results = []
        for r in results:
            result_dict = {
                "file_path": r.file_path,
                "relative_path": r.relative_path,
                "chunk_index": r.chunk_index,
                "score": round(r.score, 4),
                "purpose": r.purpose,
                "dependencies": r.dependencies,
                "exported_symbols": r.exported_symbols,
                "metadata": {
                    "language": r.metadata.get("language"),
                    "file_type": r.metadata.get("file_type")
                }
            }

            if include_code:
                result_dict["code"] = r.code

            formatted_results.append(result_dict)

        return {
            "status": "success",
            "results": formatted_results,
            "query": query
        }

    except Exception as e:
        logger.error(f"search_code failed: {e}")
        return {"status": "failed", "error": str(e)}


@mcp.tool()
async def get_project_info(project_path: str) -> dict:
    """
    Get information about indexed project.

    Returns project context, statistics, and indexing status.

    Args:
        project_path: Absolute path to project root

    Returns:
        Dictionary with project information
    """
    try:
        path = Path(project_path).resolve()
        stats = chroma.get_project_stats(path)

        if not stats["exists"]:
            return {
                "status": "not_indexed",
                "message": "Project has not been indexed yet"
            }

        # Try to get project context
        collection = chroma.get_or_create_collection(path)
        context_id = chroma.generate_document_id(path, Path("__project_context__"), 0)

        try:
            result = collection.get(ids=[context_id], include=["metadatas"])

            if result and result["metadatas"]:
                metadata = result["metadatas"][0]

                return {
                    "status": "indexed",
                    "project_id": stats["collection_name"],
                    "project_context": {
                        "project_name": metadata.get("project_name"),
                        "project_description": metadata.get("project_description"),
                        "tech_stack": metadata.get("tech_stack", []),
                        "frameworks": metadata.get("frameworks", []),
                        "architecture_type": metadata.get("architecture_type"),
                        "purpose": metadata.get("purpose")
                    },
                    "indexed_at": metadata.get("indexed_at"),
                    "stats": {
                        "total_documents": stats["total_documents"]
                    }
                }
        except:
            pass

        return {
            "status": "indexed",
            "project_id": stats["collection_name"],
            "stats": stats
        }

    except Exception as e:
        logger.error(f"get_project_info failed: {e}")
        return {"status": "failed", "error": str(e)}


@mcp.tool()
async def delete_project_index(
    project_path: str,
    confirm: bool = False
) -> dict:
    """
    Delete entire project index from ChromaDB.

    WARNING: This permanently deletes all indexed data for the project.

    Args:
        project_path: Absolute path to project root
        confirm: Must be True to confirm deletion

    Returns:
        Dictionary with deletion result
    """
    if not confirm:
        return {
            "status": "failed",
            "error": "Must set confirm=True to delete project index"
        }

    try:
        path = Path(project_path).resolve()
        chroma.delete_collection(path)

        return {
            "status": "success",
            "message": f"Project index deleted for {project_path}"
        }

    except Exception as e:
        logger.error(f"delete_project_index failed: {e}")
        return {"status": "failed", "error": str(e)}


@mcp.tool()
async def list_projects() -> dict:
    """
    List all indexed projects in ChromaDB.

    Shows all projects that have been indexed, including:
    - Project name and path
    - Tech stack and frameworks
    - Number of indexed files
    - When it was indexed

    Returns:
        Dictionary with list of projects
    """
    try:
        projects = chroma.list_all_projects()

        # Sort by most recently indexed
        projects.sort(key=lambda p: p.get("indexed_at", 0) or 0, reverse=True)

        return {
            "status": "success",
            "total_projects": len(projects),
            "projects": [
                {
                    "project_name": p["project_name"],
                    "project_path": p["project_path"],
                    "tech_stack": p.get("tech_stack", []),
                    "frameworks": p.get("frameworks", []),
                    "architecture_type": p.get("architecture_type", "unknown"),
                    "total_files": p["total_documents"] - 1,  # Exclude context document
                    "collection_name": p["collection_name"],
                    "indexed_at": p.get("indexed_at")
                }
                for p in projects
            ]
        }

    except Exception as e:
        logger.error(f"list_projects failed: {e}")
        return {"status": "failed", "error": str(e)}


@mcp.tool()
async def update_files(
    project_path: str,
    file_paths: list[str]
) -> dict:
    """
    Update or add specific files OR ENTIRE DIRECTORIES to the project index.

    ⚡ SUPPORTS BOTH FILES AND FOLDERS:
    - Individual files: ["src/main.py", "config.py"]
    - Entire directories: ["src/api/", "tests/"] (updates ALL files inside recursively)
    - Mixed: ["src/api/", "main.py", "tests/unit/"]

    Use this to:
    - Add new files to an existing index
    - Re-index modified files
    - Update entire directories/modules
    - Update specific files without re-indexing the entire project

    Args:
        project_path: Absolute path to project root
        file_paths: List of relative paths (files OR directories)
                   Examples:
                   - ["src/api/"] - updates all files in src/api/ recursively
                   - ["src/main.py"] - updates single file
                   - ["src/api/", "tests/", "config.py"] - mixed files and folders

    Returns:
        Dictionary with update results and statistics
    """
    try:
        path = Path(project_path).resolve()

        result = await indexer.update_files(
            project_path=path,
            file_paths=file_paths
        )

        return result

    except Exception as e:
        logger.error(f"update_files failed: {e}")
        return {"status": "failed", "error": str(e)}


@mcp.tool()
async def remove_files(
    project_path: str,
    file_paths: list[str]
) -> dict:
    """
    Remove specific files OR ENTIRE DIRECTORIES from the project index.

    ⚡ SUPPORTS BOTH FILES AND FOLDERS:
    - Individual files: ["old/deprecated.py", "cache.json"]
    - Entire directories: ["legacy/", "temp/"] (removes ALL files inside recursively)
    - Mixed: ["legacy/", "old_script.py", "temp/"]

    Use this when:
    - Files/folders are deleted from the project
    - Old code should no longer appear in search results
    - Removing deprecated modules or directories

    Args:
        project_path: Absolute path to project root
        file_paths: List of relative paths (files OR directories)
                   Examples:
                   - ["legacy/"] - removes all files in legacy/ recursively
                   - ["old.py"] - removes single file
                   - ["legacy/", "temp/", "cache.json"] - mixed files and folders

    Returns:
        Dictionary with removal results
    """
    try:
        path = Path(project_path).resolve()

        result = await indexer.remove_files(
            project_path=path,
            file_paths=file_paths
        )

        return result

    except Exception as e:
        logger.error(f"remove_files failed: {e}")
        return {"status": "failed", "error": str(e)}


@mcp.tool()
async def search_files(
    project_path: str,
    query: str,
    n_results: int = 10
) -> dict:
    """
    Search for files by semantic query and return only file paths.

    This is a lightweight version of search_code that returns only
    unique file paths, useful for finding relevant files quickly.

    Args:
        project_path: Absolute path to project root
        query: Natural language search query (e.g., "authentication logic")
        n_results: Maximum number of unique files to return (default: 10)

    Returns:
        Dictionary with list of matching file paths and scores
    """
    try:
        path = Path(project_path).resolve()

        # Get collection
        collection = chroma.get_or_create_collection(path)

        # Generate query embedding
        query_response = await openai_client.embeddings.create(
            input=query,
            model=config.openai.embedding_model
        )
        query_embedding = query_response.data[0].embedding

        # Search with more results to account for duplicate files
        results = await chroma.search(
            collection,
            query_embedding,
            n_results=n_results * 3,  # Get more to deduplicate
            metadata_filter=None
        )

        # Deduplicate by file path and keep best score
        file_results = {}
        for result in results:
            file_path = result.relative_path
            if file_path not in file_results or result.score > file_results[file_path]["score"]:
                file_results[file_path] = {
                    "file_path": result.file_path,
                    "relative_path": result.relative_path,
                    "score": result.score,
                    "purpose": result.purpose,
                    "language": result.metadata.get("language", "unknown")
                }

        # Sort by score and limit
        sorted_files = sorted(
            file_results.values(),
            key=lambda x: x["score"],
            reverse=True
        )[:n_results]

        return {
            "status": "success",
            "query": query,
            "total_files": len(sorted_files),
            "files": sorted_files
        }

    except Exception as e:
        logger.error(f"search_files failed: {e}")
        return {"status": "failed", "error": str(e)}


def main():
    """Main entry point for the MCP server."""
    global config, chroma, indexer, logger

    try:
        # Load configuration
        config = load_config()

        # Setup logger
        logger = setup_logger(__name__, config.server.log_level)
        logger.info(f"Starting {config.server.name} v{config.server.version}")

        # Initialize ChromaDB
        chroma = ChromaManager(config.chroma)

        # Initialize OpenAI client
        openai_client = AsyncOpenAI(api_key=config.openai.api_key)

        # Initialize rate limiter
        rate_limiter = RateLimiter(
            rpm=config.indexing.rate_limit_rpm,
            tpm=config.indexing.rate_limit_tpm
        )

        # Initialize index manager
        indexer = IndexManager(config, chroma, openai_client, rate_limiter)

        logger.info("All components initialized successfully")

        # Run MCP server
        mcp.run(transport="stdio")

    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
