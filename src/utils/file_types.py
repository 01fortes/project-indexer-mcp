"""File type detection utilities."""

from pathlib import Path
from typing import Optional


def is_binary_file(file_path: Path) -> bool:
    """
    Check if file is binary.

    Args:
        file_path: Path to file.

    Returns:
        True if binary, False otherwise.
    """
    binary_extensions = {
        '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico',
        '.pdf', '.zip', '.tar', '.gz', '.bz2', '.7z',
        '.exe', '.dll', '.so', '.dylib',
        '.woff', '.woff2', '.ttf', '.eot',
        '.pyc', '.pyo', '.class',
        '.o', '.obj', '.bin', '.dat'
    }

    return file_path.suffix.lower() in binary_extensions


def detect_language(file_path: Path) -> Optional[str]:
    """
    Detect programming language from file extension.

    Args:
        file_path: Path to file

    Returns:
        Language name or None if not recognized
    """
    extension = file_path.suffix.lower()

    language_map = {
        '.py': 'python',
        '.js': 'javascript',
        '.jsx': 'javascript',
        '.ts': 'typescript',
        '.tsx': 'typescript',
        '.go': 'go',
        '.rs': 'rust',
        '.java': 'java',
        '.kt': 'kotlin',
        '.kts': 'kotlin',
        '.c': 'c',
        '.h': 'c',
        '.cpp': 'cpp',
        '.cc': 'cpp',
        '.cxx': 'cpp',
        '.hpp': 'cpp',
        '.cs': 'c_sharp',
        '.rb': 'ruby',
        '.php': 'php',
        '.swift': 'swift',
        '.scala': 'scala',
    }

    return language_map.get(extension)
