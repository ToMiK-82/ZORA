"""
Оркестратор агентов на основе LangGraph.
Управляет потоком выполнения между специализированными агентами.
Динамически строит граф на основе реестра агентов.
"""

import logging
import hashlib
import uuid
import time
import asyncio
from collections import deque
from datetime import datetime
from typing import Dict, Any, TypedDict, Annotated, List, Optional

from langgraph.graph import StateGraph, END

try:
    from memory import memory
    MEMORY_AVAILABLE = True
except ImportError:
    MEMORY_AVAILABLE = False
    memory = None
from connectors.llm_client_distributed import generate_sync as llm_generate
from core.model_selector import get_selector
from core.agent_registry import discover_agents, get_agent_class, get_all_agents_info, AGENT_REGISTRY


# ============================================================
# TraceHandler — трассировка выполнения цепочек агентов
# ============================================================
class TraceHandler:
    """Хранит и управляет трассами выполнения запросов через оркестратор."""

    def __init__(self, max_traces: int = 100):
        self.traces: deque = deque(maxlen=max_traces)
        self._active: Dict[str, dict] = {}
        self._ws_callbacks: list = []

    def subscribe(self, callback):
        """Подписка на события трассировки (для WebSocket)."""
        self._ws_callbacks.append(callback)

    async def _notify(self, event: str, data: dict):
        for cb in self._ws_callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(event, data)
                else:
                    cb(event, data)
            except Exception:
                pass

    def start_trace(self, query: str, interface: str = "user") -> str:
        run_id = str(uuid.uuid4())[:8]
        trace = {
            "run_id": run_id,
            "query": query,
            "interface": interface,
            "started_at": time.time(),
            "completed_at": None,
            "steps": [],
            "result": None,
            "status": "running",
        }
        self._active[run_id] = trace
        self.traces.append(trace)
        # Асинхронное уведомление (если есть event loop)
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._notify("execution_trace", trace))
        except RuntimeError:
            pass
        return run_id

    def add_step(self, run_id: str, agent: str, detail: str = ""):
        trace = self._active.get(run_id)
        if trace is None:
            return
        step = {
            "agent": agent,
            "timestamp": time.time(),
            "detail": detail,
        }
        trace["steps"].append(step)
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._notify("trace_step", {"run_id": run_id, "step": step}))
        except RuntimeError:
            pass

    def complete_trace(self, run_id: str, result: str = ""):
        trace = self._active.pop(run_id, None)
        if trace is None:
            return
        trace["completed_at"] = time.time()
        trace["result"] = result
        trace["status"] = "completed"
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._notify("trace_completed", trace))
        except RuntimeError:
            pass

    def _cleanup_old_traces(self, max_age_seconds: int = 3600):
        """Удаляет завершённые трассы старше max_age_seconds."""
        now = time.time()
        cutoff = now - max_age_seconds
        # Очищаем deque от старых завершённых трасс
        new_traces = deque(maxlen=self.traces.maxlen)
        for t in self.traces:
            completed = t.get("completed_at")
            if completed and completed < cutoff:
                continue  # пропускаем старые завершённые
            new_traces.append(t)
        self.traces = new_traces
        # Очищаем активные, которые зависли (started_at слишком старые)
        stale_active = [rid for rid, t in self._active.items()
                        if t.get("started_at", 0) < cutoff and t.get("status") == "running"]
        for rid in stale_active:
            t = self._active.pop(rid, None)
            if t:
                t["status"] = "timed_out"
                t["completed_at"] = now
                self.traces.append(t)

    def get_active_traces(self) -> List[dict]:
        self._cleanup_old_traces()
        return list(self._active.values())

    def get_recent_traces(self, limit: int = 20) -> List[dict]:
        self._cleanup_old_traces()
        return list(self.traces)[-limit:]

    def get_trace(self, run_id: str) -> Optional[dict]:
        self._cleanup_old_traces()
        for t in self.traces:
            if t["run_id"] == run_id:
                return t
        return self._active.get(run_id)


trace_handler = TraceHandler()
# ============================================================


def replace_value(old, new):
    """Заменяет старое значение новым."""
    return new


class AgentState(TypedDict):
    """Состояние графа агентов."""
    query: Annotated[str, replace_value]
    agent_type: Annotated[str, replace_value]
    context: Annotated[str, replace_value]
    result: Annotated[str, replace_value]
    next_agent: Annotated[str, replace_value]
    interface: Annotated[str, replace_value]
    history: Annotated[List[Dict], replace_value]   # история диалога


