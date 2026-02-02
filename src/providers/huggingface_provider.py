"""Hugging Face provider for LLM and Embeddings via OpenAI-compatible API."""

import json
from typing import List, Dict, Any, Optional

from openai import AsyncOpenAI

from ..providers.base import LLMProvider, EmbeddingProvider, ChatMessage, LLMResponse
from ..utils.logger import get_logger

logger = get_logger(__name__)


class HuggingFaceLLMProvider(LLMProvider):
    """
    LLM provider using Hugging Face OpenAI-compatible API.

    Uses: https://router.huggingface.co/v1
    Compatible with OpenAI API format.
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: Optional[str] = None,
        max_retries: int = 3,
        timeout: int = 60
    ):
        """
        Initialize Hugging Face LLM provider.

        Args:
            model: Model ID on Hugging Face (e.g., "meta-llama/Llama-3.1-70B-Instruct")
            api_key: Hugging Face API token (HF_TOKEN)
            base_url: Custom endpoint (default: https://router.huggingface.co/v1)
            max_retries: Maximum retry attempts
            timeout: Request timeout in seconds
        """
        self._model = model
        self.api_key = api_key

        # Use HuggingFace router by default
        if base_url is None:
            base_url = "https://router.huggingface.co/v1"

        # Clean API key (remove whitespace)
        api_key = api_key.strip() if api_key else api_key

        # Initialize OpenAI-compatible client
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            max_retries=max_retries,
            timeout=timeout
        )

        # Debug: log token prefix (first 10 chars)
        if api_key:
            logger.info(f"Initialized Hugging Face LLM: {model} (token: {api_key[:10]}...)")
        else:
            logger.warning("Hugging Face token is empty!")

    async def chat_completion(
        self,
        messages: List[ChatMessage],
        response_format: Optional[Dict[str, Any]] = None,
        use_reasoning: Optional[bool] = None
    ) -> LLMResponse:
        """
        Perform chat completion using Hugging Face API.

        Args:
            messages: List of chat messages
            response_format: Optional response format (JSON schema)
            use_reasoning: Ignored for HuggingFace

        Returns:
            LLMResponse with generated text
        """
        # Convert messages to OpenAI format
        openai_messages = []
        for msg in messages:
            openai_messages.append({
                "role": msg.role,
                "content": msg.content
            })

        # Add JSON instruction if needed
        if response_format and response_format.get("type") == "json_schema":
            # Get schema if available
            schema_info = response_format.get("json_schema", {})
            schema_name = schema_info.get("name", "response")
            schema_def = schema_info.get("schema", {})

            # Format schema for display
            schema_text = json.dumps(schema_def, indent=2) if schema_def else "Not provided"

            # Create detailed JSON instruction
            json_instruction = f"""

CRITICAL INSTRUCTIONS - READ CAREFULLY:
1. You MUST respond with ONLY valid JSON. No markdown, no code blocks, no explanations, no reasoning.
2. Do NOT wrap your response in ```json or ``` tags.
3. Do NOT add any text before or after the JSON object.
4. Start your response IMMEDIATELY with {{ and end with }}
5. Ensure all JSON is properly formatted with correct quotes and commas.
6. All string values must use double quotes ("), not single quotes (').

REQUIRED JSON SCHEMA: {schema_name}
{schema_text}

Example of CORRECT response:
{{"purpose": "example", "dependencies": ["dep1"], "exported_symbols": []}}

Example of INCORRECT responses:
❌ ```json {{"field": "value"}}```
❌ Here is the JSON: {{"field": "value"}}
❌ {{'field': 'value'}}  (single quotes)

Your ENTIRE response must be pure JSON that can be directly parsed by json.loads().
DO NOT include any reasoning, explanations, or additional text."""

            if openai_messages and openai_messages[0]["role"] == "system":
                openai_messages[0]["content"] += json_instruction
            else:
                openai_messages.insert(0, {
                    "role": "system",
                    "content": f"You are a code analysis expert.{json_instruction}"
                })

        try:
            # Call HuggingFace via OpenAI-compatible API
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=openai_messages,
                temperature=0.1,  # Lower for code analysis
                max_tokens=4000,
                stream=False  # Explicitly disable streaming
            )

            # Extract content
            content = response.choices[0].message.content

            # Log raw response for debugging
            if response_format and response_format.get("type") == "json_schema":
                logger.debug(f"Raw response (first 200 chars): {content[:200]}")

            # Validate JSON if needed
            if response_format and response_format.get("type") == "json_schema":
                try:
                    json.loads(content)
                    logger.debug("Response is valid JSON")
                except json.JSONDecodeError as e:
                    logger.warning(f"Response is not valid JSON: {e}")
                    logger.warning("Attempting to extract JSON from response")
                    import re

                    # Try multiple extraction strategies
                    # 1. Try to extract JSON from markdown code blocks
                    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
                    if json_match:
                        content = json_match.group(1)
                        logger.debug("Extracted JSON from markdown block")
                    else:
                        # 2. Try to find JSON object in text
                        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', content, re.DOTALL)
                        if json_match:
                            content = json_match.group(0)
                            logger.debug("Extracted JSON from text")
                        else:
                            # 3. Last resort: wrap text in minimal JSON
                            logger.error(f"Could not extract JSON, response: {content[:500]}")
                            raise ValueError(
                                f"Model did not return valid JSON. "
                                f"Consider using a model that supports JSON mode. "
                                f"Response: {content[:200]}..."
                            )

            return LLMResponse(
                content=content,
                model=response.model,
                usage={
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0
                }
            )

        except Exception as e:
            logger.error(f"Hugging Face API error: {e}")
            logger.error(f"Model: {self._model}")
            logger.error(f"API key starts with: {self.api_key[:10] if self.api_key else 'None'}...")
            logger.error(f"Base URL: {self._client.base_url}")
            raise

    @property
    def model_name(self) -> str:
        """Return model name."""
        return self._model


class HuggingFaceEmbeddingProvider(EmbeddingProvider):
    """
    Embedding provider using Hugging Face Inference API.

    Note: HuggingFace embeddings use different API (feature-extraction).
    This still uses huggingface_hub InferenceClient.
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: Optional[str] = None,
        timeout: int = 60
    ):
        """
        Initialize Hugging Face Embedding provider.

        Args:
            model: Model ID (e.g., "sentence-transformers/all-MiniLM-L6-v2")
            api_key: Hugging Face API token
            base_url: Custom endpoint (optional)
            timeout: Request timeout in seconds
        """
        self._model = model
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout

        # Try to import huggingface_hub for embeddings
        try:
            from huggingface_hub import InferenceClient
            self.client = InferenceClient(
                token=api_key,
                timeout=timeout
            )
            self.available = True

            # Determine dimension
            self._dimension = self._get_dimension_for_model(model)

            logger.info(f"Initialized Hugging Face Embedding: {model} (dim={self._dimension})")
        except ImportError:
            logger.error(
                "huggingface_hub not installed. Install with: pip install huggingface_hub"
            )
            self.available = False
            self.client = None
            self._dimension = 384

    def _get_dimension_for_model(self, model: str) -> int:
        """Get embedding dimension for known models."""
        known_models = {
            "sentence-transformers/all-MiniLM-L6-v2": 384,
            "sentence-transformers/all-mpnet-base-v2": 768,
            "BAAI/bge-small-en-v1.5": 384,
            "BAAI/bge-base-en-v1.5": 768,
            "BAAI/bge-large-en-v1.5": 1024,
            "intfloat/e5-small-v2": 384,
            "intfloat/e5-base-v2": 768,
            "intfloat/e5-large-v2": 1024,
        }
        return known_models.get(model, 384)

    async def create_embedding(self, text: str) -> List[float]:
        """
        Create embedding for text using Hugging Face.

        Args:
            text: Text to embed

        Returns:
            List of floats representing the embedding
        """
        if not self.available:
            raise RuntimeError("Hugging Face client not available. Install huggingface_hub")

        try:
            # Call feature extraction
            embedding = self.client.feature_extraction(
                text=text,
                model=self._model
            )

            # Handle response formats
            if isinstance(embedding, list):
                if embedding and isinstance(embedding[0], list):
                    return embedding[0]
                return embedding
            else:
                raise ValueError(f"Unexpected embedding format: {type(embedding)}")

        except Exception as e:
            logger.error(f"Hugging Face embedding error: {e}")
            raise

    @property
    def model_name(self) -> str:
        """Return model name."""
        return self._model

    @property
    def dimension(self) -> int:
        """Return embedding dimension."""
        return self._dimension
