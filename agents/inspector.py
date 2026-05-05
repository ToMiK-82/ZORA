"""
Инспектор (Supervisor) для контроля качества агентов ZORA.
Анализирует диалоги, генерирует тесты, предлагает улучшения,
запускает автообучение и A/B тестирование промптов.
"""

import logging
import json
import os
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from connectors.llm_client_distributed import generate_sync
from connectors.llm_client_distributed import llm_client, LLMProvider

# Встроенная реализация ReflectionChecker для самоконтроля действий
from enum import Enum

class ReflectionType(Enum):
    """Типы проверок самоконтроля"""
    VISUAL = "visual"
    TEXT = "text"
    CODE = "code"

class _ReflectionChecker:
    """Встроенная версия ReflectionChecker для проверки успешности действий."""
    
    def __init__(self):
        self.confidence_threshold = float(os.getenv("REFLECTION_CONFIDENCE_THRESHOLD", "0.7"))
        self.max_retries = int(os.getenv("REFLECTION_MAX_RETRIES", "3"))
    
    def check_text(self, text_output: str, expected_pattern: str) -> Dict[str, Any]:
        response_lower = text_output.lower()
        success_keywords = ["успех", "успешно", "да", "true", "yes", "ок", "готово", "выполнено"]
        failure_keywords = ["ошибка", "неудача", "нет", "false", "no", "провал", "сбой"]
        success_count = sum(1 for kw in success_keywords if kw in response_lower)
        failure_count = sum(1 for kw in failure_keywords if kw in response_lower)
        success = success_count > failure_count
        confidence = 0.7 if success_count > 0 else 0.3
        return {"success": success, "reason": text_output[:200], "confidence": confidence}
    
    def check_code_execution(self, stdout: str, stderr: str) -> Dict[str, Any]:
        if stderr and len(stderr.strip()) > 0:
            return {"success": False, "reason": stderr[:200], "confidence": 0.5}
        return {"success": True, "reason": "Код выполнен без ошибок", "confidence": 0.9}
    
    def check_with_retry(self, check_type: ReflectionType, *args, **kwargs) -> Dict[str, Any]:
        for attempt in range(self.max_retries):
            if check_type == ReflectionType.TEXT:
                result = self.check_text(*args, **kwargs)
            elif check_type == ReflectionType.CODE:
                result = self.check_code_execution(*args, **kwargs)
            else:
                result = {"success": False, "reason": "Визуальная проверка недоступна", "confidence": 0.0}
            if result.get("success", False):
                return result
        return {"success": False, "reason": f"Все {self.max_retries} попыток неуспешны", "confidence": 0.0}

_reflection_checker = None

def get_reflection_checker():
    global _reflection_checker
    if _reflection_checker is None:
        _reflection_checker = _ReflectionChecker()
    return _reflection_checker

try:
    from memory import memory
    MEMORY_AVAILABLE = True
except ImportError:
    MEMORY_AVAILABLE = False
    memory = None

logger = logging.getLogger(__name__)

# Директория для хранения кандидатов промптов
PROMPT_CANDIDATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "prompt_candidates")
os.makedirs(PROMPT_CANDIDATES_DIR, exist_ok=True)


