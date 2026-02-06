"""HTTP сервер для административной панели."""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
from typing import List, Optional
import uvicorn

from ..config import load_config
from ..storage.chroma_client import ChromaManager
from ..storage.checkpoint_manager import CheckpointManager
from ..storage.analysis_repository import AnalysisRepository
from ..indexer.iterative_analyzer import IterativeProjectAnalyzer
from ..indexer.file_index_manager import FileIndexManager
from ..indexer.function_index_manager import FunctionIndexManager
from ..indexer.scanner import scan_project
from ..providers import create_providers_from_config
from ..utils.logger import setup_logger
from ..utils.rate_limiter import RateLimiter

# Create FastAPI app
app = FastAPI(
    title="Project Indexer Admin",
    description="Административная панель для управления индексами проектов",
    version="1.0.0"
)

# CORS для frontend разработки
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],  # Vite/React dev servers
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state
config = None
chroma = None
checkpoint_manager = None
analysis_repo = None
iterative_analyzer = None
file_index_manager = None
function_index_manager = None
graph_store = None  # Legacy call graph storage (optional)
logger = None


@app.on_event("startup")
async def startup():
    """Initialize components on startup."""
    global config, chroma, logger
    global checkpoint_manager, analysis_repo
    global iterative_analyzer, file_index_manager, function_index_manager

    config = load_config()
    logger = setup_logger("web", config.server.log_level)
    logger.info("Starting web admin portal")

    # Initialize ChromaDB
    chroma = ChromaManager(config.chroma)

    # Create providers
    llm_provider, embedding_provider = create_providers_from_config(config)

    # Initialize rate limiter
    rate_limiter = RateLimiter(
        rpm=config.indexing.rate_limit_rpm,
        tpm=config.indexing.rate_limit_tpm
    )

    # Initialize unified checkpoint manager
    checkpoint_dir = Path(config.chroma.persist_directory) / "checkpoints"
    checkpoint_manager = CheckpointManager(checkpoint_dir)

    # Initialize analysis repository
    analysis_repo = AnalysisRepository(checkpoint_manager)

    # Initialize iterative analyzer (Index 1)
    iterative_analyzer = IterativeProjectAnalyzer(
        llm_provider, analysis_repo, rate_limiter
    )

    # Initialize file index manager (Index 2)
    file_index_manager = FileIndexManager(
        config, chroma, llm_provider, embedding_provider,
        rate_limiter, checkpoint_manager, analysis_repo
    )

    # Initialize function index manager (Index 3)
    function_index_manager = FunctionIndexManager(
        config, chroma, llm_provider, embedding_provider,
        rate_limiter, checkpoint_manager, analysis_repo
    )

    logger.info("Web admin portal initialized (3-index system)")


# ============================================================================
# Helper Functions
# ============================================================================

def _get_unique_projects() -> List[str]:
    """Get unique project paths from checkpoint database."""
    cursor = checkpoint_manager.conn.cursor()

    # Get all unique project paths from all three index tables
    project_paths = set()

    # From project_analysis
    cursor.execute("SELECT DISTINCT project_path FROM project_analysis")
    for row in cursor.fetchall():
        project_paths.add(row[0])

    # From file_index_checkpoints
    cursor.execute("SELECT DISTINCT project_path FROM file_index_checkpoints")
    for row in cursor.fetchall():
        project_paths.add(row[0])

    # From function_index_checkpoints
    cursor.execute("SELECT DISTINCT project_path FROM function_index_checkpoints")
    for row in cursor.fetchall():
        project_paths.add(row[0])

    return list(project_paths)


