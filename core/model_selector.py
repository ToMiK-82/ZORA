"""
Модуль выбора моделей для гибридной архитектуры ZORA с самоконтролем
и конфигурация всех моделей системы.

Логика приоритетов:
1. Удалённый Ollama (если доступен)
2. DeepSeek API (резервный провайдер)

Логика выбора планировщика:
- Простые запросы → OLLAMA_FAST_PLANNER (qwen3:8b)
- Сложные reasoning-запросы → OLLAMA_DEEP_PLANNER (qwen3:14b) или OLLAMA_REASONER_MODEL (deepseek-r1:14b)
- При недоступности Ollama → DeepSeek API (chat/reasoner)
"""

import os
import logging
from typing import Dict, Optional
import requests

logger = logging.getLogger("ZORA.ModelSelector")

# ============================================================
# КОНСТАНТЫ — все модели и настройки в одном месте
# ============================================================

# === УДАЛЁННЫЙ OLLAMA СЕРВЕР ===
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
# Нормализуем URL
if not OLLAMA_HOST.startswith(("http://", "https://")):
    OLLAMA_HOST = "http://" + OLLAMA_HOST
# Защита от 0.0.0.0 — заменяем на localhost
if "0.0.0.0" in OLLAMA_HOST:
    OLLAMA_HOST = OLLAMA_HOST.replace("0.0.0.0", "localhost")
    logger.warning(f"⚠️ OLLAMA_HOST содержал 0.0.0.0, исправлено на {OLLAMA_HOST}")

OLLAMA_HOST_LOCAL = os.getenv("OLLAMA_HOST_LOCAL", "http://localhost:11434")
OLLAMA_HOST_POWERFUL = os.getenv("OLLAMA_HOST_POWERFUL", OLLAMA_HOST)

# Модели для разных типов задач
OLLAMA_VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "qwen3-vl:4b")
OLLAMA_CODER_MODEL = os.getenv("OLLAMA_CODER_MODEL", "qwen2.5-coder:7b")
OLLAMA_PLANNER_MODEL = os.getenv("OLLAMA_PLANNER_MODEL", "qwen3:14b")
OLLAMA_REASONER_MODEL = os.getenv("OLLAMA_REASONER_MODEL", "deepseek-r1:14b")

# Модели для обратной совместимости
CHAT_MODEL_WEAK = os.getenv("CHAT_MODEL_WEAK", "qwen3:8b")
CHAT_MODEL_STRONG = os.getenv("CHAT_MODEL_STRONG", "qwen3:14b")
CHAT_MODEL_STRONG_LOCAL = os.getenv("CHAT_MODEL_STRONG_LOCAL", "qwen3:14b")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
EMBED_MODEL = os.getenv("EMBED_MODEL", "bge-m3:latest")

# Тайм-аут для Ollama (сек)
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "180"))

# === DEEPSEEK API (РЕЗЕРВ) ===
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_BASE = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com")
DEEPSEEK_CHAT_MODEL = os.getenv("DEEPSEEK_CHAT_MODEL", "deepseek-chat")
DEEPSEEK_REASONER_MODEL = os.getenv("DEEPSEEK_REASONER_MODEL", "deepseek-reasoner")

# Тайм-аут для DeepSeek (сек)
DEEPSEEK_TIMEOUT = int(os.getenv("DEEPSEEK_TIMEOUT", "120"))


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (на уровне модуля для обратной совместимости)
# ============================================================

def is_coding_task(model: str) -> bool:
    """Определяет, является ли задача кодированием"""
    if model is None:
        return False
    coding_keywords = ["coder", "code", "qwen2.5-coder", "deepseek-coder"]
    return any(keyword in model.lower() for keyword in coding_keywords)


def is_embedding_task(model: str) -> bool:
    """Определяет, является ли задача эмбеддингом"""
    if model is None:
        return False
    model_lower = model.lower()
    if "bge-m3" in model_lower:
        return True
    if "embed" in model_lower:
        if "nomic-embed-text" in model_lower:
            return False
        embedding_indicators = ["embed-model", "embedding", "bge", "embed/"]
        return any(indicator in model_lower for indicator in embedding_indicators)
    return False


