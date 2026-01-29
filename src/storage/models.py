"""Data models for the project indexer."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class ProjectContext:
    """Context information about the entire project."""

    project_name: str
    project_description: str
    tech_stack: List[str] = field(default_factory=list)
    frameworks: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    architecture_type: str = "unknown"
    project_structure: str = ""
    key_entry_points: List[str] = field(default_factory=list)
    build_system: str = "unknown"
    purpose: str = ""


@dataclass
class FileMetadata:
    """Metadata about a scanned file."""

    file_path: Path
    relative_path: Path
    file_size: int
    last_modified: float
    language: str
    file_type: str  # code|documentation|config|test
    hash: str  # SHA256 hash of content


@dataclass
class FunctionInfo:
    """Information about a function/method."""

    name: str
    description: str
    parameters: List[str] = field(default_factory=list)
    return_type: str = "unknown"


@dataclass
class CodeAnalysis:
    """Analysis result from OpenAI for a code file."""

    purpose: str
    dependencies: List[str] = field(default_factory=list)
    exported_symbols: List[str] = field(default_factory=list)
    key_functions: List[FunctionInfo] = field(default_factory=list)
    architectural_notes: str = ""


@dataclass
class CodeChunk:
    """A chunk of code from a larger file."""

    content: str
    chunk_index: int
    total_chunks: int
    start_line: int = 0
    end_line: int = 0


@dataclass
class IndexedDocument:
    """A document ready to be stored in ChromaDB."""

    id: str  # Format: {project_hash}:{relative_path}:{chunk_index}
    content: str  # Code or content
    embedding: Optional[List[float]]  # Will be generated
    metadata: Dict[str, any]


@dataclass
class SearchResult:
    """Result from semantic search."""

    file_path: str
    relative_path: str
    chunk_index: int
    score: float
    purpose: str
    dependencies: List[str]
    exported_symbols: List[str]
    code: Optional[str]
    metadata: Dict[str, any]
