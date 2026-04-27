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

# Директория для хранения полных диалогов
DIALOGUES_DIR = "data/dialogues"


class DeveloperAssistant(BaseAgent):
    def __init__(self):
        super().__init__(AgentRole.DEVELOPER_ASSISTANT.value)
        self.logger = logging.getLogger("zora.agent.developer_assistant")
        self.selector = get_selector()
        model_info = self.selector.select_executor()
        self.executor_model = model_info.get("model", "llama3.2:latest")
        self.logger.info(f"DeveloperAssistant инициализирован, executor_model={self.executor_model}")

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        query = state.get("query", "")
        context = state.get("context", "")
        history = state.get("history", [])
        return self._process_specific(query, context, history)

    # ----------------------------------------------------------------------
    # Основной метод с многошаговым выполнением
    # ----------------------------------------------------------------------
    def _process_specific(self, query: str, context: str, history: List[Dict] = None) -> Dict[str, Any]:
        if history is None:
            history = []

        # Извлекаем контекст из памяти
        if not context and MEMORY_AVAILABLE and memory:
            context = self._retrieve_context(query)
            logger.debug(f"Извлечён контекст (длина {len(context)})")

        # Копируем историю, чтобы не изменять оригинал
        current_history = history.copy()
        
        # Добавляем текущий запрос в историю
        current_history.append({"role": "user", "content": query})

        # Цикл многошагового выполнения (максимум 5 итераций)
        max_iterations = 5
        iteration = 0
        all_results = []
        final_answer = None

        while iteration < max_iterations:
            iteration += 1
            logger.info(f"🔄 Итерация {iteration}/{max_iterations}")

            # Получаем решение от DeepSeek
            result = self._call_intelligent(current_history, context)
            
            if result["type"] == "plan":
                # Проверяем, есть ли критические действия, требующие подтверждения
                needs_confirmation = False
                for step in result["plan"]:
                    action = step.get("action", "")
                    details = step.get("details", "")
                    if not self._is_action_safe(action, details):
                        needs_confirmation = True
                        break
                
                if needs_confirmation:
                    # Возвращаем запрос на подтверждение вместо выполнения
                    logger.warning(f"⚠️ План требует подтверждения: {result['plan']}")
                    return {
                        "success": True,
                        "result": f"⚠️ **Требуется подтверждение**\n\nПлан содержит изменения в файлах конфигурации или опасные команды:\n```json\n{json.dumps(result['plan'], ensure_ascii=False, indent=2)}\n```\n\nПодтверждаете выполнение? (да/нет)",
                        "agent": self.agent_name,
                        "mode": "confirmation_required",
                        "pending_plan": result["plan"]
                    }
                
                # Выполняем план
                logger.info(f"📋 Получен план из {len(result['plan'])} шагов")
                execution_results = self._execute_plan(result["plan"])
                
                # Сохраняем результаты
                execution_summary = "\n".join(execution_results)
                all_results.append(execution_summary)
                
                # Добавляем результат выполнения в историю (как системное сообщение)
                current_history.append({
                    "role": "assistant",
                    "content": f"✅ Выполнены действия:\n{execution_summary}"
                })
                
                # Не завершаем цикл — продолжаем, чтобы LLM могла спланировать следующий шаг
                continue
            else:
                # Обычный ответ (без плана) — завершаем цикл
                final_answer = result["text"]
                current_history.append({"role": "assistant", "content": final_answer})
                break

        # Сохраняем полную историю в JSON-файл
        try:
            self._save_dialogue_to_json(query, final_answer if final_answer else "\n".join(all_results), current_history)
        except Exception as e:
            logger.warning(f"Не удалось сохранить диалог в JSON: {e}")

        # Сохраняем смысловой фрагмент в Qdrant для поиска
        try:
            self._save_semantic_fragment(query, final_answer if final_answer else "\n".join(all_results))
        except Exception as e:
            logger.warning(f"Не удалось сохранить смысловой фрагмент: {e}")

        # Формируем финальный ответ
        if final_answer:
            return {
                "success": True,
                "result": final_answer,
                "agent": self.agent_name,
                "iterations": iteration,
                "all_results": all_results if all_results else None
            }
        else:
            return {
                "success": True,
                "result": "\n\n".join(all_results),
                "agent": self.agent_name,
                "iterations": iteration
            }

    # ----------------------------------------------------------------------
    # Универсальный метод: DeepSeek сам решает, нужен ли план
    # ----------------------------------------------------------------------
    def _call_intelligent(self, history: List[Dict], context: str) -> Dict[str, Any]:
        """Отправляет историю диалога в DeepSeek, возвращает {'type': 'plan'|'answer', ...}"""
        
        # Форматируем историю для промпта (только последние 10 сообщений)
        history_str = ""
        if history:
            last_msgs = history[-10:]
            history_str = "\n".join([f"{m.get('role', 'user')}: {m.get('content', '')}" for m in last_msgs])

        system_prompt = """Ты — Ria, ассистент разработчика ZORA.

ПРАВИЛА:
1. Если пользователь обсуждает требования, идеи, архитектуру — отвечай обычным текстом (НЕ ИСПОЛЬЗУЙ JSON).
2. Если пользователь даёт КОНКРЕТНУЮ КОМАНДУ на действие (покажи, найди, открой, прочитай, создай, напиши, запусти) — верни JSON-план.
3. Если задача сложная и требует нескольких шагов, план должен включать ТОЛЬКО СЛЕДУЮЩИЕ НЕСКОЛЬКО ДЕЙСТВИЙ. После их выполнения я сообщу тебе результат, и ты сможешь спланировать следующие шаги.
4. После выполнения плана ты получишь результаты в истории диалога. На их основе ты можешь составить следующий план.

Формат JSON-плана:
{"plan": [{"action": "read_file|write_file|list_dir|run_command", "details": "параметры"}]}

Примеры:
- {"plan": [{"action": "list_dir", "details": "connectors"}]}
- {"plan": [{"action": "read_file", "details": "connectors/onec_mcp.py"}]}
- {"plan": [{"action": "write_file", "details": ".env||ONEC_LOGIN=user"}]}
- {"plan": [{"action": "run_command", "details": "python test.py"}]}

Важно: Верни ТОЛЬКО JSON или ТОЛЬКО текст. Никаких смешанных ответов.
"""

        user_prompt = f"""
Контекст из памяти (существующий код, документация):
{context if context else "Нет контекста."}

История диалога:
{history_str}

Твой ответ:
"""
        try:
            raw_response = deepseek_generate(
                prompt=user_prompt,
                system=system_prompt,
                temperature=0.3,
                format="auto"
            )
            logger.info(f"🔍 DeepSeek ответ (сырой): {raw_response[:500]}")
            
            # Очистка ответа от маркеров
            cleaned = raw_response.strip()
            # Удаляем ```json ... ```
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```\s*$', '', cleaned)
            
            # Ищем JSON с ключом "plan"
            json_match = re.search(r'(\{.*"plan".*\})', cleaned, re.DOTALL)
            
            if json_match:
                try:
                    data = json.loads(json_match.group(1))
                    if "plan" in data and isinstance(data["plan"], list):
                        logger.info(f"📋 Распарсен план: {len(data['plan'])} шагов")
                        return {"type": "plan", "plan": data["plan"]}
                except json.JSONDecodeError as e:
                    logger.error(f"Ошибка парсинга JSON: {e}")
            
            # Если JSON не найден — обычный ответ
            return {"type": "answer", "text": raw_response}
            
        except Exception as e:
            logger.error(f"Ошибка в _call_intelligent: {e}")
            return {"type": "answer", "text": f"Извините, произошла ошибка: {str(e)}"}

    # ----------------------------------------------------------------------
    # Выполнение плана
    # ----------------------------------------------------------------------
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
            
            logger.info(f"   Шаг {i}/{len(plan)}: {action} — {details}")
            try:
                res = self._call_real_action(action, details)
                results.append(f"✅ {action}: {res}")
                logger.info(f"   ✅ Шаг {i} выполнен успешно")
            except Exception as e:
                error_msg = f"❌ {action}: ошибка - {str(e)}"
                results.append(error_msg)
                logger.error(f"   ❌ Шаг {i} ошибка: {e}")
        
        logger.info(f"📋 Выполнение плана завершено. Успешных: {sum(1 for r in results if r.startswith('✅'))}/{len(plan)}")
        return results

    # ----------------------------------------------------------------------
    # Реальные действия
    # ----------------------------------------------------------------------
    def _is_protected_file(self, path: str) -> bool:
        """Проверяет, является ли файл защищённым (конфигурация, секреты)."""
        protected_names = ['.env', '.env.production', '.env.local', 'config.json', 'secrets.json', 'deployment_config.json']
        filename = os.path.basename(path)
        return filename in protected_names

    def _is_action_safe(self, action: str, details: str) -> bool:
        """Проверяет, безопасно ли действие (не требует подтверждения пользователя).
        Возвращает True, если действие можно выполнить без подтверждения."""
        # write_file в защищённые файлы — требует подтверждения
        if action == 'write_file' and self._is_protected_file(details.split('||')[0] if '||' in details else details):
            return False
        # Опасные команды
        if action == 'run_command':
            dangerous = ['rm -rf', 'del /f', 'format', 'shutdown', 'DROP TABLE', 'DELETE FROM', 'rd /s']
            if any(d in details.lower() for d in dangerous):
                return False
        # delete_file — всегда требует подтверждения
        if action == 'delete_file':
            return False
        return True

    def _call_real_action(self, action: str, details: str) -> str:
        if action == "read_file":
            return read_file(details)
        elif action == "write_file":
            parts = details.split("||", 1)
            if len(parts) != 2:
                return "Неверный формат write_file, нужно: путь||содержимое"
            path = parts[0]
            content = parts[1]
            
            # Защита файлов конфигурации — дописываем, а не перезаписываем
            if self._is_protected_file(path):
                if os.path.exists(path):
                    with open(path, 'r', encoding='utf-8') as f:
                        current = f.read()
                    # Проверяем, какие строки уже есть
                    lines_to_add = [l.strip() for l in content.split('\n') if l.strip() and not l.strip().startswith('#')]
                    existing_lines = [l.strip() for l in current.split('\n') if l.strip() and not l.strip().startswith('#')]
                    new_lines = []
                    for line in lines_to_add:
                        key = line.split('=')[0].strip() if '=' in line else line
                        existing_keys = [el.split('=')[0].strip() if '=' in el else el for el in existing_lines]
                        if key not in existing_keys:
                            new_lines.append(line)
                    if new_lines:
                        new_content = current.rstrip() + "\n" + "\n".join(new_lines)
                        return write_file(path, new_content)
                    else:
                        return f"Строки уже присутствуют в {path}"
                else:
                    # Файла нет — создаём
                    return write_file(path, content)
            
            # Обычный файл — перезаписываем
            return write_file(path, content)
        elif action == "list_dir":
            return list_directory(details)
        elif action == "run_command":
            dangerous = ["rm -rf", "format", "del /f", "shutdown", "rd /s"]
            if any(d in details.lower() for d in dangerous):
                return "Команда заблокирована как опасная"
            return run_command(details)
        else:
            return f"Неизвестное действие: {action}"

    # ----------------------------------------------------------------------
    # Поиск контекста в памяти
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

    # ----------------------------------------------------------------------
    # Форматирование диалога для сохранения в память
    # ----------------------------------------------------------------------
    def _format_dialogue_for_memory(self, history: List[Dict], max_length: int = 2000) -> str:
        """Форматирует историю диалога для сохранения в память, обрезая слишком длинные сообщения."""
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

    # ----------------------------------------------------------------------
    # Сохранение полной истории диалога в JSON-файл
    # ----------------------------------------------------------------------
    def _save_dialogue_to_json(self, query: str, answer: str, history: List[Dict]):
        """Сохраняет полную историю диалога в JSON-файл в data/dialogues/"""
        os.makedirs(DIALOGUES_DIR, exist_ok=True)
        
        timestamp = datetime.now()
        chat_id = timestamp.strftime("%Y%m%d_%H%M%S")
        filename = f"{DIALOGUES_DIR}/{chat_id}_{self.agent_name}.json"
        
        # Формируем структуру диалога
        dialogue = {
            "chat_id": chat_id,
            "agent": self.agent_name,
            "created_at": timestamp.isoformat(),
            "query": query,
            "answer": answer,
            "messages": []
        }
        
        # Копируем сообщения из истории (без огромных текстов для компактности)
        for msg in history:
            content = msg.get("content", "")
            # Для JSON-файла храним полный текст, но если сообщение слишком длинное,
            # сохраняем его целиком — это же файловое хранилище
            dialogue["messages"].append({
                "role": msg.get("role", "unknown"),
                "content": content,
                "timestamp": timestamp.isoformat()
            })
        
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(dialogue, f, ensure_ascii=False, indent=2)
        
        logger.info(f"💾 Диалог сохранён в JSON: {filename} ({len(dialogue['messages'])} сообщений)")

    # ----------------------------------------------------------------------
    # Сохранение смыслового фрагмента в Qdrant для поиска
    # ----------------------------------------------------------------------
    def _save_semantic_fragment(self, query: str, answer: str):
        """Сохраняет в Qdrant только ключевую идею диалога (обрезанный фрагмент)."""
        if not MEMORY_AVAILABLE or memory is None:
            return
        
        # Обрезаем до безопасной длины для эмбеддинга
        query_part = query[:300] if query else ""
        answer_part = answer[:300] if answer else ""
        fragment = f"Вопрос: {query_part}\nОтвет: {answer_part}"
        
        # Извлекаем ключевые слова из запроса
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

    def _extract_keywords(self, text: str) -> list:
        """Извлекает ключевые слова из текста."""
        import re
        # Извлекаем слова длиной >3 на кириллице и латинице
        words = re.findall(r'[а-яёА-ЯЁa-zA-Z]{4,}', text.lower())
        # Стоп-слова
        stop_words = {'что', 'как', 'для', 'это', 'котор', 'такой', 'может', 'быть', 'когда',
                      'тогда', 'здесь', 'там', 'тут', 'весь', 'еще', 'ещё', 'очень', 'просто',
                      'можно', 'нужно', 'надо', 'будет', 'есть', 'все', 'при', 'без', 'через',
                      'после', 'перед', 'между', 'пока', 'если', 'чтобы', 'также', 'иметь'}
        keywords = [w for w in words if w not in stop_words]
        # Удаляем дубликаты, сохраняя порядок
        seen = set()
        unique = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique.append(kw)
        return unique[:10]
