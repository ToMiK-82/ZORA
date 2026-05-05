"""
Агент-логист для отслеживания остатков на счетах Платон, Ликарда, Кедр.
Пока работает в режиме заглушки, требуются логины/пароли для реальных API.
"""

import logging
from typing import Dict, Any
from datetime import datetime

from agents.base import BaseAgent
from core.roles import AgentRole, get_system_prompt
from connectors.llm_client_distributed import generate_sync as llm_generate

logger = logging.getLogger(__name__)


class Logistician(BaseAgent):
    """Агент-логист для отслеживания балансов счетов."""

    role = AgentRole.LOGISTICIAN
    display_name = "Логист"
    description = "Отслеживает остатки на счетах Платон, Ликарда, Кедр"
    tools = []

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("zora.agent.logistician")

    def _process_specific(self, query: str, context: str) -> Dict[str, Any]:
        """
        Обрабатывает запросы, связанные с логистикой и балансами счетов.

        Args:
            query: Пользовательский запрос
            context: Извлечённый контекст

        Returns:
            Результат работы агента
        """
        if query is None:
            query = ""
        query_lower = query.lower()

        # 1. Запрос баланса
        if any(word in query_lower for word in ["баланс", "остаток", "счёт", "деньги", "платон", "ликарда", "кедр", "отчёт"]):
            return self._show_balances(query)

        # 2. Помощь
        if any(word in query_lower for word in ["помощь", "help", "что ты умеешь", "команды"]):
            return {
                "success": True,
                "result": (
                    "🤖 **Логист — доступные команды:**\n\n"
                    "• `покажи балансы` — отчёт по всем счетам\n"
                    "• `баланс Платон` — баланс счёта Платон\n"
                    "• `баланс Ликарда` — баланс счёта Ликарда\n"
                    "• `баланс Кедр` — баланс счёта Кедр\n\n"
                    "⚠️ В настоящее время работаю в режиме заглушки. "
                    "Для реального подключения требуются логины и пароли к API."
                ),
                "agent": self.agent_name
            }

        # По умолчанию — используем LLM
        try:
            prompt = f"""{get_system_prompt(AgentRole.LOGISTICIAN)}

Запрос пользователя: {query}

Ответь пользователю. Если запрос не относится к логистике, объясни, что ты умеешь делать.
"""
            response = llm_generate(prompt, temperature=0.3)
            return {"success": True, "result": response, "agent": self.agent_name}
        except Exception as e:
            return {
                "success": True,
                "result": (
                    "Я — Логист. Я отслеживаю остатки на счетах Платон, Ликарда, Кедр.\n"
                    "Пока работаю в режиме заглушки. Напишите «помощь» для списка команд."
                ),
                "agent": self.agent_name
            }

    def get_balances(self) -> Dict[str, Any]:
        """
        Возвращает словарь с балансами счетов для виджетов дашборда.
        """
        return {
            "platon": {"balance": None, "status": "требуется подключение"},
            "likarda": {"balance": None, "status": "требуется подключение"},
            "kedr": {"balance": None, "status": "требуется подключение"}
        }

    def _show_balances(self, query: str) -> Dict[str, Any]:
        """
        Возвращает отчёт по балансам счетов (заглушка).

        Args:
            query: Запрос пользователя

        Returns:
            Отчёт по балансам
        """
        query_lower = query.lower()

        # Заглушка данных
        accounts = {
            "platon": {"name": "Платон", "balance": None, "status": "требуется подключение"},
            "likarda": {"name": "Ликарда", "balance": None, "status": "требуется подключение"},
            "kedr": {"name": "Кедр", "balance": None, "status": "требуется подключение"}
        }

        # Фильтруем по запросу
        if "платон" in query_lower:
            accounts = {k: v for k, v in accounts.items() if k == "platon"}
        elif "ликарда" in query_lower:
            accounts = {k: v for k, v in accounts.items() if k == "likarda"}
        elif "кедр" in query_lower:
            accounts = {k: v for k, v in accounts.items() if k == "kedr"}

        # Формируем отчёт
        report_lines = [
            "📊 **Отчёт по балансам счетов**",
            f"📅 *{datetime.now().strftime('%d.%m.%Y %H:%M')}*\n"
        ]

        for acc in accounts.values():
            report_lines.append(
                f"🏦 **{acc['name']}**\n"
                f"   💰 Баланс: {acc['balance'] if acc['balance'] is not None else 'недоступно'}\n"
                f"   ⚠️ Статус: {acc['status']}\n"
            )

        report_lines.append(
            "\n---\n"
            "⚠️ **Режим заглушки.** Для получения реальных данных требуется:\n"
            "1. Логин и пароль к личному кабинету **Платон**\n"
            "2. Логин и пароль к личному кабинету **Ликарда**\n"
            "3. Логин и пароль к личному кабинету **Кедр**\n\n"
            "После предоставления доступов я смогу показывать актуальные балансы."
        )

        return {
            "success": True,
            "result": "\n".join(report_lines),
            "agent": self.agent_name
        }
