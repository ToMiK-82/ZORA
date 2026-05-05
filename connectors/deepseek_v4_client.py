"""
Клиент для DeepSeek V4 API на основе OpenAI SDK.
Поддерживает:
- DeepSeek V4 Flash и Pro модели
- Нативный Function Calling (tool_calls)
- Режим мышления (thinking) с reasoning_effort
- Потоковый режим (stream)
- Fallback на старые модели (deepseek-chat/deepseek-reasoner) при DEEPSEEK_LEGACY_MODE=true
"""

import json
import logging
import os
from typing import List, Optional, Dict, Any, Callable
from openai import OpenAI, APIError, APITimeoutError, APIConnectionError

logger = logging.getLogger("ZORA.DeepSeekV4")

# Конфигурация по умолчанию
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_BASE = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com")

# V4 модели
DEEPSEEK_V4_FLASH = os.getenv("DEEPSEEK_MODEL_FLASH", "deepseek-v4-flash")
DEEPSEEK_V4_PRO = os.getenv("DEEPSEEK_MODEL_PRO", "deepseek-v4-pro")

# Legacy модели (до 2026-07-24)
DEEPSEEK_LEGACY_CHAT = "deepseek-chat"
DEEPSEEK_LEGACY_REASONER = "deepseek-reasoner"

# Режим обратной совместимости
DEEPSEEK_LEGACY_MODE = os.getenv("DEEPSEEK_LEGACY_MODE", "false").lower() == "true"

# Режим мышления по умолчанию: "none", "flash", "pro"
DEEPSEEK_DEFAULT_REASONING = os.getenv("DEEPSEEK_DEFAULT_REASONING", "flash")


