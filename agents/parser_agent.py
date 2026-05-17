"""
Агент-парсер (Интегратор данных) для обработки документов, данных и сайтов.
Работает в диалоговом режиме и по расписанию (фоновые задачи).
Оркестрирует работу коллекторов: 1С, ИТС, ukorona.ru и других.
"""

import json
import logging
import os
import sys
import threading
import time
import hashlib
import re
import gc
import sqlite3
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Generator, Tuple

from agents.base import BaseAgent
from core.roles import AgentRole, get_system_prompt

try:
    from memory.qdrant_memory import memory as _memory
    MEMORY_AVAILABLE = True
except ImportError:
    MEMORY_AVAILABLE = False
    _memory = None

logger = logging.getLogger(__name__)

# Файл для хранения списка сайтов поставщиков
SUPPLIER_SITES_FILE = os.path.join("data", "supplier_sites.json")
# Файл для хранения результатов парсинга
PARSING_LOG_FILE = os.path.join("data", "parsing_log.json")

# Блокировка для фонового планировщика
_SCHEDULER_LOCK = threading.Lock()


class ParserAgent(BaseAgent):
    """Агент для парсинга документов, данных и сайтов поставщиков."""

    role = AgentRole.PARSER
    display_name = "Парсер (Интегратор данных)"
    description = "Парсит ИТС 1С, выгружает данные из 1С, парсит ukorona.ru и сайты поставщиков"
    tools = [
        "collect_1c", "build_its_sitemap", "parse_its", "parse_ukorona",
        "parse_all", "parse_supplier_sites", "add_source", "remove_source", "list_sources"
    ]

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("zora.agent.parser")
        self.current_task = None
        self.parsing_results = []
        self._background_thread = None
        self._running = False
        self._ensure_data_files()

        # ===== Единый механизм отслеживания прогресса =====
        self.current_operation = None       # "collect_1c", "parse_its", "parse_ukorona", "index_files"
        self.operation_name = ""            # "Выгрузка 1С", "Парсинг ИТС", ...
        self.total_steps = 0                # 0, если неизвестно
        self.current_step = 0
        self.total_indexed = 0
        self.current_subject = ""           # текущая обрабатываемая сущность/файл
        self.status_message = ""            # "Активна", "Остановлена", "Завершена (0 записей)"
        self._operation_lock = threading.Lock()
        self._operation_start_time = None

    def start_operation(self, operation: str, name: str = "", total_steps: int = 0):
        """Начинает новую операцию, сбрасывая прогресс."""
        with self._operation_lock:
            self.current_operation = operation
            self.operation_name = name or operation
            self.total_steps = total_steps
            self.current_step = 0
            self.total_indexed = 0
            self.current_subject = ""
            self.status_message = "Активна"
            self._operation_start_time = time.time()
            self.current_task = name or operation
        self.logger.info(f"▶ Начало операции: {self.operation_name} (шагов: {total_steps or 'неизвестно'})")

    def update_progress(self, step_increment: int = 0, indexed_increment: int = 0,
                        subject: str = "", total_steps: int = None):
        """Обновляет прогресс текущей операции."""
        with self._operation_lock:
            if total_steps is not None:
                self.total_steps = total_steps
            if step_increment > 0:
                self.current_step += step_increment
            if indexed_increment > 0:
                self.total_indexed += indexed_increment
            if subject:
                self.current_subject = subject
            self.status_message = "Активна"

    def finish_operation(self, success: bool, message: str = ""):
        """Завершает текущую операцию."""
        with self._operation_lock:
            elapsed = time.time() - self._operation_start_time if self._operation_start_time else 0
            self.status_message = message or ("✅ Завершена" if success else "❌ Ошибка")
            self.current_subject = ""
            self.current_task = None
            self._operation_start_time = None
            if not success:
                self.logger.error(f"⛔ Операция {self.operation_name} завершилась ошибкой: {message}")
            else:
                self.logger.info(f"✅ Операция {self.operation_name} завершена за {elapsed:.1f}с: {message}")

    def get_progress(self) -> Dict[str, Any]:
        """Возвращает текущий прогресс операции."""
        with self._operation_lock:
            if self.current_operation is None:
                return {
                    "running": False,
                    "operation_name": "",
                    "total_steps": 0,
                    "current_step": 0,
                    "total_indexed": self.total_indexed,
                    "current_subject": "",
                    "status_message": self.status_message or "Не активна"
                }
            return {
                "running": True,
                "operation": self.current_operation,
                "operation_name": self.operation_name,
                "total_steps": self.total_steps,
                "current_step": self.current_step,
                "total_indexed": self.total_indexed,
                "current_subject": self.current_subject,
                "status_message": self.status_message
            }

    def _ensure_data_files(self):
        """Создаёт файлы данных, если их нет."""
        os.makedirs("data", exist_ok=True)
        if not os.path.exists(SUPPLIER_SITES_FILE):
            with open(SUPPLIER_SITES_FILE, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)
        if not os.path.exists(PARSING_LOG_FILE):
            with open(PARSING_LOG_FILE, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)

    # ======================================================================
    # Проверка зависимостей
    # ======================================================================

    def _check_parsing_dependencies(self) -> bool:
        """Проверяет наличие необходимых библиотек для парсинга."""
        try:
            import requests  # noqa: F401
            from bs4 import BeautifulSoup  # noqa: F401
            return True
        except ImportError as e:
            self.logger.error(f"Отсутствуют зависимости для парсинга: {e}")
            return False

    # ======================================================================
    # Управление источниками
    # ======================================================================

    def add_source(self, url: str, name: str = "", schedule: str = "daily") -> Dict[str, Any]:
        """
        Добавляет URL в список источников для парсинга.

        Args:
            url: URL сайта поставщика
            name: Название источника
            schedule: Частота парсинга ("daily", "weekly", "once")

        Returns:
            Результат операции
        """
        self.logger.info(f"Добавление источника: {url} ({name})")
        try:
            sources = self._load_sources()
            for s in sources:
                if s["url"] == url:
                    return {
                        "success": False,
                        "message": f"Источник {url} уже существует",
                        "source": s
                    }

            source = {
                "url": url,
                "name": name or url,
                "schedule": schedule,
                "added": datetime.now().isoformat(),
                "last_parsed": None,
                "status": "active"
            }
            sources.append(source)
            self._save_sources(sources)
            self.logger.info(f"✅ Источник добавлен: {url}")
            return {
                "success": True,
                "message": f"✅ Источник «{name or url}» добавлен. Расписание: {schedule}",
                "source": source
            }
        except Exception as e:
            self.logger.error(f"Ошибка добавления источника: {e}")
            return {"success": False, "message": f"Ошибка: {str(e)}"}

    def remove_source(self, url: str) -> Dict[str, Any]:
        """Удаляет URL из списка источников."""
        self.logger.info(f"Удаление источника: {url}")
        try:
            sources = self._load_sources()
            filtered = [s for s in sources if s["url"] != url]
            if len(filtered) == len(sources):
                return {"success": False, "message": f"Источник {url} не найден"}
            self._save_sources(filtered)
            return {"success": True, "message": f"✅ Источник {url} удалён"}
        except Exception as e:
            self.logger.error(f"Ошибка удаления источника: {e}")
            return {"success": False, "message": f"Ошибка: {str(e)}"}

    def list_sources(self) -> Dict[str, Any]:
        """Возвращает список всех источников."""
        try:
            sources = self._load_sources()
            if not sources:
                return {"success": True, "sources": [], "message": "Нет добавленных источников"}
            return {"success": True, "sources": sources, "count": len(sources)}
        except Exception as e:
            self.logger.error(f"Ошибка получения списка источников: {e}")
            return {"success": False, "message": f"Ошибка: {str(e)}", "sources": []}

    def _load_sources(self) -> List[Dict]:
        """Загружает список источников из файла."""
        try:
            if os.path.exists(SUPPLIER_SITES_FILE):
                with open(SUPPLIER_SITES_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            self.logger.error(f"Ошибка загрузки источников: {e}")
        return []

    def _save_sources(self, sources: List[Dict]):
        """Сохраняет список источников в файл."""
        with open(SUPPLIER_SITES_FILE, "w", encoding="utf-8") as f:
            json.dump(sources, f, ensure_ascii=False, indent=2)

    # ======================================================================
    # Коллектор 1С (универсальный)
    # ======================================================================

    def collect_1c(self, types: Optional[List[str]] = None, limit: int = 10,
                   mode: str = "incremental", entity_filter: Optional[str] = None) -> Dict[str, Any]:
        """
        Собирает данные из 1С через универсальный коллектор.

        Args:
            types: (устаревший параметр, игнорируется) Оставлен для обратной совместимости
            limit: (устаревший параметр, игнорируется)
            mode: "incremental" (по умолчанию) или "full"
            entity_filter: Если указано, обрабатывается только одна сущность (для отладки)

        Returns:
            Результат сбора данных.
        """
        mode_label = "полный" if mode == "full" else "инкрементальный"
        self.start_operation("collect_1c", f"Выгрузка 1С ({mode_label})")
        self.logger.info(f"Запуск {mode_label} сбора данных из 1С")

        try:
            from collectors.onec_collector_universal import OneCUniversalCollector
            collector = OneCUniversalCollector(progress_callback=self.update_progress)
            result = collector.run(mode=mode, entity_filter=entity_filter)
            items = result.get('items_processed', 0)
            indexed = result.get('items_indexed', 0)
            if items == 0:
                self.finish_operation(True, "Нет новых данных для индексации")
            else:
                self.finish_operation(True, f"Индексировано {indexed} записей")
            return self._log_result("1c", result.get("success", False),
                f"1С ({mode_label}): обработано {items} записей, "
                f"проиндексировано {indexed}, "
                f"сущностей: {result.get('entities_processed', 0)}",
                data=result)
        except ImportError as e:
            self.finish_operation(False, f"Модуль коллектора 1С не найден: {e}")
            return self._log_result("1c", False, f"Модуль коллектора 1С не найден: {e}")
        except Exception as e:
            self.logger.error(f"Ошибка сбора 1С: {e}")
            self.finish_operation(False, f"Ошибка: {str(e)}")
            return self._log_result("1c", False, f"Ошибка: {str(e)}")

    # ======================================================================
    # Коллектор ИТС
    # ======================================================================

    def build_its_sitemap(self) -> Dict[str, Any]:
        """Строит карту сайта ИТС 1С."""
        self.current_task = "Построение карты ИТС"
        self.logger.info("Запуск построения карты ИТС")

        try:
            from collectors.its_collector import ITSCollector
            collector = ITSCollector()
            result = collector._build_sitemap()
            return self._log_result("its_sitemap", result.get("success", False),
                f"Карта ИТС: {result.get('articles', 0)} статей",
                data=result)
        except ImportError as e:
            return self._log_result("its_sitemap", False, f"Модуль ITSCollector не найден: {e}")
        except Exception as e:
            self.logger.error(f"Ошибка построения карты ИТС: {e}")
            return self._log_result("its_sitemap", False, f"Ошибка: {str(e)}")

    def parse_its(self, sections: Optional[List[str]] = None, limit: Optional[int] = None) -> Dict[str, Any]:
        """
        Парсит статьи ИТС 1С.

        Args:
            sections: Фильтр по разделу ИТС (например ["ka", "buh", "prog", "calendar"])
            limit: Максимальное количество статей

        Returns:
            Результат парсинга.
        """
        self.start_operation("parse_its", "Парсинг ИТС 1С")
        self.logger.info("Запуск парсинга ИТС")

        try:
            from collectors.its_collector import ITSCollector
            collector = ITSCollector()

            # Формируем параметры для коллектора
            params = {}
            if limit is not None:
                params["limit"] = limit
            if sections and len(sections) > 0:
                params["section"] = sections[0]  # берём первый раздел

            # Запускаем асинхронный run коллектора в синхронном контексте
            result = asyncio.run(collector.run(params=params))

            articles = result.get("items_processed", 0)
            chunks = result.get("chunks_added", 0)
            success = result.get("success", False)

            self.finish_operation(success, f"Обработано {articles} статей, {chunks} чанков")
            return self._log_result("its", success,
                f"ИТС: обработано {articles} статей, "
                f"проиндексировано {chunks} чанков",
                data=result)
        except ImportError as e:
            self.finish_operation(False, f"Модуль не найден: {e}")
            return self._log_result("its", False, f"Модуль ITSCollector не найден: {e}")
        except Exception as e:
            self.logger.error(f"Ошибка парсинга ИТС: {e}")
            self.finish_operation(False, f"Ошибка: {str(e)}")
            return self._log_result("its", False, f"Ошибка: {str(e)}")

    # ======================================================================
    # Коллектор Ukorona (переработан)
    # ======================================================================

    def parse_ukorona(self, limit: Optional[int] = None) -> Dict[str, Any]:
        """
        Парсит сайт ukorona.ru с использованием нового UkoronaCollector.

        Args:
            limit: Максимальное количество страниц

        Returns:
            Результат парсинга.
        """
        self.start_operation("parse_ukorona", "Парсинг ukorona.ru")
        self.logger.info("Запуск парсинга ukorona.ru")

        try:
            from collectors.ukorona_collector import UkoronaCollector
            collector = UkoronaCollector(config={})

            # Запускаем асинхронный run коллектора в синхронном контексте
            result = asyncio.run(collector.run(params={"limit": limit}))

            pages = result.get("items_processed", 0)
            items = result.get("chunks_added", 0)
            success = result.get("success", False)

            self.finish_operation(success, f"Обработано {pages} страниц, {items} записей")
            return self._log_result("ukorona", success,
                f"Ukorona: обработано {pages} страниц, "
                f"проиндексировано {items} записей",
                data=result)
        except ImportError as e:
            self.finish_operation(False, f"Модуль UkoronaCollector не найден: {e}")
            return self._log_result("ukorona", False, f"Модуль UkoronaCollector не найден: {e}")
        except Exception as e:
            self.logger.error(f"Ошибка парсинга ukorona: {e}")
            self.finish_operation(False, f"Ошибка: {str(e)}")
            return self._log_result("ukorona", False, f"Ошибка: {str(e)}")

    # ======================================================================
    # Парсинг сайтов поставщиков
    # ======================================================================

    def _deduplicate_texts(self, texts: List[str]) -> List[str]:
        """Удаляет дубликаты текстов."""
        seen = set()
        unique = []
        for text in texts:
            text_hash = hashlib.md5(text.encode()).hexdigest()
            if text_hash not in seen:
                seen.add(text_hash)
                unique.append(text)
        return unique

    def _extract_text_from_page(self, soup) -> List[str]:
        """Извлекает основной текст из страницы, исключая навигационные элементы."""
        texts = []

        # Удаляем навигационные элементы
        for nav in soup.find_all(["nav", "header", "footer", "aside", "script", "style"]):
            nav.decompose()

        # Ищем основной контент
        content_selectors = ["main", "article", ".content", "#content", ".product-content", ".catalog-content"]
        main_content = None
        for selector in content_selectors:
            main_content = soup.select_one(selector)
            if main_content:
                break

        if not main_content:
            main_content = soup.body

        if main_content:
            for tag in main_content.find_all(["p", "h1", "h2", "h3", "li"]):
                text = tag.get_text(strip=True)
                if len(text) > 50:
                    texts.append(text[:1000])

        return texts

    def parse_supplier_sites(self, source_url: str = None) -> Dict[str, Any]:
        """
        Парсит сайты поставщиков из списка источников.

        Args:
            source_url: Конкретный URL для парсинга (если None, парсит все активные)

        Returns:
            Результаты парсинга.
        """
        # Проверяем зависимости
        if not self._check_parsing_dependencies():
            return self._log_result("supplier", False,
                "❌ Не установлены зависимости: requests и/или beautifulsoup4. "
                "Выполните: pip install requests beautifulsoup4")

        self.start_operation("parse_supplier", "Парсинг сайтов поставщиков")
        self.logger.info(f"Запуск парсинга сайтов поставщиков")

        try:
            import requests
            from bs4 import BeautifulSoup

            sources = self._load_sources()
            if source_url:
                sources = [s for s in sources if s["url"] == source_url]

            if not sources:
                return self._log_result("supplier", False,
                    "Нет источников для парсинга. Добавьте сайты через команду.")

            total_parsed = 0
            total_indexed = 0
            total_errors = 0
            results = []

            for source in sources:
                if source.get("status") != "active":
                    self.logger.info(f"Пропуск неактивного источника: {source['url']}")
                    continue

                self.logger.info(f"Парсинг источника: {source['url']}")

                try:
                    response = requests.get(source["url"], timeout=30, headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    })

                    if response.status_code != 200:
                        results.append({
                            "url": source["url"],
                            "success": False,
                            "error": f"HTTP {response.status_code}"
                        })
                        total_errors += 1
                        continue

                    soup = BeautifulSoup(response.text, "html.parser")
                    texts = self._extract_text_from_page(soup)
                    unique_texts = self._deduplicate_texts(texts)

                    indexed = 0
                    if MEMORY_AVAILABLE and _memory:
                        for text in unique_texts[:100]:
                            try:
                                _memory.store(
                                    text=text,
                                    metadata={
                                        "type": "product",
                                        "source": source["url"],
                                        "source_name": source["name"],
                                        "timestamp": datetime.now().isoformat()
                                    }
                                )
                                indexed += 1
                            except Exception as e:
                                self.logger.warning(f"Ошибка индексации: {e}")

                    source["last_parsed"] = datetime.now().isoformat()
                    total_parsed += 1
                    total_indexed += indexed
                    results.append({
                        "url": source["url"],
                        "success": True,
                        "indexed": indexed,
                        "texts_found": len(unique_texts)
                    })

                except requests.exceptions.Timeout:
                    error_msg = f"Таймаут при загрузке {source['url']}"
                    self.logger.error(error_msg)
                    results.append({"url": source["url"], "success": False, "error": error_msg})
                    total_errors += 1
                except Exception as e:
                    error_msg = f"Ошибка парсинга {source['url']}: {str(e)}"
                    self.logger.error(error_msg)
                    results.append({"url": source["url"], "success": False, "error": str(e)})
                    total_errors += 1

            self._save_sources(sources)

            self.finish_operation(total_parsed > 0,
                f"Обработано: {total_parsed} сайтов, проиндексировано: {total_indexed} записей, ошибок: {total_errors}")
            return self._log_result("supplier", total_parsed > 0,
                f"Парсинг завершён. Обработано: {total_parsed} сайтов, "
                f"проиндексировано: {total_indexed} записей, ошибок: {total_errors}",
                data={"parsed": total_parsed, "indexed": total_indexed, "errors": total_errors, "details": results})

        except Exception as e:
            self.logger.error(f"Ошибка парсинга сайтов: {e}")
            self.finish_operation(False, f"Ошибка: {str(e)}")
            return self._log_result("supplier", False, f"Ошибка: {str(e)}")

    # ======================================================================
    # Запуск всех коллекторов
    # ======================================================================

    def parse_all(self) -> Dict[str, Any]:
        """Запускает все коллекторы последовательно."""
        self.current_task = "Полный сбор данных"
        self.logger.info("Запуск полного сбора данных")

        results = []

        # 1. 1С
        r1 = self.collect_1c()
        results.append(("1С", r1))

        # 2. ИТС
        r2 = self.parse_its()
        results.append(("ИТС", r2))

        # 3. Ukorona
        r3 = self.parse_ukorona()
        results.append(("Ukorona", r3))

        # 4. Сайты поставщиков
        r4 = self.parse_supplier_sites()
        results.append(("Поставщики", r4))

        summary = "\n".join([
            f"  {'✅' if r['success'] else '❌'} {name}: {r['message']}"
            for name, r in results
        ])

        return {
            "success": True,
            "message": f"📊 **Результаты полного сбора данных:**\n\n{summary}",
            "data": {name: r for name, r in results}
        }

    # ======================================================================
    # Фоновые задачи по расписанию
    # ======================================================================

    def _run_task_safe(self, task_func, task_name: str, *args, **kwargs):
        """Безопасно выполняет задачу с таймаутом."""
        try:
            self.logger.info(f"▶ Задача {task_name} запущена")
            result = task_func(*args, **kwargs)
            self.logger.info(f"✅ Задача {task_name} завершена")
            return result
        except Exception as e:
            self.logger.error(f"❌ Ошибка в задаче {task_name}: {e}")
            return {"success": False, "error": str(e), "message": f"Ошибка: {str(e)}"}

    def run_scheduled_tasks(self) -> List[Dict]:
        """Запускает все запланированные задачи строго последовательно.
        Каждая задача сама управляет прогрессом через start_operation/finish_operation.
        """
        self.logger.info(">>> Запуск запланированных задач парсера")
        results = []

        tasks = [
            (self.collect_1c, "1C", {"mode": "incremental"}),
            (self.parse_its, "ИТС", {"limit": 10}),
            (self.parse_ukorona, "Ukorona", {"limit": None}),
            (self.parse_supplier_sites, "Поставщики", {}),
            (self.index_project, "Индексация проекта", {"incremental": True})
        ]

        for task_func, task_name, kwargs in tasks:
            self.logger.info(f"▶ Задача {task_name} запущена")
            try:
                result = self._run_task_safe(task_func, task_name, **kwargs)
                results.append(result)
                self.logger.info(f"📊 Задача {task_name}: {result.get('message', 'OK')[:100]}")
            except Exception as e:
                self.logger.error(f"❌ Ошибка в задаче {task_name}: {e}")
                results.append({"success": False, "message": f"Ошибка: {e}"})

        self.logger.info(f"✅ Запланированные задачи завершены: {len(results)} задач")
        return results

    def start_background_scheduler(self, interval_hours: int = 6):
        """Запускает фоновый планировщик в отдельном потоке.
        Задачи выполняются последовательно, одна за другой.
        Первый запуск происходит только после ожидания интервала.
        """
        with _SCHEDULER_LOCK:
            if self._running:
                self.logger.warning("Фоновый планировщик уже запущен")
                return
            if self._background_thread and self._background_thread.is_alive():
                self.logger.warning("Фоновый планировщик уже запущен (поток жив)")
                return

            self._running = True

            def _scheduler_loop():
                self.logger.info(f"🔄 Фоновый планировщик запущен (интервал: {interval_hours}ч)")
                # Ждём первый интервал перед запуском задач
                for _ in range(interval_hours * 60):
                    if not self._running:
                        return
                    time.sleep(60)
                # Теперь запускаем задачи циклически
                while self._running:
                    try:
                        self.run_scheduled_tasks()
                    except Exception as e:
                        self.logger.error(f"Ошибка в фоновом планировщике: {e}")
                    # Ждём следующий интервал
                    for _ in range(interval_hours * 60):
                        if not self._running:
                            return
                        time.sleep(60)

            self._background_thread = threading.Thread(target=_scheduler_loop, daemon=True)
            self._background_thread.start()
            self.logger.info(f"✅ Фоновый планировщик запущен в потоке {self._background_thread.name}")

    def run_all_once(self):
        """Запускает все задачи немедленно, последовательно, с отслеживанием прогресса.
        Вызывается при нажатии кнопки «Запустить парсер» в дашборде.
        """
        self.logger.info(">>> Запуск всех задач парсера (run_all_once)")
        self.run_scheduled_tasks()
        self.logger.info("✅ Все задачи парсера завершены (run_all_once)")

    def stop_background_scheduler(self):
        """Останавливает фоновый планировщик."""
        self._running = False
        if self._background_thread:
            self._background_thread.join(timeout=5)
        self.logger.info("⏹️ Фоновый планировщик остановлен")

    # ======================================================================
    # Вспомогательные методы
    # ======================================================================

    def _log_result(self, task_type: str, success: bool, message: str, data: Dict = None) -> Dict[str, Any]:
        """Логирует результат парсинга и возвращает словарь."""
        result = {
            "success": success,
            "message": message,
            "task": self.current_task,
            "agent": self.agent_name
        }
        if data:
            result["data"] = data

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "type": task_type,
            "success": success,
            "message": message[:500] if message else ""
        }
        if data and "details" in data:
            log_entry["details"] = str(data["details"])[:500]

        self.parsing_results.append(log_entry)

        try:
            log = []
            if os.path.exists(PARSING_LOG_FILE):
                with open(PARSING_LOG_FILE, "r", encoding="utf-8") as f:
                    log = json.load(f)
            log.append(log_entry)
            if len(log) > 100:
                log = log[-100:]
            with open(PARSING_LOG_FILE, "w", encoding="utf-8") as f:
                json.dump(log, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.warning(f"Ошибка сохранения лога: {e}")

        self.current_task = None
        return result

    # ======================================================================
    # ИНДЕКСАЦИЯ ФАЙЛОВ (перенесено из memory/indexer.py)
    # ======================================================================

    # Расширения файлов по типам
    FILE_TYPES = {
        'code': {'.py', '.js', '.ts', '.go', '.java', '.cpp', '.h', '.hpp', '.cs', '.php', '.rb', '.rs', '.swift', '.kt', '.scala', '.sql'},
        'document': {'.md', '.txt', '.rst', '.tex', '.org', '.wiki', '.adoc'},
        'config': {'.json', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf', '.xml', '.env'},
        'web': {'.html', '.htm', '.css', '.scss', '.less', '.jsx', '.tsx', '.vue'},
        'data': {'.csv', '.tsv', '.xlsx', '.xls', '.ods'},
    }

    BINARY_FORMATS = {
        '.pdf': 'pypdf',
        '.docx': 'docx',
        '.doc': 'docx',
        '.pptx': 'python-pptx',
        '.ppt': 'python-pptx',
    }

    HASH_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "memory", "file_hashes.db")

    class FileHashDB:
        """Управление хэшами файлов в SQLite для инкрементальной индексации."""

        def __init__(self, db_path: str = None):
            self.db_path = db_path or ParserAgent.HASH_DB_PATH
            self._init_db()

        def _init_db(self):
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS file_hashes (
                    path TEXT PRIMARY KEY,
                    hash TEXT NOT NULL,
                    mtime REAL NOT NULL,
                    size INTEGER NOT NULL,
                    indexed_at REAL NOT NULL
                )
            """)
            conn.commit()
            conn.close()

        def get_file_hash(self, filepath: str) -> Optional[Tuple[str, float, int]]:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT hash, mtime, size FROM file_hashes WHERE path = ?", (filepath,))
            row = cursor.fetchone()
            conn.close()
            if row:
                return row[0], row[1], row[2]
            return None

        def update_file_hash(self, filepath: str, hash_val: str, mtime: float, size: int):
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO file_hashes (path, hash, mtime, size, indexed_at)
                VALUES (?, ?, ?, ?, ?)
            """, (filepath, hash_val, mtime, size, time.time()))
            conn.commit()
            conn.close()

        def delete_file_hash(self, filepath: str):
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM file_hashes WHERE path = ?", (filepath,))
            conn.commit()
            conn.close()

        def clear(self):
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM file_hashes")
            conn.commit()
            conn.close()

    @staticmethod
    def calculate_file_hash(filepath: str) -> str:
        try:
            with open(filepath, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        except Exception as e:
            logger.warning(f"Не удалось вычислить хэш файла {filepath}: {e}")
            return ""

    @staticmethod
    def should_reindex(filepath: str, hash_db=None, force: bool = False, clean: bool = False) -> Tuple[bool, str]:
        if force or clean:
            return True, "force или clean режим"
        if not os.path.exists(filepath):
            return False, "файл не существует"
        if hash_db is None:
            return True, "нет БД хэшей"
        try:
            current_mtime = os.path.getmtime(filepath)
            current_size = os.path.getsize(filepath)
            current_hash = ParserAgent.calculate_file_hash(filepath)
            if not current_hash:
                return True, "не удалось вычислить хэш"
        except Exception as e:
            logger.warning(f"Ошибка получения атрибутов файла {filepath}: {e}")
            return True, "ошибка атрибутов"
        stored = hash_db.get_file_hash(filepath)
        if stored is None:
            return True, "файл ещё не индексирован"
        stored_hash, stored_mtime, stored_size = stored
        if current_hash != stored_hash:
            return True, "хэш изменился"
        if abs(current_mtime - stored_mtime) > 1:
            return True, "время модификации изменилось"
        if current_size != stored_size:
            return True, "размер изменился"
        return False, "файл не изменился"

    @staticmethod
    def get_file_type(filepath: str) -> str:
        ext = os.path.splitext(filepath)[1].lower()
        for file_type, extensions in ParserAgent.FILE_TYPES.items():
            if ext in extensions:
                return file_type
        if ext in ParserAgent.BINARY_FORMATS:
            return 'document'
        return 'unknown'

    @staticmethod
    def read_text_file(filepath: str) -> Optional[str]:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        except UnicodeDecodeError:
            try:
                with open(filepath, 'r', encoding='utf-16') as f:
                    return f.read()
            except UnicodeDecodeError:
                try:
                    with open(filepath, 'r', encoding='utf-16-le') as f:
                        return f.read()
                except UnicodeDecodeError:
                    try:
                        with open(filepath, 'r', encoding='cp1251') as f:
                            return f.read()
                    except UnicodeDecodeError:
                        try:
                            with open(filepath, 'r', encoding='latin-1') as f:
                                return f.read()
                        except:
                            return None
        except Exception as e:
            logger.error(f"Ошибка чтения файла {filepath}: {e}")
            return None

    @staticmethod
    def read_pdf_pages(filepath: str) -> Generator[Optional[str], None, None]:
        import queue as _queue
        def _extract_page_text(page, page_num, result_queue):
            try:
                page_text = page.extract_text()
                if page_text and page_text.strip():
                    result_queue.put((page_num, page_text, None))
                else:
                    result_queue.put((page_num, "", "Пустая страница"))
            except Exception as e:
                result_queue.put((page_num, "", str(e)))
        try:
            import pypdf
            file_size = os.path.getsize(filepath)
            if file_size > 100 * 1024 * 1024:
                logger.warning(f"PDF файл слишком большой ({file_size / 1024 / 1024:.1f} MB): {filepath}")
                yield f"[ВНИМАНИЕ: PDF файл слишком большой ({file_size / 1024 / 1024:.1f} MB)]"
            with open(filepath, 'rb') as f:
                pdf_reader = pypdf.PdfReader(f)
                total_pages = len(pdf_reader.pages)
                if total_pages > 100:
                    logger.warning(f"PDF содержит много страниц ({total_pages}): {filepath}")
                    yield f"[ВНИМАНИЕ: PDF содержит {total_pages} страниц]"
                for page_num, page in enumerate(pdf_reader.pages):
                    result_queue = _queue.Queue()
                    thread = threading.Thread(target=_extract_page_text, args=(page, page_num, result_queue), daemon=True)
                    thread.start()
                    thread.join(timeout=30)
                    if thread.is_alive():
                        logger.warning(f"Таймаут извлечения текста со страницы {page_num + 1} PDF: {filepath}")
                        yield f"[ПРЕРВАНО: таймаут страницы {page_num + 1}]"
                        continue
                    try:
                        result_page_num, page_text, error = result_queue.get(timeout=5)
                        if error:
                            if "Пустая страница" not in error:
                                logger.warning(f"Ошибка извлечения текста со страницы {page_num + 1}: {error}")
                            continue
                        if page_text:
                            yield page_text
                    except _queue.Empty:
                        logger.warning(f"Таймаут получения результата со страницы {page_num + 1} PDF: {filepath}")
                        continue
                    except Exception as e:
                        logger.warning(f"Ошибка обработки страницы {page_num + 1} PDF: {e}")
                        continue
        except ImportError:
            logger.warning(f"Библиотека pypdf не установлена. Пропускаем PDF: {filepath}")
            yield None
        except Exception as e:
            logger.error(f"Ошибка чтения PDF {filepath}: {e}")
            yield None

    @staticmethod
    def read_docx_paragraphs(filepath: str) -> Generator[Optional[str], None, None]:
        try:
            import docx
            doc = docx.Document(filepath)
            for para in doc.paragraphs:
                if para.text.strip():
                    yield para.text
        except ImportError:
            logger.warning(f"Библиотека python-docx не установлена. Пропускаем DOCX: {filepath}")
            yield None
        except Exception as e:
            logger.error(f"Ошибка чтения DOCX {filepath}: {e}")
            yield None

    @staticmethod
    def read_file_content(filepath: str) -> Optional[str]:
        ext = os.path.splitext(filepath)[1].lower()
        if ext == '.pdf':
            pages = []
            for page_text in ParserAgent.read_pdf_pages(filepath):
                if page_text:
                    pages.append(page_text)
            return '\n\n'.join(pages) if pages else None
        elif ext in ['.docx', '.doc']:
            paras = []
            for para_text in ParserAgent.read_docx_paragraphs(filepath):
                if para_text:
                    paras.append(para_text)
            return '\n'.join(paras) if paras else None
        else:
            return ParserAgent.read_text_file(filepath)

    @staticmethod
    def split_code_into_chunks(content: str, filepath: str) -> List[str]:
        chunks = []
        current_chunk = []
        lines = content.split('\n')
        for line in lines:
            line_stripped = line.strip()
            if (line_stripped.startswith('def ') or
                line_stripped.startswith('class ') or
                line_stripped.startswith('async def ')):
                if current_chunk:
                    chunks.append('\n'.join(current_chunk))
                    current_chunk = []
            current_chunk.append(line)
        if current_chunk:
            chunks.append('\n'.join(current_chunk))
        if len(chunks) <= 1:
            return ParserAgent.split_text_into_chunks(content, max_chunk_size=1500, overlap=100)
        return chunks

    @staticmethod
    def split_text_into_chunks(content: str, max_chunk_size: int = 1500, overlap: int = 200) -> List[str]:
        if not content:
            return []
        chunks = []
        start = 0
        content_length = len(content)
        while start < content_length:
            end = min(start + max_chunk_size, content_length)
            if end < content_length:
                last_space = content.rfind(' ', start, end)
                last_period = content.rfind('.', start, end)
                last_newline = content.rfind('\n', start, end)
                boundary = max(last_newline, last_period, last_space)
                if boundary > start:
                    end = boundary + 1
            chunk = content[start:end].strip()
            if chunk:
                chunks.append(chunk)
            start = end - overlap if end < content_length else end
        return chunks

    @staticmethod
    def enrich_code_chunk(chunk: str, filepath: str) -> str:
        filename = os.path.basename(filepath)
        classes = re.findall(r'class\s+(\w+)', chunk)
        functions = re.findall(r'def\s+(\w+)', chunk)
        prefix = f"[Файл: {filename}]"
        if classes:
            prefix += f" [Классы: {', '.join(classes)}]"
        if functions:
            prefix += f" [Функции: {', '.join(functions)}]"
        return prefix + "\n" + chunk

    @staticmethod
    def delete_file_from_index(filepath: str, memory_client):
        try:
            if hasattr(memory_client, 'delete_by_filter'):
                memory_client.delete_by_filter({"path": filepath})
                logger.info(f"🗑️ Удалены старые данные для файла: {filepath}")
            else:
                if hasattr(memory_client, 'client'):
                    from qdrant_client.http import models
                    filter_condition = models.Filter(
                        must=[models.FieldCondition(key="path", match=models.MatchValue(value=filepath))]
                    )
                    memory_client.client.delete(
                        collection_name=memory_client.collection_name,
                        points_selector=filter_condition
                    )
                    logger.info(f"🗑️ Удалены старые данные для файла: {filepath}")
                else:
                    logger.warning(f"Не могу удалить данные файла {filepath}: нет метода delete_by_filter и нет client")
        except Exception as e:
            logger.error(f"Ошибка удаления данных файла {filepath}: {e}")

    @staticmethod
    def index_file(filepath: str, memory_client, clean: bool = False, max_file_mb: int = 10,
                   hash_db=None, incremental: bool = True, force: bool = False) -> int:
        try:
            file_type = ParserAgent.get_file_type(filepath)
            if file_type == 'unknown':
                logger.debug(f"Пропускаем неизвестный тип файла: {filepath}")
                return 0

            file_size_bytes = os.path.getsize(filepath)
            file_size_mb = file_size_bytes / (1024 * 1024)
            if file_size_mb > max_file_mb:
                logger.warning(f"Файл {filepath} слишком большой ({file_size_mb:.1f} МБ > {max_file_mb} МБ), пропускаем")
                return 0

            need_reindex = True
            reason = "force или clean режим"
            if hash_db and incremental and not force and not clean:
                need_reindex, reason = ParserAgent.should_reindex(filepath, hash_db, force, clean)
                if not need_reindex:
                    logger.debug(f"Пропускаем неизменившийся файл: {filepath} ({reason})")
                    return 0

            if clean or need_reindex:
                ParserAgent.delete_file_from_index(filepath, memory_client)

            ext = os.path.splitext(filepath)[1].lower()
            mtime = os.path.getmtime(filepath)
            chunk_index = 0

            if ext == '.pdf':
                for page_num, page_text in enumerate(ParserAgent.read_pdf_pages(filepath)):
                    if not page_text:
                        continue
                    chunks = ParserAgent.split_text_into_chunks(page_text, max_chunk_size=1500, overlap=150)
                    for chunk in chunks:
                        if not chunk.strip():
                            continue
                        metadata = {
                            "path": filepath, "filename": os.path.basename(filepath),
                            "type": file_type, "mtime": mtime,
                            "chunk": chunk_index, "page": page_num + 1, "indexed_at": time.time()
                        }
                        memory_client.store(chunk, metadata)
                        chunk_index += 1

            elif ext in ['.docx', '.doc']:
                for para_num, para_text in enumerate(ParserAgent.read_docx_paragraphs(filepath)):
                    if not para_text:
                        continue
                    chunks = ParserAgent.split_text_into_chunks(para_text, max_chunk_size=1500, overlap=150)
                    for chunk in chunks:
                        if not chunk.strip():
                            continue
                        metadata = {
                            "path": filepath, "filename": os.path.basename(filepath),
                            "type": file_type, "mtime": mtime,
                            "chunk": chunk_index, "paragraph": para_num + 1, "indexed_at": time.time()
                        }
                        memory_client.store(chunk, metadata)
                        chunk_index += 1

            else:
                content = ParserAgent.read_file_content(filepath)
                if not content or not content.strip():
                    logger.debug(f"Пропускаем пустой файл: {filepath}")
                    return 0
                if file_type == 'code':
                    chunks = ParserAgent.split_code_into_chunks(content, filepath)
                else:
                    chunks = ParserAgent.split_text_into_chunks(content)
                if not chunks:
                    logger.debug(f"Не удалось разбить файл на чанки: {filepath}")
                    return 0
                for i, chunk in enumerate(chunks):
                    if not chunk.strip():
                        continue
                    if file_type == 'code':
                        chunk = ParserAgent.enrich_code_chunk(chunk, filepath)
                    metadata = {
                        "path": filepath, "filename": os.path.basename(filepath),
                        "type": file_type, "mtime": mtime,
                        "chunk": i, "total_chunks": len(chunks), "indexed_at": time.time()
                    }
                    memory_client.store(chunk, metadata)
                    chunk_index += 1

            if chunk_index > 0:
                logger.info(f"✅ Индексирован файл: {filepath} ({chunk_index} чанков, тип: {file_type})")
            else:
                logger.warning(f"⚠️ Файл {filepath} не содержит индексируемого контента")

            if hash_db and incremental and need_reindex:
                current_hash = ParserAgent.calculate_file_hash(filepath)
                if current_hash:
                    hash_db.update_file_hash(filepath, current_hash, mtime, file_size_bytes)

            gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass

            return chunk_index

        except UnicodeDecodeError:
            logger.warning(f"Пропускаем бинарный файл: {filepath}")
            return 0
        except Exception as e:
            logger.error(f"Ошибка индексации файла {filepath}: {e}")
            return 0

    @staticmethod
    def index_directory(path: str, memory_client, recursive: bool = False, clean: bool = False,
                        max_file_mb: int = 10, hash_db=None, incremental: bool = True,
                        force: bool = False) -> Dict[str, Any]:
        path = os.path.abspath(path)
        if not os.path.exists(path):
            logger.error(f"Путь не существует: {path}")
            return {"total_files": 0, "indexed_files": 0, "skipped_files": 0, "errors": 0, "total_chunks": 0}

        if hash_db is None and incremental:
            hash_db = ParserAgent.FileHashDB()
            logger.info("📊 Используется инкрементальная индексация (проверка хэшей)")
        if clean:
            logger.warning("⚠️ Режим --clean: старые данные файлов будут удалены перед индексацией")
        if force:
            logger.warning("⚠️ Режим --force: принудительная переиндексация всех файлов")

        exclude_dirs = {
            'venv', '.git', '__pycache__', '.idea', '.vscode',
            'node_modules', 'dist', 'build', 'coverage', '.pytest_cache',
            '.docker', '.github', '.gitlab'
        }
        include_extensions = set()
        for extensions in ParserAgent.FILE_TYPES.values():
            include_extensions.update(extensions)
        include_extensions.update(ParserAgent.BINARY_FORMATS.keys())

        stats = {'total_files': 0, 'indexed_files': 0, 'skipped_files': 0, 'errors': 0, 'total_chunks': 0}

        if os.path.isfile(path):
            stats['total_files'] = 1
            chunks = ParserAgent.index_file(path, memory_client, clean, max_file_mb, hash_db, incremental, force)
            if chunks > 0:
                stats['indexed_files'] = 1
                stats['total_chunks'] = chunks
            else:
                stats['skipped_files'] = 1
        else:
            for dirpath, dirnames, filenames in os.walk(path):
                if not recursive:
                    dirnames.clear()
                else:
                    dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    ext = os.path.splitext(filename)[1].lower()
                    if ext not in include_extensions:
                        continue
                    stats['total_files'] += 1
                    try:
                        chunks = ParserAgent.index_file(filepath, memory_client, clean, max_file_mb, hash_db, incremental, force)
                        if chunks > 0:
                            stats['indexed_files'] += 1
                            stats['total_chunks'] += chunks
                        else:
                            stats['skipped_files'] += 1
                    except Exception as e:
                        logger.error(f"Ошибка индексации файла {filepath}: {e}")
                        stats['errors'] += 1

        logger.info("📊 ИТОГИ ИНДЕКСАЦИИ:")
        logger.info(f"   Всего файлов: {stats['total_files']}")
        logger.info(f"   Успешно проиндексировано: {stats['indexed_files']}")
        logger.info(f"   Пропущено: {stats['skipped_files']}")
        logger.info(f"   Ошибок: {stats['errors']}")
        logger.info(f"   Всего чанков: {stats['total_chunks']}")
        if stats['indexed_files'] > 0:
            logger.info("✅ Индексация завершена успешно!")
        else:
            logger.warning("⚠️ Не было проиндексировано ни одного файла")

        return stats

    @staticmethod
    def clear_index(memory_client):
        try:
            if hasattr(memory_client, 'clear'):
                memory_client.clear()
                logger.info("✅ Векторная память очищена")
                hash_db = ParserAgent.FileHashDB()
                hash_db.clear()
                logger.info("✅ База хэшей файлов очищена")
            else:
                logger.warning("⚠️ Очистка памяти не поддерживается")
        except Exception as e:
            logger.error(f"❌ Ошибка очистки памяти: {e}")

    # ======================================================================
    # Методы индексации для ParserAgent
    # ======================================================================

    def index_files(self, path: str, recursive: bool = True, clean: bool = False,
                    incremental: bool = True, force: bool = False) -> Dict[str, Any]:
        """Индексирует все файлы по пути (файл или папка)."""
        self.start_operation("index_files", f"Индексация: {os.path.basename(path)}")
        self.logger.info(f"Запуск индексации: {path} (recursive={recursive})")
        try:
            from memory import memory as _mem
            stats = self.index_directory(path, _mem, recursive, clean, max_file_mb=10,
                                         hash_db=self.FileHashDB(), incremental=incremental, force=force)
            self.finish_operation(stats.get("errors") == 0,
                f"Обработано {stats['total_files']} файлов, проиндексировано {stats['indexed_files']}")
            return self._log_result("file_index", stats.get("errors") == 0,
                f"Индексация: обработано {stats['total_files']} файлов, "
                f"проиндексировано {stats['indexed_files']}",
                data=stats)
        except Exception as e:
            self.logger.error(f"Ошибка индексации {path}: {e}")
            self.finish_operation(False, f"Ошибка: {str(e)}")
            return self._log_result("file_index", False, f"Ошибка: {str(e)}")

    def index_project(self, clean: bool = False, incremental: bool = True, force: bool = False) -> Dict[str, Any]:
        """Индексирует весь проект ZORA."""
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return self.index_files(project_root, recursive=True, clean=clean,
                                incremental=incremental, force=force)

    def index_single_file(self, filepath: str, clean: bool = False,
                          incremental: bool = True, force: bool = False) -> Dict[str, Any]:
        """Индексирует один файл."""
        self.start_operation("index_file", f"Индексация файла: {os.path.basename(filepath)}")
        self.logger.info(f"Запуск индексации файла: {filepath}")
        try:
            from memory import memory as _mem
            hash_db = self.FileHashDB() if incremental else None
            chunk_count = self.index_file(filepath, _mem, clean, max_file_mb=10,
                                          hash_db=hash_db, incremental=incremental, force=force)
            self.finish_operation(chunk_count > 0, f"Проиндексировано {chunk_count} чанков")
            return {
                "success": chunk_count > 0,
                "message": f"Файл {filepath}: проиндексировано {chunk_count} чанков",
                "data": {"chunks": chunk_count}
            }
        except Exception as e:
            self.logger.error(f"Ошибка индексации файла {filepath}: {e}")
            self.finish_operation(False, f"Ошибка: {str(e)}")
            return {"success": False, "message": f"Ошибка: {str(e)}"}

    # ======================================================================
    # Обработка запросов (диалоговый режим)
    # ======================================================================

    def _process_specific(self, query: str, context: str) -> Dict[str, Any]:
        """
        Обрабатывает запрос пользователя (диалоговый режим).

        Args:
            query: Пользовательский запрос
            context: Извлечённый контекст

        Returns:
            Результат обработки
        """
        self.logger.info(f"Обработка запроса парсера: {query}")
        if query is None:
            query = ""
        query_lower = query.lower()

        # 1. Добавление источника
        if "добавь" in query_lower and ("сайт" in query_lower or "источник" in query_lower or "url" in query_lower):
            import re
            urls = re.findall(r'https?://[^\s]+', query)
            if urls:
                url = urls[0]
                name = query.replace(url, "").strip()
                name = name.replace("добавь", "").replace("сайт", "").replace("источник", "").replace("для парсинга", "").strip()
                schedule = "daily"
                if "раз в день" in query_lower or "ежедневно" in query_lower:
                    schedule = "daily"
                elif "раз в неделю" in query_lower or "еженедельно" in query_lower:
                    schedule = "weekly"
                elif "один раз" in query_lower:
                    schedule = "once"

                result = self.add_source(url, name or url, schedule)
                return {"success": result["success"], "result": result["message"], "agent": self.agent_name}
            else:
                return {
                    "success": True,
                    "result": "Пожалуйста, укажите URL сайта. Например: «добавь сайт https://example.com для парсинга»",
                    "agent": self.agent_name
                }

        # 2. Удаление источника
        if "удали" in query_lower and ("сайт" in query_lower or "источник" in query_lower):
            import re
            urls = re.findall(r'https?://[^\s]+', query)
            if urls:
                result = self.remove_source(urls[0])
                return {"success": result["success"], "result": result["message"], "agent": self.agent_name}

        # 3. Список источников
        if any(word in query_lower for word in ["список", "источники", "какие сайты", "покажи источники"]):
            result = self.list_sources()
            if result["success"] and result["sources"]:
                sources_str = "\n".join([
                    f"  • {s['name']} ({s['url']}) — {s.get('schedule', 'daily')}"
                    for s in result["sources"]
                ])
                return {
                    "success": True,
                    "result": f"📋 **Источники для парсинга ({result['count']}):**\n\n{sources_str}",
                    "agent": self.agent_name
                }
            return {
                "success": True,
                "result": result.get("message", "Нет добавленных источников"),
                "agent": self.agent_name
            }

        # 4. Сбор данных из 1С (универсальный)
        if any(word in query_lower for word in ["собери 1с", "сбор 1с", "выгрузи из 1с", "данные из 1с"]):
            mode = "incremental"
            entity_filter = None
            if "полн" in query_lower or "full" in query_lower:
                mode = "full"
            import re
            only_match = re.search(r'только\s+(\S+)', query_lower)
            if only_match:
                entity_filter = only_match.group(1)
            result = self.collect_1c(mode=mode, entity_filter=entity_filter)
            return {"success": result["success"], "result": result["message"], "agent": self.agent_name}

        # 5. Построение карты ИТС
        if any(word in query_lower for word in ["карта итс", "карту итс", "построй карту итс"]):
            result = self.build_its_sitemap()
            return {"success": result["success"], "result": result["message"], "agent": self.agent_name}

        # 6. Парсинг ИТС
        if any(word in query_lower for word in ["парси итс", "парсинг итс", "спарсить итс"]):
            result = self.parse_its()
            return {"success": result["success"], "result": result["message"], "agent": self.agent_name}

        # 7. Парсинг ukorona
        if any(word in query_lower for word in ["парси ukorona", "парсинг ukorona", "спарсить ukorona", "ukorona"]):
            result = self.parse_ukorona()
            return {"success": result["success"], "result": result["message"], "agent": self.agent_name}

        # 8. Парсинг сайтов поставщиков
        if any(word in query_lower for word in ["парси сайты", "парсинг сайтов", "обнови цены", "обнови товары"]):
            result = self.parse_supplier_sites()
            return {"success": result["success"], "result": result["message"], "agent": self.agent_name}

        # 9. Запуск всех задач
        if any(word in query_lower for word in ["запусти всё", "все задачи", "полный парсинг", "собери всё", "парси всё"]):
            result = self.parse_all()
            return {"success": result["success"], "result": result["message"], "agent": self.agent_name}

        # 10. Индексация проекта
        if any(word in query_lower for word in ["проиндексируй проект", "индексация проекта", "переиндексация проекта"]):
            clean = "очистить" in query_lower or "clean" in query_lower
            force = "принудительно" in query_lower or "force" in query_lower
            result = self.index_project(clean=clean, incremental=not force, force=force)
            return {"success": result["success"], "result": result["message"], "agent": self.agent_name}

        # 11. Индексация папки
        if any(word in query_lower for word in ["проиндексируй папку", "индексируй папку", "индексация папки"]):
            path_match = re.search(r'(папку|директорию)\s+([^\s]+)', query_lower)
            if path_match:
                path = path_match.group(2)
                clean = "очистить" in query_lower
                force = "принудительно" in query_lower
                result = self.index_files(path, recursive=True, clean=clean, incremental=not force, force=force)
                return {"success": result["success"], "result": result["message"], "agent": self.agent_name}
            else:
                return {"success": False, "result": "Укажите путь к папке. Например: «проиндексируй папку ./docs»", "agent": self.agent_name}

        # 12. Индексация файла
        if any(word in query_lower for word in ["проиндексируй файл", "индексируй файл"]):
            path_match = re.search(r'файл\s+([^\s]+)', query_lower)
            if path_match:
                path = path_match.group(1)
                clean = "очистить" in query_lower
                force = "принудительно" in query_lower
                result = self.index_single_file(path, clean=clean, incremental=not force, force=force)
                return {"success": result["success"], "result": result["message"], "agent": self.agent_name}
            else:
                return {"success": False, "result": "Укажите путь к файлу. Например: «проиндексируй файл README.md»", "agent": self.agent_name}

        # 13. Помощь

        if any(word in query_lower for word in ["помощь", "help", "что ты умеешь", "команды"]):
            return {
                "success": True,
                "result": (
                    "🤖 **Парсер (Интегратор данных) — доступные команды:**\n\n"
                    "**Коллекторы:**\n"
                    "• `собери 1С` — инкрементальный сбор данных из 1С (все сущности)\n"
                    "• `собери 1С полную` — полная перезагрузка всех сущностей из 1С\n"
                    "• `собери 1С только [имя]` — сбор конкретной сущности (для отладки)\n"
                    "• `построй карту ИТС` — построить карту сайта ИТС 1С\n"
                    "• `парси ИТС [раздел]` — запустить парсинг документации ИТС 1С\n"
                    "• `парси ukorona` — запустить парсинг ukorona.ru\n"
                    "• `запусти всё` — выполнить все задачи\n\n"
                    "**Сайты поставщиков:**\n"
                    "• `добавь сайт https://... для парсинга [раз в день/неделю]` — добавить источник\n"
                    "• `удали сайт https://...` — удалить источник\n"
                    "• `список источников` — показать все источники\n"
                    "• `парси сайты` — запустить парсинг всех сайтов поставщиков\n"
                    "• `помощь` — показать это сообщение"
                ),
                "agent": self.agent_name
            }

        # По умолчанию — используем LLM
        try:
            from connectors.llm_client_distributed import generate_sync as llm_generate
            prompt = f"""{get_system_prompt(AgentRole.PARSER)}

Запрос пользователя: {query}

Ответь пользователю. Если запрос не относится к парсингу, объясни, что ты умеешь делать.
"""
            response = llm_generate(prompt, temperature=0.3)
            return {"success": True, "result": response, "agent": self.agent_name}
        except Exception as e:
            return {
                "success": True,
                "result": (
                    "Я — Парсер (Интегратор данных). Я умею:\n"
                    "• Собирать данные из 1С (товары, остатки, счета, кредиты, лизинг, заказы)\n"
                    "• Парсить документацию ИТС 1С\n"
                    "• Парсить ukorona.ru (товары, новости, акции)\n"
                    "• Парсить сайты поставщиков\n"
                    "• Добавлять новые источники через диалог\n\n"
                    "Напишите «помощь» для списка команд."
                ),
                "agent": self.agent_name
            }

    def get_last_parsing_result(self) -> Dict[str, Any]:
        """Возвращает результат последнего парсинга для виджетов дашборда."""
        if not self.parsing_results:
            return {"status": "idle", "last_result": None, "message": "Парсинг ещё не выполнялся"}

        last = self.parsing_results[-1]
        return {
            "status": "running" if self.current_task else "idle",
            "last_result": last,
            "current_task": self.current_task,
            "message": last.get("message", ""),
            "success": last.get("success", False)
        }

    def get_status(self) -> Dict[str, Any]:
        """Возвращает статус агента."""
        return {
            "name": self.agent_name,
            "display_name": self.display_name,
            "current_task": self.current_task,
            "parsing_results_count": len(self.parsing_results),
            "last_parsing": self.parsing_results[-1]["timestamp"] if self.parsing_results else None,
            "status": "running" if self.current_task else "idle",
            "background_scheduler": self._running
        }