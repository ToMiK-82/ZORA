"""
Агент-бухгалтер для работы с 1С, проводками и налоговой отчётностью.
Создан согласно заданию с новым системным промптом.
"""

import logging
from typing import Dict, Any
from agents.base import BaseAgent
from core.roles import AgentRole, get_system_prompt
from connectors.llm_client_distributed import generate as llm_generate
try:
    from memory import memory
    MEMORY_AVAILABLE = True
except ImportError:
    MEMORY_AVAILABLE = False
    memory = None

logger = logging.getLogger(__name__)


class Accountant(BaseAgent):
    """Агент-бухгалтер для помощи пользователям в работе с 1С и бухгалтерскими документами."""

    role = AgentRole.ACCOUNTANT
    display_name = "Бухгалтер"
    description = "Работает с финансовой документацией, отчётами, налоговыми вопросами"
    tools = []

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("zora.agent.accountant")

    def _process_specific(self, query: str, context: str) -> Dict[str, Any]:
        """
        Обработка бухгалтерских запросов.

        Args:
            query: Пользовательский запрос
            context: Извлечённый контекст из памяти (может быть пустым, если не передан)

        Returns:
            Словарь с результатом работы агента
        """
        if query is None:
            query = ""
        # Используем переданный контекст (уже извлечённый оркестратором)

        self.logger.info(f"Обработка бухгалтерского запроса: {query}")

        # Формируем промпт с системным промптом и контекстом
        prompt = self._build_accountant_prompt(query, context)

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

            return {
                "success": True,
                "result": result_text,
                "agent": self.agent_name,
                "context_used": bool(context)
            }

        except Exception as e:
            self.logger.error(f"Ошибка при обработке запроса бухгалтером: {e}")
            return {
                "success": False,
                "result": f"Ошибка при обработке запроса бухгалтером: {str(e)}",
                "agent": self.agent_name,
                "context_used": bool(context),
                "error": str(e)
            }

    def _build_accountant_prompt(self, query: str, context: str) -> str:
        """Формирует промпт для бухгалтера."""
        system_prompt = get_system_prompt(AgentRole.ACCOUNTANT)

        return f"""{system_prompt}

Контекст из памяти (инструкции, регламенты, документация):
{context if context else "Контекст отсутствует. Документация ещё не проиндексирована или память пуста."}

Запрос пользователя: {query}

Ответ (чёткий, пошаговый, на естественном языке, без технических деталей если они не нужны):"""

    def get_bank_balances(self) -> Dict[str, Any]:
        """
        Возвращает балансы банковских счетов для виджетов дашборда (заглушка).
        """
        return {
            "accounts": [
                {"name": "Расчётный счёт (основной)", "balance": None, "status": "требуется подключение 1С"},
                {"name": "Валютный счёт", "balance": None, "status": "требуется подключение 1С"}
            ],
            "status": "stub"
        }

    def _read_1c_document(self, doc_id: str) -> str:
        """
        Заглушка для чтения документа из 1С.

        Args:
            doc_id: ID документа

        Returns:
            Сообщение о разработке
        """
        self.logger.info(f"Запрос документа 1С: {doc_id}")
        return f"Функция чтения документа {doc_id} из 1С в разработке."