class DeepSeekV4Client:
    """
    Клиент для DeepSeek V4 API на OpenAI SDK.
    Поддерживает Function Calling, thinking, reasoning_effort.
    """

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key or DEEPSEEK_API_KEY
        self.base_url = base_url or DEEPSEEK_API_BASE
        self.legacy_mode = DEEPSEEK_LEGACY_MODE
        self.default_reasoning = DEEPSEEK_DEFAULT_REASONING

        if not self.api_key:
            logger.warning("⚠️ DEEPSEEK_API_KEY не установлен. DeepSeek V4 клиент будет недоступен.")
            self.client = None
        else:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url
            )
            logger.info(f"✅ DeepSeek V4 клиент инициализирован (base_url={self.base_url}, legacy_mode={self.legacy_mode})")

    def is_available(self) -> bool:
        """Проверяет доступность DeepSeek API."""
        if not self.client:
            return False
        try:
            # Простой тестовый запрос
            self.client.chat.completions.create(
                model=DEEPSEEK_LEGACY_CHAT if self.legacy_mode else DEEPSEEK_V4_FLASH,
                messages=[{"role": "user", "content": "test"}],
                max_tokens=5
            )
            return True
        except Exception as e:
            logger.warning(f"⚠️ DeepSeek API недоступен: {e}")
            return False

    def _resolve_model(self, model: Optional[str] = None, thinking: Optional[Dict] = None) -> str:
        """
        Определяет, какую модель использовать.
        Если legacy_mode=True — использует deepseek-chat/deepseek-reasoner.
        Иначе — V4 Flash/Pro.
        """
        if self.legacy_mode:
            # Legacy режим: если запрос требует reasoning, используем deepseek-reasoner
            if thinking and thinking.get("type") == "enabled":
                return DEEPSEEK_LEGACY_REASONER
            return model or DEEPSEEK_LEGACY_CHAT
        else:
            # V4 режим
            if model:
                return model
            # Если не указана модель, выбираем по умолчанию
            if thinking and thinking.get("type") == "enabled":
                return DEEPSEEK_V4_FLASH  # Flash тоже поддерживает thinking
            return DEEPSEEK_V4_FLASH

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        tools: Optional[List[Dict]] = None,
        thinking: Optional[Dict] = None,
        reasoning_effort: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Основной метод для chat completion с поддержкой Function Calling.

        Args:
            messages: Список сообщений [{"role": "...", "content": "..."}]
            model: Название модели (если None, выбирается автоматически)
            tools: Список инструментов в формате JSON Schema для Function Calling
            thinking: {"type": "enabled"} для включения режима мышления
            reasoning_effort: "low", "medium", "high" (для V4 Pro)
            temperature: Температура (0.0-1.0)
            max_tokens: Максимум токенов в ответе
            stream: Потоковый режим
            **kwargs: Дополнительные параметры

        Returns:
            Словарь с ответом:
            {
                "success": True/False,
                "content": str (текстовый ответ),
                "tool_calls": [{"name": str, "arguments": dict}, ...] или None,
                "finish_reason": str,
                "model": str,
                "usage": dict
            }
        """
        if not self.client:
            return {"success": False, "error": "DeepSeek V4 клиент не инициализирован (нет API ключа)"}

        # Определяем модель
        resolved_model = self._resolve_model(model, thinking)

        # Формируем параметры запроса
        api_params = {
            "model": resolved_model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
        }

        if max_tokens:
            api_params["max_tokens"] = max_tokens

        # Добавляем tools (Function Calling)
        if tools:
            api_params["tools"] = tools

        # Добавляем thinking и reasoning_effort (только для V4 моделей)
        if not self.legacy_mode:
            if thinking:
                # thinking передаётся через extra_body, так как OpenAI SDK не поддерживает его напрямую
                if "extra_body" not in api_params:
                    api_params["extra_body"] = {}
                api_params["extra_body"]["thinking"] = thinking
            if reasoning_effort:
                api_params["reasoning_effort"] = reasoning_effort

        # Добавляем дополнительные параметры
        for key in ["top_p", "frequency_penalty", "presence_penalty", "stop", "user"]:
            if key in kwargs:
                api_params[key] = kwargs[key]

        try:
            logger.info(f"🔍 DeepSeek V4 запрос: model={resolved_model}, tools={len(tools) if tools else 0}, thinking={thinking}")

            response = self.client.chat.completions.create(**api_params)

            if stream:
                # Потоковый режим — возвращаем генератор
                return self._handle_stream_response(response, resolved_model)

            # Обычный режим
            return self._parse_response(response, resolved_model)

        except APITimeoutError:
            logger.error("❌ DeepSeek V4: таймаут запроса")
            return {"success": False, "error": "Таймаут запроса к DeepSeek V4 API"}
        except APIConnectionError as e:
            logger.error(f"❌ DeepSeek V4: ошибка соединения: {e}")
            return {"success": False, "error": f"Ошибка соединения с DeepSeek V4: {e}"}
        except APIError as e:
            logger.error(f"❌ DeepSeek V4: API ошибка {e.status_code}: {e.message}")
            return {"success": False, "error": f"DeepSeek V4 API ошибка {e.status_code}: {e.message}"}
        except Exception as e:
            logger.error(f"❌ DeepSeek V4: неожиданная ошибка: {e}")
            return {"success": False, "error": f"DeepSeek V4 ошибка: {str(e)}"}

    def _parse_response(self, response, model: str) -> Dict[str, Any]:
        """Парсит ответ от API."""
        choice = response.choices[0]
        message = choice.message

        result = {
            "success": True,
            "content": message.content or "",
            "finish_reason": choice.finish_reason,
            "model": model,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                "total_tokens": response.usage.total_tokens if response.usage else 0,
            }
        }

        # Обработка tool_calls (Function Calling)
        if message.tool_calls:
            tool_calls = []
            for tc in message.tool_calls:
                try:
                    arguments = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    arguments = {"raw": tc.function.arguments}
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": arguments
                })
            result["tool_calls"] = tool_calls
            logger.info(f"🔧 Function Calling: {len(tool_calls)} вызов(ов): {[tc['name'] for tc in tool_calls]}")

        # Извлечение reasoning из ответа (если есть)
        if hasattr(message, 'reasoning') and message.reasoning:
            result["reasoning"] = message.reasoning

        return result

    def _handle_stream_response(self, stream_response, model: str):
        """Обрабатывает потоковый ответ."""
        # Для потокового режима возвращаем словарь с генератором
        def generate_chunks():
            full_content = ""
            tool_calls_buffer = {}
            for chunk in stream_response:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta is None:
                    continue

                # Текстовый контент
                if delta.content:
                    full_content += delta.content
                    yield {"type": "content", "content": delta.content}

                # Tool calls (накапливаем)
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tool_calls_buffer:
                            tool_calls_buffer[idx] = {"name": "", "arguments": ""}
                        if tc_delta.function:
                            if tc_delta.function.name:
                                tool_calls_buffer[idx]["name"] += tc_delta.function.name
                            if tc_delta.function.arguments:
                                tool_calls_buffer[idx]["arguments"] += tc_delta.function.arguments

                # Reasoning
                if hasattr(delta, 'reasoning') and delta.reasoning:
                    yield {"type": "reasoning", "content": delta.reasoning}

                # Завершение
                finish_reason = chunk.choices[0].finish_reason if chunk.choices else None
                if finish_reason:
                    yield {
                        "type": "done",
                        "finish_reason": finish_reason,
                        "full_content": full_content,
                        "tool_calls": [
                            {"name": v["name"], "arguments": json.loads(v["arguments"]) if v["arguments"] else {}}
                            for v in tool_calls_buffer.values()
                        ] if tool_calls_buffer else None
                    }

        return {"success": True, "stream": generate_chunks()}

    def chat_completion_sync(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        tools: Optional[List[Dict]] = None,
        thinking: Optional[Dict] = None,
        reasoning_effort: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> str:
        """
        Упрощённый синхронный метод — возвращает только текст ответа.
        Если были tool_calls, возвращает JSON с их описанием.
        """
        result = self.chat_completion(
            messages=messages,
            model=model,
            tools=tools,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
            **kwargs
        )

        if not result.get("success"):
            return f"Ошибка: {result.get('error', 'Неизвестная ошибка')}"

        # Если есть tool_calls, возвращаем JSON для обработки
        if result.get("tool_calls"):
            return json.dumps({
                "tool_calls": result["tool_calls"],
                "content": result.get("content", "")
            }, ensure_ascii=False)

        return result.get("content", "")

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict]] = None,
        thinking: Optional[Dict] = None,
        reasoning_effort: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        Упрощённый метод для генерации из строки (обратная совместимость).

        Args:
            prompt: Пользовательский запрос
            system: Системный промпт
            model: Модель
            temperature: Температура
            max_tokens: Максимум токенов
            tools: Список инструментов для Function Calling
            thinking: Режим мышления
            reasoning_effort: Уровень reasoning
            **kwargs: Дополнительные параметры

        Returns:
            Текст ответа
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        return self.chat_completion_sync(
            messages=messages,
            model=model,
            tools=tools,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )


# Глобальный экземпляр
_deepseek_v4_client: Optional[DeepSeekV4Client] = None


def get_v4_client() -> DeepSeekV4Client:
    """Возвращает глобальный экземпляр DeepSeekV4Client."""
    global _deepseek_v4_client
    if _deepseek_v4_client is None:
        _deepseek_v4_client = DeepSeekV4Client()
    return _deepseek_v4_client


# Функции для обратной совместимости
def generate(
    prompt: str,
    system: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    tools: Optional[List[Dict]] = None,
    thinking: Optional[Dict] = None,
    reasoning_effort: Optional[str] = None,
    **kwargs
) -> str:
    """Синхронная генерация через DeepSeek V4 (обратная совместимость)."""
    client = get_v4_client()
    return client.generate(
        prompt=prompt,
        system=system,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        tools=tools,
        thinking=thinking,
        reasoning_effort=reasoning_effort,
        **kwargs
    )


def check_deepseek_available() -> bool:
    """Проверка доступности DeepSeek API."""
    client = get_v4_client()
    return client.is_available()
