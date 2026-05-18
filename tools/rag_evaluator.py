"""
Модуль оценки качества RAG (Retrieval-Augmented Generation).
Вычисляет метрики: Hit Rate@k, MRR, Precision@k, Recall@k.
Поддерживает оценку faithfulness (верности контексту) через LLM-судью.
Использует Qdrant point ID для сопоставления с relevant_chunk_ids.
Использует гибридный поиск (hybrid_search) с ре-ранкером.
"""

import json
import logging
import os
import random
import sys
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

_evaluation_running = False
_evaluation_lock = threading.Lock()

DEFAULT_DATASET_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "rag_test_set.json")
METRICS_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "rag_metrics.json")
FAITHFULNESS_SAMPLES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "faithfulness_samples")



def _load_memory():
    try:
        from memory.qdrant_memory import memory as _memory
        return _memory
    except Exception as e:
        logger.error(f"Не удалось загрузить память: {e}")
        return None


def _load_dataset(dataset_path: Optional[str] = None) -> List[Dict]:
    path = dataset_path or DEFAULT_DATASET_PATH
    if not os.path.exists(path):
        logger.warning(f"Датасет не найден: {path}")
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info(f"Загружен датасет из {path}: {len(data)} запросов")
        return data
    except Exception as e:
        logger.error(f"Ошибка загрузки датасета: {e}")
        return []


