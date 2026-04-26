"""
Модуль для работы с векторной базой данных Qdrant.
"""

import logging
import os
from typing import List, Optional, Dict, Any
from uuid import uuid4

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models
    QDRANT_AVAILABLE = True
except ImportError as e:
    logging.warning(f"⚠️ Библиотека qdrant-client не установлена: {e}")
    QDRANT_AVAILABLE = False
    class QdrantClient:
        pass
    class models:
        pass

try:
    from connectors.embedding_client import embedding_client
except ImportError:
    # Fallback для обратной совместимости
    def generate_embedding(text, model=None):
        return [0.0] * 768
    embedding_client = None


class ZoraMemory:
    def __init__(self, host=None, port=None, collection_name="zora_memory",
                 embedding_model="nomic-embed-text", embedding_size=768,
                 optimizers_config: Optional[Dict] = None):
        if not QDRANT_AVAILABLE:
            raise ImportError("Установите qdrant-client")
        
        # Используем переменные окружения или значения по умолчанию
        host = host or os.getenv("QDRANT_HOST", "localhost")
        port = port or int(os.getenv("QDRANT_PORT", "6333"))
        
        self.client = QdrantClient(host=host, port=port, timeout=30)
        self.collection_name = collection_name
        self.embedding_model = embedding_model
        self.embedding_size = embedding_size
        self.optimizers_config = optimizers_config or self._default_optimizers_config()
        self._ensure_collection()

    def _default_optimizers_config(self) -> Dict:
        """Возвращает настройки оптимизатора по умолчанию."""
        config = {
            "indexing_threshold": 20000,          # начать индексацию HNSW после 20k точек
            "flush_interval_sec": 5,              # сброс на диск каждые 5 сек
            "max_optimization_threads": 2,        # ограничить потоки оптимизации
            "memmap_threshold": 50000,            # использовать memmap после 50k точек
            "max_segment_size": 100000,           # максимальный размер сегмента (количество точек)
            "default_segment_number": 10,         # количество сегментов по умолчанию
        }
        # Переопределение из переменных окружения
        env_config = self._load_optimizers_from_env()
        config.update(env_config)
        return config

    def _load_optimizers_from_env(self) -> Dict:
        """Загружает настройки оптимизатора из переменных окружения."""
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
        except Exception:
            # Преобразуем конфигурацию в OptimizersConfigDiff
            optimizers_diff = models.OptimizersConfigDiff(**self.optimizers_config)
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=self.embedding_size,
                    distance=models.Distance.COSINE,
                ),
                optimizers_config=optimizers_diff,
            )
            logging.info(f"Коллекция {self.collection_name} создана с оптимизатором: {self.optimizers_config}")

    def _truncate_query(self, text: str, max_chars: int = 8000) -> str:
        """
        Обрезает текст запроса до указанного количества символов.
        nomic-embed-text поддерживает до 8192 токенов.
        """
        if len(text) <= max_chars:
            return text
        truncated = text[:max_chars]
        logging.warning(f"Запрос обрезан с {len(text)} до {max_chars} символов для эмбеддинга")
        return truncated

    def _embed_text(self, text: str) -> List[float]:
        try:
            # Обрезаем текст до 8000 символов (nomic-embed-text поддерживает до 8192 токенов)
            text = self._truncate_query(text, max_chars=8000)
            
            # Пытаемся импортировать embedding_client, если он не доступен
            global embedding_client
            if embedding_client is None:
                try:
                    from connectors.embedding_client import embedding_client as ec
                    embedding_client = ec
                    logging.info(f"embedding_client импортирован: {embedding_client}")
                except ImportError as e:
                    logging.error(f"Не удалось импортировать embedding_client: {e}")
                    return [0.0] * self.embedding_size
            
            # Используем embedding_client, который использует SentenceTransformer
            if embedding_client:
                logging.debug(f"Генерация эмбеддинга для текста: {text[:50]}...")
                emb = embedding_client.generate_embedding(text)
                # Проверяем размерность эмбеддинга
                if emb and len(emb) == self.embedding_size:
                    logging.debug(f"Эмбеддинг сгенерирован, размер: {len(emb)}")
                    # Проверим, не нулевой ли эмбеддинг
                    if all(v == 0.0 for v in emb[:10]):
                        logging.warning("Эмбеддинг состоит из нулей!")
                    return emb
                else:
                    logging.warning(f"Неверный размер эмбеддинга: {len(emb) if emb else 'None'} вместо {self.embedding_size}")
            else:
                logging.error("embedding_client не доступен")
        except Exception as e:
            logging.error(f"Ошибка эмбеддинга: {e}")
            import traceback
            logging.error(traceback.format_exc())
        # Возвращаем нулевой вектор в случае ошибки
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
        
        # Генерируем эмбеддинг
        vector = self._embed_text(text)
        logging.info(f"store: text='{text[:50]}...', vector_size={len(vector)}, first_5={vector[:5]}")
        
        # Проверяем, не нулевой ли вектор
        if all(v == 0.0 for v in vector[:10]):
            logging.warning("store: Вектор состоит из нулей!")
        
        # Преобразуем вектор в правильный формат для Qdrant
        # Qdrant ожидает список чисел с плавающей точкой
        try:
            # Убедимся, что все значения - float
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
            logging.info(f"store: Точка сохранена с ID: {point_id}")
        except Exception as e:
            logging.error(f"store: Ошибка сохранения точки: {e}")
            # Попробуем альтернативный метод
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
                logging.info(f"store: Точка сохранена с ID: {point_id} (через numpy)")
            except Exception as e2:
                logging.error(f"store: Ошибка сохранения через numpy: {e2}")
                raise
        
        return point_id

    def delete_by_filter(self, filter_dict: Dict[str, Any]):
        """
        Удаляет все точки, у которых в payload есть поля, совпадающие с filter_dict.
        Пример: memory.delete_by_filter({"path": "D:/file.py"})
        """
        try:
            filter_condition = models.Filter(
                must=[models.FieldCondition(key=k, match=models.MatchValue(value=v)) for k, v in filter_dict.items()]
            )
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=filter_condition
            )
            logging.info(f"🗑️ Удалены точки по фильтру: {filter_dict}")
        except Exception as e:
            logging.error(f"Ошибка удаления по фильтру {filter_dict}: {e}")

    def search(self, query: str, limit: int = 5, agent: Optional[str] = None,
               threshold: float = 0.7) -> List[Dict[str, Any]]:
        logging.info(f"Поиск в памяти: запрос='{query}' (repr: {repr(query)})")
        query_embedding = self._embed_text(query)
        filter_condition = None
        # Временно отключаем фильтр по агенту, так как при индексации поле agent не заполняется
        # if agent:
        #     filter_condition = models.Filter(
        #         must=[models.FieldCondition(key="agent", match=models.MatchValue(value=agent))]
        #     )
        try:
            # Используем query_points (современный метод)
            results = self.client.query_points(
                collection_name=self.collection_name,
                query=query_embedding,
                query_filter=filter_condition,
                limit=limit,
                score_threshold=threshold,
            ).points
        except Exception as e:
            logging.error(f"Ошибка поиска: {e}")
            return []
        formatted = []
        for hit in results:
            payload = hit.payload
            formatted.append({
                "text": payload.get("text", ""),
                "metadata": {k: v for k, v in payload.items() if k != "text"},
                "score": hit.score,
                "path": payload.get("path", ""),
                "filename": payload.get("filename", ""),
                "type": payload.get("type", ""),
            })
        logging.info(f"Найдено результатов: {len(formatted)}")
        return formatted

    def clear(self):
        self.client.delete_collection(self.collection_name)
        self._ensure_collection()

    def get_collection_info(self):
        try:
            info = self.client.get_collection(self.collection_name)
            return {"name": info.name, "vectors_count": info.vectors_count}
        except Exception as e:
            return {"error": str(e)}


memory = ZoraMemory()