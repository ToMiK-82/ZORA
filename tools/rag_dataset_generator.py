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
import re
from datetime import datetime
from typing import Dict, Any, List, Optional, Set
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)


def extract_entities(text: str, metadata: Dict[str, Any] = None) -> Set[str]:
    """Извлекает из текста и метаданных конкретные сущности: даты, числа, коды, имена, заголовки."""
    entities = set()

    # Даты
    date_patterns = [
        r'\b\d{2}\.\d{2}\.\d{4}\b',
        r'\b\d{4}-\d{2}-\d{2}\b',
    ]
    for pat in date_patterns:
        entities.update(re.findall(pat, text))

    # Положительные числа
    numbers = re.findall(r'\b\d+(?:[.,]\d+)?\b', text)
    for num in numbers:
        try:
            value = float(num.replace(',', '.'))
            if value > 0:
                entities.add(num)
        except:
            pass

    # UUID и составные коды
    uuid_pattern = r'\b[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}\b'
    entities.update(re.findall(uuid_pattern, text))
    code_pattern = r'\b[A-Z0-9]{2,}-[A-Z0-9-]+\b'  # коды типа 2AL-58D0AEC3-...
    entities.update(re.findall(code_pattern, text))

    # Имена собственные (слова с заглавной буквы, не первые в предложении)
    proper_pattern = r'(?<=[^\n\.\?!]\s)\b[А-ЯA-Z][а-яa-z]{2,}\b'
    entities.update(re.findall(proper_pattern, text))

    # Метаданные
    if metadata:
        brand = metadata.get("brand", "")
        if brand:
            entities.add(brand)
        title = metadata.get("doc_title", "") or metadata.get("filename", "")
        if title:
            entities.add(title)

    # Оставляем не более 20 самых длинных (наиболее специфичных)
    entities = set(sorted(entities, key=lambda x: -len(x))[:20])
    return entities


# ---------- НАСТРОЙКИ ----------
MAX_CHUNKS = 500                # <-- измените, если нужно другое число
BATCH_SIZE = 10                 # размер батча для параллельных запросов
# ------------------------------

# Слова и фразы, которые делают вопрос непригодным для оценки
FORBIDDEN_PATTERNS = [
    r'\bэто(т|м|го)\s+фрагмент[а-я]*\b',
    r'\bданн(ый|ом|ого)\s+фрагмент[а-я]*\b',
    r'\bуказанн(ый|ом|ого)\s+фрагмент[а-я]*\b',
    r'\bприведённ(ый|ом|ого)\s+фрагмент[а-я]*\b',
    r'\bв\s+(этом|данном|указанном|приведённом)\s+фрагменте\b',
    r'\bво\s+фрагменте\b',
    r'\bиз\s+фрагмента\b',
    r'\bв\s+начале\s+(текста|фрагмента)\b',
    r'\bв\s+конце\s+(текста|фрагмента)\b',
    r'\bуказанн(ый|ая|ое|ые)\s+выше\b',
    r'\bуказанн(ый|ая|ое|ые)\s+ниже\b',
    r'\bперечислен[а-я]*\s+в\s+фрагменте\b',
    r'\bсогласно\s+фрагменту\b',
    r'\bописанн(ый|ая|ое|ые)\s+в\s+фрагменте\b',
    r'\bупомянут(ый|ая|ое|ые)\s+в\s+фрагменте\b',
    r'\b(первом|втором|третьем|последнем)\s+предложении\s+фрагмента\b',
    r'\b(первом|втором|третьем)\s+абзаце\b',
    r'\bэт(от|а|и|ого|ому|им|ом|ой|их|ими)\s+документ[а-я]*\b',
    r'\bкакой\s+фрагмент\b',
    r'\bкакого\s+фрагмента\b',
    r'\bо\s+каком\s+фрагменте\b',
]

# Типы, для которых вопросы наиболее критичны
TYPE_SPECIFIC_HINTS = {
    "catalog": "Указывай тип объекта 1С (справочник, документ, регистр) и конкретное имя сущности, например: «Какой БИК у банка СБЕРБАНК в справочнике БанковскиеСчета?»",
    "document": "Указывай номер документа, дату, контрагента, например: «Какая сумма в документе ПоступлениеТоваровУслуг №123 от 01.02.2025?»",
    "product": "Указывай название продукта, бренд, артикул, например: «Какой диаметр гранул у комбикорма Брюхокорм СТАРТ?»",
    "page": "Указывай заголовок статьи, дату публикации, конкретные термины, например: «Какие отделы желудка описаны в статье 'Кормление жвачных'?»",
}

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


