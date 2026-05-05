"""
Агент внутренней поддержки для сотрудников.
Помогает с вопросами по документации, регламентам, инструкциям, работе с 1С, логистикой, финансами.
"""

from typing import Dict, Any
from agents.base import BaseAgent
from core.roles import AgentRole, get_system_prompt
from connectors.llm_client_distributed import generate_sync as generate
try:
    from memory import memory
    MEMORY_AVAILABLE = True
except ImportError:
    MEMORY_AVAILABLE = False
    memory = None


class Support(BaseAgent):
    """Агент внутренней поддержки для сотрудников компании."""

    role = AgentRole.SUPPORT
    display_name = "Специалист поддержки"
    description = "Помогает пользователям с техническими вопросами и проблемами"
    tools = []

    def __init__(self):
        super().__init__()
        # Системный промпт загружается из core.roles.py
        self.system_prompt = get_system_prompt(AgentRole.SUPPORT)

    def _process_specific(self, query: str, context: str) -> Dict[str, Any]:
        """
        Обрабатывает запросы сотрудников с использованием LLM.

        Args:
            query: Запрос сотрудника
            context: Извлечённый контекст из памяти (может быть пустым, если не передан)

        Returns:
            Результат работы агента
        """
        if query is None:
            query = ""
        # Используем переданный контекст (уже извлечённый оркестратором)

        # Системный промпт не должен быть None
        system_prompt = self.system_prompt if self.system_prompt is not None else ""

        # Формируем полный промпт
        full_prompt = f"""{system_prompt}

Контекст из памяти (документация, регламенты, инструкции):
{context if context else "Контекст не найден"}

Запрос сотрудника: {query}

Ответ (вежливый, полезный, на русском языке):
"""

        try:
            response = generate(full_prompt)  # model=None по умолчанию

            if response is None:
                return {
                    "success": False,
                    "result": "Ошибка LLM: функция generate вернула None",
                    "agent": self.agent_name,
                    "context_used": bool(context)
                }

            if isinstance(response, dict) and "error" in response:
                return {
                    "success": False,
                    "result": f"Ошибка LLM: {response['error']}",
                    "agent": self.agent_name,
                    "context_used": bool(context)
                }

            result_text = str(response) if response is not None else ""

            return {
                "success": True,
                "result": result_text,
                "agent": self.agent_name,
                "context_used": bool(context)
            }

        except Exception as e:
            return {
                "success": False,
                "result": f"Ошибка при обработке запроса поддержки: {str(e)}",
                "agent": self.agent_name,
                "context_used": bool(context),
                "error": str(e)
            }
