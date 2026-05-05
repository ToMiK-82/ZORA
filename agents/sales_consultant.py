"""
Агент Sales Consultant (Менеджер по продажам) для системы ZORA.
Принимает заказы, консультирует по товарам, обрабатывает возражения.
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, Any, List, Optional

from agents.base import BaseAgent
from core.roles import AgentRole, get_system_prompt
from connectors.llm_client_distributed import generate_sync as llm_generate

try:
    from memory.qdrant_memory import memory as _memory
    MEMORY_AVAILABLE = True
except ImportError:
    MEMORY_AVAILABLE = False
    _memory = None

logger = logging.getLogger(__name__)

# Директория для хранения заказов
ORDERS_DIR = "data"


class SalesConsultant(BaseAgent):
    """
    Менеджер по продажам.
    Принимает заказы, консультирует по товарам, обрабатывает возражения.
    """

    role = AgentRole.SALES_CONSULTANT
    display_name = "Менеджер по продажам"
    description = "Принимает заказы, консультирует по товарам, обрабатывает возражения"
    tools = ["search_catalog", "take_order", "handle_objection"]

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("zora.agent.sales_consultant")
        self._order_counter = 0

    def _process_specific(self, query: str, context: str) -> Dict[str, Any]:
        """
        Обрабатывает запросы, связанные с продажами и заказами.

        Args:
            query: Пользовательский запрос
            context: Извлечённый контекст

        Returns:
            Результат работы агента
        """
        if query is None:
            query = ""

        query_lower = query.lower()

        # 1. Поиск в каталоге
        if any(word in query_lower for word in ["найди", "покажи товар", "каталог", "ищу", "подбери"]):
            return self._search_catalog(query)

        # 2. Оформление заказа
        if any(word in query_lower for word in ["заказать", "купить", "оформить заказ",
                                                  "хочу приобрести", "заказ", "оформить"]):
            return self._handle_order_request(query)

        # 3. Обработка возражений
        if any(word in query_lower for word in ["дорого", "подумаю", "сомневаюсь",
                                                  "надо посоветоваться", "дороговато"]):
            return self._handle_objection(query)

        # 4. Общая консультация
        return self._handle_general_consultation(query, context)

    # ======================================================================
    # Поиск в каталоге
    # ======================================================================
    def _search_catalog(self, query: str) -> Dict[str, Any]:
        """
        Ищет товары в Qdrant (коллекция zora_memory) по запросу.

        Args:
            query: Поисковый запрос

        Returns:
            Результат поиска
        """
        self.logger.info(f"Поиск в каталоге: {query}")

        if not MEMORY_AVAILABLE or _memory is None:
            return {
                "success": True,
                "result": "❌ **Каталог временно недоступен**\n\n"
                          "База данных Qdrant не запущена. Пожалуйста, обратитесь к администратору.\n"
                          "Вы также можете связаться с Ria для уточнения информации.",
                "agent": self.agent_name
            }

        try:
            # Ищем товары в памяти
            results = _memory.search(query=query, limit=10)

            if not results:
                return {
                    "success": True,
                    "result": f"🔍 **По запросу «{query}» ничего не найдено**\n\n"
                              "Попробуйте изменить запрос или уточнить характеристики товара.",
                    "agent": self.agent_name
                }

            # Форматируем результаты
            formatted = []
            count = 0
            for r in results:
                if count >= 5:
                    break
                text = r.get("text", "")
                score = r.get("score", 0)
                metadata = r.get("metadata", {})

                # Пытаемся извлечь цену и артикул
                price = ""
                article = ""
                if isinstance(metadata, dict):
                    price = metadata.get("price", "")
                    article = metadata.get("article", "")

                if price:
                    formatted.append(f"📦 **{text[:100]}**\n   💰 Цена: {price}\n   📋 Артикул: {article or 'не указан'}\n   🔗 Сходство: {score:.2f}")
                else:
                    formatted.append(f"📦 **{text[:150]}**\n   🔗 Сходство: {score:.2f}")
                count += 1

            return {
                "success": True,
                "result": f"🔍 **Результаты поиска по запросу «{query}»**\n\n"
                          + "\n\n".join(formatted)
                          + "\n\n---\n💡 *Хотите оформить заказ? Просто скажите «хочу заказать» и укажите товар.*",
                "agent": self.agent_name
            }

        except Exception as e:
            self.logger.error(f"Ошибка поиска в каталоге: {e}")
            return {
                "success": False,
                "result": f"❌ Ошибка при поиске: {str(e)[:200]}",
                "agent": self.agent_name
            }

    # ======================================================================
    # Оформление заказа
    # ======================================================================
    def _handle_order_request(self, query: str) -> Dict[str, Any]:
        """
        Обрабатывает запрос на оформление заказа.

        Args:
            query: Запрос пользователя

        Returns:
            Результат оформления
        """
        self.logger.info(f"Запрос на заказ: {query}")

        # Пытаемся извлечь детали заказа через LLM
        try:
            extraction_prompt = f"""
