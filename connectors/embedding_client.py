"""
Клиент для генерации эмбеддингов через Ollama API.
Использует модель bge-m3, загруженную в Ollama, вместо локального SentenceTransformer.
Это позволяет избежать скачивания 2.27 ГБ с HuggingFace.
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
EMBED_MODEL = os.getenv("EMBED_MODEL", "bge-m3:latest")

# Размерность эмбеддинга для bge-m3
EMBEDDING_SIZE = 1024


class EmbeddingClient:
    def __init__(self, model_name: str = None):
        """
        Инициализация клиента эмбеддингов.
        
        Args:
            model_name: Имя модели в Ollama (по умолчанию из EMBED_MODEL или "bge-m3")
        """
        self.model_name = model_name or EMBED_MODEL
        self.ollama_host = OLLAMA_HOST
        self._lock = threading.Lock()
        logger.info(f"Инициализация EmbeddingClient: модель={self.model_name}, host={self.ollama_host}")

    def generate_embedding(self, text: str, retries: int = 2) -> List[float]:
        """
        Генерация эмбеддинга через Ollama API /api/embeddings.
        
        Args:
            text: Текст для векторизации
            retries: Количество попыток при ошибке (для первой загрузки модели)
            
        Returns:
            Список float — векторное представление текста
        """
        with self._lock:
            last_error = None
            for attempt in range(retries):
                try:
                    response = requests.post(
                        f"{self.ollama_host}/api/embeddings",
                        json={
                            "model": self.model_name,
                            "prompt": text
                        },
                        timeout=120
                    )
                    response.raise_for_status()
                    result = response.json()
                    embedding = result.get("embedding", [])
                    
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