def is_complex_question(query: str) -> bool:
    """
    Определяет, является ли вопрос сложным.
    (Дублирует _is_complex_query из ModelSelector, но на уровне модуля)
    """
    if not query:
        return False
    query_lower = query.lower()
    words = len(query_lower.split())
    if words > 50:
        return True
    complex_terms = [
        "анализ", "алгоритм", "архитектура", "оптимизация", "проектирование",
        "интеграция", "микросервис", "распределённ", "параллельн", "масштабирование",
        "безопасность", "шифрование", "аутентификация", "авторизация", "токен",
        "нейросеть", "машинное обучение", "искусственный интеллект", "трансформер",
        "транзакция", "репликация", "кластеризация", "балансировка", "контейнеризация",
        "оркестрация", "мониторинг", "логирование", "тестирование", "дебаггинг",
        "рефакторинг", "реинжиниринг", "документация", "спецификация", "требование"
    ]
    if any(term in query_lower for term in complex_terms):
        return True
    multi_part_keywords = [" и ", " или ", " также ", " кроме ", " а также ", " либо "]
    if any(keyword in query_lower for keyword in multi_part_keywords):
        return True
    if query_lower.count(',') >= 3:
        return True
    requirement_keywords = ["нужно", "требуется", "необходимо", "следует", "должен", "обязательно"]
    if any(keyword in query_lower for keyword in requirement_keywords):
        if words > 10:
            return True
    return False


def get_model_type(model: str) -> str:
    """Возвращает тип модели"""
    if model is None:
        return "chat"
    if is_embedding_task(model):
        return "embedding"
    elif is_coding_task(model):
        return "coding"
    else:
        return "chat"


# ============================================================
# КЛАСС ModelSelector
# ============================================================