def _build_project_data(project_str: str) -> dict:
    """Build project data dictionary from all indices."""
    # Get index status
    stats = checkpoint_manager.get_all_index_stats(project_str)

    # Get analysis data
    analysis = analysis_repo.get_analysis(project_str)

    # Build project data
    project_name = Path(project_str).name
    project_description = ""
    tech_stack = []
    frameworks = []
    architecture_type = "unknown"

    if analysis:
        if analysis.project_description and analysis.project_description.value:
            project_description = analysis.project_description.value
        if analysis.languages and analysis.languages.value:
            tech_stack = analysis.languages.value
        if analysis.frameworks and analysis.frameworks.value:
            frameworks = analysis.frameworks.value
        if analysis.architecture and analysis.architecture.value:
            architecture_type = analysis.architecture.value
        project_name = project_name  # Could enhance with actual name from analysis

    # Get total files from file index
    total_files = stats["files"]["completed"]

    # Get total functions from function index
    total_functions = stats["functions"]["total_functions"]

    # Determine index statuses
    analysis_status = stats["analysis"]["status"]
    files_status = "completed" if stats["files"]["completed"] > 0 else "pending"
    functions_status = "completed" if stats["functions"]["completed"] > 0 else "pending"

    # Get indexed_at timestamp (use most recent)
    indexed_at = None
    try:
        cursor = checkpoint_manager.conn.cursor()
        cursor.execute("""
            SELECT MAX(created_at) FROM (
                SELECT created_at FROM project_analysis WHERE project_path = ?
                UNION ALL
                SELECT created_at FROM file_index_checkpoints WHERE project_path = ?
                UNION ALL
                SELECT created_at FROM function_index_checkpoints WHERE project_path = ?
            )
        """, (project_str, project_str, project_str))
        row = cursor.fetchone()
        if row and row[0]:
            # Convert timestamp string to unix timestamp
            from datetime import datetime
            dt = datetime.fromisoformat(row[0].replace('Z', '+00:00'))
            indexed_at = int(dt.timestamp())
    except Exception as e:
        logger.warning(f"Failed to get indexed_at for {project_str}: {e}")

    return {
        "project_name": project_name,
        "project_path": project_str,
        "project_description": project_description,
        "tech_stack": tech_stack,
        "frameworks": frameworks,
        "architecture_type": architecture_type,
        "total_files": total_files,
        "total_functions": total_functions,
        "indexed_at": indexed_at,
        "analysis_status": analysis_status,
        "files_status": files_status,
        "functions_status": functions_status
    }


# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "mcp_server": config.server.name if config else "not initialized"
    }


@app.get("/api/projects")
async def list_projects():
    """
    Получить список всех индексированных проектов.

    Aggregates data from all three indices (analysis, files, functions).

    Returns:
        {
            "total": int,
            "projects": [
                {
                    "project_name": str,
                    "project_path": str,
                    "project_description": str,
                    "tech_stack": List[str],
                    "frameworks": List[str],
                    "architecture_type": str,
                    "total_files": int,
                    "indexed_at": int,
                    "analysis_status": str,
                    "files_status": str,
                    "functions_status": str
                }
            ]
        }
    """
    try:
        # Get unique project paths from checkpoint manager
        unique_projects = _get_unique_projects()

        projects_list = []
        for project_str in unique_projects:
            project_data = _build_project_data(project_str)
            projects_list.append(project_data)

        # Sort by project path
        projects_list.sort(key=lambda p: p["project_path"])

        return {
            "total": len(projects_list),
            "projects": projects_list
        }
    except Exception as e:
        logger.error(f"Failed to list projects: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects/{project_path:path}/info")
async def get_project_info(project_path: str):
    """
    Получить детальную информацию о проекте.

    Args:
        project_path: Абсолютный путь к проекту

    Returns:
        {
            "status": "indexed",
            "project_id": str,
            "project_context": {...},
            "stats": {...}
        }
    """
    try:
        path = Path(project_path).resolve()
        project_str = str(path)

        # Try to get analysis from Index 1
        analysis = analysis_repo.get_analysis(project_str)

        if analysis:
            context = analysis.to_project_context()
            return {
                "status": "indexed",
                "project_id": chroma._get_collection_name(path, 'files'),
                "project_context": {
                    "project_name": context.project_name,
                    "project_description": context.project_description,
                    "tech_stack": context.tech_stack,
                    "frameworks": context.frameworks,
                    "architecture_type": context.architecture_type,
                    "key_entry_points": context.key_entry_points,
                    "purpose": context.purpose
                },
                "stats": checkpoint_manager.get_all_index_stats(project_str)
            }

        # Fallback to ChromaDB stats
        stats = chroma.get_project_stats(path)
        if not stats["exists"]:
            raise HTTPException(status_code=404, detail="Project not indexed")

        return {"status": "indexed", "stats": stats}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get project info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects/{project_path:path}/files")
async def list_project_files(project_path: str, limit: int = 100, offset: int = 0):
    """
    Получить список файлов в проекте.

    Args:
        project_path: Абсолютный путь к проекту
        limit: Максимальное количество результатов
        offset: Смещение для пагинации

    Returns:
        {
            "total": int,
            "files": [
                {
                    "relative_path": str,
                    "language": str,
                    "file_type": str,
                    "purpose": str,
                    "chunks": int
                }
            ]
        }
    """
    try:
        path = Path(project_path).resolve()
        collection = chroma.get_or_create_collection(path, collection_type='files')

        # Получить все документы (кроме __project_context__)
        results = collection.get(
            limit=limit + offset + 1,  # +1 для фильтрации __project_context__
            include=["metadatas"]
        )

        if not results or not results["metadatas"]:
            return {"total": 0, "files": []}

        # Фильтровать __project_context__ и дедуплицировать по файлу
        files_dict = {}
        for metadata in results["metadatas"]:
            rel_path = metadata.get("relative_path")
            if rel_path and rel_path != "__project_context__":
                if rel_path not in files_dict:
                    files_dict[rel_path] = {
                        "relative_path": rel_path,
                        "language": metadata.get("language", "unknown"),
                        "file_type": metadata.get("file_type", "unknown"),
                        "purpose": metadata.get("purpose", ""),
                        "chunks": 1
                    }
                else:
                    files_dict[rel_path]["chunks"] += 1

        # Пагинация
        files_list = list(files_dict.values())
        paginated = files_list[offset:offset + limit]

        return {
            "total": len(files_list),
            "files": paginated
        }

    except Exception as e:
        logger.error(f"Failed to list project files: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects/{project_path:path}/search")
