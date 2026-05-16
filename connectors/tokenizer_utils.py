"""
Утилиты для работы с токенизатором модели mxbai-embed-large-v1.
Обеспечивает корректную обрезку текста по токенам (макс. 512 токенов)
и разбиение на чанки с учётом токенов, а не символов.
"""
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

# Глобальный токенизатор (ленивая загрузка)
_tokenizer = None

# Максимальное количество токенов для mxbai-embed-large-v1
MAX_TOKENS = 512


def _get_tokenizer():
    """Ленивая загрузка токенизатора."""
    global _tokenizer
    if _tokenizer is None:
        try:
            from transformers import AutoTokenizer
            _tokenizer = AutoTokenizer.from_pretrained("mixedbread-ai/mxbai-embed-large-v1")
            logger.info(f"Токенизатор загружен: vocab_size={_tokenizer.vocab_size}")
        except Exception as e:
            logger.warning(f"Не удалось загрузить токенизатор: {e}. Используется fallback по символам.")
            _tokenizer = False  # False означает fallback
    return _tokenizer if _tokenizer is not False else None


def count_tokens(text: str) -> int:
    """Подсчитывает количество токенов в тексте."""
    tokenizer = _get_tokenizer()
    if tokenizer is None:
        # Fallback: грубая оценка (1 токен ≈ 2 символа для русского текста)
        return len(text) // 2
    return len(tokenizer.encode(text))


def truncate_by_tokens(text: str, max_tokens: int = MAX_TOKENS) -> str:
    """
    Обрезает текст так, чтобы он укладывался в max_tokens токенов.
    Если токенизатор недоступен, использует fallback по символам.
    """
    if not text:
        return text

    tokenizer = _get_tokenizer()
    if tokenizer is None:
        # Fallback: 1 токен ≈ 2 символа
        max_chars = max_tokens * 2
        if len(text) > max_chars:
            return text[:max_chars]
        return text

    tokens = tokenizer.encode(text)
    if len(tokens) <= max_tokens:
        return text

    # Обрезаем токены и декодируем обратно
    truncated_tokens = tokens[:max_tokens]
    return tokenizer.decode(truncated_tokens, skip_special_tokens=True)


def chunk_by_tokens(
    text: str,
    max_tokens: int = MAX_TOKENS,
    overlap_tokens: int = 50
) -> List[str]:
    """
    Разбивает текст на чанки, каждый не длиннее max_tokens токенов.
    Чанки разделяются по границам предложений, с перекрытием overlap_tokens токенов.

    Args:
        text: Исходный текст
        max_tokens: Максимальное количество токенов в чанке (по умолчанию 512)
        overlap_tokens: Количество токенов перекрытия между соседними чанками

    Returns:
        Список чанков
    """
    if not text:
        return []

    tokenizer = _get_tokenizer()
    if tokenizer is None:
        # Fallback: чанкинг по символам
        chunk_size = max_tokens * 2  # ~2 символа на токен
        overlap = overlap_tokens * 2
        return _chunk_by_chars_fallback(text, chunk_size, overlap)

    tokens = tokenizer.encode(text)
    if len(tokens) <= max_tokens:
        return [text]

    chunks = []
    start = 0

    while start < len(tokens):
        end = min(start + max_tokens, len(tokens))
        chunk_tokens = tokens[start:end]
        chunk_text = tokenizer.decode(chunk_tokens, skip_special_tokens=True)

        # Пытаемся найти границу предложения в последней части чанка
        if end < len(tokens):
            # Ищем границу предложения в последних overlap_tokens токенах
            search_start = max(start, end - overlap_tokens)
            search_tokens = tokens[search_start:end]
            search_text = tokenizer.decode(search_tokens, skip_special_tokens=True)

            # Ищем конец последнего предложения
            cut_pos = -1
            for sep in [". ", "! ", "? ", ".\n", "!\n", "?\n", "\n\n"]:
                pos = search_text.rfind(sep)
                if pos > cut_pos:
                    cut_pos = pos

            if cut_pos > 0:
                # Нашли границу предложения — обрезаем чанк до неё
                prefix_text = tokenizer.decode(tokens[start:search_start], skip_special_tokens=True)
                chunk_text = prefix_text + search_text[:cut_pos + 1]
                # Пересчитываем start в токенах
                chunk_encoded = tokenizer.encode(chunk_text)
                start += len(chunk_encoded) - overlap_tokens
                if start < 0:
                    start = 0
            else:
                start = end - overlap_tokens
                if start < 0:
                    start = 0
        else:
            start = len(tokens)

        if chunk_text.strip():
            chunks.append(chunk_text.strip())

    return chunks


def _chunk_by_chars_fallback(text: str, chunk_size: int = 3000, overlap: int = 200) -> List[str]:
    """Fallback-функция чанкинга по символам, если токенизатор недоступен."""
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end >= len(text):
            chunks.append(text[start:])
            break
        cut = text.rfind(". ", start + chunk_size - overlap, end)
        if cut == -1:
            cut = text.rfind("\n\n", start + chunk_size - overlap, end)
        if cut == -1:
            cut = end
        else:
            cut += 1
        chunks.append(text[start:cut])
        start = cut
    return chunks
