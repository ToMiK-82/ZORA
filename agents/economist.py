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
    
    def __init__(self):
        super().__init__(AgentRole.ECONOMIST.value)
        self.logger = logging.getLogger("zora.agent.economist")
        self.system_prompt = get_system_prompt(AgentRole.ECONOMIST)
    
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
    
    def _retrieve_context(self, query: str, limit: int = 5) -> str:
        try:
            from memory import memory
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
