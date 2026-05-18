"""
Модуль оценки faithfulness (верности контексту) для RAG-пайплайна ZORA.
Использует отдельную LLM-модель (судью) через Ollama для оценки,
насколько ответ агента соответствует предоставленному контексту.
"""

import json
import logging
import os
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Модель судьи из переменной окружения, по умолчанию llama3.2:latest
FAITHFULNESS_JUDGE_MODEL = os.getenv("FAITHFULNESS_JUDGE_MODEL", "llama3.2:latest")

# Шаблон промпта для оценки faithfulness
FAITHFULNESS_PROMPT_TEMPLATE = """Ты — эксперт по проверке качества ответов. Твоя задача — оценить, насколько ответ ассистента соответствует контексту, и не содержит ли он выдуманных фактов.

Вопрос: {question}
Контекст (найденные документы): {context}
Ответ ассистента: {answer}

Оцени по шкале от 1 до 5:
1 — ответ полностью противоречит контексту или выдуман
3 — ответ частично опирается на контекст, но содержит неподтверждённые детали
5 — ответ полностью основан на контексте, без галлюцинаций

Выдай только JSON в таком формате (без лишнего текста):
{{"faithfulness_score": <число от 1 до 5>, "reasoning": "<краткое обоснование>"}}"""


def _call_ollama_judge(prompt: str, model: str = FAITHFULNESS_JUDGE_MODEL) -> Optional[str]:
    """
    Отправляет запрос к Ollama для оценки faithfulness.
    Использует прямой вызов ollama.chat или HTTP API.
    """
    # Пробуем через ollama Python-библиотеку
    try:
        import ollama
        response = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1, "num_predict": 512},
            format="json"
        )
        content = response.get("message", {}).get("content", "")
        if content:
            return content.strip()
    except ImportError:
        logger.debug("Библиотека ollama не установлена, пробуем через HTTP API")
    except Exception as e:
        logger.warning(f"Ошибка вызова ollama.chat: {e}. Пробуем HTTP API.")

    # Fallback: прямой HTTP-вызов к Ollama API
    try:
        import httpx
        ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        url = f"{ollama_host.rstrip('/')}/api/chat"
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "options": {"temperature": 0.1, "num_predict": 512},
            "format": "json",
            "stream": False
        }
        resp = httpx.post(url, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        content = data.get("message", {}).get("content", "")
        if content:
            return content.strip()
    except ImportError:
        logger.error("httpx не установлен, невозможно вызвать Ollama API")
    except Exception as e:
        logger.error(f"Ошибка HTTP-вызова Ollama: {e}")

    return None


def _parse_faithfulness_response(response_text: str) -> Dict[str, Any]:
    """
    Парсит JSON-ответ от LLM-судьи.
    Возвращает словарь с faithfulness_score и reasoning.
    При ошибке парсинга возвращает score=0 и reasoning="parsing error".
    """
    if not response_text:
        return {"faithfulness_score": 0, "reasoning": "parsing error: empty response"}

    try:
        # Очистка от Markdown-обёрток
        text = response_text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        result = json.loads(text)
        if not isinstance(result, dict):
            return {"faithfulness_score": 0, "reasoning": "parsing error: not a dict"}

        score = result.get("faithfulness_score", 0)
        reasoning = result.get("reasoning", "")

        # Валидация score
        if not isinstance(score, (int, float)) or score < 1 or score > 5:
            logger.warning(f"Некорректный faithfulness_score: {score}, сбрасываю в 0")
            score = 0

        return {
            "faithfulness_score": int(score),
            "reasoning": str(reasoning) if reasoning else "no reasoning provided"
        }
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.warning(f"Ошибка парсинга ответа судьи: {e}")
        return {"faithfulness_score": 0, "reasoning": f"parsing error: {str(e)}"}


def evaluate_faithfulness(question: str, context: str, answer: str) -> Dict[str, Any]:
    """
    Оценивает faithfulness ответа относительно контекста и вопроса.

    Args:
        question: Исходный вопрос пользователя.
        context: Текст контекста (найденные документы/чанки).
        answer: Ответ, сгенерированный агентом.

    Returns:
        Словарь вида:
        {
            "faithfulness_score": int (1-5, или 0 при ошибке),
            "reasoning": str (обоснование оценки)
        }
    """
    if not answer or not answer.strip():
        logger.warning("Получен пустой ответ для оценки faithfulness")
        return {"faithfulness_score": 0, "reasoning": "empty answer"}

    if not context or not context.strip():
        logger.warning("Получен пустой контекст для оценки faithfulness")
        return {"faithfulness_score": 0, "reasoning": "empty context"}

    # Обрезаем контекст, если он слишком длинный (модель судьи может иметь лимит)
    max_context_chars = 8000
    if len(context) > max_context_chars:
        context = context[:max_context_chars] + "\n... [контекст обрезан]"

    prompt = FAITHFULNESS_PROMPT_TEMPLATE.format(
        question=question.strip(),
        context=context.strip(),
        answer=answer.strip()
    )

    logger.info(f"Оценка faithfulness: вопрос='{question[:80]}...', "
                f"контекст={len(context)} симв., ответ={len(answer)} симв.")

    response_text = _call_ollama_judge(prompt)
    result = _parse_faithfulness_response(response_text)

    logger.info(f"Результат faithfulness: score={result['faithfulness_score']}, "
                f"reasoning='{result['reasoning'][:100]}...'")

    return result
