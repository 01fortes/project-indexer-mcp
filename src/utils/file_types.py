"""File type detection utilities."""

from pathlib import Path


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
