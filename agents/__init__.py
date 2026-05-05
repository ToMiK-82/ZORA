"""
Пакет агентов ZORA.
Обновленная версия после очистки - только актуальные агенты.
"""

from agents.base import BaseAgent
from agents.economist import Economist
from agents.purchaser import Purchaser
from agents.accountant import Accountant
from agents.support import Support
from agents.smm import Smm
from agents.website import Website
from agents.developer_assistant import DeveloperAssistant
from agents.operator_1c_local import Operator1CLocal

# Словарь агентов для оркестратора
# Только актуальные агенты после очистки
agents = {
    'economist': Economist(),
    'purchaser': Purchaser(),
    'accountant': Accountant(),
    'support': Support(),
    'smm': Smm(),
    'website': Website(),
    'developer_assistant': DeveloperAssistant(),
    'operator_1c': Operator1CLocal(),
}

__all__ = [
    "BaseAgent",
    "Economist",
    "Purchaser",
    "Accountant",
    "Support",
    "Smm",
    "Website",
    "DeveloperAssistant",
    "Operator1CLocal",
    "agents"
]
