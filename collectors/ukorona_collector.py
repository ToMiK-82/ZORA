"""
Коллектор данных с сайта ukorona.ru.
Наследует BaseCollector, реализует асинхронный run().
Сохраняет всю существующую функциональность: бренды, структурированные данные,
PDF, изображения, видео, белые/чёрные списки.
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

logger = logging.getLogger("ZORA.Collector.Ukorona")

# Конфигурация
UKORONA_URL = os.getenv("UKORONA_URL", "https://ukorona.ru")
SITEMAP_FILE = os.path.join("data", "ukorona_sitemap.json")
STATE_FILE = os.path.join("data", "ukorona_state.json")
TEMP_DIR = os.path.join("data", "ukorona_temp")
REQUEST_DELAY = 1.0

ALLOWED_URL_PATTERNS = ["/catalog/", "/product/", "/articles/"]
BLACKLIST_WORDS = [
    "contacts", "dealers", "about", "vacancy", "privacy",
    "policy", "news", "main", "login", "register", "delivery",
    "payment", "warranty", "service", "reviews", "faq",
]


class UkoronaCollector(BaseCollector):
    def __init__(self, config: dict = None):
        super().__init__(config)
        self.base_url = config.get("base_url", UKORONA_URL) if config else UKORONA_URL
        self.sitemap = {}
        self.state = {}
        self.session = self._create_session()

    @staticmethod
    def _create_session() -> requests.Session:
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
        Основной метод запуска парсинга.

        Параметры (в params):
            limit: int — ограничение числа страниц (None = все)
        """
        params = params or {}
        limit = params.get("limit", None)
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
        all_pages = sitemap.get("articles", [])
        if limit:
            all_pages = all_pages[:limit]

        total_pages = len(all_pages)
        logger.info(f"Всего страниц для обработки: {total_pages}")

        # Индексация
        try:
            from memory.qdrant_memory import memory as _memory
        except ImportError:
            self.status = "error"
            return {"success": False, "chunks_added": 0, "items_processed": 0, "errors": ["Qdrant память недоступна"]}

        errors = []
        total_indexed = 0

        for idx, page in enumerate(all_pages):
            if self._stop_event.is_set():
                break

            url = page["url"]
            if url in processed_urls:
                logger.debug(f"Пропуск: {url}")
                continue
            if not self._is_url_allowed(url):
                processed_urls.add(url)
                continue

            self._update_progress(idx / total_pages, f"Обработка: {url}")
            logger.info(f"Обработка: {url}")

            resp = await self._run_sync_in_thread(self._fetch_page, url)
            if not resp:
                errors.append(f"Не удалось загрузить {url}")
                continue

            html = resp.text
            page_type = self._classify_url(url)
            doc_title = page.get("title", url.split("/")[-1] or url)
            date = datetime.now().isoformat()
            brand = self._detect_brand(url, html)
            structured = self._extract_structured_data(html)
            if "name" in structured:
                doc_title = structured["name"]

            # Текстовый контент
            text = self._extract_text(html)
            if text:
                chunks = chunk_by_tokens(text)
                for i, chunk in enumerate(chunks):
                    metadata = {
                        "source": "ukorona",
                        "type": page_type,
                        "entity_id": url,
                        "parent_doc_id": url,
                        "doc_title": doc_title,
                        "date": date,
                        "chunk_index": i,
                        "url": url,
                        "brand": brand,
                    }
                    if structured:
                        # добавляем только непустые значения
                        for k, v in structured.items():
                            if v:
                                metadata[k] = v
                    _memory.store(text=chunk, metadata=metadata)
                    total_indexed += 1

            # PDF, изображения, видео – аналогично синхронной версии
            pdf_links = self._extract_pdf_links(html, url)
            for pdf_url in pdf_links:
                if pdf_url in processed_urls:
                    continue
                pdf_text = await self._run_sync_in_thread(self._extract_pdf_text, pdf_url)
                if pdf_text:
                    chunks = chunk_by_tokens(pdf_text)
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

            images = self._extract_image_metadata(html, url)
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

            videos = self._extract_video_info(html, url)
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

        # Сохранение состояния
        state["processed_urls"] = list(processed_urls)
        state["last_run"] = datetime.now().isoformat()
        state["last_indexed"] = total_indexed
        self._save_json(STATE_FILE, state)

        self.status = "done"
        self._update_progress(1.0, f"Завершено. Проиндексировано {total_indexed} записей.")
        return {
            "success": len(errors) == 0 or total_indexed > 0,
            "chunks_added": total_indexed,
            "items_processed": len(all_pages),
            "errors": errors[:10]
        }

    # --------------- Вспомогательные методы (перенесены из старого модуля) ---------------
    def _is_url_allowed(self, url: str) -> bool:
        url_lower = url.lower()
        if not any(pattern in url_lower for pattern in ALLOWED_URL_PATTERNS):
            return False
        for word in BLACKLIST_WORDS:
            if word in url_lower:
                return False
        return True

    def _classify_url(self, url: str) -> str:
        url_lower = url.lower()
        if "/product/" in url_lower or "/catalog/" in url_lower:
            return "product"
        if "/news/" in url_lower:
            return "news"
        if "/actions/" in url_lower or "/promotions/" in url_lower:
            return "promotion"
        return "page"

    def _detect_brand(self, url: str, html: str) -> str:
        url_lower = url.lower()
        if "/bryuhokorm" in url_lower or "/bryukokorm" in url_lower:
            return "Брюхокорм"
        if "/yuzhnaya-korona" in url_lower or "/uzhnaya-korona" in url_lower:
            return "Южная Корона"
        try:
            soup = BeautifulSoup(html, "html.parser")
            breadcrumbs = soup.select_one(".breadcrumbs, nav.breadcrumb, .breadcrumb")
            if breadcrumbs:
                crumbs_text = breadcrumbs.get_text(" ", strip=True).lower()
                if "брюхокорм" in crumbs_text:
                    return "Брюхокорм"
                if "южная корона" in crumbs_text or "южнокорм" in crumbs_text:
                    return "Южная Корона"
            meta_brand = soup.find("meta", attrs={"name": "brand"})
            if meta_brand and meta_brand.get("content"):
                content = meta_brand["content"].strip().lower()
                if "брюхокорм" in content:
                    return "Брюхокорм"
                if "южная корона" in content or "южнокорм" in content:
                    return "Южная Корона"
            elem = soup.find(attrs={"data-brand": True})
            if elem:
                brand_val = elem["data-brand"].strip().lower()
                if "брюхокорм" in brand_val:
                    return "Брюхокорм"
                if "южная корона" in brand_val or "южнокорм" in brand_val:
                    return "Южная Корона"
        except Exception:
            pass
        return "unknown"

    def _build_sitemap(self) -> Dict[str, Any]:
        logger.info("Построение карты сайта ukorona.ru...")
        # сначала sitemap.xml
        urls = self._get_all_urls_from_sitemap()
        if not urls:
            urls = self._crawl_navigation([self.base_url])
        if not urls:
            logger.error("Не удалось собрать ни одной ссылки")
            return {"success": False, "error": "Не удалось собрать URL"}
        sitemap = {
            "built_at": datetime.now().isoformat(),
            "total_articles": len(urls),
            "articles": [{"url": u, "title": u.split("/")[-1] or u} for u in urls]
        }
        self._save_json(SITEMAP_FILE, sitemap)
        logger.info(f"Карта построена: {len(urls)} страниц")
        return {"success": True, "articles": len(urls)}

    def _get_all_urls_from_sitemap(self) -> List[str]:
        sitemap_url = urljoin(self.base_url, "/sitemap.xml")
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

    def _crawl_navigation(self, start_urls: List[str]) -> List[str]:
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
                    continue
                if any(skip in full for skip in ["/login", "/register"]):
                    continue
                all_links.add(full)
                if full not in visited:
                    to_visit.add(full)
        return list(all_links)

    def _fetch_page(self, url: str, stream: bool = False) -> Optional[requests.Response]:
        time.sleep(REQUEST_DELAY)
        try:
            resp = self.session.get(url, timeout=30, stream=stream)
            if resp.status_code == 200:
                return resp
        except requests.RequestException as e:
            logger.warning(f"Ошибка загрузки {url}: {e}")
        return None

    def _extract_text(self, html: str) -> str:
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

    def _extract_structured_data(self, html: str) -> Dict[str, Any]:
        soup = BeautifulSoup(html, "html.parser")
        data = {}
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                ld = json.loads(script.string)
                if not isinstance(ld, dict):
                    continue
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
                        data["brand"] = ld["brand"].get("name") if isinstance(ld["brand"], dict) else str(ld["brand"])
                    for key in ("weight", "height", "width", "depth", "gtin13", "mpn"):
                        if key in ld:
                            data[key] = ld[key]
            except Exception:
                pass
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
                if len(key) < 2 or not value:
                    continue
                if key not in data:
                    data[key] = value
        clean_data = {}
        for k, v in data.items():
            if v is None or v == "" or (isinstance(v, str) and v.strip() == ""):
                continue
            if isinstance(v, float) and v == 0.0:
                continue
            if isinstance(v, bool) and not v:
                continue
            clean_data[k] = v
        return clean_data

    def _extract_pdf_links(self, html: str, base_url: str) -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.lower().endswith(".pdf"):
                links.append(urljoin(base_url, href))
        return links

    def _extract_image_metadata(self, html: str, base_url: str) -> List[Dict[str, str]]:
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
            logger.warning("pypdf не установлена. PDF пропущены.")
            return None
        except Exception as e:
            logger.error(f"Ошибка извлечения текста из PDF {pdf_url}: {e}")
            return None

    @staticmethod
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

    @staticmethod
    def _save_json(filepath: str, data: Any):
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)