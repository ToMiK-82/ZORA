"""
Коллектор данных с сайта ukorona.ru.
Парсит товары, новости, акции и индексирует в Qdrant с унифицированным payload.

Особенности:
  - Автоматическое получение всех URL через sitemap.xml или обход навигации.
  - Извлечение текста из PDF (pypdf).
  - Сохранение метаданных изображений (alt/title).
  - Сохранение описаний видео.
  - Динамическое извлечение структурированных данных (характеристик) с любых страниц.
  - Фильтрация пустых/нулевых значений в метаданных.
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

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("ZORA.Collector.Ukorona")

# ----- Конфигурация -----
UKORONA_URL = os.getenv("UKORONA_URL", "https://ukorona.ru")
SITEMAP_FILE = os.path.join("data", "ukorona_sitemap.json")
STATE_FILE = os.path.join("data", "ukorona_state.json")
TEMP_DIR = os.path.join("data", "ukorona_temp")

REQUEST_DELAY = 1.0


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
    time.sleep(REQUEST_DELAY)
    try:
        resp = session.get(url, timeout=30, stream=stream)
        if resp.status_code == 200:
            return resp
    except requests.RequestException as e:
        logger.warning(f"Ошибка загрузки {url}: {e}")
    return None


def _chunk_text(text: str, chunk_size: int = 1500, overlap: int = 200) -> List[str]:
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end >= len(text):
            chunks.append(text[start:])
            break
        cut = text.rfind(". ", start + chunk_size - overlap, end)
        if cut == -1:
            cut = text.rfind("\n\n", start + chunk_size - overlap, end)
        if cut == -1:
            cut = end
        else:
            cut += 1
        chunks.append(text[start:cut])
        start = cut
    return chunks


def _classify_url(url: str) -> str:
    """Определяет тип контента по URL (product/news/promotion/unknown)."""
    url_lower = url.lower()
    if "/product/" in url_lower or "/catalog/" in url_lower:
        return "product"
    if "/news/" in url_lower:
        return "news"
    if "/actions/" in url_lower or "/promotions/" in url_lower:
        return "promotion"
    return "page"


# ----- Получение полного списка URL -----
def _get_all_urls_from_sitemap() -> List[str]:
    """Пытается загрузить sitemap.xml и извлечь все URL."""
    sitemap_url = urljoin(UKORONA_URL, "/sitemap.xml")
    logger.info(f"Проверяю sitemap: {sitemap_url}")
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
    Рекурсивно обходит навигацию, собирает все внутренние ссылки.
    Останавливается, когда не остаётся новых URL.
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
            if parsed.netloc != urlparse(UKORONA_URL).netloc:
                continue  # только внутренние ссылки
            if any(skip in full for skip in ["/login", "/register"]):
                continue
            all_links.add(full)
            if full not in visited:
                to_visit.add(full)
    return list(all_links)


def build_sitemap() -> Dict[str, Any]:
    """Строит полную карту сайта ukorona.ru."""
    logger.info("Построение карты сайта ukorona.ru...")
    session = _get_session()

    # 1. Попытка через sitemap
    urls = _get_all_urls_from_sitemap()
    if not urls:
        # 2. Обход навигации с главной
        logger.info("Sitemap не найден, начинаю обход с главной...")
        urls = _crawl_navigation([UKORONA_URL], session)

    if not urls:
        logger.error("Не удалось собрать ни одной ссылки")
        return {"success": False, "error": "Не удалось собрать URL"}

    sitemap = {
        "built_at": datetime.now().isoformat(),
        "total_articles": len(urls),
        "articles": [{"url": u, "title": u.split("/")[-1] or u} for u in urls]
    }
    _save_json(SITEMAP_FILE, sitemap)
    logger.info(f"✅ Карта построена: {len(urls)} страниц")
    return {"success": True, "articles": len(urls)}


# ----- Извлечение контента -----
def _extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

    content = None
    for selector in [".content", "main", "article", ".text", ".description",
                     ".product-content", ".news-content", ".action-content"]:
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


def _extract_structured_data(html: str) -> Dict[str, Any]:
    """
    Извлекает все структурированные пары ключ-значение со страницы.
    Приоритет: микроразметка Schema.org (JSON-LD), затем видимый текст.
    Возвращает только непустые значения.
    """
    soup = BeautifulSoup(html, "html.parser")
    data = {}

    # 1. Микроразметка (JSON-LD)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            ld = json.loads(script.string)
            if not isinstance(ld, dict):
                continue
            # Обработка типа Product (может быть вложенный @type)
            if ld.get("@type") == "Product" or "name" in ld:
                if "name" in ld:
                    data["name"] = ld["name"]
                if "offers" in ld:
                    offer = ld["offers"]
                    if isinstance(offer, dict):
                        if "price" in offer:
                            try:
                                data["price"] = float(offer["price"])
                            except (ValueError, TypeError):
                                pass
                        if "availability" in offer:
                            data["in_stock"] = "InStock" in str(offer.get("availability", ""))
                if "sku" in ld:
                    data["article"] = str(ld["sku"])
                if "description" in ld:
                    data["description_microdata"] = ld["description"]
                if "brand" in ld:
                    if isinstance(ld["brand"], dict):
                        data["brand"] = ld["brand"].get("name", str(ld["brand"]))
                    else:
                        data["brand"] = str(ld["brand"])
                # Добавляем любые другие свойства Product, если есть
                for key in ("weight", "height", "width", "depth", "gtin13", "mpn"):
                    if key in ld:
                        data[key] = ld[key]
        except Exception:
            pass

    # 2. Видимые характеристики (ключ: значение)
    # Ищем элементы, содержащие ':'
    pair_pattern = re.compile(r'^\s*(.+?)\s*[:—]\s*(.+?)\s*$')
    for tag in soup.find_all(text=True):
        parent = tag.parent
        if parent.name in ['script', 'style', 'noscript']:
            continue
        text = tag.strip()
        if not text or len(text) > 200:
            continue
        match = pair_pattern.match(text)
        if match:
            key = match.group(1).strip()
            value = match.group(2).strip()
            # Отбрасываем слишком короткие или длинные ключи, служебные строки
            if len(key) < 2 or len(value) == 0:
                continue
            if key in data:
                continue  # приоритет у микроразметки
            data[key] = value

    # Фильтруем пустые/нулевые значения
    clean_data = {}
    for k, v in data.items():
        if v is None or v == "":
            continue
        if isinstance(v, str) and v.strip() == "":
            continue
        if isinstance(v, float) and v == 0.0:
            continue
        if isinstance(v, bool) and not v:  # False убираем, True оставляем
            continue
        clean_data[k] = v

    return clean_data


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
    for iframe in soup.find_all("iframe", src=True):
        src = urljoin(base_url, iframe["src"])
        if any(d in src for d in ["youtube.com", "rutube.ru", "vimeo.com"]):
            title_tag = soup.find("h1") or soup.find("h2")
            title = title_tag.get_text(strip=True) if title_tag else "Видео"
            videos.append({"url": src, "title": title, "type": "video"})
    return videos


def _extract_pdf_text(pdf_url: str, session: requests.Session) -> Optional[str]:
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
        logger.warning("pypdf не установлена. PDF пропущены.")
        return None
    except Exception as e:
        logger.error(f"Ошибка извлечения текста из PDF {pdf_url}: {e}")
        return None


# ----- Основной метод -----
def run(limit: Optional[int] = None) -> Dict[str, Any]:
    """Парсит все страницы ukorona.ru и индексирует в Qdrant."""
    logger.info("Запуск полного парсинга ukorona.ru...")

    # 1. Загружаем или строим карту
    sitemap = _load_json(SITEMAP_FILE)
    if not sitemap or "articles" not in sitemap:
        build_result = build_sitemap()
        if not build_result.get("success"):
            return {"success": False, "error": build_result.get("error", "Не удалось построить карту")}
        sitemap = _load_json(SITEMAP_FILE)

    state = _load_json(STATE_FILE, {"processed_urls": []})
    processed_urls = set(state.get("processed_urls", []))

    all_pages = sitemap.get("articles", [])
    if limit:
        all_pages = all_pages[:limit]

    logger.info(f"Всего страниц: {len(all_pages)}")
    session = _get_session()
    errors = []
    total_indexed = 0

    try:
        from memory.qdrant_memory import memory as _memory
    except ImportError:
        logger.warning("Qdrant память недоступна")
        return {"success": False, "error": "Qdrant память недоступна"}

    for page in all_pages:
        url = page["url"]
        if url in processed_urls:
            logger.debug(f"  Пропуск: {url}")
            continue

        logger.info(f"  Обработка: {url}")
        resp = _fetch_page(url, session)
        if not resp:
            errors.append(f"Не удалось загрузить {url}")
            continue

        html = resp.text
        page_type = _classify_url(url)

        # Базовый заголовок
        doc_title = page.get("title", url.split("/")[-1] or url)
        parent_doc_id = url
        date = datetime.now().isoformat()

        # Извлекаем структурированные данные (для товаров и любых других страниц)
        structured = _extract_structured_data(html)
        if "name" in structured:
            doc_title = structured["name"]

        # --- Текстовый контент ---
        text = _extract_text(html)
        if text:
            chunks = _chunk_text(text)
            for i, chunk in enumerate(chunks):
                metadata = {
                    "source": "ukorona",
                    "type": page_type,
                    "entity_id": url,
                    "parent_doc_id": parent_doc_id,
                    "doc_title": doc_title,
                    "date": date,
                    "chunk_index": i,
                    "url": url,
                }
                # Добавляем структурированные данные (только непустые)
                if structured:
                    metadata.update(structured)
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
                chunks = _chunk_text(pdf_text)
                for j, chunk in enumerate(chunks):
                    metadata = {
                        "source": "ukorona",
                        "type": "pdf",
                        "entity_id": pdf_url,
                        "parent_doc_id": url,
                        "doc_title": doc_title,
                        "date": date,
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
                "source": "ukorona",
                "type": "image",
                "entity_id": img_id,
                "parent_doc_id": url,
                "doc_title": img["text"],
                "date": date,
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
                "source": "ukorona",
                "type": "video",
                "entity_id": vid_id,
                "parent_doc_id": url,
                "doc_title": vid["title"],
                "date": date,
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
        "pages_processed": len(all_pages),
        "items_indexed": total_indexed,
        "errors": errors[:10],
        "total_errors": len(errors)
    }
    logger.info(f"✅ Парсинг ukorona.ru завершён: {result}")
    return result


def get_status() -> Dict[str, Any]:
    state = _load_json(STATE_FILE, {})
    sitemap = _load_json(SITEMAP_FILE, {})
    return {
        "collector": "Ukorona",
        "last_run": state.get("last_run"),
        "pages_processed": len(state.get("processed_urls", [])),
        "items_indexed": state.get("last_indexed", 0),
        "sitemap_articles": sitemap.get("total_articles", 0)
    }