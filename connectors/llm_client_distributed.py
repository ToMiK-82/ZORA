"""
Упрощённый клиент для работы с мультимодельной архитектурой ZORA.
Поддерживает:
1. Удалённый Ollama сервер - основной провайдер
2. DeepSeek API - резервный провайдер
"""

import logging
import asyncio
import aiohttp
from typing import List, Optional, Dict, Any
from enum import Enum

from config.distributed_models import (
    OLLAMA_HOST,
    OLLAMA_TIMEOUT,
    DEEPSEEK_API_KEY,
    DEEPSEEK_API_BASE,
    DEEPSEEK_CHAT_MODEL,
    DEEPSEEK_REASONER_MODEL,
    DEEPSEEK_TIMEOUT
)

from core.model_selector import get_selector

logger = logging.getLogger("ZORA.LLM.Distributed")

class LLMProvider(Enum):
    """Провайдеры LLM моделей"""
    OLLAMA = "ollama"      # Удалённый Ollama сервер
    DEEPSEEK = "deepseek"  # DeepSeek API
    AUTO = "auto"          # Автоматический выбор

class LLMClientDistributed:
    """Упрощённый клиент для работы с мультимодельной архитектурой"""
    
    def __init__(self, preferred_provider: LLMProvider = LLMProvider.AUTO):
        self.preferred_provider = preferred_provider
        self._session = None
        self.selector = get_selector()
        
        logger.info(f"Инициализация LLMClientDistributed с OLLAMA_HOST={OLLAMA_HOST}")
        
    async def _get_session(self):
        """Ленивое создание aiohttp сессии"""
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def _call_ollama(self, prompt: str, model: str, temperature: float = 0.7,
                          system_prompt: Optional[str] = None) -> str:
        """Вызывает Ollama API"""
        try:
            session = await self._get_session()
            
            # Проверяем на None
            if prompt is None:
                prompt = ""
            if system_prompt is None:
                system_prompt = ""
            
            # Формируем полный промпт
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
                            system_prompt: Optional[str] = None) -> str:
        """Вызывает DeepSeek API"""
        if not DEEPSEEK_API_KEY:
            raise ValueError("DEEPSEEK_API_KEY не установен")
        
        try:
            session = await self._get_session()
            
            # Проверяем на None
            if prompt is None:
                prompt = ""
            if system_prompt is None:
                system_prompt = ""
            
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": 4096
            }
            
            headers = {
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            }
            
            logger.info(f"Вызов DeepSeek API: модель={model}, промпт='{prompt[:50]}...'")
            
            async with session.post(
                f"{DEEPSEEK_API_BASE}/chat/completions",
                json=payload,
                headers=headers,
                timeout=DEEPSEEK_TIMEOUT
            ) as response:
                response.raise_for_status()
                result = await response.json()
                response_text = result["choices"][0]["message"]["content"].strip()
                logger.info(f"✅ Успешный ответ от DeepSeek API (модель: {model})")
                return response_text
                
        except Exception as e:
            logger.error(f"❌ Ошибка вызова DeepSeek API: {e}")
            raise
    
    async def generate(self, prompt: str, model_info: Dict[str, Optional[str]], 
                      temperature: float = 0.7, system_prompt: Optional[str] = None) -> str:
        """
        Генерация ответа с использованием выбранной модели и провайдера
        
        Args:
            prompt: Пользовательский запрос
            model_info: Словарь с информацией о модели {'provider': str, 'model': str}
            temperature: Креативность (0.0-1.0)
            system_prompt: Системный промпт
            
        Returns:
            Текст ответа
        """
        if not prompt:
            return "Пустой запрос"
        
        provider = model_info.get("provider")
        model = model_info.get("model")
        
        if not provider or not model:
            return "Ошибка: не указан провайдер или модель"
        
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
                    system_prompt=system_prompt
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
        Генерация ответа с автоматическим выбором модели по типу задачи
        
        Args:
            prompt: Пользовательский запрос
            task_type: Тип задачи ('planner', 'coder', 'vision')
            temperature: Креативность (0.0-1.0)
            system_prompt: Системный промпт
            
        Returns:
            Текст ответа
        """
        # Выбираем модель по типу задачи
        if task_type == "vision":
            model_info = self.selector.select_vision()
        elif task_type == "coder":
            model_info = self.selector.select_coder()
        else:  # planner
            model_info = self.selector.select_planner(prompt)
        
        # Проверяем доступность модели
        if model_info["provider"] is None:
            if task_type == "vision":
                return "Ошибка: модель для анализа изображений недоступна (удалённый Ollama офлайн)"
            else:
                return "Ошибка: все модели недоступны"
        
        logger.info(f"Выбрана модель: провайдер={model_info['provider']}, модель={model_info['model']}")
        
        # Генерируем ответ
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

# Создаём глобальный экземпляр клиента
_client = None

async def get_client() -> LLMClientDistributed:
    """Возвращает глобальный экземпляр клиента"""
    global _client
    if _client is None:
        _client = LLMClientDistributed()
    return _client

async def generate(prompt: str, task_type: str = "planner", temperature: float = 0.7,
                  system_prompt: str = None) -> str:
    """
    Упрощённый интерфейс для генерации
    
    Args:
        prompt: Пользовательский запрос
        task_type: Тип задачи ('planner', 'coder', 'vision')
        temperature: Креативность
        system_prompt: Системный промпт
        
    Returns:
        Текст ответа
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
                 system_prompt: str = None, **kwargs) -> str:
    """
    Синхронная обёртка для генерации
    
    Args:
        prompt: Пользовательский запрос
        model: Имя модели (если None, выбирается автоматически)
        provider: Провайдер ('ollama', 'deepseek')
        temperature: Креативность (0.0-1.0)
        max_tokens: Максимальное количество токенов (опционально)
        system_prompt: Системный промпт
        **kwargs: Дополнительные параметры
        
    Returns:
        Текст ответа
    """
    if not prompt:
        return "Пустой запрос"
    
    import concurrent.futures
    import asyncio
    import logging
    
    logger = logging.getLogger("ZORA.LLM.Distributed")
    
    def _run_in_new_loop():
        # Создаём новый цикл событий в этом потоке
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        try:
            # Создаём новый клиент внутри нового event loop
            async def _generate_with_new_client():
                client = LLMClientDistributed()
                try:
                    # Если модель не указана, используем автоматический выбор
                    if model is None:
                        # Определяем тип задачи по умолчанию
                        task_type = "planner"
                        return await client.generate_with_task_type(
                            prompt=prompt,
                            task_type=task_type,
                            temperature=temperature,
                            system_prompt=system_prompt
                        )
                    else:
                        # Используем указанную модель и провайдер
                        model_info = {
                            "provider": provider,
                            "model": model
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
            # Аккуратно закрываем loop
            try:
                new_loop.run_until_complete(new_loop.shutdown_asyncgens())
                new_loop.close()
            except:
                pass
            asyncio.set_event_loop(None)
    
    # Запускаем в отдельном потоке, чтобы не мешать основному циклу
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_run_in_new_loop)
        try:
            return future.result(timeout=120)  # тайм-аут 2 минуты
        except concurrent.futures.TimeoutError:
            logger.error("Тайм-аут генерации (120 сек)")
            return "Ошибка: тайм-аут генерации"
        except Exception as e:
            logger.error(f"Ошибка в generate_sync: {e}")
            return f"Ошибка генерации: {str(e)}"
