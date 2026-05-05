"""
Клиент для взаимодействия с Ollama API
"""
import os
import requests
import logging
from typing import List, Optional

logger = logging.getLogger("ZORA.Ollama")

# Используем переменную окружения или значение по умолчанию
OLLAMA_BASE_URL = os.getenv("OLLAMA_HOST", "http://localhost:11434")
# Нормализуем URL: добавляем http:// если отсутствует
if not OLLAMA_BASE_URL.startswith(("http://", "https://")):
    OLLAMA_BASE_URL = "http://" + OLLAMA_BASE_URL

def generate(
    prompt: str,
    model: str = None,
    temperature: float = 0.7,
    system: Optional[str] = None,
    format: str = None  # например, "json"
) -> str:
    """
    Генерация ответа от модели через /api/generate
    """
    try:
        # Если модель не указана, используем значение по умолчанию из .env
        if model is None:
            from core.model_selector import CHAT_MODEL_WEAK
            model = CHAT_MODEL_WEAK
        
        logger.info(f"📤 Вызов Ollama: модель={model}, URL={OLLAMA_BASE_URL}")
        
        # Формируем полный промпт с системным сообщением
        full_prompt = prompt
        if system:
            full_prompt = f"System: {system}\n\nUser: {prompt}\n\nAssistant:"

        payload = {
            "model": model,
            "prompt": full_prompt,
            "options": {
                "temperature": temperature,
                "num_predict": 1000
            },
            "stream": False
        }

        if format == "json":
            payload["format"] = "json"

        response = requests.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()
        return result.get("response", "").strip()

    except Exception as e:
        logger.error(f"❌ Ошибка вызова Ollama: {e}")
        return f"Ошибка генерации: {str(e)}"


def generate_embedding(text: str, model: str = "nomic-embed-text") -> List[float]:
    """
    Получение векторного эмбеддинга через /api/embeddings
    Использует nomic-embed-text (работает с :latest)
    """
    try:
        response = requests.post(f"{OLLAMA_BASE_URL}/api/embeddings", json={
            "model": model,
            "prompt": text
        })
        response.raise_for_status()
        return response.json()["embedding"]
    except Exception as e:
        logger.error(f"❌ Ошибка генерации эмбеддинга: {e}")
        return []