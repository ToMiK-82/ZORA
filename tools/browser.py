"""
Модуль браузерной автоматизации с использованием Zendriver.
Zendriver - Python-библиотека для работы с Chrome через CDP.
"""

import asyncio
import logging
import os
import zendriver as zd
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Глобальные переменные для синглтона браузера
_browser = None
_current_page = None

async def _get_browser():
    """Получить или создать экземпляр браузера (синглтон)."""
    global _browser
    if _browser is None:
        # Пробуем найти Chrome в стандартных местах
        chrome_paths = [
            "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
            "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
            os.path.expanduser("~\\AppData\\Local\\Google\\Chrome\\Application\\chrome.exe"),
            "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",  # Edge тоже подходит
        ]
        
        browser_executable_path = None
        for path in chrome_paths:
            if os.path.exists(path):
                browser_executable_path = path
                logger.info(f"Найден браузер: {path}")
                break
        
        if browser_executable_path:
            _browser = await zd.start(browser_executable_path=browser_executable_path)
            logger.info(f"Браузер Zendriver запущен с {browser_executable_path}")
        else:
            # Если браузер не найден, пробуем запустить без указания пути
            # (Zendriver попробует найти сам)
            _browser = await zd.start()
            logger.info("Браузер Zendriver запущен (автоопределение)")
    return _browser

async def get_page_text(url: str) -> str:
    """Открывает URL и возвращает текстовое содержимое страницы."""
    try:
        browser = await _get_browser()
        tab = await browser.get(url)
        # Ждем загрузки страницы
        await asyncio.sleep(1)
        # Получаем текст через evaluate
        text = await tab.evaluate("document.body.innerText")
        logger.info(f"Получен текст страницы {url} (длина: {len(text)} символов)")
        return text
    except Exception as e:
        logger.error(f"Ошибка при получении текста страницы {url}: {e}")
        return f"Ошибка: {e}"

async def get_page_html(url: str) -> str:
    """Открывает URL и возвращает HTML-код страницы."""
    try:
        # Проверяем, что URL валидный
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        # Пробуем использовать Zendriver
        try:
            browser = await _get_browser()
            tab = await browser.get(url)
            # Ждем загрузки страницы
            await asyncio.sleep(2)
            # Получаем HTML через evaluate
            html = await tab.evaluate("document.documentElement.outerHTML")
            logger.info(f"Получен HTML страницы {url} через Zendriver (длина: {len(html)} символов)")
            return html
        except Exception as zendriver_error:
            logger.warning(f"Zendriver не сработал, пробуем requests: {zendriver_error}")
            
            # Fallback на requests
            try:
                import requests
                from bs4 import BeautifulSoup
                
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                response = requests.get(url, headers=headers, timeout=10)
                response.raise_for_status()
                
                # Используем BeautifulSoup для чистого HTML
                soup = BeautifulSoup(response.text, 'html.parser')
                # Удаляем скрипты и стили для чистого текста
                for script in soup(["script", "style"]):
                    script.decompose()
                
                html = str(soup)
                logger.info(f"Получен HTML страницы {url} через requests (длина: {len(html)} символов)")
                return html
            except ImportError:
                logger.error("Библиотека requests не установлена")
                return f"Ошибка: требуется установить библиотеку requests (pip install requests)"
            except Exception as requests_error:
                logger.error(f"Ошибка при получении HTML через requests: {requests_error}")
                return f"Ошибка получения страницы: {requests_error}"
                
    except Exception as e:
        logger.error(f"Ошибка при получении HTML страницы {url}: {e}")
        return f"Ошибка: {e}"

async def click_element(selector: str) -> str:
    """Клик по элементу по CSS-селектору или тексту."""
    try:
        browser = await _get_browser()
        if not browser.pages:
            return "Нет открытых страниц. Сначала откройте страницу с помощью get_page_text или get_page_html."
        
        page = browser.pages[-1]  # последняя открытая страница
        
        # Пробуем найти по CSS-селектору
        element = await page.query_selector(selector)
        if element:
            await element.click()
            logger.info(f"Клик по элементу с селектором: {selector}")
            return f"Клик выполнен по элементу: {selector}"
        
        # Пробуем найти по тексту
        elements = await page.find(selector)
        if elements:
            await elements[0].click()
            logger.info(f"Клик по элементу с текстом: {selector}")
            return f"Клик выполнен по элементу с текстом: {selector}"
        
        return f"Элемент '{selector}' не найден"
    except Exception as e:
        logger.error(f"Ошибка при клике по элементу {selector}: {e}")
        return f"Ошибка: {e}"

