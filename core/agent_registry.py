"""
Реестр агентов ZORA.
Обеспечивает динамическое обнаружение и регистрацию агентов.
"""

import importlib
import logging
import pkgutil
import sys
from typing import Dict, Any, List, Optional, Type

from agents.base import BaseAgent
from core.roles import AgentRole

logger = logging.getLogger(__name__)

# Глобальный реестр: {role_value: class}
AGENT_REGISTRY: Dict[str, Type[BaseAgent]] = {}


def discover_agents() -> Dict[str, Type[BaseAgent]]:
    """
    Сканирует пакет agents, находит все классы, наследующие BaseAgent
    и у которых role is not None.

    Returns:
        Словарь {role.value: class}
    """
    global AGENT_REGISTRY
    discovered = {}

    import agents as agents_package
    package_path = agents_package.__path__

    for importer, modname, ispkg in pkgutil.iter_modules(package_path):
        if modname.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"agents.{modname}")
            # Ищем все классы, наследующие BaseAgent
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and issubclass(attr, BaseAgent)
                        and attr is not BaseAgent
                        and getattr(attr, 'role', None) is not None):
                    role_value = attr.role.value
                    if role_value in discovered:
                        logger.warning(f"Дублирование роли {role_value}: {attr.__name__} заменяет {discovered[role_value].__name__}")
                    discovered[role_value] = attr
                    logger.info(f"📦 Обнаружен агент: {attr.__name__} (роль: {role_value})")
        except Exception as e:
            logger.warning(f"Ошибка загрузки модуля agents.{modname}: {e}")

    AGENT_REGISTRY = discovered
    logger.info(f"✅ Реестр агентов обновлён: {len(discovered)} агентов")
    return discovered


def get_agent_class(role: str) -> Optional[Type[BaseAgent]]:
    """
    Возвращает класс агента по строке роли.

    Args:
        role: Строка роли (например, "economist", "developer")

    Returns:
        Класс агента или None
    """
    if not AGENT_REGISTRY:
        discover_agents()
    return AGENT_REGISTRY.get(role)


def get_all_agents_info() -> List[Dict[str, Any]]:
    """
    Возвращает список метаинформации обо всех зарегистрированных агентах.

    Returns:
        Список словарей с role, display_name, description, tools
    """
    if not AGENT_REGISTRY:
        discover_agents()

    result = []
    for role_value, cls in AGENT_REGISTRY.items():
        info = cls.get_info()
        info["status"] = "активен"
        result.append(info)
    return result


def get_agent_info(role: str) -> Optional[Dict[str, Any]]:
    """
    Возвращает метаинформацию о конкретном агенте по его роли.

    Args:
        role: Строка роли (например, "economist", "developer")

    Returns:
        Словарь с role, display_name, description, tools или None
    """
    if not AGENT_REGISTRY:
        discover_agents()

    cls = AGENT_REGISTRY.get(role)
    if cls is None:
        return None
    return cls.get_info()


def get_all_agents_dict() -> Dict[str, str]:
    """
    Возвращает словарь {role_value: display_name} для всех зарегистрированных агентов.
    Удобно для передачи в веб-интерфейс.

    Returns:
        Словарь {role_value: display_name}
    """
    if not AGENT_REGISTRY:
        discover_agents()

    result = {}
    for role_value, cls in AGENT_REGISTRY.items():
        info = cls.get_info()
        result[role_value] = info.get("display_name", role_value)
    return result


def reload_agents() -> Dict[str, Type[BaseAgent]]:
    """
    Перезагружает реестр агентов: очищает кэш импорта и вызывает discover_agents заново.

    Returns:
        Обновлённый словарь {role.value: class}
    """
    global AGENT_REGISTRY

    # Очищаем кэш импорта для пакета agents
    for module_name in list(sys.modules.keys()):
        if module_name.startswith("agents.") or module_name == "agents":
            del sys.modules[module_name]

    # Также очищаем кэш для core.roles (промпты)
    from core.roles import clear_prompt_cache
    clear_prompt_cache()

    AGENT_REGISTRY = {}
    return discover_agents()
