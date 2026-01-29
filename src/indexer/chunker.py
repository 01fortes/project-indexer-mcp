"""Code chunking for large files."""

from pathlib import Path
from typing import List

import tiktoken

from ..storage.models import CodeChunk
from ..utils.logger import get_logger

logger = get_logger(__name__)


def estimate_tokens(text: str, model: str = "gpt-4") -> int:
    """
    Estimate token count using tiktoken.

    Args:
        text: Text to count tokens for.
        model: Model name for tokenizer.

    Returns:
        Estimated token count.
    """
    try:
        encoding = tiktoken.encoding_for_model(model)
        return len(encoding.encode(text))
    except Exception as e:
        # Fallback: rough estimate
        logger.warning(f"Failed to use tiktoken: {e}, using fallback")
        return len(text) // 4  # Rough approximation


async def chunk_code_file(
    content: str,
    file_path: Path,
    language: str,
    max_tokens: int = 6000,
    overlap_tokens: int = 500
) -> List[CodeChunk]:
    """
    Intelligently chunk large code files.

    Args:
        content: File content.
        file_path: Path to file.
        language: Programming language.
        max_tokens: Maximum tokens per chunk.
        overlap_tokens: Overlap between chunks.

    Returns:
        List of CodeChunk objects.
    """
    # Estimate tokens
    total_tokens = estimate_tokens(content)

    # If small enough, return as single chunk
    if total_tokens <= max_tokens:
        return [CodeChunk(
            content=content,
            chunk_index=0,
            total_chunks=1,
            start_line=1,
            end_line=len(content.splitlines())
        )]

    logger.info(f"Chunking {file_path}: {total_tokens} tokens")

    # Split into lines
    lines = content.splitlines(keepends=True)

    # Try structure-aware chunking for supported languages
    if language in ['python', 'javascript', 'typescript']:
        chunks = await _structure_aware_chunk(lines, language, max_tokens, overlap_tokens)
        if chunks:
            return chunks

    # Fallback: line-based chunking
    return await _line_based_chunk(lines, max_tokens, overlap_tokens)


async def _structure_aware_chunk(
    lines: List[str],
    language: str,
    max_tokens: int,
    overlap_tokens: int
) -> List[CodeChunk]:
    """
    Attempt structure-aware chunking (simplified).

    This is a basic implementation. For production, use tree-sitter or ast module.

    Args:
        lines: File lines.
        language: Programming language.
        max_tokens: Max tokens per chunk.
        overlap_tokens: Overlap tokens.

    Returns:
        List of chunks or empty list if not possible.
    """
    # For simplicity, we'll do basic function/class detection for Python
    if language == "python":
        chunks = []
        current_chunk_lines = []
        current_chunk_tokens = 0
        chunk_index = 0
        start_line = 1

        for i, line in enumerate(lines, 1):
            # Check if it's a function or class definition
            is_boundary = line.strip().startswith(('def ', 'class ', 'async def '))

            line_tokens = estimate_tokens(line)

            # If adding this line exceeds max and we have content, create chunk
            if current_chunk_tokens + line_tokens > max_tokens and current_chunk_lines:
                chunk_content = ''.join(current_chunk_lines)
                chunks.append(CodeChunk(
                    content=chunk_content,
                    chunk_index=chunk_index,
                    total_chunks=0,  # Will update later
                    start_line=start_line,
                    end_line=i - 1
                ))

                # Start new chunk with overlap
                overlap_lines = []
                overlap_tokens_count = 0
                for ol in reversed(current_chunk_lines):
                    ol_tokens = estimate_tokens(ol)
                    if overlap_tokens_count + ol_tokens <= overlap_tokens:
                        overlap_lines.insert(0, ol)
                        overlap_tokens_count += ol_tokens
                    else:
                        break

                current_chunk_lines = overlap_lines
                current_chunk_tokens = overlap_tokens_count
                chunk_index += 1
                start_line = i

            current_chunk_lines.append(line)
            current_chunk_tokens += line_tokens

        # Add final chunk
        if current_chunk_lines:
            chunk_content = ''.join(current_chunk_lines)
            chunks.append(CodeChunk(
                content=chunk_content,
                chunk_index=chunk_index,
                total_chunks=0,
                start_line=start_line,
                end_line=len(lines)
            ))

        # Update total_chunks
        total = len(chunks)
        for chunk in chunks:
            chunk.total_chunks = total

        return chunks

    return []


async def _line_based_chunk(
    lines: List[str],
    max_tokens: int,
    overlap_tokens: int
) -> List[CodeChunk]:
    """
    Simple line-based chunking with overlap.

    Args:
        lines: File lines.
        max_tokens: Max tokens per chunk.
        overlap_tokens: Overlap tokens.

    Returns:
        List of CodeChunk objects.
    """
    chunks = []
    current_lines = []
    current_tokens = 0
    chunk_index = 0
    start_line = 1

    for i, line in enumerate(lines, 1):
        line_tokens = estimate_tokens(line)

        # If adding this line exceeds max, create chunk
        if current_tokens + line_tokens > max_tokens and current_lines:
            chunk_content = ''.join(current_lines)
            chunks.append(CodeChunk(
                content=chunk_content,
                chunk_index=chunk_index,
                total_chunks=0,
                start_line=start_line,
                end_line=i - 1
            ))

            # Calculate overlap
            overlap_lines = []
            overlap_tokens_count = 0
            for ol in reversed(current_lines):
                ol_tokens = estimate_tokens(ol)
                if overlap_tokens_count + ol_tokens <= overlap_tokens:
                    overlap_lines.insert(0, ol)
                    overlap_tokens_count += ol_tokens
                else:
                    break

            current_lines = overlap_lines
            current_tokens = overlap_tokens_count
            chunk_index += 1
            start_line = i

        current_lines.append(line)
        current_tokens += line_tokens

    # Add final chunk
    if current_lines:
        chunk_content = ''.join(current_lines)
        chunks.append(CodeChunk(
            content=chunk_content,
            chunk_index=chunk_index,
            total_chunks=0,
            start_line=start_line,
            end_line=len(lines)
        ))

    # Update total_chunks
    total = len(chunks)
    for chunk in chunks:
        chunk.total_chunks = total

    return chunks