def _validate_question(question: str) -> bool:
    """Проверяет, что вопрос не содержит дейктических ссылок на фрагмент/документ."""
    if not question or len(question.strip()) < 10:
        return False
    question_lower = question.lower()
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, question_lower):
            return False
    return True


def validate_question_concrete(question: str, chunk_text: str, metadata: Dict[str, Any]) -> bool:
    """Проверяет, что вопрос достаточно конкретный для оценки RAG.
    Пропускает вопросы с числами, названиями в кавычках или содержащие сущности из чанка."""
    if not question or len(question.strip()) < 15:
        return False

    # Отсекаем явные ссылки на "фрагмент", "документ" без названия
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, question.lower()):
            return False

    # Если вопрос содержит число или название в кавычках — он достаточно конкретный
    if re.search(r'\d', question) or '«' in question or '"' in question:
        return True

    # Если в исходном чанке есть извлечённые сущности, хотя бы одна должна быть в вопросе
    entities = extract_entities(chunk_text, metadata)
    if entities:
        question_lower = question.lower()
        for ent in entities:
            if ent.lower() in question_lower:
                return True
        # Сущности есть, но вопрос их не содержит — отклоняем
        return False

    # Если сущностей нет, разрешаем длинные вопросы (более 60 символов)
    return len(question) > 60


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
        # Проверяем кешированный вопрос через позитивную валидацию
        if not validate_question_concrete(cached_question, chunk_text, chunk_metadata):
            logger.debug(f"Кешированный вопрос не прошёл конкретную валидацию, перегенерируем")
        else:
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

    # Извлекаем сущности для подсказки LLM и валидации
    entities = extract_entities(chunk_text, chunk_metadata)
    entities_hint = ""
    if entities:
        entities_hint = f"\n**Обязательные сущности (включи в вопрос хотя бы одну):** {', '.join(sorted(entities)[:10])}\n"

    # Подсказка для конкретного типа данных
    type_hint = TYPE_SPECIFIC_HINTS.get(chunk_type, "Указывай конкретные названия, имена, даты, числа из фрагмента.")

    prompt = f"""Ты — генератор тестовых вопросов для оценки поисковой системы (RAG).

Прочитай фрагмент документа и придумай ОДИН вопрос, ответ на который можно найти ТОЛЬКО в этом фрагменте.

Тип данных: {chunk_type} ({type_hint})
Источник: {chunk_source}

Фрагмент: {text_preview}
{entities_hint}
**ЖЁСТКИЕ ТРЕБОВАНИЯ К ВОПРОСУ (нарушать нельзя):**

1. **НИКАКИХ ссылок на фрагмент, текст, документ.** Запрещены слова: «этот фрагмент», «в данном фрагменте», «указанный выше», «в начале текста», «в первом предложении», «согласно фрагменту», «описанный в», «упомянутый в» и подобные. Вопрос должен быть самодостаточным.

2. **Вопрос должен содержать конкретные сущности из текста:** названия продуктов, бренды, имена людей, названия организаций, идентификаторы (GUID, Ref_Key), даты, номера строк, БИК, SWIFT, суммы.

3. **Если в чанке несколько записей или строк,** вопрос должен явно идентифицировать, о какой именно записи речь (через имя, идентификатор, номер строки, бренд).

4. **Вопрос должен звучать так, как будто его задаёт реальный пользователь,** который не видит текст, но знает, что ищет.

5. **Вопрос должен быть ОДНИМ.** Не надо генерировать несколько вопросов.

**Примеры ПРАВИЛЬНЫХ вопросов:**
- «Какой БИК указан для банка СБЕРБАНК в справочнике БанковскиеСчета?»
- «Какая масса нетто у продукта Брюхокорм СТАРТ для бройлеров?»
- «Какая дата изменения у записи контрагента ООО "Заря"?»
- «Сколько процентов протеина содержится в комбикорме РОСТ согласно спецификации?»

**Примеры НЕПРАВИЛЬНЫХ вопросов (такие генерировать НЕЛЬЗЯ):**
- «Какие физические свойства перечислены в первом предложении фрагмента?» ← Ссылка на фрагмент
- «С какого дня выращивания рекомендуется включать в рацион указанный продукт?» ← «Указанный» без названия
- «Какая дата изменения записи?» ← Нет конкретного имени/ID
- «Какой статус у документа?» ← Непонятно, у какого документа

Верни ТОЛЬКО JSON-объект без пояснений и без Markdown:
{{"question": "..."}}

Если невозможно придумать корректный вопрос, верни: {{"question": ""}}
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
        # Очистка от Markdown-обёрток
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0].strip()
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0].strip()

        result = json.loads(json_str)
        if not isinstance(result, dict):
            # Иногда LLM возвращает массив из одного элемента
            if isinstance(result, list) and len(result) > 0 and isinstance(result[0], dict):
                result = result[0]
            else:
                return []

        question = result.get("question", "").strip()
        if not question:
            return []

        # Позитивная валидация через сущности (заменяет старую _validate_question)
        if not validate_question_concrete(question, chunk_text, chunk_metadata):
            logger.debug(f"Вопрос не прошёл конкретную валидацию: {question[:80]}")
            return []

        # Дополнительная страховка: старая проверка на дейктические ссылки
        if not _validate_question(question):
            logger.warning(f"Вопрос не прошёл валидацию (дейктические ссылки): {question[:100]}")
            return []

        return [{
            "question": question,
            "chunk_id": chunk_id,
            "chunk_text_preview": chunk_text[:200],
            "source": chunk_source,
            "type": chunk_type
        }]
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
    Для каждого чанка находит соседние (parent_doc_id совпадает, chunk_index отличается на 1–2).
    Возвращает словарь: chunk_id -> [соседние chunk_id]
    """
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

    neighbor_index = {}
    for parent, items in doc_groups.items():
        items.sort(key=lambda x: x[1])
        for i, (chunk_id, idx) in enumerate(items):
            neighbors = []
            # Берём ±2 соседних чанка
            for offset in [-2, -1, 1, 2]:
                neighbor_idx = i + offset
                if 0 <= neighbor_idx < len(items):
                    neighbors.append(items[neighbor_idx][0])
            neighbor_index[chunk_id] = neighbors

    total_neighbors = sum(len(v) for v in neighbor_index.values())
    logger.info(f"Построен индекс соседей: {len(neighbor_index)} чанков, {total_neighbors} связей")
    return neighbor_index