class ModelSelector:
    """Класс для выбора оптимальной модели по типу задачи"""

    def __init__(self):
        self.ollama_host = OLLAMA_HOST
        self.vision_model = OLLAMA_VISION_MODEL
        self.coder_model = OLLAMA_CODER_MODEL
        self.fast_planner_model = os.getenv("OLLAMA_FAST_PLANNER", "qwen3:8b")
        self.deep_planner_model = OLLAMA_PLANNER_MODEL
        self.reasoner_model = OLLAMA_REASONER_MODEL

        self.deepseek_chat_model = DEEPSEEK_CHAT_MODEL
        self.deepseek_reasoner_model = DEEPSEEK_REASONER_MODEL

        logger.info(f"Инициализация ModelSelector с OLLAMA_HOST={self.ollama_host}")
        logger.info(f"Модели: vision={self.vision_model}, coder={self.coder_model}, "
                    f"fast_planner={self.fast_planner_model}, deep_planner={self.deep_planner_model}, "
                    f"reasoner={self.reasoner_model}")

    def select_planner(self, query: str) -> Dict[str, Optional[str]]:
        """
        Выбирает модель для планирования.

        Args:
            query: Пользовательский запрос

        Returns:
            Словарь с провайдером и моделью: {'provider': 'ollama'|'deepseek', 'model': str}
        """
        if self._check_ollama_available():
            if not self._is_complex_query(query):
                logger.info(f"Простой запрос планирования, использую {self.fast_planner_model}")
                return {"provider": "ollama", "model": self.fast_planner_model}

            if self._is_complex_reasoning_query(query) and self.reasoner_model:
                logger.info(f"Очень сложный reasoning-запрос, использую {self.reasoner_model}")
                return {"provider": "ollama", "model": self.reasoner_model}

            if self._is_complex_query(query):
                logger.info(f"Сложный запрос планирования, использую {self.deep_planner_model}")
                return {"provider": "ollama", "model": self.deep_planner_model}

            logger.info(f"Простой запрос планирования, использую {self.fast_planner_model}")
            return {"provider": "ollama", "model": self.fast_planner_model}

        logger.warning("Удалённый Ollama недоступен, переключаюсь на DeepSeek API")
        if self._is_complex_reasoning_query(query):
            logger.info(f"Очень сложный reasoning-запрос, использую DeepSeek Reasoner")
            return {"provider": "deepseek", "model": self.deepseek_reasoner_model}

        if self._is_complex_query(query):
            logger.info(f"Сложный запрос планирования, использую DeepSeek Reasoner")
            return {"provider": "deepseek", "model": self.deepseek_reasoner_model}

        logger.info(f"Простой запрос планирования, использую DeepSeek Chat")
        return {"provider": "deepseek", "model": self.deepseek_chat_model}

    def select_coder(self) -> Dict[str, Optional[str]]:
        """Выбирает модель для генерации кода."""
        if self._check_ollama_available():
            logger.info(f"Выбор модели для кодирования: {self.coder_model}")
            return {"provider": "ollama", "model": self.coder_model}

        logger.warning("Удалённый Ollama недоступен, использую DeepSeek Chat для кодирования")
        return {"provider": "deepseek", "model": self.deepseek_chat_model}

    def select_vision(self) -> Dict[str, Optional[str]]:
        """Выбирает модель для анализа изображений."""
        if self._check_ollama_available():
            logger.info(f"Выбор модели для зрения: {self.vision_model}")
            return {"provider": "ollama", "model": self.vision_model}

        logger.error("Удалённый Ollama недоступен, модель для зрения недоступна")
        return {"provider": None, "model": None}

    def _check_ollama_available(self) -> bool:
        """Проверяет доступность удалённого Ollama."""
        try:
            response = requests.get(f"{self.ollama_host}/api/tags", timeout=3)
            return response.status_code == 200
        except Exception as e:
            logger.debug(f"Удалённый Ollama недоступен: {e}")
            return False

    def _is_complex_query(self, query: str) -> bool:
        """
        Определяет, является ли запрос сложным (требует глубокого планировщика).
        """
        if not query:
            return False

        query_lower = query.lower()

        complex_keywords = [
            "архитектур", "спроектировать", "рефакторинг", "план разработки",
            "многопоточ", "оптимизаци производительности", "алгоритм", "стратег",
            "интеграци систем", "математическ", "логическ", "доказать теорему",
            "проектирование системы", "микросервис", "распределённ", "параллельн",
            "масштабирование", "безопасность", "шифрование", "аутентификация",
            "авторизация", "нейросеть", "машинное обучение", "искусственный интеллект",
            "трансформер", "транзакция", "репликация", "кластеризация",
            "балансировка", "контейнеризация", "оркестрация", "реинжиниринг",
            "спецификация", "требование", "документация", "тестирование"
        ]

        simple_keywords = [
            "курс", "доллар", "евро", "валюта", "цена", "стоимость", "сколько стоит",
            "погода", "время", "дата", "привет", "здравствуй", "как дела",
            "покажи", "найди", "открой", "прочитай", "посмотри", "что такое"
        ]

        if any(kw in query_lower for kw in simple_keywords):
            return False

        if len(query_lower.split()) < 5:
            return False

        return any(kw in query_lower for kw in complex_keywords)

    def _is_complex_reasoning_query(self, query: str) -> bool:
        """
        Определяет, является ли запрос очень сложным reasoning-запросом.
        """
        if not query:
            return False

        query_lower = query.lower()

        reasoning_keywords = [
            "доказать теорему", "математическое доказательство", "логический вывод",
            "философский", "этический", "моральный", "метафизический",
            "теоретический", "фундаментальный", "исследовательский",
            "научный метод", "гипотеза", "эксперимент", "верификация",
            "формальная логика", "дедукция", "индукция", "абдукция",
            "критическое мышление", "аналитическое мышление", "системное мышление"
        ]

        return any(kw in query_lower for kw in reasoning_keywords)

    def get_available_providers(self) -> Dict[str, bool]:
        """Возвращает информацию о доступности провайдеров."""
        ollama_available = self._check_ollama_available()
        deepseek_available = bool(DEEPSEEK_API_KEY)

        return {
            "ollama": ollama_available,
            "deepseek": deepseek_available,
            "vision_available": ollama_available
        }


# Создаём глобальный экземпляр селектора
_selector = None


def get_selector() -> ModelSelector:
    """Возвращает глобальный экземпляр ModelSelector"""
    global _selector
    if _selector is None:
        _selector = ModelSelector()
    return _selector
