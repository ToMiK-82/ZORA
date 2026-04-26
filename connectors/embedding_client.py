"""
Клиент для генерации эмбеддингов через Ollama API.
Использует модель nomic-embed-text (стабильная, без бага NaN).
"""
import os
import requests
import logging
import threading
from typing import List, Optional

logger = logging.getLogger(__name__)

# URL Ollama сервера
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
# Нормализуем URL
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
        self._lock = threading.Lock()
        logger.info(f"Инициализация EmbeddingClient: модель={self.model_name}, host={self.ollama_host}")

    def _sanitize_text(self, text: str) -> str:
        """
        Очищает текст от проблемных символов.
        """
        import re
        # Заменяем тройные кавычки на одинарные
        text = text.replace('"""', '"')
        text = text.replace("'''", "'")
        # Удаляем всё, кроме ASCII, кириллицы и базовых символов
        text = re.sub(r'[^\x20-\x7E\u0400-\u04FF\u0500-\u052F\n\r]', '', text)
        return text

    def _truncate_text(self, text: str, max_chars: int = 8000) -> str:
        """
        Обрезает текст до указанного количества символов.
        nomic-embed-text поддерживает до 8192 токенов.
        """
        if len(text) <= max_chars:
            return text
        truncated = text[:max_chars]
        logger.warning(f"Текст обрезан с {len(text)} до {max_chars} символов для эмбеддинга")
        return truncated

    def generate_embedding(self, text: str, retries: int = 3) -> List[float]:
        """
        Генерация эмбеддинга через Ollama API.
        
        Args:
            text: Текст для векторизации
            retries: Количество попыток при ошибке
            retries: Количество попыток при ошибке (для первой загрузки модели)
            
        Returns:
            Список float — векторное представление текста
        """
        with self._lock:
            # Обрезаем текст до 8000 символов
            text = self._truncate_text(text, max_chars=8000)
            # Очищаем текст
            text = self._sanitize_text(text)
            
            last_error = None
            for attempt in range(retries):
                try:
                    # Используем /api/embeddings (старый API, стабильный)
                    url = f"{self.ollama_host}/api/embeddings"
                    logger.info(f"Отправка запроса к {url} (текст: {len(text)} символов)")
                    response = requests.post(
                        url,
                        json={
                            "model": self.model_name,
                            "prompt": text
                        },
                        timeout=120
                    )
                    logger.info(f"Ответ от {url}: статус {response.status_code}")
                    
                    # Если 404 — пробуем новый API /api/embed
                    if response.status_code == 404:
                        logger.warning(f"API /api/embeddings не найден, пробую /api/embed")
                        url = f"{self.ollama_host}/api/embed"
                        response = requests.post(
                            url,
                            json={
                                "model": self.model_name,
                                "input": text
                            },
                            timeout=120
                        )
                        logger.info(f"Ответ от {url}: статус {response.status_code}")
                    
                    response.raise_for_status()
                    result = response.json()
                    
                    # Старый API возвращает {"embedding": [...]}, новый — {"embeddings": [[...]]}
                    embedding = result.get("embedding")
                    if embedding is None:
                        embeddings_list = result.get("embeddings", [])
                        embedding = embeddings_list[0] if embeddings_list else []
                    
                    if not embedding:
                        logger.error(f"Пустой эмбеддинг от Ollama для модели {self.model_name}")
                        return [0.0] * EMBEDDING_SIZE
                    
                    logger.debug(f"Эмбеддинг сгенерирован: размер={len(embedding)}")
                    return embedding
                    
                except requests.exceptions.ConnectionError as e:
                    logger.error(f"Ошибка подключения к Ollama ({self.ollama_host}): {e}")
                    return [0.0] * EMBEDDING_SIZE
                except Exception as e:
                    last_error = e
                    if attempt < retries - 1:
                        logger.warning(f"Попытка {attempt + 1}/{retries} не удалась: {e}. Повтор через 5 сек...")
                        import time
                        time.sleep(5)
                    else:
                        logger.error(f"Ошибка генерации эмбеддинга через Ollama после {retries} попыток: {e}")
                        return [0.0] * EMBEDDING_SIZE
            
            return [0.0] * EMBEDDING_SIZE


# Глобальный экземпляр
embedding_client = EmbeddingClient()
