"""
Модуль для сохранения "уроков" (опыта) в память ZORA.
Сохраняет контекст решений для самообучения системы.
"""

import logging
import time
from typing import Dict, Any, Optional
try:
    from memory import memory
    MEMORY_AVAILABLE = True
except ImportError:
    MEMORY_AVAILABLE = False
    memory = None

logger = logging.getLogger(__name__)


def save_lesson(
    query: str,
    response: str,
    result: str,
    agent: str = "developer_assistant",
    metadata: Optional[Dict[str, Any]] = None
) -> str:
    """
    Сохраняет урок (опыт) в память для самообучения системы.
    
    Args:
        query: Исходный запрос пользователя
        response: Ответ ассистента
        result: Результат выполнения (если есть)
        agent: Агент, который обработал запрос
        metadata: Дополнительные метаданные
        
    Returns:
        ID сохранённого урока
    """
    try:
        # Формируем текст урока
        lesson_text = f"""
Запрос: {query}

Ответ ассистента ({agent}):
{response}

Результат:
{result}
"""
        
        # Формируем метаданные
        lesson_metadata = {
            "type": "lesson",
            "agent": agent,
            "query": query,
            "timestamp": time.time(),
            "result_summary": result[:100] if result else "",
            "lesson_type": "success" if result and "успех" in result.lower() or "успешно" in result.lower() else "general"
        }
        
        # Добавляем дополнительные метаданные
        if metadata:
            lesson_metadata.update(metadata)
        
        # Сохраняем в память
        lesson_id = memory.store(lesson_text, lesson_metadata)
        
        logger.info(f"Урок сохранён (ID: {lesson_id}, агент: {agent})")
        return lesson_id
        
    except Exception as e:
        logger.error(f"Ошибка сохранения урока: {e}")
        return ""


def search_lessons(
    query: str = "",
    agent: Optional[str] = None,
    limit: int = 5,
    lesson_type: Optional[str] = None
) -> list:
    """
    Ищет сохранённые уроки в памяти.
    
    Args:
        query: Поисковый запрос
        agent: Фильтр по агенту
        limit: Максимальное количество результатов
        lesson_type: Тип урока (success, general, error)
        
    Returns:
        Список найденных уроков
    """
    try:
        # Формируем фильтр
        filter_dict = {"type": "lesson"}
        if agent:
            filter_dict["agent"] = agent
        if lesson_type:
            filter_dict["lesson_type"] = lesson_type
        
        # Ищем в памяти
        results = memory.search(query, limit=limit)
        
        # Фильтруем только уроки
        lessons = []
        for result in results:
            if result.get("metadata", {}).get("type") == "lesson":
                lessons.append({
                    "text": result["text"],
                    "metadata": result["metadata"],
                    "score": result.get("score", 0)
                })
        
        logger.debug(f"Найдено {len(lessons)} уроков по запросу: {query}")
        return lessons
        
    except Exception as e:
        logger.error(f"Ошибка поиска уроков: {e}")
        return []


def analyze_lessons_for_improvements() -> str:
    """
    Анализирует сохранённые уроки и предлагает улучшения.
    
    Returns:
        Текст с предложениями по улучшению
    """
    try:
        # Получаем последние уроки
        lessons = search_lessons(limit=20)
        
        if not lessons:
            return "Нет сохранённых уроков для анализа."
        
        # Анализируем уроки
        success_count = sum(1 for l in lessons if l["metadata"].get("lesson_type") == "success")
        total_count = len(lessons)
        success_rate = (success_count / total_count * 100) if total_count > 0 else 0
        
        # Формируем отчёт
        report = f"""
Анализ сохранённых уроков ZORA:
===============================
Всего уроков: {total_count}
Успешных решений: {success_count}
Процент успеха: {success_rate:.1f}%

Последние успешные решения:
"""
        
        # Добавляем примеры успешных решений
        success_lessons = [l for l in lessons if l["metadata"].get("lesson_type") == "success"]
        for i, lesson in enumerate(success_lessons[:3], 1):
            query = lesson["metadata"].get("query", "Неизвестно")[:50]
            agent = lesson["metadata"].get("agent", "Неизвестно")
            report += f"\n{i}. [{agent}] {query}..."
        
        # Предложения по улучшению
        report += "\n\nПредложения по улучшению:\n"
        
        if success_rate < 70:
            report += "1. Увеличить количество успешных решений - добавить больше примеров в память\n"
        
        if total_count < 10:
            report += "2. Накопить больше опыта - продолжать работу с системой\n"
        
        # Анализ по агентам
        agents = {}
        for lesson in lessons:
            agent = lesson["metadata"].get("agent", "unknown")
            agents[agent] = agents.get(agent, 0) + 1
        
        if agents:
            report += "\nРаспределение по агентам:\n"
            for agent, count in agents.items():
                report += f"  - {agent}: {count} уроков\n"
        
        logger.info(f"Анализ уроков завершён: {total_count} уроков, успех {success_rate:.1f}%")
        return report
        
    except Exception as e:
        logger.error(f"Ошибка анализа уроков: {e}")
        return f"Ошибка анализа уроков: {e}"


def schedule_lesson_analysis(interval_hours: int = 24):
    """
    Запускает периодический анализ уроков.
    
    Args:
        interval_hours: Интервал анализа в часах
    """
    import asyncio
    
    async def _analysis_task():
        while True:
            try:
                logger.info("🚀 Запуск анализа сохранённых уроков...")
                report = analyze_lessons_for_improvements()
                
                # Сохраняем отчёт анализа как новый урок
                if "Ошибка" not in report and "Нет сохранённых уроков" not in report:
                    save_lesson(
                        query="Анализ эффективности системы",
                        response=report,
                        result="Анализ завершён",
                        agent="system_analyzer",
                        metadata={"analysis_type": "periodic"}
                    )
                
                logger.info("✅ Анализ уроков завершён")
                
            except Exception as e:
                logger.error(f"Ошибка в задаче анализа уроков: {e}")
            
            # Ждем указанный интервал
            await asyncio.sleep(interval_hours * 3600)
    
    # Запускаем фоновую задачу
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_analysis_task())
        else:
            loop.run_until_complete(_analysis_task())
    except Exception as e:
        logger.error(f"Не удалось запустить анализ уроков: {e}")
    
    logger.info(f"✅ Анализ уроков запланирован (интервал: {interval_hours} часов)")


if __name__ == "__main__":
    # Тестирование модуля
    logging.basicConfig(level=logging.INFO)
    
    # Тест сохранения урока
    lesson_id = save_lesson(
        query="Как прочитать файл main.py?",
        response="Используй функцию read_file из tools.file_ops",
        result="Файл успешно прочитан",
        agent="developer_assistant"
    )
    
    print(f"Урок сохранён с ID: {lesson_id}")
    
    # Тест поиска уроков
    lessons = search_lessons("файл")
    print(f"Найдено уроков: {len(lessons)}")
    
    # Тест анализа
    report = analyze_lessons_for_improvements()
    print(f"Отчёт анализа:\n{report}")