# Сопоставление ролей агентов и типов чанков для фильтрации поиска
INTENT_TYPE_MAP = {
    "developer": ["code", "document", "config"],
    "parser": ["documentation", "product", "balance", "order", "news", "promotion"],
    "economist": ["balance", "catalog", "document", "accumulation_register", "balance_analytics"],
    "accountant": ["document", "catalog", "balance", "information_register", "accumulation_register"],
    "logistician": ["balance", "accumulation_register", "balance_analytics", "catalog"],
    "procurement_manager": ["product", "catalog", "order", "sale"],
    "sales_consultant": ["product", "catalog", "sale", "order"],
    "support": ["documentation", "product", "news", "promotion"],
    "smm": ["news", "promotion", "documentation"],
    "website": ["web", "documentation"],
    "default": ["catalog", "document", "documentation", "product", "balance"]
}


class AgentStatusTracker:
    """Трекер статусов агентов в реальном времени."""

    def __init__(self):
        self._statuses: Dict[str, dict] = {}

    def set_running(self, role: str, task: str = ""):
        self._statuses[role] = {
            "status": "running",
            "current_task": task,
            "last_activity": datetime.now().isoformat(),
        }

    def set_idle(self, role: str):
        self._statuses[role] = {
            "status": "idle",
            "current_task": None,
            "last_activity": datetime.now().isoformat(),
        }

    def set_error(self, role: str, error: str = ""):
        self._statuses[role] = {
            "status": "error",
            "current_task": error,
            "last_activity": datetime.now().isoformat(),
        }

    def get_status(self, role: str) -> dict:
        return self._statuses.get(role, {"status": "idle", "current_task": None, "last_activity": None})

    def get_all_statuses(self) -> Dict[str, dict]:
        return dict(self._statuses)


agent_status_tracker = AgentStatusTracker()


