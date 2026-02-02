"""Provider factory - creates LLM and Embedding providers from configuration.

This module contains all the routing logic for selecting and instantiating
the correct provider based on configuration. Individual provider implementations
know nothing about each other.
"""

from typing import Tuple

from ..config import Config
from .base import LLMProvider, EmbeddingProvider
from ..utils.logger import get_logger

logger = get_logger(__name__)


def create_providers_from_config(config: Config) -> Tuple[LLMProvider, EmbeddingProvider]:
    """
    Factory function to create LLM and Embedding providers from configuration.

    This is the single entry point for provider creation. All routing logic
    is encapsulated here. Individual provider modules don't know about each other.

    Args:
        config: Configuration object with provider settings

    Returns:
        Tuple of (llm_provider, embedding_provider)

    Raises:
        ValueError: If provider is not supported or required settings are missing
        ImportError: If required dependencies are not installed
    """
    llm_provider = _create_llm_provider(config)
    embedding_provider = _create_embedding_provider(config)

    logger.info(
        f"Initialized providers: LLM={llm_provider.model_name}, "
        f"Embedding={embedding_provider.model_name}"
    )

    return llm_provider, embedding_provider


def _create_llm_provider(config: Config) -> LLMProvider:
    """
    Create LLM provider based on configuration.

    Args:
        config: Configuration object

    Returns:
        LLM provider instance

    Raises:
        ValueError: If provider not supported or settings missing
        ImportError: If required dependencies not installed
    """
    provider_type = config.provider.llm_provider.lower()

    if provider_type == "openai":
        return _create_openai_llm(config)
    elif provider_type == "huggingface":
        return _create_huggingface_llm(config)
    else:
        raise ValueError(
            f"Unsupported LLM provider: '{config.provider.llm_provider}'. "
            f"Supported providers: openai, huggingface"
        )


def _create_embedding_provider(config: Config) -> EmbeddingProvider:
    """
    Create Embedding provider based on configuration.

    Args:
        config: Configuration object

    Returns:
        Embedding provider instance

    Raises:
        ValueError: If provider not supported or settings missing
        ImportError: If required dependencies not installed
    """
    provider_type = config.provider.embedding_provider.lower()

    if provider_type == "openai":
        return _create_openai_embedding(config)
    elif provider_type == "huggingface":
        return _create_huggingface_embedding(config)
    else:
        raise ValueError(
            f"Unsupported Embedding provider: '{config.provider.embedding_provider}'. "
            f"Supported providers: openai, huggingface"
        )


# ============================================================================
# OpenAI Provider Creation
# ============================================================================

def _create_openai_llm(config: Config) -> LLMProvider:
    """Create OpenAI LLM provider."""
    if not config.provider.llm_api_key:
        raise ValueError(
            "OpenAI API key is required for LLM. "
            "Set LLM_API_KEY or OPENAI_API_KEY environment variable."
        )

    from .openai_provider import OpenAILLMProvider

    return OpenAILLMProvider(
        api_key=config.provider.llm_api_key,
        model=config.provider.llm_model,
        reasoning_effort=config.provider.reasoning_effort,
        max_retries=config.provider.max_retries,
        timeout=config.provider.timeout
    )


def _create_openai_embedding(config: Config) -> EmbeddingProvider:
    """Create OpenAI Embedding provider."""
    if not config.provider.embedding_api_key:
        raise ValueError(
            "OpenAI API key is required for embeddings. "
            "Set EMBEDDING_API_KEY or OPENAI_API_KEY environment variable."
        )

    from .openai_provider import OpenAIEmbeddingProvider

    return OpenAIEmbeddingProvider(
        api_key=config.provider.embedding_api_key,
        model=config.provider.embedding_model,
        max_retries=config.provider.max_retries,
        timeout=config.provider.timeout
    )


# ============================================================================
# HuggingFace Provider Creation
# ============================================================================

def _create_huggingface_llm(config: Config) -> LLMProvider:
    """Create HuggingFace LLM provider."""
    if not config.provider.llm_api_key:
        raise ValueError(
            "HuggingFace token is required for LLM. "
            "Set LLM_API_KEY, HUGGINGFACE_TOKEN, or HF_TOKEN environment variable."
        )

    try:
        from .huggingface_provider import HuggingFaceLLMProvider
    except ImportError as e:
        raise ImportError(
            "HuggingFace provider requires additional dependencies. "
            "Install with: pip install -r requirements-huggingface.txt"
        ) from e

    return HuggingFaceLLMProvider(
        model=config.provider.llm_model,
        api_key=config.provider.llm_api_key,
        base_url=config.provider.llm_base_url,
        max_retries=config.provider.max_retries,
        timeout=config.provider.timeout
    )


def _create_huggingface_embedding(config: Config) -> EmbeddingProvider:
    """Create HuggingFace Embedding provider."""
    if not config.provider.embedding_api_key:
        raise ValueError(
            "HuggingFace token is required for embeddings. "
            "Set EMBEDDING_API_KEY, HUGGINGFACE_TOKEN, or HF_TOKEN environment variable."
        )

    try:
        from .huggingface_provider import HuggingFaceEmbeddingProvider
    except ImportError as e:
        raise ImportError(
            "HuggingFace provider requires additional dependencies. "
            "Install with: pip install -r requirements-huggingface.txt"
        ) from e

    return HuggingFaceEmbeddingProvider(
        model=config.provider.embedding_model,
        api_key=config.provider.embedding_api_key,
        base_url=config.provider.embedding_base_url,
        timeout=config.provider.timeout
    )


# ============================================================================
# Future: Add more providers here
# ============================================================================
# def _create_anthropic_llm(config: Config) -> LLMProvider:
#     """Create Anthropic (Claude) LLM provider."""
#     pass
#
# def _create_local_llm(config: Config) -> LLMProvider:
#     """Create local/custom LLM provider."""
#     pass
