"""
Агент-ассистент разработчика с двухуровневой архитектурой:
Plan: DeepSeek Reasoner/API → Act: llama3.2:latest (локально)
"""

import json
import logging
from typing import Dict, Any, List

from agents.base import BaseAgent
from core.roles import AgentRole, get_system_prompt
from core.model_selector import get_selector

from connectors.deepseek_client import generate as deepseek_generate
from connectors.llm_client_distributed import generate_sync as local_generate
from tools.file_ops import read_file, write_file, list_directory
from tools.shell import run_command

try:
    from memory import memory
    MEMORY_AVAILABLE = True
except ImportError:
    MEMORY_AVAILABLE = False
    memory = None

logger = logging.getLogger(__name__)


class DeveloperAssistant(BaseAgent):
    def __init__(self):
        super().__init__(AgentRole.DEVELOPER_ASSISTANT.value)
        self.logger = logging.getLogger("zora.agent.developer_assistant")
        self.selector = get_selector()
        # Исполнитель — получаем из селектора (llama3.2:latest)
        model_info = self.selector.select_executor()
        self.executor_model = model_info.get("model", "llama3.2:latest")

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        query = state.get("query", "")
        context = state.get("context", "")
        history = state.get("history", [])
        return self._process_specific(query, context, history)

    def _process_specific(self, query: str, context: str, history: List[Dict] = None) -> Dict[str, Any]:
        if history is None:
            history = []

        if not context and MEMORY_AVAILABLE and memory:
            context = self._retrieve_context(query)

        # План через DeepSeek
        plan = self._plan_via_deepseek(query, context, history)
        if not plan:
            return {
                "success": False,
                "result": "Не удалось составить план действий. Проверьте DeepSeek API.",
                "agent": self.agent_name
            }

        # Выполнение плана через локального исполнителя
        results = []
        all_success = True
        for step in plan:
            action = step.get("action")
            details = step.get("details")
            if not action or not details:
                continue
            try:
                res = self._execute_action(action, details, self.executor_model)
                results.append(f"✅ {action}: {res}")
            except Exception as e:
                results.append(f"❌ {action}: ошибка - {str(e)}")
                all_success = False

        final_answer = "\n".join(results)

        if MEMORY_AVAILABLE and memory:
            try:
                memory.store(
                    text=f"User: {query}\nAssistant: {final_answer}",
                    metadata={"type": "dialogue", "agent": self.agent_name}
                )
            except Exception as e:
                logger.warning(f"Не удалось сохранить диалог: {e}")

        return {
            "success": all_success,
            "result": final_answer,
            "agent": self.agent_name,
            "plan_used": plan
        }

    # ----------------------------------------------------------------------
    # Планировщик (DeepSeek)
    # ----------------------------------------------------------------------
    def _plan_via_deepseek(self, query: str, context: str, history: List[Dict]) -> List[Dict]:
        system_prompt = """
Ты — планировщик в системе ZORA. По запросу пользователя составь список действий для ассистента-исполнителя.
Действия: read_file, write_file, list_dir, run_command.
Верни ТОЛЬКО JSON с ключом "plan": [{"action": "...", "details": "..."}]
"""
        history_str = ""
        if history:
            last_msgs = history[-5:]
            history_str = "\n".join([f"{m['role']}: {m['content']}" for m in last_msgs])

        user_prompt = f"""
Контекст из памяти:
{context if context else "Нет контекста."}

История диалога:
{history_str}

Запрос пользователя: {query}

Составь план действий.
"""
        try:
            response = deepseek_generate(
                prompt=user_prompt,
                system=system_prompt,
                temperature=0.2,
                format="json"
            )
            response = response.strip()
            if response.startswith("```json"):
                response = response[7:]
            if response.endswith("```"):
                response = response[:-3]
            data = json.loads(response)
            return data.get("plan", [])
        except Exception as e:
            logger.error(f"Ошибка планирования: {e}")
            return [{"action": "run_command", "details": f"echo 'Ошибка планирования: {e}'"}]

    # ----------------------------------------------------------------------
    # Исполнитель (локальная модель)
    # ----------------------------------------------------------------------
    def _execute_action(self, action: str, details: str, model: str) -> str:
        prompt = f"""Ты — исполнитель. Выполни строго:
ACTION: {action}
DETAILS: {details}
Никакого другого текста."""
        try:
            response = local_generate(prompt, model=model, temperature=0.1)
            return self._parse_and_execute_action(response)
        except Exception as e:
            return f"Ошибка при вызове модели {model}: {e}"

    def _parse_and_execute_action(self, response_text: str) -> str:
        lines = response_text.strip().split('\n')
        action, details = None, None
        for line in lines:
            if line.startswith("ACTION:"):
                action = line.split(":", 1)[1].strip()
            elif line.startswith("DETAILS:"):
                details = line.split(":", 1)[1].strip()
        if not action or not details:
            return "Не удалось распарсить ACTION/DETAILS из ответа LLM."
        return self._call_real_action(action, details)

    def _call_real_action(self, action: str, details: str) -> str:
        if action == "read_file":
            return read_file(details)
        elif action == "write_file":
            parts = details.split("||", 1)
            if len(parts) == 2:
                return write_file(parts[0], parts[1])
            return "Неверный формат write_file, нужно: путь||содержимое"
        elif action == "list_dir":
            return list_directory(details)
        elif action == "run_command":
            dangerous = ["rm -rf", "format", "del /f", "shutdown", "rd /s"]
            if any(d in details.lower() for d in dangerous):
                return "Команда заблокирована"
            return run_command(details)
        else:
            return f"Неизвестное действие: {action}"

    # ----------------------------------------------------------------------
    # Поиск контекста
    # ----------------------------------------------------------------------
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