Извлеки из запроса пользователя информацию для заказа.
Верни ТОЛЬКО JSON без пояснений.

Формат:
{{"customer_name": "имя клиента или null", "items": [{{"name": "название", "quantity": количество}}], "total": общая_сумма_или_null}}

Запрос: {query}

JSON:
"""
            response = llm_generate(extraction_prompt, temperature=0.1)
            # Пробуем распарсить JSON
            response_clean = response.strip()
            if response_clean.startswith("```"):
                response_clean = response_clean.split("\n", 1)[1].rsplit("\n", 1)[0]
            order_data = json.loads(response_clean)

            customer_name = order_data.get("customer_name")
            items = order_data.get("items", [])
            total = order_data.get("total")

            # Проверяем, хватает ли данных
            if not customer_name or not items:
                return {
                    "success": True,
                    "result": self._ask_clarification(
                        "Для оформления заказа мне нужно знать:\n"
                        "1. **Ваше имя** (как записать заказ)\n"
                        "2. **Что хотите заказать** (название товара и количество)\n\n"
                        "Пожалуйста, уточните эти данные."
                    ),
                    "agent": self.agent_name
                }

            # Сохраняем заказ
            result = self._take_order(customer_name, items, total or 0)
            return {
                "success": True,
                "result": result,
                "agent": self.agent_name
            }

        except (json.JSONDecodeError, Exception) as e:
            self.logger.warning(f"Не удалось распарсить заказ: {e}")
            return {
                "success": True,
                "result": self._ask_clarification(
                    "Пожалуйста, уточните:\n"
                    "1. **Ваше имя**\n"
                    "2. **Что хотите заказать** (название и количество)\n"
                    "3. **Общую сумму** (если знаете)\n\n"
                    "Например: «Закажи 2 мыши по 500 рублей, Иванов Иван»"
                ),
                "agent": self.agent_name
            }

    def _take_order(self, customer_name: str, items: List[Dict], total: float) -> str:
        """
        Сохраняет заказ в файл data/orders.json.

        Args:
            customer_name: Имя клиента
            items: Список товаров [{"name": "...", "quantity": 1}]
            total: Общая сумма

        Returns:
            Сообщение с номером заказа
        """
        os.makedirs(ORDERS_DIR, exist_ok=True)

        # Генерируем номер заказа
        today = datetime.now().strftime("%Y%m%d")
        self._order_counter += 1
        order_id = f"ORD-{today}-{self._order_counter:03d}"

        order = {
            "order_id": order_id,
            "date": datetime.now().isoformat(),
            "customer": customer_name,
            "items": items,
            "total": total,
            "status": "новый"
        }

        # Сохраняем в файл
        orders_file = os.path.join(ORDERS_DIR, "orders.json")
        existing_orders = []
        if os.path.exists(orders_file):
            try:
                with open(orders_file, "r", encoding="utf-8") as f:
                    existing_orders = json.load(f)
            except (json.JSONDecodeError, Exception):
                existing_orders = []

        existing_orders.append(order)
        with open(orders_file, "w", encoding="utf-8") as f:
            json.dump(existing_orders, f, ensure_ascii=False, indent=2)

        self.logger.info(f"✅ Заказ {order_id} сохранён для {customer_name}")

        # Формируем ответ
        items_str = "\n".join([f"  • {item.get('name', 'товар')} x{item.get('quantity', 1)}" for item in items])
        return (
            f"✅ **Заказ оформлен!**\n\n"
            f"📋 **Номер заказа:** `{order_id}`\n"
            f"👤 **Клиент:** {customer_name}\n"
            f"📦 **Товары:**\n{items_str}\n"
            f"💰 **Сумма:** {total:,.2f} руб.\n"
            f"📌 **Статус:** новый\n\n"
            f"Спасибо за заказ! Мы свяжемся с вами для подтверждения."
        )

    # ======================================================================
    # Обработка возражений
    # ======================================================================
    def _handle_objection(self, text: str) -> Dict[str, Any]:
        """
        Анализирует типовые возражения и возвращает готовый ответ.

        Args:
            text: Текст возражения

        Returns:
            Ответ на возражение
        """
        self.logger.info(f"Обработка возражения: {text}")

        text_lower = text.lower()

        # Словарь типовых возражений
        objections = {
            "дорого": (
                "💡 **Понимаю ваше беспокойство о цене!**\n\n"
                "Давайте посмотрим на это с другой стороны:\n"
                "1. **Качество** — мы работаем только с проверенными поставщиками\n"
                "2. **Гарантия** — на все товары предоставляется гарантия\n"
                "3. **Сервис** — бесплатная консультация и поддержка\n\n"
                "Кроме того, у нас есть **гибкая система скидок** при заказе от определённой суммы.\n"
                "Хотите, я подберу более бюджетный вариант?"
            ),
            "подумаю": (
                "🤔 **Конечно, решение должно быть взвешенным!**\n\n"
                "Может быть, я могу помочь с дополнительной информацией?\n"
                "1. **Сравнение** с аналогичными товарами\n"
                "2. **Отзывы** других клиентов\n"
                "3. **Расчёт** выгоды при покупке\n\n"
                "Или, если хотите, я могу **зарезервировать** товар на сегодняшнюю цену."
            ),
            "сомневаюсь": (
                "🤝 **Сомнения — это нормально!**\n\n"
                "Давайте разберёмся вместе:\n"
                "1. Что именно вызывает сомнения?\n"
                "2. Может быть, нужна дополнительная консультация?\n"
                "3. Хотите посмотреть товар вживую?\n\n"
                "Я здесь, чтобы помочь вам принять правильное решение!"
            ),
            "посоветоваться": (
                "👥 **Отличная идея!**\n\n"
                "Я могу подготовить **коммерческое предложение** для вашего руководителя "
                "или **сравнительную таблицу** с другими вариантами.\n\n"
                "Также могу напомнить о себе завтра, если оставите контакт."
            )
        }

        # Ищем подходящее возражение
        for key, response in objections.items():
            if key in text_lower:
                return {
                    "success": True,
                    "result": response,
                    "agent": self.agent_name
                }

        # Если не нашли в словаре, используем LLM
        try:
            prompt = f"""
