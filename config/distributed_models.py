"""
Конфигурация для упрощённой мультимодельной архитектуры ZORA
"""

import os
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# === УДАЛЁННЫЙ OLLAMA СЕРВЕР ===

# Основной Ollama сервер
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://10.160.68.222:11434")
OLLAMA_HOST_LOCAL = os.getenv("OLLAMA_HOST_LOCAL", "http://localhost:11434")
OLLAMA_HOST_POWERFUL = os.getenv("OLLAMA_HOST_POWERFUL", "http://10.160.68.222:11434")

# Модели для разных типов задач
OLLAMA_VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "qwen3-vl:4b")
OLLAMA_CODER_MODEL = os.getenv("OLLAMA_CODER_MODEL", "qwen2.5-coder:7b")
OLLAMA_PLANNER_MODEL = os.getenv("OLLAMA_PLANNER_MODEL", "qwen3:14b")
OLLAMA_REASONER_MODEL = os.getenv("OLLAMA_REASONER_MODEL", "deepseek-r1:14b")

# Модели для импорта из других файлов (обратная совместимость)
CHAT_MODEL_WEAK = os.getenv("CHAT_MODEL_WEAK", "llama3.2:latest")
CHAT_MODEL_STRONG = os.getenv("CHAT_MODEL_STRONG", "qwen3:14b")
CHAT_MODEL_STRONG_LOCAL = os.getenv("CHAT_MODEL_STRONG_LOCAL", "qwen3:14b")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
EMBED_MODEL = os.getenv("EMBED_MODEL", "bge-m3")

# Тайм-аут для Ollama (сек)
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "180"))

# === DEEPSEEK API (РЕЗЕРВ) ===

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_BASE = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com")
DEEPSEEK_CHAT_MODEL = os.getenv("DEEPSEEK_CHAT_MODEL", "deepseek-chat")
DEEPSEEK_REASONER_MODEL = os.getenv("DEEPSEEK_REASONER_MODEL", "deepseek-reasoner")

# Тайм-аут для DeepSeek (сек)
DEEPSEEK_TIMEOUT = int(os.getenv("DEEPSEEK_TIMEOUT", "120"))

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===

def is_coding_task(model: str) -> bool:
    """Определяет, является ли задача кодированием"""
    if model is None:
        return False
    coding_keywords = ["coder", "code", "qwen2.5-coder", "deepseek-coder"]
    return any(keyword in model.lower() for keyword in coding_keywords)

def is_embedding_task(model: str) -> bool:
    """Определяет, является ли задача эмбеддингом"""
    if model is None:
        return False
    # Точные проверки для embedding моделей
    model_lower = model.lower()
    
    # Проверяем точные названия моделей
    if "bge-m3" in model_lower:
        return True
    # Проверяем, что это именно embedding модель, а не просто содержит "embed" в названии
    if "embed" in model_lower:
        # Исключаем nomic-embed-text, так как мы ее больше не используем
        if "nomic-embed-text" in model_lower:
            return False
        # Проверяем, что это действительно embedding модель
        embedding_indicators = ["embed-model", "embedding", "bge", "embed/"]
        return any(indicator in model_lower for indicator in embedding_indicators)
    
    return False

def is_complex_question(query: str) -> bool:
    """
    Определяет, является ли вопрос сложным.
    
    Сложные вопросы:
    1. Длинные запросы (более 50 слов)
    2. Содержат сложные термины (анализ, алгоритм, архитектура, оптимизация)
    3. Требуют глубокого анализа или вычислений
    4. Содержат несколько подвопросов
    """
    if not query:
        return False
    
    query_lower = query.lower()
    
    # 1. Длина запроса
    words = len(query_lower.split())
    if words > 50:
        return True
    
    # 2. Сложные термины
    complex_terms = [
        "анализ", "алгоритм", "архитектура", "оптимизация", "проектирование",
        "интеграция", "микросервис", "распределённ", "параллельн", "масштабирование",
        "безопасность", "шифрование", "аутентификация", "авторизация", "токен",
        "нейросеть", "машинное обучение", "искусственный интеллект", "трансформер",
        "транзакция", "репликация", "кластеризация", "балансировка", "контейнеризация",
        "оркестрация", "мониторинг", "логирование", "тестирование", "дебаггинг",
        "рефакторинг", "реинжиниринг", "документация", "спецификация", "требование"
    ]
    
    if any(term in query_lower for term in complex_terms):
        return True
    
    # 3. Вопросы с несколькими частями (содержат "и", "или", "также", "кроме")
    multi_part_keywords = [" и ", " или ", " также ", " кроме ", " а также ", " либо "]
    if any(keyword in query_lower for keyword in multi_part_keywords):
        return True
    
    # 4. Вопросы с перечислением (содержат запятые для перечисления)
    if query_lower.count(',') >= 3:
        return True
    
    # 5. Вопросы с требованиями (содержат "нужно", "требуется", "необходимо", "следует")
    requirement_keywords = ["нужно", "требуется", "необходимо", "следует", "должен", "обязательно"]
    if any(keyword in query_lower for keyword in requirement_keywords):
        # Но только если это не простой запрос
        if words > 10:
            return True
    
    return False


def get_model_type(model: str) -> str:
    """Возвращает тип модели"""
    if model is None:
        return "chat"
    if is_embedding_task(model):
        return "embedding"
    elif is_coding_task(model):
        return "coding"
    else:
        return "chat"
