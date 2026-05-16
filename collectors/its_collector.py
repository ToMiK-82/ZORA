"""
Коллектор данных с портала ИТС 1С (its.1c.ru).
Строит карту сайта, парсит статьи, PDF, изображения, видео и индексирует в Qdrant.

Особенности:
  - Автоматическое получение всех URL через sitemap.xml или обход навигации.
  - Извлечение текста из PDF (pypdf).
  - Сохранение метаданных изображений (alt/title).
  - Сохранение описаний видео.
  - Унифицированный payload: source, type, entity_id, parent_doc_id, doc_title, date, chunk_index.
"""

import json
import logging
import os
import time
import re
from datetime import datetime
from typing import Dict, Any, List, Optional
from urllib.parse import urljoin, urlparse

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from connectors.tokenizer_utils import chunk_by_tokens

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("ZORA.Collector.ITS")

# ----- Конфигурация -----
ITS_BASE_URL = "https://its.1c.ru"
SITEMAP_FILE = os.path.join("data", "its_sitemap.json")
STATE_FILE = os.path.join("data", "its_state.json")
TEMP_DIR = os.path.join("data", "its_temp")           # для временных файлов PDF

ITS_USERNAME = os.getenv("ITS_USERNAME", "")
ITS_PASSWORD = os.getenv("ITS_PASSWORD", "")
REQUEST_DELAY = 1.5

# ===== БЕЛЫЙ СПИСОК РАЗДЕЛОВ ИТС =====
# Индексируются только URL, содержащие один из этих паттернов.
ALLOWED_URL_PATTERNS = [
    "/its/ka/",
    "/its/buh/",
    "/its/prog/",
    "/its/calendar/",
]


def _is_url_allowed(url: str) -> bool:
    """Проверяет, соответствует ли URL белому списку разделов ИТС."""
    url_lower = url.lower()
    for pattern in ALLOWED_URL_PATTERNS:
        if pattern in url_lower:
            return True
    return False


# ----- Вспомогательные функции -----
def _load_json(filepath: str, default=None) -> Any:
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
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _get_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    })
    return session


def _fetch_page(url: str, session: requests.Session, stream: bool = False) -> Optional[requests.Response]:
    """Загружает страницу с задержкой. Возвращает response, если статус 200, иначе None."""
    time.sleep(REQUEST_DELAY)
    try:
        resp = session.get(url, timeout=30, stream=stream)
        if resp.status_code == 200:
            return resp
    except requests.RequestException as e:
        logger.warning(f"Ошибка загрузки {url}: {e}")
    return None


# ----- Получение полного списка URL -----
def _get_all_urls_from_sitemap() -> List[str]:
    """Пытается загрузить sitemap.xml и извлечь все URL."""
    sitemap_url = urljoin(ITS_BASE_URL, "/sitemap.xml")
    logger.info(f"Проверяю наличие sitemap: {sitemap_url}")
    try:
        resp = requests.get(sitemap_url, timeout=10)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "xml")
            urls = [loc.get_text(strip=True) for loc in soup.find_all("loc")]
            logger.info(f"Из sitemap получено {len(urls)} URL")
            return urls
    except Exception as e:
        logger.warning(f"Ошибка загрузки sitemap: {e}")
    return []


def _crawl_navigation(start_urls: List[str], session: requests.Session) -> List[str]:
    """
    Рекурсивно обходит навигацию, собирает все ссылки, начинающиеся с /docs/ или /documentation/.
    """
    visited = set()
    to_visit = set(start_urls)
    all_links = set()

    while to_visit:
        url = to_visit.pop()
        if url in visited:
            continue
        visited.add(url)
        resp = _fetch_page(url, session)
        if not resp:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        for link in soup.find_all("a", href=True):
            href = link["href"].strip()
            if not href or href.startswith("#") or href.startswith("javascript:"):
                continue
            full = urljoin(url, href)
            parsed = urlparse(full)
            if parsed.netloc != urlparse(ITS_BASE_URL).netloc:
                continue  # внешние ссылки
            if any(prefix in full for prefix in ["/login", "/register"]):
                continue
            if "/docs/" in full or "/documentation/" in full:
                all_links.add(full)
                if full not in visited:
                    to_visit.add(full)
    return list(all_links)


