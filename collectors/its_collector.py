"""
Коллектор данных с портала ИТС 1С (its.1c.ru).
Строит карту сайта, парсит статьи и индексирует в Qdrant.
"""

import json
import logging
import os
import time
import re
from datetime import datetime
from typing import Dict, Any, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("ZORA.Collector.ITS")

# Конфигурация
ITS_BASE_URL = "https://its.1c.ru"
SITEMAP_FILE = os.path.join("data", "its_sitemap.json")
STATE_FILE = os.path.join("data", "its_state.json")

# Учётные данные из .env
ITS_USERNAME = os.getenv("ITS_USERNAME", "")
ITS_PASSWORD = os.getenv("ITS_PASSWORD", "")

# Задержка между запросами (уважаем сервер)
REQUEST_DELAY = 1.5

# Разделы по умолчанию для парсинга
DEFAULT_SECTIONS = [
    "Комплексная автоматизация",
    "Бухгалтерия предприятия",
    "Зарплата и управление персоналом",
    "Управление торговлей",
    "Новости",
    "Календарь бухгалтера",
]


def _load_json(filepath: str, default=None) -> Any:
    """Загружает JSON из файла."""
    if default is None:
        default = {}
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Ошибка загрузки {filepath}: {e}")
    return default


def _save_json(filepath: str, data: Any):
    """Сохраняет данные в JSON файл."""
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _get_session() -> requests.Session:
    """Создаёт сессию с заголовками."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    })
    return session


def _fetch_page(url: str, session: requests.Session) -> Optional[str]:
    """Загружает страницу с задержкой."""
    time.sleep(REQUEST_DELAY)
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        logger.warning(f"Ошибка загрузки {url}: {e}")
        return None


def build_sitemap() -> Dict[str, Any]:
    """
    Строит карту сайта ИТС 1С: обходит разделы и собирает ссылки на статьи.

    Returns:
        Статистика: количество разделов и статей.
    """
    logger.info("Построение карты сайта ИТС 1С...")
    session = _get_session()

    # Пробуем авторизоваться
    if ITS_USERNAME and ITS_PASSWORD:
        login_url = urljoin(ITS_BASE_URL, "/login")
        try:
            resp = session.post(login_url, data={
                "username": ITS_USERNAME,
                "password": ITS_PASSWORD,
            }, timeout=30)
            if resp.ok:
                logger.info("Авторизация на ИТС 1С выполнена")
            else:
                logger.warning(f"Авторизация не удалась: {resp.status_code}")
        except Exception as e:
            logger.warning(f"Ошибка авторизации: {e}")

    # Загружаем главную страницу документации
    docs_url = urljoin(ITS_BASE_URL, "/docs")
    html = _fetch_page(docs_url, session)
    if not html:
        logger.error("Не удалось загрузить страницу документации")
        return {"success": False, "error": "Не удалось загрузить its.1c.ru"}

    soup = BeautifulSoup(html, "html.parser")

    # Ищем разделы в навигации
    sections = {}
    for link in soup.find_all("a", href=True):
        href = link["href"]
        text = link.get_text(strip=True)
        if "/docs/" in href and text and len(text) > 3:
            full_url = urljoin(ITS_BASE_URL, href)
            if text not in sections:
                sections[text] = {
                    "title": text,
                    "url": full_url,
                    "articles": []
                }

    # Если разделы не найдены через навигацию, добавляем стандартные
    if not sections:
        logger.warning("Разделы не найдены через навигацию, использую стандартные")
        for section_name in DEFAULT_SECTIONS:
            section_slug = section_name.lower().replace(" ", "-")
            sections[section_name] = {
                "title": section_name,
                "url": urljoin(ITS_BASE_URL, f"/docs/{section_slug}"),
                "articles": []
            }

    # Для каждого раздела собираем статьи
    total_articles = 0
    for section_name, section_data in sections.items():
        logger.info(f"  Раздел: {section_name}")
        section_html = _fetch_page(section_data["url"], session)
        if not section_html:
            continue

        section_soup = BeautifulSoup(section_html, "html.parser")
        article_links = section_soup.find_all("a", href=True)

        for link in article_links:
            href = link["href"]
            title = link.get_text(strip=True)
            if "/docs/" in href and title and len(title) > 5:
                # Проверяем, что это не навигационная ссылка
                if not any(skip in href for skip in ["/login", "/register", "#"]):
                    article_url = urljoin(ITS_BASE_URL, href)
                    section_data["articles"].append({
                        "title": title,
                        "url": article_url
                    })
                    total_articles += 1

        # Ограничиваем количество статей для карты
        if len(section_data["articles"]) > 50:
            section_data["articles"] = section_data["articles"][:50]

    sitemap = {
        "built_at": datetime.now().isoformat(),
        "total_sections": len(sections),
        "total_articles": total_articles,
        "sections": {k: v for k, v in sections.items()}
    }

    _save_json(SITEMAP_FILE, sitemap)
    logger.info(f"✅ Карта сайта построена: {len(sections)} разделов, {total_articles} статей")
    return {
        "success": True,
        "sections": len(sections),
        "articles": total_articles,
        "sitemap_file": SITEMAP_FILE
    }


def _extract_article_text(html: str) -> str:
    """Извлекает основной текст статьи из HTML."""
    soup = BeautifulSoup(html, "html.parser")

    # Удаляем скрипты, стили, навигацию
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

    # Пробуем найти контент в разных возможных контейнерах
    content = None
    for selector in [".article-content", "main", ".content", "#content",
                     ".document-content", ".text", "article"]:
        content = soup.select_one(selector)
        if content:
            break

    if not content:
        content = soup.body

    if content:
        text = content.get_text(separator="\n", strip=True)
        # Очищаем от лишних пробелов
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text
    return ""


def _chunk_text(text: str, chunk_size: int = 1500, overlap: int = 200) -> List[str]:
    """Разбивает текст на перекрывающиеся чанки."""
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end >= len(text):
            chunks.append(text[start:])
            break
        # Ищем границу предложения или абзаца
        cut = text.rfind(". ", start + chunk_size - overlap, end)
        if cut == -1:
            cut = text.rfind("\n\n", start + chunk_size - overlap, end)
        if cut == -1:
            cut = end
        else:
            cut += 1  # включаем точку
        chunks.append(text[start:cut])
        start = cut
    return chunks


def run(sections: Optional[List[str]] = None, limit: Optional[int] = None) -> Dict[str, Any]:
    """
    Парсит статьи ИТС 1С и индексирует в Qdrant.

    Args:
        sections: Список разделов для парсинга. Если None — все из карты.
        limit: Максимальное количество статей для парсинга.

    Returns:
        Результат операции.
    """
    logger.info(f"Запуск парсинга ИТС: sections={sections}, limit={limit}")

    # Загружаем или строим карту
    sitemap = _load_json(SITEMAP_FILE)
    if not sitemap or "sections" not in sitemap:
        logger.info("Карта сайта не найдена, строим...")
        sitemap_result = build_sitemap()
        if not sitemap_result.get("success"):
            return {"success": False, "error": "Не удалось построить карту сайта"}
        sitemap = _load_json(SITEMAP_FILE)

    # Загружаем состояние (уже обработанные URL)
    state = _load_json(STATE_FILE, {"processed_urls": []})
    processed_urls = set(state.get("processed_urls", []))

    session = _get_session()
    all_articles = []
    errors = []
    total_indexed = 0

    # Собираем статьи из указанных разделов
    for section_name, section_data in sitemap.get("sections", {}).items():
        if sections and section_name not in sections:
            continue
        for article in section_data.get("articles", []):
            all_articles.append({
                **article,
                "section": section_name
            })

    if limit:
        all_articles = all_articles[:limit]

    logger.info(f"Всего статей для обработки: {len(all_articles)}")

    for article in all_articles:
        url = article["url"]
        if url in processed_urls:
            logger.debug(f"  Пропуск (уже обработано): {article['title']}")
            continue

        logger.info(f"  Парсинг: {article['title']}")
        html = _fetch_page(url, session)
        if not html:
            errors.append(f"Не удалось загрузить {url}")
            continue

        text = _extract_article_text(html)
        if not text:
            errors.append(f"Пустой текст: {url}")
            continue

        # Разбиваем на чанки и индексируем
        chunks = _chunk_text(text)
        try:
            from memory.qdrant_memory import memory as _memory
        except ImportError:
            logger.warning("Qdrant память недоступна")
            break

        for i, chunk in enumerate(chunks):
            try:
                _memory.store(
                    text=chunk,
                    metadata={
                        "source": "its",
                        "type": "documentation",
                        "section": article.get("section", ""),
                        "title": article["title"],
                        "url": url,
                        "chunk_index": i,
                        "timestamp": datetime.now().isoformat(),
                        "raw_html": html[:5000]  # сохраняем первые 5000 символов HTML для контекста
                    }
                )
                total_indexed += 1
            except Exception as e:
                logger.warning(f"Ошибка индексации чанка {i}: {e}")

        # Отмечаем URL как обработанный
        processed_urls.add(url)

    # Сохраняем состояние
    state["processed_urls"] = list(processed_urls)
    state["last_run"] = datetime.now().isoformat()
    state["last_articles_processed"] = len(all_articles)
    state["last_indexed"] = total_indexed
    _save_json(STATE_FILE, state)

    result = {
        "success": len(errors) == 0 or len(all_articles) > 0,
        "articles_found": len(all_articles),
        "articles_processed": len(all_articles),
        "chunks_indexed": total_indexed,
        "errors": errors[:10],  # Ограничиваем вывод ошибок
        "total_errors": len(errors)
    }

    logger.info(f"✅ Парсинг ИТС завершён: {result}")
    return result


def get_status() -> Dict[str, Any]:
    """Возвращает статус коллектора."""
    state = _load_json(STATE_FILE, {})
    sitemap = _load_json(SITEMAP_FILE, {})
    return {
        "collector": "ITS",
        "last_run": state.get("last_run"),
        "articles_processed": state.get("last_articles_processed", 0),
        "chunks_indexed": state.get("last_indexed", 0),
        "sitemap_sections": sitemap.get("total_sections", 0),
        "sitemap_articles": sitemap.get("total_articles", 0),
        "processed_urls": len(state.get("processed_urls", []))
    }
