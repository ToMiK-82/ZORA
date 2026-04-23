"""
Модуль для работы с векторной базой данных Qdrant.
Обеспечивает хранение и поиск контекста для агентов ZORA.
"""

import logging
from typing import List, Optional, Dict, Any
from uuid import uuid4

from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import UnexpectedResponse

from connectors.llm_client import llm_client


class ZoraMemory:
    """Класс для управления памятью агентов в Qdrant."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        collection_name: str = "zora_memory",
        embedding_model: str = "nomic-embed-text",
        embedding_size: int = 768,
    ):
        """
        Инициализация клиента Qdrant.

        Args:
            host: Хост Qdrant
            port: Порт Qdrant
            collection_name: Название коллекции
            embedding_model: Модель для создания эмбеддингов
            embedding_size: Размерность эмбеддингов
        """
        self.client = QdrantClient(host=host, port=port)
        self.collection_name = collection_name
        self.embedding_model = embedding_model
        self.embedding_size = embedding_size

        # Создаём коллекцию, если её нет
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        """Создаёт коллекцию в Qdrant, если она не существует."""
        try:
            collections = self.client.get_collections().collections
            collection_names = [c.name for c in collections]
            if self.collection_name not in collection_names:
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(
                        size=self.embedding_size,
                        distance=models.Distance.COSINE,
                    ),
                )
                logging.info(f"Коллекция {self.collection_name} создана.")
        except Exception as e:
            logging.error(f"Ошибка при создании коллекции: {e}")
            raise

    def _embed_text(self, text: str) -> List[float]:
        """
        Создаёт эмбеддинг для текста с помощью универсального LLM клиента.

        Args:
            text: Текст для эмбеддинга

        Returns:
            Список чисел с плавающей точкой (эмбеддинг)
        """
        try:
            # Используем универсальный LLM клиент для генерации эмбеддингов
            embedding = llm_client.generate_embedding(
                text=text,
                model=self.embedding_model
            )
            
            if embedding and len(embedding) > 0:
                return embedding
            else:
                # Fallback: возвращаем нулевой вектор
                logging.warning(f"Не удалось получить эмбеддинг для текста, возвращаю нулевой вектор")
                return [0.0] * self.embedding_size
        except Exception as e:
            logging.error(f"Ошибка при создании эмбеддинга: {e}")
            # Возвращаем нулевой вектор в случае ошибки
            return [0.0] * self.embedding_size

    def store(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        agent: Optional[str] = None,
        timestamp: Optional[float] = None,
    ) -> str:
        """
        Сохраняет текст в память.

        Args:
            text: Текст для сохранения
            metadata: Дополнительные метаданные
            agent: Имя агента, сохранившего текст
            timestamp: Временная метка

        Returns:
            ID сохранённой записи
        """
        if metadata is None:
            metadata = {}
        if agent:
            metadata["agent"] = agent
        if timestamp:
            metadata["timestamp"] = timestamp

        embedding = self._embed_text(text)
        point_id = str(uuid4())

        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                models.PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={
                        "text": text,
                        **metadata,
                    },
                )
            ],
        )
        logging.debug(f"Текст сохранён в память с ID {point_id}")
        return point_id

    def search(
        self,
        query: str,
        limit: int = 5,
        agent: Optional[str] = None,
        threshold: float = 0.7,
    ) -> List[Dict[str, Any]]:
        """
        Ищет похожие тексты в памяти.

        Args:
            query: Поисковый запрос
            limit: Максимальное количество результатов
            agent: Фильтр по агенту
            threshold: Порог схожести

        Returns:
            Список найденных записей с текстом и метаданными
        """
        query_embedding = self._embed_text(query)

        # Фильтр по агенту, если указан
        filter_condition = None
        if agent:
            filter_condition = models.Filter(
                must=[
                    models.FieldCondition(
                        key="agent",
                        match=models.MatchValue(value=agent),
                    )
                ]
            )

        try:
            results = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_embedding,
                query_filter=filter_condition,
                limit=limit,
                score_threshold=threshold,
            )
        except UnexpectedResponse:
            # Коллекция может быть пустой
            return []

        formatted_results = []
        for result in results:
            formatted_results.append(
                {
                    "text": result.payload.get("text", ""),
                    "metadata": {
                        k: v for k, v in result.payload.items() if k != "text"
                    },
                    "score": result.score,
                }
            )
        return formatted_results

    def clear(self) -> None:
        """Очищает всю коллекцию."""
        self.client.delete_collection(collection_name=self.collection_name)
        self._ensure_collection()
        logging.info(f"Коллекция {self.collection_name} очищена.")


# Глобальный экземпляр памяти для использования во всём проекте
memory = ZoraMemory()