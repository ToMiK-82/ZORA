"""
Модуль оценки качества RAG (Retrieval-Augmented Generation).
Вычисляет метрики: Hit Rate@k, MRR, Precision@k, Recall@k.
Использует Qdrant point ID для сопоставления с relevant_chunk_ids.
"""

import json
import logging
import os
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

_evaluation_running = False
_evaluation_lock = threading.Lock()

DEFAULT_DATASET_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "rag_test_set.json")
METRICS_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "rag_metrics.json")


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


def evaluate_rag(dataset_path: Optional[str] = None, k_list: Optional[List[int]] = None) -> Dict[str, Any]:
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
            results = memory.search(query=query, limit=max_k, threshold=0.0, types=types)
            # Извлекаем ID из словарей, возвращаемых методом search
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

    _save_metrics(metrics)
    logger.info(f"Оценка RAG завершена: Hit Rate@5 = {metrics['hit_rate'].get('@5', 0):.2%}")
    return metrics


def run_evaluation_async(dataset_path: Optional[str] = None, k_list: Optional[List[int]] = None) -> Dict[str, Any]:
    global _evaluation_running

    with _evaluation_lock:
        if _evaluation_running:
            return {"success": False, "error": "Оценка уже запущена"}
        _evaluation_running = True

    def _run():
        global _evaluation_running
        try:
            evaluate_rag(dataset_path=dataset_path, k_list=k_list)
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