"""
Модуль для работы с векторной базой данных Qdrant.
Поддерживает гибридный поиск (dense + keyword) и ре-ранкер на базе CrossEncoder.
Модель эмбеддингов: bge-m3 (1024 мерности) через Ollama.
"""

import logging
import os
import threading
from typing import List, Optional, Dict, Any
from uuid import uuid4

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models
    from qdrant_client.models import Prefetch, Filter, FieldCondition, MatchAny
    QDRANT_AVAILABLE = True
except ImportError as e:
    logging.warning(f"⚠️ Библиотека qdrant-client не установлена: {e}")
    QDRANT_AVAILABLE = False
    # Заглушки
    class QdrantClient:
        pass
    class models:
        pass
    class Prefetch:
        pass
    class Filter:
        pass
    class FieldCondition:
        pass
    class MatchAny:
        pass

try:
    from connectors.embedding_client import embedding_client
except ImportError:
    def generate_embedding(text, model=None):
        return [0.0] * 1024
    embedding_client = None

logger = logging.getLogger(__name__)

# Глобальный ре-ранкер (ленивая загрузка)
_reranker = None
_reranker_lock = threading.Lock()
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "DiTy/cross-encoder-russian-msmarco")


def _get_reranker():
    """Ленивая загрузка CrossEncoder ре-ранкера."""
    global _reranker
    if _reranker is None:
        with _reranker_lock:
            if _reranker is None:
                try:
                    from sentence_transformers import CrossEncoder
                    logger.info(f"🔄 Загрузка ре-ранкера {RERANKER_MODEL}...")
                    _reranker = CrossEncoder(RERANKER_MODEL, max_length=512)
                    logger.info(f"✅ Ре-ранкер {RERANKER_MODEL} загружен")
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось загрузить ре-ранкер: {e}. Ре-ранкинг отключён.")
                    _reranker = False  # False = попытка была, но не удалась
    return _reranker if _reranker else None


