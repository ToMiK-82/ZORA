"""
Планировщик фоновых задач для ZORA.
Запускает автоматическое обучение, проверки и обслуживание по расписанию.
"""

import logging
import asyncio
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Callable, Optional

logger = logging.getLogger(__name__)


class ScheduledTask:
    """Одна запланированная задача."""

    def __init__(self, name: str, callback: Callable, interval_hours: float = 24,
                 at_time: Optional[str] = None, enabled: bool = True):
        self.name = name
        self.callback = callback
        self.interval_hours = interval_hours
        self.at_time = at_time  # "HH:MM" — время выполнения
        self.enabled = enabled
        self.last_run: Optional[datetime] = None
        self.next_run: Optional[datetime] = None
        self.runs_count = 0
        self.errors_count = 0

    def calculate_next_run(self) -> datetime:
        now = datetime.now()
        if self.at_time:
            # Запуск в указанное время каждый день
            hour, minute = map(int, self.at_time.split(':'))
            candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= now:
                candidate += timedelta(days=1)
            return candidate
        else:
            # Интервальный запуск
            if self.last_run is None:
                return now
            return self.last_run + timedelta(hours=self.interval_hours)

    def is_due(self) -> bool:
        if not self.enabled:
            return False
        if self.next_run is None:
            self.next_run = self.calculate_next_run()
            return False
        return datetime.now() >= self.next_run

    async def execute(self) -> Dict[str, Any]:
        """Выполняет задачу и возвращает результат."""
        logger.info(f"🔄 Запуск задачи: {self.name}")
        start = time.time()
        try:
            if asyncio.iscoroutinefunction(self.callback):
                result = await self.callback()
            else:
                result = self.callback()

            elapsed = time.time() - start
            self.last_run = datetime.now()
            self.next_run = self.calculate_next_run()
            self.runs_count += 1

            logger.info(f"✅ Задача '{self.name}' выполнена за {elapsed:.1f}с")
            return {"success": True, "name": self.name, "elapsed": elapsed, "result": result}

        except Exception as e:
            elapsed = time.time() - start
            self.errors_count += 1
            logger.error(f"❌ Ошибка задачи '{self.name}': {e}")
            return {"success": False, "name": self.name, "elapsed": elapsed, "error": str(e)}


class Scheduler:
    """Планировщик фоновых задач."""

    def __init__(self):
        self.tasks: Dict[str, ScheduledTask] = {}
        self._running = False
        self._loop_task: Optional[asyncio.Task] = None

    def add_task(self, name: str, callback: Callable, interval_hours: float = 24,
                 at_time: Optional[str] = None, enabled: bool = True) -> ScheduledTask:
        """Добавляет задачу в планировщик."""
        task = ScheduledTask(name, callback, interval_hours, at_time, enabled)
        self.tasks[name] = task
        logger.info(f"📅 Добавлена задача '{name}' (интервал: {interval_hours}ч, время: {at_time or 'интервал'})")
        return task

    def remove_task(self, name: str) -> bool:
        """Удаляет задачу."""
        if name in self.tasks:
            del self.tasks[name]
            logger.info(f"🗑️ Удалена задача '{name}'")
            return True
        return False

    def get_status(self) -> Dict[str, Any]:
        """Возвращает статус всех задач."""
        return {
            "running": self._running,
            "tasks": {
                name: {
                    "enabled": t.enabled,
                    "last_run": t.last_run.isoformat() if t.last_run else None,
                    "next_run": t.next_run.isoformat() if t.next_run else None,
                    "runs_count": t.runs_count,
                    "errors_count": t.errors_count
                }
                for name, t in self.tasks.items()
            }
        }

    async def _loop(self):
        """Главный цикл планировщика."""
        logger.info("🔄 Планировщик запущен")
        while self._running:
            for task in self.tasks.values():
                if task.is_due():
                    asyncio.create_task(task.execute())
            await asyncio.sleep(30)  # Проверка каждые 30 секунд

    def start(self):
        """Запускает планировщик."""
        if self._running:
            logger.warning("Планировщик уже запущен")
            return
        self._running = True
        self._loop_task = asyncio.create_task(self._loop())
        logger.info("✅ Планировщик фоновых задач запущен")

    async def stop(self):
        """Останавливает планировщик."""
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        logger.info("⏹️ Планировщик остановлен")

    def run_now(self, name: str) -> Dict[str, Any]:
        """Запускает задачу немедленно (синхронно)."""
        if name not in self.tasks:
            return {"success": False, "error": f"Задача '{name}' не найдена"}
        task = self.tasks[name]
        # Запускаем в текущем event loop
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Создаём задачу в текущем loop
                future = asyncio.run_coroutine_threadsafe(task.execute(), loop)
                return future.result(timeout=300)
            else:
                return asyncio.run(task.execute())
        except Exception as e:
            return {"success": False, "error": str(e)}


# Глобальный экземпляр планировщика
scheduler = Scheduler()
