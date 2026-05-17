"""
Коллектор данных с портала ИТС 1С (its.1c.ru).
Наследует BaseCollector, реализует асинхронный run().
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

import requests
from bs4 import BeautifulSoup

from collectors.base import BaseCollector
from connectors.tokenizer_utils import chunk_by_tokens

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


class ITSCollector(BaseCollector):
    """Коллектор данных с портала ИТС 1С (its.1c.ru)."""

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.base_url = config.get("base_url", ITS_BASE_URL) if config else ITS_BASE_URL
        self.sitemap = {}
        self.state = {}
        self.session = self._create_session()

    @staticmethod
    def _create_session() -> requests.Session:
        """Создаёт сессию requests с заголовками."""
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        return session

    async def run(self, params: dict = None) -> dict:
        """
        Основной метод запуска парсинга ИТС.

        Параметры (в params):
            limit: int — ограничение числа статей (None = все)
            section: str — фильтр по разделу ИТС (например "ka", "buh", "prog", "calendar")
            fresh_only: bool — если True, пропускает уже обработанные URL

        Returns:
            dict с ключами:
                - success: bool
                - chunks_added: int
                - items_processed: int
                - errors: list[str]
        """
        params = params or {}
        limit = params.get("limit", None)
        section_filter = params.get("section", None)
        fresh_only = params.get("fresh_only", False)

        self.status = "running"
        self._update_progress(0.0, "Подготовка карты сайта...")

        # Загружаем или строим карту
        sitemap = self._load_json(SITEMAP_FILE)
        if not sitemap or "articles" not in sitemap:
            build_result = await self._run_sync_in_thread(self._build_sitemap)
            if not build_result.get("success"):
                self.status = "error"
                return {
                    "success": False,
                    "chunks_added": 0,
                    "items_processed": 0,
                    "errors": [build_result.get("error", "Не удалось построить карту")]
                }
            sitemap = self._load_json(SITEMAP_FILE)

        state = self._load_json(STATE_FILE, {"processed_urls": []})
        processed_urls = set(state.get("processed_urls", []))
        all_articles = sitemap.get("articles", [])

        # Фильтр по разделу, если указан
        if section_filter:
            section_filter = section_filter.lower()
            all_articles = [
                a for a in all_articles
                if f"/its/{section_filter}/" in a.get("url", "").lower()
            ]
            logger.info(f"Отфильтровано по разделу '{section_filter}': {len(all_articles)} статей")

        if limit:
            all_articles = all_articles[:limit]

        total_pages = len(all_articles)
        logger.info(f"Всего статей для обработки: {total_pages}")

        # Индексация
        try:
            from memory.qdrant_memory import memory as _memory
        except ImportError:
            self.status = "error"
            return {"success": False, "chunks_added": 0, "items_processed": 0, "errors": ["Qdrant память недоступна"]}

        errors = []
        total_indexed = 0

        for idx, article in enumerate(all_articles):
            if self._stop_event.is_set():
                logger.info("Остановка по запросу")
                break

            url = article["url"]

            # Пропуск уже обработанных
            if url in processed_urls:
                logger.debug(f"Пропуск (уже обработано): {url}")
                continue

            # Фильтрация по белому списку разделов ИТС
            if not self._is_url_allowed(url):
                logger.debug(f"Пропуск (не в белом списке): {url}")
                processed_urls.add(url)
                continue

            self._update_progress(idx / total_pages if total_pages else 0, f"Обработка: {url}")
            logger.info(f"Обработка: {url}")

            resp = await self._run_sync_in_thread(self._fetch_page, url)
            if not resp:
                errors.append(f"Не удалось загрузить {url}")
                continue

            html = resp.text
            doc_title = article.get("title", url.split("/")[-1] or url)
            date = datetime.now().isoformat()

            # --- Текстовый контент ---
            text = self._extract_text(html)
            if text:
                chunks = chunk_by_tokens(text)
                for i, chunk in enumerate(chunks):
                    metadata = {
                        "source": "its",
                        "type": "documentation",
                        "entity_id": url,
                        "parent_doc_id": url,
                        "doc_title": doc_title,
                        "date": date,
                        "chunk_index": i,
                        "url": url,
                    }
                    _memory.store(text=chunk, metadata=metadata)
                    total_indexed += 1

            # --- PDF-ссылки ---
            pdf_links = self._extract_pdf_links(html, url)
            for pdf_url in pdf_links:
                if pdf_url in processed_urls:
                    continue
                logger.info(f"    Индексирую PDF: {pdf_url}")
                pdf_text = await self._run_sync_in_thread(self._extract_pdf_text, pdf_url)
                if pdf_text:
                    chunks = chunk_by_tokens(pdf_text)
                    for j, chunk in enumerate(chunks):
                        metadata = {
                            "source": "its",
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
            images = self._extract_image_metadata(html, url)
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
            videos = self._extract_video_info(html, url)
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
        self._save_json(STATE_FILE, state)

        self.status = "done"
        self._update_progress(1.0, f"Завершено. Проиндексировано {total_indexed} записей.")
        return {
            "success": len(errors) == 0 or total_indexed > 0,
            "chunks_added": total_indexed,
            "items_processed": len(all_articles),
            "errors": errors[:10]
        }

    # --------------- Вспомогательные методы ---------------

    def _is_url_allowed(self, url: str) -> bool:
        """Проверяет, соответствует ли URL белому списку разделов ИТС."""
        url_lower = url.lower()
        for pattern in ALLOWED_URL_PATTERNS:
            if pattern in url_lower:
                return True
        return False

    def _build_sitemap(self) -> Dict[str, Any]:
        """Строит полную карту сайта ИТС: sitemap.xml или обход навигации."""
        logger.info("Построение карты сайта ИТС 1С...")

        # Пробуем авторизоваться
        if ITS_USERNAME and ITS_PASSWORD:
            login_url = urljoin(self.base_url, "/login")
            try:
                resp = self.session.post(login_url, data={"username": ITS_USERNAME, "password": ITS_PASSWORD}, timeout=30)
                if resp.ok:
                    logger.info("Авторизация на ИТС выполнена")
                else:
                    logger.warning(f"Авторизация не удалась: {resp.status_code}")
            except Exception as e:
                logger.warning(f"Ошибка авторизации: {e}")

        # 1. Попытка через sitemap
        urls = self._get_all_urls_from_sitemap()
        if not urls:
            # 2. Обход навигации
            logger.info("Sitemap не найден, начинаю обход навигации...")
            start_urls = [urljoin(self.base_url, "/docs"), urljoin(self.base_url, "/documentation")]
            urls = self._crawl_navigation(start_urls)

        if not urls:
            logger.error("Не удалось собрать ни одной ссылки")
            return {"success": False, "error": "Не удалось собрать URL"}

        sitemap = {
            "built_at": datetime.now().isoformat(),
            "total_articles": len(urls),
            "articles": [{"url": u, "title": u.split("/")[-1] or u} for u in urls]
        }
        self._save_json(SITEMAP_FILE, sitemap)
        logger.info(f"✅ Карта построена: {len(urls)} статей")
        return {"success": True, "articles": len(urls)}

    def _get_all_urls_from_sitemap(self) -> List[str]:
        """Пытается загрузить sitemap.xml и извлечь все URL."""
        sitemap_url = urljoin(self.base_url, "/sitemap.xml")
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

    def _crawl_navigation(self, start_urls: List[str]) -> List[str]:
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
            resp = self._fetch_page(url)
            if not resp:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for link in soup.find_all("a", href=True):
                href = link["href"].strip()
                if not href or href.startswith("#") or href.startswith("javascript:"):
                    continue
                full = urljoin(url, href)
                parsed = urlparse(full)
                if parsed.netloc != urlparse(self.base_url).netloc:
                    continue  # внешние ссылки
                if any(prefix in full for prefix in ["/login", "/register"]):
                    continue
                if "/docs/" in full or "/documentation/" in full:
                    all_links.add(full)
                    if full not in visited:
                        to_visit.add(full)
        return list(all_links)

    def _fetch_page(self, url: str, stream: bool = False) -> Optional[requests.Response]:
        """Загружает страницу с задержкой. Возвращает response, если статус 200, иначе None."""
        time.sleep(REQUEST_DELAY)
        try:
            resp = self.session.get(url, timeout=30, stream=stream)
            if resp.status_code == 200:
                return resp
        except requests.RequestException as e:
            logger.warning(f"Ошибка загрузки {url}: {e}")
        return None

    def _extract_text(self, html: str) -> str:
        """Извлекает основной текст из HTML."""
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

    def _extract_pdf_links(self, html: str, base_url: str) -> List[str]:
        """Извлекает ссылки на PDF из HTML."""
        soup = BeautifulSoup(html, "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.lower().endswith(".pdf"):
                links.append(urljoin(base_url, href))
        return links

    def _extract_image_metadata(self, html: str, base_url: str) -> List[Dict[str, str]]:
        """Извлекает метаданные изображений (alt, title)."""
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

    def _extract_video_info(self, html: str, base_url: str) -> List[Dict[str, str]]:
        """Извлекает информацию о видео (iframe с YouTube, rutube и т.п.)."""
        soup = BeautifulSoup(html, "html.parser")
        videos = []
        for iframe in soup.find_all("iframe", src=True):
            src = urljoin(base_url, iframe["src"])
            if any(d in src for d in ["youtube.com", "rutube.ru", "vimeo.com"]):
                title_tag = soup.find("h1") or soup.find("h2")
                title = title_tag.get_text(strip=True) if title_tag else "Видео"
                videos.append({"url": src, "title": title, "type": "video"})
        return videos

    def _extract_pdf_text(self, pdf_url: str) -> Optional[str]:
        """Скачивает PDF и возвращает извлечённый текст (первые 2000 символов)."""
        try:
            import pypdf
            resp = self._fetch_page(pdf_url, stream=True)
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

    @staticmethod
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

    @staticmethod
    def _save_json(filepath: str, data: Any):
        """Сохраняет данные в JSON-файл."""
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @staticmethod
    def get_status() -> Dict[str, Any]:
        """Возвращает состояние последнего запуска коллектора."""
        state = ITSCollector._load_json(STATE_FILE, {})
        sitemap = ITSCollector._load_json(SITEMAP_FILE, {})
        return {
            "collector": "ITS",
            "last_run": state.get("last_run"),
            "articles_processed": len(state.get("processed_urls", [])),
            "chunks_indexed": state.get("last_indexed", 0),
            "sitemap_articles": sitemap.get("total_articles", 0)
        }
