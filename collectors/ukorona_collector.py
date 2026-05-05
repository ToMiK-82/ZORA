"""
Коллектор данных с сайта ukorona.ru.
Парсит товары, новости, акции и индексирует в Qdrant.
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

logger = logging.getLogger("ZORA.Collector.Ukorona")

# Конфигурация
UKORONA_URL = os.getenv("UKORONA_URL", "https://ukorona.ru")
SITEMAP_FILE = os.path.join("data", "ukorona_sitemap.json")
STATE_FILE = os.path.join("data", "ukorona_state.json")

# Задержка между запросами
REQUEST_DELAY = 1.0

# Категории для обхода
CATEGORIES = [
    "/catalog/",
    "/news/",
    "/actions/",
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
    Строит карту сайта ukorona.ru: обходит категории и собирает ссылки.

    Returns:
        Статистика: количество найденных URL по типам.
    """
    logger.info("Построение карты сайта ukorona.ru...")
    session = _get_session()

    sitemap = {
        "built_at": datetime.now().isoformat(),
        "products": [],
        "news": [],
        "promotions": [],
    }

    for category_path in CATEGORIES:
        category_url = urljoin(UKORONA_URL, category_path)
        logger.info(f"  Категория: {category_url}")

        html = _fetch_page(category_url, session)
        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")

        # Собираем все ссылки
        for link in soup.find_all("a", href=True):
            href = link["href"]
            title = link.get_text(strip=True)

            # Пропускаем служебные ссылки
            if any(skip in href for skip in ["#", "javascript:", "/login", "/register"]):
                continue

            full_url = urljoin(UKORONA_URL, href)

            # Определяем тип по URL
            if "/product/" in href or "/catalog/" in href:
                if full_url not in [p["url"] for p in sitemap["products"]]:
                    sitemap["products"].append({
                        "url": full_url,
                        "title": title or "Товар"
                    })
            elif "/news/" in href:
                if full_url not in [n["url"] for n in sitemap["news"]]:
                    sitemap["news"].append({
                        "url": full_url,
                        "title": title or "Новость"
                    })
            elif "/actions/" in href or "/promotions/" in href:
                if full_url not in [p["url"] for p in sitemap["promotions"]]:
                    sitemap["promotions"].append({
                        "url": full_url,
                        "title": title or "Акция"
                    })

        # Пробуем пагинацию
        page = 2
        while True:
            pagination_url = f"{category_url}?page={page}"
            page_html = _fetch_page(pagination_url, session)
            if not page_html:
                break

            page_soup = BeautifulSoup(page_html, "html.parser")
            links_on_page = page_soup.find_all("a", href=True)
            if not links_on_page:
                break

            found_new = False
            for link in links_on_page:
                href = link["href"]
                title = link.get_text(strip=True)
                if any(skip in href for skip in ["#", "javascript:", "/login", "/register"]):
                    continue

                full_url = urljoin(UKORONA_URL, href)

                if "/product/" in href or "/catalog/" in href:
                    if full_url not in [p["url"] for p in sitemap["products"]]:
                        sitemap["products"].append({"url": full_url, "title": title or "Товар"})
                        found_new = True
                elif "/news/" in href:
                    if full_url not in [n["url"] for n in sitemap["news"]]:
                        sitemap["news"].append({"url": full_url, "title": title or "Новость"})
                        found_new = True
                elif "/actions/" in href or "/promotions/" in href:
                    if full_url not in [p["url"] for p in sitemap["promotions"]]:
                        sitemap["promotions"].append({"url": full_url, "title": title or "Акция"})
                        found_new = True

            if not found_new:
                break
            page += 1

    total = len(sitemap["products"]) + len(sitemap["news"]) + len(sitemap["promotions"])
    _save_json(SITEMAP_FILE, sitemap)
    logger.info(f"✅ Карта сайта построена: {len(sitemap['products'])} товаров, "
                f"{len(sitemap['news'])} новостей, {len(sitemap['promotions'])} акций")
    return {
        "success": True,
        "products": len(sitemap["products"]),
        "news": len(sitemap["news"]),
        "promotions": len(sitemap["promotions"]),
        "total": total,
        "sitemap_file": SITEMAP_FILE
    }


