"""Data models for the project indexer."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


# =============================================================================
# Index 1: Project Analysis Models
# =============================================================================

@dataclass
class AnalysisField:
    """A field with a confidence score from iterative analysis."""
    value: Any  # str | List[str] | None
    confidence: int  # 0-100

    def __post_init__(self):
        """Validate confidence range."""
        if not 0 <= self.confidence <= 100:
            raise ValueError(f"Confidence must be 0-100, got {self.confidence}")


@dataclass
class ProjectAnalysisResult:
    """Result of iterative project analysis (Index 1)."""
    project_path: str
    project_description: AnalysisField = field(default_factory=lambda: AnalysisField(None, 0))
    languages: AnalysisField = field(default_factory=lambda: AnalysisField([], 0))
    frameworks: AnalysisField = field(default_factory=lambda: AnalysisField([], 0))
    modules: AnalysisField = field(default_factory=lambda: AnalysisField([], 0))
    entry_points: AnalysisField = field(default_factory=lambda: AnalysisField([], 0))
    architecture: AnalysisField = field(default_factory=lambda: AnalysisField(None, 0))
    iteration_count: int = 0
    total_files_analyzed: int = 0
    files_analyzed: List[str] = field(default_factory=list)
    completed: bool = False

    def min_confidence(self) -> int:
        """Return the minimum confidence across all fields."""
        return min(
            self.project_description.confidence,
            self.languages.confidence,
            self.frameworks.confidence,
            self.modules.confidence,
            self.entry_points.confidence,
            self.architecture.confidence
        )

    def avg_confidence(self) -> int:
        """Return average confidence across all fields."""
        confidences = [
            self.project_description.confidence,
            self.languages.confidence,
            self.frameworks.confidence,
            self.modules.confidence,
            self.entry_points.confidence,
            self.architecture.confidence
        ]
        return sum(confidences) // len(confidences)

    def to_project_context(self) -> "ProjectContext":
        """Convert to ProjectContext for backward compatibility."""
        return ProjectContext(
            project_name=Path(self.project_path).name,
            project_description=self.project_description.value or "",
            tech_stack=self.languages.value or [],
            frameworks=self.frameworks.value or [],
            dependencies=[],
            architecture_type=self.architecture.value or "unknown",
            project_structure="",
            key_entry_points=self.entry_points.value or [],
            build_system="unknown",
            purpose=self.project_description.value or ""
        )


# =============================================================================
# Index 3: Function Extraction Models
# =============================================================================

@dataclass
class ExtractedFunction:
    """A function extracted from source code via AST analysis."""
    name: str
    file_path: str
    line_start: int
    line_end: int
    code: str
    parameters: List[str]
    return_type: Optional[str] = None
    is_async: bool = False
    is_method: bool = False
    class_name: Optional[str] = None
    decorators: List[str] = field(default_factory=list)
    docstring: Optional[str] = None


@dataclass
class AnalyzedFunction:
    """A function with LLM-generated analysis (extends ExtractedFunction)."""
    # From ExtractedFunction
    name: str
    file_path: str
    line_start: int
    line_end: int
    code: str
    parameters: List[str]
    return_type: Optional[str] = None
    is_async: bool = False
    is_method: bool = False
    class_name: Optional[str] = None
    decorators: List[str] = field(default_factory=list)
    docstring: Optional[str] = None

    # LLM analysis
    description: str = ""
    purpose: str = ""
    input_description: str = ""
    output_description: str = ""
    side_effects: List[str] = field(default_factory=list)
    complexity: str = "medium"  # low/medium/high

    @classmethod
    def from_extracted(cls, func: ExtractedFunction, analysis: Dict[str, Any]) -> "AnalyzedFunction":
        """Create AnalyzedFunction from ExtractedFunction and LLM analysis."""
        return cls(
            name=func.name,
            file_path=func.file_path,
            line_start=func.line_start,
            line_end=func.line_end,
            code=func.code,
            parameters=func.parameters,
            return_type=func.return_type,
            is_async=func.is_async,
            is_method=func.is_method,
            class_name=func.class_name,
            decorators=func.decorators,
            docstring=func.docstring,
            description=analysis.get("description", ""),
            purpose=analysis.get("purpose", ""),
            input_description=analysis.get("input_description", ""),
            output_description=analysis.get("output_description", ""),
            side_effects=analysis.get("side_effects", []),
            complexity=analysis.get("complexity", "medium")
        )


# =============================================================================
# Existing Models (Index 2 and shared)
# =============================================================================

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
