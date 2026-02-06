"""MCP Server for project indexing."""

import asyncio
import atexit
import signal
import sys
from pathlib import Path
from typing import List, Optional, Set

from mcp.server.fastmcp import FastMCP

from .config import load_config
from .indexer.iterative_analyzer import IterativeProjectAnalyzer
from .indexer.file_index_manager import FileIndexManager
from .indexer.function_index_manager import FunctionIndexManager
from .providers import create_providers_from_config
from .storage.analysis_repository import AnalysisRepository
from .storage.checkpoint_manager import CheckpointManager
from .storage.chroma_client import ChromaManager
from .utils.logger import setup_logger
from .utils.rate_limiter import RateLimiter

# Initialize MCP server
mcp = FastMCP("project-indexer")

# Global state
config = None
chroma = None
checkpoint_manager = None
analysis_repo = None
iterative_analyzer = None
file_index_manager = None
function_index_manager = None
logger = None
active_tasks: Set[asyncio.Task] = set()
_shutdown_in_progress = False


async def cancel_all_tasks():
    """Cancel all active tasks."""
    global active_tasks
    for task in list(active_tasks):
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    active_tasks.clear()


def cleanup():
    """Cleanup resources on shutdown."""
    global chroma, _shutdown_in_progress

    if _shutdown_in_progress:
        return
    _shutdown_in_progress = True

    if logger:
        logger.info("Shutting down, cleaning up resources...")

    try:
        # Cancel all active tasks first
        if active_tasks:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(cancel_all_tasks())
                else:
                    asyncio.run(cancel_all_tasks())
            except Exception as e:
                if logger:
                    logger.warning(f"Error cancelling tasks: {e}")

        if logger:
            logger.info("Cleanup complete")
    except Exception as e:
        if logger:
            logger.error(f"Error during cleanup: {e}")


# =============================================================================
# 🔍 STEP 1: Load Project Info (run this FIRST for new projects)
# =============================================================================