def _parse_product_page(url: str, html: str) -> Optional[Dict[str, Any]]:
    """Парсит страницу товара."""
    soup = BeautifulSoup(html, "html.parser")

    # Название
    name = ""
    for tag in soup.find_all(["h1", "h2"]):
        text = tag.get_text(strip=True)
        if text and len(text) > 3:
            name = text
            break

    # Цена
    price = 0.0
    price_pattern = re.compile(r'(\d[\d\s]*[.,]?\d*)')
    for price_tag in soup.find_all(class_=re.compile(r"price|cost|amount", re.I)):
        text = price_tag.get_text(strip=True)
        match = price_pattern.search(text)
        if match:
            try:
                price = float(match.group(1).replace(" ", "").replace(",", "."))
            except ValueError:
                pass

    # Артикул
    article = ""
    for tag in soup.find_all(["span", "div", "p"]):
        text = tag.get_text(strip=True)
        if "артикул" in text.lower() or "article" in text.lower():
            article = text.split(":")[-1].strip() if ":" in text else text
            break

    # Наличие
    in_stock = True
    for tag in soup.find_all(["span", "div", "p"]):
        text = tag.get_text(strip=True).lower()
        if "нет в наличии" in text or "под заказ" in text:
            in_stock = False
            break

    # Описание
    description = ""
    for selector in [".description", "#description", ".product-description",
                     ".content", "article", ".text"]:
        desc_tag = soup.select_one(selector)
        if desc_tag:
            description = desc_tag.get_text(separator="\n", strip=True)
            break

    if not description:
        # Берём весь текст body как описание
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        if soup.body:
            description = soup.body.get_text(separator="\n", strip=True)[:3000]

    if not name:
        return None

    return {
        "source": "ukorona",
        "type": "product",
        "name": name,
        "price": price,
        "in_stock": in_stock,
        "article": article,
        "description": description,
        "url": url,
        "timestamp": datetime.now().isoformat()
    }


def _parse_news_page(url: str, html: str) -> Optional[Dict[str, Any]]:
    """Парсит страницу новости."""
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    for tag in soup.find_all(["h1", "h2"]):
        text = tag.get_text(strip=True)
        if text and len(text) > 5:
            title = text
            break

    content = ""
    for selector in [".news-content", ".content", "article", ".text", "main"]:
        content_tag = soup.select_one(selector)
        if content_tag:
            content = content_tag.get_text(separator="\n", strip=True)
            break

    if not title:
        return None

    return {
        "source": "ukorona",
        "type": "news",
        "name": title,
        "description": content[:3000],
        "url": url,
        "timestamp": datetime.now().isoformat()
    }


def _parse_promotion_page(url: str, html: str) -> Optional[Dict[str, Any]]:
    """Парсит страницу акции."""
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    for tag in soup.find_all(["h1", "h2"]):
        text = tag.get_text(strip=True)
        if text and len(text) > 5:
            title = text
            break

    content = ""
    for selector in [".action-content", ".promotion-content", ".content", "article", "main"]:
        content_tag = soup.select_one(selector)
        if content_tag:
            content = content_tag.get_text(separator="\n", strip=True)
            break

    if not title:
        return None

    return {
        "source": "ukorona",
        "type": "promotion",
        "name": title,
        "description": content[:3000],
        "url": url,
        "timestamp": datetime.now().isoformat()
    }


