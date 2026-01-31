"""OpenAI реализации LLM и Embedding провайдеров."""

from typing import List, Dict, Any, Optional
from openai import AsyncOpenAI

from .base import (
    LLMProvider,
    EmbeddingProvider,
    ChatMessage,
    LLMResponse
)


class OpenAILLMProvider(LLMProvider):
    """
    OpenAI провайдер для анализа кода через Responses API.

    Использует responses.create() для всех моделей.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        reasoning_effort: str = "medium",
        max_retries: int = 3,
        timeout: int = 60
    ):
        self._client = AsyncOpenAI(
            api_key=api_key,
            max_retries=max_retries,
            timeout=timeout
        )
        self._model = model
        self._reasoning_effort = reasoning_effort

    async def chat_completion(
        self,
        messages: List[ChatMessage],
        response_format: Optional[Dict[str, Any]] = None,
        use_reasoning: Optional[bool] = None
    ) -> LLMResponse:
        """Выполнить OpenAI responses API call."""

        # Конвертация messages → input + instructions
        system_messages = [msg.content for msg in messages if msg.role == "system"]
        instructions = " ".join(system_messages) if system_messages else "You are a code analysis expert. Analyze code and provide structured JSON output."

        user_messages = [msg.content for msg in messages if msg.role == "user"]
        input_text = "\n\n".join(user_messages)

        # Параметры для Responses API
        params = {
            "model": self._model,
            "input": input_text,
            "instructions": instructions,
            "text": {
                "format": {"type": "json_object"}
            }
        }

        # Добавить reasoning только если явно запрошено
        # По умолчанию reasoning ВЫКЛЮЧЕН (для файлов - быстрее и дешевле)
        # Для анализа проекта - передать use_reasoning=True
        if use_reasoning is True:
            params["reasoning"] = {
                "effort": self._reasoning_effort
            }

        # Вызов Responses API
        response = await self._client.responses.create(**params)

        # Извлечь content из response.output
        # output - это список ResponseReasoningItem или ResponseOutputText объектов
        output = response.output

        if not output:
            content = ""
        elif isinstance(output, str):
            content = output
        elif isinstance(output, list):
            # Обработать список output items
            texts = []
            for item in output:
                # ResponseReasoningItem имеет summary и content
                if hasattr(item, 'summary') and item.summary:
                    # Извлечь text из каждого summary объекта
                    for summary_obj in item.summary:
                        if hasattr(summary_obj, 'text'):
                            texts.append(summary_obj.text)
                # Если нет summary, попробовать content
                elif hasattr(item, 'content') and item.content:
                    if isinstance(item.content, list):
                        for content_obj in item.content:
                            if hasattr(content_obj, 'text'):
                                texts.append(content_obj.text)
                    elif hasattr(item.content, 'text'):
                        texts.append(item.content.text)
                # ResponseOutputText просто имеет text
                elif hasattr(item, 'text'):
                    texts.append(item.text)
                # Fallback - строковое представление
                elif isinstance(item, str):
                    texts.append(item)

            content = "\n".join(texts) if texts else ""
        else:
            # Одиночный объект (не список)
            if hasattr(output, 'text'):
                content = output.text
            else:
                content = str(output)

        return LLMResponse(
            content=content,
            model=response.model,
            usage={
                "prompt_tokens": response.usage.input_tokens if hasattr(response.usage, 'input_tokens') else 0,
                "completion_tokens": response.usage.output_tokens if hasattr(response.usage, 'output_tokens') else 0,
                "total_tokens": (response.usage.input_tokens if hasattr(response.usage, 'input_tokens') else 0) +
                               (response.usage.output_tokens if hasattr(response.usage, 'output_tokens') else 0)
            }
        )

    @property
    def model_name(self) -> str:
        return self._model


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """
    OpenAI провайдер для генерации embeddings.

    Поддерживает:
    - text-embedding-3-small (1536 dim, рекомендуется)
    - text-embedding-3-large (3072 dim)
    - text-embedding-ada-002 (1536 dim, legacy)
    """

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        max_retries: int = 3,
        timeout: int = 60
    ):
        self._client = AsyncOpenAI(
            api_key=api_key,
            max_retries=max_retries,
            timeout=timeout
        )
        self._model = model

        # Определить размерность для известных моделей
        self._dimensions = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
            "text-embedding-ada-002": 1536
        }

    async def create_embedding(self, text: str) -> List[float]:
        """Создать OpenAI embedding."""
        response = await self._client.embeddings.create(
            input=text,
            model=self._model
        )
        return response.data[0].embedding

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._dimensions.get(self._model, 1536)


def create_providers_from_config(config) -> tuple[LLMProvider, EmbeddingProvider]:
    """
    Фабричная функция для создания провайдеров из конфигурации.

    Args:
        config: Config объект с настройками

    Returns:
        Tuple (llm_provider, embedding_provider)
    """
    # Создать LLM провайдер
    if config.provider.llm_provider == "openai":
        llm_provider = OpenAILLMProvider(
            api_key=config.provider.llm_api_key,
            model=config.provider.llm_model,
            reasoning_effort=config.provider.reasoning_effort,
            max_retries=config.provider.max_retries,
            timeout=config.provider.timeout
        )
    else:
        raise ValueError(f"Unsupported LLM provider: {config.provider.llm_provider}")

    # Создать Embedding провайдер
    if config.provider.embedding_provider == "openai":
        embedding_provider = OpenAIEmbeddingProvider(
            api_key=config.provider.embedding_api_key,
            model=config.provider.embedding_model,
            max_retries=config.provider.max_retries,
            timeout=config.provider.timeout
        )
    else:
        raise ValueError(f"Unsupported embedding provider: {config.provider.embedding_provider}")

    return llm_provider, embedding_provider