class ZoraOrchestrator:
    """Оркестратор для управления агентами ZORA.
    Динамически строит граф на основе реестра агентов."""

    def __init__(self):
        # Словарь экземпляров агентов {role_value: instance}
        self.agents = {}
        self.graph = self._build_graph()
        self.intent_cache = {}
        self.model_selector = get_selector()

    def _get_or_create_agent(self, role_value: str):
        """Возвращает экземпляр агента по роли, создавая при необходимости."""
        if role_value not in self.agents:
            agent_class = get_agent_class(role_value)
            if agent_class:
                self.agents[role_value] = agent_class()
        return self.agents.get(role_value)

    def get_agent_status(self, role: str) -> dict:
        """Возвращает статус агента по его роли."""
        # Сначала проверяем трекер
        tracker_status = agent_status_tracker.get_status(role)
        if tracker_status.get("status") != "idle":
            return tracker_status
        # Fallback на метод агента
        agent = self.agents.get(role)
        if agent and hasattr(agent, 'get_status'):
            return agent.get_status()
        return tracker_status

    def _build_graph(self):
        """Строит граф LangGraph динамически на основе реестра агентов."""
        registry = discover_agents()
        workflow = StateGraph(AgentState)

        workflow.add_node("router", self._route_to_agent)

        for role_value, agent_class in registry.items():
            def make_agent_node(role: str):
                def agent_node(state: dict) -> dict:
                    return self._call_agent(state, role)
                return agent_node

            workflow.add_node(role_value, make_agent_node(role_value))
            logging.info(f"➕ Добавлен узел графа: {role_value} ({agent_class.display_name})")

        workflow.set_entry_point("router")

        agent_map = {role_value: role_value for role_value in registry.keys()}
        workflow.add_conditional_edges(
            "router",
            self._decide_next_agent,
            agent_map
        )

        for role_value in registry.keys():
            workflow.add_edge(role_value, END)

        workflow.add_conditional_edges("router", self._should_continue, {"continue": END, "end": END})
        return workflow.compile()

    def _classify_intent(self, query: str, interface: str = "user") -> str:
        query_hash = hashlib.md5(query.lower().strip().encode()).hexdigest()
        cache_key = f"{query_hash}_{interface}"
        if cache_key in self.intent_cache:
            return self.intent_cache[cache_key]

        if interface == "dev":
            self.intent_cache[cache_key] = "developer"
            return "developer"

        else:
            query_lower = query.lower()

            economist_keywords = ["курс", "валюта", "доллар", "евро", "цена", "стоимость", "экономика", "расход", "доход"]
            if any(kw in query_lower for kw in economist_keywords):
                self.intent_cache[cache_key] = "economist"
                return "economist"

            try:
                import threading
                from queue import Queue

                result_queue = Queue()

                def _call_llm():
                    try:
                        response = llm_generate(
                            f"Классифицируй запрос: {query}\nВерни только: economist, support, или developer",
                            model="llama3.2:latest",
                            temperature=0.1,
                            use_local_first=True
                        )
                        agent_name = str(response).strip().lower()
                        valid_agents = ["economist", "support", "developer"]
                        if agent_name not in valid_agents:
                            agent_name = "support"
                        result_queue.put(agent_name)
                    except Exception as e:
                        logging.warning(f"Ошибка классификации LLM: {e}")
                        result_queue.put("support")

                thread = threading.Thread(target=_call_llm)
                thread.daemon = True
                thread.start()
                thread.join(timeout=5)

                if thread.is_alive():
                    logging.warning(f"Тайм-аут классификации (5 сек), используем support")
                    agent_name = "support"
                else:
                    try:
                        agent_name = result_queue.get(timeout=2)
                    except:
                        agent_name = "support"

                self.intent_cache[cache_key] = agent_name
                return agent_name
            except Exception as e:
                logging.warning(f"Ошибка при классификации интента: {e}")
                return "support"

    def _legacy_route(self, query: str, interface: str = "user") -> str:
        """Резервный классификатор на основе ключевых слов."""
        query_lower = query.lower()

        if interface == "dev":
            dev_keywords = [
                "/dev", "ассистент", "помоги с кодом", "разработчик", "код", "файл",
                "прочитай", "запусти", "команда", "python", "скрипт", "программа",
                "отладка", "ошибка", "баг", "тест", "индекс", "память", "вектор",
                "qdrant", "docker", "git", "репозиторий", "ветка", "merge", "pull",
                "push", "commit", "конфигурация", "настройка", "установка", "зависимость",
                "библиотека", "модуль", "импорт", "функция", "класс", "метод", "переменная",
                "синтаксис", "компиляция", "интерпретатор", "среда", "ide", "vscode",
                "отладчик", "логирование", "лог", "консоль", "терминал", "shell", "bash",
                "powershell", "cmd", "командная строка", "процесс", "поток", "память",
                "оперативная", "диск", "хранилище", "база данных", "sql", "nosql",
                "api", "rest", "graphql", "веб", "сервер", "клиент", "браузер",
                "html", "css", "javascript", "typescript", "react", "vue", "angular",
                "открой файл", "прочитай файл", "покажи файл", "посмотри файл", "открыть файл",
                "проект", "понимание", "система", "настройка", "оркестратор", "агент", "агенты",
                "контекст", "поиск", "информация", "данные", "база", "хранилище", "векторная",
                "эмбеддинг", "ollama", "модель", "llm", "запрос", "ответ", "диалог", "чат"
            ]
            if any(keyword in query_lower for keyword in dev_keywords):
                return "developer"
            dev_greetings = ['привет', 'здравствуй', 'добрый день', 'кто ты', 'как тебя зовут']
            if any(greet in query_lower for greet in dev_greetings):
                return "developer"

        if interface == "user" and "/dev" in query_lower:
            return "developer"

        if any(word in query_lower for word in ["цена", "стоимость", "экономика", "расход", "доход", "продажа", "коммерция", "клиент", "сделка", "курс", "доллар", "евро", "валюта", "рубль", "биткоин", "криптовалюта"]):
            return "economist"
        elif any(word in query_lower for word in ["закупка", "остаток", "заказ", "поставка"]):
            return "procurement_manager"
        elif any(word in query_lower for word in ["бухгалтер", "1с", "проводка", "налог", "финанс", "денеж"]):
            return "accountant"
        elif any(word in query_lower for word in ["поддержка", "жалоба", "вопрос", "помощь"]):
            return "support"
        elif any(word in query_lower for word in ["соцсеть", "smm", "маркетинг", "реклама"]):
            return "smm"
        elif any(word in query_lower for word in ["сайт", "веб", "интернет", "лендинг"]):
            return "website"
        elif any(word in query_lower for word in ["парси", "парсер", "парсинг", "итс", "документ", "скрапинг", "собрать", "индексировать"]):
            return "parser"
        elif any(word in query_lower for word in ["продаж", "выручк", "отчёт по продажам", "менеджер по продажам", "sales", "объём продаж", "топ продаж", "клиентская база", "контрагент", "покупател"]):
            return "sales_consultant"
        elif any(word in query_lower for word in ["баланс", "остаток", "счёт", "платон", "ликарда", "кедр", "логист"]):
            return "logistician"
        else:
            return "developer" if interface == "dev" else "support"

    def _extract_keywords(self, query: str) -> list:
        """Извлекает ключевые слова из запроса для улучшения поиска."""
        import re

        if "Текущий запрос:" in query:
            parts = query.split("Текущий запрос:")
            if len(parts) > 1:
                query = parts[-1].strip()

        patterns = [
            r'агента[-\s]+([а-яё]+)',
            r'файл\s+([а-яё]+\.\w+)',
            r'код\s+([а-яё]+)',
            r'покажи\s+([а-яё]+)',
            r'найди\s+([а-яё]+)'
        ]
        keywords = []
        for pattern in patterns:
            match = re.search(pattern, query.lower())
            if match:
                keywords.append(match.group(1))

        words = re.findall(r'[а-яё]{4,}', query.lower())
        stop_words = {'покажи', 'код', 'агента', 'файл', 'найди', 'какой', 'где', 'что', 'как', 'для', 'из', 'с', 'в', 'на', 'пожалуйста', 'можно', 'мне', 'тебе', 'это', 'такой'}
        for w in words:
            if w not in stop_words and w not in keywords:
                keywords.append(w)

        seen = set()
        unique = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique.append(kw)
        return unique[:5]

    def _route_to_agent(self, state: dict) -> dict:
        query = state.get("query", "")
        interface = state.get("interface", "user")

        # Определяем agent_type (без изменений)
        if interface == "dev":
            dev_greetings = ['привет', 'здравствуй', 'добрый день', 'кто ты', 'как тебя зовут',
                             'представься', 'что ты умеешь', 'расскажи о себе']
            if any(greet in query.lower() for greet in dev_greetings):
                state["agent_type"] = "developer"
                agent_type = "developer"
            else:
                agent_type = "developer"
                state["agent_type"] = agent_type
        elif interface == "user":
            user_greetings = ['привет', 'здравствуй', 'добрый день', 'кто ты', 'как тебя зовут',
                              'представься', 'что ты умеешь', 'расскажи о себе']
            if any(greet in query.lower() for greet in user_greetings):
                state["agent_type"] = "support"
                agent_type = "support"
            else:
                try:
                    agent_type = self._classify_intent(query, interface)
                    if agent_type not in AGENT_REGISTRY:
                        agent_type = self._legacy_route(query, interface)
                        if agent_type not in AGENT_REGISTRY:
                            agent_type = "support"
                except Exception as e:
                    agent_type = self._legacy_route(query, interface)
                    if agent_type not in AGENT_REGISTRY:
                        agent_type = "support"
                state["agent_type"] = agent_type
        else:
            agent_type = "support"
            state["agent_type"] = agent_type

        # --- НОВОЕ: фильтрация по типам чанков ---
        # Определяем, какие типы чанков нужны этому агенту
        if interface == "dev":
            agent_types = INTENT_TYPE_MAP.get("developer", ["code", "document", "config"])
        else:
            agent_types = INTENT_TYPE_MAP.get(agent_type, INTENT_TYPE_MAP["default"])
        # ---------------------------------------

        # Поиск контекста в памяти с фильтрацией
        try:
            logging.info(f"Запрос перед поиском: {repr(query)}")
            # Передаём список типов в hybrid_search
            context_results = memory.hybrid_search(query, limit=15, types=agent_types, score_threshold=0.3)
            logging.info(f"Гибридный поиск для запроса '{query}' вернул {len(context_results)} результатов (фильтр по типам: {agent_types})")

            results_with_path = [r for r in context_results if r.get("path")]
            if len(results_with_path) < 5:
                keywords = self._extract_keywords(query)
                if keywords:
                    logging.info(f"Извлечённые ключевые слова: {keywords}")
                    extended_query = " ".join(keywords[:5])
                    extra_results = memory.search(extended_query, limit=10, threshold=0.3, types=agent_types)
                    seen_texts = {r.get("text", "") for r in context_results}
                    for r in extra_results:
                        if r.get("path"):
                            text = r.get("text", "")
                            if text not in seen_texts:
                                context_results.append(r)
                                seen_texts.add(text)
                    logging.info(f"Дополнительный поиск по ключевым словам добавил {len(extra_results)} результатов")

            results_with_path = [r for r in context_results if r.get("path")]
            results_without_path = [r for r in context_results if not r.get("path")]
            selected = results_with_path[:5] if results_with_path else []
            if len(selected) < 5 and results_without_path:
                selected.extend(results_without_path[:5 - len(selected)])
            parts = []
            for r in selected:
                text = r.get("text", "")
                path = r.get("path", "")
                if path:
                    parts.append(f"📁 Файл: {path}\n{text}")
                else:
                    parts.append(text)
            state["context"] = "\n\n".join(parts)
            logging.info(f"Контекст собран из {len(selected)} фрагментов")
        except Exception as e:
            logging.error(f"Ошибка поиска контекста: {e}")
            state["context"] = ""
        return state

    def _decide_next_agent(self, state: dict) -> str:
        return state.get("agent_type", "support")

    def _should_continue(self, state: dict) -> str:
        if "завершено" in state.get("result", "").lower() or not state.get("result"):
            return "end"
        return "continue"

    def _call_agent(self, state: dict, role_value: str) -> dict:
        """Универсальный метод вызова любого агента по его роли."""
        # Устанавливаем статус running
        agent_status_tracker.set_running(role_value, state.get("query", "")[:100])
        try:
            agent = self._get_or_create_agent(role_value)
            if agent is None:
                logging.warning(f"Агент для роли {role_value} не найден в реестре")
                state["result"] = f"Агент для роли {role_value} не найден."
                agent_status_tracker.set_idle(role_value)
                return state

            result = agent.process(state)
            state["result"] = result.get("result", "")

            if "mode" in result:
                state["mode"] = result["mode"]
            if "pending_plan" in result:
                state["pending_plan"] = result["pending_plan"]
            if "reasoning" in result:
                state["reasoning"] = result["reasoning"]

            # Возвращаем в idle после успешного выполнения
            agent_status_tracker.set_idle(role_value)

        except Exception as e:
            logging.error(f"Ошибка при вызове агента {role_value}: {e}")
            state["result"] = f"Ошибка в работе агента {role_value}: {str(e)}"
            agent_status_tracker.set_error(role_value, str(e))
        return state

    def process(self, query: str, interface: str = "user", history: List[Dict] = None) -> Dict[str, Any]:
        if history is None:
            history = []
        
        # Стартуем трассировку
        run_id = trace_handler.start_trace(query, interface)
        
        initial_state = AgentState(
            query=query,
            agent_type="support",
            context="",
            result="",
            next_agent="",
            interface=interface,
            history=history
        )
        try:
            final_state = self.graph.invoke(initial_state)
            
            # Добавляем шаг с выбранным агентом
            agent = final_state.get("agent_type", "support")
            trace_handler.add_step(run_id, agent, "Обработка запроса")
            
            # Завершаем трассировку
            result_text = final_state.get("result", "")
            trace_handler.complete_trace(run_id, result_text[:200])


            reasoning = []
            context = final_state.get("context", "")
            result = final_state.get("result", "")

            if context:
                import re
                file_matches = re.findall(r'📁 Файл: (.+?)\n', context)
                if file_matches:
                    reasoning.append(f"Найдено {len(file_matches)} релевантных файлов:")
                    for i, file_path in enumerate(file_matches[:3], 1):
                        reasoning.append(f"  {i}. {file_path}")
                    if len(file_matches) > 3:
                        reasoning.append(f"  ... и ещё {len(file_matches) - 3} файлов")

            agent = final_state.get("agent_type", "")
            reasoning.append(f"Выбран агент: {agent}")

            if context:
                reasoning.append(f"Поиск контекста выполнен успешно")

            response = {
                "success": True,
                "result": result,
                "agent": agent,
                "context": context,
                "reasoning": reasoning
            }
            if "mode" in final_state:
                response["mode"] = final_state["mode"]
            if "pending_plan" in final_state:
                response["pending_plan"] = final_state["pending_plan"]
            return response
        except Exception as e:
            logging.error(f"Ошибка в оркестраторе: {e}")
            return {
                "success": False,
                "error": str(e),
                "result": "Произошла ошибка при обработке запроса.",
                "reasoning": [f"Ошибка: {str(e)}"]
            }

orchestrator = ZoraOrchestrator()