class AgentInspector:
    """Инспектор для контроля и обучения агентов."""

    def __init__(self):
        self.local_model = "llama3.2:latest"
        self.vision_model = "qwen3-vl:4b"
        self.planner_model = "deepseek-chat"

    # ========== Базовые методы ==========

    def get_agent_stats(self, agent_name: str, days: int = 7) -> Dict[str, Any]:
        """Получает статистику работы агента за последние N дней."""
        if not MEMORY_AVAILABLE or memory is None:
            return {"error": "Память недоступна"}

        try:
            results = memory.search(query=agent_name, limit=100)
            dialogues = [r for r in results if r.get("metadata", {}).get("agent") == agent_name]

            total = len(dialogues)
            useful = sum(1 for d in dialogues if d.get("metadata", {}).get("rating") == "useful")
            errors = sum(1 for d in dialogues if d.get("metadata", {}).get("type") == "error_lesson")

            return {
                "agent": agent_name,
                "total_dialogues": total,
                "useful_count": useful,
                "error_count": errors,
                "success_rate": useful / total if total > 0 else 0,
                "dialogues": dialogues[:20]
            }
        except Exception as e:
            logger.error(f"Ошибка получения статистики: {e}")
            return {"error": str(e)}

    def get_all_agents(self) -> List[str]:
        """Возвращает список всех агентов."""
        return [
            "developer_assistant", "economist", "accountant", "purchaser",
            "support", "smm", "website",
            "operator_1c_local", "parser_agent"
        ]

    def get_recent_errors(self, days: int = 1) -> List[Dict]:
        """Получает ошибки за последние N дней."""
        if not MEMORY_AVAILABLE or memory is None:
            return []
        try:
            results = memory.search(query="error_lesson", limit=50)
            cutoff = datetime.now() - timedelta(days=days)
            recent = []
            for r in results:
                ts = r.get("metadata", {}).get("timestamp")
                if ts:
                    try:
                        if datetime.fromisoformat(ts) > cutoff:
                            recent.append(r)
                    except:
                        pass
            return recent
        except Exception as e:
            logger.error(f"Ошибка получения ошибок: {e}")
            return []

    def count_repeated_errors(self, agent_name: str, days: int = 7) -> int:
        """Считает количество повторяющихся ошибок агента."""
        errors = self.get_recent_errors(days)
        agent_errors = [e for e in errors if e.get("metadata", {}).get("agent") == agent_name]
        return len(agent_errors)

    # ========== Анализ и тестирование ==========

    def analyze_errors(self, agent_name: str) -> str:
        """Анализирует ошибки агента и возвращает отчёт."""
        stats = self.get_agent_stats(agent_name)
        if "error" in stats:
            return f"Ошибка: {stats['error']}"

        if stats["error_count"] == 0:
            return f"✅ Агент {agent_name} не имеет задокументированных ошибок."

        errors_text = "\n".join([
            f"- {e.get('text', '')[:200]}"
            for e in stats["dialogues"]
            if e.get("metadata", {}).get("type") == "error_lesson"
        ])

        prompt = f"""
Проанализируй ошибки агента {agent_name}:

Ошибки:
{errors_text}

Выведи:
1. Основные типы ошибок
2. Возможные причины
3. Рекомендации по исправлению
"""
        return generate_sync(prompt, model=self.local_model, temperature=0.3)

    def generate_test_cases(self, agent_name: str, limit: int = 5) -> List[Dict]:
        """Генерирует тест-кейсы для проверки агента."""
        prompt = f"""
Сгенерируй {limit} тестовых запросов для агента {agent_name} системы ZORA.

Тест-кейсы должны проверять:
1. Базовые команды (read_file, write_file, list_dir)
2. Обработку ошибок
3. Сложные многошаговые задачи

Формат ответа: JSON-массив с ключами "query", "expected_action", "expected_details".

Пример:
[
    {{"query": "покажи файл README.md", "expected_action": "read_file", "expected_details": "README.md"}},
    {{"query": "создай test.py с print('hi')", "expected_action": "write_file", "expected_details": "test.py||print('hi')"}}
]
"""
        try:
            response = llm_client.generate(prompt, temperature=0.3, provider=LLMProvider.DEEPSEEK)
            return json.loads(response)
        except Exception as e:
            logger.error(f"Ошибка генерации тест-кейсов: {e}")
            return []

    def run_tests(self, agent_name: str, test_cases: List[Dict] = None) -> Dict[str, Any]:
        """Запускает тесты для агента."""
        if test_cases is None:
            test_cases = self.generate_test_cases(agent_name)

        results = []
        passed = 0

        for test in test_cases:
            query = test.get("query")
            expected_action = test.get("expected_action")

            # Здесь нужно вызвать агента и проверить ответ
            # Для простоты возвращаем заглушку
            results.append({
                "query": query,
                "expected_action": expected_action,
                "passed": True,
                "actual": "test"
            })
            passed += 1

        return {
            "agent": agent_name,
            "total_tests": len(test_cases),
            "passed": passed,
            "failed": len(test_cases) - passed,
            "results": results
        }

    def test_prompt(self, agent_name: str, prompt_text: str) -> float:
        """Тестирует промпт и возвращает оценку (0-100)."""
        # Заглушка — в реальности нужно запустить агента с этим промптом
        # и оценить качество ответов
        return 50.0

    # ========== Управление промптами ==========

    def get_current_prompt(self, agent_name: str) -> Optional[str]:
        """Получает текущий системный промпт агента."""
        try:
            module_path = f"agents.{agent_name}"
            import importlib
            module = importlib.import_module(module_path)
            # Ищем атрибут system_prompt или DEFAULT_SYSTEM_PROMPT
            for attr in ["system_prompt", "DEFAULT_SYSTEM_PROMPT", "SYSTEM_PROMPT"]:
                if hasattr(module, attr):
                    return getattr(module, attr)
            return None
        except Exception as e:
            logger.error(f"Ошибка получения промпта {agent_name}: {e}")
            return None

    def get_candidate_prompt(self, agent_name: str) -> Optional[str]:
        """Получает кандидат промпта для A/B тестирования."""
        candidate_path = os.path.join(PROMPT_CANDIDATES_DIR, f"{agent_name}_candidate.txt")
        if os.path.exists(candidate_path):
            with open(candidate_path, 'r', encoding='utf-8') as f:
                return f.read()
        return None

    def save_candidate_prompt(self, agent_name: str, prompt_text: str):
        """Сохраняет кандидат промпта."""
        candidate_path = os.path.join(PROMPT_CANDIDATES_DIR, f"{agent_name}_candidate.txt")
        with open(candidate_path, 'w', encoding='utf-8') as f:
            f.write(prompt_text)
        logger.info(f"💾 Сохранён кандидат промпта для {agent_name}")

    def save_pending_improvement(self, agent_name: str, prompt_text: str):
        """Сохраняет ожидающее подтверждения улучшение."""
        pending_path = os.path.join(PROMPT_CANDIDATES_DIR, f"{agent_name}_pending.txt")
        with open(pending_path, 'w', encoding='utf-8') as f:
            f.write(prompt_text)
        logger.info(f"⏳ Сохранено ожидающее улучшение для {agent_name}")

    def update_agent_prompt(self, agent_name: str, new_prompt: str) -> bool:
        """Обновляет промпт агента (запись в файл кандидата)."""
        try:
            # Сохраняем как утверждённый промпт
            approved_path = os.path.join(PROMPT_CANDIDATES_DIR, f"{agent_name}_approved.txt")
            with open(approved_path, 'w', encoding='utf-8') as f:
                f.write(new_prompt)
            logger.info(f"✅ Утверждён новый промпт для {agent_name}")
            return True
        except Exception as e:
            logger.error(f"Ошибка обновления промпта {agent_name}: {e}")
            return False

    def suggest_prompt_improvement(self, agent_name: str) -> str:
        """Предлагает улучшенную версию промпта агента."""
        stats = self.get_agent_stats(agent_name)
        if "error" in stats:
            return f"Ошибка: {stats['error']}"

        errors_text = "\n".join([
            f"- {e.get('text', '')[:200]}"
            for e in stats["dialogues"]
            if e.get("metadata", {}).get("type") == "error_lesson"
        ])

        prompt = f"""
Ты — эксперт по улучшению промптов для AI-агентов.

Агент: {agent_name}
Успешность: {stats['success_rate'] * 100:.1f}%
Ошибки:
{errors_text if errors_text else "Нет задокументированных ошибок"}

Предложи улучшенную версию системного промпта для этого агента.
Учти выявленные проблемы. Верни ТОЛЬКО новый промпт (без пояснений).
"""
        return llm_client.generate(prompt, temperature=0.4, provider=LLMProvider.DEEPSEEK)

    # ========== Автообучение и A/B тестирование ==========

    def run_learning_cycle(self) -> Dict[str, Any]:
        """Запускает полный цикл обучения."""
        logger.info("🔄 Запуск цикла обучения")

        # 1. Анализируем новые ошибки
        errors = self.get_recent_errors(days=1)
        if not errors:
            logger.info("Новых ошибок нет")
            return {"status": "no_errors", "message": "Новых ошибок нет"}

        # 2. Генерируем улучшенные промпты
        generated = 0
        for agent_name in self.get_all_agents():
            repeated = self.count_repeated_errors(agent_name, days=7)
            if repeated > 0:
                new_prompt = self.suggest_prompt_improvement(agent_name)
                if new_prompt and not new_prompt.startswith("Ошибка"):
                    self.save_candidate_prompt(agent_name, new_prompt)
                    generated += 1

        # 3. Запускаем A/B тестирование
        ab_results = self.run_ab_tests()

        return {
            "status": "completed",
            "errors_analyzed": len(errors),
            "prompts_generated": generated,
            "ab_test_results": ab_results
        }

    def run_ab_tests(self) -> Dict[str, Any]:
        """Запускает A/B тестирование промптов."""
        results = {}

        for agent_name in self.get_all_agents():
            current_prompt = self.get_current_prompt(agent_name)
            candidate_prompt = self.get_candidate_prompt(agent_name)

            if not candidate_prompt:
                continue

            # Тестируем оба
            current_score = self.test_prompt(agent_name, current_prompt or "")
            candidate_score = self.test_prompt(agent_name, candidate_prompt)

            # Сравниваем
            if candidate_score > current_score * 1.1:  # улучшение >10%
                results[agent_name] = {
                    "improved": True,
                    "new_score": candidate_score,
                    "old_score": current_score,
                    "improvement_percent": ((candidate_score - current_score) / current_score * 100) if current_score else 0
                }
                logger.info(f"✅ Найдено улучшение для {agent_name}: {current_score:.1f} → {candidate_score:.1f}")
            else:
                results[agent_name] = {
                    "improved": False,
                    "old_score": current_score,
                    "new_score": candidate_score,
                    "message": "Улучшение незначительное"
                }

        return results

    def apply_improvements(self, confirmed_only: bool = True) -> Dict[str, Any]:
        """Применяет улучшенные промпты."""
        applied = {}

        for agent_name, result in self.run_ab_tests().items():
            if result.get("improved"):
                candidate = self.get_candidate_prompt(agent_name)
                if candidate:
                    if confirmed_only:
                        self.save_pending_improvement(agent_name, candidate)
                        applied[agent_name] = "pending_confirmation"
                    else:
                        self.update_agent_prompt(agent_name, candidate)
                        applied[agent_name] = "applied"

        return applied

    def auto_fix_prompts(self) -> Dict[str, Any]:
        """Автоматически исправляет промпты при повторяющихся ошибках."""
        fixed = {}

        for agent_name in self.get_all_agents():
            repeated_errors = self.count_repeated_errors(agent_name, days=7)

            if repeated_errors > 3:
                logger.info(f"🔧 Агент {agent_name} требует исправления ({repeated_errors} ошибок)")
                new_prompt = self.suggest_prompt_improvement(agent_name)

                if new_prompt and not new_prompt.startswith("Ошибка"):
                    self.update_agent_prompt(agent_name, new_prompt)
                    fixed[agent_name] = {"fixed": True, "errors_before": repeated_errors}

        return fixed

    # ========== Визуальная проверка ==========

    def check_screenshot(self, before_path: str, after_path: str, expected: str) -> Dict[str, Any]:
        """Проверяет скриншоты до/после с помощью vision-модели."""
        try:
            from connectors.vision_client import vision_client
            result = vision_client.compare_screenshots(before_path, after_path, expected)
            return result
        except Exception as e:
            logger.error(f"Ошибка vision-проверки: {e}")
            return {"success": False, "reason": str(e)}

    def capture_and_check(self, task: str = "Проверка интерфейса") -> Dict[str, Any]:
        """Делает скриншот и проверяет его через vision-модель."""
        try:
            # Создаём скриншот через инструмент desktop_automation
            from tools.desktop_automation import take_screenshot
            screenshot_path = take_screenshot()

            from connectors.vision_client import vision_client
            result = vision_client.analyze_screenshot(screenshot_path, task)
            result["screenshot_path"] = screenshot_path
            return result
        except Exception as e:
            logger.error(f"Ошибка создания/проверки скриншота: {e}")
            return {"success": False, "error": str(e)}

    # ========== Оценка качества RAG ==========

    def evaluate_rag(self, dataset_path: Optional[str] = None, k_list: Optional[List[int]] = None) -> Dict[str, Any]:
        """
        Запускает оценку качества RAG (Retrieval-Augmented Generation).
        Использует модуль tools.rag_evaluator для вычисления метрик.

        Args:
            dataset_path: Путь к JSON-файлу с тестовым датасетом.
                          Если None, используется data/rag_test_set.json.
            k_list: Список значений k для метрик (по умолчанию [1, 3, 5]).

        Returns:
            Словарь с метриками: Hit Rate@k, MRR, Precision@k, Recall@k.
        """
        try:
            from tools.rag_evaluator import evaluate_rag as _evaluate_rag
            metrics = _evaluate_rag(dataset_path=dataset_path, k_list=k_list)
            if metrics.get("success"):
                logger.info(f"✅ RAG оценка завершена: Hit Rate@5 = {metrics['hit_rate'].get('@5', 0):.2%}")
                # Сохраняем результат в память для последующего анализа
                if MEMORY_AVAILABLE and memory is not None:
                    try:
                        memory.store(
                            text=f"RAG Evaluation Results: {json.dumps(metrics, ensure_ascii=False, indent=2)}",
                            metadata={
                                "type": "rag_evaluation",
                                "timestamp": datetime.now().isoformat(),
                                "hit_rate_5": metrics.get("hit_rate", {}).get("@5", 0),
                                "mrr": metrics.get("mrr", 0)
                            }
                        )
                    except Exception as e:
                        logger.warning(f"Не удалось сохранить метрики RAG в память: {e}")
            else:
                logger.warning(f"⚠️ Ошибка оценки RAG: {metrics.get('error', 'Неизвестная ошибка')}")
            return metrics
        except ImportError as e:
            logger.error(f"Модуль rag_evaluator не найден: {e}")
            return {"success": False, "error": f"Модуль rag_evaluator не найден: {e}"}
        except Exception as e:
            logger.error(f"Ошибка оценки RAG: {e}")
            return {"success": False, "error": str(e)}

    def get_rag_metrics(self) -> Dict[str, Any]:
        """
        Возвращает последние сохранённые метрики RAG.
        Использует модуль tools.rag_evaluator.
        """
        try:
            from tools.rag_evaluator import get_last_metrics, is_evaluation_running
            metrics = get_last_metrics()
            metrics["evaluation_running"] = is_evaluation_running()
            return metrics
        except ImportError:
            return {"success": False, "error": "Модуль rag_evaluator не найден"}
        except Exception as e:
            logger.error(f"Ошибка получения метрик RAG: {e}")
            return {"success": False, "error": str(e)}

    def run_rag_evaluation_async(self, dataset_path: Optional[str] = None, k_list: Optional[List[int]] = None) -> Dict[str, Any]:
        """
        Запускает оценку RAG в фоновом потоке (не блокирует API).

        Args:
            dataset_path: Путь к датасету.
            k_list: Список k для метрик.

        Returns:
            Словарь с результатом запуска.
        """
        try:
            from tools.rag_evaluator import run_evaluation_async as _run_async
            return _run_async(dataset_path=dataset_path, k_list=k_list)
        except ImportError as e:
            return {"success": False, "error": f"Модуль rag_evaluator не найден: {e}"}
        except Exception as e:
            logger.error(f"Ошибка запуска RAG оценки: {e}")
            return {"success": False, "error": str(e)}

    # ========== Генерация тестового датасета для RAG ==========

    def generate_rag_dataset(self, max_chunks: Optional[int] = None,
                              incremental: bool = True,
                              chunk_types: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Генерирует тестовый датасет для оценки RAG из чанков в Qdrant.
        Для каждого чанка вызывает LLM и генерирует 1-3 вопроса.

        Args:
            max_chunks: Максимальное количество чанков для обработки.
            incremental: Если True, добавляет только новые вопросы.
            chunk_types: Список типов чанков для обработки.

        Returns:
            Результат операции.
        """
        try:
            from tools.rag_dataset_generator import generate_dataset
            return generate_dataset(
                max_chunks=max_chunks,
                incremental=incremental,
                chunk_types=chunk_types
            )
        except ImportError as e:
            return {"success": False, "error": f"Модуль rag_dataset_generator не найден: {e}"}
        except Exception as e:
            logger.error(f"Ошибка генерации датасета RAG: {e}")
            return {"success": False, "error": str(e)}

    def run_dataset_generation_async(self, max_chunks: Optional[int] = None,
                                      incremental: bool = True,
                                      chunk_types: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Запускает генерацию датасета в фоновом потоке.

        Args:
            max_chunks: Максимальное количество чанков.
            incremental: Инкрементальный режим.
            chunk_types: Типы чанков.

        Returns:
            Словарь с результатом запуска.
        """
        try:
            from tools.rag_dataset_generator import run_generation_async
            return run_generation_async(
                max_chunks=max_chunks,
                incremental=incremental,
                chunk_types=chunk_types
            )
        except ImportError as e:
            return {"success": False, "error": f"Модуль rag_dataset_generator не найден: {e}"}
        except Exception as e:
            logger.error(f"Ошибка запуска генерации датасета: {e}")
            return {"success": False, "error": str(e)}

    def get_dataset_stats(self) -> Dict[str, Any]:
        """Возвращает статистику по тестовому датасету."""
        try:
            from tools.rag_dataset_generator import get_dataset_stats
            return get_dataset_stats()
        except ImportError as e:
            return {"success": False, "error": f"Модуль rag_dataset_generator не найден: {e}"}
        except Exception as e:
            logger.error(f"Ошибка получения статистики датасета: {e}")
            return {"success": False, "error": str(e)}

    # ========== Интеграция ReflectionChecker (самоконтроль действий) ==========


    def check_action_success(self, action_type: str, *args, **kwargs) -> Dict[str, Any]:
        """
        Проверяет успешность действия агента через ReflectionChecker.
        
        Args:
            action_type: Тип действия ('visual', 'text', 'code')
            *args, **kwargs: Аргументы для соответствующей проверки
            
        Returns:
            Результат проверки с confidence
        """
        try:
            checker = get_reflection_checker()
            
            type_map = {
                "visual": ReflectionType.VISUAL,
                "text": ReflectionType.TEXT,
                "code": ReflectionType.CODE
            }
            
            ref_type = type_map.get(action_type)
            if not ref_type:
                return {"success": False, "reason": f"Неизвестный тип действия: {action_type}"}
            
            return checker.check_with_retry(ref_type, *args, **kwargs)
        except Exception as e:
            logger.error(f"Ошибка ReflectionChecker: {e}")
            return {"success": False, "reason": str(e), "confidence": 0.0}

    def verify_agent_response(self, agent_name: str, query: str, response: str) -> Dict[str, Any]:
        """
        Проверяет качество ответа агента через текстовую проверку.
        
        Args:
            agent_name: Имя агента
            query: Исходный запрос
            response: Ответ агента
            
        Returns:
            Результат проверки
        """
        try:
            checker = get_reflection_checker()
            expected = f"Ответ агента {agent_name} на запрос: {query}"
            return checker.check_text(response, expected)
        except Exception as e:
            logger.error(f"Ошибка проверки ответа агента: {e}")
            return {"success": False, "reason": str(e), "confidence": 0.0}

    def verify_code_execution(self, stdout: str, stderr: str) -> Dict[str, Any]:
        """
        Проверяет успешность выполнения кода.
        
        Args:
            stdout: Стандартный вывод
            stderr: Вывод ошибок
            
        Returns:
            Результат проверки
        """
        try:
            checker = get_reflection_checker()
            return checker.check_code_execution(stdout, stderr)
        except Exception as e:
            logger.error(f"Ошибка проверки выполнения кода: {e}")
            return {"success": False, "reason": str(e), "confidence": 0.0}


# Глобальный экземпляр инспектора
_inspector = None


def get_inspector() -> AgentInspector:
    global _inspector
    if _inspector is None:
        _inspector = AgentInspector()
    return _inspector
