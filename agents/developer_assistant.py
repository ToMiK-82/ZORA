"""
Агент-ассистент разработчика для проекта ZORA.
Рефлексивная версия с циклом выполнения инструментов (ReAct).
"""

import logging
import json
import asyncio
import re
import sys
import os
import subprocess
import tempfile
import ast
import importlib.util
from typing import Dict, Any, List

from agents.base import BaseAgent
from core.roles import AgentRole, get_system_prompt
from connectors.llm_client_distributed import generate_sync as llm_generate
from core.model_selector import get_selector

try:
    from memory import memory
    MEMORY_AVAILABLE = True
except ImportError:
    MEMORY_AVAILABLE = False
    memory = None

from tools.file_ops import read_file, write_file, list_directory
from tools.shell import run_command
from tools.browser import (
    get_page_text, get_page_html, click_element, fill_input,
    perform_actions, close_browser, get_current_url, take_screenshot
)
from tools.desktop_automation import (
    get_screenshot, find_window_by_title, click_at_coords, 
    type_text, click_on_text, get_window_list, move_window,
    resize_window, get_mouse_position, press_key, hotkey, scroll
)
import socket
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)


class DeveloperAssistant(BaseAgent):
    """Рефлексивный ассистент разработчика с циклом выполнения инструментов."""

    def __init__(self):
        super().__init__(AgentRole.DEVELOPER_ASSISTANT.value)
        self.logger = logging.getLogger("zora.agent.developer_assistant")
        self.system_prompt = get_system_prompt(AgentRole.DEVELOPER_ASSISTANT)
        self.last_actions = []

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        query = state.get("query", "")
        context = state.get("context", "")
        history = state.get("history", [])
        # Динамический выбор модели через ModelSelector
        selector = get_selector()
        model_info = selector.select_planner(query)
        model = state.get("model", model_info.get("model", "qwen3:8b"))
        provider = state.get("provider", model_info.get("provider", "ollama"))
        return self._process_specific(query, context, history, model, provider)

    def _process_specific(self, query: str, context: str, history: List[Dict],
                          model: str, provider: str) -> Dict[str, Any]:
        if query is None:
            query = ""
        if context is None:
            context = ""
        if history is None:
            history = []

        if not context and MEMORY_AVAILABLE and memory:
            context = self._retrieve_context(query)

        lessons = self._retrieve_lessons(query)

        current_prompt = self._build_reflective_prompt(query, context, history, lessons)
        iteration = 0
        max_iterations = 5
        all_actions_results = []

        while iteration < max_iterations:
            iteration += 1
            self.logger.info(f"Итерация {iteration}")

            try:
                response = llm_generate(
                    current_prompt,
                    model=model,
                    provider=provider,
                    temperature=0.5
                )
                if isinstance(response, dict) and "error" in response:
                    return {
                        "success": False,
                        "result": f"Ошибка LLM: {response['error']}",
                        "agent": self.agent_name,
                        "context_used": bool(context)
                    }

                result_text = response.get("text", str(response)) if isinstance(response, dict) else str(response)

                reasoning = self._extract_reasoning(result_text)
                if reasoning and MEMORY_AVAILABLE and memory:
                    try:
                        memory.store(
                            text=f"Query: {query}\nReasoning: {reasoning}",
                            metadata={"type": "reasoning", "agent": self.agent_name, "timestamp": None}
                        )
                    except Exception as e:
                        self.logger.warning(f"Не удалось сохранить reasoning: {e}")

                if self._should_execute_tools(result_text):
                    if self._is_looping(result_text):
                        break

                    exec_result = self._execute_tools_from_response(result_text, query, context)
                    actions_summary = exec_result.get("result", "")
                    all_actions_results.append(actions_summary)

                    current_prompt = self._build_continuation_prompt(
                        query=query,
                        context=context,
                        history=history,
                        lessons=lessons,
                        previous_response=result_text,
                        actions_result=actions_summary
                    )
                    continue

                cleaned_result = self._post_process_response(result_text, query, reasoning)
                return {
                    "success": True,
                    "result": cleaned_result,
                    "agent": self.agent_name,
                    "context_used": bool(context),
                    "tools_used": len(all_actions_results) > 0,
                    "reasoning": reasoning,
                    "iterations": iteration,
                    "original_response": result_text[:500] + "..." if len(result_text) > 500 else result_text
                }

            except Exception as e:
                self.logger.error(f"Ошибка в итерации {iteration}: {e}")
                return {
                    "success": False,
                    "result": f"Ошибка: {str(e)}",
                    "agent": self.agent_name,
                    "context_used": bool(context),
                    "error": str(e)
                }

        return {
            "success": True,
            "result": f"Достигнут лимит итераций ({max_iterations}). Последние действия:\n" + "\n".join(all_actions_results[-3:]),
            "agent": self.agent_name,
            "context_used": bool(context),
            "tools_used": True,
            "max_iterations_reached": True
        }

    def _build_continuation_prompt(self, query: str, context: str, history: List[Dict],
                                   lessons: str, previous_response: str, actions_result: str) -> str:
        prompt_parts = []
        if history:
            history_str = "\n".join(
                f"{msg.get('role', 'unknown')}: {msg.get('content', '')}"
                for msg in history[-10:]
            )
            prompt_parts.append(f"## История диалога\n{history_str}\n")

        prompt_parts.append(f"## Контекст из памяти\n{context if context else 'Отсутствует.'}\n")
        if lessons:
            prompt_parts.append(f"## Извлечённые уроки\n{lessons}\n")

        prompt_parts.append(f"""
## Твои предыдущие рассуждения и действия
{previous_response}

## Результаты выполненных действий
{actions_result}

## Инструкция
Теперь, основываясь на результатах, продолжи анализ.
- Если тебе нужно прочитать ещё файлы или выполнить другие действия — напиши следующий ACTION.
- Если у тебя достаточно информации для ответа — напиши финальный ответ (без ACTION).
- Не повторяй уже выполненные действия.

## Запрос пользователя (оригинальный)
{query}

## Твой следующий шаг (начни с блока РАССУЖДЕНИЯ:)
""")
        return "\n".join(prompt_parts)

    def _build_reflective_prompt(self, query: str, context: str, history: List[Dict], lessons: str) -> str:
        prompt_parts = []

        if history:
            recent_history = history[-3:]
            history_str = "\n".join(
                f"{msg.get('role', 'user' if msg.get('role') == 'user' else 'assistant')}: {msg.get('content', '')}"
                for msg in recent_history
            )
            prompt_parts.append(f"## История диалога (последние сообщения)\n{history_str}\n")

        if context:
            prompt_parts.append(f"## Контекст из памяти\n{context}\n")

        if lessons:
            prompt_parts.append(f"## Извлечённые уроки\n{lessons}\n")

        prompt_parts.append(f"""
## Твоя роль
Ты — **Ria**, интеллектуальный ассистент системы ZORA. Твоя задача — давать точные, полезные и краткие ответы, а также активно помогать в разработке: искать код, анализировать структуру проекта, запускать тесты, проверять стиль кода и работать с Git.

## Инструкции по ответу
1. **Сначала подумай** (блок РАССУЖДЕНИЯ:):
   - Кратко проанализируй запрос
   - Определи, какая информация нужна
   - Реши, нужны ли инструменты

2. **Затем действуй или отвечай**:
   - Если нужны данные извне → используй инструменты
   - Если есть вся информация → дай прямой ответ
   - Будь краток и точен

3. **Формат инструментов** (только если нужно):
   ACTION: название_инструмента
   DETAILS: параметры

   Доступные инструменты:
   - `read_file(путь)` – прочитать файл
   - `write_file(путь||текст)` – записать файл
   - `list_dir(путь)` – список файлов в папке
   - `run_command(команда)` – выполнить shell-команду
   - `search_code(ключевое_слово)` – поиск текста во всех .py файлах
   - `lint_file(путь)` – проверить файл линтером (flake8/pylint)
   - `project_tree(глубина)` – показать дерево папок проекта (например, 3)
   - `git_status()` – статус Git репозитория
   - `eval_python(код)` – выполнить небольшой Python-скрипт
   - `check_internet()` – диагностика интернета
   - `get_page_html(URL)` – получить HTML страницы
   - `ast_analyze(путь)` – анализ Python-файла через AST (поиск неиспользуемых импортов, функций, переменных)
   - `check_imports(путь)` – проверка корректности импортов в Python-файле
   - `run_pytest(путь_к_тестам)` – запуск pytest для тестирования кода

4. **Автономный анализ кода**:
   Если пользователь просит «проверить проект», «проанализировать агентов» или «найти ошибки в коде», действуй автономно по плану:
   1. Используй `list_dir` для получения списка всех Python-файлов в целевой папке (например, `agents/`).
   2. Для каждого файла выполни:
      - `read_file` для ознакомления с содержимым
      - `lint_file` для проверки стиля и базовых ошибок
      - `ast_analyze` для поиска неиспользуемых импортов и переменных
      - `check_imports` для проверки корректности импортов
   3. Собери все найденные проблемы в единый отчёт.
   4. Для каждой проблемы предложи конкретное исправление. Если исправление безопасно (удаление неиспользуемого импорта, добавление docstring), применяй его немедленно через `write_file`.
   5. По окончании выведи итоговую статистику: сколько файлов проверено, сколько проблем найдено, сколько исправлено.

5. **Важные правила**:
   - Отвечай на русском языке
   - Будь конкретным и полезным
   - Не повторяй одни и те же действия
   - Если инструмент вернул ошибку → объясни причину и предложи альтернативу
   - При автономном анализе кода применяй безопасные исправления без дополнительного подтверждения

## Запрос пользователя
{query}

## Твой ответ (начни с РАССУЖДЕНИЯ:)
""")
        return "\n".join(prompt_parts)

    def _extract_reasoning(self, text: str) -> str:
        if "РАССУЖДЕНИЯ:" in text:
            parts = text.split("РАССУЖДЕНИЯ:", 1)
            if len(parts) > 1:
                reasoning_part = parts[1].split("\n\n", 1)[0]
                return reasoning_part.strip()
        return ""

    def _is_looping(self, response_text: str) -> bool:
        actions = re.findall(r"ACTION:\s*(\w+)", response_text)
        if not actions:
            return False
        if self.last_actions == actions:
            return True
        self.last_actions = actions
        return False

    def _retrieve_lessons(self, query: str, limit: int = 3) -> str:
        if not MEMORY_AVAILABLE or memory is None:
            return ""
        try:
            search_query = query + " ошибка не удалось успех lesson feedback good_example"
            results = memory.search(query=search_query, limit=limit)
            lessons = []
            for r in results:
                meta = r.get("metadata", {})
                if meta.get("type") in ("lesson", "error", "feedback", "good_example"):
                    text = r.get("text", "")[:400]
                    lessons.append(f"- {text}")
            return "\n".join(lessons) if lessons else ""
        except Exception as e:
            self.logger.warning(f"Не удалось извлечь уроки: {e}")
            return ""

    def _should_execute_tools(self, response_text: str) -> bool:
        tool_keywords = [
            "ACTION:", "read_file", "write_file", "list_dir", "run_command",
            "search_code", "lint_file", "project_tree", "git_status", "eval_python",
            "get_page_text", "get_page_html", "click_element", "fill_input",
            "perform_actions", "get_current_url", "take_screenshot", "close_browser",
            "check_internet", "project_health_check"
        ]
        return any(keyword in response_text for keyword in tool_keywords)

    def _run_project_health_check(self) -> str:
        """
        Сканирует все .py файлы проекта на наличие типичных проблем:
        - жёстко заданный localhost
        - устаревшие названия моделей (nomic-embed-text, llama2)
        - отсутствие загрузки .env
        - неиспользуемые импорты (через ast)
        Возвращает структурированный отчёт.
        """
        import os
        import re
        import ast
        from pathlib import Path

        issues = []
        project_root = Path(".").resolve()
        py_files = list(project_root.rglob("*.py"))

        excluded_dirs = {"venv", "__pycache__", ".git", "node_modules"}
        py_files = [f for f in py_files if not any(ex in f.parts for ex in excluded_dirs)]

        for file_path in py_files:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                continue

            file_issues = []

            # 1. localhost без переменных окружения
            if re.search(r"localhost:11434|127\.0\.0\.1:11434", content):
                if "OLLAMA_HOST" not in content and "os.getenv" not in content:
                    file_issues.append("  - Жёстко задан localhost:11434 (должен использоваться OLLAMA_HOST из .env)")

            # 2. Устаревшие модели
            if "nomic-embed-text" in content:
                file_issues.append("  - Используется устаревшая модель 'nomic-embed-text' (заменить на 'bge-m3')")
            if "llama2" in content.lower():
                file_issues.append("  - Используется устаревшая модель 'llama2' (заменить на 'llama3.2' или 'qwen3')")

            # 3. Проверка загрузки .env
            if "load_dotenv" not in content and "from dotenv" not in content:
                if "os.getenv" in content:
                    file_issues.append("  - Используется os.getenv, но отсутствует загрузка .env (from dotenv import load_dotenv)")

            # 4. AST-анализ неиспользуемых импортов
            try:
                tree = ast.parse(content)
                imported_names = set()
                used_names = set()

                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            imported_names.add(alias.name.split('.')[0])
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            imported_names.add(node.module.split('.')[0])
                        for alias in node.names:
                            imported_names.add(alias.name)
                    elif isinstance(node, ast.Name):
                        used_names.add(node.id)

                unused = imported_names - used_names
                if unused and not any(x in content for x in ["@", "register", "plugin"]):
                    file_issues.append(f"  - Возможно неиспользуемые импорты: {', '.join(list(unused)[:5])}")
            except:
                pass

            if file_issues:
                issues.append(f"\n📁 Файл: {file_path}")
                issues.extend(file_issues)

        if not issues:
            return "✅ Проект в хорошем состоянии: критических проблем не найдено."
        else:
            return "🔍 Найдены потенциальные проблемы:\n" + "\n".join(issues)

    def _execute_tools_from_response(self, response_text: str, original_query: str, context: str) -> Dict[str, Any]:
        self.logger.info("Выполнение инструментов на основе ответа LLM")
        lines = response_text.strip().split('\n')
        actions = []
        current_action = None
        current_details = None

        for line in lines:
            if line.startswith("ACTION:"):
                if current_action and current_details:
                    actions.append((current_action, current_details))
                current_action = line.split(":", 1)[1].strip()
                current_details = ""
            elif line.startswith("DETAILS:") and current_action:
                current_details = line.split(":", 1)[1].strip()
            elif current_action and current_details is not None:
                current_details += "\n" + line

        if current_action and current_details:
            actions.append((current_action, current_details))

        results = []
        for action, details in actions:
            try:
                result = self._run_async(self._execute_single_action_with_timeout(action, details))
                results.append(f"✅ {action}: {result}")
            except asyncio.TimeoutError:
                results.append(f"❌ {action}: таймаут (120 сек)")
            except Exception as e:
                results.append(f"❌ {action}: ошибка - {str(e)}")

        if results:
            return {
                "success": True,
                "result": "Выполнены действия:\n" + "\n".join(results),
                "agent": self.agent_name,
                "context_used": bool(context),
                "tools_executed": True,
                "actions_count": len(actions)
            }
        return {
            "success": True,
            "result": response_text,
            "agent": self.agent_name,
            "context_used": bool(context),
            "tools_executed": False
        }

    async def _execute_single_action_with_timeout(self, action: str, details: str) -> str:
        return await asyncio.wait_for(
            self._execute_single_action(action, details),
            timeout=120.0
        )

    async def _execute_single_action(self, action: str, details: str) -> str:
        if action == "read_file":
            return read_file(details)
        elif action == "write_file":
            parts = details.split("||", 1)
            if len(parts) == 2:
                return write_file(parts[0], parts[1])
            return "Ошибка: неверный формат DETAILS для write_file. Используйте: путь||содержимое"
        elif action == "list_dir":
            return list_directory(details)
        elif action == "run_command":
            if sys.platform == "win32":
                details = f'chcp 65001 > nul && {details}'
            return run_command(details)

        elif action == "get_page_text":
            return await get_page_text(details)
        elif action == "get_page_html":
            return await get_page_html(details)
        elif action == "click_element":
            return await click_element(details)
        elif action == "fill_input":
            parts = details.split("||", 1)
            if len(parts) == 2:
                return await fill_input(parts[0], parts[1])
            return "Ошибка: неверный формат DETAILS для fill_input. Используйте: селектор||значение"
        elif action == "perform_actions":
            try:
                actions = json.loads(details)
                return perform_actions(actions)
            except json.JSONDecodeError as e:
                return f"Ошибка парсинга JSON: {e}"
        elif action == "get_current_url":
            return get_current_url()
        elif action == "take_screenshot":
            return take_screenshot(details if details else "screenshot.png")
        elif action == "close_browser":
            return close_browser()

        elif action == "search_code":
            keyword = details.strip()
            try:
                if sys.platform == "win32":
                    cmd = f'findstr /s /n /i /c:"{keyword}" *.py'
                else:
                    cmd = f'grep -r -n -i "{keyword}" --include="*.py" .'
                result = subprocess.run(cmd, capture_output=True, text=True, shell=True, timeout=30)
                if result.stdout:
                    lines = result.stdout.strip().split('\n')[:20]
                    return "Найдены совпадения:\n" + "\n".join(lines)
                else:
                    return f"Совпадений для '{keyword}' не найдено"
            except Exception as e:
                return f"Ошибка поиска: {e}"

        elif action == "lint_file":
            file_path = details.strip()
            try:
                cmd = f"flake8 {file_path}"
                result = subprocess.run(cmd, capture_output=True, text=True, shell=True, timeout=30)
                if result.returncode == 0:
                    return f"✅ Линтинг {file_path}: ошибок не найдено"
                else:
                    return f"⚠️ Найдены проблемы:\n{result.stdout}"
            except Exception as e:
                return f"Ошибка запуска линтера: {e}"

        elif action == "project_tree":
            max_depth = int(details) if details.isdigit() else 3
            def tree(dir_path, prefix="", depth=0):
                if depth > max_depth:
                    return ""
                lines = []
                try:
                    items = sorted(os.listdir(dir_path))
                except PermissionError:
                    return ""
                for i, name in enumerate(items):
                    if name.startswith('.') or name in ['__pycache__', 'node_modules', 'venv', '.git']:
                        continue
                    path = os.path.join(dir_path, name)
                    is_last = i == len(items)-1
                    lines.append(f"{prefix}{'└── ' if is_last else '├── '}{name}")
                    if os.path.isdir(path):
                        ext_prefix = "    " if is_last else "│   "
                        lines.append(tree(path, prefix + ext_prefix, depth+1))
                return "\n".join(filter(None, lines))
            return "Структура проекта:\n" + tree(".")

        elif action == "git_status":
            try:
                result = subprocess.run("git status --short", capture_output=True, text=True, shell=True, timeout=10)
                if result.stdout:
                    return "Изменённые файлы:\n" + result.stdout
                else:
                    return "Рабочая директория чиста"
            except Exception as e:
                return f"Ошибка Git: {e}"

        elif action == "eval_python":
            code = details
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                tmp_path = f.name
            try:
                result = subprocess.run([sys.executable, tmp_path], capture_output=True, text=True, timeout=10)
                os.unlink(tmp_path)
                if result.returncode == 0:
                    return result.stdout
                else:
                    return f"Ошибка выполнения:\n{result.stderr}"
            except Exception as e:
                return f"Ошибка: {e}"

        elif action == "check_internet":
            return await self._check_internet_connection(details)

        elif action == "project_health_check":
            return self._run_project_health_check()

        # Новые инструменты для анализа кода
        elif action == "ast_analyze":
            file_path = details.strip()
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                tree = ast.parse(content)
                
                # Собираем информацию о файле
                imports = []
                functions = []
                classes = []
                variables = []
                used_names = set()
                
                # Собираем все имена, которые используются
                class NameCollector(ast.NodeVisitor):
                    def visit_Name(self, node):
                        used_names.add(node.id)
                        self.generic_visit(node)
                
                collector = NameCollector()
                collector.visit(tree)
                
                # Анализируем узлы
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            imports.append(alias.name)
                    elif isinstance(node, ast.ImportFrom):
                        module = node.module or ""
                        for alias in node.names:
                            imports.append(f"{module}.{alias.name}" if module else alias.name)
                    elif isinstance(node, ast.FunctionDef):
                        functions.append(node.name)
                    elif isinstance(node, ast.ClassDef):
                        classes.append(node.name)
                    elif isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                variables.append(target.id)
                
                # Находим неиспользуемые импорты, функции и переменные
                unused_imports = [imp for imp in imports if imp.split('.')[-1] not in used_names]
                unused_functions = [func for func in functions if func not in used_names]
                unused_variables = [var for var in variables if var not in used_names]
                
                report = {
                    "file": file_path,
                    "imports_count": len(imports),
                    "functions_count": len(functions),
                    "classes_count": len(classes),
                    "variables_count": len(variables),
                    "unused_imports": unused_imports,
                    "unused_functions": unused_functions,
                    "unused_variables": unused_variables,
                    "total_unused": len(unused_imports) + len(unused_functions) + len(unused_variables)
                }
                
                # Форматируем отчёт
                result = f"📊 AST-анализ файла: {file_path}\n"
                result += f"📈 Статистика: {len(imports)} импортов, {len(functions)} функций, {len(classes)} классов, {len(variables)} переменных\n"
                
                if unused_imports:
                    result += f"⚠️ Неиспользуемые импорты ({len(unused_imports)}):\n"
                    for imp in unused_imports:
                        result += f"   - {imp}\n"
                
                if unused_functions:
                    result += f"⚠️ Неиспользуемые функции ({len(unused_functions)}):\n"
                    for func in unused_functions:
                        result += f"   - {func}\n"
                
                if unused_variables:
                    result += f"⚠️ Неиспользуемые переменные ({len(unused_variables)}):\n"
                    for var in unused_variables:
                        result += f"   - {var}\n"
                
                if not unused_imports and not unused_functions and not unused_variables:
                    result += "✅ Все импорты, функции и переменные используются\n"
                
                return result
                
            except FileNotFoundError:
                return f"❌ Файл не найден: {file_path}"
            except SyntaxError as e:
                return f"❌ Синтаксическая ошибка в файле: {e}"
            except Exception as e:
                return f"❌ Ошибка AST-анализа: {e}"

        elif action == "check_imports":
            file_path = details.strip()
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                tree = ast.parse(content)
                import_errors = []
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            module_name = alias.name
                            try:
                                spec = importlib.util.find_spec(module_name)
                                if spec is None:
                                    import_errors.append(f"❌ Модуль не найден: {module_name}")
                            except Exception:
                                import_errors.append(f"❌ Ошибка при проверке модуля: {module_name}")
                    
                    elif isinstance(node, ast.ImportFrom):
                        module_name = node.module or ""
                        for alias in node.names:
                            full_name = f"{module_name}.{alias.name}" if module_name else alias.name
                            try:
                                # Пробуем импортировать модуль
                                if module_name:
                                    spec = importlib.util.find_spec(module_name)
                                    if spec is None:
                                        import_errors.append(f"❌ Модуль не найден: {module_name}")
                                # Проверяем, существует ли атрибут в модуле
                                # (это сложная проверка, поэтому просто отмечаем)
                            except Exception:
                                import_errors.append(f"❌ Ошибка при проверке импорта: {full_name}")
                
                if import_errors:
                    result = f"🔍 Проверка импортов в файле: {file_path}\n"
                    result += "⚠️ Найдены проблемы:\n"
                    for error in import_errors:
                        result += f"   {error}\n"
                    result += f"\nВсего проблем: {len(import_errors)}"
                else:
                    result = f"✅ Все импорты в файле {file_path} корректны"
                
                return result
                
            except FileNotFoundError:
                return f"❌ Файл не найден: {file_path}"
            except SyntaxError as e:
                return f"❌ Синтаксическая ошибка в файле: {e}"
            except Exception as e:
                return f"❌ Ошибка проверки импортов: {e}"

        elif action == "run_pytest":
            test_path = details.strip() if details.strip() else "."
            try:
                # Проверяем, установлен ли pytest
                import pytest
                
                cmd = f"pytest {test_path} -q"
                result = subprocess.run(cmd, capture_output=True, text=True, shell=True, timeout=60)
                
                if result.returncode == 0:
                    # Парсим вывод pytest
                    lines = result.stdout.strip().split('\n')
                    passed = 0
                    failed = 0
                    skipped = 0
                    
                    for line in lines:
                        if "passed" in line and "failed" not in line:
                            # Пример: "3 passed in 0.01s"
                            parts = line.split()
                            for part in parts:
                                if part.isdigit():
                                    passed = int(part)
                                    break
                        elif "failed" in line:
                            parts = line.split()
                            for part in parts:
                                if part.isdigit():
                                    failed = int(part)
                                    break
                        elif "skipped" in line:
                            parts = line.split()
                            for part in parts:
                                if part.isdigit():
                                    skipped = int(part)
                                    break
                    
                    result_text = f"✅ Тесты пройдены успешно\n"
                    result_text += f"📊 Результаты: {passed} пройдено"
                    if failed > 0:
                        result_text += f", {failed} упало"
                    if skipped > 0:
                        result_text += f", {skipped} пропущено"
                    
                    return result_text
                else:
                    # Есть ошибки
                    error_lines = []
                    for line in result.stdout.split('\n') + result.stderr.split('\n'):
                        if "FAILED" in line or "ERROR" in line or "AssertionError" in line:
                            error_lines.append(line.strip())
                    
                    result_text = f"❌ Тесты не пройдены\n"
                    result_text += f"📊 Вывод pytest:\n{result.stdout[:500]}"
                    if error_lines:
                        result_text += f"\n\n⚠️ Основные ошибки:\n"
                        for error in error_lines[:5]:
                            result_text += f"   - {error}\n"
                    
                    return result_text
                    
            except ImportError:
                return "⚠️ Pytest не установлен. Установите: pip install pytest"
            except subprocess.TimeoutExpired:
                return "❌ Таймаут выполнения тестов (60 секунд)"
            except Exception as e:
                return f"❌ Ошибка запуска pytest: {e}"

        # Новые UI-инструменты для автоматизации рабочего стола
        elif action == "click_coords":
            try:
                x, y = map(int, details.split(','))
                return click_at_coords(x, y)
            except ValueError:
                return "❌ Ошибка: координаты должны быть в формате 'x,y'"
            except Exception as e:
                return f"❌ Ошибка при клике по координатам: {e}"

        elif action == "type_text":
            return type_text(details)

        elif action == "find_window":
            win = find_window_by_title(details)
            if win:
                return f"✅ Окно активировано: {win.title}"
            else:
                return f"❌ Окно с текстом '{details}' не найдено"

        elif action == "click_on_text":
            success = click_on_text(details)
            if success:
                return "✅ Клик выполнен по элементу с текстом"
            else:
                return f"❌ Элемент с текстом '{details}' не найден"

        elif action == "get_screenshot":
            try:
                img = get_screenshot()
                path = details if details else "screenshot.png"
                img.save(path)
                return f"✅ Скриншот сохранён: {path}"
            except Exception as e:
                return f"❌ Ошибка при создании скриншота: {e}"

        elif action == "list_windows":
            try:
                windows = get_window_list()
                if windows:
                    result = "📋 Открытые окна:\n"
                    for i, win in enumerate(windows[:10], 1):
                        result += f"{i}. {win['title']} ({win['width']}x{win['height']}) {'[активно]' if win['is_active'] else ''}\n"
                    if len(windows) > 10:
                        result += f"... и ещё {len(windows) - 10} окон\n"
                    return result
                else:
                    return "❌ Не удалось получить список окон"
            except Exception as e:
                return f"❌ Ошибка при получении списка окон: {e}"

        elif action == "move_window":
            try:
                parts = details.split(',')
                if len(parts) == 3:
                    title = parts[0].strip()
                    x = int(parts[1].strip())
                    y = int(parts[2].strip())
                    return move_window(title, x, y)
                else:
                    return "❌ Ошибка: формат должен быть 'заголовок,x,y'"
            except Exception as e:
                return f"❌ Ошибка при перемещении окна: {e}"

        elif action == "resize_window":
            try:
                parts = details.split(',')
                if len(parts) == 3:
                    title = parts[0].strip()
                    width = int(parts[1].strip())
                    height = int(parts[2].strip())
                    return resize_window(title, width, height)
                else:
                    return "❌ Ошибка: формат должен быть 'заголовок,ширина,высота'"
            except Exception as e:
                return f"❌ Ошибка при изменении размера окна: {e}"

        elif action == "get_mouse_position":
            try:
                pos = get_mouse_position()
                return f"📍 Позиция мыши: x={pos['x']}, y={pos['y']}"
            except Exception as e:
                return f"❌ Ошибка при получении позиции мыши: {e}"

        elif action == "press_key":
            return press_key(details)

        elif action == "hotkey":
            try:
                keys = details.split(',')
                return hotkey(*[k.strip() for k in keys])
            except Exception as e:
                return f"❌ Ошибка при нажатии комбинации клавиш: {e}"

        elif action == "scroll":
            try:
                amount = int(details)
                return scroll(amount)
            except ValueError:
                return "❌ Ошибка: количество прокруток должно быть числом"
            except Exception as e:
                return f"❌ Ошибка при прокрутке: {e}"

        elif action == "find_element_by_vision":
            description = details.strip()
            try:
                # 1. Создаём скриншот
                img = get_screenshot()
                temp_path = "temp_vision.png"
                img.save(temp_path)
                
                # 2. Подготавливаем промпт для vision-модели
                prompt = f"На изображении найди элемент интерфейса: '{description}'. Верни координаты его центра в формате 'x,y' и ничего больше."
                
                # 3. Отправляем в vision-модель (qwen3-vl:4b)
                try:
                    # Пробуем использовать llm_generate с поддержкой изображений
                    response = llm_generate(
                        prompt=prompt,
                        model="qwen3-vl:4b",
                        provider="ollama",
                        temperature=0.1,
                        # Предполагаем, что llm_generate поддерживает передачу изображений
                        # Если нет, нужно будет доработать connectors/llm_client_distributed.py
                        image_path=temp_path
                    )
                    
                    # 4. Парсим ответ
                    import re
                    response_text = response.get("text", str(response)) if isinstance(response, dict) else str(response)
                    match = re.search(r'(\d+)\s*,\s*(\d+)', response_text)
                    
                    if match:
                        x, y = int(match.group(1)), int(match.group(2))
                        # Удаляем временный файл
                        try:
                            os.remove(temp_path)
                        except:
                            pass
                        return f"✅ Координаты элемента: {x}, {y}"
                    else:
                        # Удаляем временный файл
                        try:
                            os.remove(temp_path)
                        except:
                            pass
                        return f"❌ Не удалось найти координаты элемента. Ответ модели: {response_text[:200]}"
                        
                except Exception as e:
                    # Удаляем временный файл
                    try:
                        os.remove(temp_path)
                    except:
                        pass
                    return f"❌ Ошибка при вызове vision-модели: {e}"
                    
            except Exception as e:
                return f"❌ Ошибка при поиске элемента по vision: {e}"

        else:
            return f"Неизвестное действие: {action}"

    def _run_async(self, coro):
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)

    async def _check_internet_connection(self, details: str = "") -> str:
        import time
        import concurrent.futures

        results = ["🔍 Диагностика подключения к интернету:"]

        try:
            import requests
            results.append("✅ Библиотека requests установлена")
        except ImportError:
            results.append("❌ Библиотека requests не установлена (pip install requests)")

        try:
            from bs4 import BeautifulSoup
            results.append("✅ Библиотека beautifulsoup4 установлена")
        except ImportError:
            results.append("⚠️ Библиотека beautifulsoup4 не установлена")

        try:
            import zendriver
            results.append("✅ Библиотека zendriver установлена")
        except ImportError:
            results.append("⚠️ Библиотека zendriver не установлена")

        test_urls = [
            "https://www.google.com",
            "https://www.github.com",
            "https://www.cloudflare.com",
            "https://www.cbr.ru"
        ]

        if details:
            custom_urls = [url.strip() for url in details.split(",") if url.strip()]
            test_urls = custom_urls + test_urls

        def check_url(url):
            try:
                start_time = time.time()
                try:
                    import requests
                    headers = {'User-Agent': 'Mozilla/5.0'}
                    response = requests.get(url, headers=headers, timeout=10)
                    status = response.status_code
                    end_time = time.time()
                    response_time = (end_time - start_time) * 1000
                    return url, True, status, response_time, len(response.text)
                except ImportError:
                    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req, timeout=10) as response:
                        status = response.getcode()
                        end_time = time.time()
                        response_time = (end_time - start_time) * 1000
                        content_length = len(response.read())
                        return url, True, status, response_time, content_length
            except Exception as e:
                return url, False, str(e), 0, 0

        results.append("\n🌐 Проверка доступности сайтов:")
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_url = {executor.submit(check_url, url): url for url in test_urls}
            for future in concurrent.futures.as_completed(future_to_url):
                url, success, status, response_time, content_length = future.result()
                if success:
                    results.append(f"✅ {url}: доступен (статус {status}, время {response_time:.0f} мс, размер {content_length} байт)")
                else:
                    results.append(f"❌ {url}: недоступен ({status})")

        results.append("\n🔧 Проверка сетевых служб:")
        try:
            socket.gethostbyname("google.com")
            results.append("✅ DNS: работает")
        except socket.gaierror:
            results.append("❌ DNS: не работает")

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex(("8.8.8.8", 53))
            sock.close()
            if result == 0:
                results.append("✅ Внешняя сеть: доступна")
            else:
                results.append("⚠️ Внешняя сеть: возможны проблемы с фаерволом")
        except:
            results.append("⚠️ Внешняя сеть: не удалось проверить")

        return "\n".join(results)

    def _retrieve_context(self, query: str, limit: int = 5) -> str:
        if not MEMORY_AVAILABLE or memory is None:
            self.logger.warning("Память недоступна")
            return ""
        try:
            results = memory.search(query=query, limit=limit * 2)
            if not results:
                return ""
            grouped = {}
            for r in results:
                path = r.get("path", "unknown")
                grouped.setdefault(path, []).append(r)
            parts = []
            for path, file_results in list(grouped.items())[:limit]:
                parts.append(f"\n📁 Файл: {path}")
                for i, r in enumerate(file_results[:3], 1):
                    text = r.get("text", "")
                    score = r.get("score", 0)
                    if len(text) > 500:
                        text = text[:500] + "..."
                    parts.append(f"  [{i}] Сходство: {score:.2f}\n     {text}")
            context = "\n".join(parts)
            if context:
                context = "📚 РЕЛЕВАНТНЫЙ КОНТЕКСТ ИЗ ПАМЯТИ:\n" + context
            return context
        except Exception as e:
            self.logger.error(f"Ошибка при извлечении контекста: {e}")
            return ""

    def _post_process_response(self, response_text: str, query: str, reasoning: str = "") -> str:
        self.logger.info("Пост-обработка ответа")

        if len(response_text) < 300 and "ACTION:" not in response_text:
            return response_text

        if "РАССУЖДЕНИЯ:" in response_text:
            parts = response_text.split("РАССУЖДЕНИЯ:", 1)
            if len(parts) > 1:
                main_part = parts[1].split("\n\n", 1)
                if len(main_part) > 1:
                    response_text = main_part[1]
                else:
                    response_text = main_part[0]

        patterns_to_remove = [
            r"ACTION:.*?\nDETAILS:.*?(?=\n\n|\nACTION:|$)",
            r"## Инструкция.*?(?=\n##|\n\n|$)",
            r"## Твоя роль.*?(?=\n##|\n\n|$)",
            r"## Формат инструментов.*?(?=\n##|\n\n|$)",
            r"Доступные инструменты:.*?(?=\n##|\n\n|$)",
            r"Важные правила:.*?(?=\n##|\n\n|$)",
            r"Если инструмент вернул ошибку.*?(?=\n|$)",
            r"Будь конкретным и полезным.*?(?=\n|$)",
            r"Отвечай на русском языке.*?(?=\n|$)",
            r"Не повторяй одни и те же действия.*?(?=\n|$)",
        ]

        for pattern in patterns_to_remove:
            response_text = re.sub(pattern, "", response_text, flags=re.DOTALL | re.IGNORECASE)

        lines = response_text.split('\n')
        cleaned_lines = []
        for line in lines:
            line = line.strip()
            if line and not line.startswith(('Note:', 'Примечание:', 'TODO:', 'FIXME:')):
                line = re.sub(r'<[^>]+>', '', line)
                if not re.match(r'^```\w*$', line):
                    cleaned_lines.append(line)

        response_text = '\n'.join(cleaned_lines)

        if len(response_text) > 1000:
            sentences = re.split(r'[.!?]+', response_text)
            if len(sentences) > 3:
                response_text = '. '.join(sentences[:3]) + '.'
                response_text += "\n\n*(Ответ сокращен для удобства чтения)*"

        if reasoning and len(reasoning) < 100:
            response_text = f"💭 {reasoning}\n\n{response_text}"

        if "История диалога:" in response_text or "История диалога (последние сообщения):" in response_text:
            response_text = re.sub(r'## История диалога.*?(?=\n##|\n\n|$)', '', response_text, flags=re.DOTALL)

        if "РЕЛЕВАНТНЫЙ КОНТЕКСТ ИЗ ПАМЯТИ:" in response_text:
            response_text = re.sub(r'📚 РЕЛЕВАНТНЫЙ КОНТЕКСТ ИЗ ПАМЯТИ:.*?(?=\n##|\n\n|$)', '', response_text, flags=re.DOTALL)

        if '```' in response_text:
            code_blocks = response_text.split('```')
            if len(code_blocks) % 2 == 1:
                response_text += '```'

        response_text = re.sub(r'\n\s*\n\s*\n+', '\n\n', response_text)

        if len(response_text) > 2000:
            response_text = response_text[:2000] + "...\n\n*(Ответ обрезан для удобства чтения)*"

        return response_text.strip()