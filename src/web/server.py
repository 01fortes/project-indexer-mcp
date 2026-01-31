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
from ..indexer.index_manager import IndexManager
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
indexer = None
logger = None


@app.on_event("startup")
async def startup():
    """Initialize components on startup."""
    global config, chroma, indexer, logger

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

    # Initialize IndexManager
    indexer = IndexManager(config, chroma, llm_provider, embedding_provider, rate_limiter)

    logger.info("Web admin portal initialized")


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

    Returns:
        {
            "total": int,
            "projects": [
                {
                    "project_name": str,
                    "project_path": str,
                    "tech_stack": List[str],
                    "frameworks": List[str],
                    "architecture_type": str,
                    "total_files": int,
                    "collection_name": str,
                    "indexed_at": str
                }
            ]
        }
    """
    try:
        projects = chroma.list_all_projects()

        # Сортировка по дате индексации
        projects.sort(key=lambda p: p.get("indexed_at", 0) or 0, reverse=True)

        return {
            "total": len(projects),
            "projects": [
                {
                    "project_name": p["project_name"],
                    "project_path": p["project_path"],
                    "tech_stack": p.get("tech_stack", []),
                    "frameworks": p.get("frameworks", []),
                    "architecture_type": p.get("architecture_type", "unknown"),
                    "total_files": p["total_documents"] - 1,  # Exclude context doc
                    "collection_name": p["collection_name"],
                    "indexed_at": p.get("indexed_at")
                }
                for p in projects
            ]
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
        stats = chroma.get_project_stats(path)

        if not stats["exists"]:
            raise HTTPException(status_code=404, detail="Project not indexed")

        context = await indexer.get_project_context(path)

        if context:
            return {
                "status": "indexed",
                "project_id": stats["collection_name"],
                "project_context": context,
                "stats": {"total_documents": stats["total_documents"]}
            }

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
        collection = chroma.get_or_create_collection(path)

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


@app.post("/api/projects/{project_path:path}/search")
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

        result = await indexer.search_code(
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
        collection = chroma.get_or_create_collection(path)

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

        # Вызываем метод IndexManager для обновления файлов
        result = await indexer.update_files(path, file_paths)

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
# Static Files (Frontend)
# ============================================================================

# Serve static frontend files
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/")
    async def serve_frontend():
        """Serve the main frontend page."""
        index_file = static_dir / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        return {"message": "Frontend not available. Create src/web/static/index.html"}


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
