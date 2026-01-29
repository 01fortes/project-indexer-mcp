"""Embedding generation using OpenAI."""

from pathlib import Path
from typing import List, Optional

from openai import AsyncOpenAI

from ..storage.models import CodeAnalysis, ProjectContext
from ..utils.logger import get_logger

logger = get_logger(__name__)


async def generate_embedding(
    text: str,
    client: AsyncOpenAI,
    model: str = "text-embedding-3-small"
) -> List[float]:
    """
    Generate embedding for text using OpenAI.

    Args:
        text: Text to embed.
        client: OpenAI async client.
        model: Embedding model to use.

    Returns:
        List of floats representing the embedding.
    """
    try:
        response = await client.embeddings.create(
            input=text,
            model=model
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"Failed to generate embedding: {e}")
        raise


async def batch_generate_embeddings(
    texts: List[str],
    client: AsyncOpenAI,
    model: str = "text-embedding-3-small",
    max_batch_size: int = 100
) -> List[List[float]]:
    """
    Generate embeddings for multiple texts in batches.

    Args:
        texts: List of texts to embed.
        client: OpenAI async client.
        model: Embedding model to use.
        max_batch_size: Maximum batch size.

    Returns:
        List of embeddings.
    """
    embeddings = []

    # Process in batches
    for i in range(0, len(texts), max_batch_size):
        batch = texts[i:i + max_batch_size]
        logger.debug(f"Generating embeddings for batch {i // max_batch_size + 1}")

        try:
            response = await client.embeddings.create(
                input=batch,
                model=model
            )
            batch_embeddings = [item.embedding for item in response.data]
            embeddings.extend(batch_embeddings)

        except Exception as e:
            logger.error(f"Failed to generate embeddings for batch: {e}")
            # Generate individually for this batch
            for text in batch:
                try:
                    emb = await generate_embedding(text, client, model)
                    embeddings.append(emb)
                except:
                    # Use zero vector as fallback
                    embeddings.append([0.0] * 1536)

    return embeddings


def prepare_embedding_text(
    code: str,
    file_path: Path,
    analysis: CodeAnalysis,
    project_context: Optional[ProjectContext] = None
) -> str:
    """
    Prepare text for embedding generation.

    Combines code, analysis, and project context for better semantic search.

    Args:
        code: Original code.
        file_path: File path.
        analysis: Code analysis result.
        project_context: Optional project context.

    Returns:
        Formatted text for embedding.
    """
    parts = []

    # Add project context if available
    if project_context:
        parts.append(f"Project: {project_context.project_name}")
        if project_context.tech_stack:
            parts.append(f"Stack: {', '.join(project_context.tech_stack[:5])}")

    # Add file info
    parts.append(f"File: {file_path}")

    # Add analysis
    if analysis.purpose:
        parts.append(f"Purpose: {analysis.purpose}")

    if analysis.exported_symbols:
        parts.append(f"Exports: {', '.join(analysis.exported_symbols[:10])}")

    if analysis.dependencies:
        parts.append(f"Dependencies: {', '.join(analysis.dependencies[:10])}")

    if analysis.key_functions:
        func_summaries = []
        for func in analysis.key_functions[:5]:  # Limit to 5 functions
            params_str = ', '.join(func.parameters)
            func_summaries.append(f"{func.name}({params_str}): {func.description}")
        if func_summaries:
            parts.append("Functions:\n" + "\n".join(func_summaries))

    # Add code (truncated if needed)
    code_preview = code[:2000] if len(code) > 2000 else code
    parts.append(f"\nCode:\n{code_preview}")

    return "\n".join(parts)