class ZoraMemory:
    def __init__(self, host=None, port=None, collection_name="zora_memory",
                 embedding_model="bge-m3", embedding_size=1024,
                 optimizers_config: Optional[Dict] = None):
        if not QDRANT_AVAILABLE:
            raise ImportError("Установите qdrant-client")

        host = host or os.getenv("QDRANT_HOST", "localhost")
        port = port or int(os.getenv("QDRANT_PORT", "6333"))

        self.client = QdrantClient(host=host, port=port, timeout=30)
        self.collection_name = collection_name
        self.embedding_model = embedding_model
        self.embedding_size = embedding_size
        self.optimizers_config = optimizers_config or self._default_optimizers_config()
        self._ensure_collection()

    def _default_optimizers_config(self) -> Dict:
        config = {
            "indexing_threshold": 20000,
            "flush_interval_sec": 5,
            "max_optimization_threads": 2,
            "memmap_threshold": 50000,
            "max_segment_size": 100000,
            "default_segment_number": 10,
        }
        env_config = self._load_optimizers_from_env()
        config.update(env_config)
        return config

    def _load_optimizers_from_env(self) -> Dict:
        config = {}
        for key in ["indexing_threshold", "flush_interval_sec", "max_optimization_threads",
                    "memmap_threshold", "max_segment_size", "default_segment_number"]:
            env_val = os.getenv(f"QDRANT_{key.upper()}")
            if env_val is not None:
                try:
                    config[key] = int(env_val)
                except ValueError:
                    logging.warning(f"Неверное значение переменной окружения QDRANT_{key.upper()}: {env_val}")
        return config

    def _ensure_collection(self):
        try:
            self.client.get_collection(self.collection_name)
            logger.info(f"Коллекция {self.collection_name} уже существует")
        except Exception:
            optimizers_diff = models.OptimizersConfigDiff(**self.optimizers_config)
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=self.embedding_size,
                    distance=models.Distance.COSINE,
                ),
                optimizers_config=optimizers_diff,
            )
            logger.info(f"Коллекция {self.collection_name} создана с размерностью {self.embedding_size}")

    def _ensure_text_index(self):
        """Создаёт полнотекстовый индекс на поле text, если его нет."""
        try:
            self.client.create_field_index(
                collection_name=self.collection_name,
                field_name="text",
                field_schema=models.TextIndexParams(
                    type=models.TextIndexType.TEXT,
                    tokenizer=models.TokenizerType.WORD,
                    min_token_len=2,
                    max_token_len=20,
                    lowercase=True,
                )
            )
            logger.info(f"✅ Полнотекстовый индекс на поле 'text' создан для {self.collection_name}")
        except Exception as e:
            # Индекс может уже существовать — это нормально
            logger.debug(f"Полнотекстовый индекс (возможно уже есть): {e}")

    def _embed_text(self, text: str) -> List[float]:
        try:
            global embedding_client
            if embedding_client is None:
                try:
                    from connectors.embedding_client import embedding_client as ec
                    embedding_client = ec
                    logger.info(f"embedding_client импортирован: {embedding_client}")
                except ImportError as e:
                    logger.error(f"Не удалось импортировать embedding_client: {e}")
                    return [0.0] * self.embedding_size

            if embedding_client:
                logger.debug(f"Генерация эмбеддинга для текста: {text[:50]}...")
                emb = embedding_client.generate_embedding(text)
                if emb and len(emb) == self.embedding_size:
                    if all(v == 0.0 for v in emb[:10]):
                        logger.warning("Эмбеддинг состоит из нулей!")
                    return emb
                else:
                    logger.warning(f"Неверный размер эмбеддинга: {len(emb) if emb else 'None'} вместо {self.embedding_size}")
            else:
                logger.error("embedding_client не доступен")
        except Exception as e:
            logger.error(f"Ошибка эмбеддинга: {e}")
            import traceback
            logger.error(traceback.format_exc())
        return [0.0] * self.embedding_size

    def store(self, text: str, metadata: Optional[Dict] = None,
              agent: Optional[str] = None, timestamp: Optional[float] = None) -> str:
        if metadata is None:
            metadata = {}
        if agent:
            metadata["agent"] = agent
        if timestamp:
            metadata["timestamp"] = timestamp
        point_id = str(uuid4())

        vector = self._embed_text(text)
        logger.info(f"store: text='{text[:50]}...', vector_size={len(vector)}, first_5={vector[:5]}")

        if all(v == 0.0 for v in vector[:10]):
            logger.warning("store: Вектор состоит из нулей!")

        try:
            vector_float = [float(v) for v in vector]
            self.client.upsert(
                collection_name=self.collection_name,
                points=[
                    models.PointStruct(
                        id=point_id,
                        vector=vector_float,
                        payload={"text": text, **metadata},
                    )
                ],
            )
            logger.info(f"store: Точка сохранена с ID: {point_id}")
        except Exception as e:
            logger.error(f"store: Ошибка сохранения точки: {e}")
            try:
                import numpy as np
                vector_np = np.array(vector, dtype=np.float32)
                self.client.upsert(
                    collection_name=self.collection_name,
                    points=[
                        models.PointStruct(
                            id=point_id,
                            vector=vector_np.tolist(),
                            payload={"text": text, **metadata},
                        )
                    ],
                )
                logger.info(f"store: Точка сохранена с ID: {point_id} (через numpy)")
            except Exception as e2:
                logger.error(f"store: Ошибка сохранения через numpy: {e2}")
                raise

        return point_id

    def delete_by_filter(self, filter_dict: Dict[str, Any]):
        try:
            filter_condition = models.Filter(
                must=[models.FieldCondition(key=k, match=models.MatchValue(value=v)) for k, v in filter_dict.items()]
            )
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=filter_condition
            )
            logger.info(f"🗑️ Удалены точки по фильтру: {filter_dict}")
        except Exception as e:
            logger.error(f"Ошибка удаления по фильтру {filter_dict}: {e}")

    def search(self, query: str, limit: int = 5, agent: Optional[str] = None,
               threshold: float = 0.7, types: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Поиск в памяти. Теперь использует hybrid_search с ре-ранкером.
        Для обратной совместимости.
        """
        return self.hybrid_search(query=query, types=types, limit=limit, score_threshold=threshold)

    def hybrid_search(self, query: str, types: Optional[List[str]] = None,
                      limit: int = 5, score_threshold: float = 0.0) -> List[Dict[str, Any]]:
        """
        Гибридный поиск: dense (векторный) + keyword (полнотекстовый) с RRF-слиянием.
        Затем ре-ранкинг через CrossEncoder для финального топ-N.

        Args:
            query: Текстовый запрос
            types: Список типов для фильтрации (например, ["catalog", "document"])
            limit: Количество результатов
            score_threshold: Порог оценки (0.0 = без фильтра)

        Returns:
            Список словарей с результатами
        """
        logger.info(f"Гибридный поиск: запрос='{query}', types={types}, limit={limit}")

        # 1. Получаем эмбеддинг запроса
        query_embedding = self._embed_text(query)

        # 2. Строим фильтр по типам
        must_conditions = []
        if types:
            must_conditions.append(
                FieldCondition(key="type", match=MatchAny(any=types))
            )
        query_filter = Filter(must=must_conditions) if must_conditions else None

        # 3. Prefetch: dense + keyword
        prefetch_limit = limit * 4  # берём с запасом для ре-ранкера
        prefetch = [
            Prefetch(
                query=query_embedding,
                using="",          # dense index (основной вектор)
                limit=prefetch_limit,
                score_threshold=score_threshold,
            ),
            Prefetch(
                query=query,
                using="text",      # keyword index (полнотекстовый)
                limit=prefetch_limit,
                score_threshold=score_threshold,
            )
        ]

        try:
            results = self.client.query_points(
                collection_name=self.collection_name,
                prefetch=prefetch,
                query_filter=query_filter,
                limit=prefetch_limit * 2,
                score_threshold=score_threshold,
            ).points
        except Exception as e:
            logger.error(f"Ошибка гибридного поиска: {e}")
            # Fallback на обычный dense search
            return self._dense_search_fallback(query, query_embedding, query_filter, limit, score_threshold)

        # 4. Дедупликация по ID
        seen_ids = set()
        unique_results = []
        for hit in results:
            if hit.id not in seen_ids:
                seen_ids.add(hit.id)
                unique_results.append(hit)

        if not unique_results:
            logger.info("Гибридный поиск не дал результатов")
            return []

        # 5. Ре-ранкинг через CrossEncoder
        reranker = _get_reranker()
        if reranker and len(unique_results) > 1:
            try:
                pairs = [(query, hit.payload.get("text", "")) for hit in unique_results]
                scores = reranker.predict(pairs)
                ranked = sorted(zip(unique_results, scores), key=lambda x: x[1], reverse=True)
                unique_results = [r[0] for r in ranked[:limit]]
                logger.debug(f"Ре-ранкинг выполнен: {len(unique_results)} результатов")
            except Exception as e:
                logger.warning(f"Ошибка ре-ранкинга: {e}, использую результаты без ре-ранкинга")
                unique_results = unique_results[:limit]
        else:
            unique_results = unique_results[:limit]

        # 6. Форматирование результата
        formatted = []
        for hit in unique_results:
            payload = hit.payload or {}
            formatted.append({
                "id": str(hit.id),
                "text": payload.get("text", ""),
                "metadata": {k: v for k, v in payload.items() if k != "text"},
                "score": getattr(hit, 'score', 0.0),
                "path": payload.get("path", ""),
                "filename": payload.get("filename", ""),
                "type": payload.get("type", ""),
            })

        logger.info(f"Гибридный поиск: найдено {len(formatted)} результатов")
        return formatted

    def _dense_search_fallback(self, query: str, query_embedding: List[float],
                                query_filter, limit: int, score_threshold: float) -> List[Dict[str, Any]]:
        """Fallback на обычный dense search, если hybrid_search не сработал."""
        logger.info("Fallback на dense search")
        try:
            results = self.client.query_points(
                collection_name=self.collection_name,
                query=query_embedding,
                query_filter=query_filter,
                limit=limit,
                score_threshold=score_threshold,
            ).points
        except Exception as e:
            logger.error(f"Ошибка dense search fallback: {e}")
            return []

        formatted = []
        for hit in results:
            payload = hit.payload or {}
            formatted.append({
                "id": str(hit.id),
                "text": payload.get("text", ""),
                "metadata": {k: v for k, v in payload.items() if k != "text"},
                "score": hit.score,
                "path": payload.get("path", ""),
                "filename": payload.get("filename", ""),
                "type": payload.get("type", ""),
            })
        return formatted

    def clear(self):
        self.client.delete_collection(self.collection_name)
        self._ensure_collection()

    def get_collection_info(self):
        try:
            info = self.client.get_collection(self.collection_name)
            return {"name": self.collection_name, "vectors_count": info.vectors_count}
        except Exception as e:
            return {"error": str(e)}


memory = ZoraMemory()
