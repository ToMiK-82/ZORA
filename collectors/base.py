"""
Базовый класс для всех коллекторов данных.
Стандартизирует прогресс, статус и интерфейс запуска.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    def __init__(self, config: dict = None):
        """
        Args:
            config: словарь с параметрами коллектора (url, ключи API и т.п.)
        """
        self.config = config or {}
        self.progress = 0.0          # 0..1
        self.status = "idle"         # idle / running / done / error
        self._current_step_message = ""
        self._stop_event = asyncio.Event()

    @abstractmethod
    async def run(self, params: dict) -> dict:
        """
        Запускает сбор и индексацию данных.

        Args:
            params: параметры запуска (mode, limit, entity_filter и т.п.)

        Returns:
            dict с ключами:
                - success: bool
                - chunks_added: int (сколько чанков добавлено в Qdrant)
                - items_processed: int (сколько элементов обработано)
                - errors: list[str]
        """
        ...

    def get_progress(self) -> dict:
        """Возвращает текущий прогресс коллектора."""
        return {
            "collector": self.__class__.__name__,
            "progress": self.progress,
            "status": self.status,
            "message": self._current_step_message
        }

    def stop(self):
        """Устанавливает флаг остановки для длительных операций."""
        self._stop_event.set()
        self.status = "stopped"

    def _update_progress(self, progress: float, message: str = ""):
        """Обновляет прогресс и сообщение."""
        self.progress = max(0.0, min(progress, 1.0))
        self._current_step_message = message

    @staticmethod
    async def _run_sync_in_thread(func, *args, **kwargs):
        """Запускает синхронную функцию в отдельном потоке, не блокируя event loop."""
        return await asyncio.to_thread(func, *args, **kwargs)