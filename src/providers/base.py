"""Абстрактные интерфейсы для провайдеров LLM и Embedding."""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class ChatMessage:
    """Сообщение для чата."""
    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class LLMResponse:
    """Ответ от LLM провайдера."""
    content: str
    model: str
    usage: Optional[Dict[str, int]] = None  # tokens used


class LLMProvider(ABC):
    """
    Абстрактный интерфейс для LLM провайдеров (анализ кода).

    Используется для:
    - Анализа контекста проекта
    - Анализа файлов с кодом
    - Генерации описаний
    """

    @abstractmethod
    async def chat_completion(
        self,
        messages: List[ChatMessage],
        response_format: Optional[Dict[str, Any]] = None,
        use_reasoning: Optional[bool] = None
    ) -> LLMResponse:
        """
        Выполнить chat completion запрос.

        Args:
            messages: Список сообщений чата
            response_format: Опциональный формат ответа (JSON schema)
            use_reasoning: Использовать ли reasoning (для Responses API)
                          None/False - без reasoning (быстрее, для файлов)
                          True - с reasoning (медленнее, для проекта)

        Returns:
            LLMResponse с текстом ответа
        """
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Название используемой модели."""
        pass


class EmbeddingProvider(ABC):
    """
    Абстрактный интерфейс для Embedding провайдеров.

    Используется для генерации векторных представлений кода и запросов.
    """

    @abstractmethod
    async def create_embedding(self, text: str) -> List[float]:
        """
        Создать embedding для текста.

        Args:
            text: Текст для генерации embedding

        Returns:
            Список float - вектор embedding
        """
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Название используемой embedding модели."""
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Размерность embedding векторов."""
        pass