def run(limit: Optional[int] = None, update_existing: bool = False) -> Dict[str, Any]:
    """
    Парсит сайт ukorona.ru и индексирует данные в Qdrant.

    Args:
        limit: Максимальное количество страниц для парсинга.
        update_existing: Обновлять ли уже проиндексированные URL.

    Returns:
        Результат операции.
    """
    logger.info(f"Запуск парсинга ukorona.ru: limit={limit}, update_existing={update_existing}")

    # Загружаем или строим карту
    sitemap = _load_json(SITEMAP_FILE)
    if not sitemap or "products" not in sitemap:
        logger.info("Карта сайта не найдена, строим...")
        sitemap_result = build_sitemap()
        if not sitemap_result.get("success"):
            return {"success": False, "error": "Не удалось построить карту сайта"}
        sitemap = _load_json(SITEMAP_FILE)

    # Загружаем состояние
    state = _load_json(STATE_FILE, {"processed_urls": []})
    processed_urls = set(state.get("processed_urls", []))

    session = _get_session()
    errors = []
    total_indexed = 0
    total_processed = 0

    # Собираем все URL для обработки
    all_pages = []
    for item in sitemap.get("products", []):
        all_pages.append(("product", item))
    for item in sitemap.get("news", []):
        all_pages.append(("news", item))
    for item in sitemap.get("promotions", []):
        all_pages.append(("promotion", item))

    if limit:
        all_pages = all_pages[:limit]

    logger.info(f"Всего страниц для обработки: {len(all_pages)}")

    for page_type, item in all_pages:
        url = item["url"]

        if not update_existing and url in processed_urls:
            logger.debug(f"  Пропуск (уже обработано): {url}")
            continue

        logger.info(f"  Парсинг ({page_type}): {item.get('title', url)[:60]}")
        html = _fetch_page(url, session)
        if not html:
            errors.append(f"Не удалось загрузить {url}")
            continue

        # Парсим в зависимости от типа
        parsed = None
        if page_type == "product":
            parsed = _parse_product_page(url, html)
        elif page_type == "news":
            parsed = _parse_news_page(url, html)
        elif page_type == "promotion":
            parsed = _parse_promotion_page(url, html)

        if not parsed:
            errors.append(f"Не удалось распарсить {url}")
            continue

        # Индексируем в Qdrant
        try:
            from memory.qdrant_memory import memory as _memory
        except ImportError:
            logger.warning("Qdrant память недоступна")
            break

        try:
            text = f"{parsed.get('name', '')} - {parsed.get('description', '')}"
            metadata = {k: v for k, v in parsed.items() if k not in ("name", "description")}
            metadata["raw_data"] = json.dumps(parsed, ensure_ascii=False)
            _memory.store(text=text, metadata=metadata)
            total_indexed += 1
        except Exception as e:
            logger.warning(f"Ошибка индексации {url}: {e}")
            errors.append(f"Ошибка индексации: {e}")

        processed_urls.add(url)
        total_processed += 1

    # Сохраняем состояние
    state["processed_urls"] = list(processed_urls)
    state["last_run"] = datetime.now().isoformat()
    state["last_processed"] = total_processed
    state["last_indexed"] = total_indexed
    _save_json(STATE_FILE, state)

    result = {
        "success": len(errors) == 0 or total_processed > 0,
        "pages_found": len(all_pages),
        "pages_processed": total_processed,
        "items_indexed": total_indexed,
        "errors": errors[:10],
        "total_errors": len(errors)
    }

    logger.info(f"✅ Парсинг ukorona.ru завершён: {result}")
    return result


def get_status() -> Dict[str, Any]:
    """Возвращает статус коллектора."""
    state = _load_json(STATE_FILE, {})
    sitemap = _load_json(SITEMAP_FILE, {})
    return {
        "collector": "Ukorona",
        "last_run": state.get("last_run"),
        "pages_processed": state.get("last_processed", 0),
        "items_indexed": state.get("last_indexed", 0),
        "sitemap_products": len(sitemap.get("products", [])),
        "sitemap_news": len(sitemap.get("news", [])),
        "sitemap_promotions": len(sitemap.get("promotions", [])),
        "processed_urls": len(state.get("processed_urls", []))
    }
