"""
Универсальный клиент для работы с LLM моделями.
Поддерживает:
1. Удалённый Ollama сервер - основной локальный провайдер
2. DeepSeek V4 API (OpenAI SDK) - основной облачный провайдер
3. DeepSeek Legacy API (deepseek-chat/deepseek-reasoner) - обратная совместимость

Содержит как асинхронный (LLMClientDistributed), так и синхронный (LLMClient) клиенты.
"""

import logging
import asyncio
import aiohttp
import requests
from typing import List, Optional, Dict, Any
from enum import Enum

from core.model_selector import (
    OLLAMA_HOST,
    OLLAMA_TIMEOUT,
    DEEPSEEK_API_KEY,
    DEEPSEEK_API_BASE,
    DEEPSEEK_CHAT_MODEL,
    DEEPSEEK_REASONER_MODEL,
    DEEPSEEK_V4_FLASH,
    DEEPSEEK_V4_PRO,
    DEEPSEEK_LEGACY_MODE,
    DEEPSEEK_DEFAULT_REASONING,
    DEEPSEEK_TIMEOUT,
    EMBED_MODEL,
)
from core.model_selector import get_selector

logger = logging.getLogger("ZORA.LLM.Distributed")


class LLMProvider(Enum):
    """Провайдеры LLM моделей"""
    OLLAMA = "ollama"      # Удалённый Ollama сервер
    DEEPSEEK = "deepseek"  # DeepSeek API (V4 или Legacy)
    AUTO = "auto"          # Автоматический выбор


# ============================================================
# СИНХРОННЫЙ КЛИЕНТ (LLMClient) — для простых/фоновых задач
# ============================================================

