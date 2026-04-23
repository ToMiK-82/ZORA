"""
Агент Главный бухгалтер для контроля проводок, НДС, учётной политики.
"""

from typing import Dict, Any
from agents.base import BaseAgent


class ChiefAccountant(BaseAgent):
    """Агент Главный бухгалтер."""

    def __init__(self):
        super().__init__("chief_accountant")

    def _process_specific(self, query: str, context: str) -> Dict[str, Any]:
        """
        Обрабатывает запросы по бухгалтерскому учёту.

        Args:
            query: Пользовательский запрос
            context: Извлечённый контекст

        Returns:
            Результат работы агента
        """
        # Пока заглушка - возвращаем сообщение о разработке
        return {
            "success": True,
            "result": "Агент Главный бухгалтер ещё в разработке. Запрос: " + query,
            "agent": self.agent_name,
            "context_used": bool(context)
        }