def generate_dataset(
    dataset_path: Optional[str] = None,
    max_chunks: int = MAX_CHUNKS,
    incremental: bool = True,
    batch_size: int = BATCH_SIZE
) -> Dict[str, Any]:

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

    if incremental and existing_chunk_ids:
        new_chunks = [c for c in all_chunks if c["metadata"].get("chunk_id") not in existing_chunk_ids]
    else:
        new_chunks = all_chunks

    random.shuffle(new_chunks)
    selected_chunks = new_chunks[:max_chunks]
    logger.info(f"Отобрано для генерации: {len(selected_chunks)} чанков (из {len(new_chunks)} новых)")

    if not selected_chunks:
        return {"success": True, "message": "Нет новых чанков", "total_pairs": len(existing_dataset)}

    neighbor_index = _build_neighbor_index(all_chunks)

    question_cache = QuestionCache()
    new_pairs = []
    chunks_processed = 0
    errors = 0
    invalid_questions_filtered = 0

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
                        # Дополнительная проверка через позитивную валидацию (по chunk_text_preview)
                        if not validate_question_concrete(q.get("question", ""), q.get("chunk_text_preview", ""), {}):
                            invalid_questions_filtered += 1
                            logger.debug(f"Отфильтрован неконкретный вопрос: {q.get('question', '')[:80]}")
                            continue
                        chunk_id = q["chunk_id"]
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

    if invalid_questions_filtered > 0:
        logger.info(f"Отфильтровано невалидных вопросов: {invalid_questions_filtered}")

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
        "invalid_questions_filtered": invalid_questions_filtered,
    }
    logger.info(f"✅ Генерация завершена: {result}")
    return result


def run_generation_async(dataset_path=None, max_chunks=MAX_CHUNKS, incremental=True, chunk_types=None):
    global _generation_running
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


def cleanup_dataset(dataset_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Удаляет из датасета все вопросы с дейктическими ссылками.
    Возвращает статистику удаления.
    """
    path = dataset_path or DEFAULT_DATASET_PATH
    dataset = _load_dataset(path)
    if not dataset:
        return {"success": True, "removed": 0, "remaining": 0}

    original_count = len(dataset)
    cleaned = []
    removed = 0
    for item in dataset:
        query = item.get("query", "")
        if _validate_question(query):
            cleaned.append(item)
        else:
            removed += 1
            logger.debug(f"Удалён невалидный вопрос: {query[:100]}...")

    _save_dataset(cleaned, path)
    logger.info(f"Очистка датасета: удалено {removed} из {original_count} записей")
    return {"success": True, "removed": removed, "remaining": len(cleaned)}