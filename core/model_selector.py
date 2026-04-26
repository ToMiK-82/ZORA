"""
Модуль выбора моделей для гибридной архитектуры ZORA с самоконтролем
"""

import os
import logging
from typing import Dict, Optional
import requests

logger = logging.getLogger("ZORA.ModelSelector")

# ============================================================
# КОНСТАНТЫ
# ============================================================

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
if not OLLAMA_HOST.startswith(("http://", "https://")):
    OLLAMA_HOST = "http://" + OLLAMA_HOST
if "0.0.0.0" in OLLAMA_HOST:
    OLLAMA_HOST = OLLAMA_HOST.replace("0.0.0.0", "localhost")

# Модели для разных типов задач
OLLAMA_VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "qwen3-vl:4b")
OLLAMA_EXECUTOR_MODEL = os.getenv("OLLAMA_EXECUTOR_MODEL", "llama3.2:latest")
OLLAMA_CODER_MODEL = os.getenv("OLLAMA_CODER_MODEL", "llama3.2:latest")
OLLAMA_PLANNER_MODEL = os.getenv("OLLAMA_PLANNER_MODEL", "llama3.2:latest")
OLLAMA_REASONER_MODEL = os.getenv("OLLAMA_REASONER_MODEL", "llama3.2:latest")

# DeepSeek API
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_BASE = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com")
DEEPSEEK_CHAT_MODEL = os.getenv("DEEPSEEK_CHAT_MODEL", "deepseek-chat")
DEEPSEEK_REASONER_MODEL = os.getenv("DEEPSEEK_REASONER_MODEL", "deepseek-reasoner")

EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "180"))
DEEPSEEK_TIMEOUT = int(os.getenv("DEEPSEEK_TIMEOUT", "120"))

# ============================================================
# КЛАСС ModelSelector
# ============================================================

class ModelSelector:
    def __init__(self):
        self.ollama_host = OLLAMA_HOST
        self.vision_model = OLLAMA_VISION_MODEL
        self.executor_model = OLLAMA_EXECUTOR_MODEL
        self.coder_model = OLLAMA_CODER_MODEL
        self.fast_planner_model = os.getenv("OLLAMA_FAST_PLANNER", "llama3.2:latest")
        self.deep_planner_model = OLLAMA_PLANNER_MODEL
        self.reasoner_model = OLLAMA_REASONER_MODEL
        self.deepseek_chat_model = DEEPSEEK_CHAT_MODEL
        self.deepseek_reasoner_model = DEEPSEEK_REASONER_MODEL

        logger.info(f"ModelSelector: vision={self.vision_model}, executor={self.executor_model}")

    def select_planner(self, query: str) -> Dict[str, Optional[str]]:
        """Выбирает модель для планирования — всегда DeepSeek (Reasoner для сложных, Chat для простых)."""
        # Проверяем, доступен ли DeepSeek API
        if not DEEPSEEK_API_KEY:
            logger.warning("DeepSeek API ключ отсутствует, использую локальный Ollama")
            if self._check_ollama_available():
                return {"provider": "ollama", "model": self.fast_planner_model}
            return {"provider": None, "model": None}

        # Используем DeepSeek
        if self._is_complex_reasoning_query(query) or self._is_complex_query(query):
            logger.info(f"Сложный запрос → DeepSeek Reasoner")
            return {"provider": "deepseek", "model": self.deepseek_reasoner_model}
        else:
            logger.info(f"Простой запрос → DeepSeek Chat")
            return {"provider": "deepseek", "model": self.deepseek_chat_model}

    def select_executor(self) -> Dict[str, Optional[str]]:
        """Выбирает модель для исполнителя действий (локальная llama3.2:latest)."""
        if self._check_ollama_available():
            logger.info(f"Исполнитель: {self.executor_model}")
            return {"provider": "ollama", "model": self.executor_model}
        logger.warning("Ollama недоступен, исполнитель не работает")
        return {"provider": None, "model": None}

    def select_vision(self) -> Dict[str, Optional[str]]:
        """Выбирает модель для анализа изображений."""
        if self._check_ollama_available():
            logger.info(f"Vision модель: {self.vision_model}")
            return {"provider": "ollama", "model": self.vision_model}
        logger.error("Ollama недоступен, vision модель не работает")
        return {"provider": None, "model": None}

    def select_coder(self) -> Dict[str, Optional[str]]:
        """Выбирает модель для генерации кода."""
        if self._check_ollama_available():
            return {"provider": "ollama", "model": self.coder_model}
        return {"provider": "deepseek", "model": self.deepseek_chat_model}

    def _check_ollama_available(self) -> bool:
        try:
            response = requests.get(f"{self.ollama_host}/api/tags", timeout=3)
            return response.status_code == 200
        except:
            return False

    def _is_complex_query(self, query: str) -> bool:
        if not query:
            return False
        query_lower = query.lower()
        complex_keywords = ["архитектур", "спроектировать", "рефакторинг", "план разработки",
                            "оптимизаци", "алгоритм", "интеграци", "микросервис", "масштабирование",
                            "безопасность", "нейросеть", "тестирование", "документация"]
        simple_keywords = ["привет", "как дела", "покажи", "найди", "открой", "прочитай"]
        if any(kw in query_lower for kw in simple_keywords):
            return False
        if len(query_lower.split()) < 5:
            return False
        return any(kw in query_lower for kw in complex_keywords)

    def _is_complex_reasoning_query(self, query: str) -> bool:
        if not query:
            return False
        query_lower = query.lower()
        reasoning_keywords = ["доказать", "логический вывод", "философский", "теоретический",
                              "гипотеза", "верификация", "дедукция", "индукция"]
        return any(kw in query_lower for kw in reasoning_keywords)


_selector = None
def get_selector() -> ModelSelector:
    global _selector
    if _selector is None:
        _selector = ModelSelector()
    return _selector
