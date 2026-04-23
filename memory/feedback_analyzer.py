"""
Анализатор обратной связи для системы самообучения ZORA.
Анализирует негативные отзывы и генерирует предложения по улучшению системных промптов агентов.
"""

import json
import os
import logging
from collections import Counter
from datetime import datetime
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

def load_feedback() -> List[Dict[str, Any]]:
    """
    Загружает обратную связь из файла data/feedback.json.
    
    Returns:
        Список записей обратной связи
    """
    feedback_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "feedback.json")
    
    try:
        if not os.path.exists(feedback_path):
            logger.warning(f"Файл обратной связи не найден: {feedback_path}")
            return []
        
        with open(feedback_path, 'r', encoding='utf-8') as f:
            feedbacks = json.load(f)
        
        logger.info(f"Загружено {len(feedbacks)} записей обратной связи")
        return feedbacks
    
    except Exception as e:
        logger.error(f"Ошибка загрузки обратной связи: {e}")
        return []

def analyze_negative_feedback(feedbacks: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """
    Анализирует негативные отзывы и группирует их по агентам.
    
    Args:
        feedbacks: Список записей обратной связи
        
    Returns:
        Словарь {агент: [список проблем]}
    """
    # Определяем негативные оценки
    negative_ratings = ["bad", "useless", "wrong", "incorrect", "poor"]
    
    # Группируем проблемы по агентам
    agent_issues = {}
    
    for feedback in feedbacks:
        rating = feedback.get("rating", "").lower()
        agent = feedback.get("agent", "unknown")
        comment = feedback.get("comment", "")
        query = feedback.get("query", "")
        
        # Проверяем, является ли отзыв негативным
        if rating in negative_ratings or any(word in comment.lower() for word in ["не", "нет", "ошибка", "плохо", "неправильно"]):
            if agent not in agent_issues:
                agent_issues[agent] = []
            
            # Формируем описание проблемы
            issue_text = f"Запрос: {query[:100]}... | Комментарий: {comment}"
            agent_issues[agent].append(issue_text)
    
    # Анализируем частые слова в проблемах
    analyzed_issues = {}
    
    for agent, issues in agent_issues.items():
        if not issues:
            continue
        
        # Собираем все тексты проблем
        all_text = " ".join(issues).lower()
        
        # Удаляем стоп-слова и анализируем частые слова
        stop_words = {"и", "в", "на", "с", "по", "для", "не", "что", "это", "как", "но", "а", "или", "из", "от", "до", "за"}
        words = [word for word in all_text.split() if word not in stop_words and len(word) > 3]
        
        # Находим наиболее частые слова
        word_counts = Counter(words)
        common_words = [word for word, count in word_counts.most_common(10) if count > 1]
        
        # Формируем список проблем с анализом
        analyzed_issues[agent] = {
            "issues": issues[:5],  # Берем первые 5 проблем для анализа
            "common_words": common_words,
            "count": len(issues)
        }
    
    return analyzed_issues

def generate_prompt_suggestions(agent: str, issues_data: Dict[str, Any]) -> List[str]:
    """
    Генерирует предложения по улучшению промпта для указанного агента.
    
    Args:
        agent: Имя агента
        issues_data: Данные о проблемах агента
        
    Returns:
        Список предложений по улучшению
    """
    suggestions = []
    issues = issues_data.get("issues", [])
    common_words = issues_data.get("common_words", [])
    
    if not issues:
        return suggestions
    
    # Базовые предложения на основе частых слов
    if "иностранный" in common_words or "английский" in common_words:
        suggestions.append(f"Добавить в промпт агента {agent} требование отвечать ТОЛЬКО на русском языке без иностранных слов.")
    
    if "код" in common_words or "пример" in common_words:
        suggestions.append(f"Добавить в промпт агента {agent} требование приводить примеры кода при ответах на технические вопросы.")
    
    if "подробно" in common_words or "подробнее" in common_words:
        suggestions.append(f"Усилить требование в промпте агента {agent} давать подробные развернутые ответы.")
    
    if "неправильно" in common_words or "ошибка" in common_words:
        suggestions.append(f"Добавить в промпт агента {agent} требование проверять точность информации перед ответом.")
    
    # Общие предложения
    suggestions.append(f"Пересмотреть системный промпт агента {agent} на основе {len(issues)} негативных отзывов.")
    suggestions.append(f"Проанализировать типичные ошибки агента {agent}: {', '.join(common_words[:3])}")
    
    return suggestions

def save_suggestions(suggestions: Dict[str, List[str]]) -> bool:
    """
    Сохраняет предложения по улучшению в файл.
    
    Args:
        suggestions: Словарь {агент: [предложения]}
        
    Returns:
        True если успешно, False в противном случае
    """
    suggestions_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "prompt_suggestions.json")
    
    try:
        # Создаем структуру для сохранения
        suggestions_data = {
            "generated_at": datetime.now().isoformat(),
            "suggestions": suggestions,
            "summary": {
                "total_agents": len(suggestions),
                "total_suggestions": sum(len(s) for s in suggestions.values())
            }
        }
        
        # Создаем директорию, если её нет
        os.makedirs(os.path.dirname(suggestions_path), exist_ok=True)
        
        # Сохраняем в файл
        with open(suggestions_path, 'w', encoding='utf-8') as f:
            json.dump(suggestions_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Сохранено {len(suggestions)} предложений по улучшению в {suggestions_path}")
        return True
    
    except Exception as e:
        logger.error(f"Ошибка сохранения предложений: {e}")
        return False

def analyze_and_suggest() -> Dict[str, List[str]]:
    """
    Основная функция анализа обратной связи и генерации предложений.
    
    Returns:
        Словарь с предложениями по улучшению
    """
    logger.info("Запуск анализа обратной связи...")
    
    # Загружаем обратную связь
    feedbacks = load_feedback()
    
    if not feedbacks:
        logger.warning("Нет данных обратной связи для анализа")
        return {}
    
    # Анализируем негативные отзывы
    agent_issues = analyze_negative_feedback(feedbacks)
    
    if not agent_issues:
        logger.info("Не найдено негативных отзывов для анализа")
        return {}
    
    # Генерируем предложения для каждого агента
    all_suggestions = {}
    
    for agent, issues_data in agent_issues.items():
        suggestions = generate_prompt_suggestions(agent, issues_data)
        if suggestions:
            all_suggestions[agent] = suggestions
            logger.info(f"Сгенерировано {len(suggestions)} предложений для агента {agent}")
    
    # Сохраняем предложения
    if all_suggestions:
        save_suggestions(all_suggestions)
    
    logger.info(f"Анализ завершен. Сгенерировано предложений для {len(all_suggestions)} агентов")
    return all_suggestions

def get_latest_suggestions() -> Dict[str, Any]:
    """
    Возвращает последние сохраненные предложения.
    
    Returns:
        Данные предложений или пустой словарь
    """
    suggestions_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "prompt_suggestions.json")
    
    try:
        if not os.path.exists(suggestions_path):
            return {}
        
        with open(suggestions_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    except Exception as e:
        logger.error(f"Ошибка загрузки предложений: {e}")
        return {}

if __name__ == "__main__":
    # Настройка логирования для тестирования
    logging.basicConfig(level=logging.INFO)
    
    # Запуск анализа
    suggestions = analyze_and_suggest()
    
    if suggestions:
        print("✅ Сгенерированные предложения:")
        for agent, agent_suggestions in suggestions.items():
            print(f"\n📋 Агент: {agent}")
            for i, suggestion in enumerate(agent_suggestions, 1):
                print(f"  {i}. {suggestion}")
    else:
        print("⚠️ Не удалось сгенерировать предложения")