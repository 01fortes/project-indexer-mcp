"""Iterative project analyzer with confidence scores (Index 1)."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from ..providers.base import ChatMessage, LLMProvider
from ..storage.analysis_repository import AnalysisRepository
from ..storage.models import AnalysisField, ProjectAnalysisResult
from ..utils.logger import get_logger
from ..utils.rate_limiter import RateLimiter

logger = get_logger(__name__)

# Files to read in first iteration (configuration and entry points)
FIRST_LEVEL_FILES = [
    # Documentation
    "README.md", "README.rst", "README.txt", "README",
    "ARCHITECTURE.md", "docs/README.md", "docs/index.md",

    # Python
    "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile",

    # Node.js
    "package.json", "tsconfig.json",

    # Rust
    "Cargo.toml",

    # Go
    "go.mod",

    # Java/Kotlin
    "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle.kts",

    # Docker
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml",

    # Config
    "Makefile", ".env.example", "config.yaml", "config.json",
]

# Directories to scan for first level
FIRST_LEVEL_DIRS = ["src", "lib", "app", "cmd", "internal", "pkg"]

# Maximum iterations and files per iteration
MAX_ITERATIONS = 10
MAX_FILES_PER_ITERATION = 20
MIN_CONFIDENCE_THRESHOLD = 90

# Directories to ignore when generating tree
IGNORED_DIRS = {
    ".git", ".svn", ".hg",  # VCS
    "node_modules", "vendor", "venv", ".venv", "env",  # Dependencies
    "__pycache__", ".pytest_cache", ".mypy_cache",  # Python cache
    "build", "dist", "target", "out", "bin",  # Build outputs
    ".idea", ".vscode", ".vs",  # IDE
    "coverage", ".coverage", "htmlcov",  # Coverage
    ".gradle", ".mvn",  # Build tools
}

# Maximum depth and items for directory tree
MAX_TREE_DEPTH = 4
MAX_TREE_ITEMS_PER_DIR = 30


class IterativeProjectAnalyzer:
    """
    Iteratively analyzes a project to build understanding with confidence scores.

    Algorithm:
    1. Check force_reindex -> clear tables
    2. Check existing checkpoint -> restore state
    3. Collect first level files
    4. LOOP (max 10 iterations):
       a. Read file contents (max 20 files per iteration)
       b. Build prompt with FileContext[]
       c. Call LLM with JSON schema
       d. Validate response, retry up to 3 times
       e. Update analysis state
       f. IF min_confidence >= 90% AND next_path empty -> STOP
       g. Filter next_path (verify exists)
       h. Save iteration checkpoint
    5. Save final result to SQLite
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        analysis_repository: AnalysisRepository,
        rate_limiter: RateLimiter
    ):
        """
        Initialize analyzer.

        Args:
            llm_provider: LLM provider for analysis
            analysis_repository: Repository for storing results
            rate_limiter: Rate limiter for API calls
        """
        self.llm_provider = llm_provider
        self.analysis_repo = analysis_repository
        self.rate_limiter = rate_limiter

    async def analyze(
        self,
        project_path: Path,
        force_reindex: bool = False
    ) -> ProjectAnalysisResult:
        """
        Perform iterative project analysis.

        Args:
            project_path: Path to project root
            force_reindex: Force fresh analysis

        Returns:
            ProjectAnalysisResult with confidence scores
        """
        project_path = project_path.resolve()
        project_str = str(project_path)
        logger.info(f"Starting iterative analysis for {project_path}")

        # Step 1: Handle force_reindex
        if force_reindex:
            logger.info("Force reindex: clearing existing analysis")
            self.analysis_repo.clear_project(project_str)

        # Step 2: Check for existing analysis
        existing = self.analysis_repo.get_analysis(project_str)
        if existing and existing.completed:
            logger.info(f"Analysis already complete with min confidence {existing.min_confidence()}%")
            return existing

        # Step 3: Initialize or restore state
        if existing:
            logger.info(f"Resuming from iteration {existing.iteration_count}")
            current_state = existing
            files_read = set(existing.files_analyzed)
        else:
            current_state = ProjectAnalysisResult(project_path=project_str)
            files_read = set()

        # Step 4: Collect first level files
        if current_state.iteration_count == 0:
            next_files = self._collect_first_level_files(project_path)
            logger.info(f"First level: {len(next_files)} files to read")
        else:
            # Get from last iteration if resuming
            last_iter = self.analysis_repo.get_last_iteration(project_str)
            if last_iter and last_iter.get("snapshot", {}).get("next_path"):
                next_files = last_iter["snapshot"]["next_path"]
            else:
                next_files = []

        # Step 5: Iteration loop
        for iteration in range(current_state.iteration_count, MAX_ITERATIONS):
            logger.info(f"=== Iteration {iteration + 1}/{MAX_ITERATIONS} ===")

            # Filter files to only those not yet read
            files_to_read = self._filter_valid_paths(project_path, next_files, files_read)

            if not files_to_read:
                logger.info("No more files to read")
                min_conf = current_state.min_confidence()
                if min_conf >= MIN_CONFIDENCE_THRESHOLD:
                    logger.info(f"Analysis complete with min_confidence={min_conf}%")
                    current_state.completed = True
                    break
                elif min_conf >= 70:
                    # Allow completion with lower confidence if no more files
                    logger.info(f"No more files to analyze, marking complete with min_confidence={min_conf}%")
                    current_state.completed = True
                    break
                else:
                    logger.warning(f"Confidence only {min_conf}%, but no more files")
                    break

            # Limit files per iteration
            files_to_read = files_to_read[:MAX_FILES_PER_ITERATION]
            logger.info(f"Reading {len(files_to_read)} files")

            # Read file contents
            file_contexts = await self._read_files_content(project_path, files_to_read)
            files_read.update(files_to_read)

            # Call LLM
            try:
                response = await self._call_llm_with_validation(
                    project_path, file_contexts, current_state
                )
            except Exception as e:
                logger.error(f"LLM call failed: {e}")
                break

            # Update state from response
            current_state = self._update_state_from_response(
                current_state, response, list(files_read), iteration + 1
            )

            # Get next files to read
            next_files = response.get("next_path", [])

            # Save iteration checkpoint
            self.analysis_repo.save_iteration(
                project_str,
                iteration + 1,
                files_to_read,
                [f["path"] for f in file_contexts],
                {
                    "state": self._state_to_dict(current_state),
                    "next_path": next_files
                }
            )

            # Save current state
            self.analysis_repo.save_analysis(current_state)

            # Check completion
            min_conf = current_state.min_confidence()
            if min_conf >= MIN_CONFIDENCE_THRESHOLD and not next_files:
                logger.info(f"Analysis complete! Min confidence: {min_conf}%")
                current_state.completed = True
                break

            logger.info(f"Min confidence: {min_conf}%, continuing...")

        # Final save - mark completed if we exhausted iterations and have good enough confidence
        min_conf = current_state.min_confidence()
        avg_conf = current_state.avg_confidence()

        if not current_state.completed:
            if min_conf >= MIN_CONFIDENCE_THRESHOLD:
                current_state.completed = True
            elif min_conf >= 70:
                # Allow completion with lower min confidence if we've exhausted iterations
                logger.info(f"Exhausted iterations, marking complete with min_confidence={min_conf}%, avg_confidence={avg_conf}%")
                current_state.completed = True
            elif avg_conf >= 80:
                # Allow completion if average confidence is high even if min is low
                logger.info(f"Marking complete with avg_confidence={avg_conf}% (min={min_conf}%)")
                current_state.completed = True

        self.analysis_repo.save_analysis(current_state)
        logger.info(f"Analysis finished. Completed: {current_state.completed}, "
                   f"Iterations: {current_state.iteration_count}, "
                   f"Files analyzed: {len(current_state.files_analyzed)}")

        return current_state

    def _collect_first_level_files(self, project_path: Path) -> List[str]:
        """Collect files for the first iteration."""
        files = []

        # Add known config files if they exist
        for filename in FIRST_LEVEL_FILES:
            file_path = project_path / filename
            if file_path.exists() and file_path.is_file():
                files.append(filename)

        # Add first-level files from key directories
        for dir_name in FIRST_LEVEL_DIRS:
            dir_path = project_path / dir_name
            if dir_path.exists() and dir_path.is_dir():
                try:
                    for item in dir_path.iterdir():
                        if item.is_file() and not item.name.startswith('.'):
                            rel_path = str(item.relative_to(project_path))
                            if rel_path not in files:
                                files.append(rel_path)
                except PermissionError:
                    pass

        return files

    def _filter_valid_paths(
        self,
        project_path: Path,
        paths: List[str],
        already_read: Set[str]
    ) -> List[str]:
        """Filter paths to only valid, unread files."""
        valid = []
        for path in paths:
            if path in already_read:
                continue

            full_path = project_path / path
            if full_path.exists() and full_path.is_file():
                valid.append(path)
            elif full_path.exists() and full_path.is_dir():
                # Expand directory to files
                try:
                    for item in full_path.iterdir():
                        if item.is_file() and not item.name.startswith('.'):
                            rel = str(item.relative_to(project_path))
                            if rel not in already_read and rel not in valid:
                                valid.append(rel)
                except PermissionError:
                    pass

        return valid

    async def _read_files_content(
        self,
        project_path: Path,
        file_paths: List[str]
    ) -> List[Dict[str, str]]:
        """Read file contents."""
        contexts = []
        max_content_length = 10000  # Truncate very large files

        for rel_path in file_paths:
            full_path = project_path / rel_path
            try:
                content = full_path.read_text(encoding='utf-8', errors='ignore')
                if len(content) > max_content_length:
                    content = content[:max_content_length] + "\n... [TRUNCATED]"

                contexts.append({
                    "path": rel_path,
                    "content": content
                })
            except Exception as e:
                logger.warning(f"Could not read {rel_path}: {e}")

        return contexts

    async def _call_llm_with_validation(
        self,
        project_path: Path,
        file_contexts: List[Dict[str, str]],
        current_state: ProjectAnalysisResult,
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """Call LLM and validate response, with retries."""
        prompt = self._build_prompt(project_path, file_contexts, current_state)
        schema = self._get_response_schema()

        for attempt in range(max_retries):
            try:
                await self.rate_limiter.acquire(tokens=2000, request_count=1)

                response = await self.llm_provider.chat_completion(
                    messages=[
                        ChatMessage(
                            role="system",
                            content="You are a code analysis expert. Analyze project files and build understanding. Return JSON."
                        ),
                        ChatMessage(role="user", content=prompt)
                    ],
                    response_format={"type": "json_schema", "json_schema": schema},
                    use_reasoning=True
                )

                result = json.loads(response.content)

                # Validate
                is_valid, error = self._validate_response(result)
                if is_valid:
                    return result

                logger.warning(f"Invalid response (attempt {attempt + 1}): {error}")

            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse error (attempt {attempt + 1}): {e}")
            except Exception as e:
                logger.error(f"LLM call error (attempt {attempt + 1}): {e}")
                if attempt == max_retries - 1:
                    raise

        raise ValueError("Failed to get valid response after max retries")

    def _generate_directory_tree(
        self,
        project_path: Path,
        max_depth: int = MAX_TREE_DEPTH,
        max_items: int = MAX_TREE_ITEMS_PER_DIR
    ) -> str:
        """
        Generate a visual tree of project directory structure.

        Args:
            project_path: Root path of the project
            max_depth: Maximum depth to traverse
            max_items: Maximum items to show per directory

        Returns:
            String representation of directory tree
        """
        def build_tree(path: Path, prefix: str = "", depth: int = 0) -> List[str]:
            """Recursively build tree structure."""
            if depth >= max_depth:
                return []

            lines = []
            try:
                # Get all items in directory
                items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name))

                # Filter out ignored items
                items = [
                    item for item in items
                    if not item.name.startswith('.') and item.name not in IGNORED_DIRS
                ]

                # Limit items
                if len(items) > max_items:
                    items = items[:max_items]
                    truncated = True
                else:
                    truncated = False

                for i, item in enumerate(items):
                    is_last = (i == len(items) - 1) and not truncated

                    # Choose appropriate tree characters
                    connector = "└── " if is_last else "├── "
                    extension = "    " if is_last else "│   "

                    # Add item name
                    if item.is_dir():
                        lines.append(f"{prefix}{connector}{item.name}/")
                        # Recurse into directory
                        lines.extend(build_tree(item, prefix + extension, depth + 1))
                    else:
                        lines.append(f"{prefix}{connector}{item.name}")

                # Add truncation indicator
                if truncated:
                    lines.append(f"{prefix}└── ... ({len(list(path.iterdir())) - max_items} more items)")

            except PermissionError:
                lines.append(f"{prefix}[Permission Denied]")
            except Exception as e:
                lines.append(f"{prefix}[Error: {e}]")

            return lines

        # Build tree starting from root
        tree_lines = [f"{project_path.name}/"]
        tree_lines.extend(build_tree(project_path))

        return "\n".join(tree_lines)

    def _build_prompt(
        self,
        project_path: Path,
        file_contexts: List[Dict[str, str]],
        current_state: ProjectAnalysisResult
    ) -> str:
        """Build the analysis prompt."""
        # Format current state
        state_summary = ""
        if current_state.iteration_count > 0:
            state_summary = f"""
CURRENT UNDERSTANDING (after {current_state.iteration_count} iterations):
- Description: {current_state.project_description.value} (confidence: {current_state.project_description.confidence}%)
- Languages: {current_state.languages.value} (confidence: {current_state.languages.confidence}%)
- Frameworks: {current_state.frameworks.value} (confidence: {current_state.frameworks.confidence}%)
- Modules: {current_state.modules.value} (confidence: {current_state.modules.confidence}%)
- Entry Points: {current_state.entry_points.value} (confidence: {current_state.entry_points.confidence}%)
- Architecture: {current_state.architecture.value} (confidence: {current_state.architecture.confidence}%)
- Files analyzed: {len(current_state.files_analyzed)}
"""

        # Generate directory tree
        directory_tree = self._generate_directory_tree(project_path)

        # Format file contents
        files_content = ""
        for ctx in file_contexts:
            files_content += f"\n=== FILE: {ctx['path']} ===\n{ctx['content']}\n"

        prompt = f"""Analyze this software project to understand its structure and purpose.

PROJECT: {project_path.name}
PATH: {project_path}

PROJECT STRUCTURE:
{directory_tree}

{state_summary}

NEW FILES TO ANALYZE:
{files_content}

Based on ALL available information (current understanding + new files + project structure), provide:

1. **project_description**: What does this project do? (1-2 sentences)
2. **languages**: List of programming languages used
3. **frameworks**: List of frameworks/libraries used
4. **modules**: List of major modules/packages in the project
5. **entry_points**: List of main entry point files
6. **architecture**: Type of architecture (monolithic/microservices/library/cli/web-app/api/etc)
7. **next_path**: List of file/directory paths to analyze next (max 20)
   - Use PROJECT STRUCTURE above to identify relevant files/directories
   - You can specify directories (e.g., "src/service/") - all files inside will be read
   - Focus on paths that would increase the LOWEST confidence scores
8. **reasoning**: Brief explanation of your analysis

For each field, also provide a confidence score (0-100):
- 0-30: Uncertain, need more information
- 31-60: Reasonable guess based on limited info
- 61-90: Fairly confident, have good evidence
- 91-100: Very confident, have strong evidence

If any field already has high confidence (>90%), you can keep the same value.
Always provide next_path suggestions unless ALL fields have 90%+ confidence.
"""
        return prompt

    def _get_response_schema(self) -> Dict[str, Any]:
        """Get JSON schema for LLM response."""
        return {
            "name": "project_analysis",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "project_description": {"type": ["string", "null"]},
                    "project_description_confidence": {"type": "integer"},
                    "languages": {"type": ["array", "null"], "items": {"type": "string"}},
                    "languages_confidence": {"type": "integer"},
                    "frameworks": {"type": ["array", "null"], "items": {"type": "string"}},
                    "frameworks_confidence": {"type": "integer"},
                    "modules": {"type": ["array", "null"], "items": {"type": "string"}},
                    "modules_confidence": {"type": "integer"},
                    "entry_points": {"type": ["array", "null"], "items": {"type": "string"}},
                    "entry_points_confidence": {"type": "integer"},
                    "architecture": {"type": ["string", "null"]},
                    "architecture_confidence": {"type": "integer"},
                    "next_path": {"type": ["array", "null"], "items": {"type": "string"}},
                    "reasoning": {"type": "string"}
                },
                "required": [
                    "project_description", "project_description_confidence",
                    "languages", "languages_confidence",
                    "frameworks", "frameworks_confidence",
                    "modules", "modules_confidence",
                    "entry_points", "entry_points_confidence",
                    "architecture", "architecture_confidence",
                    "next_path", "reasoning"
                ],
                "additionalProperties": False
            }
        }

    def _validate_response(self, response: Dict[str, Any]) -> Tuple[bool, str]:
        """Validate LLM response."""
        required_confidence_fields = [
            "project_description_confidence",
            "languages_confidence",
            "frameworks_confidence",
            "modules_confidence",
            "entry_points_confidence",
            "architecture_confidence"
        ]

        for field in required_confidence_fields:
            if field not in response:
                return False, f"Missing field: {field}"

            value = response[field]
            if not isinstance(value, int) or not 0 <= value <= 100:
                return False, f"Invalid confidence value for {field}: {value}"

        return True, ""

    def _update_state_from_response(
        self,
        current_state: ProjectAnalysisResult,
        response: Dict[str, Any],
        files_analyzed: List[str],
        iteration: int
    ) -> ProjectAnalysisResult:
        """Update state from LLM response."""
        # Only update if new confidence is higher or field is empty
        def update_field(current: AnalysisField, new_value: Any, new_conf: int) -> AnalysisField:
            if new_conf > current.confidence or current.value is None:
                return AnalysisField(new_value, new_conf)
            return current

        return ProjectAnalysisResult(
            project_path=current_state.project_path,
            project_description=update_field(
                current_state.project_description,
                response.get("project_description"),
                response.get("project_description_confidence", 0)
            ),
            languages=update_field(
                current_state.languages,
                response.get("languages"),
                response.get("languages_confidence", 0)
            ),
            frameworks=update_field(
                current_state.frameworks,
                response.get("frameworks"),
                response.get("frameworks_confidence", 0)
            ),
            modules=update_field(
                current_state.modules,
                response.get("modules"),
                response.get("modules_confidence", 0)
            ),
            entry_points=update_field(
                current_state.entry_points,
                response.get("entry_points"),
                response.get("entry_points_confidence", 0)
            ),
            architecture=update_field(
                current_state.architecture,
                response.get("architecture"),
                response.get("architecture_confidence", 0)
            ),
            iteration_count=iteration,
            total_files_analyzed=len(files_analyzed),
            files_analyzed=files_analyzed,
            completed=False
        )

    def _state_to_dict(self, state: ProjectAnalysisResult) -> Dict[str, Any]:
        """Convert state to dictionary for snapshot."""
        return {
            "project_path": state.project_path,
            "project_description": state.project_description.value,
            "project_description_confidence": state.project_description.confidence,
            "languages": state.languages.value,
            "languages_confidence": state.languages.confidence,
            "frameworks": state.frameworks.value,
            "frameworks_confidence": state.frameworks.confidence,
            "modules": state.modules.value,
            "modules_confidence": state.modules.confidence,
            "entry_points": state.entry_points.value,
            "entry_points_confidence": state.entry_points.confidence,
            "architecture": state.architecture.value,
            "architecture_confidence": state.architecture.confidence,
            "iteration_count": state.iteration_count,
            "files_analyzed": state.files_analyzed,
            "completed": state.completed
        }
