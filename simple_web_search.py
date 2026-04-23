#!/usr/bin/env python3
"""
Простая рабочая версия веб-поиска для ZORA.
Использует DuckDuckGo Instant Answer API.
"""

import requests
import logging

logger = logging.getLogger("ZORA.SimpleWebSearch")

def simple_duckduckgo_search(query: str, num_results: int = 3):
    """Простой поиск через DuckDuckGo Instant Answer API."""
    try:
        params = {
            "q": query,
            "format": "json",
            "no_html": "1",
            "skip_disambig": "1",
            "kl": "ru-ru"
        }
        
        response = requests.get("https://api.duckduckgo.com/", params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            results = []
            
            # Основной ответ
            if data.get("AbstractText"):
                results.append({
                    "title": data.get("Heading", "DuckDuckGo Instant Answer"),
                    "snippet": data.get("AbstractText", "")[:200],
                    "link": data.get("AbstractURL", ""),
                    "source": "duckduckgo"
                })
            
            # Связанные темы
            if "RelatedTopics" in data:
                for topic in data["RelatedTopics"][:num_results]:
                    if isinstance(topic, dict) and "Text" in topic:
                        results.append({
                            "title": topic.get("Text", "").split(" - ")[0] if " - " in topic.get("Text", "") else topic.get("Text", "")[:50],
                            "snippet": topic.get("Text", "")[:150],
                            "link": topic.get("FirstURL", ""),
                            "source": "duckduckgo"
                        })
            
            logger.info(f"✅ Найдено {len(results)} результатов через DuckDuckGo")
            return results
        else:
            logger.warning(f"⚠️ DuckDuckGo API вернул статус {response.status_code}")
            return []
            
    except Exception as e:
        logger.error(f"❌ Ошибка поиска через DuckDuckGo: {e}")
        return []

def get_simple_web_context(query: str) -> str:
    """
    Получает простой контекст из интернета.
    
    Args:
        query: Поисковый запрос
        
    Returns:
        Контекстная информация из интернета
    """
    try:
        # Для налоговых вопросов добавляем год
        if any(word in query.lower() for word in ["ндс", "налог", "закон", "ставка", "2026"]):
            query_with_year = f"{query} 2026"
            results = simple_duckduckgo_search(query_with_year, num_results=2)
        else:
            results = simple_duckduckgo_search(query, num_results=2)
        
        if results:
            context = "Актуальная информация из интернета:\n\n"
            for result in results:
                context += f"• {result['title']}: {result['snippet']}\n"
            return context
        else:
            return "Не удалось найти актуальную информацию в интернете."
            
    except Exception as e:
        logger.error(f"❌ Ошибка при получении контекста: {e}")
        return f"Ошибка при поиске в интернете: {str(e)}"

def test_simple_search():
    """Тестирование простого поиска."""
    print("🧪 Тестирование простого веб-поиска")
    print("=" * 50)
    
    # Тест 1: Налоговый вопрос
    print("\n1. Тест налогового вопроса:")
    context = get_simple_web_context("ставка НДС")
    print(f"Контекст: {context[:200]}...")
    
    # Тест 2: Общий вопрос
    print("\n2. Тест общего вопроса:")
    context = get_simple_web_context("курс доллара")
    print(f"Контекст: {context[:200]}...")
    
    # Тест 3: Прямой поиск
    print("\n3. Тест прямого поиска:")
    results = simple_duckduckgo_search("новости технологий", num_results=2)
    if results:
        print(f"Найдено результатов: {len(results)}")
        for i, result in enumerate(results, 1):
            print(f"{i}. {result['title'][:50]}...")
    else:
        print("Результаты не найдены")
    
    return True

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_simple_search()
    
    print("\n" + "=" * 50)
    print("✅ Простой веб-поиск готов к использованию!")
    print("=" * 50)
    
    print("\n📋 ИНСТРУКЦИЯ ПО ИСПОЛЬЗОВАНИЮ:")
    print("1. Импортируйте функции в свой код:")
    print("   from simple_web_search import get_simple_web_context")
    print("2. Используйте для получения актуальной информации:")
    print("   context = get_simple_web_context('ставка НДС 2026')")
    print("3. Добавьте контекст в промпт LLM")
    print("4. ZORA будет отвечать на основе свежих данных!")
    
    print("\n🚀 ПРИМЕР ИСПОЛЬЗОВАНИЯ В ZORA:")
    print("""
# В оркестраторе или основном коде:
from simple_web_search import get_simple_web_context

def get_agent_response(query):
    # Получаем актуальный контекст
    web_context = get_simple_web_context(query)
    
    # Создаём промпт с актуальными данными
    system_prompt = f\"\"\"Ты ZORA - бизнес-помощник.
Текущий год: 2026. Используй актуальные данные.

{web_context}

Отвечай кратко и по делу.\"\"\"
    
    # Отправляем запрос в LLM
    return generate_response(query, system_prompt)
    """)