async def fill_input(selector: str, value: str) -> str:
    """Заполнить поле ввода по CSS-селектору."""
    try:
        browser = await _get_browser()
        if not browser.pages:
            return "Нет открытых страниц. Сначала откройте страницу с помощью get_page_text или get_page_html."
        
        page = browser.pages[-1]
        element = await page.query_selector(selector)
        if element:
            await element.fill(value)
            logger.info(f"Поле {selector} заполнено значением: {value}")
            return f"Поле '{selector}' заполнено значением: '{value}'"
        else:
            return f"Элемент '{selector}' не найден"
    except Exception as e:
        logger.error(f"Ошибка при заполнении поля {selector}: {e}")
        return f"Ошибка: {e}"

async def perform_actions(actions: List[Dict[str, Any]]) -> str:
    """Выполнить последовательность действий."""
    try:
        browser = await _get_browser()
        results = []
        
        for action in actions:
            action_type = action.get("type", "").lower()
            
            if action_type == "open":
                url = action.get("url", "")
                if url:
                    page = await browser.get(url)
                    results.append(f"Открыта страница: {url}")
                else:
                    results.append("Ошибка: URL не указан для действия 'open'")
                    
            elif action_type == "click":
                selector = action.get("selector", "")
                if selector:
                    if browser.pages:
                        page = browser.pages[-1]
                        element = await page.query_selector(selector)
                        if element:
                            await element.click()
                            results.append(f"Клик по элементу: {selector}")
                        else:
                            results.append(f"Элемент не найден: {selector}")
                    else:
                        results.append("Нет открытых страниц для клика")
                else:
                    results.append("Ошибка: селектор не указан для действия 'click'")
                    
            elif action_type == "fill":
                selector = action.get("selector", "")
                value = action.get("value", "")
                if selector and value is not None:
                    if browser.pages:
                        page = browser.pages[-1]
                        element = await page.query_selector(selector)
                        if element:
                            await element.fill(value)
                            results.append(f"Заполнено поле {selector} значением: {value}")
                        else:
                            results.append(f"Элемент не найден: {selector}")
                    else:
                        results.append("Нет открытых страниц для заполнения")
                else:
                    results.append("Ошибка: селектор или значение не указаны для действия 'fill'")
                    
            elif action_type == "wait":
                seconds = action.get("seconds", 1)
                await asyncio.sleep(seconds)
                results.append(f"Ожидание {seconds} секунд")
                
            else:
                results.append(f"Неизвестный тип действия: {action_type}")
        
        return "\n".join(results)
    except Exception as e:
        logger.error(f"Ошибка при выполнении действий: {e}")
        return f"Ошибка: {e}"

async def close_browser():
    """Закрыть браузер (освободить ресурсы)."""
    global _browser, _current_page
    try:
        if _browser:
            await _browser.stop()
            _browser = None
            _current_page = None
            logger.info("Браузер закрыт")
            return "Браузер успешно закрыт"
    except Exception as e:
        logger.error(f"Ошибка при закрытии браузера: {e}")
        return f"Ошибка при закрытии браузера: {e}"

async def get_current_url() -> str:
    """Получить URL текущей страницы."""
    try:
        browser = await _get_browser()
        if browser.pages:
            page = browser.pages[-1]
            return await page.url()
        return "Нет открытых страниц"
    except Exception as e:
        logger.error(f"Ошибка при получении текущего URL: {e}")
        return f"Ошибка: {e}"

async def take_screenshot(path: str = "screenshot.png") -> str:
    """Сделать скриншот текущей страницы."""
    try:
        browser = await _get_browser()
        if browser.pages:
            page = browser.pages[-1]
            await page.screenshot(path=path)
            logger.info(f"Скриншот сохранен в: {path}")
            return f"Скриншот сохранен в: {path}"
        return "Нет открытых страниц для скриншота"
    except Exception as e:
        logger.error(f"Ошибка при создании скриншота: {e}")
        return f"Ошибка: {e}"