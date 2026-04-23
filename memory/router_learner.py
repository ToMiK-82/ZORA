"""
Модуль для автоматического улучшения маршрутизации запросов в ZORA.
Анализирует ошибки маршрутизации и предлагает новые ключевые слова для _legacy_route.
"""

import json
import os
import logging
import re
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict

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

def load_misrouted_queries(feedbacks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Анализирует обратную связь для поиска случаев неправильной маршрутизации.
    
    Args:
        feedbacks: Список записей обратной связи
        
    Returns:
        Список запросов с ошибками маршрутизации
    """
    misrouted_queries = []
    
    # Определяем негативные оценки, связанные с маршрутизацией
    routing_keywords = ["неправильный агент", "не тот агент", "не туда", "маршрутизация", 
                       "направлен не туда", "неправильно направлен", "неправильный ответ"]
    
    for feedback in feedbacks:
        rating = feedback.get("rating", "").lower()
        comment = feedback.get("comment", "").lower()
        query = feedback.get("query", "")
        agent = feedback.get("agent", "")
        
        # Проверяем, является ли отзыв негативным и связанным с маршрутизацией
        is_negative = rating in ["bad", "useless", "wrong", "incorrect", "poor"]
        is_routing_issue = any(keyword in comment for keyword in routing_keywords)
        
        if is_negative and is_routing_issue and query and agent:
            misrouted_queries.append({
                "query": query,
                "agent": agent,
                "comment": comment,
                "rating": rating,
                "timestamp": feedback.get("timestamp", "")
            })
    
    logger.info(f"Найдено {len(misrouted_queries)} запросов с ошибками маршрутизации")
    return misrouted_queries

def extract_keywords_from_query(query: str, agent: str) -> List[str]:
    """
    Извлекает ключевые слова из запроса для улучшения маршрутизации.
    
    Args:
        query: Пользовательский запрос
        agent: Агент, к которому был направлен запрос (возможно, неправильно)
        
    Returns:
        Список ключевых слов
    """
    # Удаляем стоп-слова
    stop_words = {"и", "в", "на", "с", "по", "для", "не", "что", "это", "как", "но", 
                  "а", "или", "из", "от", "до", "за", "у", "о", "же", "бы", "ли", "то"}
    
    # Разбиваем запрос на слова
    words = re.findall(r'\b\w+\b', query.lower())
    
    # Фильтруем стоп-слова и короткие слова
    keywords = [word for word in words if word not in stop_words and len(word) > 2]
    
    # Удаляем дубликаты
    keywords = list(dict.fromkeys(keywords))
    
    return keywords[:10]  # Возвращаем не более 10 ключевых слов

def analyze_misrouting_patterns(misrouted_queries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Анализирует паттерны ошибок маршрутизации.
    
    Args:
        misrouted_queries: Список запросов с ошибками маршрутизации
        
    Returns:
        Словарь с анализом паттернов
    """
    if not misrouted_queries:
        return {}
    
    # Группируем по агентам
    agent_patterns = defaultdict(list)
    
    for query_data in misrouted_queries:
        agent = query_data["agent"]
        query = query_data["query"]
        
        # Извлекаем ключевые слова
        keywords = extract_keywords_from_query(query, agent)
        
        agent_patterns[agent].append({
            "query": query,
            "keywords": keywords,
            "comment": query_data["comment"]
        })
    
    # Анализируем частые ключевые слова для каждого агента
    analysis = {}
    
    for agent, queries in agent_patterns.items():
        # Собираем все ключевые слова
        all_keywords = []
        for query_data in queries:
            all_keywords.extend(query_data["keywords"])
        
        # Подсчитываем частоту
        from collections import Counter
        keyword_counts = Counter(all_keywords)
        
        # Находим наиболее частые ключевые слова
        common_keywords = [keyword for keyword, count in keyword_counts.most_common(5) if count > 1]
        
        analysis[agent] = {
            "query_count": len(queries),
            "common_keywords": common_keywords,
            "sample_queries": [q["query"] for q in queries[:3]],
            "suggestions": generate_routing_suggestions(agent, common_keywords, queries)
        }
    
    return analysis

def generate_routing_suggestions(agent: str, common_keywords: List[str], queries: List[Dict[str, Any]]) -> List[str]:
    """
    Генерирует предложения по улучшению маршрутизации.
    
    Args:
        agent: Агент, к которому неправильно направляются запросы
        common_keywords: Общие ключевые слова для этих запросов
        queries: Список запросов с ошибками
        
    Returns:
        Список предложений
    """
    suggestions = []
    
    if not common_keywords:
        return suggestions
    
    # Определяем возможных правильных агентов на основе ключевых слов
    agent_keyword_mapping = {
        "economist": ["цена", "стоимость", "экономика", "расход", "доход", "бюджет", "финанс"],
        "monitor": ["мониторинг", "конкурент", "акция", "цена конкурента", "рынок"],
        "purchaser": ["закупка", "остаток", "заказ", "поставка", "склад", "товар"],
        "accountant": ["бухгалтер", "1с", "проводка", "налог", "отчёт", "баланс"],
        "logistician": ["логистика", "доставка", "топливо", "платон", "автодор", "транспорт"],
        "sales_manager": ["продажа", "коммерция", "клиент", "сделка", "договор"],
        "support": ["поддержка", "жалоба", "вопрос", "помощь", "проблема"],
        "smm": ["соцсеть", "smm", "маркетинг", "реклама", "социальный"],
        "website": ["сайт", "веб", "интернет", "лендинг", "домен"],
        "reporter": ["отчёт", "уведомление", "телеграм", "статистика", "аналитика"],
        "developer": ["код", "файл", "программа", "python", "скрипт", "ошибка", "debug"]
    }
    
    # Находим агентов, которые могли бы быть правильными
    possible_correct_agents = []
    
    for keyword in common_keywords:
        for correct_agent, agent_keywords in agent_keyword_mapping.items():
            if keyword in agent_keywords and correct_agent != agent:
                possible_correct_agents.append(correct_agent)
    
    # Удаляем дубликаты
    possible_correct_agents = list(dict.fromkeys(possible_correct_agents))
    
    # Генерируем предложения
    if possible_correct_agents:
        for correct_agent in possible_correct_agents[:2]:  # Берем не более 2 возможных агентов
            suggestion = f"Запросы с ключевыми словами '{', '.join(common_keywords[:3])}' " \
                        f"часто направляются к агенту '{agent}', но возможно должны направляться " \
                        f"к агенту '{correct_agent}'. Рассмотрите добавление этих ключевых слов " \
                        f"в _legacy_route для агента '{correct_agent}'."
            suggestions.append(suggestion)
    else:
        # Если не удалось определить правильного агента, предлагаем общие улучшения
        suggestion = f"Запросы с ключевыми словами '{', '.join(common_keywords[:3])}' " \
                    f"часто направляются к агенту '{agent}' с негативной оценкой. " \
                    f"Рассмотрите уточнение маршрутизации для этих ключевых слов."
        suggestions.append(suggestion)
    
    return suggestions

def save_routing_suggestions(suggestions: Dict[str, Any]) -> bool:
    """
    Сохраняет предложения по улучшению маршрутизации в файл.
    
    Args:
        suggestions: Словарь с предложениями
        
    Returns:
        True если успешно, False в противном случае
    """
    suggestions_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "routing_suggestions.json")
    
    try:
        # Создаем структуру для сохранения
        suggestions_data = {
            "generated_at": datetime.now().isoformat(),
            "suggestions": suggestions,
            "summary": {
                "total_agents": len(suggestions),
                "total_queries": sum(agent_data.get("query_count", 0) for agent_data in suggestions.values())
            }
        }
        
        # Создаем директорию, если её нет
        os.makedirs(os.path.dirname(suggestions_path), exist_ok=True)
        
        # Сохраняем в файл
        with open(suggestions_path, 'w', encoding='utf-8') as f:
            json.dump(suggestions_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Сохранено предложений по улучшению маршрутизации для {len(suggestions)} агентов")
        return True
    
    except Exception as e:
        logger.error(f"Ошибка сохранения предложений по маршрутизации: {e}")
        return False

def analyze_and_suggest_routing_improvements() -> Dict[str, Any]:
    """
    Основная функция анализа ошибок маршрутизации и генерации предложений.
    
    Returns:
        Словарь с предложениями по улучшению
    """
    logger.info("Запуск анализа ошибок маршрутизации...")
    
    # Загружаем обратную связь
    feedbacks = load_feedback()
    
    if not feedbacks:
        logger.warning("Нет данных обратной связи для анализа")
        return {}
    
    # Находим запросы с ошибками маршрутизации
    misrouted_queries = load_misrouted_queries(feedbacks)
    
    if not misrouted_queries:
        logger.info("Не найдено ошибок маршрутизации для анализа")
        return {}
    
    # Анализируем паттерны ошибок
    analysis = analyze_misrouting_patterns(misrouted_queries)
    
    if not analysis:
        logger.info("Не удалось проанализировать паттерны ошибок")
        return {}
    
    # Сохраняем предложения
    save_routing_suggestions(analysis)
    
    logger.info(f"Анализ маршрутизации завершен. Проанализировано {len(misrouted_queries)} запросов")
    return analysis

def get_latest_routing_suggestions() -> Dict[str, Any]:
    """
    Возвращает последние сохраненные предложения по улучшению маршрутизации.
    
    Returns:
        Данные предложений или пустой словарь
    """
    suggestions_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "routing_suggestions.json")
    
    try:
        if not os.path.exists(suggestions_path):
            return {}
        
        with open(suggestions_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    except Exception as e:
        logger.error(f"Ошибка загрузки предложений по маршрутизации: {e}")
        return {}

if __name__ == "__main__":
    # Настройка логирования для тестирования
    logging.basicConfig(level=logging.INFO)
    
    # Запуск анализа
    suggestions = analyze_and_suggest_routing_improvements()
    
    if suggestions:
        print("✅ Сгенерированные предложения по улучшению маршрутизации:")
        for agent, agent_data in suggestions.items():
            print(f"\n📋 Агент: {agent}")
            print(f"   Количество запросов с ошибками: {agent_data.get('query_count', 0)}")
            print(f"   Общие ключевые слова: {', '.join(agent_data.get('common_keywords', []))}")
            
            suggestions_list = agent_data.get("suggestions", [])
            if suggestions_list:
                print(f"   Предложения:")
                for i, suggestion in enumerate(suggestions_list, 1):
                    print(f"     {i}. {suggestion}")
            else:
                print(f"   ⚠️ Нет конкретных предложений")
    else:
        print("⚠️ Не удалось сгенерировать предложения по улучшению маршрутизации")