"""
Клиент для генерации эмбеддингов через Ollama API.
Использует модель nomic-embed-text (стабильная, без бага NaN).

ВАЖНО: Чанкинг текста выполняется на стороне indexer.py.
EmbeddingClient НЕ обрезает текст — он доверяет чанкеру.
"""
import os
import requests
import logging
from typing import List

logger = logging.getLogger(__name__)

# URL Ollama сервера
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
if not OLLAMA_HOST.startswith(("http://", "https://")):
    OLLAMA_HOST = "http://" + OLLAMA_HOST

# Модель эмбеддингов в Ollama
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

# Размерность эмбеддинга для nomic-embed-text
EMBEDDING_SIZE = 768


class EmbeddingClient:
    def __init__(self, model_name: str = None):
        """
        Инициализация клиента эмбеддингов.

        Args:
            model_name: Имя модели в Ollama (по умолчанию из EMBED_MODEL или "nomic-embed-text")
        """
        self.model_name = model_name or EMBED_MODEL
        self.ollama_host = OLLAMA_HOST
        logger.info(f"Инициализация EmbeddingClient: модель={self.model_name}, host={self.ollama_host}")

    def generate_embedding(self, text: str) -> List[float]:
        """
        Генерирует эмбеддинг для текста через Ollama API.
        Текст должен быть заранее подготовлен чанкером (размер <1500 символов).

        Args:
            text: Текст для векторизации (уже подготовлен чанкером)

        Returns:
            Список float — векторное представление текста (768 мер)
        """
        if not text or not text.strip():
            logger.warning("Пустой текст для эмбеддинга")
            return [0.0] * EMBEDDING_SIZE

        try:
            url = f"{self.ollama_host}/api/embeddings"
            logger.debug(f"Запрос к {url} (текст: {len(text)} символов)")

            response = requests.post(
                url,
                json={"model": self.model_name, "prompt": text},
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                embedding = data.get("embedding", [0.0] * EMBEDDING_SIZE)
                if not embedding:
                    logger.error(f"Пустой эмбеддинг от Ollama для модели {self.model_name}")
                    return [0.0] * EMBEDDING_SIZE
                logger.debug(f"Эмбеддинг сгенерирован: размер={len(embedding)}")
                return embedding
            else:
                # Если 404 — пробуем новый API /api/embed
                if response.status_code == 404:
                    logger.warning("API /api/embeddings не найден, пробую /api/embed")
                    url = f"{self.ollama_host}/api/embed"
                    response = requests.post(
                        url,
                        json={"model": self.model_name, "input": text},
                        timeout=30
                    )
                    if response.status_code == 200:
                        data = response.json()
                        embeddings_list = data.get("embeddings", [])
                        embedding = embeddings_list[0] if embeddings_list else [0.0] * EMBEDDING_SIZE
                        logger.debug(f"Эмбеддинг сгенерирован (новый API): размер={len(embedding)}")
                        return embedding

                logger.error(f"Ошибка Ollama: {response.status_code} - {response.text[:200]}")
                return [0.0] * EMBEDDING_SIZE

        except requests.exceptions.ConnectionError as e:
            logger.error(f"Ошибка подключения к Ollama ({self.ollama_host}): {e}")
            return [0.0] * EMBEDDING_SIZE
        except Exception as e:
            logger.error(f"Ошибка генерации эмбеддинга: {e}")
            return [0.0] * EMBEDDING_SIZE


# Глобальный экземпляр
embedding_client = EmbeddingClient()