class LLMClient:
    """Универсальный синхронный клиент для работы с LLM моделями"""

    def __init__(self, preferred_provider: LLMProvider = LLMProvider.AUTO):
        self.preferred_provider = preferred_provider
        self._ollama_available = None
        self._deepseek_available = None
        self._ollama_client = None
        self._deepseek_client = None
        self._deepseek_v4_client = None

    def _import_ollama(self):
        """Ленивый импорт Ollama клиента"""
        if self._ollama_client is None:
            try:
                from connectors.ollama_client import generate as ollama_generate
                from connectors.ollama_client import generate_embedding as ollama_embedding
                self._ollama_client = {
                    "generate": ollama_generate,
                    "generate_embedding": ollama_embedding
                }
            except ImportError as e:
                logger.warning(f"⚠️ Ollama клиент не найден: {e}")
                self._ollama_client = None
        return self._ollama_client

    def _import_deepseek_v4(self):
        """Ленивый импорт DeepSeek V4 клиента (OpenAI SDK)"""
        if self._deepseek_v4_client is None:
            try:
                from connectors.deepseek_v4_client import get_v4_client
                self._deepseek_v4_client = get_v4_client()
            except ImportError as e:
                logger.warning(f"⚠️ DeepSeek V4 клиент не найден: {e}")
                self._deepseek_v4_client = None
        return self._deepseek_v4_client

    def _import_deepseek_legacy(self):
        """Ленивый импорт DeepSeek Legacy клиента (для обратной совместимости)"""
        if self._deepseek_client is None:
            try:
                # Пробуем V4 клиент как замену Legacy
                from connectors.deepseek_v4_client import get_v4_client
                v4 = get_v4_client()
                if v4 and v4.is_available():
                    self._deepseek_client = {
                        "generate": v4.generate,
                        "generate_embedding": lambda text, model=None: [],
                        "check_available": v4.is_available
                    }
                else:
                    self._deepseek_client = None
            except ImportError as e:
                logger.warning(f"⚠️ DeepSeek V4 клиент не найден: {e}")
                self._deepseek_client = None
        return self._deepseek_client

    def check_ollama_available(self) -> bool:
        """Проверка доступности Ollama"""
        if self._ollama_available is None:
            try:
                response = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
                self._ollama_available = response.status_code == 200
                logger.info(f"✅ Ollama доступен: {self._ollama_available}")
            except Exception as e:
                logger.warning(f"⚠️ Ollama недоступен: {e}")
                self._ollama_available = False
        return self._ollama_available

    def check_deepseek_available(self) -> bool:
        """Проверка доступности DeepSeek API (V4 или Legacy)"""
        # Сначала пробуем V4
        v4 = self._import_deepseek_v4()
        if v4 and v4.is_available():
            self._deepseek_available = True
            logger.info("✅ DeepSeek V4 доступен")
            return True

        # Fallback на Legacy
        legacy = self._import_deepseek_legacy()
        if legacy and "check_available" in legacy:
            self._deepseek_available = legacy["check_available"]()
            logger.info(f"✅ DeepSeek Legacy доступен: {self._deepseek_available}")
        else:
            self._deepseek_available = False

        return self._deepseek_available

    def get_available_providers(self) -> List[LLMProvider]:
        """Получить список доступных провайдеров"""
        available = []
        if self.check_ollama_available():
            available.append(LLMProvider.OLLAMA)
        if self.check_deepseek_available():
            available.append(LLMProvider.DEEPSEEK)
        logger.info(f"Доступные провайдеры: {[p.value for p in available]}")
        return available

    def select_provider(self, preferred: Optional[LLMProvider] = None) -> Optional[LLMProvider]:
        """
        Выбор провайдера на основе предпочтений и доступности
        """
        preferred = preferred or self.preferred_provider
        available = self.get_available_providers()

        if not available:
            logger.error("❌ Нет доступных LLM провайдеров")
            return None

        if preferred == LLMProvider.AUTO:
            if LLMProvider.OLLAMA in available:
                return LLMProvider.OLLAMA
            elif LLMProvider.DEEPSEEK in available:
                return LLMProvider.DEEPSEEK
        elif preferred in available:
            return preferred

        logger.warning(f"⚠️ Предпочтительный провайдер {preferred.value} недоступен, использую {available[0].value}")
        return available[0]

    def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        system: Optional[str] = None,
        format: str = None,
        provider: Optional[LLMProvider] = None,
        tools: Optional[List[Dict]] = None,
        thinking: Optional[Dict] = None,
        reasoning_effort: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        Генерация ответа с автоматическим выбором провайдера (синхронно)
        """
        selected_provider = self.select_provider(provider)

        if not selected_provider:
            return "Ошибка: нет доступных LLM провайдеров. Проверьте настройки Ollama или DeepSeek API."

        logger.info(f"Использую провайдер: {selected_provider.value}")

        try:
            if selected_provider == LLMProvider.OLLAMA:
                ollama = self._import_ollama()
                if ollama and "generate" in ollama:
                    model = model or "llama3.2:latest"
                    return ollama["generate"](
                        prompt=prompt,
                        model=model,
                        temperature=temperature,
                        system=system,
                        format=format,
                        **kwargs
                    )

            elif selected_provider == LLMProvider.DEEPSEEK:
                # Пробуем V4 клиент в первую очередь
                v4 = self._import_deepseek_v4()
                if v4 and v4.is_available():
                    # Определяем модель
                    if model is None:
                        model = DEEPSEEK_V4_FLASH if not DEEPSEEK_LEGACY_MODE else DEEPSEEK_CHAT_MODEL

                    # Если есть tools — используем chat_completion_sync
                    if tools:
                        messages = []
                        if system:
                            messages.append({"role": "system", "content": system})
                        messages.append({"role": "user", "content": prompt})

                        return v4.chat_completion_sync(
                            messages=messages,
                            model=model,
                            tools=tools,
                            thinking=thinking,
                            reasoning_effort=reasoning_effort,
                            temperature=temperature,
                            **kwargs
                        )
                    else:
                        return v4.generate(
                            prompt=prompt,
                            system=system,
                            model=model,
                            temperature=temperature,
                            thinking=thinking,
                            reasoning_effort=reasoning_effort,
                            **kwargs
                        )

                # Fallback на Legacy
                logger.warning("⚠️ DeepSeek V4 недоступен, пробую Legacy")
                legacy = self._import_deepseek_legacy()
                if legacy and "generate" in legacy:
                    model = model or DEEPSEEK_CHAT_MODEL
                    return legacy["generate"](
                        prompt=prompt,
                        model=model,
                        temperature=temperature,
                        system=system,
                        format=format,
                        **kwargs
                    )

            raise ValueError(f"Провайдер {selected_provider.value} не поддерживается")

        except Exception as e:
            logger.error(f"❌ Ошибка генерации через {selected_provider.value}: {e}")
            available = self.get_available_providers()
            other_providers = [p for p in available if p != selected_provider]

            if other_providers:
                logger.info(f"Пробую другой провайдер: {other_providers[0].value}")
                return self.generate(
                    prompt=prompt,
                    model=model,
                    temperature=temperature,
                    system=system,
                    format=format,
                    provider=other_providers[0],
                    tools=tools,
                    thinking=thinking,
                    reasoning_effort=reasoning_effort,
                    **kwargs
                )

            return f"Ошибка генерации через все доступные провайдеры: {str(e)}"

    def generate_embedding(
        self,
        text: str,
        model: Optional[str] = None,
        provider: Optional[LLMProvider] = None
    ) -> List[float]:
        """
        Генерация эмбеддинга с автоматическим выбором провайдера (синхронно)
        """
        selected_provider = self.select_provider(provider)

        if not selected_provider:
            logger.error("❌ Нет доступных провайдеров для эмбеддинга")
            return []

        try:
            if selected_provider == LLMProvider.OLLAMA:
                ollama = self._import_ollama()
                if ollama and "generate_embedding" in ollama:
                    model = model or EMBED_MODEL
                    return ollama["generate_embedding"](text, model)

            elif selected_provider == LLMProvider.DEEPSEEK:
                legacy = self._import_deepseek_legacy()
                if legacy and "generate_embedding" in legacy:
                    model = model or "text-embedding"
                    return legacy["generate_embedding"](text, model)

            raise ValueError(f"Провайдер {selected_provider.value} не поддерживает эмбеддинги")

        except Exception as e:
            logger.error(f"❌ Ошибка генерации эмбеддинга через {selected_provider.value}: {e}")
            return []

    def get_status(self) -> Dict[str, Any]:
        """Получить статус всех провайдеров"""
        return {
            "preferred_provider": self.preferred_provider.value,
            "ollama_available": self.check_ollama_available(),
            "deepseek_available": self.check_deepseek_available(),
            "available_providers": [p.value for p in self.get_available_providers()]
        }


# Глобальный экземпляр синхронного клиента
llm_client = LLMClient(preferred_provider=LLMProvider.AUTO)


# Функции для обратной совместимости (синхронные)
def generate(
    prompt: str,
    model: Optional[str] = None,
    temperature: float = 0.7,
    system: Optional[str] = None,
    format: str = None,
    tools: Optional[List[Dict]] = None,
    thinking: Optional[Dict] = None,
    reasoning_effort: Optional[str] = None,
    **kwargs
) -> str:
    """Синхронная генерация (для обратной совместимости)"""
    if prompt is None:
        prompt = ""
    return llm_client.generate(
        prompt=prompt,
        model=model,
        temperature=temperature,
        system=system,
        format=format,
        tools=tools,
        thinking=thinking,
        reasoning_effort=reasoning_effort,
        **kwargs
    )


def generate_embedding(text: str, model: Optional[str] = None) -> List[float]:
    """Синхронная генерация эмбеддинга (для обратной совместимости)"""
    return llm_client.generate_embedding(text=text, model=model)


# ============================================================
# АСИНХРОННЫЙ КЛИЕНТ (LLMClientDistributed) — для оркестратора
# ============================================================

class LLMClientDistributed:
    """Асинхронный клиент для работы с мультимодельной архитектурой"""

    def __init__(self, preferred_provider: LLMProvider = LLMProvider.AUTO):
        self.preferred_provider = preferred_provider
        self._session = None
        self.selector = get_selector()
        self._deepseek_v4_client = None

        logger.info(f"Инициализация LLMClientDistributed с OLLAMA_HOST={OLLAMA_HOST}")

    def _get_deepseek_v4(self):
        """Ленивый импорт DeepSeek V4 клиента"""
        if self._deepseek_v4_client is None:
            try:
                from connectors.deepseek_v4_client import get_v4_client
                self._deepseek_v4_client = get_v4_client()
            except ImportError:
                self._deepseek_v4_client = None
        return self._deepseek_v4_client

    async def _get_session(self):
        """Ленивое создание aiohttp сессии"""
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _call_ollama(self, prompt: str, model: str, temperature: float = 0.7,
                          system_prompt: Optional[str] = None) -> str:
        """Вызывает Ollama API (асинхронно)"""
        try:
            session = await self._get_session()

            if prompt is None:
                prompt = ""
            if system_prompt is None:
                system_prompt = ""

            full_prompt = prompt
            if system_prompt:
                full_prompt = f"System: {system_prompt}\n\nUser: {prompt}\n\nAssistant:"

            payload = {
                "model": model,
                "prompt": full_prompt,
                "options": {
                    "temperature": temperature,
                    "num_predict": 1000
                },
                "stream": False
            }

            logger.info(f"Вызов Ollama API: модель={model}, промпт='{prompt[:50]}...'")

            async with session.post(
                f"{OLLAMA_HOST}/api/generate",
                json=payload,
                timeout=OLLAMA_TIMEOUT
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    response_text = result.get("response", "").strip()
                    if response_text:
                        logger.info(f"✅ Успешный ответ от Ollama (модель: {model})")
                        return response_text
                    else:
                        logger.warning(f"Пустой ответ от Ollama (модель: {model})")
                        raise Exception("Пустой ответ от Ollama")

                elif response.status == 404:
                    error_msg = f"Модель {model} не найдена в Ollama"
                    logger.error(f"❌ {error_msg}")
                    raise Exception(error_msg)

                else:
                    error_text = await response.text()
                    error_msg = f"Ошибка Ollama: статус {response.status}, текст: {error_text[:200]}"
                    logger.error(f"❌ {error_msg}")
                    raise Exception(error_msg)

        except aiohttp.ClientError as e:
            error_msg = f"Сетевая ошибка при вызове Ollama: {str(e)}"
            logger.error(f"❌ {error_msg}")
            raise Exception(error_msg)

        except asyncio.TimeoutError:
            error_msg = f"Таймаут при вызове Ollama ({OLLAMA_TIMEOUT} сек)"
            logger.error(f"❌ {error_msg}")
            raise Exception(error_msg)

        except Exception as e:
            error_msg = f"Ошибка при вызове Ollama: {str(e)}"
            logger.error(f"❌ {error_msg}")
            raise

    async def _call_deepseek(self, prompt: str, model: str, temperature: float = 0.7,
                            system_prompt: Optional[str] = None,
                            tools: Optional[List[Dict]] = None,
                            thinking: Optional[Dict] = None,
                            reasoning_effort: Optional[str] = None) -> str:
        """Вызывает DeepSeek API (асинхронно) через V4 клиент или Legacy"""
        if not DEEPSEEK_API_KEY:
            raise ValueError("DEEPSEEK_API_KEY не установлен")

        # Пробуем V4 клиент
        v4 = self._get_deepseek_v4()
        if v4 and v4.is_available():
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            result = v4.chat_completion(
                messages=messages,
                model=model,
                tools=tools,
                thinking=thinking,
                reasoning_effort=reasoning_effort,
                temperature=temperature,
                max_tokens=4096
            )

            if result.get("success"):
                # Если есть tool_calls, возвращаем JSON
                if result.get("tool_calls"):
                    import json
                    return json.dumps({
                        "tool_calls": result["tool_calls"],
                        "content": result.get("content", "")
                    }, ensure_ascii=False)
                return result.get("content", "")

            # Если V4 не сработал, пробуем Legacy
            logger.warning(f"⚠️ DeepSeek V4 ошибка: {result.get('error')}, пробую Legacy")

        # Fallback на Legacy (ручной HTTP)
        try:
            session = await self._get_session()

            if prompt is None:
                prompt = ""
            if system_prompt is None:
                system_prompt = ""

            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            payload = {
                "model": model or DEEPSEEK_CHAT_MODEL,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": 4096
            }

            headers = {
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            }

            logger.info(f"Вызов DeepSeek Legacy API: модель={model}, промпт='{prompt[:50]}...'")

            async with session.post(
                f"{DEEPSEEK_API_BASE}/chat/completions",
                json=payload,
                headers=headers,
                timeout=DEEPSEEK_TIMEOUT
            ) as response:
                response.raise_for_status()
                result = await response.json()
                response_text = result["choices"][0]["message"]["content"].strip()
                logger.info(f"✅ Успешный ответ от DeepSeek Legacy API (модель: {model})")
                return response_text

        except Exception as e:
            logger.error(f"❌ Ошибка вызова DeepSeek API: {e}")
            raise

    async def generate(self, prompt: str, model_info: Dict[str, Optional[str]], 
                      temperature: float = 0.7, system_prompt: Optional[str] = None) -> str:
        """
        Асинхронная генерация ответа с использованием выбранной модели и провайдера
        """
        if not prompt:
            return "Пустой запрос"

        provider = model_info.get("provider")
        model = model_info.get("model")

        if not provider or not model:
            return "Ошибка: не указан провайдер или модель"

        # Извлекаем дополнительные параметры для DeepSeek V4
        tools = model_info.get("tools")
        thinking = model_info.get("thinking")
        reasoning_effort = model_info.get("reasoning_effort")

        try:
            if provider == "ollama":
                return await self._call_ollama(
                    prompt=prompt,
                    model=model,
                    temperature=temperature,
                    system_prompt=system_prompt
                )
            elif provider == "deepseek":
                return await self._call_deepseek(
                    prompt=prompt,
                    model=model,
                    temperature=temperature,
                    system_prompt=system_prompt,
                    tools=tools,
                    thinking=thinking,
                    reasoning_effort=reasoning_effort
                )
            else:
                return f"Ошибка: неизвестный провайдер '{provider}'"

        except Exception as e:
            error_msg = f"Ошибка генерации: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return error_msg

    async def generate_with_task_type(self, prompt: str, task_type: str,
                                     temperature: float = 0.7, 
                                     system_prompt: Optional[str] = None) -> str:
        """
        Асинхронная генерация с автоматическим выбором модели по типу задачи
        """
        if task_type == "vision":
            model_info = self.selector.select_vision()
        elif task_type == "coder":
            model_info = self.selector.select_coder()
        else:  # planner
            model_info = self.selector.select_planner(prompt)

        if model_info["provider"] is None:
            if task_type == "vision":
                return "Ошибка: модель для анализа изображений недоступна (удалённый Ollama офлайн)"
            else:
                return "Ошибка: все модели недоступны"

        logger.info(f"Выбрана модель: провайдер={model_info['provider']}, модель={model_info['model']}")

        return await self.generate(
            prompt=prompt,
            model_info=model_info,
            temperature=temperature,
            system_prompt=system_prompt
        )

    async def close(self):
        """Закрывает сессию"""
        if self._session:
            await self._session.close()
            self._session = None

    def __del__(self):
        """Деструктор для закрытия сессии"""
        if self._session:
            asyncio.create_task(self.close())


# Глобальный экземпляр асинхронного клиента
_client = None


async def get_client() -> LLMClientDistributed:
    """Возвращает глобальный экземпляр асинхронного клиента"""
    global _client
    if _client is None:
        _client = LLMClientDistributed()
    return _client


async def generate_async(prompt: str, task_type: str = "planner", temperature: float = 0.7,
                        system_prompt: str = None) -> str:
    """
    Упрощённый асинхронный интерфейс для генерации
    """
    client = await get_client()
    return await client.generate_with_task_type(
        prompt=prompt,
        task_type=task_type,
        temperature=temperature,
        system_prompt=system_prompt
    )


def generate_sync(prompt: str, model: str = None, provider: str = "ollama", 
                 temperature: float = 0.7, max_tokens: int = None, 
                 system_prompt: str = None, tools: Optional[List[Dict]] = None,
                 thinking: Optional[Dict] = None, reasoning_effort: Optional[str] = None,
                 **kwargs) -> str:
    """
    Синхронная обёртка для асинхронной генерации (через отдельный event loop)
    Поддерживает Function Calling (tools), thinking, reasoning_effort.
    """
    if not prompt:
        return "Пустой запрос"

    import concurrent.futures

    def _run_in_new_loop():
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        try:
            async def _generate_with_new_client():
                client = LLMClientDistributed()
                try:
                    if model is None:
                        task_type = "planner"
                        return await client.generate_with_task_type(
                            prompt=prompt,
                            task_type=task_type,
                            temperature=temperature,
                            system_prompt=system_prompt
                        )
                    else:
                        model_info = {
                            "provider": provider,
                            "model": model,
                            "tools": tools,
                            "thinking": thinking,
                            "reasoning_effort": reasoning_effort
                        }
                        return await client.generate(
                            prompt=prompt,
                            model_info=model_info,
                            temperature=temperature,
                            system_prompt=system_prompt
                        )
                finally:
                    await client.close()

            return new_loop.run_until_complete(_generate_with_new_client())
        finally:
            try:
                new_loop.run_until_complete(new_loop.shutdown_asyncgens())
                new_loop.close()
            except:
                pass
            asyncio.set_event_loop(None)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_run_in_new_loop)
        try:
            return future.result(timeout=300)
        except concurrent.futures.TimeoutError:
            logger.error("Тайм-аут генерации (300 сек)")
            return "Ошибка: тайм-аут генерации"
        except Exception as e:
            logger.error(f"Ошибка в generate_sync: {e}")
            return f"Ошибка генерации: {str(e)}"