def build_sitemap() -> Dict[str, Any]:
    """Строит полную карту сайта ИТС: sitemap.xml или обход навигации."""
    logger.info("Построение карты сайта ИТС 1С...")
    session = _get_session()

    # Пробуем авторизоваться
    if ITS_USERNAME and ITS_PASSWORD:
        login_url = urljoin(ITS_BASE_URL, "/login")
        try:
            resp = session.post(login_url, data={"username": ITS_USERNAME, "password": ITS_PASSWORD}, timeout=30)
            if resp.ok:
                logger.info("Авторизация на ИТС выполнена")
            else:
                logger.warning(f"Авторизация не удалась: {resp.status_code}")
        except Exception as e:
            logger.warning(f"Ошибка авторизации: {e}")

    # 1. Попытка через sitemap
    urls = _get_all_urls_from_sitemap()
    if urls:
        sitemap = {
            "built_at": datetime.now().isoformat(),
            "total_articles": len(urls),
            "articles": [{"url": u, "title": u.split("/")[-1] or u} for u in urls]
        }
        _save_json(SITEMAP_FILE, sitemap)
        logger.info(f"✅ Карта построена из sitemap: {len(urls)} статей")
        return {"success": True, "articles": len(urls)}

    # 2. Обход навигации
    logger.info("Sitemap не найден, начинаю обход навигации...")
    start_urls = [urljoin(ITS_BASE_URL, "/docs"), urljoin(ITS_BASE_URL, "/documentation")]
    all_links = _crawl_navigation(start_urls, session)
    if not all_links:
        logger.error("Не удалось собрать ни одной ссылки")
        return {"success": False, "error": "Не удалось собрать URL"}

    sitemap = {
        "built_at": datetime.now().isoformat(),
        "total_articles": len(all_links),
        "articles": [{"url": u, "title": u.split("/")[-1] or u} for u in all_links]
    }
    _save_json(SITEMAP_FILE, sitemap)
    logger.info(f"✅ Карта построена через обход: {len(all_links)} статей")
    return {"success": True, "articles": len(all_links)}


# ----- Извлечение контента -----
def _extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

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
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text
    return ""


