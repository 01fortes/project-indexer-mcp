"""Language-specific AST analyzers with factory pattern."""

from typing import Optional
from .base import BaseLanguageAnalyzer
from .python_analyzer import PythonAnalyzer
from .kotlin_analyzer import KotlinAnalyzer
from .generic_analyzer import GenericAnalyzer


class AnalyzerFactory:
    """
    Factory for creating language-specific analyzers.

    Uses strategy pattern to delegate analysis to appropriate language analyzer.
    """

    # Registry of language-specific analyzers
    _analyzers = {
        'python': PythonAnalyzer,
        'kotlin': KotlinAnalyzer,
        'kt': KotlinAnalyzer,
        'kts': KotlinAnalyzer,
        # Add more as we implement them:
        # 'javascript': JavaScriptAnalyzer,
        # 'typescript': TypeScriptAnalyzer,
        # 'java': JavaAnalyzer,
        # 'go': GoAnalyzer,
        # 'rust': RustAnalyzer,
    }

    @classmethod
    def create_analyzer(cls, language: str) -> BaseLanguageAnalyzer:
        """
        Create appropriate analyzer for language.

        Args:
            language: Programming language (python, kotlin, javascript, etc.)

        Returns:
            Language-specific analyzer or generic analyzer
        """
        language = language.lower()

        # Check if we have a specific analyzer
        if language in cls._analyzers:
            return cls._analyzers[language]()

        # Fall back to generic analyzer
        return GenericAnalyzer(language)

    @classmethod
    def register_analyzer(cls, language: str, analyzer_class: type):
        """
        Register a new language analyzer.

        Allows for dynamic registration of new analyzers.

        Args:
            language: Language name
            analyzer_class: Analyzer class (must inherit from BaseLanguageAnalyzer)
        """
        cls._analyzers[language] = analyzer_class

    @classmethod
    def get_supported_languages(cls) -> list:
        """
        Get list of languages with specific analyzers.

        Returns:
            List of language names
        """
        return list(cls._analyzers.keys())


# Convenience function
def get_analyzer(language: str) -> BaseLanguageAnalyzer:
    """
    Get analyzer for language.

    Args:
        language: Programming language

    Returns:
        Language analyzer instance
    """
    return AnalyzerFactory.create_analyzer(language)


__all__ = [
    'BaseLanguageAnalyzer',
    'PythonAnalyzer',
    'KotlinAnalyzer',
    'GenericAnalyzer',
    'AnalyzerFactory',
    'get_analyzer'
]
