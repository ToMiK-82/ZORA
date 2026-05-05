"""
Генератор тестового датасета для оценки RAG.
Проходит по чанкам в Qdrant, для каждого вызывает LLM и генерирует 1-3 вопроса.
Сохраняет результат в data/rag_test_set.json.
"""

import json
import logging
import os
import threading
import time
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Путь к датасету
DEFAULT_DATASET_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "rag_test_set.json"
)

# Глобальный флаг для защиты от повторного запуска
_generation_running = False
_generation_lock = threading.Lock()

# Типы чанков, для которых генерируем вопросы
CHUNK_TYPES_FOR_QUESTIONS = [
    "documentation", "product", "balance", "bank_account",
    "credit", "lease", "order", "news", "promotion",
    "code", "lesson", "dialogue_fragment", "good_example"
]


def _load_memory():
    """Загружает память Qdrant."""
    try:
        from memory.qdrant_memory import memory as _memory
        return _memory
    except Exception as e:
        logger.error(f"Не удалось загрузить память: {e}")
        return None


def _load_dataset(dataset_path: Optional[str] = None) -> List[Dict]:
    """Загружает существующий датасет."""
    path = dataset_path or DEFAULT_DATASET_PATH
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка загрузки датасета: {e}")
        return []


def _save_dataset(dataset: List[Dict], dataset_path: Optional[str] = None):
    """Сохраняет датасет в JSON-файл."""
    path = dataset_path or DEFAULT_DATASET_PATH
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dataset, f, ensure_ascii=False, indent=2)
        logger.info(f"✅ Датасет сохранён: {len(dataset)} пар, путь: {path}")
    except Exception as e:
        logger.error(f"Ошибка сохранения датасета: {e}")


def _get_llm_client():
    """Получает LLM клиент для генерации вопросов."""
    try:
        from connectors.llm_client_distributed import llm_client, LLMProvider
        return llm_client, LLMProvider
    except ImportError:
        try:
            from connectors.llm_client_distributed import LLMClient, LLMProvider
            client = LLMClient()
            return client, LLMProvider
        except ImportError as e:
            logger.error(f"LLM клиент не найден: {e}")
            return None, None


def _generate_questions_for_chunk(chunk_text: str, chunk_metadata: Dict[str, Any],
                                   llm_client, LLMProvider) -> List[Dict[str, Any]]:
    """
    Генерирует 1-3 вопроса для одного чанка через LLM.

    Args:
        chunk_text: Текст чанка.
        chunk_metadata: Метаданные чанка.
        llm_client: Клиент LLM.
        LLMProvider: Класс провайдера.

    Returns:
        Список словарей {question, chunk_id, chunk_text_preview, source, type}.
    """
    # Обрезаем текст до 2000 символов для промпта
    text_preview = chunk_text[:2000]
    chunk_type = chunk_metadata.get("type", "unknown")
    chunk_source = chunk_metadata.get("source", "unknown")
    chunk_id = chunk_metadata.get("chunk_id", "") or chunk_metadata.get("id", "")

    # Если нет chunk_id, используем хеш текста
    if not chunk_id:
        chunk_id = str(hash(chunk_text[:200])) if chunk_text else "unknown"

    prompt = f"""Ты — генератор тестовых вопросов для системы RAG (Retrieval-Augmented Generation).

Прочитай фрагмент документа ниже и придумай 1-3 вопроса, на которые этот фрагмент является хорошим ответом.

Тип фрагмента: {chunk_type}
Источник: {chunk_source}

Фрагмент:
```
{text_preview}
```

Вопросы должны быть:
- Похожи на реальные запросы пользователя (на русском языке)
- Разнообразными по формулировке
- Такими, на которые можно ответить ИСКЛЮЧИТЕЛЬНО из этого фрагмента

Верни ТОЛЬКО JSON-массив без пояснений:
[
  {{"question": "..."}},
  {{"question": "..."}}
]

Если фрагмент слишком короткий или неинформативный, верни пустой массив [].
"""

    try:
        # Пробуем через DeepSeek (более качественно), fallback на Ollama
        response = llm_client.generate(
            prompt=prompt,
            temperature=0.7,
            provider=LLMProvider.DEEPSEEK
        )
    except Exception:
        try:
            response = llm_client.generate(
                prompt=prompt,
                temperature=0.7,
                provider=LLMProvider.OLLAMA
            )
        except Exception as e:
            logger.warning(f"Ошибка генерации вопросов через LLM: {e}")
            return []

    if not response or not response.strip():
        return []

    # Парсим JSON из ответа
    try:
        # Ищем JSON в ответе
        json_str = response.strip()
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0].strip()
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0].strip()

        questions = json.loads(json_str)
        if not isinstance(questions, list):
            return []

        # Форматируем результат
        result = []
        for q in questions:
            if isinstance(q, dict) and q.get("question", "").strip():
                result.append({
                    "question": q["question"].strip(),
                    "chunk_id": chunk_id,
                    "chunk_text_preview": chunk_text[:200],
                    "source": chunk_source,
                    "type": chunk_type
                })
        return result
    except (json.JSONDecodeError, Exception) as e:
        logger.debug(f"Не удалось распарсить ответ LLM: {e}")
        return []


