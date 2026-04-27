"""
Оркестратор агентов на основе LangGraph.
Управляет потоком выполнения между специализированными агентами.
"""

import logging
import hashlib
from typing import Dict, Any, TypedDict, Annotated, List
from enum import Enum

from langgraph.graph import StateGraph, END

try:
    from memory import memory
    MEMORY_AVAILABLE = True
except ImportError:
    MEMORY_AVAILABLE = False
    memory = None
from connectors.llm_client_distributed import generate_sync as llm_generate
from core.model_selector import get_selector


def replace_value(old, new):
    """Заменяет старое значение новым."""
    return new


class AgentType(Enum):
    """Типы агентов, доступных в системе."""
    ECONOMIST = "economist"
    PURCHASER = "purchaser"
    ACCOUNTANT = "accountant"
    SUPPORT = "support"
    SMM = "smm"
    WEBSITE = "website"
    DEVELOPER = "developer"
    PARSER = "parser"


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
    """Оркестратор для управления агентами ZORA."""

    def __init__(self):
        self.graph = self._build_graph()
        self.intent_cache = {}
        self.model_selector = get_selector()

    def _classify_intent(self, query: str, interface: str = "user") -> str:
        query_hash = hashlib.md5(query.lower().strip().encode()).hexdigest()
        cache_key = f"{query_hash}_{interface}"
        if cache_key in self.intent_cache:
            return self.intent_cache[cache_key]
        
        # Для интерфейса "dev" используем упрощённую логику
        if interface == "dev":
            query_lower = query.lower()
            
            # Ключевые слова для разработчика
            dev_keywords = [
                "код", "файл", "проект", "агент", "память", "вектор", "qdrant", "docker", "git", 
                "репозиторий", "отладка", "ошибка", "тест", "скрипт", "python", "программа", 
                "система", "настройка", "оркестратор", "контекст", "поиск", "информация", "данные", 
                "база", "хранилище", "эмбеддинг", "ollama", "модель", "llm", "запрос", "ответ", 
                "диалог", "чат", "покажи", "найди", "открой", "прочитай", "запусти", "команда",
                "индекс", "ветка", "merge", "pull", "push", "commit", "конфигурация", "установка",
                "зависимость", "библиотека", "модуль", "импорт", "функция", "класс", "метод",
                "переменная", "синтаксис", "компиляция", "интерпретатор", "среда", "ide", "vscode",
                "отладчик", "логирование", "лог", "консоль", "терминал", "shell", "bash",
                "powershell", "cmd", "командная строка", "процесс", "поток", "оперативная",
                "диск", "хранилище", "база данных", "sql", "nosql", "api", "rest", "graphql",
                "веб", "сервер", "клиент", "браузер", "html", "css", "javascript", "typescript",
                "react", "vue", "angular", "понимание", "векторная", "привет", "здравствуй",
                "добрый день", "кто ты", "как тебя зовут", "представься", "что ты умеешь",
                "расскажи о себе"
            ]
            
            # Проверяем наличие ключевых слов разработчика
            for keyword in dev_keywords:
                if keyword in query_lower:
                    self.intent_cache[cache_key] = "developer"
                    return "developer"
            
            # Если не нашли ключевых слов разработчика, используем LLM классификатор
            # но с быстрым тайм-аутом
            try:
                import threading
                from queue import Queue
                
                result_queue = Queue()
                
                def _call_llm():
                    try:
                        # Используем llama3.2:latest для классификации
                        response = llm_generate(
                            f"Классифицируй запрос для интерфейса разработчика: {query}\nВерни только: developer или economist",
                            model="llama3.2:latest", 
                            temperature=0.1, 
                            use_local_first=True
                        )
                        agent_name = str(response).strip().lower()
                        if agent_name not in ["developer", "economist"]:
                            agent_name = "developer"
                        result_queue.put(agent_name)
                    except Exception as e:
                        logging.warning(f"Ошибка классификации LLM: {e}")
                        result_queue.put("developer")
                
                thread = threading.Thread(target=_call_llm)
                thread.daemon = True
                thread.start()
                thread.join(timeout=15)  # Увеличенный тайм-аут 15 секунд
                
                if thread.is_alive():
                    logging.warning(f"Тайм-аут классификации (15 сек), используем developer")
                    agent_name = "developer"
                else:
                    try:
                        agent_name = result_queue.get(timeout=5)  # Увеличенный таймаут получения результата
                    except:
                        agent_name = "developer"
                
                self.intent_cache[cache_key] = agent_name
                return agent_name
            except Exception as e:
                logging.warning(f"Ошибка при классификации интента: {e}")
                return "developer"
        
        # Для интерфейса "user" используем обычную логику
        else:
            query_lower = query.lower()
            
            # Сначала проверяем ключевые слова для быстрой классификации
            economist_keywords = ["курс", "валюта", "доллар", "евро", "цена", "стоимость", "экономика", "расход", "доход"]
            if any(kw in query_lower for kw in economist_keywords):
                self.intent_cache[cache_key] = "economist"
                return "economist"
            
            # Если не нашли ключевых слов, используем LLM классификатор
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
                return AgentType.DEVELOPER.value
            dev_greetings = ['привет', 'здравствуй', 'добрый день', 'кто ты', 'как тебя зовут']
            if any(greet in query_lower for greet in dev_greetings):
                return AgentType.DEVELOPER.value
        
        if interface == "user" and "/dev" in query_lower:
            return AgentType.DEVELOPER.value
        
        if any(word in query_lower for word in ["цена", "стоимость", "экономика", "расход", "доход", "продажа", "коммерция", "клиент", "сделка", "курс", "доллар", "евро", "валюта", "рубль", "биткоин", "криптовалюта"]):
            return AgentType.ECONOMIST.value
        elif any(word in query_lower for word in ["закупка", "остаток", "заказ", "поставка"]):
            return AgentType.PURCHASER.value
        elif any(word in query_lower for word in ["бухгалтер", "1с", "проводка", "налог", "финанс", "денеж"]):
            return AgentType.ACCOUNTANT.value
        elif any(word in query_lower for word in ["поддержка", "жалоба", "вопрос", "помощь"]):
            return AgentType.SUPPORT.value
        elif any(word in query_lower for word in ["соцсеть", "smm", "маркетинг", "реклама"]):
            return AgentType.SMM.value
        elif any(word in query_lower for word in ["сайт", "веб", "интернет", "лендинг"]):
            return AgentType.WEBSITE.value
        elif any(word in query_lower for word in ["парси", "парсер", "парсинг", "итс", "1с", "документ", "скрапинг", "собрать", "индексировать"]):
            return AgentType.PARSER.value
        else:
            return AgentType.DEVELOPER.value if interface == "dev" else AgentType.SUPPORT.value

    def _build_graph(self):
        workflow = StateGraph(AgentState)

        workflow.add_node("router", self._route_to_agent)
        workflow.add_node("economist", self._call_economist)
        workflow.add_node("purchaser", self._call_purchaser)
        workflow.add_node("accountant", self._call_accountant)
        workflow.add_node("support", self._call_support)
        workflow.add_node("smm", self._call_smm)
        workflow.add_node("website", self._call_website)
        workflow.add_node("developer", self._call_developer_assistant)
        workflow.add_node("parser", self._call_parser)

        workflow.set_entry_point("router")

        workflow.add_conditional_edges(
            "router",
            self._decide_next_agent,
            {
                AgentType.ECONOMIST.value: "economist",
                AgentType.PURCHASER.value: "purchaser",
                AgentType.ACCOUNTANT.value: "accountant",
                AgentType.SUPPORT.value: "support",
                AgentType.SMM.value: "smm",
                AgentType.WEBSITE.value: "website",
                AgentType.DEVELOPER.value: "developer",
                AgentType.PARSER.value: "parser",
            }
        )

        for agent in ["economist", "purchaser", "accountant", "support", "smm", "website", "developer", "parser"]:
            workflow.add_edge(agent, END)

        workflow.add_conditional_edges("router", self._should_continue, {"continue": END, "end": END})
        return workflow.compile()

    def _extract_keywords(self, query: str) -> list:
        """Извлекает ключевые слова из запроса для улучшения поиска."""
        import re
        
        # Если есть "Текущий запрос:", берём только часть после него
        if "Текущий запрос:" in query:
            parts = query.split("Текущий запрос:")
            if len(parts) > 1:
                query = parts[-1].strip()
        
        # Ищем слова после "агента", "файл", "код"
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
        
        # Также извлекаем все слова длиной >4, которые могут быть существительными
        words = re.findall(r'[а-яё]{4,}', query.lower())
        stop_words = {'покажи', 'код', 'агента', 'файл', 'найди', 'какой', 'где', 'что', 'как', 'для', 'из', 'с', 'в', 'на', 'пожалуйста', 'можно', 'мне', 'тебе', 'это', 'такой'}
        for w in words:
            if w not in stop_words and w not in keywords:
                keywords.append(w)
        
        # Удаляем дубликаты
        seen = set()
        unique = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique.append(kw)
        # Ограничиваем количество ключевых слов (первые 5)
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
            valid_agents = [agent.value for agent in AgentType]
            if agent_type not in valid_agents:
                agent_type = self._legacy_route(query, interface)
            state["agent_type"] = agent_type
        except Exception as e:
            agent_type = self._legacy_route(query, interface)
            state["agent_type"] = agent_type

        try:
            logging.info(f"Запрос перед поиском: {repr(query)}")
            # Основной поиск по полному запросу
            context_results = memory.search(query, limit=15, threshold=0.3)
            logging.info(f"Поиск контекста для запроса '{query}' вернул {len(context_results)} результатов")
            
            # Если результатов с path мало, выполняем дополнительный поиск по ключевым словам
            results_with_path = [r for r in context_results if r.get("path")]
            if len(results_with_path) < 5:
                keywords = self._extract_keywords(query)
                if keywords:
                    logging.info(f"Извлечённые ключевые слова: {keywords}")
                    # Объединяем ключевые слова в одну строку для расширенного поиска
                    extended_query = " ".join(keywords[:5])
                    extra_results = memory.search(extended_query, limit=10, threshold=0.3)
                    # Добавляем уникальные результаты с path
                    seen_texts = {r.get("text", "") for r in context_results}
                    for r in extra_results:
                        if r.get("path"):
                            text = r.get("text", "")
                            if text not in seen_texts:
                                context_results.append(r)
                                seen_texts.add(text)
                    logging.info(f"Дополнительный поиск по ключевым словам добавил {len(extra_results)} результатов")
            
            logging.info(f"Пример результатов: {[r.get('path', 'no_path') for r in context_results[:2]]}")
            results_with_path = [r for r in context_results if r.get("path")]
            results_without_path = [r for r in context_results if not r.get("path")]
            # Приоритет результатам с path
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
            logging.info(f"Контекст собран из {len(selected)} фрагментов (с path: {len(results_with_path)}, без path: {len(results_without_path)})")
        except Exception as e:
            logging.error(f"Ошибка поиска контекста: {e}")
            state["context"] = ""
        return state

    def _decide_next_agent(self, state: dict) -> str:
        return state.get("agent_type", AgentType.ECONOMIST.value)

    def _should_continue(self, state: dict) -> str:
        if "завершено" in state.get("result", "").lower() or not state.get("result"):
            return "end"
        return "continue"

    def _call_agent_template(self, state: dict, agent_name: str) -> dict:
        try:
            module = __import__(f"agents.{agent_name}", fromlist=[agent_name.capitalize()])
            agent_class = getattr(module, agent_name.capitalize())
            agent = agent_class()
            result = agent.process(state)
            state["result"] = result.get("result", "")
        except Exception as e:
            logging.error(f"Ошибка при вызове агента {agent_name}: {e}")
            state["result"] = f"Ошибка в работе агента {agent_name}: {str(e)}"
        return state

    def _call_economist(self, state: dict) -> dict:
        return self._call_agent_template(state, "economist")

    def _call_purchaser(self, state: dict) -> dict:
        return self._call_agent_template(state, "purchaser")

    def _call_accountant(self, state: dict) -> dict:
        return self._call_agent_template(state, "accountant")

    def _call_support(self, state: dict) -> dict:
        return self._call_agent_template(state, "support")

    def _call_smm(self, state: dict) -> dict:
        return self._call_agent_template(state, "smm")

    def _call_website(self, state: dict) -> dict:
        return self._call_agent_template(state, "website")
    
    def _call_developer_assistant(self, state: dict) -> dict:
        try:
            from agents.developer_assistant import DeveloperAssistant
            agent = DeveloperAssistant()
            result = agent.process(state)
            state["result"] = result.get("result", "")
        except Exception as e:
            logging.error(f"Ошибка при вызове агента разработчика: {e}")
            state["result"] = f"Ошибка в работе агента разработчика: {str(e)}"
        return state
    
    def _call_parser(self, state: dict) -> dict:
        try:
            from agents.parser_agent import ParserAgent
            agent = ParserAgent()
            result = agent.process(state)
            state["result"] = result.get("result", "")
        except Exception as e:
            logging.error(f"Ошибка при вызове агента-парсера: {e}")
            state["result"] = f"Ошибка в работе агента-парсера: {str(e)}"
        return state

    def process(self, query: str, interface: str = "user", history: List[Dict] = None) -> Dict[str, Any]:
        if history is None:
            history = []
        initial_state = AgentState(
            query=query,
            agent_type=AgentType.ECONOMIST.value,
            context="",
            result="",
            next_agent="",
            interface=interface,
            history=history
        )
        try:
            final_state = self.graph.invoke(initial_state)
            
            # Извлекаем рассуждения из контекста или результата
            reasoning = []
            context = final_state.get("context", "")
            result = final_state.get("result", "")
            
            # Если в контексте есть информация о поиске, добавляем её как рассуждение
            if context:
                # Извлекаем информацию о найденных файлах
                import re
                file_matches = re.findall(r'📁 Файл: (.+?)\n', context)
                if file_matches:
                    reasoning.append(f"Найдено {len(file_matches)} релевантных файлов:")
                    for i, file_path in enumerate(file_matches[:3], 1):
                        reasoning.append(f"  {i}. {file_path}")
                    if len(file_matches) > 3:
                        reasoning.append(f"  ... и ещё {len(file_matches) - 3} файлов")
            
            # Добавляем информацию о выбранном агенте
            agent = final_state.get("agent_type", "")
            reasoning.append(f"Выбран агент: {agent}")
            
            # Добавляем информацию о поиске контекста
            if context:
                reasoning.append(f"Поиск контекста выполнен успешно")
            
            return {
                "success": True,
                "result": result,
                "agent": agent,
                "context": context,
                "reasoning": reasoning
            }
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
                        
                        # Запуск планового анализа кода агентов
                        logging.info("🔍 Запуск планового анализа кода агентов...")
                        try:
                            state = {
                                "query": "Проанализируй всех агентов в папке agents/, найди ошибки, неиспользуемые импорты, нарушения стиля. Предложи исправления. Если ошибки критичны и исправления очевидны, внеси их самостоятельно.",
                                "interface": "dev",
                                "history": []
                            }
                            # Вызвать агента-разработчика
                            result = self._call_developer_assistant(state)
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