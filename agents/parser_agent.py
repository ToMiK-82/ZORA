"""
Агент-парсер (Интегратор данных) для обработки документов, данных и сайтов.
Работает в диалоговом режиме и по расписанию (фоновые задачи).
Оркестрирует работу коллекторов: 1С, ИТС, ukorona.ru и других.
"""

import json
import logging
import os
import threading
import time
from datetime import datetime
from typing import Dict, Any, List, Optional

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
        self.current_task = f"Сбор данных из 1С ({mode_label})"
        self.logger.info(f"Запуск {mode_label} сбора данных из 1С")

        try:
            from collectors.onec_collector_universal import run as run_1c_universal
            result = run_1c_universal(mode=mode, entity_filter=entity_filter)
            return self._log_result("1c", result.get("success", False),
                f"1С ({mode_label}): обработано {result.get('items_processed', 0)} записей, "
                f"проиндексировано {result.get('items_indexed', 0)}, "
                f"сущностей: {result.get('entities_processed', 0)}",
                data=result)
        except ImportError as e:
            # Fallback на старый коллектор
            self.logger.warning(f"Универсальный коллектор не найден, пробую старый: {e}")
            try:
                from collectors.onec_collector import run as run_1c
                result = run_1c(types=types, limit=limit)
                return self._log_result("1c", result.get("success", False),
                    f"1С (старый): обработано {result.get('items_processed', 0)} записей, "
                    f"проиндексировано {result.get('items_indexed', 0)}",
                    data=result)
            except ImportError as e2:
                return self._log_result("1c", False, f"Модуль коллектора 1С не найден: {e2}")
        except Exception as e:
            self.logger.error(f"Ошибка сбора 1С: {e}")
            return self._log_result("1c", False, f"Ошибка: {str(e)}")

    # ======================================================================
    # Коллектор ИТС
    # ======================================================================

    def build_its_sitemap(self) -> Dict[str, Any]:
        """Строит карту сайта ИТС 1С."""
        self.current_task = "Построение карты ИТС"
        self.logger.info("Запуск построения карты ИТС")

        try:
            from collectors.its_collector import build_sitemap
            result = build_sitemap()
            return self._log_result("its_sitemap", result.get("success", False),
                f"Карта ИТС: {result.get('sections', 0)} разделов, {result.get('articles', 0)} статей",
                data=result)
        except ImportError as e:
            return self._log_result("its_sitemap", False, f"Модуль collectors.its_collector не найден: {e}")
        except Exception as e:
            self.logger.error(f"Ошибка построения карты ИТС: {e}")
            return self._log_result("its_sitemap", False, f"Ошибка: {str(e)}")

    def parse_its(self, sections: Optional[List[str]] = None, limit: Optional[int] = None) -> Dict[str, Any]:
        """
        Парсит статьи ИТС 1С.

        Args:
            sections: Список разделов (например, ["Комплексная автоматизация"])
            limit: Максимальное количество статей

        Returns:
            Результат парсинга.
        """
        self.current_task = "Парсинг ИТС 1С"
        self.logger.info("Запуск парсинга ИТС")

        try:
            from collectors.its_collector import run as run_its
            result = run_its(sections=sections, limit=limit)
            return self._log_result("its", result.get("success", False),
                f"ИТС: обработано {result.get('articles_processed', 0)} статей, "
                f"проиндексировано {result.get('chunks_indexed', 0)} чанков",
                data=result)
        except ImportError as e:
            return self._log_result("its", False, f"Модуль collectors.its_collector не найден: {e}")
        except Exception as e:
            self.logger.error(f"Ошибка парсинга ИТС: {e}")
            return self._log_result("its", False, f"Ошибка: {str(e)}")

    # ======================================================================
    # Коллектор Ukorona
    # ======================================================================

    def parse_ukorona(self, limit: Optional[int] = None) -> Dict[str, Any]:
        """
        Парсит сайт ukorona.ru.

        Args:
            limit: Максимальное количество страниц

        Returns:
            Результат парсинга.
        """
        self.current_task = "Парсинг ukorona.ru"
        self.logger.info("Запуск парсинга ukorona.ru")

        try:
            from collectors.ukorona_collector import run as run_ukorona
            result = run_ukorona(limit=limit)
            return self._log_result("ukorona", result.get("success", False),
                f"Ukorona: обработано {result.get('pages_processed', 0)} страниц, "
                f"проиндексировано {result.get('items_indexed', 0)} записей",
                data=result)
        except ImportError as e:
            return self._log_result("ukorona", False, f"Модуль collectors.ukorona_collector не найден: {e}")
        except Exception as e:
            self.logger.error(f"Ошибка парсинга ukorona: {e}")
            return self._log_result("ukorona", False, f"Ошибка: {str(e)}")

    # ======================================================================
    # Парсинг сайтов поставщиков (старый метод)
    # ======================================================================

    def parse_supplier_sites(self, source_url: str = None) -> Dict[str, Any]:
        """
        Парсит сайты поставщиков из списка источников.

        Args:
            source_url: Конкретный URL для парсинга (если None, парсит все активные)

        Returns:
            Результаты парсинга.
        """
        self.current_task = "Парсинг сайтов поставщиков"
        self.logger.info(f"Запуск парсинга сайтов поставщиков")

        try:
            sources = self._load_sources()
            if source_url:
                sources = [s for s in sources if s["url"] == source_url]

            if not sources:
                return self._log_result("supplier", False,
                    "Нет источников для парсинга. Добавьте сайты через команду.")

            total_parsed = 0
            total_indexed = 0
            results = []

            for source in sources:
                if source.get("status") != "active":
                    continue
                self.logger.info(f"Парсинг источника: {source['url']}")
                try:
                    import requests
                    from bs4 import BeautifulSoup

                    response = requests.get(source["url"], timeout=30, headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    })
                    if response.status_code != 200:
                        results.append({"url": source["url"], "success": False, "error": f"HTTP {response.status_code}"})
                        continue

                    soup = BeautifulSoup(response.text, "html.parser")

                    texts = []
                    for tag in soup.find_all(["p", "h1", "h2", "h3", "li", "td", "span", "div"]):
                        text = tag.get_text(strip=True)
                        if len(text) > 20:
                            texts.append(text)

                    indexed = 0
                    if MEMORY_AVAILABLE and _memory:
                        for text in texts[:100]:
                            try:
                                _memory.store(
                                    text=text[:1000],
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
                    results.append({"url": source["url"], "success": True, "indexed": indexed})

                except Exception as e:
                    self.logger.error(f"Ошибка парсинга {source['url']}: {e}")
                    results.append({"url": source["url"], "success": False, "error": str(e)})

            self._save_sources(sources)

            return self._log_result("supplier", True,
                f"Парсинг завершён. Обработано: {total_parsed} сайтов, проиндексировано: {total_indexed} записей",
                data={"parsed": total_parsed, "indexed": total_indexed, "details": results})

        except ImportError as e:
            return self._log_result("supplier", False,
                f"Необходимые библиотеки не установлены: {e}. Установите requests и beautifulsoup4.")
        except Exception as e:
            self.logger.error(f"Ошибка парсинга сайтов: {e}")
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
        r2 = self.parse_its(limit=5)
        results.append(("ИТС", r2))

        # 3. Ukorona
        r3 = self.parse_ukorona(limit=5)
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

    def run_scheduled_tasks(self):
        """Запускает все запланированные задачи (вызывается из планировщика)."""
        self.logger.info(">>> Запуск запланированных задач парсера")
        results = []

        # 1. Сбор данных из 1С
        r1 = self.collect_1c()
        results.append(r1)

        # 2. Парсинг ИТС (инкрементальный)
        r2 = self.parse_its(limit=10)
        results.append(r2)

        # 3. Парсинг ukorona.ru
        r3 = self.parse_ukorona(limit=10)
        results.append(r3)

        # 4. Парсинг сайтов поставщиков
        r4 = self.parse_supplier_sites()
        results.append(r4)

        self.logger.info(f"✅ Запланированные задачи завершены: {len(results)} задач")
        return results

    def start_background_scheduler(self, interval_hours: int = 6):
        """Запускает фоновый планировщик в отдельном потоке."""
        if self._background_thread and self._background_thread.is_alive():
            self.logger.warning("Фоновый планировщик уже запущен")
            return

        self._running = True

        def _scheduler_loop():
            self.logger.info(f"🔄 Фоновый планировщик запущен (интервал: {interval_hours}ч)")
            while self._running:
                try:
                    now = datetime.now()
                    self.run_scheduled_tasks()
                    for _ in range(interval_hours * 60):
                        if not self._running:
                            break
                        time.sleep(60)
                except Exception as e:
                    self.logger.error(f"Ошибка в фоновом планировщике: {e}")
                    time.sleep(300)

        self._background_thread = threading.Thread(target=_scheduler_loop, daemon=True)
        self._background_thread.start()
        self.logger.info(f"✅ Фоновый планировщик запущен в потоке {self._background_thread.name}")

    def stop_background_scheduler(self):
        """Останавливает фоновый планировщик."""
        self._running = False
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

        self.parsing_results.append({
            "timestamp": datetime.now().isoformat(),
            "type": task_type,
            "success": success,
            "message": message
        })

        try:
            log = []
            if os.path.exists(PARSING_LOG_FILE):
                with open(PARSING_LOG_FILE, "r", encoding="utf-8") as f:
                    log = json.load(f)
            log.append(self.parsing_results[-1])
            if len(log) > 100:
                log = log[-100:]
            with open(PARSING_LOG_FILE, "w", encoding="utf-8") as f:
                json.dump(log, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.warning(f"Ошибка сохранения лога: {e}")

        self.current_task = None
        return result

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
            # Определяем режим
            mode = "incremental"
            entity_filter = None
            if "полн" in query_lower or "full" in query_lower:
                mode = "full"
            # Извлекаем имя сущности после "только"
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
            # Извлекаем раздел, если указан
            sections = None
            for section in ["комплексная автоматизация", "бухгалтерия", "зарплата", "управление торговлей", "новости"]:
                if section in query_lower:
                    if sections is None:
                        sections = []
                    sections.append(section)
            result = self.parse_its(sections=sections)
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

        # 10. Помощь
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