def _get_all_chunks_from_qdrant(memory, batch_size: int = 100) -> List[Dict[str, Any]]:
    """
    Получает все чанки из Qdrant с фильтром по типам.
    Использует scroll API для пагинации.

    Args:
        memory: Экземпляр ZoraMemory.
        batch_size: Размер батча для scroll.

    Returns:
        Список чанков с текстом и метаданными.
    """
    all_chunks = []
    try:
        # Используем прямой доступ к QdrantClient для scroll
        from qdrant_client.http import models

        # Строим фильтр по типам
        filter_condition = models.Filter(
            must=[
                models.FieldCondition(
                    key="type",
                    match=models.MatchAny(any=CHUNK_TYPES_FOR_QUESTIONS)
                )
            ]
        )

        next_offset = None
        while True:
            try:
                results = memory.client.scroll(
                    collection_name=memory.collection_name,
                    limit=batch_size,
                    offset=next_offset,
                    filter=filter_condition,
                    with_payload=True,
                    with_vectors=False
                )
            except Exception:
                # Если фильтр не работает, пробуем без фильтра
                results = memory.client.scroll(
                    collection_name=memory.collection_name,
                    limit=batch_size,
                    offset=next_offset,
                    with_payload=True,
                    with_vectors=False
                )

            points, next_offset = results

            for point in points:
                payload = point.payload or {}
                text = payload.get("text", "")
                metadata = {k: v for k, v in payload.items() if k != "text"}
                metadata["chunk_id"] = str(point.id)

                if text and len(text.strip()) > 20:  # Пропускаем пустые/короткие чанки
                    all_chunks.append({
                        "text": text,
                        "metadata": metadata
                    })

            if next_offset is None:
                break

        logger.info(f"Загружено чанков из Qdrant: {len(all_chunks)}")
    except Exception as e:
        logger.error(f"Ошибка получения чанков из Qdrant: {e}")

    return all_chunks


