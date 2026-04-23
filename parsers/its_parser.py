"""
Парсер документации с портала ИТС 1С (its.1c.ru).
Требуется подписка и учётные данные.
"""

import os
import logging
import time
import json
from typing import List, Dict, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация
ITS_BASE_URL = "https://its.1c.ru"
ITS_LOGIN_URL = urljoin(ITS_BASE_URL, "/login")
ITS_DOCS_URL = urljoin(ITS_BASE_URL, "/docs")

# Переменные окружения
ITS_USERNAME = os.getenv("ITS_USERNAME")
ITS_PASSWORD = os.getenv("ITS_PASSWORD")


class ITSParser:
    """Парсер портала ИТС 1С."""
    
    def __init__(self, headless: bool = True):
        """
        Инициализация парсера.
        
        Args:
            headless: Запуск браузера в фоновом режиме (без GUI).
        """
        self.headless = headless
        self.driver = None
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        self.is_authenticated = False
        
    def init_driver(self):
        """Инициализация Selenium WebDriver с использованием webdriver-manager."""
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
        
        options = Options()
        if self.headless:
            options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=options)
        self.driver.implicitly_wait(10)
        logger.info("WebDriver инициализирован (webdriver-manager)")
    
    def login(self):
        """
        Аутентификация на портале ИТС 1С.
        Использует Selenium для обработки JavaScript и форм.
        """
        if not ITS_USERNAME or not ITS_PASSWORD:
            logger.error("Не заданы ITS_USERNAME или ITS_PASSWORD в переменных окружения")
            return False
        
        if not self.driver:
            self.init_driver()
        
        try:
            logger.info(f"Открываю страницу входа: {ITS_LOGIN_URL}")
            self.driver.get(ITS_LOGIN_URL)
            
            # Ждём появления формы входа
            wait = WebDriverWait(self.driver, 20)
            username_field = wait.until(
                EC.presence_of_element_located((By.NAME, "username"))
            )
            password_field = self.driver.find_element(By.NAME, "password")
            submit_button = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            
            # Вводим учётные данные
            username_field.send_keys(ITS_USERNAME)
            password_field.send_keys(ITS_PASSWORD)
            submit_button.click()
            
            # Ждём перехода на главную страницу
            time.sleep(5)
            
            # Проверяем успешность входа
            if "login" not in self.driver.current_url.lower():
                logger.info("Успешная аутентификация на ИТС 1С")
                self.is_authenticated = True
                
                # Сохраняем cookies для requests сессии
                cookies = self.driver.get_cookies()
                for cookie in cookies:
                    self.session.cookies.set(cookie['name'], cookie['value'])
                
                return True
            else:
                logger.error("Не удалось войти: возможно неверные учётные данные")
                return False
                
        except TimeoutException:
            logger.error("Таймаут при ожидании элементов входа")
            return False
        except Exception as e:
            logger.error(f"Ошибка при аутентификации: {e}")
            return False
    
    def get_page(self, url: str) -> Optional[str]:
        """
        Загружает страницу через requests (если аутентифицированы) или через Selenium.
        
        Args:
            url: URL страницы.
            
        Returns:
            HTML содержимое страницы или None в случае ошибки.
        """
        if self.is_authenticated:
            try:
                response = self.session.get(url, timeout=30)
                response.raise_for_status()
                return response.text
            except requests.RequestException as e:
                logger.warning(f"Ошибка requests для {url}: {e}. Пробуем через Selenium.")
        
        # Если не аутентифицированы или requests не сработал, используем Selenium
        if not self.driver:
            self.init_driver()
        
        try:
            self.driver.get(url)
            time.sleep(3)  # Ждём загрузки JavaScript
            return self.driver.page_source
        except Exception as e:
            logger.error(f"Ошибка Selenium для {url}: {e}")
            return None
    
    def parse_documentation_section(self, section_url: str) -> List[Dict]:
        """
        Парсит раздел документации.
        
        Args:
            section_url: URL раздела.
            
        Returns:
            Список документов с заголовком, текстом и метаданными.
        """
        html = self.get_page(section_url)
        if not html:
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        documents = []
        
        # Пример: находим все ссылки на статьи
        article_links = soup.select('a.article-link')  # Нужно уточнить селектор
        
        for link in article_links[:5]:  # Ограничимся 5 статьями для теста
            article_url = urljoin(ITS_BASE_URL, link.get('href'))
            article_title = link.get_text(strip=True)
            
            logger.info(f"Парсим статью: {article_title}")
            article_html = self.get_page(article_url)
            if not article_html:
                continue
            
            article_soup = BeautifulSoup(article_html, 'html.parser')
            # Извлекаем основной текст (нужно уточнить селектор)
            content_div = article_soup.select_one('.article-content')
            if not content_div:
                content_div = article_soup.select_one('main')
            
            article_text = content_div.get_text(strip=True) if content_div else ""
            
            documents.append({
                'title': article_title,
                'url': article_url,
                'text': article_text,
                'source': 'its_1c',
                'section': section_url
            })
        
        logger.info(f"Найдено {len(documents)} документов в разделе {section_url}")
        return documents
    
    def get_main_sections(self) -> List[Dict]:
        """
        Получает список основных разделов документации.
        
        Returns:
            Список разделов с названием и URL.
        """
        html = self.get_page(ITS_DOCS_URL)
        if not html:
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        sections = []
        
        # Пример: находим меню разделов (нужно уточнить селектор)
        menu_items = soup.select('nav.main-menu a')
        
        for item in menu_items:
            title = item.get_text(strip=True)
            href = item.get('href')
            if href and '/docs/' in href:
                full_url = urljoin(ITS_BASE_URL, href)
                sections.append({
                    'title': title,
                    'url': full_url
                })
        
        logger.info(f"Найдено {len(sections)} разделов документации")
        return sections
    
    def parse_all_documentation(self, limit_sections: int = 3) -> List[Dict]:
        """
        Парсит все разделы документации.
        
        Args:
            limit_sections: Ограничение количества разделов (для теста).
            
        Returns:
            Список всех документов.
        """
        if not self.is_authenticated:
            logger.info("Пытаемся аутентифицироваться...")
            if not self.login():
                logger.error("Не удалось аутентифицироваться")
                return []
        
        sections = self.get_main_sections()
        if not sections:
            logger.warning("Не удалось получить разделы документации")
            return []
        
        all_documents = []
        for i, section in enumerate(sections[:limit_sections]):
            logger.info(f"Обрабатываем раздел {i+1}/{len(sections[:limit_sections])}: {section['title']}")
            documents = self.parse_documentation_section(section['url'])
            all_documents.extend(documents)
            time.sleep(2)  # Пауза между разделами
        
        logger.info(f"Всего собрано {len(all_documents)} документов")
        return all_documents
    
    def save_to_json(self, documents: List[Dict], filename: str = "its_documents.json"):
        """Сохраняет документы в JSON файл."""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(documents, f, ensure_ascii=False, indent=2)
        logger.info(f"Документы сохранены в {filename}")
    
    def close(self):
        """Закрывает WebDriver."""
        if self.driver:
            self.driver.quit()
            logger.info("WebDriver закрыт")


