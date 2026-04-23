"""
Telegram-обработчик для интеграции ZORA с Telegram-ботом.
Позволяет Telegram-боту использовать оркестратор агентов ZORA.
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("zora.telegram.handler")


class TelegramHandler:
    """Обработчик для взаимодействия с ZORA из Telegram-бота."""

    def __init__(self):
        self.logger = logger
        self._orchestrator = None
        self._zora_core = None
        
        # Попытка загрузить оркестратор
        try:
            from core.orchestrator import orchestrator
            self._orchestrator = orchestrator
            self.logger.info("✅ Оркестратор ZORA загружен для Telegram-бота")
        except ImportError as e:
            self.logger.warning(f"⚠️ Оркестратор не найден: {e}")
        
        # Классическое ядро ZORA больше не используется, используем только оркестратор
        self._zora_core = None
        self.logger.info("ℹ️ Классическое ядро ZORA не используется, используется только оркестратор")
    
    def process_message(self, message: str, user_id: int, chat_id: int) -> Dict[str, Any]:
        """
        Обрабатывает сообщение от пользователя Telegram.

        Args:
            message: Текст сообщения
            user_id: ID пользователя Telegram
            chat_id: ID чата

        Returns:
            Словарь с результатом обработки
        """
        self.logger.info(f"Обработка сообщения от пользователя {user_id}: {message[:100]}...")
        
        # Пытаемся использовать оркестратор, если доступен
        if self._orchestrator:
            try:
                result = self._orchestrator.process(message)
                if result.get("success"):
                    return {
                        "success": True,
                        "text": result.get("result", "Нет ответа"),
                        "agent": result.get("agent", "unknown"),
                        "source": "orchestrator",
                        "context": result.get("context", "")
                    }
            except Exception as e:
                self.logger.error(f"Ошибка оркестратора: {e}")
        
        # Fallback к классическому ядру ZORA
        if self._zora_core:
            try:
                response = self._zora_core.speak(message)
                return {
                    "success": True,
                    "text": response,
                    "agent": "zora_core",
                    "source": "zora_core",
                    "context": ""
                }
            except Exception as e:
                self.logger.error(f"Ошибка классического ядра ZORA: {e}")
        
        # Если ничего не работает, возвращаем заглушку
        return {
            "success": False,
            "text": "Извините, сервис ZORA временно недоступен. Попробуйте позже.",
            "agent": "none",
            "source": "fallback",
            "error": "Все обработчики недоступны"
        }
    
    def get_help_text(self) -> str:
        """Возвращает текст помощи для пользователя."""
        help_text = """
🤖 *ZORA Assistant* — ваш интеллектуальный помощник в бизнесе

*Доступные функции:*
• 📊 *Финансовый анализ* — прибыль, расходы, налоги
• 🚛 *Логистика* — маршруты, доставка, топливо
• 📦 *Закупки* — остатки, прогнозы, заказы
• 📄 *Бухгалтерия* — проводки, отчёты, 1С
• 📈 *Аналитика* — отчёты, тренды, прогнозы
• 💬 *Поддержка* — ответы на вопросы клиентов
• 📱 *SMM* — контент для соцсетей
• 🌐 *Сайт* — аналитика и оптимизация

*Примеры запросов:*
• "Какая прибыль за месяц?"
• "Оцени маршрут до Екатеринбурга"
• "Нужно ли заказывать курицу?"
• "Сформируй отчёт по продажам"
• "Напиши пост для Instagram"

Просто напишите ваш вопрос, и ZORA направит его нужному специалисту!
        """
        return help_text
    
    def get_status(self) -> Dict[str, Any]:
        """Возвращает статус обработчика."""
        return {
            "orchestrator_available": self._orchestrator is not None,
            "zora_core_available": self._zora_core is not None,
            "status": "ready" if (self._orchestrator or self._zora_core) else "unavailable"
        }


# Глобальный экземпляр обработчика
telegram_handler = TelegramHandler()
