"""Provider abstractions and implementations.

Architecture:
- base.py: Abstract interfaces (LLMProvider, EmbeddingProvider)
- openai_provider.py: OpenAI implementation (isolated)
- huggingface_provider.py: HuggingFace implementation (isolated)
- factory.py: Provider routing logic (knows about all providers)

Supported providers:
- OpenAI: LLM (Responses API) + Embeddings
- HuggingFace: LLM (Inference API) + Embeddings

Usage:
    from src.providers import create_providers_from_config
    llm, embedding = create_providers_from_config(config)
"""

# Base interfaces
from .base import (
    LLMProvider,
    EmbeddingProvider,
    ChatMessage,
    LLMResponse
)

# Factory (main entry point)
from .factory import create_providers_from_config

# Individual provider implementations (optional, for direct use)
from .openai_provider import (
    OpenAILLMProvider,
    OpenAIEmbeddingProvider
)

# HuggingFace providers (optional dependency)
try:
    from .huggingface_provider import (
        HuggingFaceLLMProvider,
        HuggingFaceEmbeddingProvider
    )
    _huggingface_available = True
except ImportError:
    _huggingface_available = False
    HuggingFaceLLMProvider = None
    HuggingFaceEmbeddingProvider = None


__all__ = [
    # Interfaces
    "LLMProvider",
    "EmbeddingProvider",
    "ChatMessage",
    "LLMResponse",

    # Factory (main API)
    "create_providers_from_config",

    # Concrete implementations (for direct instantiation)
    "OpenAILLMProvider",
    "OpenAIEmbeddingProvider",
]

if _huggingface_available:
    __all__.extend([
        "HuggingFaceLLMProvider",
        "HuggingFaceEmbeddingProvider"
    ])
