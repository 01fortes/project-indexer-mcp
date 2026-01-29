"""File scanning with gitignore support and pattern matching."""

import hashlib
from pathlib import Path
from typing import List, Optional, Tuple

import pathspec

from ..config import FilePatterns
from ..storage.models import FileMetadata
from ..utils.logger import get_logger

logger = get_logger(__name__)


# Language detection map
LANGUAGE_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".java": "java",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".c": "c",
    ".h": "c",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".md": "markdown",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
}


async def scan_project(
    project_path: Path,
    include_patterns: List[str],
    exclude_patterns: List[str],
    respect_gitignore: bool = True,
    max_file_size_mb: float = 1.0
) -> List[FileMetadata]:
    """
    Scan project directory and return file metadata.

    Args:
        project_path: Project root path.
        include_patterns: Glob patterns to include.
        exclude_patterns: Glob patterns to exclude.
        respect_gitignore: Whether to respect .gitignore rules.
        max_file_size_mb: Maximum file size in MB.

    Returns:
        List of FileMetadata for files to index.
    """
    logger.info(f"Scanning project: {project_path}")

    # Get gitignore spec if needed
    gitignore_spec = None
    if respect_gitignore:
        gitignore_spec = await get_gitignore_spec(project_path)

    # Create pathspec for include/exclude patterns
    include_spec = pathspec.PathSpec.from_lines('gitwildmatch', include_patterns)
    exclude_spec = pathspec.PathSpec.from_lines('gitwildmatch', exclude_patterns)

    files = []
    max_size_bytes = int(max_file_size_mb * 1024 * 1024)

    # Walk directory tree
    for file_path in project_path.rglob('*'):
        if not file_path.is_file():
            continue

        try:
            relative_path = file_path.relative_to(project_path)
            relative_str = str(relative_path)

            # Check gitignore
            if gitignore_spec and gitignore_spec.match_file(relative_str):
                continue

            # Check exclude patterns
            if exclude_spec.match_file(relative_str):
                continue

            # Check include patterns
            if not include_spec.match_file(relative_str):
                continue

            # Check file size
            file_size = file_path.stat().st_size
            should_index, reason = should_index_file(file_path, file_size, max_size_bytes)

            if not should_index:
                logger.debug(f"Skipping {relative_path}: {reason}")
                continue

            # Get file metadata
            language = detect_language(file_path)
            file_type = classify_file_type(file_path)
            file_hash = await calculate_file_hash(file_path)

            metadata = FileMetadata(
                file_path=file_path,
                relative_path=relative_path,
                file_size=file_size,
                last_modified=file_path.stat().st_mtime,
                language=language,
                file_type=file_type,
                hash=file_hash
            )

            files.append(metadata)

        except Exception as e:
            logger.warning(f"Error scanning {file_path}: {e}")
            continue

    logger.info(f"Found {len(files)} files to index")
    return files


async def get_gitignore_spec(project_path: Path) -> Optional[pathspec.PathSpec]:
    """
    Parse .gitignore into pathspec.

    Args:
        project_path: Project root path.

    Returns:
        PathSpec object or None if .gitignore doesn't exist.
    """
    gitignore_path = project_path / '.gitignore'
    if not gitignore_path.exists():
        return None

    try:
        with open(gitignore_path, 'r') as f:
            patterns = f.read().splitlines()
        return pathspec.PathSpec.from_lines('gitwildmatch', patterns)
    except Exception as e:
        logger.warning(f"Failed to parse .gitignore: {e}")
        return None


def should_index_file(
    file_path: Path,
    file_size: int,
    max_size_bytes: int
) -> Tuple[bool, Optional[str]]:
    """
    Determine if file should be indexed.

    Args:
        file_path: Path to file.
        file_size: File size in bytes.
        max_size_bytes: Maximum allowed size.

    Returns:
        Tuple of (should_index, reason_if_not).
    """
    # Check size
    if file_size > max_size_bytes:
        return False, f"File too large: {file_size / 1024 / 1024:.2f}MB"

    if file_size == 0:
        return False, "Empty file"

    # Check for binary files by extension
    binary_extensions = [
        '.png', '.jpg', '.jpeg', '.gif', '.pdf', '.zip', '.tar', '.gz',
        '.ico', '.woff', '.woff2', '.ttf', '.eot', '.pyc', '.so', '.dll',
        '.exe', '.bin', '.dat'
    ]

    if file_path.suffix.lower() in binary_extensions:
        return False, "Binary file"

    return True, None


def detect_language(file_path: Path) -> str:
    """
    Detect programming language from file extension.

    Args:
        file_path: Path to file.

    Returns:
        Language name or 'unknown'.
    """
    return LANGUAGE_MAP.get(file_path.suffix.lower(), "unknown")


def classify_file_type(file_path: Path) -> str:
    """
    Classify file as code, test, documentation, or config.

    Args:
        file_path: Path to file.

    Returns:
        File type: code|test|documentation|config.
    """
    path_str = str(file_path).lower()

    # Documentation
    if any(doc in path_str for doc in ['readme', 'contributing', 'changelog', 'license', 'docs/']):
        return "documentation"

    if file_path.suffix.lower() in ['.md', '.rst', '.txt']:
        return "documentation"

    # Configuration
    if any(cfg in file_path.name.lower() for cfg in ['config', 'settings', '.env', 'dockerfile']):
        return "config"

    if file_path.suffix.lower() in ['.json', '.yaml', '.yml', '.toml', '.ini', '.conf', '.xml']:
        # Check if it's package.json or similar (not config)
        if file_path.name in ['package.json', 'pyproject.toml', 'Cargo.toml']:
            return "config"
        # Other JSON/YAML might be data or config
        return "config"

    # Tests
    if any(test in path_str for test in ['test', 'tests', 'spec', '__test__', '.test.', '.spec.']):
        return "test"

    # Default to code
    return "code"


async def calculate_file_hash(file_path: Path) -> str:
    """
    Calculate SHA256 hash of file content.

    Args:
        file_path: Path to file.

    Returns:
        Hex digest of SHA256 hash.
    """
    hasher = hashlib.sha256()
    try:
        with open(file_path, 'rb') as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception as e:
        logger.warning(f"Failed to hash {file_path}: {e}")
        return ""