def index_to_memory(documents: List[Dict]):
    """
    Индексирует документы в векторную память.
    
    Args:
        documents: Список документов.
    """
    try:
        from memory.qdrant_memory import memory
    except ImportError:
        logger.error("Модуль памяти не доступен")
        return
    
    for doc in documents:
        try:
            memory.store(
                text=doc['text'],
                metadata={
                    'title': doc['title'],
                    'url': doc['url'],
                    'source': 'its_1c',
                    'section': doc.get('section', ''),
                    'type': 'documentation'
                }
            )
        except Exception as e:
            logger.error(f"Ошибка индексации документа {doc['title']}: {e}")
    
    logger.info(f"Проиндексировано {len(documents)} документов в память")


def main():
    """Основная функция для тестирования парсера."""
    parser = ITSParser(headless=True)
    
    try:
        # Парсим документацию (ограничимся 2 разделами для теста)
        documents = parser.parse_all_documentation(limit_sections=2)
        
        if documents:
            # Сохраняем в JSON
            parser.save_to_json(documents)
            
            # Индексируем в память
            index_to_memory(documents)
            
            print(f"Успешно собрано {len(documents)} документов")
        else:
            print("Не удалось собрать документы")
    
    except Exception as e:
        logger.error(f"Ошибка в main: {e}")
    
    finally:
        parser.close()


if __name__ == "__main__":
    main()