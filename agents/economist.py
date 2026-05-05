"""
Агент-экономист для расчёта юнит-экономики, красной линии и финансового анализа.
Полностью переработан по образцу developer_assistant с экономической специализацией.
"""

import logging
from typing import Dict, Any
from agents.base import BaseAgent
from core.roles import AgentRole, get_system_prompt
from connectors.llm_client_distributed import generate_sync as llm_generate
try:
    from memory import memory
    MEMORY_AVAILABLE = True
except ImportError:
    MEMORY_AVAILABLE = False
    memory = None
from tools.file_ops import read_file, write_file, list_directory
from tools.shell import run_command
from tools.browser import get_page_text, get_page_html

logger = logging.getLogger(__name__)


class Economist(BaseAgent):
    """Агент-экономист с доступом к инструментам для финансового анализа."""

    role = AgentRole.ECONOMIST
    display_name = "Экономист"
    description = "Анализирует экономические данные, предлагает решения по оптимизации затрат"
    tools = ["read_file", "write_file", "list_directory", "run_command",
             "get_page_text", "get_page_html"]

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("zora.agent.economist")
        self.system_prompt = get_system_prompt(AgentRole.ECONOMIST)

    def get_financial_stats(self) -> Dict[str, Any]:
        """
        Возвращает финансовую статистику для виджетов дашборда (заглушка).
        """
        return {
            "revenue_today": None,
            "revenue_month": None,
            "expenses_today": None,
            "expenses_month": None,
            "profit_today": None,
            "profit_month": None,
            "status": "stub",
            "message": "Для получения реальных данных требуется подключение к 1С"
        }

    def _process_specific(self, query: str, context: str) -> Dict[str, Any]:
        """
        Обработка экономических запросов с использованием LLM и инструментов.

        Args:
            query: Пользовательский запрос
            context: Извлечённый контекст из памяти (может быть пустым, если не передан)

        Returns:
            Словарь с результатом работы агента
        """
        if query is None:
            query = ""
        # Используем переданный контекст (уже извлечённый оркестратором)

        self.logger.info(f"Обработка экономического запроса: {query}")

        # Формируем промпт с инструкциями по использованию инструментов
        prompt = self._build_economist_prompt(query, context)

        # Получаем ответ от LLM
        try:
            response = llm_generate(prompt)  # model=None по умолчанию

            if isinstance(response, dict) and "error" in response:
                return {
                    "success": False,
                    "result": f"Ошибка LLM: {response['error']}",
                    "agent": self.agent_name,
                    "context_used": bool(context)
                }

            # Парсим ответ LLM
            result_text = response.get("text", str(response)) if isinstance(response, dict) else str(response)

            # Проверяем, содержит ли ответ команды для выполнения
            if self._should_execute_tools(result_text):
                return self._execute_tools_from_response(result_text, query, context)

            return {
                "success": True,
                "result": result_text,
                "agent": self.agent_name,
                "context_used": bool(context),
                "tools_used": False
            }

        except Exception as e:
            self.logger.error(f"Ошибка при обработке запроса экономистом: {e}")
            return {
                "success": False,
                "result": f"Ошибка при обработке запроса экономистом: {str(e)}",
                "agent": self.agent_name,
                "context_used": bool(context),
                "error": str(e)
            }

    def _build_economist_prompt(self, query: str, context: str) -> str:
        """Строит промпт для экономиста с инструкциями по инструментам."""

        # Получаем системный промпт
        system_prompt = self.system_prompt if self.system_prompt is not None else ""

        tools_description = """
Доступные инструменты для экономического анализа:

1. **read_file(path)**: Чтение файлов с данными (CSV, Excel, JSON, текстовые файлы)
2. **write_file(path, content)**: Запись результатов анализа в файлы
3. **list_directory(path)**: Просмотр содержимого директорий с данными
4. **run_command(command)**: Выполнение shell команд для анализа данных
5. **get_page_text(url)**: Получение текста с веб-страниц (новости, курсы валют, экономические данные)
6. **get_page_html(url)**: Получение HTML кода страниц для парсинга данных

Примеры использования инструментов:
- Для анализа данных из файла: "Прочитай файл data/sales.csv и проанализируй тренды"
- Для получения актуальных данных: "Получи курс доллара с сайта ЦБ РФ"
- Для сохранения результатов: "Сохрани отчёт в файл reports/economic_analysis.txt"

Если тебе нужны данные из файлов или интернета, укажи это в ответе.
"""

        return f"""{system_prompt}

{tools_description}

Контекст из памяти системы:
{context if context else "Контекст не найден"}

Запрос пользователя: {query}

Твоя задача: предоставить подробный экономический анализ, расчёты и рекомендации.
Если данных недостаточно, укажи, какие инструменты нужно использовать для их получения.
"""

    def _should_execute_tools(self, response_text: str) -> bool:
        """Определяет, нужно ли выполнять инструменты на основе ответа LLM."""
        tool_keywords = [
            "read_file", "write_file", "list_directory", "run_command",
            "get_page_text", "get_page_html", "прочитай файл", "получи данные",
            "сохрани в файл", "выполни команду", "открой страницу"
        ]
        return any(keyword in response_text.lower() for keyword in tool_keywords)

    def _execute_tools_from_response(self, response_text: str, original_query: str, context: str) -> Dict[str, Any]:
        """Выполняет инструменты на основе инструкций в ответе LLM."""
        self.logger.info("Выполнение инструментов на основе ответа LLM")

        # В реальной реализации здесь был бы парсинг ответа LLM и выполнение инструментов
        # Для простоты возвращаем сообщение о необходимости ручного выполнения

        return {
            "success": True,
            "result": f"""{response_text}

Примечание: Агент-экономист определил, что для выполнения запроса нужны инструменты.
Для автоматического выполнения инструментов требуется дополнительная интеграция.
Пока что вы можете:
1. Использовать инструменты вручную через веб-интерфейс
2. Обратиться к ассистенту разработчика для автоматизации""",
            "agent": self.agent_name,
            "context_used": bool(context),
            "tools_requested": True,
            "needs_manual_tool_execution": True
        }

    def _get_exchange_rate(self, currency: str) -> float:
        """
        Заглушка для получения курса валюты.

        Args:
            currency: Код валюты (USD, EUR, CNY)

        Returns:
            Курс или 0.0 с предупреждением
        """
        self.logger.warning(f"Функция получения курса {currency} в разработке")
        return 0.0

    def _read_csv_data(self, path: str) -> str:
        """
        Читает CSV-файл с помощью pandas (если установлен).

        Args:
            path: Путь к CSV-файлу

        Returns:
            Текстовое представление данных
        """
        try:
            import pandas as pd
            df = pd.read_csv(path)
            return df.to_string(max_rows=20)
        except ImportError:
            return "❌ Библиотека pandas не установлена"
        except Exception as e:
            return f"❌ Ошибка чтения CSV: {str(e)[:200]}"
