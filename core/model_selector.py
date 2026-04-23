"""
Модуль выбора моделей для гибридной архитектуры ZORA с самоконтролем

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

class ModelSelector:
    """Класс для выбора оптимальной модели по типу задачи"""
    
    def __init__(self):
        self.ollama_host = os.getenv("OLLAMA_HOST", "http://192.168.68.56:11434")
        self.vision_model = os.getenv("OLLAMA_VISION_MODEL", "qwen3-vl:4b")
        self.coder_model = os.getenv("OLLAMA_CODER_MODEL", "qwen2.5-coder:7b")
        self.fast_planner_model = os.getenv("OLLAMA_FAST_PLANNER", "qwen3:8b")
        self.deep_planner_model = os.getenv("OLLAMA_DEEP_PLANNER", "qwen3:14b")
        self.reasoner_model = os.getenv("OLLAMA_REASONER_MODEL", "deepseek-r1:14b")
        
        self.deepseek_chat_model = os.getenv("DEEPSEEK_CHAT_MODEL", "deepseek-chat")
        self.deepseek_reasoner_model = os.getenv("DEEPSEEK_REASONER_MODEL", "deepseek-reasoner")
        
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
        # 1. Проверяем доступность удалённого Ollama
        if self._check_ollama_available():
            # Для обычных запросов использовать быструю модель
            if not self._is_complex_query(query):
                logger.info(f"Простой запрос планирования, использую {self.fast_planner_model}")
                return {"provider": "ollama", "model": self.fast_planner_model}
            
            # Если запрос очень сложный и есть reasoner-модель — используем её
            if self._is_complex_reasoning_query(query) and self.reasoner_model:
                logger.info(f"Очень сложный reasoning-запрос, использую {self.reasoner_model}")
                return {"provider": "ollama", "model": self.reasoner_model}
            
            # Если запрос сложный — используем глубокий планировщик
            if self._is_complex_query(query):
                logger.info(f"Сложный запрос планирования, использую {self.deep_planner_model}")
                return {"provider": "ollama", "model": self.deep_planner_model}
            
            # Простые запросы — используем быстрый планировщик
            logger.info(f"Простой запрос планирования, использую {self.fast_planner_model}")
            return {"provider": "ollama", "model": self.fast_planner_model}
        
        # 2. Иначе — DeepSeek API
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
        """
        Выбирает модель для генерации кода.
        
        Returns:
            Словарь с провайдером и моделью
        """
        if self._check_ollama_available():
            logger.info(f"Выбор модели для кодирования: {self.coder_model}")
            return {"provider": "ollama", "model": self.coder_model}
        
        # fallback на DeepSeek Chat (он тоже умеет код)
        logger.warning("Удалённый Ollama недоступен, использую DeepSeek Chat для кодирования")
        return {"provider": "deepseek", "model": self.deepseek_chat_model}
    
    def select_vision(self) -> Dict[str, Optional[str]]:
        """
        Выбирает модель для анализа изображений.
        
        Returns:
            Словарь с провайдером и моделью (provider может быть None, если нет fallback)
        """
        if self._check_ollama_available():
            logger.info(f"Выбор модели для зрения: {self.vision_model}")
            return {"provider": "ollama", "model": self.vision_model}
        
        # Для зрения нет облачного fallback — возвращаем ошибку
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
        
        Args:
            query: Пользовательский запрос
            
        Returns:
            True если запрос требует глубокого анализа
        """
        if not query:
            return False
        
        query_lower = query.lower()
        
        # Ключевые слова для сложных запросов (только действительно сложные задачи)
        complex_keywords = [
            "архитектур", "спроектировать", "рефакторинг", "план разработки", 
            "многопоточ", "оптимизаци производительности", "алгоритм", "стратег", "интеграци систем",
            "математическ", "логическ", "доказать теорему", "проектирование системы",
            "микросервис", "распределённ", "параллельн", "масштабирование",
            "безопасность", "шифрование", "аутентификация", "авторизация",
            "нейросеть", "машинное обучение", "искусственный интеллект",
            "трансформер", "транзакция", "репликация", "кластеризация",
            "балансировка", "контейнеризация", "оркестрация", "реинжиниринг",
            "спецификация", "требование", "документация", "тестирование"
        ]
        
        # Простые запросы, которые НЕ должны считаться сложными
        simple_keywords = [
            "курс", "доллар", "евро", "валюта", "цена", "стоимость", "сколько стоит",
            "погода", "время", "дата", "привет", "здравствуй", "как дела",
            "покажи", "найди", "открой", "прочитай", "посмотри", "что такое"
        ]
        
        # Если запрос содержит простые ключевые слова, он не сложный
        if any(kw in query_lower for kw in simple_keywords):
            return False
        
        # Проверяем длину запроса - короткие запросы обычно простые
        if len(query_lower.split()) < 5:
            return False
        
        return any(kw in query_lower for kw in complex_keywords)
    
    def _is_complex_reasoning_query(self, query: str) -> bool:
        """
        Определяет, является ли запрос очень сложным reasoning-запросом.
        
        Args:
            query: Пользовательский запрос
            
        Returns:
            True если запрос требует особо глубокого reasoning
        """
        if not query:
            return False
        
        query_lower = query.lower()
        
        # Ключевые слова для очень сложных reasoning-запросов
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
        """
        Возвращает информацию о доступности провайдеров.
        
        Returns:
            Словарь с доступностью провайдеров
        """
        ollama_available = self._check_ollama_available()
        deepseek_available = bool(os.getenv("DEEPSEEK_API_KEY"))
        
        return {
            "ollama": ollama_available,
            "deepseek": deepseek_available,
            "vision_available": ollama_available  # Vision только через Ollama
        }


# Создаём глобальный экземпляр селектора
_selector = None

def get_selector() -> ModelSelector:
    """Возвращает глобальный экземпляр ModelSelector"""
    global _selector
    if _selector is None:
        _selector = ModelSelector()
    return _selector