@mcp.tool()
async def load_project_info(
    project_path: str,
    force_reindex: bool = False
) -> dict:
    """
    🔍 STEP 1: Load and analyze project information - tech stack, architecture, modules.

    ✅ NO PREREQUISITES - This is the FIRST step, run it before anything else.

    ⚡ WHEN TO USE:
    - ALWAYS run this FIRST before any other indexing for a NEW project
    - When you need to understand what a project does
    - When you need to know languages, frameworks, modules used
    - Before running index_project_files or index_project_functions

    🔗 DEPENDENCY CHAIN (this is step 1):
    1. load_project_info (this) → 2. index_project_files → 3. index_project_functions

    📋 WHAT IT DOES:
    - Reads README, config files (package.json, pyproject.toml, etc.)
    - Iteratively analyzes project structure with LLM
    - Builds confidence scores (0-100%) for each insight
    - Continues until 90%+ confidence on all fields

    📊 RETURNS:
    - description: What the project does
    - languages: Programming languages used (Python, TypeScript, etc.)
    - frameworks: Frameworks used (FastAPI, React, etc.)
    - modules: Major modules/packages in the project
    - entry_points: Main entry files (main.py, index.ts, etc.)
    - architecture: Type (monolithic, microservices, library, CLI, web-app)

    Args:
        project_path: Absolute path to project root directory
        force_reindex: Force fresh analysis (ignore cached results)

    Returns:
        Dictionary with project analysis and confidence scores
    """
    try:
        path = Path(project_path).resolve()
        logger.info(f"load_project_info called: {path}, force_reindex={force_reindex}")

        if not path.exists():
            return {"status": "failed", "error": "Project path does not exist"}

        if not path.is_dir():
            return {"status": "failed", "error": "Project path is not a directory"}

        result = await iterative_analyzer.analyze(path, force_reindex)

        return {
            "status": "success" if result.completed else "partial",
            "project_path": str(path),
            "completed": result.completed,
            "iteration_count": result.iteration_count,
            "files_analyzed": len(result.files_analyzed),
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

    except Exception as e:
        logger.error(f"understand_project failed: {e}")
        return {"status": "failed", "error": str(e)}


@mcp.tool()
async def get_project_overview(project_path: str) -> dict:
    """
    📖 GET PROJECT INFO - Fast access to cached project analysis.

    🎯 TRIGGER PHRASES (use this tool when user asks):
    - "what is this project?", "describe this project"
    - "what languages/frameworks are used?"
    - "what does this project do?"
    - "tell me about this project"
    - "what's the architecture?"
    - "show project info/overview/summary"

    ⚡ WHEN TO USE:
    - When you already ran load_project_info and need to recall the results
    - To quickly check what languages/frameworks a project uses
    - To see project description without re-analyzing

    ⚠️ REQUIRES: load_project_info must have been run first

    Args:
        project_path: Absolute path to project root

    Returns:
        Dictionary with cached project analysis or error if not found
    """
    try:
        path = Path(project_path).resolve()

        result = analysis_repo.get_analysis(str(path))

        if not result:
            return {
                "status": "not_found",
                "message": "Project has not been analyzed. Run load_project_info first."
            }

        return {
            "status": "success",
            "project_path": str(path),
            "completed": result.completed,
            "iteration_count": result.iteration_count,
            "files_analyzed": len(result.files_analyzed),
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

    except Exception as e:
        logger.error(f"get_project_overview failed: {e}")
        return {"status": "failed", "error": str(e)}


# =============================================================================
# 📁 STEP 2: Index Project Files (enables semantic code search)
# =============================================================================

@mcp.tool()
async def index_project_files(
    project_path: str,
    force_reindex: bool = False,
    file_patterns: Optional[List[str]] = None,
    exclude_patterns: Optional[List[str]] = None
) -> dict:
    """
    📁 STEP 2: Index all project files for semantic search.

    ⚠️ PREREQUISITE CHECK:
    Before calling this function, you MUST verify that load_project_info
    has been completed for this project. Use check_project_indexes() to verify.
    If project info is not loaded, call load_project_info() FIRST.

    ⚡ WHEN TO USE:
    - After load_project_info to enable code search
    - When you want to search for files by description/purpose
    - When you need semantic search across the codebase
    - To find files related to specific functionality

    🔗 DEPENDENCY CHAIN:
    1. load_project_info (REQUIRED) → 2. index_project_files (this)

    📋 WHAT IT DOES:
    - Scans all source files in the project
    - Analyzes each file with LLM to understand its purpose
    - Creates semantic embeddings for intelligent search
    - Stores in vector database for fast retrieval

    🔍 ENABLES:
    - find_relevant_files() - search files by description
    - search_code() - search code by natural language

    Args:
        project_path: Absolute path to project root directory
        force_reindex: Force reindex all files (ignore cache)
        file_patterns: Glob patterns to include (e.g., ["**/*.py", "**/*.ts"])
        exclude_patterns: Glob patterns to exclude (e.g., ["**/tests/**"])

    Returns:
        Dictionary with indexing stats (files indexed, chunks created, etc.)
    """
    try:
        path = Path(project_path).resolve()
        logger.info(f"index_project_files called: {path}, force_reindex={force_reindex}")

        if not path.exists():
            return {"status": "failed", "error": "Project path does not exist"}

        result = await file_index_manager.index_files(
            path,
            force_reindex,
            file_patterns=file_patterns,
            exclude_patterns=exclude_patterns
        )

        return result

    except Exception as e:
        logger.error(f"build_file_search_index failed: {e}")
        return {"status": "failed", "error": str(e)}


@mcp.tool()
async def find_relevant_files(
    project_path: str,
    query: str,
    n_results: int = 10,
    file_type: Optional[str] = None,
    language: Optional[str] = None,
    include_code: bool = True
) -> dict:
    """
    🔎 SEMANTIC FILE SEARCH - Use when user asks about finding/locating files.

    🎯 TRIGGER PHRASES (use this tool when user says):
    - "find files...", "where is...", "show files...", "locate files..."
    - "which files handle/contain/implement/use..."
    - "files related to...", "files for..."
    - "where can I find...", "show me the code for..."
    - "where is [X] used?", "what uses [X]?", "find usage of [X]"
    - "where does [X] appear?", "where is [X] mentioned?"
    - "[table/class/variable] where used?" (e.g., "campaign_meta где используется?")
    - ANY question about finding files by functionality or purpose

    ⚡ EXAMPLE QUERIES:
    - "Find files that handle user authentication"
    - "Where is the database connection logic?"
    - "Show me files related to API endpoints"
    - "Which files implement payment processing?"
    - "Locate configuration files"

    ⚠️ REQUIRES: index_project_files must be run first

    📋 EXAMPLES:
    - query="user authentication" → finds auth.py, login.ts, etc.
    - query="API routes" → finds router.py, endpoints.ts, etc.
    - query="database models" → finds models.py, schema.ts, etc.

    Args:
        project_path: Absolute path to project root
        query: Natural language description of what you're looking for
        n_results: Max number of files to return (default: 10)
        file_type: Filter by type: "code" | "documentation" | "config" | "test"
        language: Filter by language: "python" | "typescript" | "javascript" etc.
        include_code: Include file content in results (default: True)

    Returns:
        List of matching files with relevance scores and content
    """
    try:
        path = Path(project_path).resolve()

        result = await file_index_manager.search_files(
            path, query, n_results, file_type, language, include_code
        )

        return result

    except Exception as e:
        logger.error(f"find_relevant_files failed: {e}")
        return {"status": "failed", "error": str(e)}


@mcp.tool()
async def refresh_file_index(
    project_path: str,
    file_paths: List[str]
) -> dict:
    """
    🔄 Update search index for specific changed files.

    ⚡ WHEN TO USE:
    - After modifying files and wanting updated search results
    - When new files were added to the project
    - To incrementally update without full reindex

    Args:
        project_path: Absolute path to project root
        file_paths: Relative paths to re-index (e.g., ["src/auth.py", "src/api/"])

    Returns:
        Dictionary with update stats
    """
    try:
        path = Path(project_path).resolve()

        result = await file_index_manager.update_files(path, file_paths)

        return result

    except Exception as e:
        logger.error(f"refresh_file_index failed: {e}")
        return {"status": "failed", "error": str(e)}


# =============================================================================
# 🔧 STEP 3: Index Project Functions (enables function-level search)
# =============================================================================

@mcp.tool()
async def index_project_functions(
    project_path: str,
    force_reindex: bool = False
) -> dict:
    """
    🔧 STEP 3: Index all functions and methods for semantic search.

    ⚠️ PREREQUISITE CHECK:
    Before calling this function, you MUST verify that BOTH indexes exist:
    1. load_project_info - project info must be loaded
    2. index_project_files - file index must be built
    Use check_project_indexes() to verify both are complete.
    If missing, call them in order: load_project_info → index_project_files → this.

    ⚡ WHEN TO USE:
    - When you need to find specific functions by what they do
    - When you want to understand function signatures and behavior
    - For deeper code understanding than file-level search
    - To find functions that process data, handle errors, etc.

    🔗 DEPENDENCY CHAIN:
    1. load_project_info (REQUIRED) → 2. index_project_files (REQUIRED) → 3. index_project_functions (this)

    📋 WHAT IT DOES:
    - Parses all source files with AST (Abstract Syntax Tree)
    - Extracts every function, method, and class method
    - Analyzes each function with LLM to understand:
      • What it does (description)
      • Why it exists (purpose in context)
      • Inputs/outputs
      • Side effects (DB writes, API calls, etc.)
      • Complexity level

    🔍 ENABLES:
    - find_functions() - search functions by description
    - get_function_details() - get full function analysis

    💡 SUPPORTED LANGUAGES:
    - Python (def, async def, methods, decorators)
    - Kotlin (fun, suspend fun, extension functions)
    - JavaScript/TypeScript, Java, Go, Rust (generic support)

    Args:
        project_path: Absolute path to project root directory
        force_reindex: Force reindex all functions (ignore cache)

    Returns:
        Dictionary with stats (functions found, analyzed, etc.)
    """
    try:
        path = Path(project_path).resolve()
        logger.info(f"index_project_functions called: {path}, force_reindex={force_reindex}")

        if not path.exists():
            return {"status": "failed", "error": "Project path does not exist"}

        result = await function_index_manager.index_functions(path, force_reindex)

        return result

    except Exception as e:
        logger.error(f"build_function_search_index failed: {e}")
        return {"status": "failed", "error": str(e)}


@mcp.tool()
async def find_functions(
    project_path: str,
    query: str,
    n_results: int = 10,
    language: Optional[str] = None,
    class_name: Optional[str] = None
) -> dict:
    """
    🔎 SEMANTIC FUNCTION SEARCH - Use when user asks about finding/locating functions.

    🎯 TRIGGER PHRASES (use this tool when user says):
    - "find function/method...", "where is the function...", "show function..."
    - "which function does...", "what function handles/uses..."
    - "function that...", "method for...", "function to..."
    - "how does [feature] work?" (search for implementing functions)
    - "where is [action] implemented/done?" (e.g., "where is validation done?")
    - "what calls/uses [function/class/table]?"
    - "where is [function/method] called?"
    - "find usage of [function]", "who calls [function]?"
    - ANY question about finding functions/methods by what they do

    ⚡ EXAMPLE QUERIES:
    - "Find function that validates user input"
    - "Where is password hashing done?"
    - "Find methods that write to database"
    - "Show functions that call external APIs"
    - "Which function sends emails?"
    - "How is authentication implemented?" (find auth functions)

    ⚠️ REQUIRES: index_project_functions must be run first

    📋 EXAMPLES:
    - query="validate email" → finds validate_email(), isValidEmail(), etc.
    - query="hash password" → finds hash_password(), bcrypt functions, etc.
    - query="send notification" → finds send_email(), push_notification(), etc.

    📊 RETURNS FOR EACH FUNCTION:
    - name: Function name
    - file_path: Where it's located
    - line_start/line_end: Line numbers
    - class_name: If it's a method
    - description: What it does
    - complexity: low/medium/high
    - code: Full source code

    Args:
        project_path: Absolute path to project root
        query: Natural language description of what the function does
        n_results: Max number of functions to return (default: 10)
        language: Filter by language ("python", "kotlin", "typescript", etc.)
        class_name: Filter by class name (for methods)

    Returns:
        List of matching functions with details and source code
    """
    try:
        path = Path(project_path).resolve()

        result = await function_index_manager.search_functions(
            path, query, n_results, language, class_name
        )

        return result

    except Exception as e:
        logger.error(f"find_functions failed: {e}")
        return {"status": "failed", "error": str(e)}


@mcp.tool()
async def get_function_details(
    project_path: str,
    function_id: str
) -> dict:
    """
    📋 GET DETAILED FUNCTION INFO - Use to get complete details about a specific function.

    🎯 TRIGGER PHRASES (use this tool when user says):
    - "show me the code for [function_name]"
    - "what does [function_name] do?"
    - "tell me more about [function_name]"
    - "show full details of [function_name]"
    - "what are the parameters of [function_name]?"
    - "explain [function_name]"
    - After using find_functions() when user wants full details

    ⚡ WHEN TO USE:
    - After find_functions() to get full details about a result
    - When you need complete function analysis including:
      • Full source code
      • Parameter descriptions
      • Return value description
      • Side effects list
      • Complexity assessment

    Args:
        project_path: Absolute path to project root
        function_id: Function ID from find_functions() results

    Returns:
        Complete function details including code, analysis, and metadata
    """
    try:
        path = Path(project_path).resolve()

        result = await function_index_manager.get_function_info(path, function_id)

        return result

    except Exception as e:
        logger.error(f"get_function_details failed: {e}")
        return {"status": "failed", "error": str(e)}


# =============================================================================
# 📊 Status & Combined Operations
# =============================================================================

@mcp.tool()
async def check_project_indexes(project_path: str) -> dict:
    """
    📊 Check what indexes exist and their status for a project.

    ⚡ WHEN TO USE:
    - BEFORE calling index_project_files - verify load_project_info is complete
    - BEFORE calling index_project_functions - verify BOTH previous indexes exist
    - To see indexing statistics and decide what to run next
    - When user asks to "index a project" - check what's missing first

    💡 USE THIS TO DETERMINE WHAT TO RUN:
    - If indices.analysis.status != "completed" → run load_project_info first
    - If indices.files.status != "completed" → run index_project_files
    - If indices.functions.status != "completed" → run index_project_functions

    📋 RETURNS:
    - indices.analysis: Project info status (load_project_info)
    - indices.files: File index status (index_project_files)
    - indices.functions: Function index status (index_project_functions)

    Args:
        project_path: Absolute path to project root

    Returns:
        Status of all three indexes with statistics
    """
    try:
        path = Path(project_path).resolve()
        project_str = str(path)

        # Get stats from checkpoint manager
        stats = checkpoint_manager.get_all_index_stats(project_str)

        # Get analysis details
        analysis = analysis_repo.get_analysis(project_str)

        return {
            "status": "success",
            "project_path": project_str,
            "indices": {
                "analysis": {
                    "status": stats["analysis"]["status"],
                    "iteration_count": stats["analysis"]["iteration_count"],
                    "min_confidence": stats["analysis"]["min_confidence"],
                    "files_analyzed": stats["analysis"]["files_analyzed"],
                    "description": analysis.project_description.value if analysis else None,
                    "languages": analysis.languages.value if analysis else None,
                    "frameworks": analysis.frameworks.value if analysis else None
                },
                "files": {
                    "status": "completed" if stats["files"]["completed"] > 0 else "pending",
                    "total_files": stats["files"]["total"],
                    "completed_files": stats["files"]["completed"],
                    "failed_files": stats["files"]["failed"],
                    "total_chunks": stats["files"]["total_chunks"]
                },
                "functions": {
                    "status": "completed" if stats["functions"]["completed"] > 0 else "pending",
                    "total_files": stats["functions"]["total"],
                    "completed_files": stats["functions"]["completed"],
                    "failed_files": stats["functions"]["failed"],
                    "total_functions": stats["functions"]["total_functions"]
                }
            }
        }

    except Exception as e:
        logger.error(f"check_project_indexes failed: {e}")
        return {"status": "failed", "error": str(e)}


@mcp.tool()
async def full_project_index(
    project_path: str,
    force_reindex: bool = False
) -> dict:
    """
    🚀 One-click full project indexing (runs all 3 steps automatically).

    ✅ NO PREREQUISITES - This handles all dependencies automatically.

    ⚡ WHEN TO USE:
    - For new projects - sets up everything at once
    - When user says "index this project" without specifics
    - When you want complete indexing without checking prerequisites
    - For full reindex after major project changes

    📋 RUNS SEQUENTIALLY (handles all dependencies):
    1. load_project_info - Analyze what the project does
    2. index_project_files - Enable file search
    3. index_project_functions - Enable function search

    💡 ALTERNATIVE: For more control, run steps individually:
    - check_project_indexes() to see what exists
    - load_project_info() → index_project_files() → index_project_functions()

    ⏱️ NOTE: This can take several minutes for large projects.

    Args:
        project_path: Absolute path to project root directory
        force_reindex: Force fresh indexing (ignore all caches)

    Returns:
        Combined results from all three indexing steps
    """
    try:
        path = Path(project_path).resolve()
        logger.info(f"full_project_index called: {path}, force_reindex={force_reindex}")

        if not path.exists():
            return {"status": "failed", "error": "Project path does not exist"}

        results = {}

        # Step 1: Load project info
        logger.info("Step 1/3: Loading project info (load_project_info)...")
        analysis_result = await iterative_analyzer.analyze(path, force_reindex)
        results["project_info"] = {
            "status": "success" if analysis_result.completed else "partial",
            "min_confidence": analysis_result.min_confidence(),
            "avg_confidence": analysis_result.avg_confidence(),
            "iterations": analysis_result.iteration_count
        }

        # Check if we can proceed - need completed=True OR min_confidence >= 70%
        if not analysis_result.completed:
            min_conf = analysis_result.min_confidence()
            if min_conf >= 70:
                logger.info(f"Analysis partial but sufficient (min={min_conf}%), continuing...")
                # Mark as completed for downstream checks
                analysis_result.completed = True
                analysis_repo.save_analysis(analysis_result)
            else:
                logger.warning(f"Analysis confidence too low ({min_conf}%), stopping.")
                return {
                    "status": "partial",
                    "project_path": str(path),
                    "results": results,
                    "error": f"Project analysis confidence too low ({min_conf}%). Try force_reindex=true",
                    "summary": f"Project info: partial (min_confidence={min_conf}%)"
                }

        # Step 2: Index project files
        logger.info("Step 2/3: Indexing project files (index_project_files)...")
        files_result = await file_index_manager.index_files(path, force_reindex)
        results["files_index"] = {
            "status": files_result.get("status"),
            "indexed_files": files_result.get("stats", {}).get("indexed_files", 0),
            "total_chunks": files_result.get("stats", {}).get("total_chunks", 0)
        }

        # Check if file indexing succeeded before proceeding to functions
        if files_result.get("status") == "failed":
            logger.warning("File indexing failed, skipping function indexing")
            return {
                "status": "partial",
                "project_path": str(path),
                "results": results,
                "error": files_result.get("error"),
                "summary": f"Project info: success, Files: failed - {files_result.get('error')}"
            }

        # Step 3: Index project functions
        logger.info("Step 3/3: Indexing project functions (index_project_functions)...")
        functions_result = await function_index_manager.index_functions(path, force_reindex)
        results["functions_index"] = {
            "status": functions_result.get("status"),
            "processed_files": functions_result.get("stats", {}).get("processed_files", 0),
            "total_functions": functions_result.get("stats", {}).get("total_functions", 0)
        }

        # Determine overall status
        statuses = [r.get("status") for r in results.values()]
        if all(s == "success" for s in statuses):
            overall = "success"
        elif any(s == "failed" for s in statuses):
            overall = "partial"
        else:
            overall = "partial"

        return {
            "status": overall,
            "project_path": str(path),
            "results": results,
            "summary": f"Project info: {results['project_info']['status']}, "
                      f"Files: {results['files_index']['indexed_files']} indexed, "
                      f"Functions: {results['functions_index']['total_functions']} indexed"
        }

    except Exception as e:
        logger.error(f"full_project_index failed: {e}")
        return {"status": "failed", "error": str(e)}


def main():
    """Main entry point for the MCP server."""
    global config, chroma, logger
    global checkpoint_manager, analysis_repo
    global iterative_analyzer, file_index_manager, function_index_manager

    # Register cleanup handlers
    atexit.register(cleanup)

    def signal_handler(signum, frame):
        if logger:
            logger.info(f"Received signal {signum}, initiating shutdown...")
        cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Load configuration
        config = load_config()

        # Setup logger
        logger = setup_logger(__name__, config.server.log_level)
        logger.info(f"Starting {config.server.name} v{config.server.version}")
        logger.info(f"Current working directory: {Path.cwd()}")

        # Initialize ChromaDB
        chroma = ChromaManager(config.chroma)

        # Create providers from configuration
        llm_provider, embedding_provider = create_providers_from_config(config)
        logger.info(f"Using LLM: {llm_provider.model_name}, Embedding: {embedding_provider.model_name}")

        # Initialize rate limiter
        rate_limiter = RateLimiter(
            rpm=config.indexing.rate_limit_rpm,
            tpm=config.indexing.rate_limit_tpm
        )

        # Initialize unified checkpoint manager
        checkpoint_dir = Path(config.chroma.persist_directory) / "checkpoints"
        checkpoint_manager = CheckpointManager(checkpoint_dir)

        # Initialize analysis repository (Index 1)
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

        logger.info("All components initialized successfully (3-index system)")

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
