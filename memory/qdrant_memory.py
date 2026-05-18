"""
Модуль для работы с векторной базой данных Qdrant.
Поддерживает гибридный поиск (dense + keyword) и ре-ранкер на базе CrossEncoder.
Модель эмбеддингов: mxbai-embed-large (1024 размерности) через Ollama.
"""

import logging
import os
import threading
from typing import List, Optional, Dict, Any
from uuid import uuid4

import httpx

from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.models import Prefetch, Filter

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
                    _reranker = False
    return _reranker if _reranker else None


class ZoraMemory:
    def __init__(self, host=None, port=None, collection_name="zora_memory",
                 embedding_model="mxbai-embed-large", embedding_size=1024,
                 optimizers_config: Optional[Dict] = None):
        host = host or os.getenv("QDRANT_HOST", "localhost")
        port = port or int(os.getenv("QDRANT_PORT", "6333"))

        self.client = QdrantClient(host=host, port=port, timeout=30)
        self.collection_name = collection_name
        self.embedding_model = embedding_model
        self.embedding_size = embedding_size
        self.optimizers_config = optimizers_config or self._default_optimizers_config()

        # Проверяем версию Qdrant (нужна >= 1.10 для гибридного поиска)
        self._supports_hybrid = self._check_qdrant_version()

        self._ensure_collection()
        self._ensure_text_index()

    def _check_qdrant_version(self) -> bool:
        """Проверяет, поддерживает ли сервер Qdrant гибридный поиск (>= 1.10)."""
        try:
            info = self.client.info()
            version_str = info.version
            parts = version_str.split(".")
            major, minor = int(parts[0]), int(parts[1])
            if major > 1 or (major == 1 and minor >= 10):
                logger.info(f"Qdrant версии {version_str} поддерживает гибридный поиск")
                return True
            else:
                logger.warning(f"Qdrant версии {version_str} не поддерживает гибридный поиск. Будет использован только dense.")
                return False
        except Exception as e:
            logger.error(f"Не удалось определить версию Qdrant: {e}")
            return False

    def _default_optimizers_config(self) -> Dict:
        config = {
            "indexing_threshold": 20000,
            "flush_interval_sec": 5,
            "max_optimization_threads": 2,
            "memmap_threshold": 50000,
            "max_segment_size": 100000,
            "default_segment_number": 10,
        }
        for key in config:
            env_val = os.getenv(f"QDRANT_{key.upper()}")
            if env_val is not None:
                try:
                    config[key] = int(env_val)
                except ValueError:
                    logger.warning(f"Неверное значение QDRANT_{key.upper()}: {env_val}")
        return config

    def _ensure_collection(self):
        try:
            self.client.get_collection(self.collection_name)
            logger.info(f"Коллекция {self.collection_name} уже существует")
        except Exception:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=self.embedding_size,
                    distance=models.Distance.COSINE,
                ),
                optimizers_config=models.OptimizersConfigDiff(**self.optimizers_config),
            )
            logger.info(f"Коллекция {self.collection_name} создана с размерностью {self.embedding_size}")

    def _ensure_text_index(self):
        """Создаёт полнотекстовый индекс на поле text, если его нет.
        Сначала пробует create_field_index (qdrant-client >= 1.12),
        при AttributeError переключается на HTTP REST API."""
        # Вариант 1: через qdrant-client (если версия поддерживает)
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
            return
        except AttributeError:
            logger.warning("create_field_index не поддерживается клиентом, пробуем через REST API")
        except Exception as e:
            if "already exists" in str(e).lower():
                logger.debug("Индекс уже существует")
                return
            logger.warning(f"Ошибка create_field_index: {e}. Пробуем через REST API.")

        # Вариант 2: через HTTP REST API (работает с любой версией сервера)
        try:
            host = self.client._host if hasattr(self.client, '_host') else os.getenv("QDRANT_HOST", "localhost")
            port = self.client._port if hasattr(self.client, '_port') else os.getenv("QDRANT_PORT", "6333")
            url = f"http://{host}:{port}/collections/{self.collection_name}/index"
            payload = {"field_name": "text", "field_schema": "text"}
            resp = httpx.put(url, json=payload, timeout=10)
            if resp.status_code == 200:
                logger.info(f"✅ Текстовый индекс на поле 'text' создан (REST API) для {self.collection_name}")
            elif resp.status_code == 400 and "already exists" in resp.text.lower():
                logger.debug("Индекс уже существует (REST)")
            else:
                logger.warning(f"Неожиданный ответ REST API: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            logger.error(f"Ошибка создания индекса через REST API: {e}")

    def _embed_text(self, text: str) -> List[float]:
        try:
            from connectors.embedding_client import embedding_client
            emb = embedding_client.generate_embedding(text)
            if emb and len(emb) == self.embedding_size:
                return emb
            logger.warning(f"Размер эмбеддинга {len(emb) if emb else 'None'} != {self.embedding_size}")
        except Exception as e:
            logger.error(f"Ошибка эмбеддинга: {e}")
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

        try:
            self.client.upsert(
                collection_name=self.collection_name,
                points=[
                    models.PointStruct(
                        id=point_id,
                        vector=[float(v) for v in vector],
                        payload={"text": text, **metadata},
                    )
                ],
            )
            logger.info(f"store: Точка сохранена с ID: {point_id}")
            return point_id
        except Exception as e:
            logger.error(f"store: Ошибка сохранения: {e}")
            raise

    def delete_by_filter(self, filter_dict: Dict[str, Any]):
        from qdrant_client.models import FieldCondition
        filter_condition = Filter(
            must=[FieldCondition(key=k, match=models.MatchValue(value=v)) for k, v in filter_dict.items()]
        )
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=filter_condition
        )
        logger.info(f"🗑️ Удалены точки по фильтру: {filter_dict}")

    def search(self, query: str, limit: int = 5, agent: Optional[str] = None,
               threshold: float = 0.0, types: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Единый интерфейс поиска, делегирует в hybrid_search."""
        return self.hybrid_search(query=query, types=types, limit=limit, score_threshold=threshold)

    def hybrid_search(self, query: str, types: Optional[List[str]] = None,
                      limit: int = 5, score_threshold: float = 0.0) -> List[Dict[str, Any]]:
        """
        Гибридный поиск (dense + keyword) с ре-ранкером.
        Если Qdrant не поддерживает Prefetch, автоматически переключается на dense.
        """
        logger.info(f"Гибридный поиск: запрос='{query}', types={types}, limit={limit}")

        # Если нет поддержки гибридного — сразу dense
        if not self._supports_hybrid:
            logger.info("Гибридный поиск отключён, используется dense")
            return self._dense_search(query, types, limit, score_threshold)

        query_embedding = self._embed_text(query)

        # Импортируем всё необходимое внутри функции, чтобы избежать конфликтов с глобальным импортом
        from qdrant_client.models import FieldCondition, MatchAny, NearestQuery, Filter as QdrantFilter, MatchText

        # Фильтр по типам
        must = []
        if types:
            must.append(FieldCondition(key="type", match=MatchAny(any=types)))
        query_filter = Filter(must=must) if must else None

        prefetch_limit = limit * 4

        # Qdrant 1.17.1 не поддерживает prefetch с keyword (строковым) запросом.
        # Поэтому делаем два отдельных запроса и объединяем результаты.

        # 1. Dense поиск через query_points с prefetch (только dense)
        try:
            dense_prefetch = [
                Prefetch(
                    query=NearestQuery(nearest=query_embedding),
                    using="",
                    limit=prefetch_limit,
                )
            ]
            dense_results = self.client.query_points(
                collection_name=self.collection_name,
                prefetch=dense_prefetch,
                query=query_embedding,
                query_filter=query_filter,
                limit=prefetch_limit,
                score_threshold=score_threshold,
            ).points
        except Exception as e:
            logger.error(f"Ошибка dense prefetch: {e}. Переключаюсь на dense.")
            return self._dense_search(query, types, limit, score_threshold)

        # 2. Keyword поиск через scroll с match на text
        try:
            # FieldCondition и MatchAny импортированы глобально (from qdrant_client.models import FieldCondition, MatchAny)
            keyword_filter = QdrantFilter(
                must=[FieldCondition(key="text", match=MatchText(text=query))]
            )
            if types:
                keyword_filter.must.append(FieldCondition(key="type", match=MatchAny(any=types)))

            keyword_results = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=keyword_filter,
                limit=prefetch_limit,
                with_payload=True,
            )[0]
        except Exception as e:
            logger.warning(f"Ошибка keyword поиска: {e}. Использую только dense.")
            keyword_results = []

        # 3. Объединение результатов (дедупликация по id)
        seen_ids = set()
        combined = []
        for hit in dense_results + keyword_results:
            if hit.id not in seen_ids:
                seen_ids.add(hit.id)
                combined.append(hit)

        if not combined:
            logger.info("Гибридный поиск не дал результатов")
            return []

        # Ре-ранкер
        reranker = _get_reranker()
        if reranker and len(combined) > 1:
            try:
                pairs = [(query, hit.payload.get("text", "")) for hit in combined]
                scores = reranker.predict(pairs)
                combined = [hit for _, hit in sorted(zip(scores, combined), key=lambda x: x[0], reverse=True)]
            except Exception as e:
                logger.warning(f"Ошибка ре-ранкинга: {e}")

        # Форматирование
        formatted = []
        for hit in combined[:limit]:
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

    def _dense_search(self, query: str, types: Optional[List[str]] = None,
                      limit: int = 5, score_threshold: float = 0.0) -> List[Dict[str, Any]]:
        """Обычный плотный поиск (используется, если гибридный недоступен или произошла ошибка)."""
        from qdrant_client.models import FieldCondition, MatchAny
        query_embedding = self._embed_text(query)
        must = []
        if types:
            must.append(FieldCondition(key="type", match=MatchAny(any=types)))
        query_filter = Filter(must=must) if must else None

        try:
            results = self.client.query_points(
                collection_name=self.collection_name,
                query=query_embedding,
                query_filter=query_filter,
                limit=limit,
                score_threshold=score_threshold,
            ).points
        except Exception as e:
            logger.error(f"Ошибка dense поиска: {e}")
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
        self._ensure_text_index()

    def get_collection_info(self):
        try:
            info = self.client.get_collection(self.collection_name)
            # qdrant-client 1.18+ использует points_count вместо vectors_count
            count = getattr(info, 'points_count', None) or getattr(info, 'vectors_count', 0)
            return {"name": self.collection_name, "vectors_count": count}
        except Exception as e:
            return {"error": str(e)}


memory = ZoraMemory()