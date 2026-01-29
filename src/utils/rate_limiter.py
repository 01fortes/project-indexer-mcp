"""Rate limiter for OpenAI API calls using token bucket algorithm."""

import asyncio
import time
from typing import Callable, TypeVar

from ..utils.logger import get_logger

logger = get_logger(__name__)

T = TypeVar('T')


class RateLimiter:
    """
    Token bucket rate limiter for API calls.

    Limits both requests per minute (RPM) and tokens per minute (TPM).
    """

    def __init__(self, rpm: int, tpm: int):
        """
        Initialize rate limiter.

        Args:
            rpm: Requests per minute limit.
            tpm: Tokens per minute limit.
        """
        self.rpm = rpm
        self.tpm = tpm

        # Token buckets
        self.request_tokens = rpm
        self.token_tokens = tpm

        # Last refill times
        self.last_request_refill = time.time()
        self.last_token_refill = time.time()

        # Lock for thread safety
        self.lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1, request_count: int = 1) -> None:
        """
        Wait if necessary to acquire rate limit tokens.

        Args:
            tokens: Number of tokens (for TPM limit).
            request_count: Number of requests (for RPM limit).
        """
        async with self.lock:
            while True:
                # Refill buckets based on elapsed time
                now = time.time()

                # Refill request tokens
                time_since_request_refill = now - self.last_request_refill
                self.request_tokens = min(
                    self.rpm,
                    self.request_tokens + (time_since_request_refill / 60.0) * self.rpm
                )
                self.last_request_refill = now

                # Refill token tokens
                time_since_token_refill = now - self.last_token_refill
                self.token_tokens = min(
                    self.tpm,
                    self.token_tokens + (time_since_token_refill / 60.0) * self.tpm
                )
                self.last_token_refill = now

                # Check if we have enough tokens
                if self.request_tokens >= request_count and self.token_tokens >= tokens:
                    # Consume tokens
                    self.request_tokens -= request_count
                    self.token_tokens -= tokens
                    break

                # Calculate wait time
                wait_time_requests = (request_count - self.request_tokens) / (self.rpm / 60.0)
                wait_time_tokens = (tokens - self.token_tokens) / (self.tpm / 60.0)
                wait_time = max(wait_time_requests, wait_time_tokens, 0.1)

                logger.debug(f"Rate limit reached, waiting {wait_time:.2f}s")
                await asyncio.sleep(wait_time)

    async def execute_with_retry(
        self,
        func: Callable[[], T],
        max_retries: int = 3,
        base_delay: float = 1.0
    ) -> T:
        """
        Execute function with automatic retry on rate limit errors.

        Args:
            func: Async function to execute.
            max_retries: Maximum number of retries.
            base_delay: Base delay for exponential backoff.

        Returns:
            Result of function call.

        Raises:
            Exception: If all retries fail.
        """
        for attempt in range(max_retries):
            try:
                result = await func()
                return result

            except Exception as e:
                error_str = str(e).lower()

                # Check if it's a rate limit error
                if "rate" in error_str or "429" in error_str or "too many requests" in error_str:
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(f"Rate limit error, retrying in {delay}s (attempt {attempt + 1}/{max_retries})")
                        await asyncio.sleep(delay)
                        continue

                # Check if it's a timeout error
                if "timeout" in error_str or "timed out" in error_str:
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(f"Timeout error, retrying in {delay}s (attempt {attempt + 1}/{max_retries})")
                        await asyncio.sleep(delay)
                        continue

                # Other errors or last attempt - raise
                logger.error(f"Error executing function: {e}")
                raise

        raise Exception(f"Failed after {max_retries} retries")
