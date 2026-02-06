"""Repository for managing project analysis data (Index 1)."""

from pathlib import Path
from typing import Optional

from .checkpoint_manager import CheckpointManager
from .models import AnalysisField, ProjectAnalysisResult
from ..utils.logger import get_logger

logger = get_logger(__name__)


class AnalysisRepository:
    """
    Repository for storing and retrieving project analysis results.

    Works with the unified CheckpointManager to persist Index 1 data.
    """

    def __init__(self, checkpoint_manager: CheckpointManager):
        """
        Initialize repository.

        Args:
            checkpoint_manager: Unified checkpoint manager instance
        """
        self.checkpoint_manager = checkpoint_manager

    def save_analysis(self, analysis: ProjectAnalysisResult) -> None:
        """
        Save or update project analysis result.

        Args:
            analysis: ProjectAnalysisResult to save
        """
        self.checkpoint_manager.save_project_analysis(
            project_path=analysis.project_path,
            project_description=analysis.project_description.value,
            project_description_confidence=analysis.project_description.confidence,
            languages=analysis.languages.value or [],
            languages_confidence=analysis.languages.confidence,
            frameworks=analysis.frameworks.value or [],
            frameworks_confidence=analysis.frameworks.confidence,
            modules=analysis.modules.value or [],
            modules_confidence=analysis.modules.confidence,
            entry_points=analysis.entry_points.value or [],
            entry_points_confidence=analysis.entry_points.confidence,
            architecture=analysis.architecture.value,
            architecture_confidence=analysis.architecture.confidence,
            iteration_count=analysis.iteration_count,
            files_analyzed=analysis.files_analyzed,
            completed=analysis.completed
        )
        logger.debug(f"Saved analysis for {analysis.project_path}")

    def get_analysis(self, project_path: str) -> Optional[ProjectAnalysisResult]:
        """
        Get project analysis result.

        Args:
            project_path: Path to project root

        Returns:
            ProjectAnalysisResult or None if not found
        """
        data = self.checkpoint_manager.get_project_analysis(project_path)

        if not data:
            return None

        return ProjectAnalysisResult(
            project_path=data["project_path"],
            project_description=AnalysisField(
                data["project_description"],
                data["project_description_confidence"]
            ),
            languages=AnalysisField(
                data["languages"],
                data["languages_confidence"]
            ),
            frameworks=AnalysisField(
                data["frameworks"],
                data["frameworks_confidence"]
            ),
            modules=AnalysisField(
                data["modules"],
                data["modules_confidence"]
            ),
            entry_points=AnalysisField(
                data["entry_points"],
                data["entry_points_confidence"]
            ),
            architecture=AnalysisField(
                data["architecture"],
                data["architecture_confidence"]
            ),
            iteration_count=data["iteration_count"],
            total_files_analyzed=len(data["files_analyzed"]),
            files_analyzed=data["files_analyzed"],
            completed=data["completed"]
        )

    def save_iteration(
        self,
        project_path: str,
        iteration: int,
        files_requested: list,
        files_read: list,
        snapshot: dict
    ) -> None:
        """
        Save analysis iteration snapshot.

        Args:
            project_path: Path to project root
            iteration: Iteration number
            files_requested: Files that were requested to read
            files_read: Files that were actually read
            snapshot: Full state snapshot
        """
        self.checkpoint_manager.save_analysis_iteration(
            project_path=project_path,
            iteration=iteration,
            files_requested=files_requested,
            files_read=files_read,
            snapshot=snapshot
        )
        logger.debug(f"Saved iteration {iteration} for {project_path}")

    def get_last_iteration(self, project_path: str) -> Optional[dict]:
        """
        Get the last analysis iteration for a project.

        Args:
            project_path: Path to project root

        Returns:
            Dictionary with iteration data or None
        """
        return self.checkpoint_manager.get_last_iteration(project_path)

    def clear_project(self, project_path: str) -> None:
        """
        Clear all analysis data for a project.

        Args:
            project_path: Path to project root
        """
        self.checkpoint_manager.clear_project_analysis(project_path)
        logger.info(f"Cleared analysis data for {project_path}")

    def is_analysis_complete(self, project_path: str) -> bool:
        """
        Check if project analysis is complete.

        Args:
            project_path: Path to project root

        Returns:
            True if analysis is complete
        """
        analysis = self.get_analysis(project_path)
        return analysis is not None and analysis.completed

    def get_analysis_summary(self, project_path: str) -> Optional[dict]:
        """
        Get a summary of project analysis for display.

        Args:
            project_path: Path to project root

        Returns:
            Dictionary with analysis summary or None
        """
        analysis = self.get_analysis(project_path)
        if not analysis:
            return None

        return {
            "project_path": analysis.project_path,
            "project_name": Path(analysis.project_path).name,
            "description": analysis.project_description.value,
            "description_confidence": analysis.project_description.confidence,
            "languages": analysis.languages.value,
            "languages_confidence": analysis.languages.confidence,
            "frameworks": analysis.frameworks.value,
            "frameworks_confidence": analysis.frameworks.confidence,
            "modules": analysis.modules.value,
            "modules_confidence": analysis.modules.confidence,
            "entry_points": analysis.entry_points.value,
            "entry_points_confidence": analysis.entry_points.confidence,
            "architecture": analysis.architecture.value,
            "architecture_confidence": analysis.architecture.confidence,
            "min_confidence": analysis.min_confidence(),
            "iteration_count": analysis.iteration_count,
            "files_analyzed_count": len(analysis.files_analyzed),
            "completed": analysis.completed
        }