def generate_dataset(
    dataset_path: Optional[str] = None,
    max_chunks: Optional[int] = None,
    incremental: bool = True,
    chunk_types: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Генерирует тестовый датасет из чанков в Qdrant.

    Args:
        dataset_path: Путь для сохранения датасета.
        max_chunks: Максимальное количество чанков для обработки.
        incremental: Если True, добавляет только новые вопросы (для которых chunk_id ещё нет).
        chunk_types: Список типов чанков для обработки.

    Returns:
        Результат операции.
    """
    global CHUNK_TYPES_FOR_QUESTIONS
    if chunk_types:
        CHUNK_TYPES_FOR_QUESTIONS = chunk_types

    logger.info(f"🚀 Запуск генерации датасета: max_chunks={max_chunks}, incremental={incremental}")

    # Загружаем память
    memory = _load_memory()
    if memory is None:
        return {"success": False, "error": "Память Qdrant недоступна"}

    # Загружаем LLM клиент
    llm_client, LLMProvider = _get_llm_client()
    if llm_client is None:
        return {"success": False, "error": "LLM клиент недоступен"}

    # Загружаем существующий датасет
    existing_dataset = _load_dataset(dataset_path)
    existing_chunk_ids = set()
    if incremental:
        for item in existing_dataset:
            chunk_ids = item.get("relevant_chunk_ids", [])
            if isinstance(chunk_ids, list):
                existing_chunk_ids.update(chunk_ids)
            elif isinstance(chunk_ids, str):
                existing_chunk_ids.add(chunk_ids)

    logger.info(f"Существующий датасет: {len(existing_dataset)} пар, {len(existing_chunk_ids)} уникальных chunk_id")

    # Получаем все чанки из Qdrant
    all_chunks = _get_all_chunks_from_qdrant(memory)
    if not all_chunks:
        return {"success": False, "error": "Нет чанков в Qdrant для генерации вопросов"}

    # Фильтруем: оставляем только новые чанки (если incremental)
    if incremental and existing_chunk_ids:
        chunks_to_process = [
            c for c in all_chunks
            if c["metadata"].get("chunk_id") not in existing_chunk_ids
        ]
        logger.info(f"Новых чанков для обработки: {len(chunks_to_process)} (из {len(all_chunks)})")
    else:
        chunks_to_process = all_chunks

    if max_chunks and max_chunks < len(chunks_to_process):
        chunks_to_process = chunks_to_process[:max_chunks]

    if not chunks_to_process:
        return {
            "success": True,
            "message": "Нет новых чанков для генерации вопросов",
            "total_pairs": len(existing_dataset),
            "new_pairs": 0,
            "chunks_processed": 0
        }

    # Генерируем вопросы для каждого чанка
    new_pairs = []
    chunks_processed = 0
    errors = 0

    for i, chunk in enumerate(chunks_to_process):
        try:
            logger.info(f"  [{i+1}/{len(chunks_to_process)}] Обработка чанка: {chunk['metadata'].get('type', 'unknown')}...")

            questions = _generate_questions_for_chunk(
                chunk["text"],
                chunk["metadata"],
                llm_client,
                LLMProvider
            )

            for q in questions:
                new_pairs.append({
                    "query": q["question"],
                    "relevant_chunk_ids": [q["chunk_id"]],
                    "source": q["source"],
                    "type": q["type"],
                    "chunk_text_preview": q["chunk_text_preview"]
                })

            chunks_processed += 1

            # Небольшая задержка между запросами к LLM
            time.sleep(0.5)

        except Exception as e:
            logger.warning(f"Ошибка обработки чанка {i}: {e}")
            errors += 1

    # Объединяем с существующим датасетом
    if incremental:
        # Добавляем только новые пары
        existing_questions = {item["query"] for item in existing_dataset}
        truly_new = [p for p in new_pairs if p["query"] not in existing_questions]
        updated_dataset = existing_dataset + truly_new
    else:
        updated_dataset = new_pairs

    # Сохраняем
    _save_dataset(updated_dataset, dataset_path)

    result = {
        "success": True,
        "total_pairs": len(updated_dataset),
        "new_pairs": len(new_pairs),
        "chunks_processed": chunks_processed,
        "chunks_total": len(chunks_to_process),
        "errors": errors,
        "incremental": incremental,
        "dataset_path": dataset_path or DEFAULT_DATASET_PATH
    }

    logger.info(f"✅ Генерация датасета завершена: {result}")
    return result


def run_generation_async(
    dataset_path: Optional[str] = None,
    max_chunks: Optional[int] = None,
    incremental: bool = True,
    chunk_types: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Запускает генерацию датасета в фоновом потоке.

    Args:
        dataset_path: Путь для сохранения датасета.
        max_chunks: Максимальное количество чанков.
        incremental: Инкрементальный режим.
        chunk_types: Типы чанков.

    Returns:
        Словарь с результатом запуска.
    """
    global _generation_running

    with _generation_lock:
        if _generation_running:
            return {"success": False, "error": "Генерация датасета уже запущена"}
        _generation_running = True

    def _run():
        global _generation_running
        try:
            generate_dataset(
                dataset_path=dataset_path,
                max_chunks=max_chunks,
                incremental=incremental,
                chunk_types=chunk_types
            )
        except Exception as e:
            logger.error(f"Ошибка в фоновой генерации датасета: {e}")
        finally:
            with _generation_lock:
                _generation_running = False

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return {"success": True, "message": "Генерация датасета запущена в фоне"}


def is_generation_running() -> bool:
    """Возвращает True, если генерация датасета выполняется."""
    with _generation_lock:
        return _generation_running


def get_dataset_stats(dataset_path: Optional[str] = None) -> Dict[str, Any]:
    """Возвращает статистику по датасету."""
    dataset = _load_dataset(dataset_path)

    if not dataset:
        return {
            "success": True,
            "total_pairs": 0,
            "unique_chunk_ids": 0,
            "sources": {},
            "types": {}
        }

    sources = {}
    types = {}
    chunk_ids = set()

    for item in dataset:
        source = item.get("source", "unknown")
        sources[source] = sources.get(source, 0) + 1

        t = item.get("type", "unknown")
        types[t] = types.get(t, 0) + 1

        chunk_ids_list = item.get("relevant_chunk_ids", [])
        if isinstance(chunk_ids_list, list):
            chunk_ids.update(chunk_ids_list)
        elif isinstance(chunk_ids_list, str):
            chunk_ids.add(chunk_ids_list)

    return {
        "success": True,
        "total_pairs": len(dataset),
        "unique_chunk_ids": len(chunk_ids),
        "sources": sources,
        "types": types
    }
