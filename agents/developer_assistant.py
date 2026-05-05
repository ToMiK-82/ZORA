"""
Агент-ассистент разработчика с двухуровневой архитектурой:
Plan: DeepSeek Reasoner/API → Act: llama3.2:latest (локально)
С поддержкой многошагового выполнения сложных задач.
"""

import json
import logging
import os
import re
from datetime import datetime
from typing import Dict, Any, List

from agents.base import BaseAgent
from core.roles import AgentRole, get_system_prompt
from core.model_selector import get_selector

from connectors.llm_client_distributed import generate_sync as local_generate
from connectors.llm_client_distributed import llm_client, LLMProvider
from tools.file_ops import read_file, write_file, list_directory
from tools.shell import run_command

try:
    from memory import memory
    MEMORY_AVAILABLE = True
except ImportError:
    MEMORY_AVAILABLE = False
    memory = None

logger = logging.getLogger(__name__)

# Директория для хранения полных диалогов
DIALOGUES_DIR = "data/dialogues"


class DeveloperAssistant(BaseAgent):
    """Ассистент разработчика с двухуровневой архитектурой Plan/Act."""

    role = AgentRole.DEVELOPER
    display_name = "Разработчик Ria"
    description = "Помогает писать код, анализировать архитектуру, искать информацию в коде и документации"
    tools = ["read_file", "write_file", "list_directory", "run_command", "get_page_text", "get_page_html"]

    def __init__(self):
        super().__init__("Ria")
        self.logger = logging.getLogger("zora.agent.developer_assistant")
        self.selector = get_selector()
        model_info = self.selector.select_executor()
        self.executor_model = model_info.get("model", "llama3.2:latest")
        self.logger.info(f"Ria инициализирована, executor_model={self.executor_model}")
        self.confirmed_plans = set()
        # Кэш для прочитанных файлов (чтобы не читать одно и то же много раз)
        self.read_files_cache = {}

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        query = state.get("query", "")
        context = state.get("context", "")
        history = state.get("history", [])
        return self._process_specific(query, context, history)

    # ======================================================================
    # Основной метод с многошаговым выполнением
    # ======================================================================
    def _process_specific(self, query: str, context: str, history: List[Dict] = None) -> Dict[str, Any]:
        if history is None:
            history = []

        # ===== Режим "объясни" — сначала выполняем действия, потом объясняем =====
        if query.lower().startswith("объясни") or query.lower().startswith("почему"):
            logger.info("🧠 Режим 'объясни' активирован")
            
            # Собираем информацию о текущем состоянии проекта
            info_plan = [
                {"action": "list_dir", "details": "tools"},
                {"action": "read_file", "details": "tools/its_scout.py"},
                {"action": "read_file", "details": "data/its_site_map.json"}
            ]
            
            execution_results = []
            for step in info_plan:
                action = step.get("action")
                details = step.get("details")
                
                # Проверяем существование файла перед read_file
                if action == "read_file" and not os.path.exists(details):
                    execution_results.append(f"⚠️ Файл {details} не найден")
                    continue
                
                try:
                    res = self._call_real_action(action, details)
                    if len(res) > 300:
                        res = res[:300] + "..."
                    execution_results.append(f"✅ {action}: {res}")
                except Exception as e:
                    execution_results.append(f"❌ {action}: {str(e)[:100]}")
            
            info_summary = "\n".join(execution_results)
            
            # Формируем объяснение на основе собранных данных
            explain_prompt = f"""
Ты — Ria. Кратко объясни пользователю, что ты делаешь.

Результаты проверки:
{info_summary}

Ответь в 2-3 предложениях, в женском роде.
"""
            try:
                explanation = local_generate(explain_prompt, model=self.executor_model, temperature=0.5)
            except:
                explanation = "Я проверила состояние проекта. Смотри результаты выше."
            
            return {
                "success": True,
                "result": f"**🧠 Что я делаю:**\n{explanation}\n\n**📊 Результаты проверки:**\n{info_summary}",
                "agent": self.agent_name
            }

        # ===== Долгосрочная память — автоматический поиск по истории =====
        if MEMORY_AVAILABLE and memory and len(query) > 20:
            try:
                history_context = self._retrieve_relevant_history(query)
                if history_context:
                    context = history_context + "\n\n" + context if context else history_context
                    logger.info(f"📚 Добавлен контекст из истории ({len(history_context)} символов)")
            except Exception as e:
                logger.warning(f"Ошибка поиска истории: {e}")

        # Проверка памяти
        if any(phrase in query.lower() for phrase in ["проверь память", "что в памяти", "сколько точек", "есть информация в памяти", "информация появилась"]):
            try:
                from memory import memory as _mem
                info = _mem._memory.client.get_collection(_mem._memory.collection_name)
                count = info.points_count
                return {
                    "success": True,
                    "result": f"📊 **Состояние памяти Qdrant**\n\n"
                              f"- Точки (фрагменты): **{count}**\n"
                              f"- Коллекция: `{_mem._memory.collection_name}`\n\n"
                              f"Типы данных в памяти: код, диалоги, документация, конфиги.\n\n"
                              f"Если нужно найти что-то конкретное, спроси с ключевыми словами.",
                    "agent": self.agent_name
                }
            except Exception as e:
                return {
                    "success": True,
                    "result": f"❌ Ошибка проверки памяти: {str(e)}",
                    "agent": self.agent_name
                }

        if not context and MEMORY_AVAILABLE and memory:
            context = self._retrieve_full_context(query)
            logger.debug(f"Извлечён контекст (длина {len(context)})")

        current_history = history.copy()
        current_history.append({"role": "user", "content": query})

        max_iterations = 15
        iteration = 0
        all_results = []
        final_answer = None
        last_reasoning = None
        last_plan_hash = None

        while iteration < max_iterations:
            iteration += 1
            logger.info(f"🔄 Итерация {iteration}/{max_iterations}")

            result = self._call_intelligent(current_history, context, query)
            
            if result["type"] == "plan":
                plan_hash = json.dumps(result["plan"], sort_keys=True)
                if plan_hash == last_plan_hash:
                    logger.warning("⚠️ Обнаружено повторение плана! Прерываю цикл.")
                    break
                last_plan_hash = plan_hash
                
                needs_confirmation = False
                for step in result["plan"]:
                    action = step.get("action", "")
                    details = step.get("details", "")
                    if not self._is_action_safe(action, details):
                        needs_confirmation = True
                        break
                
                if needs_confirmation:
                    plan_hash = json.dumps(result["plan"], sort_keys=True)
                    if plan_hash in self.confirmed_plans:
                        self.confirmed_plans.discard(plan_hash)
                        logger.info(f"✅ План уже подтверждён, выполняю")
                    else:
                        logger.warning(f"⚠️ План требует подтверждения")
                        return {
                            "success": True,
                            "result": f"⚠️ **Требуется подтверждение**\n\nПлан содержит изменения в файлах конфигурации или опасные команды:\n```json\n{json.dumps(result['plan'], ensure_ascii=False, indent=2)}\n```\n\nПодтверждаете выполнение? (да/нет)",
                            "agent": self.agent_name,
                            "mode": "confirmation_required",
                            "pending_plan": result["plan"]
                        }
                
                logger.info(f"📋 Получен план из {len(result['plan'])} шагов")
                execution_results = self._execute_plan(result["plan"])
                execution_summary = "\n".join(execution_results)
                all_results.append(execution_summary)
                
                # Проверяем, была ли это команда пользователя, которая не требует продолжения
                user_command_keywords = ["создай", "напиши", "запусти", "выполни", "покажи", "прочитай", "удали", "сделай"]
                is_single_command = False
                if query and any(kw in query.lower() for kw in user_command_keywords):
                    is_single_command = True
                    logger.info(f"✅ Обнаружена одноразовая команда, завершаю цикл")
                
                # Также проверяем, что план состоит из 1-2 шагов и все успешны
                if not is_single_command and len(result["plan"]) <= 2 and all(r.startswith('✅') for r in execution_results):
                    is_single_command = True
                    logger.info(f"✅ План из {len(result['plan'])} шагов выполнен успешно, завершаю цикл")
                
                if is_single_command:
                    final_answer = execution_summary
                    break
                
                current_history.append({
                    "role": "system",
                    "content": f"## Результаты выполненных действий\n{execution_summary[:1500]}\n\nПродолжай выполнение задачи."
                })
                
                self._save_execution_summary(query, execution_summary)
                continue
            else:
                final_answer = result["text"]
                current_history.append({"role": "assistant", "content": final_answer})
                last_reasoning = result.get("reasoning")
                break

        try:
            self._save_dialogue_to_json(query, final_answer if final_answer else "\n".join(all_results), current_history)
        except Exception as e:
            logger.warning(f"Не удалось сохранить диалог в JSON: {e}")

        try:
            self._save_semantic_fragment(query, final_answer if final_answer else "\n".join(all_results))
        except Exception as e:
            logger.warning(f"Не удалось сохранить смысловой фрагмент: {e}")

        if final_answer:
            return {
                "success": True,
                "result": final_answer,
                "agent": self.agent_name,
                "iterations": iteration,
                "all_results": all_results if all_results else None,
                "reasoning": last_reasoning
            }
        else:
            return {
                "success": True,
                "result": "\n\n".join(all_results),
                "agent": self.agent_name,
                "iterations": iteration,
                "reasoning": last_reasoning
            }

    # ======================================================================
    # Универсальный метод: DeepSeek сам решает, нужен ли план
    # ======================================================================
    def _call_intelligent(self, history: List[Dict], context: str, query: str = "") -> Dict[str, Any]:
        """Отправляет историю диалога в DeepSeek, при ошибке использует локальную модель."""
        
        max_retries = 2
        
        history_str = ""
        if history:
            last_msgs = history[-10:]
            formatted_msgs = []
            for m in last_msgs:
                role = m.get('role', 'user')
                content = m.get('content', '')
                if len(content) > 800:
                    content = content[:800] + "...[обрезано]"
                formatted_msgs.append(f"{role}: {content}")
            history_str = "\n".join(formatted_msgs)

        system_prompt = """Ты — Ria, AI-ассистент разработчика системы ZORA. Отвечай в женском роде.

## ДОСТУПНЫЕ ИНСТРУМЕНТЫ
- `read_file` — прочитать файл
- `write_file` — создать/изменить файл (с валидацией)
- `delete_file` — удалить файл (требует подтверждения)
- `list_dir` — список файлов
- `run_command` — выполнить команду
- `analyze_data` — анализ уже прочитанных данных
- `git_status`, `git_diff`, `git_diff_staged`, `git_log`, `git_commit`, `git_add` — работа с Git

## КРИТИЧЕСКОЕ ПРАВИЛО: ФОРМАТ WRITE_FILE
Для действия `write_file` используй ТОЛЬКО такой формат:
{"action": "write_file", "details": "путь_к_файлу||содержимое_файла"}

Разделитель — две вертикальные черты (||). НЕ используй поле "content". НЕ используй другие форматы.

Правильные примеры:
- {"action": "write_file", "details": "test.py||print('hello')"}
- {"action": "write_file", "details": "tools/scout.py||import requests"}
- {"action": "write_file", "details": "data/config.json||{\"key\": \"value\"}"}

Неправильные примеры (НЕ ДЕЛАЙ ТАК):
- {"action": "write_file", "details": "test.py", "content": "print('hello')"}  ❌
- {"action": "write_file", "details": "test.py print('hello')"}  ❌
- {"action": "write_file", "details": "test.py"}  ❌

## МАРШРУТИЗАЦИЯ ПО ТИПАМ ЗАДАЧ
| Тип задачи | Модель | Формат ответа |
|---|---|---|
| Исполнитель (create, write, run, git) | llama3.2:latest | JSON-план |
| Советник (анализ, идеи, обсуждение) | llama3.2:latest | Обычный текст |
| Сложное планирование | DeepSeek API | JSON-план |
| Анализ данных | llama3.2:latest | Текст/анализ |

Примеры:
- Пользователь: "создай test.py с print('hi')" → {"plan": [{"action": "write_file", "details": "test.py||print('hi')"}]}
- Пользователь: "что думаешь об архитектуре?" → (текст с анализом)
- Пользователь: "проанализируй its_site_map.json" → {"plan": [{"action": "analyze_data", "details": "its_site_map.json: посчитать страницы"}]}

## ВАЖНО: АНАЛИЗ ДАННЫХ
Когда ты прочитала файл с данными (JSON, CSV, текст) и пользователь просит тебя проанализировать их, НЕ ЧИТАЙ ФАЙЛ СНОВА! 
Используй действие `analyze_data` с параметром, указывающим, что нужно сделать.

### Формат analyze_data:
{"plan": [{"action": "analyze_data", "details": "что нужно сделать"}]}

Пример: "проанализируй its_site_map.json, выведи количество страниц и список разделов"
→ {"plan": [{"action": "analyze_data", "details": "its_site_map.json: посчитать количество страниц, извлечь разделы из URL"}]}

После analyze_data система вернёт тебе результат анализа, который ты можешь использовать.

## ПРАВИЛО ЧТЕНИЯ ФАЙЛОВ

### Когда НУЖНО читать файлы:
1. Пользователь явно просит: "покажи файл X", "прочитай файл X", "открой файл X"
2. Пользователь просит: "проанализируй файл X", "посмотри файл X"
3. Пользователь даёт задачу, которая требует понимания кода: "исправь ошибку в base.py", "добавь функцию в utils.py", "найди баг в модуле memory"

### Когда НЕ НУЖНО читать файлы:
1. Пользователь даёт команду с готовым содержимым: "создай файл X с содержимым Y" — содержимое уже есть, читать не нужно
2. Пользователь даёт команду: "выполни команду X", "запусти скрипт Y"
3. Пользователь просто здоровается или задаёт общий вопрос без указания на конкретный файл

### Важно:
- Если ты не уверена, нужно ли читать файл — лучше сначала спросить пользователя.
- Не читай файлы "про запас" или для "лучшего понимания контекста", если это не требуется для выполнения задачи.
- Если задача требует прочитать файл, а пользователь не дал его имя — спроси: "Какой файл нужно прочитать?"

## ПРАВИЛА ПОВЕДЕНИЯ
1. **Долгосрочная память:** Ты помнишь прошлые диалоги. Используй эту информацию.
2. **Саморефлексия:** Если ты ошиблась, запомни ошибку и не повторяй.
3. **Объяснение:** Когда тебя просят "объясни", сначала покажи рассуждения, потом ответ.
4. **Планирование:** Разбивай сложные задачи на шаги. Не бойся спрашивать уточнения.
5. **Валидация:** После записи файла проверяй, что он создался.
6. Если пользователь пишет "покажи файл X" или "прочитай файл X", ты должна выполнить read_file, даже если этот файл уже был в кэше.
7. Используй analyze_data для извлечения информации из уже загруженных данных.
8. Не спрашивай "Что дальше?" после выполнения одноразовых команд.
9. Если пользователь подтвердил действие — выполняй план сразу.

## ФОРМАТ ОТВЕТА
- Для действий (создать, показать, выполнить, удалить): ТОЛЬКО JSON {"plan": [...]}
- Для объяснений: сначала блок РАССУЖДЕНИЯ:, затем ответ
- Для обсуждения и советов: просто текст
"""

        execution_context = self._retrieve_execution_context(query)
        
        user_prompt = f"""
Контекст из памяти:
{context if context else "Нет контекста."}

{execution_context if execution_context else ""}
История диалога:
{history_str}

Твой ответ:
"""
        for attempt in range(max_retries + 1):
            try:
                if attempt == 0 or attempt <= max_retries:
                    raw_response = llm_client.generate(
                        prompt=user_prompt,
                        system=system_prompt,
                        temperature=0.3,
                        provider=LLMProvider.DEEPSEEK
                    )
                    logger.info(f"🔍 DeepSeek ответ (сырой): {raw_response[:300]}...")
                    
                    cleaned = raw_response.strip()
                    cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
                    cleaned = re.sub(r'\s*```\s*$', '', cleaned)
                    
                    reasoning = None
                    response_text = raw_response
                    
                    if "РАССУЖДЕНИЯ:" in raw_response:
                        parts = raw_response.split("РАССУЖДЕНИЯ:", 1)
                        if len(parts) > 1:
                            reasoning_part = parts[1]
                            end_markers = ["\n\n##", "\n###", "\n\n**", "\n---"]
                            end_pos = len(reasoning_part)
                            for marker in end_markers:
                                pos = reasoning_part.find(marker)
                                if pos != -1 and pos < end_pos:
                                    end_pos = pos
                            reasoning = reasoning_part[:end_pos].strip()
                            response_text = parts[0].strip()
                    
                    json_match = re.search(r'(\{.*"plan".*\})', cleaned, re.DOTALL)
                    
                    if json_match:
                        try:
                            data = json.loads(json_match.group(1))
                            if "plan" in data and isinstance(data["plan"], list):
                                logger.info(f"📋 Распарсен план (DeepSeek): {len(data['plan'])} шагов")
                                return {"type": "plan", "plan": data["plan"], "reasoning": reasoning}
                        except json.JSONDecodeError as e:
                            logger.error(f"Ошибка парсинга JSON: {e}")
                    
                    return {"type": "answer", "text": response_text, "reasoning": reasoning}
                    
            except Exception as e:
                logger.warning(f"DeepSeek попытка {attempt + 1} failed: {e}")
                if attempt == max_retries:
                    logger.info("DeepSeek недоступен, переключаюсь на локальную модель")
                    try:
                        local_response = local_generate(user_prompt, model=self.executor_model, temperature=0.3)
                        if local_response.strip().startswith("{") and "plan" in local_response:
                            try:
                                data = json.loads(local_response)
                                if "plan" in data:
                                    return {"type": "plan", "plan": data["plan"]}
                            except:
                                pass
                        return {"type": "answer", "text": local_response}
                    except Exception as local_e:
                        logger.error(f"Локальная модель тоже недоступна: {local_e}")
                        return {"type": "answer", "text": f"Извините, произошла ошибка: {str(e)}"}
    
        return {"type": "answer", "text": "Извините, не удалось обработать запрос. Попробуйте позже."}

    # ======================================================================
    # Выполнение плана
    # ======================================================================
    def _execute_plan(self, plan: List[Dict]) -> List[str]:
        """Выполняет план действий через локальные инструменты."""
        logger.info(f"📋 Выполняю план из {len(plan)} шагов")
        results = []
        
        for i, step in enumerate(plan, 1):
            action = step.get("action")
            details = step.get("details")
            if not action or not details:
                results.append(f"❌ Пропущен некорректный шаг: {step}")
                continue
            
            logger.info(f"   Шаг {i}/{len(plan)}: {action} — {details[:100]}")
            try:
                res = self._call_real_action(action, details)
                if len(res) > 5000:
                    res = res[:5000] + "\n\n...[файл обрезан, показано 5000 символов]"
                results.append(f"✅ {action}: {res}")
                logger.info(f"   ✅ Шаг {i} выполнен успешно")
            except Exception as e:
                error_msg = f"❌ {action}: ошибка - {str(e)[:200]}"
                results.append(error_msg)
                logger.error(f"   ❌ Шаг {i} ошибка: {e}")
                self._reflect_on_error(action, str(e), details)
        
        logger.info(f"📋 Выполнение плана завершено. Успешных: {sum(1 for r in results if r.startswith('✅'))}/{len(plan)}")
        return results

    # ======================================================================
    # Реальные действия
    # ======================================================================
    def _is_protected_file(self, path: str) -> bool:
        protected_names = ['.env', '.env.production', '.env.local', 'config.json', 'secrets.json', 'deployment_config.json']
        filename = os.path.basename(path)
        return filename in protected_names

    def _is_action_safe(self, action: str, details: str) -> bool:
        if action == 'delete_file':
            return False
        if action == 'write_file' and self._is_protected_file(details.split('||')[0] if '||' in details else details):
            return False
        if action == 'run_command':
            dangerous = ['rm -rf', 'del /f', 'format', 'shutdown', 'DROP TABLE', 'DELETE FROM', 'rd /s']
            if any(d in details.lower() for d in dangerous):
                return False
        return True

    def _call_real_action(self, action: str, details: str) -> str:
        if action == "read_file":
            content = read_file(details)
            self.read_files_cache[details] = content
            return content
            
        elif action == "analyze_data":
            return self._analyze_data(details)
            
        elif action == "write_file":
            parts = details.split("||", 1)
            if len(parts) != 2:
                return "Неверный формат write_file, нужно: путь||содержимое"
            path = parts[0]
            content = parts[1]
            
            write_result = self._do_write_file(path, content)
            
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    saved_content = f.read()
                if len(saved_content) > 0:
                    return f"✅ Файл {path} успешно сохранён ({len(content)} символов)"
                else:
                    return f"⚠️ Файл {path} сохранён, но содержимое пустое"
            else:
                return f"❌ Ошибка: файл {path} не был создан"
            
        elif action == "delete_file":
            try:
                if os.path.exists(details):
                    os.remove(details)
                    return f"✅ Файл {details} удалён"
                else:
                    return f"❌ Файл {details} не найден"
            except Exception as e:
                return f"❌ Ошибка удаления {details}: {e}"
            
        elif action == "list_dir":
            return list_directory(details)
            
        elif action == "run_command":
            dangerous = ["rm -rf", "format", "del /f", "shutdown", "rd /s"]
            if any(d in details.lower() for d in dangerous):
                return "Команда заблокирована как опасная"
            return run_command(details)
            
        elif action == "git_status":
            return run_command("git status --short")
        elif action == "git_diff":
            return run_command("git diff")
        elif action == "git_diff_staged":
            return run_command("git diff --staged")
        elif action == "git_log":
            limit = details if details.isdigit() else 10
            return run_command(f"git log --oneline -{limit}")
        elif action == "git_commit":
            message = details if details else "Автоматический коммит от Ria"
            return run_command(f'git commit -m "{message}"')
        elif action == "git_add":
            return run_command(f"git add {details if details else '.'}")
            
        else:
            return f"Неизвестное действие: {action}"

    # ======================================================================
    # Анализ данных (без повторного чтения файлов)
    # ======================================================================
    def _analyze_data(self, details: str) -> str:
        """Анализирует данные из кэша (уже прочитанные файлы) без повторного чтения."""
        
        file_path = None
        analysis_task = details
        
        if ":" in details:
            parts = details.split(":", 1)
            potential_path = parts[0].strip()
            if potential_path in self.read_files_cache:
                file_path = potential_path
                analysis_task = parts[1].strip()
            elif os.path.exists(potential_path):
                try:
                    content = read_file(potential_path)
                    self.read_files_cache[potential_path] = content
                    file_path = potential_path
                    analysis_task = parts[1].strip()
                except:
                    pass
        
        if not file_path and self.read_files_cache:
            file_path = list(self.read_files_cache.keys())[-1]
        
        if not file_path or file_path not in self.read_files_cache:
            return "❌ Нет данных для анализа. Сначала прочитайте файл с помощью read_file."
        
        content = self.read_files_cache[file_path]
        
        try:
            data = json.loads(content)
            return self._analyze_json(data, analysis_task, file_path)
        except json.JSONDecodeError:
            return self._analyze_text(content, analysis_task, file_path)
    
    def _analyze_json(self, data: Any, task: str, file_path: str) -> str:
        """Анализирует JSON-данные."""
        
        if isinstance(data, dict):
            keys = list(data.keys())
            total_items = len(keys)
            
            sections = set()
            for url in keys:
                if "/db/" in url:
                    parts = url.split("/db/", 1)
                    if len(parts) > 1:
                        section = parts[1].split("/")[0]
                        sections.add(section)
            
            if "количество" in task.lower() or "сколько" in task.lower() or "страниц" in task.lower():
                return f"📊 **Анализ файла `{file_path}`**\n\n- Всего записей: **{total_items}**\n- Разделы: {', '.join(sections) if sections else 'не определены'}\n\n**Примеры страниц:**\n" + "\n".join([f"  • {k}" for k in list(keys)[:10]])
            
            if "раздел" in task.lower() or "section" in task.lower():
                return f"📁 **Разделы сайта в `{file_path}`**\n\n" + "\n".join([f"  • {s}" for s in sections]) + f"\n\nВсего разделов: {len(sections)}"
            
            return f"📊 **Анализ `{file_path}`**\n\n- Тип: словарь\n- Количество ключей: {total_items}\n- Разделы: {', '.join(sections) if sections else 'не определены'}\n\n**Первые 5 ключей:**\n" + "\n".join([f"  • {k}: {type(v).__name__}" for k, v in list(data.items())[:5]])
        
        elif isinstance(data, list):
            total_items = len(data)
            return f"📊 **Анализ `{file_path}`**\n\n- Тип: массив\n- Количество элементов: {total_items}\n\n**Первый элемент:**\n{json.dumps(data[0], ensure_ascii=False, indent=2)[:500] if total_items > 0 else 'пусто'}"
        
        else:
            return f"📊 **Анализ `{file_path}`**\n\nТип данных: {type(data).__name__}\nЗначение: {str(data)[:500]}"
    
    def _analyze_text(self, content: str, task: str, file_path: str) -> str:
        """Анализирует текстовые данные."""
        lines = content.split('\n')
        return f"📄 **Анализ `{file_path}`**\n\n- Размер: {len(content)} символов\n- Строк: {len(lines)}\n\n**Первые 500 символов:**\n{content[:500]}"

    # ======================================================================
    # Поиск контекста в памяти
    # ======================================================================
    def _retrieve_context(self, query: str, limit: int = 5) -> str:
        if not MEMORY_AVAILABLE or memory is None:
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
            logger.error(f"Ошибка извлечения контекста: {e}")
            return ""

    def _retrieve_full_context(self, query: str, limit: int = 5) -> str:
        if not MEMORY_AVAILABLE or memory is None:
            return ""
        
        context_parts = []
        
        try:
            results = memory.search(query=query, limit=limit * 3)
            for r in results:
                path = r.get("path", "unknown")
                text = r.get("text", "")
                score = r.get("score", 0)
                metadata = r.get("metadata", {})
                doc_type = metadata.get("type", "unknown") if isinstance(metadata, dict) else "unknown"
                
                if doc_type == "code":
                    label = "📁 [КОД]"
                    max_len = 800
                elif doc_type == "dialogue_fragment":
                    label = "💡 [ОБСУЖДЕНИЕ]"
                    max_len = 500
                elif doc_type == "lesson":
                    label = "🎓 [УРОК]"
                    max_len = 400
                else:
                    label = "📄"
                    max_len = 500
                
                if len(text) > max_len:
                    text = text[:max_len] + "..."
                context_parts.append(f"{label} {path} (сходство: {score:.2f})\n{text}\n")
        except Exception as e:
            logger.warning(f"Ошибка поиска в памяти: {e}")
        
        if not context_parts:
            return ""
        
        return "## 📚 КОНТЕКСТ ИЗ ПАМЯТИ\n\n" + "\n---\n".join(context_parts)

    # ======================================================================
    # Сохранение диалогов
    # ======================================================================
    def _format_dialogue_for_memory(self, history: List[Dict], max_length: int = 2000) -> str:
        formatted = []
        total_length = 0
        for msg in reversed(history):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if len(content) > 500:
                content = content[:500] + "..."
            msg_str = f"{role}: {content}"
            if total_length + len(msg_str) > max_length:
                formatted.append("...[предыдущие сообщения обрезаны]")
                break
            formatted.insert(0, msg_str)
            total_length += len(msg_str)
        return "\n".join(formatted)

    def _save_dialogue_to_json(self, query: str, answer: str, history: List[Dict]):
        os.makedirs(DIALOGUES_DIR, exist_ok=True)
        timestamp = datetime.now()
        chat_id = timestamp.strftime("%Y%m%d_%H%M%S")
        filename = f"{DIALOGUES_DIR}/{chat_id}_{self.agent_name}.json"
        
        dialogue = {
            "chat_id": chat_id,
            "agent": self.agent_name,
            "created_at": timestamp.isoformat(),
            "query": query,
            "answer": answer,
            "messages": []
        }
        
        for msg in history[-20:]:
            dialogue["messages"].append({
                "role": msg.get("role", "unknown"),
                "content": msg.get("content", ""),
                "timestamp": timestamp.isoformat()
            })
        
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(dialogue, f, ensure_ascii=False, indent=2)
        
        logger.info(f"💾 Диалог сохранён в JSON: {filename} ({len(dialogue['messages'])} сообщений)")

    def _save_semantic_fragment(self, query: str, answer: str):
        if not MEMORY_AVAILABLE or memory is None:
            return
        
        query_part = query[:300] if query else ""
        answer_part = answer[:300] if answer else ""
        fragment = f"Вопрос: {query_part}\nОтвет: {answer_part}"
        keywords = self._extract_keywords(query)
        
        memory.store(
            text=fragment,
            metadata={
                "type": "dialogue_fragment",
                "agent": self.agent_name,
                "keywords": keywords[:5],
                "timestamp": datetime.now().isoformat()
            }
        )
        logger.info(f"🔍 Смысловой фрагмент сохранён в Qdrant ({len(fragment)} символов, keywords: {keywords[:3]})")

    def _save_execution_summary(self, query: str, summary: str):
        if not MEMORY_AVAILABLE or memory is None:
            return
        
        try:
            memory.store(
                text=f"Задача: {query[:300]}\nВыполнено: {summary[:500]}",
                metadata={
                    "type": "execution_summary",
                    "agent": self.agent_name,
                    "timestamp": datetime.now().isoformat(),
                    "keywords": self._extract_keywords(query)[:5]
                }
            )
            logger.info(f"💾 Резюме выполнения сохранено в память")
        except Exception as e:
            logger.warning(f"Ошибка сохранения резюме выполнения: {e}")

    def _retrieve_execution_context(self, query: str) -> str:
        if not MEMORY_AVAILABLE or memory is None:
            return ""
        
        try:
            results = memory.search(query=query, limit=3)
            if not results:
                return ""
            
            summaries = []
            for r in results:
                text = r.get("text", "")
                score = r.get("score", 0)
                metadata = r.get("metadata", {})
                if metadata.get("type") in ("execution_summary", "dialogue_fragment") and score > 0.6:
                    summaries.append(f"## Ранее было выполнено\n{text[:500]}")
            
            return "\n\n".join(summaries) if summaries else ""
        except Exception as e:
            logger.warning(f"Ошибка поиска контекста выполнения: {e}")
            return ""

    def _extract_keywords(self, text: str, max_keywords: int = 5) -> list:
        if not text or len(text.strip()) < 10:
            return []
        
        prompt = f"""Извлеки из текста самые важные ключевые слова (не более {max_keywords}).
Верни ТОЛЬКО список ключевых слов через запятую, без кавычек, без нумерации.

Текст: {text[:300]}

Ключевые слова:"""
        
        try:
            response = local_generate(prompt, model=self.executor_model, temperature=0.1)
            keywords = [kw.strip().lower() for kw in response.strip().split(',') if kw.strip()]
            return keywords[:max_keywords]
        except Exception as e:
            logger.warning(f"Ошибка извлечения ключевых слов: {e}")
            return []

    # ======================================================================
    # Вспомогательные методы
    # ======================================================================
    def _do_write_file(self, path: str, content: str) -> str:
        """Выполняет запись файла с защитой конфигов."""
        if self._is_protected_file(path):
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    current = f.read()
                lines_to_add = [l.strip() for l in content.split('\n') if l.strip() and not l.strip().startswith('#')]
                existing_lines = [l.strip() for l in current.split('\n') if l.strip() and not l.strip().startswith('#')]
                existing_keys = [el.split('=')[0].strip() if '=' in el else el for el in existing_lines]
                new_lines = []
                for line in lines_to_add:
                    key = line.split('=')[0].strip() if '=' in line else line
                    if key not in existing_keys:
                        new_lines.append(line)
                if new_lines:
                    new_content = current.rstrip() + "\n" + "\n".join(new_lines)
                    return write_file(path, new_content)
                else:
                    return f"Строки уже присутствуют в {path}"
            else:
                return write_file(path, content)
        return write_file(path, content)

    def _retrieve_relevant_history(self, query: str, limit: int = 3) -> str:
        """Ищет в памяти релевантные прошлые диалоги по ключевым словам запроса."""
        try:
            results = memory.search(query=query, limit=limit * 2)
            if not results:
                return ""
            
            parts = []
            for r in results:
                text = r.get("text", "")
                score = r.get("score", 0)
                metadata = r.get("metadata", {})
                doc_type = metadata.get("type", "") if isinstance(metadata, dict) else ""
                if doc_type == "dialogue_fragment" and score > 0.6 and len(text) > 50:
                    parts.append(f"🕐 **Из истории обсуждений:**\n{text}")
            return "\n\n".join(parts) if parts else ""
        except Exception as e:
            logger.warning(f"Ошибка поиска истории: {e}")
            return ""

    def _reflect_on_error(self, action: str, error: str, context: str):
        """Сохраняет ошибку в память для будущего обучения."""
        if not MEMORY_AVAILABLE or memory is None:
            return
        try:
            memory.store(
                text=f"Ошибка при {action}: {error}\nКонтекст: {context[:300]}",
                metadata={
                    "type": "error_lesson",
                    "agent": self.agent_name,
                    "action": action,
                    "timestamp": datetime.now().isoformat()
                }
            )
            logger.info(f"📝 Ошибка сохранена в память для обучения")
        except Exception as e:
            logger.warning(f"Не удалось сохранить ошибку: {e}")