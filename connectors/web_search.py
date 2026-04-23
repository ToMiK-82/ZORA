"""
Модуль для веб-поиска через различные API.
Позволяет ZORA получать свежие данные из интернета.
"""

import os
import requests
import logging
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("ZORA.WebSearch")

class WebSearch:
    """Класс для выполнения веб-поиска через различные API."""
    
    def __init__(self):
        self.serpapi_key = os.getenv("SERPAPI_KEY")
        self.google_api_key = os.getenv("GOOGLE_API_KEY")
        self.google_cse_id = os.getenv("GOOGLE_CSE_ID")
        
    def search_serpapi(self, query: str, num_results: int = 5) -> Optional[List[Dict[str, str]]]:
        """Поиск через SerpAPI (serpapi.com)."""
        if not self.serpapi_key:
            logger.warning("⚠️ SERPAPI_KEY не установлен в переменных окружения")
            return None
        
        try:
            params = {
                "q": query,
                "api_key": self.serpapi_key,
                "num": num_results,
                "hl": "ru",  # Язык: русский
                "gl": "ru"   # Страна: Россия
            }
            
            response = requests.get("https://serpapi.com/search", params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            results = []
            if "organic_results" in data:
                for item in data["organic_results"][:num_results]:
                    result = {
                        "title": item.get("title", ""),
                        "snippet": item.get("snippet", ""),
                        "link": item.get("link", ""),
                        "source": "serpapi"
                    }
                    results.append(result)
            
            logger.info(f"✅ Найдено {len(results)} результатов через SerpAPI")
            return results
            
        except Exception as e:
            logger.error(f"❌ Ошибка поиска через SerpAPI: {e}")
            return None
    
    def search_google(self, query: str, num_results: int = 5) -> Optional[List[Dict[str, str]]]:
        """Поиск через Google Custom Search API."""
        if not self.google_api_key or not self.google_cse_id:
            logger.warning("⚠️ GOOGLE_API_KEY или GOOGLE_CSE_ID не установлены")
            return None
        
        try:
            params = {
                "q": query,
                "key": self.google_api_key,
                "cx": self.google_cse_id,
                "num": num_results,
                "lr": "lang_ru",  # Язык: русский
                "gl": "ru"        # Страна: Россия
            }
            
            response = requests.get("https://www.googleapis.com/customsearch/v1", params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            results = []
            if "items" in data:
                for item in data["items"][:num_results]:
                    result = {
                        "title": item.get("title", ""),
                        "snippet": item.get("snippet", ""),
                        "link": item.get("link", ""),
                        "source": "google"
                    }
                    results.append(result)
            
            logger.info(f"✅ Найдено {len(results)} результатов через Google")
            return results
            
        except Exception as e:
            logger.error(f"❌ Ошибка поиска через Google: {e}")
            return None
    
    def search_duckduckgo(self, query: str, num_results: int = 5) -> Optional[List[Dict[str, str]]]:
        """Поиск через DuckDuckGo HTML (альтернативный метод)."""
        try:
            # Используем HTML версию DuckDuckGo с User-Agent
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1"
            }
            
            params = {
                "q": query,
                "kl": "ru-ru",
                "kz": "-1"
            }
            
            response = requests.get("https://duckduckgo.com/html/", params=params, headers=headers, timeout=30)
            
            if response.status_code != 200:
                logger.warning(f"⚠️ DuckDuckGo HTML вернул статус {response.status_code}")
                return None
            
            # Парсим HTML
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.text, 'html.parser')
            
            results = []
            
            # Ищем результаты поиска
            for result in soup.find_all('div', class_='result', limit=num_results):
                try:
                    # Заголовок
                    title_elem = result.find('a', class_='result__title')
                    title = title_elem.get_text(strip=True) if title_elem else ""
                    
                    # Ссылка
                    link = title_elem.get('href', '') if title_elem else ""
                    
                    # Описание
                    snippet_elem = result.find('a', class_='result__snippet')
                    if not snippet_elem:
                        snippet_elem = result.find('div', class_='result__snippet')
                    
                    snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""
                    
                    if title and link:
                        results.append({
                            "title": title[:100],
                            "snippet": snippet[:200] if snippet else "Нет описания",
                            "link": link,
                            "source": "duckduckgo_html"
                        })
                except Exception as e:
                    logger.debug(f"Ошибка парсинга результата: {e}")
                    continue
            
            # Альтернативный поиск по структуре
            if not results:
                for link in soup.find_all('a', class_='result__url', limit=num_results):
                    title = link.get_text(strip=True)
                    href = link.get('href', '')
                    
                    # Ищем следующий элемент с описанием
                    next_elem = link.find_next(['a', 'div'], class_='result__snippet')
                    snippet = next_elem.get_text(strip=True) if next_elem else ""
                    
                    results.append({
                        "title": title[:100],
                        "snippet": snippet[:200] if snippet else "Нет описания",
                        "link": href,
                        "source": "duckduckgo_html"
                    })
            
            logger.info(f"✅ Найдено {len(results)} результатов через DuckDuckGo HTML")
            return results if results else None
            
        except Exception as e:
            logger.error(f"❌ Ошибка поиска через DuckDuckGo HTML: {e}")
            return None
    
    def search(self, query: str, num_results: int = 5) -> List[Dict[str, str]]:
        """
        Умный поиск: пытается использовать доступные API в порядке приоритета.
        
        Args:
            query: Поисковый запрос
            num_results: Количество результатов
            
        Returns:
            Список результатов поиска
        """
        # Пробуем разные источники в порядке приоритета
        sources = [
            ("serpapi", self.search_serpapi),
            ("google", self.search_google),
            ("duckduckgo", self.search_duckduckgo)
        ]
        
        for source_name, search_func in sources:
            try:
                results = search_func(query, num_results)
                if results:
                    logger.info(f"✅ Использован {source_name} для поиска: '{query}'")
                    return results
            except Exception as e:
                logger.warning(f"⚠️ {source_name} недоступен: {e}")
                continue
        
        logger.warning(f"⚠️ Все источники поиска недоступны для запроса: '{query}'")
        return []
    
    def format_results(self, results: List[Dict[str, str]]) -> str:
        """Форматирует результаты поиска в читаемый текст."""
        if not results:
            return "Результаты поиска не найдены."
        
        formatted = "Результаты поиска:\n\n"
        for i, result in enumerate(results, 1):
            formatted += f"{i}. **{result['title']}**\n"
            formatted += f"   {result['snippet']}\n"
            formatted += f"   Источник: {result['source']}\n"
            formatted += f"   Ссылка: {result['link']}\n\n"
        
        return formatted
    
    def search_and_format(self, query: str, num_results: int = 3) -> str:
        """Выполняет поиск и возвращает отформатированные результаты."""
        results = self.search(query, num_results)
        return self.format_results(results)


