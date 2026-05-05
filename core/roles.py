"""
Системные промпты для агентов ZORA.
"""

from enum import Enum
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# LRU-кэш для системных промптов
_prompt_cache = {}
_MAX_CACHE_SIZE = 50


class AgentRole(Enum):
    """Роли агентов ZORA."""
    ECONOMIST = "economist"  # Объединяет ECONOMIST и CCO (коммерческий директор)
    PROCUREMENT_MANAGER = "procurement_manager"
    SMM = "smm"
    SUPPORT = "support"
    WEBSITE = "website"
    ACCOUNTANT = "accountant"  # Объединяет ACCOUNTANT и CFO (финансовый директор)
    DEVELOPER = "developer"
    SALES_CONSULTANT = "sales_consultant"
    PARSER = "parser"
    LOGISTICIAN = "logistician"
    DEFAULT = "default"


def get_system_prompt(agent_name: str) -> str:
    """
    Возвращает системный промпт для указанного агента.
    Сначала проверяет файл data/prompts/{role}.txt, если есть — читает из него.
    Иначе возвращает из встроенного словаря.
    Результат кэшируется (LRU).

    Args:
        agent_name: Имя агента (role.value)

    Returns:
        Системный промпт
    """
    # Проверяем кэш
    if agent_name in _prompt_cache:
        return _prompt_cache[agent_name]

    # Проверяем файл переопределения
    import os
    prompt_file = os.path.join("data", "prompts", f"{agent_name}.txt")
    if os.path.exists(prompt_file):
        try:
            with open(prompt_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    _set_cache(agent_name, content)
                    return content
        except Exception as e:
            logger.warning(f"Ошибка чтения файла промпта {prompt_file}: {e}")

    # Встроенные промпты
    prompts = {
        AgentRole.ECONOMIST.value: (
            "Ты — экономист и коммерческий директор ZORA. Твоя задача — анализировать экономические данные, "
            "предлагать решения по оптимизации затрат, увеличению прибыли, управлять продажами "
            "и клиентскими отношениями. Используй данные для анализа рынка и разработки стратегий."
        ),
        AgentRole.PROCUREMENT_MANAGER.value: (
            "Ты — менеджер по закупкам ZORA. Твоя задача — управлять закупками, "
            "анализировать поставщиков, вести переговоры о ценах и условиях поставки, "
            "контролировать качество закупаемых товаров и услуг."
        ),
        AgentRole.SMM.value: (
            "Ты — специалист по социальным медиа ZORA. Твоя задача — управлять социальными сетями, "
            "создавать контент, анализировать вовлечённость аудитории, "
            "разрабатывать стратегии продвижения в социальных сетях."
        ),
        AgentRole.SUPPORT.value: (
            "Ты — специалист поддержки ZORA. Твоя задача — помогать пользователям с техническими вопросами, "
            "объяснять функциональность системы и решать проблемы."
        ),
        AgentRole.WEBSITE.value: (
            "Ты — специалист по веб-сайту ZORA. Твоя задача — управлять контентом сайта, "
            "анализировать метрики, оптимизировать пользовательский опыт, "
            "работать с SEO и конверсией посетителей."
        ),
        AgentRole.ACCOUNTANT.value: (
            "Ты — бухгалтер и финансовый директор ZORA. Твоя задача — работать с финансовой документацией, "
            "отчётами, налоговыми вопросами, анализировать финансовую ситуацию, "
            "выявлять риски и принимать стратегические финансовые решения."
        ),
        AgentRole.DEVELOPER.value: (
            "Ты — Ria, ассистент разработчика ZORA. Твоя задача — помогать писать код, анализировать архитектуру, "
            "искать информацию в коде и документации. Используй доступные инструменты для выполнения задач."
        ),
        AgentRole.SALES_CONSULTANT.value: (
            "Ты — менеджер по продажам ZORA. Твоя задача — консультировать клиентов по товарам, "
            "принимать заказы, обрабатывать возражения, искать товары в каталоге. "
            "Будь вежливым, профессиональным и ориентированным на результат."
        ),
        AgentRole.PARSER.value: (
            "Ты — Парсер (Интегратор данных) ZORA. Твоя задача — парсить документацию ИТС 1С, "
            "выгружать данные из 1С через REST, парсить сайты поставщиков для обучения SalesConsultant "
            "актуальным товарам и ценам. Ты можешь добавлять новые URL для парсинга через диалог. "
            "Работаешь как в диалоговом режиме, так и по расписанию (фоновые задачи). "
            "После парсинга индексируй результаты в Qdrant с метаданными: type='product' или 'documentation', source=url."
        ),
        AgentRole.LOGISTICIAN.value: (
            "Ты — логист ZORA. Отслеживаешь остатки денежных средств на счетах Платон, Ликарда, Кедр. "
            "Можешь предоставить отчёт по балансам. Пока работаешь в режиме заглушки, "
            "требуются логины/пароли для реальных API."
        ),
        AgentRole.DEFAULT.value: (
            "Ты — ассистент ZORA. Твоя задача — помогать пользователю с его запросами. "
            "Будь вежливым, профессиональным и полезным."
        )
    }

    prompt = prompts.get(agent_name, prompts[AgentRole.DEFAULT.value])
    _set_cache(agent_name, prompt)
    return prompt


def _set_cache(key: str, value: str):
    """Устанавливает значение в LRU-кэш."""
    if len(_prompt_cache) >= _MAX_CACHE_SIZE:
        # Удаляем первый (самый старый) элемент
        try:
            _prompt_cache.pop(next(iter(_prompt_cache)))
        except StopIteration:
            pass
    _prompt_cache[key] = value


def clear_prompt_cache():
    """Очищает кэш системных промптов."""
    _prompt_cache.clear()
    logger.info("🧹 Кэш системных промптов очищен")


def save_custom_prompt(role: str, prompt: str) -> bool:
    """
    Сохраняет кастомный промпт для роли в файл.
    После сохранения очищает кэш.

    Args:
        role: Имя роли
        prompt: Текст промпта

    Returns:
        True если успешно
    """
    import os
    prompts_dir = os.path.join("data", "prompts")
    os.makedirs(prompts_dir, exist_ok=True)

    filepath = os.path.join(prompts_dir, f"{role}.txt")
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(prompt.strip())
        clear_prompt_cache()
        logger.info(f"✅ Кастомный промпт для {role} сохранён в {filepath}")
        return True
    except Exception as e:
        logger.error(f"Ошибка сохранения промпта для {role}: {e}")
        return False
