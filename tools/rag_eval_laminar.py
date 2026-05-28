"""
Скрипт оценки RAG с отправкой результатов в Laminar.
"""
import json
import logging
from lmnr import observe, Evaluation
from memory.qdrant_memory import memory

logger = logging.getLogger(__name__)


@observe(name="rag_evaluation")
def run_rag_evaluation():
    """Загружает тестовый датасет, выполняет поиск и логирует результаты в Laminar."""
    # Загружаем тестовый датасет
    with open("data/rag_test_set.json", "r", encoding="utf-8") as f:
        dataset = json.load(f)

    for item in dataset:
        query = item["query"]
        expected_chunk_id = item["chunk_id"]

        # Выполняем поиск
        retrieved = memory.hybrid_search(query, limit=5)
        retrieved_ids = [r["chunk_id"] for r in retrieved]

        # Логируем результат в Laminar
        Evaluation.log(
            query=query,
            retrieved_chunks=retrieved_ids,
            expected_chunks=[expected_chunk_id],
        )

    logger.info(f"Оценка RAG завершена. Обработано {len(dataset)} запросов.")