Ты — менеджер по продажам. Клиент высказал возражение.
Ответь вежливо, профессионально, помоги преодолеть сомнения.

Возражение клиента: {text}

Твой ответ (2-3 предложения, на русском):
"""
            response = llm_generate(prompt, temperature=0.5)
            return {
                "success": True,
                "result": f"💬 **Я вас понимаю!**\n\n{response}",
                "agent": self.agent_name
            }
        except Exception as e:
            return {
                "success": True,
                "result": "💬 **Спасибо за ваш отзыв!** Если у вас есть вопросы, я всегда готов помочь.",
                "agent": self.agent_name
            }

    # ======================================================================
    # Вспомогательные методы
    # ======================================================================
    def get_order_stats(self) -> Dict[str, Any]:
        """
        Возвращает статистику заказов для виджетов дашборда.
        Читает data/orders.json, подсчитывает заказы за сегодня и за неделю.
        """
        orders_file = os.path.join("data", "orders.json")
        if not os.path.exists(orders_file):
            return {"today_count": 0, "week_count": 0, "today_sum": 0.0, "status": "нет данных"}
        
        try:
            with open(orders_file, "r", encoding="utf-8") as f:
                orders = json.load(f)
        except (json.JSONDecodeError, Exception):
            return {"today_count": 0, "week_count": 0, "today_sum": 0.0, "status": "ошибка чтения"}
        
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        from datetime import timedelta
        week_start = today_start - timedelta(days=7)
        
        today_count = 0
        today_sum = 0.0
        week_count = 0
        
        for order in orders:
            try:
                order_date = datetime.fromisoformat(order.get("date", ""))
                if order_date >= today_start:
                    today_count += 1
                    today_sum += float(order.get("total", 0))
                if order_date >= week_start:
                    week_count += 1
            except (ValueError, TypeError):
                continue
        
        return {
            "today_count": today_count,
            "week_count": week_count,
            "today_sum": round(today_sum, 2),
            "status": "ok"
        }

    def _ask_clarification(self, question: str) -> str:
        """
        Возвращает вопрос для уточнения у пользователя.

        Args:
            question: Текст вопроса

        Returns:
            Вопрос
        """
        return f"❓ **Уточнение:**\n\n{question}"

    def _handle_general_consultation(self, query: str, context: str) -> Dict[str, Any]:
        """
        Общая консультация по товарам.

        Args:
            query: Запрос пользователя
            context: Контекст

        Returns:
            Ответ консультации
        """
        # Сначала ищем в каталоге
        search_result = self._search_catalog(query)
        if search_result["success"] and "ничего не найдено" not in search_result["result"]:
            return search_result

        # Если ничего не нашли, используем LLM
        try:
            prompt = f"""{get_system_prompt(AgentRole.SALES_CONSULTANT)}

Контекст: {context if context else "Нет контекста"}

Запрос клиента: {query}

Ответь клиенту вежливо и профессионально. Если нужна дополнительная информация — спроси.
"""
            response = llm_generate(prompt, temperature=0.5)
            return {
                "success": True,
                "result": response,
                "agent": self.agent_name
            }
        except Exception as e:
            return {
                "success": True,
                "result": f"💼 **Чем могу помочь?**\n\n"
                          f"Я могу:\n"
                          f"• 🔍 Найти товар в каталоге\n"
                          f"• 📦 Оформить заказ\n"
                          f"• 💡 Проконсультировать по товарам\n\n"
                          f"Что вас интересует?",
                "agent": self.agent_name
            }