# Глобальный экземпляр для поиска
web_search = WebSearch()


def is_web_search_available() -> bool:
    """Проверяет, доступен ли веб-поиск."""
    # DuckDuckGo всегда доступен (бесплатно, без API ключей)
    # Также проверяем наличие API ключей для других сервисов
    return True  # DuckDuckGo всегда доступен


def get_web_search_context(query: str) -> str:
    """
    Получает контекст из интернета для запроса.
    
    Args:
        query: Поисковый запрос
        
    Returns:
        Контекстная информация из интернета
    """
    if not is_web_search_available():
        return "Веб-поиск недоступен. Добавьте API ключи в .env файл."
    
    try:
        # Для налоговых и законодательных вопросов добавляем год
        if any(word in query.lower() for word in ["ндс", "налог", "закон", "ставка", "2026"]):
            query_with_year = f"{query} 2026 год актуальные данные"
            results = web_search.search(query_with_year, num_results=3)
        else:
            results = web_search.search(query, num_results=3)
        
        if results:
            context = "Актуальная информация из интернета:\n\n"
            for result in results:
                context += f"• {result['title']}: {result['snippet']}\n"
            return context
        else:
            return "Не удалось найти актуальную информацию в интернете."
            
    except Exception as e:
        logger.error(f"❌ Ошибка при получении контекста из интернета: {e}")
        return f"Ошибка при поиске в интернете: {str(e)}"