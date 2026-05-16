"""
Генератор тестового датасета для оценки RAG.
Выбирает случайные чанки из Qdrant, генерирует конкретные вопросы через LLM.
Использует кеширование и параллельные запросы.
Жёстко ограничен до MAX_CHUNKS = 500 чанков (можно изменить).
"""

import json
import logging
import os
import sqlite3
import threading
import hashlib
import random
from datetime import datetime
from typing import Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# ---------- НАСТРОЙКИ ----------
MAX_CHUNKS = 500                # <-- измените, если нужно другое число
BATCH_SIZE = 10                 # размер батча для параллельных запросов
# ------------------------------

DEFAULT_DATASET_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "rag_test_set.json"
)

CACHE_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "rag_question_cache.db"
)

_generation_running = False
_generation_lock = threading.Lock()


class QuestionCache:
    def __init__(self, db_path: str = CACHE_DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""CREATE TABLE IF NOT EXISTS question_cache
                         (hash TEXT PRIMARY KEY, question TEXT)""")
        conn.commit()
        conn.close()

    def get(self, text_hash: str) -> Optional[str]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT question FROM question_cache WHERE hash=?", (text_hash,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None

    def set(self, text_hash: str, question: str):
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT OR REPLACE INTO question_cache (hash, question) VALUES (?, ?)",
                     (text_hash, question))
        conn.commit()
        conn.close()


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
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка загрузки датасета: {e}")
        return []


def _save_dataset(dataset: List[Dict], dataset_path: Optional[str] = None):
    path = dataset_path or DEFAULT_DATASET_PATH
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dataset, f, ensure_ascii=False, indent=2)
        logger.info(f"✅ Датасет сохранён: {len(dataset)} пар, путь: {path}")
    except Exception as e:
        logger.error(f"Ошибка сохранения датасета: {e}")


def _get_llm_client():
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


def _generate_questions_for_chunk_sync(chunk_text: str, chunk_metadata: Dict[str, Any],
                                       llm_client, LLMProvider,
                                       cache: QuestionCache) -> List[Dict[str, Any]]:
    text_hash = hashlib.md5(chunk_text[:2000].encode()).hexdigest()
    cached_question = cache.get(text_hash)
    if cached_question:
        chunk_id = str(chunk_metadata.get("chunk_id", "") or hash(chunk_text[:200]))
        return [{
            "question": cached_question,
            "chunk_id": chunk_id,
            "chunk_text_preview": chunk_text[:200],
            "source": chunk_metadata.get("source", "unknown"),
            "type": chunk_metadata.get("type", "unknown")
        }]

    questions = _generate_questions_for_chunk(chunk_text, chunk_metadata, llm_client, LLMProvider)
    if questions:
        cache.set(text_hash, questions[0]["question"])
    return questions


def _generate_questions_for_chunk(chunk_text: str, chunk_metadata: Dict[str, Any],
                                   llm_client, LLMProvider) -> List[Dict[str, Any]]:
    text_preview = chunk_text[:2000]
    chunk_type = chunk_metadata.get("type", "unknown")
    chunk_source = chunk_metadata.get("source", "unknown")
    chunk_id = str(chunk_metadata.get("chunk_id", "") or hash(chunk_text[:200]))

    # --- новый промпт, требующий конкретности ---
    prompt = f"""Ты — генератор тестовых вопросов для системы поиска (RAG).

Прочитай фрагмент документа и придумай 1-3 вопроса, на которые этот фрагмент является **единственно верным** ответом.

Тип фрагмента: {chunk_type}
Источник: {chunk_source}

Фрагмент: {text_preview}

**Требования к вопросам (обязательны):**
1. Вопрос должен содержать **конкретные факты из фрагмента**: имена, названия организаций, идентификаторы, даты, номера строк, суммы.  
2. Не используй общие формулировки («какая дата?», «какой статус?», «кто указан?»). Вместо этого пиши: «Какая дата изменения у записи Музалевой Валентины Алексеевны?» или «Какой статус у сотрудника с идентификатором 82b81f1f?».  
3. Если в чанке несколько записей, вопрос должен явно указывать, о какой именно записи идёт речь (используй уникальный идентификатор, имя или порядковый номер).  
4. Каждый вопрос должен быть самодостаточным и однозначно определять, какую информацию нужно найти.  
5. Избегай повторов — все вопросы должны быть разными.

Верни ТОЛЬКО JSON-массив без пояснений:
[
  {{"question": "..."}},
  {{"question": "..."}}
]

Если фрагмент слишком короткий или не содержит фактов, верни [].
"""

    try:
        response = llm_client.generate(prompt=prompt, temperature=0.7, provider=LLMProvider.DEEPSEEK)
    except Exception:
        try:
            response = llm_client.generate(prompt=prompt, temperature=0.7, provider=LLMProvider.OLLAMA)
        except Exception as e:
            logger.warning(f"Ошибка генерации вопросов: {e}")
            return []

    if not response or not response.strip():
        return []

    try:
        json_str = response.strip()
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0].strip()
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0].strip()

        questions = json.loads(json_str)
        if not isinstance(questions, list):
            return []

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
    except Exception as e:
        logger.debug(f"Не удалось распарсить ответ LLM: {e}")
        return []


def _get_all_chunks_from_qdrant(memory, batch_size: int = 100) -> List[Dict[str, Any]]:
    """Загружает все чанки из Qdrant (без фильтра по типам)."""
    all_chunks = []
    try:
        next_offset = None
        while True:
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
                if text and len(text.strip()) > 20:
                    all_chunks.append({"text": text, "metadata": metadata})
            if next_offset is None:
                break
        logger.info(f"Загружено чанков из Qdrant: {len(all_chunks)}")
    except Exception as e:
        logger.error(f"Ошибка получения чанков: {e}")
    return all_chunks


def _build_neighbor_index(all_chunks: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """
    Строит индекс соседних чанков.
    Для каждого чанка находит соседние (parent_doc_id совпадает, chunk_index отличается на 1).
    Возвращает словарь: chunk_id -> [соседние chunk_id]
    """
    # Группируем чанки по parent_doc_id
    doc_groups = {}
    for chunk in all_chunks:
        meta = chunk["metadata"]
        parent = meta.get("parent_doc_id", "")
        if not parent:
            continue
        chunk_id = meta.get("chunk_id", "")
        chunk_index = meta.get("chunk_index", 0)
        if isinstance(chunk_index, str):
            try:
                chunk_index = int(chunk_index)
            except (ValueError, TypeError):
                chunk_index = 0
        doc_groups.setdefault(parent, []).append((chunk_id, chunk_index))

    # Строим индекс соседей
    neighbor_index = {}
    for parent, items in doc_groups.items():
        # Сортируем по chunk_index
        items.sort(key=lambda x: x[1])
        for i, (chunk_id, idx) in enumerate(items):
            neighbors = []
            if i > 0:
                neighbors.append(items[i - 1][0])  # предыдущий
            if i < len(items) - 1:
                neighbors.append(items[i + 1][0])  # следующий
            neighbor_index[chunk_id] = neighbors

    logger.info(f"Построен индекс соседей: {len(neighbor_index)} чанков имеют соседей")
    return neighbor_index


def generate_dataset(
    dataset_path: Optional[str] = None,
    max_chunks: int = MAX_CHUNKS,
    incremental: bool = True,
    batch_size: int = BATCH_SIZE
) -> Dict[str, Any]:

    # Защита от передачи None — используем значение по умолчанию
    if max_chunks is None:
        max_chunks = MAX_CHUNKS

    logger.info(f"🚀 Генерация датасета: max_chunks={max_chunks}, batch={batch_size}")

    memory = _load_memory()
    if memory is None:
        return {"success": False, "error": "Память Qdrant недоступна"}

    llm_client, LLMProvider = _get_llm_client()
    if llm_client is None:
        return {"success": False, "error": "LLM клиент недоступен"}

    existing_dataset = _load_dataset(dataset_path)
    existing_chunk_ids = set()
    if incremental:
        for item in existing_dataset:
            ids = item.get("relevant_chunk_ids", [])
            if isinstance(ids, list):
                existing_chunk_ids.update(ids)
            elif isinstance(ids, str):
                existing_chunk_ids.add(ids)

    all_chunks = _get_all_chunks_from_qdrant(memory)
    if not all_chunks:
        return {"success": False, "error": "Нет чанков для генерации вопросов"}

    # Фильтрация и ограничение
    if incremental and existing_chunk_ids:
        new_chunks = [c for c in all_chunks if c["metadata"].get("chunk_id") not in existing_chunk_ids]
    else:
        new_chunks = all_chunks

    random.shuffle(new_chunks)
    selected_chunks = new_chunks[:max_chunks]
    logger.info(f"Отобрано для генерации: {len(selected_chunks)} чанков (из {len(new_chunks)} новых)")

    if not selected_chunks:
        return {"success": True, "message": "Нет новых чанков", "total_pairs": len(existing_dataset)}

    # Строим индекс соседних чанков для всех загруженных чанков
    neighbor_index = _build_neighbor_index(all_chunks)
    logger.info(f"Индекс соседей построен: {sum(len(v) for v in neighbor_index.values())} связей")

    question_cache = QuestionCache()
    new_pairs = []
    chunks_processed = 0
    errors = 0

    batches = [selected_chunks[i:i + batch_size] for i in range(0, len(selected_chunks), batch_size)]
    logger.info(f"Всего батчей: {len(batches)}")

    for batch_idx, batch in enumerate(batches):
        logger.info(f"  🧩 Батч {batch_idx+1}/{len(batches)} ({len(batch)} чанков)")
        with ThreadPoolExecutor(max_workers=batch_size) as executor:
            futures = {}
            for chunk in batch:
                future = executor.submit(
                    _generate_questions_for_chunk_sync,
                    chunk["text"], chunk["metadata"],
                    llm_client, LLMProvider, question_cache
                )
                futures[future] = chunk
            for future in as_completed(futures):
                try:
                    questions = future.result()
                    for q in questions:
                        chunk_id = q["chunk_id"]
                        # Добавляем соседние чанки в relevant_chunk_ids
                        neighbor_ids = neighbor_index.get(chunk_id, [])
                        all_relevant_ids = [chunk_id] + neighbor_ids
                        new_pairs.append({
                            "query": q["question"],
                            "relevant_chunk_ids": all_relevant_ids,
                            "source": q["source"],
                            "type": q["type"],
                            "chunk_text_preview": q["chunk_text_preview"]
                        })
                    chunks_processed += 1
                except Exception as e:
                    logger.warning(f"Ошибка обработки чанка: {e}")
                    errors += 1

    if incremental:
        existing_queries = {item["query"] for item in existing_dataset}
        truly_new = [p for p in new_pairs if p["query"] not in existing_queries]
        updated_dataset = existing_dataset + truly_new
    else:
        updated_dataset = new_pairs

    _save_dataset(updated_dataset, dataset_path)

    result = {
        "success": True,
        "total_pairs": len(updated_dataset),
        "new_pairs": len(new_pairs),
        "chunks_processed": chunks_processed,
        "errors": errors,
    }
    logger.info(f"✅ Генерация завершена: {result}")
    return result


def run_generation_async(dataset_path=None, max_chunks=MAX_CHUNKS, incremental=True, chunk_types=None):
    global _generation_running
    # Защита от передачи None
    if max_chunks is None:
        max_chunks = MAX_CHUNKS
    with _generation_lock:
        if _generation_running:
            return {"success": False, "error": "Генерация уже запущена"}
        _generation_running = True

    def _run():
        global _generation_running
        try:
            generate_dataset(dataset_path, max_chunks=max_chunks, incremental=incremental)
        except Exception as e:
            logger.error(f"Ошибка фоновой генерации: {e}")
        finally:
            with _generation_lock:
                _generation_running = False

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return {"success": True, "message": "Генерация запущена"}


def is_generation_running():
    return _generation_running


def get_dataset_stats(dataset_path=None):
    dataset = _load_dataset(dataset_path)
    if not dataset:
        return {"success": True, "total_pairs": 0}
    sources = {}
    types = {}
    chunk_ids = set()
    for item in dataset:
        source = item.get("source", "unknown")
        sources[source] = sources.get(source, 0) + 1
        t = item.get("type", "unknown")
        types[t] = types.get(t, 0) + 1
        ids = item.get("relevant_chunk_ids", [])
        if isinstance(ids, list):
            chunk_ids.update(ids)
        elif isinstance(ids, str):
            chunk_ids.add(ids)
    return {
        "success": True,
        "total_pairs": len(dataset),
        "unique_chunk_ids": len(chunk_ids),
        "sources": sources,
        "types": types
    }