from sentence_transformers import SentenceTransformer
import logging

logger = logging.getLogger(__name__)

class EmbeddingClient:
    def __init__(self, model_name: str = "BAAI/bge-m3"):
        self.model = SentenceTransformer(model_name)
        logger.info(f"Загружена модель эмбеддингов: {model_name}")

    def generate_embedding(self, text: str) -> list:
        try:
            embedding = self.model.encode(text, normalize_embeddings=True)
            return embedding.tolist()
        except Exception as e:
            logger.error(f"Ошибка генерации эмбеддинга: {e}")
            return [0.0] * 768

embedding_client = EmbeddingClient()