def _extract_pdf_links(html: str, base_url: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith(".pdf"):
            links.append(urljoin(base_url, href))
    return links


def _extract_image_metadata(html: str, base_url: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    images = []
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if not src:
            continue
        full_src = urljoin(base_url, src)
        alt = img.get("alt", "").strip()
        title = img.get("title", "").strip()
        text = alt or title or os.path.basename(src)
        if text:
            images.append({"url": full_src, "alt": alt, "title": title, "text": text})
    return images


def _extract_video_info(html: str, base_url: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    videos = []
    # Простой поиск iframe/ссылок с YouTube, rutube и т.п.
    for iframe in soup.find_all("iframe", src=True):
        src = urljoin(base_url, iframe["src"])
        if any(d in src for d in ["youtube.com", "rutube.ru", "vimeo.com"]):
            title_tag = soup.find("h1") or soup.find("h2")
            title = title_tag.get_text(strip=True) if title_tag else "Видео"
            videos.append({"url": src, "title": title, "type": "video"})
    return videos


def _extract_pdf_text(pdf_url: str, session: requests.Session) -> Optional[str]:
    """Скачивает PDF и возвращает извлечённый текст (первые 2000 символов)."""
    try:
        import pypdf
        resp = _fetch_page(pdf_url, session, stream=True)
        if not resp:
            return None
        os.makedirs(TEMP_DIR, exist_ok=True)
        local_path = os.path.join(TEMP_DIR, os.path.basename(urlparse(pdf_url).path))
        with open(local_path, "wb") as f:
            f.write(resp.content)
        with open(local_path, "rb") as f:
            reader = pypdf.PdfReader(f)
            text = "\n".join(page.extract_text() for page in reader.pages if page.extract_text())
        os.remove(local_path)
        return text[:2000] if text else None
    except ImportError:
        logger.warning("Библиотека pypdf не установлена. PDF пропущены.")
        return None
    except Exception as e:
        logger.error(f"Ошибка извлечения текста из PDF {pdf_url}: {e}")
        return None


# ----- Основной метод -----
def run(limit: Optional[int] = None) -> Dict[str, Any]:
    """Парсит все материалы ИТС и индексирует в Qdrant."""
    logger.info("Запуск полного парсинга ИТС...")

    # 1. Загружаем или строим карту
    sitemap = _load_json(SITEMAP_FILE)
    if not sitemap or "articles" not in sitemap:
        build_result = build_sitemap()
        if not build_result.get("success"):
            return {"success": False, "error": build_result.get("error", "Не удалось построить карту")}
        sitemap = _load_json(SITEMAP_FILE)

    state = _load_json(STATE_FILE, {"processed_urls": []})
    processed_urls = set(state.get("processed_urls", []))

    all_articles = sitemap.get("articles", [])
    if limit:
        all_articles = all_articles[:limit]

    logger.info(f"Всего статей: {len(all_articles)}")
    session = _get_session()
    errors = []
    total_indexed = 0

    try:
        from memory.qdrant_memory import memory as _memory
    except ImportError:
        logger.warning("Qdrant память недоступна")
        return {"success": False, "error": "Qdrant память недоступна"}

    for article in all_articles:
        url = article["url"]
        if url in processed_urls:
            logger.debug(f"  Пропуск: {url}")
            continue

        # Фильтрация по белому списку разделов ИТС
        if not _is_url_allowed(url):
            logger.debug(f"  Пропуск (не в белом списке): {url}")
            processed_urls.add(url)
            continue

        logger.info(f"  Обработка: {url}")
        resp = _fetch_page(url, session)
        if not resp:
            errors.append(f"Не удалось загрузить {url}")
            continue

        html = resp.text

        # --- Текстовый контент ---
        text = _extract_text(html)
        if text:
            chunks = chunk_by_tokens(text)
            for i, chunk in enumerate(chunks):
                metadata = {
                    "source": "its",
                    "type": "documentation",
                    "entity_id": url,
                    "parent_doc_id": url,
                    "doc_title": article.get("title", url.split("/")[-1]),
                    "date": datetime.now().isoformat(),
                    "chunk_index": i,
                    "url": url,
                }
                _memory.store(text=chunk, metadata=metadata)
                total_indexed += 1

        # --- PDF-ссылки ---
        pdf_links = _extract_pdf_links(html, url)
        for pdf_url in pdf_links:
            if pdf_url in processed_urls:
                continue
            logger.info(f"    Индексирую PDF: {pdf_url}")
            pdf_text = _extract_pdf_text(pdf_url, session)
            if pdf_text:
                chunks = chunk_by_tokens(pdf_text)
                for j, chunk in enumerate(chunks):
                    metadata = {
                        "source": "its",
                        "type": "pdf",
                        "entity_id": pdf_url,
                        "parent_doc_id": url,
                        "doc_title": article.get("title", "PDF документ"),
                        "date": datetime.now().isoformat(),
                        "chunk_index": j,
                        "url": pdf_url,
                    }
                    _memory.store(text=chunk, metadata=metadata)
                    total_indexed += 1
            processed_urls.add(pdf_url)

        # --- Изображения ---
        images = _extract_image_metadata(html, url)
        for img in images:
            img_id = img["url"]
            if img_id in processed_urls:
                continue
            metadata = {
                "source": "its",
                "type": "image",
                "entity_id": img_id,
                "parent_doc_id": url,
                "doc_title": img["text"],
                "date": datetime.now().isoformat(),
                "chunk_index": 0,
                "url": img["url"],
                "alt": img.get("alt"),
                "title": img.get("title"),
            }
            _memory.store(text=img["text"], metadata=metadata)
            total_indexed += 1
            processed_urls.add(img_id)

        # --- Видео ---
        videos = _extract_video_info(html, url)
        for vid in videos:
            vid_id = vid["url"]
            if vid_id in processed_urls:
                continue
            metadata = {
                "source": "its",
                "type": "video",
                "entity_id": vid_id,
                "parent_doc_id": url,
                "doc_title": vid["title"],
                "date": datetime.now().isoformat(),
                "chunk_index": 0,
                "url": vid["url"],
            }
            _memory.store(text=vid["title"], metadata=metadata)
            total_indexed += 1
            processed_urls.add(vid_id)

        processed_urls.add(url)

    # Сохраняем состояние
    state["processed_urls"] = list(processed_urls)
    state["last_run"] = datetime.now().isoformat()
    state["last_indexed"] = total_indexed
    _save_json(STATE_FILE, state)

    result = {
        "success": len(errors) == 0 or total_indexed > 0,
        "articles_processed": len(all_articles),
        "chunks_indexed": total_indexed,
        "errors": errors[:10],
        "total_errors": len(errors)
    }
    logger.info(f"✅ Парсинг ИТС завершён: {result}")
    return result


def get_status() -> Dict[str, Any]:
    state = _load_json(STATE_FILE, {})
    sitemap = _load_json(SITEMAP_FILE, {})
    return {
        "collector": "ITS",
        "last_run": state.get("last_run"),
        "articles_processed": len(state.get("processed_urls", [])),
        "chunks_indexed": state.get("last_indexed", 0),
        "sitemap_articles": sitemap.get("total_articles", 0)
    }