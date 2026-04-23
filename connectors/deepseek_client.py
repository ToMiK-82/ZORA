"""
Клиент для взаимодействия с DeepSeek API
"""
import os
import requests
import logging
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

logger = logging.getLogger("ZORA.DeepSeek")

# Конфигурация DeepSeek API
DEEPSEEK_API_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_DEFAULT_MODEL = "deepseek-chat"  # Можно использовать "deepseek-coder" для кода

def generate(
    prompt: str,
    model: str = DEEPSEEK_DEFAULT_MODEL,
    temperature: float = 0.7,
    system: Optional[str] = None,
    format: str = None,
    max_tokens: int = 4096,
    **kwargs
) -> str:
    """
    Генерация ответа от модели DeepSeek через API
    
    Args:
        prompt: Пользовательский запрос
        model: Модель DeepSeek (deepseek-chat, deepseek-coder и т.д.)
        temperature: Креативность ответа (0.0-1.0)
        system: Системный промпт
        format: Формат ответа (например, "json_object")
        max_tokens: Максимальное количество токенов в ответе
        **kwargs: Дополнительные параметры API
        
    Returns:
        Текст ответа от модели
    """
    if not DEEPSEEK_API_KEY:
        logger.error("❌ DEEPSEEK_API_KEY не установлен в переменных окружения")
        return "Ошибка: API ключ DeepSeek не настроен. Добавьте DEEPSEEK_API_KEY в .env файл."
    
    try:
        messages = []
        
        # Добавляем системный промпт если есть
        if system:
            messages.append({"role": "system", "content": system})
        
        # Добавляем пользовательский запрос
        messages.append({"role": "user", "content": prompt})
        
        # Формируем запрос к API
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False
        }
        
        # Добавляем формат если указан
        if format == "json":
            payload["response_format"] = {"type": "json_object"}
        
        # Добавляем дополнительные параметры
        payload.update(kwargs)
        
        # Отправляем запрос
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(
            f"{DEEPSEEK_API_BASE_URL}/chat/completions",
            json=payload,
            headers=headers,
            timeout=30  # Таймаут 30 секунд
        )
        
        # Проверяем ответ
        response.raise_for_status()
        result = response.json()
        
        # Извлекаем текст ответа
        if "choices" in result and len(result["choices"]) > 0:
            return result["choices"][0]["message"]["content"]
        else:
            logger.error(f"❌ Неожиданный формат ответа DeepSeek: {result}")
            return "Ошибка: неожиданный формат ответа от DeepSeek API."
            
    except requests.exceptions.Timeout:
        logger.error("❌ Таймаут при запросе к DeepSeek API")
        return "Ошибка: таймаут при запросе к DeepSeek API. Проверьте подключение к интернету."
        
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Ошибка сети при запросе к DeepSeek API: {e}")
        return f"Ошибка сети: {str(e)}"
        
    except Exception as e:
        logger.error(f"❌ Ошибка вызова DeepSeek API: {e}")
        return f"Ошибка генерации через DeepSeek: {str(e)}"


def generate_embedding(text: str, model: str = "text-embedding") -> List[float]:
    """
    Получение векторного эмбеддинга через DeepSeek API
    
    Args:
        text: Текст для эмбеддинга
        model: Модель для эмбеддинга
        
    Returns:
        Вектор эмбеддинга
    """
    if not DEEPSEEK_API_KEY:
        logger.error("❌ DEEPSEEK_API_KEY не установлен в переменных окружения")
        return []
    
    try:
        payload = {
            "model": model,
            "input": text
        }
        
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(
            f"{DEEPSEEK_API_BASE_URL}/embeddings",
            json=payload,
            headers=headers,
            timeout=30
        )
        
        response.raise_for_status()
        result = response.json()
        
        if "data" in result and len(result["data"]) > 0:
            return result["data"][0]["embedding"]
        else:
            logger.error(f"❌ Неожиданный формат ответа эмбеддинга DeepSeek: {result}")
            return []
            
    except Exception as e:
        logger.error(f"❌ Ошибка генерации эмбеддинга DeepSeek: {e}")
        return []


def check_deepseek_available() -> bool:
    """
    Проверка доступности DeepSeek API
    
    Returns:
        True если API доступен, False в противном случае
    """
    if not DEEPSEEK_API_KEY:
        logger.warning("⚠️ DEEPSEEK_API_KEY не установлен")
        return False
    
    try:
        # Простой тестовый запрос для проверки доступности
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        
        # Минимальный тестовый запрос
        test_payload = {
            "model": DEEPSEEK_DEFAULT_MODEL,
            "messages": [{"role": "user", "content": "test"}],
            "max_tokens": 5
        }
        
        response = requests.post(
            f"{DEEPSEEK_API_BASE_URL}/chat/completions",
            json=test_payload,
            headers=headers,
            timeout=10
        )
        
        return response.status_code == 200
        
    except Exception as e:
        logger.warning(f"⚠️ DeepSeek API недоступен: {e}")
        return False


class DeepSeekClient:
    """Класс-клиент для работы с DeepSeek API"""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or DEEPSEEK_API_KEY
        self.base_url = DEEPSEEK_API_BASE_URL
        self.default_model = DEEPSEEK_DEFAULT_MODEL
        
    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """Отправка сообщений в чат"""
        if not self.api_key:
            raise ValueError("API ключ DeepSeek не установлен")
        
        payload = {
            "model": kwargs.get("model", self.default_model),
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 4096),
            "stream": False
        }
        
        # Добавляем дополнительные параметры
        for key in ["response_format", "top_p", "frequency_penalty", "presence_penalty"]:
            if key in kwargs:
                payload[key] = kwargs[key]
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=kwargs.get("timeout", 30)
        )
        
        response.raise_for_status()
        result = response.json()
        
        if "choices" in result and len(result["choices"]) > 0:
            return result["choices"][0]["message"]["content"]
        else:
            raise ValueError("Неожиданный формат ответа от DeepSeek API")
    
    def is_available(self) -> bool:
        """Проверка доступности API"""
        return check_deepseek_available()


# Глобальный экземпляр клиента
deepseek_client = DeepSeekClient()