"""
Базовый класс для всех агентов ZORA.
Определяет общий интерфейс и методы работы с памятью и LLM.
"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, List

try:
    from memory import memory
    MEMORY_AVAILABLE = True
except ImportError:
    MEMORY_AVAILABLE = False
    memory = None

from connectors.llm_client_distributed import llm_client
from core.roles import get_system_prompt
import asyncio
from datetime import datetime, time


class BaseBackgroundAgent(ABC):
    """Базовый класс для агентов, работающих в фоне."""
    
    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(f"zora.agent.{name}")
        self._running = False
        self._current_task = None
        self._last_activity = None
    
    @abstractmethod
    async def execute(self):
        """Основная логика агента (вызывается планировщиком или циклом)."""
        pass
    
    async def monitoring_loop(self, check_interval: int = 60):
        """
        Бесконечный цикл с проверкой рабочего времени.
        Запускается планировщиком один раз в начале рабочего дня.
        """
        self._running = True
        self.logger.info(f"🔄 Цикл мониторинга {self.name} запущен")
        
        while self._running:
            if self._is_working_time():
                try:
                    self._current_task = "Выполнение задачи"
                    await self.execute()
                    self._last_activity = datetime.now()
                except Exception as e:
                    self.logger.error(f"Ошибка в цикле {self.name}: {e}")
                finally:
                    self._current_task = None
            else:
                self._current_task = f"Ожидание рабочего времени (сейчас {datetime.now().time()})"
            
            await asyncio.sleep(check_interval)
        
        self.logger.info(f"⏹️ Цикл мониторинга {self.name} остановлен")
    
    def _is_working_time(self) -> bool:
        """
        Проверяет, находится ли текущее время в рабочем интервале.
        Должен быть переопределён в дочерних классах.
        """
        return True
    
    def stop(self):
        """Останавливает цикл мониторинга."""
        self._running = False
        self._current_task = "Остановлен"
        self.logger.info(f"🛑 Получена команда остановки для {self.name}")
    
    def get_status(self) -> dict:
        """Возвращает текущий статус агента для API."""
        return {
            "name": self.name,
            "running": self._running,
            "current_task": self._current_task,
            "last_activity": self._last_activity.isoformat() if self._last_activity else None
        }


class BaseAgent(ABC):
    """Абстрактный базовый класс для всех агентов."""

    def __init__(self, agent_name: str):
        """
        Инициализация агента.

        Args:
            agent_name: Имя агента (например, "economist", "monitor")
        """
        self.agent_name = agent_name
        self.logger = logging.getLogger(f"zora.agent.{agent_name}")

    def _retrieve_context(self, query: str, limit: int = 5) -> str:
        """
        Извлекает релевантный контекст из памяти.

        Args:
            query: Поисковый запрос
            limit: Максимальное количество результатов

        Returns:
            Строка с контекстом
        """
        if not MEMORY_AVAILABLE or memory is None:
            self.logger.warning("Память недоступна, контекст не извлечён")
            return ""
        
        try:
            results = memory.search(query=query, limit=limit * 2)
            if not results:
                return ""
            
            # Группировка по файлам
            grouped = {}
            for r in results:
                path = r.get("path", "unknown")
                grouped.setdefault(path, []).append(r)
            
            context_parts = []
            for path, chunks in list(grouped.items())[:limit]:
                context_parts.append(f"\n📁 Файл: {path}")
                for i, chunk in enumerate(chunks[:3], 1):
                    text = chunk.get("text", "")
                    score = chunk.get("score", 0)
                    if len(text) > 500:
                        text = text[:500] + "..."
                    context_parts.append(f"  [{i}] Сходство: {score:.2f}")
                    context_parts.append(f"     {text}")
                    context_parts.append("")
            
            context = "\n".join(context_parts)
            if context:
                context = "📚 РЕЛЕВАНТНЫЙ КОНТЕКСТ ИЗ ПАМЯТИ:\n" + context
                context += "\n\n💡 ИНСТРУКЦИЯ: Используй эту информацию для ответа. Если находишь релевантные фрагменты, цитируй их и указывай из какого файла они взяты."
            
            return context
        except Exception as e:
            self.logger.error(f"Ошибка при извлечении контекста: {e}")
            return ""

    def _store_result(self, query: str, result: str, metadata: Dict[str, Any] = None) -> str:
        """
        Сохраняет результат работы агента в память.

        Args:
            query: Исходный запрос
            result: Результат работы агента
            metadata: Дополнительные метаданные

        Returns:
            ID сохранённой записи
        """
        if not MEMORY_AVAILABLE or memory is None:
            self.logger.warning("Память недоступна, результат не сохранён")
            return ""
            
        if metadata is None:
            metadata = {}

        full_metadata = {
            "agent": self.agent_name,
            "query": query,
            **metadata
        }

        try:
            record_id = memory.store(result, metadata=full_metadata)
            self.logger.debug(f"Результат сохранён в память с ID {record_id}")
            return record_id
        except Exception as e:
            self.logger.error(f"Ошибка при сохранении результата: {e}")
            return ""

    def _build_prompt(self, query: str, context: str = "") -> str:
        """
        Формирует промпт для LLM на основе системного промпта и контекста.

        Args:
            query: Пользовательский запрос
            context: Извлечённый контекст из памяти

        Returns:
            Полный промпт для LLM
        """
        system_prompt = get_system_prompt(self.agent_name)

        prompt_parts = [system_prompt]

        if context:
            prompt_parts.append(f"Релевантный контекст из памяти:\n{context}\n")

        prompt_parts.append(f"Запрос пользователя: {query}")
        prompt_parts.append("\nОтвет агента:")

        return "\n".join(prompt_parts)

    def _call_llm(self, prompt: str, model: str = None) -> str:
        """
        Вызывает LLM через универсальный клиент (автоматически выбирает Ollama или DeepSeek API).

        Args:
            prompt: Полный промпт
            model: Модель (если None, используется модель по умолчанию для выбранного провайдера)

        Returns:
            Ответ LLM
        """
        try:
            response = llm_client.generate(
                prompt=prompt,
                model=model,
                temperature=0.3,
                system=get_system_prompt(self.agent_name)
            )
            return response.strip()
        except Exception as e:
            self.logger.error(f"Ошибка при вызове LLM: {e}")
            return f"Ошибка при обработке запроса: {str(e)}"

    @abstractmethod
    def _process_specific(self, query: str, context: str) -> Dict[str, Any]:
        """
        Абстрактный метод для специфической обработки агентом.
        Должен быть реализован в каждом конкретном агенте.

        Args:
            query: Пользовательский запрос
            context: Извлечённый контекст

        Returns:
            Словарь с результатом работы агента
        """
        pass

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Основной метод обработки запроса агентом.

        Args:
            state: Состояние с запросом и дополнительными данными

        Returns:
            Обновлённое состояние с результатом работы агента
        """
        query = state.get("query", "")
        self.logger.info(f"Агент {self.agent_name} обрабатывает запрос: {query}")

        # Используем контекст из состояния, если он уже извлечён оркестратором
        context = state.get("context")
        if context is None:
            # Если контекста нет, извлекаем сами
            context = self._retrieve_context(query)
            self.logger.debug(f"Извлечён контекст длиной {len(context)} символов")
        else:
            self.logger.debug(f"Используем переданный контекст длиной {len(context)} символов")

        # Вызываем специфическую обработку
        try:
            result = self._process_specific(query, context)
        except Exception as e:
            self.logger.error(f"Ошибка в специфической обработке: {e}")
            result = {
                "success": False,
                "error": str(e),
                "result": f"Агент {self.agent_name} столкнулся с ошибкой при обработке."
            }

        # Сохраняем результат в память
        if result.get("success", True) and "result" in result:
            self._store_result(query, result["result"])

        # Обновляем состояние
        state.update(result)
        return state