def _save_metrics(metrics: Dict[str, Any]):
    metrics["timestamp"] = datetime.now().isoformat()
    try:
        os.makedirs(os.path.dirname(METRICS_FILE_PATH), exist_ok=True)
        with open(METRICS_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(metrics, f, ensure_ascii=False, indent=2)
        logger.info(f"Метрики сохранены в {METRICS_FILE_PATH}")
    except Exception as e:
        logger.error(f"Ошибка сохранения метрик: {e}")


def _compute_hit_rate(results: List[List[str]], relevant_ids: List[str], k: int) -> float:
    hits = 0
    total = len(results)
    for i, retrieved_ids in enumerate(results):
        top_k = retrieved_ids[:k]
        if any(rid in top_k for rid in relevant_ids[i] if isinstance(relevant_ids[i], list)):
            hits += 1
        elif isinstance(relevant_ids[i], str) and relevant_ids[i] in top_k:
            hits += 1
    return hits / total if total > 0 else 0.0


def _compute_mrr(results: List[List[str]], relevant_ids: List[str]) -> float:
    total = 0.0
    count = 0
    for i, retrieved_ids in enumerate(results):
        relevant = relevant_ids[i]
        if isinstance(relevant, str):
            relevant = [relevant]
        for rank, rid in enumerate(retrieved_ids, 1):
            if rid in relevant:
                total += 1.0 / rank
                break
        count += 1
    return total / count if count > 0 else 0.0


def _compute_precision_at_k(results: List[List[str]], relevant_ids: List[str], k: int) -> float:
    total_precision = 0.0
    count = 0
    for i, retrieved_ids in enumerate(results):
        top_k = retrieved_ids[:k]
        relevant = relevant_ids[i]
        if isinstance(relevant, str):
            relevant = [relevant]
        if len(top_k) > 0:
            relevant_in_top = sum(1 for rid in top_k if rid in relevant)
            total_precision += relevant_in_top / len(top_k)
        count += 1
    return total_precision / count if count > 0 else 0.0


def _compute_recall_at_k(results: List[List[str]], relevant_ids: List[str], k: int) -> float:
    total_recall = 0.0
    count = 0
    for i, retrieved_ids in enumerate(results):
        top_k = retrieved_ids[:k]
        relevant = relevant_ids[i]
        if isinstance(relevant, str):
            relevant = [relevant]
        if len(relevant) > 0:
            found = sum(1 for rid in top_k if rid in relevant)
            total_recall += found / len(relevant)
        count += 1
    return total_recall / count if count > 0 else 0.0


def _generate_agent_answer(query: str, context_text: str) -> str:
    """
    Генерирует ответ агента на основе вопроса и контекста с помощью основной LLM (DeepSeek).

    Args:
        query: Исходный вопрос.
        context_text: Текст найденных документов (контекст).

    Returns:
        Сгенерированный ответ или сообщение об ошибке.
    """
    try:
        from connectors.llm_client_distributed import llm_client as sync_client

        prompt = (
            "Ты — ассистент, отвечающий на вопросы на основе предоставленного контекста. "
            "Используй ТОЛЬКО информацию из контекста. Если в контексте нет ответа, так и скажи.\n\n"
            f"Контекст:\n{context_text[:12000]}\n\n"
            f"Вопрос: {query}\n\n"
            "Ответ:"
        )

        logger.info(f"Генерация ответа агента для вопроса: '{query[:60]}...'")
        answer = sync_client.generate(
            prompt=prompt,
            temperature=0.3,
            system="Ты — полезный ассистент. Отвечай кратко и по делу, только на основе контекста."
        )

        if not answer or answer.startswith("Ошибка"):
            logger.warning(f"Ошибка генерации ответа: {answer}")
            return f"[Ошибка генерации ответа: {answer}]"

        logger.info(f"Ответ агента сгенерирован: {len(answer)} симв.")
        return answer

    except Exception as e:
        logger.error(f"Неожиданная ошибка генерации ответа: {e}")
        return f"[Ошибка генерации ответа: {str(e)}]"


def _evaluate_faithfulness_for_dataset(
    dataset: List[Dict],
    memory,
    sample_size: Optional[int] = None,
    max_k: int = 5,
    ci_mode: bool = False
) -> Dict:
    """
    Оценивает faithfulness для датасета: для каждого вопроса получает контекст,
    генерирует ответ и оценивает его верность контексту.

    Args:
        dataset: Список вопросов из датасета.
        memory: Экземпляр ZoraMemory для поиска.
        sample_size: Размер случайной подвыборки (None = все вопросы).
        max_k: Количество чанков для поиска.
        ci_mode: Если True, возвращает также флаг прохождения CI-проверки.

    Returns:
        Словарь с результатами оценки faithfulness.
    """
    import importlib.util
    import os
    _faith_spec = importlib.util.spec_from_file_location(
        "faithfulness_evaluator",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "faithfulness_evaluator.py")
    )
    _faith_mod = importlib.util.module_from_spec(_faith_spec)
    _faith_spec.loader.exec_module(_faith_mod)
    evaluate_faithfulness = _faith_mod.evaluate_faithfulness

    # Фильтруем вопросы без relevant_chunk_ids
    valid_items = [item for item in dataset if item.get("query") and item.get("relevant_chunk_ids")]
    if not valid_items:
        logger.warning("Нет валидных вопросов для оценки faithfulness")
        return {"faithfulness_mean": None, "faithfulness_samples": [], "faithfulness_total": 0}

    # Подвыборка
    if sample_size is not None and sample_size < len(valid_items):
        sampled_items = random.sample(valid_items, sample_size)
        logger.info(f"Оценка faithfulness на подвыборке: {sample_size} из {len(valid_items)} вопросов")
    else:
        sampled_items = valid_items
        logger.info(f"Оценка faithfulness на всех {len(valid_items)} вопросах")

    os.makedirs(FAITHFULNESS_SAMPLES_DIR, exist_ok=True)

    scores = []
    samples = []
    errors = 0

    for idx, item in enumerate(sampled_items):
        query = item.get("query", "")
        item_type = item.get("type")
        types = [item_type] if item_type else None

        logger.info(f"[{idx + 1}/{len(sampled_items)}] Оценка faithfulness для: '{query[:50]}...'")

        try:
            # Получаем контекст через гибридный поиск
            search_results = memory.hybrid_search(query=query, limit=max_k, types=types, score_threshold=0.0)

            # Склеиваем тексты чанков в один контекст
            context_text = "\n\n".join([
                hit.get("text", "") for hit in search_results if hit.get("text")
            ])

            if not context_text:
                logger.warning(f"Пустой контекст для вопроса '{query[:50]}...'")
                context_text = "[Контекст не найден]"

            # Генерируем ответ агента
            answer = _generate_agent_answer(query, context_text)

            # Оцениваем faithfulness
            result = evaluate_faithfulness(question=query, context=context_text, answer=answer)

            score = result.get("faithfulness_score", 0)
            reasoning = result.get("reasoning", "")

            scores.append(score)

            # Сохраняем сэмпл
            sample = {
                "question": query,
                "context_preview": context_text[:500],
                "answer": answer[:1000],
                "faithfulness_score": score,
                "reasoning": reasoning
            }
            samples.append(sample)

            # Сохраняем детальный файл
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            sample_file = os.path.join(FAITHFULNESS_SAMPLES_DIR, f"faithfulness_{timestamp}_{idx:04d}.json")
            try:
                with open(sample_file, "w", encoding="utf-8") as f:
                    json.dump({
                        "question": query,
                        "context_text": context_text,
                        "answer": answer,
                        "faithfulness_score": score,
                        "reasoning": reasoning,
                        "timestamp": timestamp
                    }, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning(f"Не удалось сохранить сэмпл в {sample_file}: {e}")

            logger.info(f"  → Score: {score}/5, reasoning: {reasoning[:60]}...")

        except Exception as e:
            logger.error(f"Ошибка при оценке faithfulness для вопроса '{query[:50]}': {e}")
            scores.append(0)
            errors += 1

    if not scores:
        return {"faithfulness_mean": None, "faithfulness_samples": [], "faithfulness_total": 0}

    faithfulness_mean = sum(scores) / len(scores)

    result = {
        "faithfulness_mean": round(faithfulness_mean, 4),
        "faithfulness_samples": samples[:20],  # Первые 20 для контроля
        "faithfulness_total": len(scores),
        "faithfulness_errors": errors
    }

    logger.info(
        f"Оценка faithfulness завершена: средняя={faithfulness_mean:.2f}/5, "
        f"оценено={len(scores)}, ошибок={errors}"
    )

    if ci_mode:
        result["ci_passed"] = faithfulness_mean >= 4.0
        result["ci_threshold"] = 4.0

    return result


def evaluate_rag(
    dataset_path: Optional[str] = None,
    k_list: Optional[List[int]] = None,
    evaluate_faithfulness: bool = False,
    faithfulness_sample_size: Optional[int] = 50,
    ci: bool = False
) -> Dict[str, Any]:
    if k_list is None:
        k_list = [1, 3, 5]

    dataset = _load_dataset(dataset_path)
    if not dataset:
        return {"error": "Датасет пуст или не найден", "success": False}

    memory = _load_memory()
    if memory is None:
        return {"error": "Память Qdrant недоступна", "success": False}

    max_k = max(k_list)
    all_retrieved_ids = []
    all_relevant_ids = []

    logger.info(f"Запуск оценки RAG: {len(dataset)} запросов, k_list={k_list}")

    for item in dataset:
        query = item.get("query", "")
        relevant = item.get("relevant_chunk_ids", [])
        item_type = item.get("type")

        if not query or not relevant:
            continue

        types = [item_type] if item_type else None

        try:
            # Используем гибридный поиск с ре-ранкером
            results = memory.hybrid_search(query=query, limit=max_k, types=types, score_threshold=0.0)
            # Извлекаем ID из словарей, возвращаемых методом hybrid_search
            retrieved_ids = [hit.get("id", "") for hit in results if hit.get("id")]
            all_retrieved_ids.append(retrieved_ids)
            all_relevant_ids.append(relevant)
        except Exception as e:
            logger.error(f"Ошибка поиска для запроса '{query[:50]}': {e}")
            all_retrieved_ids.append([])
            all_relevant_ids.append(relevant)

    if not all_retrieved_ids:
        return {"error": "Нет результатов поиска", "success": False}

    metrics = {
        "success": True,
        "total_queries": len(all_retrieved_ids),
        "k_list": k_list,
        "hit_rate": {},
        "mrr": _compute_mrr(all_retrieved_ids, all_relevant_ids),
        "precision": {},
        "recall": {},
        "faithfulness_mean": None,
        "faithfulness_samples": None,
    }

    for k in k_list:
        metrics["hit_rate"][f"@{k}"] = _compute_hit_rate(all_retrieved_ids, all_relevant_ids, k)
        metrics["precision"][f"@{k}"] = _compute_precision_at_k(all_retrieved_ids, all_relevant_ids, k)
        metrics["recall"][f"@{k}"] = _compute_recall_at_k(all_retrieved_ids, all_relevant_ids, k)

    try:
        info = memory.get_collection_info()
        metrics["vectors_count"] = info.get("vectors_count", "—")
    except Exception as e:
        logger.warning(f"Не удалось получить количество векторов: {e}")
        metrics["vectors_count"] = "—"

    # Оценка faithfulness
    if evaluate_faithfulness:
        logger.info("Запуск оценки faithfulness...")
        # В CI-режиме используем фиксированную маленькую выборку
        if ci:
            fs_sample_size = 25
        else:
            fs_sample_size = faithfulness_sample_size

        faithfulness_results = _evaluate_faithfulness_for_dataset(
            dataset=dataset,
            memory=memory,
            sample_size=fs_sample_size,
            max_k=max_k,
            ci_mode=ci
        )
        metrics["faithfulness_mean"] = faithfulness_results.get("faithfulness_mean")
        metrics["faithfulness_samples"] = faithfulness_results.get("faithfulness_samples")
        metrics["faithfulness_total"] = faithfulness_results.get("faithfulness_total")
        metrics["faithfulness_errors"] = faithfulness_results.get("faithfulness_errors")

        if ci:
            metrics["ci_passed"] = faithfulness_results.get("ci_passed", False)
            metrics["ci_threshold"] = 4.0

    _save_metrics(metrics)
    logger.info(f"Оценка RAG завершена: Hit Rate@5 = {metrics['hit_rate'].get('@5', 0):.2%}")

    # CI-режим: если faithfulness ниже порога, возвращаем ненулевой код
    if ci and metrics.get("ci_passed") is False:
        logger.error(f"❌ CI не пройден: faithfulness_mean={metrics.get('faithfulness_mean')} < 4.0")
        # Возвращаем результат, но вызывающий код должен проверить ci_passed
        metrics["ci_failed"] = True

    return metrics


def run_evaluation_async(
    dataset_path: Optional[str] = None,
    k_list: Optional[List[int]] = None,
    evaluate_faithfulness: bool = False,
    faithfulness_sample_size: Optional[int] = 50,
    ci: bool = False
) -> Dict[str, Any]:
    global _evaluation_running

    with _evaluation_lock:
        if _evaluation_running:
            return {"success": False, "error": "Оценка уже запущена"}
        _evaluation_running = True

    def _run():
        global _evaluation_running
        try:
            result = evaluate_rag(
                dataset_path=dataset_path,
                k_list=k_list,
                evaluate_faithfulness=evaluate_faithfulness,
                faithfulness_sample_size=faithfulness_sample_size,
                ci=ci
            )
            # Если CI не пройден — завершаем с ошибкой
            if ci and result.get("ci_failed"):
                logger.error("❌ CI проверка faithfulness не пройдена. Завершение с кодом 1.")
                os._exit(1)
        except Exception as e:
            logger.error(f"Ошибка в фоновой оценке RAG: {e}")
        finally:
            with _evaluation_lock:
                _evaluation_running = False

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return {"success": True, "message": "Оценка RAG запущена в фоне"}



def get_last_metrics() -> Dict[str, Any]:
    if not os.path.exists(METRICS_FILE_PATH):
        return {}
    try:
        with open(METRICS_FILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка чтения метрик: {e}")
        return {}


def is_evaluation_running() -> bool:
    with _evaluation_lock:
        return _evaluation_running
