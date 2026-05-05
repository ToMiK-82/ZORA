"""
Оркестратор агентов на основе LangGraph.
Управляет потоком выполнения между специализированными агентами.
Динамически строит граф на основе реестра агентов.
"""

import logging
import hashlib
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
                # Сообщение о создании узла графа уже выводится в _build_graph
        return self.agents.get(role_value)

    def get_agent_status(self, role: str) -> dict:
        """Возвращает статус агента по его роли."""
        agent = self.agents.get(role)
        if agent and hasattr(agent, 'get_status'):
            return agent.get_status()
        return {"status": "unknown", "current_task": None, "last_activity": None}

    def _build_graph(self):
        """Строит граф LangGraph динамически на основе реестра агентов."""
        # Сканируем реестр
        registry = discover_agents()
        workflow = StateGraph(AgentState)

        # Добавляем узел-роутер
        workflow.add_node("router", self._route_to_agent)

        # Динамически добавляем узлы для каждого агента из реестра
        for role_value, agent_class in registry.items():
            # Создаём замыкание для захвата role_value
            def make_agent_node(role: str):
                def agent_node(state: dict) -> dict:
                    return self._call_agent(state, role)
                return agent_node

            workflow.add_node(role_value, make_agent_node(role_value))
            logging.info(f"➕ Добавлен узел графа: {role_value} ({agent_class.display_name})")

        workflow.set_entry_point("router")

        # Строим conditional edges от роутера ко всем агентам
        agent_map = {role_value: role_value for role_value in registry.keys()}
        workflow.add_conditional_edges(
            "router",
            self._decide_next_agent,
            agent_map
        )

        # Все агенты ведут к END
        for role_value in registry.keys():
            workflow.add_edge(role_value, END)

        workflow.add_conditional_edges("router", self._should_continue, {"continue": END, "end": END})
        return workflow.compile()

    def _classify_intent(self, query: str, interface: str = "user") -> str:
        query_hash = hashlib.md5(query.lower().strip().encode()).hexdigest()
        cache_key = f"{query_hash}_{interface}"
        if cache_key in self.intent_cache:
            return self.intent_cache[cache_key]

        # Для интерфейса "dev" все запросы направляем агенту developer (Ria)
        if interface == "dev":
            self.intent_cache[cache_key] = "developer"
            return "developer"

        # Для интерфейса "user" используем обычную логику
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

        if interface == "dev":
            dev_greetings = ['привет', 'здравствуй', 'добрый день', 'кто ты', 'как тебя зовут',
                             'представься', 'что ты умеешь', 'расскажи о себе']
            if any(greet in query.lower() for greet in dev_greetings):
                state["agent_type"] = "developer"
        elif interface == "user":
            user_greetings = ['привет', 'здравствуй', 'добрый день', 'кто ты', 'как тебя зовут',
                              'представься', 'что ты умеешь', 'расскажи о себе']
            if any(greet in query.lower() for greet in user_greetings):
                state["agent_type"] = "support"
                return state

        try:
            agent_type = self._classify_intent(query, interface)
            # Проверяем, существует ли роль в реестре
            if agent_type not in AGENT_REGISTRY:
                agent_type = self._legacy_route(query, interface)
                # Если и legacy не нашёл, fallback на support
                if agent_type not in AGENT_REGISTRY:
                    agent_type = "support"
            state["agent_type"] = agent_type
        except Exception as e:
            agent_type = self._legacy_route(query, interface)
            if agent_type not in AGENT_REGISTRY:
                agent_type = "support"
            state["agent_type"] = agent_type

        # Поиск контекста в памяти
        try:
            logging.info(f"Запрос перед поиском: {repr(query)}")
            context_results = memory.search(query, limit=15, threshold=0.3)
            logging.info(f"Поиск контекста для запроса '{query}' вернул {len(context_results)} результатов")

            results_with_path = [r for r in context_results if r.get("path")]
            if len(results_with_path) < 5:
                keywords = self._extract_keywords(query)
                if keywords:
                    logging.info(f"Извлечённые ключевые слова: {keywords}")
                    extended_query = " ".join(keywords[:5])
                    extra_results = memory.search(extended_query, limit=10, threshold=0.3)
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
        try:
            agent = self._get_or_create_agent(role_value)
            if agent is None:
                logging.warning(f"Агент для роли {role_value} не найден в реестре")
                state["result"] = f"Агент для роли {role_value} не найден."
                return state

            result = agent.process(state)
            state["result"] = result.get("result", "")

            # Передаём дополнительные поля (для developer_assistant)
            if "mode" in result:
                state["mode"] = result["mode"]
            if "pending_plan" in result:
                state["pending_plan"] = result["pending_plan"]
            if "reasoning" in result:
                state["reasoning"] = result["reasoning"]

        except Exception as e:
            logging.error(f"Ошибка при вызове агента {role_value}: {e}")
            state["result"] = f"Ошибка в работе агента {role_value}: {str(e)}"
        return state

    def process(self, query: str, interface: str = "user", history: List[Dict] = None) -> Dict[str, Any]:
        if history is None:
            history = []
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

    def schedule_background_tasks(self):
        import asyncio
        from datetime import datetime

        async def _run_daily_checks():
            while True:
                try:
                    now = datetime.now()
                    if now.hour == 9 and now.minute == 0:
                        logging.info(">>> Запуск ежедневных проверок агентов...")
                        # Запускаем фоновые задачи парсера
                        parser_agent = self._get_or_create_agent("parser")
                        if parser_agent and hasattr(parser_agent, 'run_scheduled_tasks'):
                            try:
                                results = parser_agent.run_scheduled_tasks()
                                logging.info(f"✅ Фоновые задачи парсера выполнены: {len(results)} задач")
                            except Exception as e:
                                logging.error(f"Ошибка фоновых задач парсера: {e}")
                        logging.info("✅ Ежедневные проверки завершены")
                    if now.hour == 3 and now.minute == 0:
                        logging.info(">>> Запуск анализа обратной связи...")
                        try:
                            from memory.feedback_analyzer import analyze_and_suggest
                            suggestions = analyze_and_suggest()
                            if suggestions:
                                logging.info(f"✅ Анализ обратной связи завершен. Сгенерировано предложений для {len(suggestions)} агентов")
                        except Exception as e:
                            logging.error(f"Ошибка анализа обратной связи: {e}")

                        logging.info("🔍 Запуск планового анализа кода агентов...")
                        try:
                            state = {
                                "query": "Проанализируй всех агентов в папке agents/, найди ошибки, неиспользуемые импорты, нарушения стиля. Предложи исправления. Если ошибки критичны и исправления очевидны, внеси их самостоятельно.",
                                "interface": "dev",
                                "history": []
                            }
                            dev_agent = self._get_or_create_agent("developer")
                            if dev_agent:
                                result = dev_agent.process(state)
                                logging.info(f"Результат ночного анализа: {result.get('result', '')[:500]}")
                        except Exception as e:
                            logging.error(f"Ошибка ночного анализа кода: {e}")

                    if now.hour % 6 == 0 and now.minute == 0:
                        logging.info("▶ Запуск анализа уроков для самообучения...")
                        try:
                            from memory.lesson_saver import analyze_lessons_for_improvements
                            report = analyze_lessons_for_improvements()
                            if "Предложения по улучшению" in report:
                                logging.info("📊 Найдены предложения по улучшению системы")
                        except Exception as e:
                            logging.error(f"Ошибка анализа уроков: {e}")
                    if now.hour % 12 == 0 and now.minute == 0:
                        logging.info("▶ Запуск фоновой индексации проекта...")
                        try:
                            from memory.indexer import index_directory
                            import os
                            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                            results = index_directory(project_root)
                            logging.info(f"✅ Индексация завершена: {results['indexed_files']} файлов, {results['total_chunks']} чанков")
                        except Exception as e:
                            logging.error(f"Ошибка индексации: {e}")
                    await asyncio.sleep(60)
                except Exception as e:
                    logging.error(f"Ошибка в фоновой задаче: {e}")
                    await asyncio.sleep(60)

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(_run_daily_checks())
            else:
                loop.run_until_complete(_run_daily_checks())
        except Exception as e:
            logging.error(f"Не удалось запустить фоновые задачи: {e}")

        try:
            from memory.lesson_saver import schedule_lesson_analysis
            schedule_lesson_analysis(interval_hours=24)
            logging.info("✅ Анализ уроков запланирован")
        except Exception as e:
            logging.warning(f"Не удалось запланировать анализ уроков: {e}")

        try:
            from memory.indexer import schedule_background_indexing
            import os
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            schedule_background_indexing(project_root, interval_hours=12)
            logging.info("✅ Фоновая индексация запланирована")
        except Exception as e:
            logging.warning(f"Не удалось запланировать фоновую индексацию: {e}")

        logging.info("✅ Все фоновые задачи запланированы")


orchestrator = ZoraOrchestrator()
