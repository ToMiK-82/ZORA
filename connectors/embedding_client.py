"""
Клиент для генерации эмбеддингов через Ollama API.
Использует модель mxbai-embed-large (1024 мерности).
Не требует префиксов — текст используется как есть.

ВАЖНО: Чанкинг текста выполняется на стороне коллекторов.
EmbeddingClient обрезает текст по токенам (макс. 512) перед отправкой в Ollama.
"""
import os
import logging
from typing import List

from connectors.tokenizer_utils import truncate_by_tokens, MAX_TOKENS

logger = logging.getLogger(__name__)

# URL Ollama сервера
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

# Модель эмбеддингов в Ollama
EMBED_MODEL = os.getenv("EMBED_MODEL", "mxbai-embed-large")

# Размерность эмбеддинга для mxbai-embed-large
EMBEDDING_SIZE = 1024


class EmbeddingClient:
    def __init__(self, model_name: str = None):
        self.model_name = model_name or EMBED_MODEL
        self.ollama_host = OLLAMA_HOST
        logger.info(f"Инициализация EmbeddingClient: модель={self.model_name}, host={self.ollama_host}")

    def generate_embedding(self, text: str) -> List[float]:
        if not text or not text.strip():
            logger.warning("Пустой текст для эмбеддинга")
            return [0.0] * EMBEDDING_SIZE

        # mxbai-embed-large имеет лимит 512 токенов.
        # Обрезаем текст по токенам, а не по символам.
        text = truncate_by_tokens(text, max_tokens=MAX_TOKENS)

        # Используем requests API напрямую (с retry при ошибке 400)
        return self._generate_via_requests(text)

    def _generate_via_requests(self, text: str, max_retries: int = 3) -> List[float]:
        """
        Генерация эмбеддинга через requests API с retry при ошибке 400.
        При превышении длины контекста уменьшает длину текста и повторяет.
        """
        import requests
        current_text = text
        current_max_tokens = MAX_TOKENS

        for attempt in range(max_retries):
            try:
                url = f"{self.ollama_host}/api/embed"
                response = requests.post(
                    url,
                    json={"model": self.model_name, "input": current_text},
                    timeout=30
                )
                if response.status_code == 200:
                    data = response.json()
                    embeddings_list = data.get("embeddings", [])
                    if embeddings_list:
                        logger.debug(f"Эмбеддинг сгенерирован (requests API): размер={len(embeddings_list[0])}")
                        return embeddings_list[0]
                    else:
                        logger.error(f"Пустой эмбеддинг от Ollama (requests)")
                        return [0.0] * EMBEDDING_SIZE

                if response.status_code == 400 and "exceeds the context length" in response.text:
                    # Уменьшаем длину текста и пробуем снова
                    current_max_tokens = current_max_tokens // 2
                    logger.warning(f"Превышение длины контекста, уменьшаю до {current_max_tokens} токенов (попытка {attempt + 1}/{max_retries})")
                    current_text = truncate_by_tokens(text, max_tokens=current_max_tokens)
                    continue

                logger.error(f"Ошибка Ollama (requests): {response.status_code} - {response.text[:200]}")
                return [0.0] * EMBEDDING_SIZE

            except Exception as e:
                logger.error(f"Ошибка генерации эмбеддинга (requests): {e}")
                if attempt < max_retries - 1:
                    continue
                return [0.0] * EMBEDDING_SIZE

        logger.error(f"Не удалось сгенерировать эмбеддинг после {max_retries} попыток")
        return [0.0] * EMBEDDING_SIZE


# Глобальный экземпляр
embedding_client = EmbeddingClient()