async def search_in_project(
    project_path: str,
    query: str,
    n_results: int = 10,
    file_type: Optional[str] = None,
    language: Optional[str] = None
):
    """
    Семантический поиск в проекте.

    Args:
        project_path: Абсолютный путь к проекту
        query: Поисковый запрос
        n_results: Количество результатов
        file_type: Фильтр по типу файла (optional)
        language: Фильтр по языку (optional)

    Returns:
        {
            "status": "success",
            "query": str,
            "results": [...]
        }
    """
    try:
        path = Path(project_path).resolve()

        # Use file_index_manager for search
        result = await file_index_manager.search_files(
            project_path=path,
            query=query,
            n_results=n_results,
            file_type=file_type,
            language=language,
            include_code=True
        )

        return result

    except Exception as e:
        logger.error(f"Search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects/{project_path:path}/files/{file_path:path}")
async def get_file_chunks(project_path: str, file_path: str):
    """
    Получить все чанки конкретного файла.

    Args:
        project_path: Абсолютный путь к проекту
        file_path: Относительный путь к файлу

    Returns:
        {
            "status": "success",
            "file_path": str,
            "total_chunks": int,
            "chunks": [
                {
                    "chunk_index": int,
                    "content": str,
                    "purpose": str,
                    "dependencies": List[str],
                    "exported_symbols": List[str]
                }
            ]
        }
    """
    try:
        path = Path(project_path).resolve()
        collection = chroma.get_or_create_collection(path, collection_type='files')

        # Получить все документы для этого файла
        results = collection.get(
            where={"relative_path": file_path},
            include=["documents", "metadatas"]
        )

        if not results or not results["documents"]:
            raise HTTPException(status_code=404, detail="File not found in index")

        # Сортировать по chunk_index
        chunks = []
        for i, doc in enumerate(results["documents"]):
            metadata = results["metadatas"][i]
            chunks.append({
                "chunk_index": metadata.get("chunk_index", 0),
                "total_chunks": metadata.get("total_chunks", 1),
                "content": doc,
                "purpose": metadata.get("purpose", ""),
                "dependencies": metadata.get("dependencies", "").split(", ") if metadata.get("dependencies") else [],
                "exported_symbols": metadata.get("exported_symbols", "").split(", ") if metadata.get("exported_symbols") else [],
                "language": metadata.get("language", "unknown"),
                "file_type": metadata.get("file_type", "unknown")
            })

        # Сортировать по chunk_index
        chunks.sort(key=lambda x: x["chunk_index"])

        return {
            "status": "success",
            "file_path": file_path,
            "total_chunks": len(chunks),
            "chunks": chunks
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get file chunks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/projects/{project_path:path}/files/update")
async def update_file_index(project_path: str, request: dict):
    """
    Обновить индекс конкретных файлов в проекте.

    Args:
        project_path: Абсолютный путь к проекту
        request: JSON body с полем "file_paths" - список относительных путей

    Request body:
        {
            "file_paths": ["src/main.py", "src/utils.py"]
        }

    Returns:
        {
            "status": "success",
            "stats": {
                "updated_files": int,
                "failed_files": int,
                "total_chunks": int
            }
        }
    """
    try:
        path = Path(project_path).resolve()
        file_paths = request.get("file_paths", [])

        if not file_paths:
            raise HTTPException(status_code=400, detail="file_paths is required")

        # Use file_index_manager for updating files
        result = await file_index_manager.update_files(path, file_paths)

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update files: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/projects/{project_path:path}")
async def delete_project(project_path: str):
    """
    Удалить проект из индекса.

    Args:
        project_path: Абсолютный путь к проекту
    """
    try:
        path = Path(project_path).resolve()
        chroma.delete_collection(path)

        return {
            "status": "success",
            "message": f"Project deleted: {project_path}"
        }

    except Exception as e:
        logger.error(f"Failed to delete project: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Index 1: Project Analysis API
# ============================================================================

@app.get("/api/projects/{project_path:path}/analysis")
async def get_project_analysis(project_path: str):
    """
    Get project analysis result (Index 1).

    Returns:
        {
            "status": "success",
            "analysis": {...}
        }
    """
    try:
        path = Path(project_path).resolve()
        result = analysis_repo.get_analysis(str(path))

        if not result:
            raise HTTPException(status_code=404, detail="Project not analyzed")

        return {
            "status": "success",
            "project_path": str(path),
            "completed": result.completed,
            "iteration_count": result.iteration_count,
            "files_analyzed": result.files_analyzed,
            "analysis": {
                "description": result.project_description.value,
                "description_confidence": result.project_description.confidence,
                "languages": result.languages.value,
                "languages_confidence": result.languages.confidence,
                "frameworks": result.frameworks.value,
                "frameworks_confidence": result.frameworks.confidence,
                "modules": result.modules.value,
                "modules_confidence": result.modules.confidence,
                "entry_points": result.entry_points.value,
                "entry_points_confidence": result.entry_points.confidence,
                "architecture": result.architecture.value,
                "architecture_confidence": result.architecture.confidence
            },
            "min_confidence": result.min_confidence()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get project analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects/{project_path:path}/analysis/iterations")
async def get_analysis_iterations(project_path: str):
    """
    Get analysis iterations history.

    Returns list of iteration snapshots.
    """
    try:
        path = Path(project_path).resolve()

        cursor = checkpoint_manager.conn.cursor()
        cursor.execute("""
            SELECT iteration, files_requested, files_read, snapshot, created_at
            FROM analysis_iterations
            WHERE project_path = ?
            ORDER BY iteration ASC
        """, (str(path),))

        iterations = []
        for row in cursor.fetchall():
            import json
            iterations.append({
                "iteration": row[0],
                "files_requested": json.loads(row[1]) if row[1] else [],
                "files_read": json.loads(row[2]) if row[2] else [],
                "created_at": row[4]
            })

        return {
            "status": "success",
            "total": len(iterations),
            "iterations": iterations
        }

    except Exception as e:
        logger.error(f"Failed to get analysis iterations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/projects/{project_path:path}/analysis/start")
async def start_project_analysis(project_path: str, request: dict = None):
    """
    Start or resume project analysis (Index 1).

    Request body (optional):
        {
            "force_reindex": false
        }
    """
    try:
        path = Path(project_path).resolve()
        force = request.get("force_reindex", False) if request else False

        if not path.exists():
            raise HTTPException(status_code=404, detail="Project path not found")

        result = await iterative_analyzer.analyze(path, force)

        return {
            "status": "success" if result.completed else "partial",
            "completed": result.completed,
            "iteration_count": result.iteration_count,
            "min_confidence": result.min_confidence()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Index 3: Functions API
# ============================================================================

@app.get("/api/projects/{project_path:path}/functions")
async def list_functions(
    project_path: str,
    language: Optional[str] = None,
    class_name: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
):
    """
    List all indexed functions for a project.
    """
    try:
        path = Path(project_path).resolve()
        collection = chroma.get_or_create_collection(path, collection_type='functions')

        # Build where filter
        where = {}
        if language:
            where["language"] = language
        if class_name:
            where["class_name"] = class_name

        results = collection.get(
            where=where if where else None,
            limit=limit + offset,
            include=["metadatas"]
        )

        if not results or not results["metadatas"]:
            return {"status": "success", "total": 0, "functions": []}

        # Format and paginate
        functions = []
        for i, metadata in enumerate(results["metadatas"]):
            if i < offset:
                continue
            if len(functions) >= limit:
                break

            functions.append({
                "id": results["ids"][i],
                "name": metadata.get("function_name"),
                "file_path": metadata.get("relative_path"),
                "line_start": metadata.get("line_start"),
                "line_end": metadata.get("line_end"),
                "class_name": metadata.get("class_name"),
                "is_method": metadata.get("is_method"),
                "is_async": metadata.get("is_async"),
                "language": metadata.get("language"),
                "description": metadata.get("description"),
                "complexity": metadata.get("complexity")
            })

        return {
            "status": "success",
            "total": len(results["ids"]),
            "functions": functions
        }

    except Exception as e:
        logger.error(f"Failed to list functions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects/{project_path:path}/functions/search")
async def search_functions_api(
    project_path: str,
    q: str,
    n_results: int = 10,
    language: Optional[str] = None,
    class_name: Optional[str] = None
):
    """
    Semantic search for functions.
    """
    try:
        path = Path(project_path).resolve()

        result = await function_index_manager.search_functions(
            path, q, n_results, language, class_name
        )

        return result

    except Exception as e:
        logger.error(f"Failed to search functions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects/{project_path:path}/functions/{function_id}")
async def get_function_details(project_path: str, function_id: str):
    """
    Get detailed information about a specific function.
    """
    try:
        path = Path(project_path).resolve()

        result = await function_index_manager.get_function_info(path, function_id)

        if result.get("status") == "failed":
            raise HTTPException(status_code=404, detail=result.get("error"))

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get function details: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects/{project_path:path}/files/{file_path:path}/functions")
async def get_file_functions(project_path: str, file_path: str):
    """
    Get all functions in a specific file.
    """
    try:
        path = Path(project_path).resolve()
        collection = chroma.get_or_create_collection(path, collection_type='functions')

        results = collection.get(
            where={"relative_path": file_path},
            include=["documents", "metadatas"]
        )

        if not results or not results["ids"]:
            return {"status": "success", "total": 0, "functions": []}

        functions = []
        for i, metadata in enumerate(results["metadatas"]):
            functions.append({
                "id": results["ids"][i],
                "name": metadata.get("function_name"),
                "line_start": metadata.get("line_start"),
                "line_end": metadata.get("line_end"),
                "class_name": metadata.get("class_name"),
                "is_method": metadata.get("is_method"),
                "is_async": metadata.get("is_async"),
                "description": metadata.get("description"),
                "purpose": metadata.get("purpose"),
                "complexity": metadata.get("complexity"),
                "code": results["documents"][i]
            })

        # Sort by line number
        functions.sort(key=lambda f: f.get("line_start", 0))

        return {
            "status": "success",
            "total": len(functions),
            "file_path": file_path,
            "functions": functions
        }

    except Exception as e:
        logger.error(f"Failed to get file functions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/projects/{project_path:path}/functions/reindex")
async def reindex_functions(project_path: str, request: dict = None):
    """
    Reindex functions for a project.

    Request body (optional):
        {
            "force_reindex": false
        }
    """
    try:
        path = Path(project_path).resolve()
        force = request.get("force_reindex", False) if request else False

        result = await function_index_manager.index_functions(path, force)

        return result

    except Exception as e:
        logger.error(f"Failed to reindex functions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Combined Index Status API
# ============================================================================

async def _get_actual_file_count(project_path: Path, index_type: str = "files") -> int:
    """
    Get actual number of files in project that would be indexed.

    Args:
        project_path: Project root path
        index_type: "files" or "functions" to use appropriate patterns

    Returns:
        Count of files that match indexing criteria
    """
    try:
        # Get analysis to determine languages/patterns
        project_str = str(project_path)
        analysis = analysis_repo.get_analysis(project_str)

        # Determine patterns based on index type and analysis
        if index_type == "files":
            # Use file index patterns
            include_patterns = config.indexing.file_patterns or ["**/*.py", "**/*.js", "**/*.ts", "**/*.kt", "**/*.java"]
            exclude_patterns = config.indexing.exclude_patterns or []
        else:  # functions
            # Use function index patterns (only source files)
            if analysis and analysis.languages:
                languages = analysis.languages.value if hasattr(analysis.languages, 'value') else analysis.languages
                # Build patterns based on detected languages
                lang_extensions = {
                    'python': '**/*.py',
                    'javascript': '**/*.js',
                    'typescript': '**/*.ts',
                    'kotlin': '**/*.kt',
                    'java': '**/*.java',
                    'go': '**/*.go',
                    'rust': '**/*.rs'
                }
                include_patterns = [lang_extensions.get(lang.lower(), f'**/*.{lang.lower()}')
                                   for lang in languages if isinstance(lang, str)]
            else:
                include_patterns = ["**/*.py", "**/*.js", "**/*.ts", "**/*.kt", "**/*.java"]
            exclude_patterns = config.indexing.exclude_patterns or []

        # Scan project
        files = await scan_project(
            project_path=project_path,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            respect_gitignore=True,
            max_file_size_mb=config.indexing.max_file_size_mb
        )

        return len(files)
    except Exception as e:
        logger.warning(f"Failed to count files in {project_path}: {e}")
        return 0

@app.get("/api/projects/{project_path:path}/index-status")
async def get_index_status(project_path: str):
    """
    Get status of all three indices for a project.
    """
    try:
        path = Path(project_path).resolve()
        project_str = str(path)

        stats = checkpoint_manager.get_all_index_stats(project_str)
        analysis = analysis_repo.get_analysis(project_str)

        # Get actual file counts for accurate totals
        actual_file_count = await _get_actual_file_count(path, "files")
        actual_source_file_count = await _get_actual_file_count(path, "functions")

        # Determine file index status
        files_indexed = stats["files"]["total"]
        files_completed = stats["files"]["completed"]
        files_failed = stats["files"]["failed"]

        if actual_file_count > 0 and files_completed == actual_file_count:
            files_status = "completed"
        elif files_failed > 0 and files_completed + files_failed == actual_file_count:
            files_status = "partial"
        elif files_completed > 0 or files_failed > 0:
            files_status = "in_progress"
        else:
            files_status = "pending"

        # Determine function index status
        func_indexed = stats["functions"]["total"]
        func_completed = stats["functions"]["completed"]
        func_failed = stats["functions"]["failed"]

        if actual_source_file_count > 0 and func_completed == actual_source_file_count:
            functions_status = "completed"
        elif func_failed > 0 and func_completed + func_failed == actual_source_file_count:
            functions_status = "partial"
        elif func_completed > 0 or func_failed > 0:
            functions_status = "in_progress"
        else:
            functions_status = "pending"

        return {
            "status": "success",
            "project_path": project_str,
            "indices": {
                "analysis": {
                    "status": stats["analysis"]["status"],
                    "iteration_count": stats["analysis"]["iteration_count"],
                    "min_confidence": stats["analysis"]["min_confidence"],
                    "files_analyzed": stats["analysis"]["files_analyzed"],
                    "languages": analysis.languages.value if analysis else None,
                    "frameworks": analysis.frameworks.value if analysis else None
                },
                "files": {
                    "status": files_status,
                    "total_files": actual_file_count,  # Реальное количество файлов в проекте
                    "indexed_files": files_indexed,  # Файлы начавшие индексацию
                    "completed_files": files_completed,
                    "failed_files": files_failed,
                    "total_chunks": stats["files"]["total_chunks"]
                },
                "functions": {
                    "status": functions_status,
                    "total_files": actual_source_file_count,  # Реальное количество source файлов
                    "indexed_files": func_indexed,  # Файлы начавшие индексацию
                    "completed_files": func_completed,
                    "failed_files": func_failed,
                    "total_functions": stats["functions"]["total_functions"]
                }
            }
        }

    except Exception as e:
        logger.error(f"Failed to get index status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Call Graph API Endpoints
# ============================================================================

@app.get("/api/projects/{project_path:path}/call-graph/stats")
async def get_call_graph_stats(project_path: str):
    """
    Получить статистику call graph для проекта.

    Returns:
        {
            "status": "success",
            "stats": {
                "total_functions": int,
                "total_calls": int,
                "entry_points": int,
                "layers": {"controller": int, "service": int, ...},
                "trigger_types": {"http": int, "kafka": int, ...}
            }
        }
    """
    if not graph_store:
        raise HTTPException(status_code=503, detail="Call graph not enabled")

    try:
        logger.info(f"[STATS DEBUG] Received project_path: {project_path}")
        path = Path(project_path).resolve()
        logger.info(f"[STATS DEBUG] Resolved path: {path}")
        logger.info(f"[STATS DEBUG] graph_store.db_path: {graph_store.db_path}")

        # Get all functions
        functions = graph_store.get_all_functions(str(path))
        logger.info(f"[STATS DEBUG] Functions returned: {len(functions)}")

        # Calculate stats
        entry_points = [f for f in functions if f.get('is_entry_point')]
        layers = {}
        trigger_types = {}

        for func in functions:
            layer = func.get('layer', 'unknown')
            layers[layer] = layers.get(layer, 0) + 1

            if func.get('trigger_type'):
                trigger = func['trigger_type']
                trigger_types[trigger] = trigger_types.get(trigger, 0) + 1

        # Get total calls
        calls = graph_store.get_all_calls(str(path))

        return {
            "status": "success",
            "stats": {
                "total_functions": len(functions),
                "total_calls": len(calls),
                "entry_points": len(entry_points),
                "layers": layers,
                "trigger_types": trigger_types
            }
        }

    except Exception as e:
        logger.error(f"Failed to get call graph stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects/{project_path:path}/call-graph/functions")
async def get_functions(
    project_path: str,
    layer: Optional[str] = None,
    trigger_type: Optional[str] = None,
    entry_points_only: bool = False,
    limit: int = 100,
    offset: int = 0
):
    """
    Получить список функций с фильтрацией.

    Args:
        project_path: Путь к проекту
        layer: Фильтр по слою (controller/service/repository/etc)
        trigger_type: Фильтр по типу триггера (http/kafka/scheduled/etc)
        entry_points_only: Только точки входа
        limit: Лимит результатов
        offset: Смещение для пагинации

    Returns:
        {
            "total": int,
            "functions": [
                {
                    "id": str,
                    "name": str,
                    "file_path": str,
                    "line_number": int,
                    "layer": str,
                    "is_entry_point": bool,
                    "trigger_type": str,
                    "trigger_metadata": {...},
                    "description": str
                }
            ]
        }
    """
    if not graph_store:
        raise HTTPException(status_code=503, detail="Call graph not enabled")

    try:
        path = Path(project_path).resolve()

        # Get all functions
        functions = graph_store.get_all_functions(str(path))

        # Apply filters
        filtered = functions

        if entry_points_only:
            filtered = [f for f in filtered if f.get('is_entry_point')]

        if layer:
            filtered = [f for f in filtered if f.get('layer') == layer]

        if trigger_type:
            filtered = [f for f in filtered if f.get('trigger_type') == trigger_type]

        # Paginate
        total = len(filtered)
        paginated = filtered[offset:offset + limit]

        return {
            "total": total,
            "functions": paginated
        }

    except Exception as e:
        logger.error(f"Failed to get functions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects/{project_path:path}/call-graph/functions/{function_id}")
async def get_function_details(project_path: str, function_id: str):
    """
    Получить детальную информацию о функции.

    Returns:
        {
            "function": {...},
            "calls": [...],  # Функции, которые вызывает эта функция
            "callers": [...]  # Функции, которые вызывают эту функцию
        }
    """
    if not graph_store:
        raise HTTPException(status_code=503, detail="Call graph not enabled")

    try:
        path = Path(project_path).resolve()

        # Get function
        func = graph_store.get_function(str(path), function_id)

        if not func:
            raise HTTPException(status_code=404, detail="Function not found")

        # Get calls (what this function calls)
        calls = graph_store.get_function_calls(str(path), function_id)

        # Get callers (who calls this function)
        callers = graph_store.get_function_callers(str(path), function_id)

        return {
            "function": func,
            "calls": calls,
            "callers": callers
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get function details: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects/{project_path:path}/call-graph/entry-points")
async def get_entry_points(project_path: str):
    """
    Получить все точки входа (entry points) в проекте.

    Returns:
        {
            "total": int,
            "entry_points": [
                {
                    "function_id": str,
                    "function_name": str,
                    "file_path": str,
                    "trigger_type": str,
                    "trigger_metadata": {...},
                    "layer": str
                }
            ]
        }
    """
    if not graph_store:
        raise HTTPException(status_code=503, detail="Call graph not enabled")

    try:
        path = Path(project_path).resolve()

        # Get all entry points
        functions = graph_store.get_all_functions(str(path))
        entry_points = [f for f in functions if f.get('is_entry_point')]

        return {
            "total": len(entry_points),
            "entry_points": entry_points
        }

    except Exception as e:
        logger.error(f"Failed to get entry points: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/projects/{project_path:path}/call-graph/trace")
async def trace_call_flow(project_path: str, request: dict):
    """
    Построить граф вызовов от точки входа.

    Request body:
        {
            "function_id": str,  # ID точки входа
            "max_depth": int     # Максимальная глубина (optional, default 10)
        }

    Returns:
        {
            "status": "success",
            "root": str,
            "nodes": [...],
            "edges": [...]
        }
    """
    if not graph_store:
        raise HTTPException(status_code=503, detail="Call graph not enabled")

    try:
        path = Path(project_path).resolve()
        function_id = request.get("function_id")
        max_depth = request.get("max_depth", 10)

        if not function_id:
            raise HTTPException(status_code=400, detail="function_id is required")

        # Build call tree
        visited = set()
        nodes = []
        edges = []

        def build_tree(func_id: str, depth: int):
            if depth > max_depth or func_id in visited:
                return

            visited.add(func_id)

            # Get function
            func = graph_store.get_function(str(path), func_id)
            if not func:
                return

            nodes.append(func)

            # Get calls
            calls = graph_store.get_function_calls(str(path), func_id)

            for call in calls:
                target_id = call.get('target_function_id')
                if target_id:
                    edges.append({
                        "from": func_id,
                        "to": target_id,
                        "call_site": call.get('call_site', '')
                    })
                    build_tree(target_id, depth + 1)

        build_tree(function_id, 0)

        return {
            "status": "success",
            "root": function_id,
            "nodes": nodes,
            "edges": edges
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to trace call flow: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Checkpoint Monitoring
# ============================================================================

@app.get("/api/checkpoints/{project_path:path}/stats")
async def get_checkpoint_stats(project_path: str, index_type: Optional[str] = None):
    """
    Get checkpoint statistics for a project.

    Returns summary of completed/failed files for each pass.

    Args:
        project_path: Project path
        index_type: Filter by index type ('simple', 'graph', or None for all)
    """
    if not graph_store:
        raise HTTPException(status_code=503, detail="Call graph not enabled")

    try:
        path = Path(project_path).resolve()
        stats = graph_store.get_checkpoint_stats(str(path), index_type)

        return {
            "status": "success",
            "project_path": str(path),
            "index_type": index_type,
            "stats": stats
        }
    except Exception as e:
        logger.error(f"Failed to get checkpoint stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/checkpoints/{project_path:path}")
async def get_checkpoints(
    project_path: str,
    pass_number: Optional[int] = None,
    status: Optional[str] = None,
    index_type: Optional[str] = None,
    limit: int = 1000,
    offset: int = 0
):
    """
    Get detailed checkpoint list for a project.

    Args:
        project_path: Project path
        pass_number: Filter by pass (1 or 2)
        status: Filter by status (completed/failed)
        index_type: Filter by index type ('simple' or 'graph')
        limit: Max results
        offset: Pagination offset

    Returns:
        List of checkpoints with details
    """
    if not graph_store:
        raise HTTPException(status_code=503, detail="Call graph not enabled")

    try:
        path = Path(project_path).resolve()

        # Build query
        query = "SELECT * FROM indexing_checkpoints WHERE project_path = ?"
        params = [str(path)]

        if pass_number:
            query += " AND pass_number = ?"
            params.append(pass_number)

        if status:
            query += " AND status = ?"
            params.append(status)

        if index_type:
            query += " AND index_type = ?"
            params.append(index_type)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        # Execute query
        cursor = graph_store.conn.cursor()
        cursor.execute(query, params)

        checkpoints = []
        for row in cursor.fetchall():
            checkpoints.append({
                "id": row[0],
                "project_path": row[1],
                "file_path": row[2],
                "status": row[3],
                "pass_number": row[4],
                "error_message": row[5],
                "created_at": row[6],
                "index_type": row[7] if len(row) > 7 else "simple"  # Fallback for old schema
            })

        # Get total count
        count_query = "SELECT COUNT(*) FROM indexing_checkpoints WHERE project_path = ?"
        count_params = [str(path)]

        if pass_number:
            count_query += " AND pass_number = ?"
            count_params.append(pass_number)

        if status:
            count_query += " AND status = ?"
            count_params.append(status)

        if index_type:
            count_query += " AND index_type = ?"
            count_params.append(index_type)

        cursor.execute(count_query, count_params)
        total = cursor.fetchone()[0]

        return {
            "status": "success",
            "checkpoints": checkpoints,
            "total": total,
            "limit": limit,
            "offset": offset
        }

    except Exception as e:
        logger.error(f"Failed to get checkpoints: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/checkpoints/{project_path:path}")
async def clear_checkpoints(project_path: str, index_type: Optional[str] = None):
    """
    Clear checkpoints for a project.

    Args:
        project_path: Project path
        index_type: If specified, clear only checkpoints of this type ('simple' or 'graph')

    Useful for forcing fresh reindex.
    """
    if not graph_store:
        raise HTTPException(status_code=503, detail="Call graph not enabled")

    try:
        path = Path(project_path).resolve()
        graph_store.clear_checkpoints(str(path), index_type)

        message = f"Cleared checkpoints for {path}"
        if index_type:
            message += f" (index type: {index_type})"
        else:
            message += " (all index types)"

        return {
            "status": "success",
            "message": message
        }

    except Exception as e:
        logger.error(f"Failed to clear checkpoints: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Static Files (Frontend)
# ============================================================================

# Serve static frontend files
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/api/internal/file-checkpoints")
    async def get_file_checkpoints(project_path: str):
        """Get all file index checkpoints for a project."""
        try:
            cursor = checkpoint_manager.conn.cursor()
            cursor.execute("""
                SELECT relative_path, status, chunks_count, created_at
                FROM file_index_checkpoints
                WHERE project_path = ?
                ORDER BY created_at DESC
            """, (project_path,))

            checkpoints = []
            for row in cursor.fetchall():
                checkpoints.append({
                    "relative_path": row[0],
                    "status": row[1],
                    "chunks_count": row[2],
                    "created_at": row[3]
                })

            return {"checkpoints": checkpoints}
        except Exception as e:
            logger.error(f"Failed to get file checkpoints: {e}")
            return {"checkpoints": []}

    @app.get("/api/internal/function-checkpoints")
    async def get_function_checkpoints(project_path: str):
        """Get all function index checkpoints for a project."""
        try:
            cursor = checkpoint_manager.conn.cursor()
            cursor.execute("""
                SELECT relative_path, status, functions_count, created_at
                FROM function_index_checkpoints
                WHERE project_path = ?
                ORDER BY created_at DESC
            """, (project_path,))

            checkpoints = []
            for row in cursor.fetchall():
                checkpoints.append({
                    "relative_path": row[0],
                    "status": row[1],
                    "functions_count": row[2],
                    "created_at": row[3]
                })

            return {"checkpoints": checkpoints}
        except Exception as e:
            logger.error(f"Failed to get function checkpoints: {e}")
            return {"checkpoints": []}

    @app.get("/")
    async def serve_frontend():
        """Serve the main frontend page."""
        index_file = static_dir / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        return {"message": "Frontend not available. Create src/web/static/index.html"}

    @app.get("/checkpoints")
    async def serve_checkpoints():
        """Serve the checkpoint monitoring page."""
        checkpoints_file = static_dir / "checkpoints.html"
        if checkpoints_file.exists():
            return FileResponse(str(checkpoints_file))
        return {"message": "Checkpoints page not available"}


def run_web_server(host: str = "0.0.0.0", port: int = 8080):
    """
    Запустить веб-сервер.

    Args:
        host: Адрес хоста
        port: Порт
    """
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run_web_server()
