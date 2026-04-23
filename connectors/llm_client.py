"""
Универсальный клиент для работы с LLM моделями.
Поддерживает Ollama (локально) и DeepSeek API (облачно) с автоматическим fallback.
"""
import logging
from typing import List, Optional, Dict, Any
from enum import Enum
import os

# Импортируем настройки моделей
try:
    from config.distributed_models import CHAT_MODEL_WEAK, DEEPSEEK_MODEL, EMBED_MODEL
except ImportError:
    # Значения по умолчанию если конфиг не найден
    CHAT_MODEL_WEAK = "llama3.2:latest"
    DEEPSEEK_MODEL = "deepseek-chat"
    EMBED_MODEL = "nomic-embed-text"

logger = logging.getLogger("ZORA.LLM")

class LLMProvider(Enum):
    """Провайдеры LLM моделей"""
    OLLAMA = "ollama"
    DEEPSEEK = "deepseek"
    AUTO = "auto"  # Автоматический выбор

class LLMClient:
    """Универсальный клиент для работы с LLM моделями"""
    
    def __init__(self, preferred_provider: LLMProvider = LLMProvider.AUTO):
        self.preferred_provider = preferred_provider
        self._ollama_available = None
        self._deepseek_available = None
        
        # Импортируем клиенты лениво, чтобы избежать ошибок импорта
        self._ollama_client = None
        self._deepseek_client = None
        
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
    
    def _import_deepseek(self):
        """Ленивый импорт DeepSeek клиента"""
        if self._deepseek_client is None:
            try:
                from connectors.deepseek_client import generate as deepseek_generate
                from connectors.deepseek_client import generate_embedding as deepseek_embedding
                from connectors.deepseek_client import check_deepseek_available
                self._deepseek_client = {
                    "generate": deepseek_generate,
                    "generate_embedding": deepseek_embedding,
                    "check_available": check_deepseek_available
                }
            except ImportError as e:
                logger.warning(f"⚠️ DeepSeek клиент не найден: {e}")
                self._deepseek_client = None
        return self._deepseek_client
    
    def check_ollama_available(self) -> bool:
        """Проверка доступности Ollama"""
        if self._ollama_available is None:
            try:
                import requests
                # Используем OLLAMA_HOST из конфигурации
                from config.distributed_models import OLLAMA_HOST
                response = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
                self._ollama_available = response.status_code == 200
                logger.info(f"✅ Ollama доступен: {self._ollama_available}")
            except Exception as e:
                logger.warning(f"⚠️ Ollama недоступен: {e}")
                self._ollama_available = False
        return self._ollama_available
    
    def check_deepseek_available(self) -> bool:
        """Проверка доступности DeepSeek API"""
        if self._deepseek_available is None:
            deepseek = self._import_deepseek()
            if deepseek and "check_available" in deepseek:
                self._deepseek_available = deepseek["check_available"]()
                logger.info(f"✅ DeepSeek доступен: {self._deepseek_available}")
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
        
        Args:
            preferred: Предпочтительный провайдер (если None, используется self.preferred_provider)
            
        Returns:
            Выбранный провайдер или None если нет доступных
        """
        preferred = preferred or self.preferred_provider
        available = self.get_available_providers()
        
        if not available:
            logger.error("❌ Нет доступных LLM провайдеров")
            return None
        
        # Если выбран AUTO, используем приоритет: Ollama -> DeepSeek
        if preferred == LLMProvider.AUTO:
            if LLMProvider.OLLAMA in available:
                return LLMProvider.OLLAMA
            elif LLMProvider.DEEPSEEK in available:
                return LLMProvider.DEEPSEEK
        
        # Если выбран конкретный провайдер, проверяем его доступность
        elif preferred in available:
            return preferred
        
        # Если предпочтительный недоступен, используем первый доступный
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
        **kwargs
    ) -> str:
        """
        Генерация ответа с автоматическим выбором провайдера
        
        Args:
            prompt: Пользовательский запрос
            model: Модель (если None, используется модель по умолчанию для провайдера)
            temperature: Креативность ответа (0.0-1.0)
            system: Системный промпт
            format: Формат ответа (например, "json")
            provider: Предпочтительный провайдер
            **kwargs: Дополнительные параметры
            
        Returns:
            Текст ответа от модели
        """
        selected_provider = self.select_provider(provider)
        
        if not selected_provider:
            return "Ошибка: нет доступных LLM провайдеров. Проверьте настройки Ollama или DeepSeek API."
        
        logger.info(f"Использую провайдер: {selected_provider.value}")
        
        try:
            if selected_provider == LLMProvider.OLLAMA:
                ollama = self._import_ollama()
                if ollama and "generate" in ollama:
                    # Для Ollama используем модель по умолчанию если не указана
                    model = model or CHAT_MODEL_WEAK
                    return ollama["generate"](
                        prompt=prompt,
                        model=model,
                        temperature=temperature,
                        system=system,
                        format=format,
                        **kwargs
                    )
            
            elif selected_provider == LLMProvider.DEEPSEEK:
                deepseek = self._import_deepseek()
                if deepseek and "generate" in deepseek:
                    # Для DeepSeek используем модель по умолчанию если не указана
                    model = model or DEEPSEEK_MODEL
                    return deepseek["generate"](
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
            
            # Пробуем другой провайдер в случае ошибки
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
        Генерация эмбеддинга с автоматическим выбором провайдера
        
        Args:
            text: Текст для эмбеддинга
            model: Модель для эмбеддинга
            provider: Предпочтительный провайдер
            
        Returns:
            Вектор эмбеддинга
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
                deepseek = self._import_deepseek()
                if deepseek and "generate_embedding" in deepseek:
                    model = model or "text-embedding"
                    return deepseek["generate_embedding"](text, model)
            
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


# Глобальный экземпляр универсального клиента
llm_client = LLMClient(preferred_provider=LLMProvider.AUTO)

# Функции для обратной совместимости
def generate(
    prompt: str,
    model: Optional[str] = None,
    temperature: float = 0.7,
    system: Optional[str] = None,
    format: str = None,
    **kwargs
) -> str:
    """Функция для обратной совместимости с существующим кодом"""
    # Проверяем на None
    if prompt is None:
        prompt = ""
    
    return llm_client.generate(
        prompt=prompt,
        model=model,
        temperature=temperature,
        system=system,
        format=format,
        **kwargs
    )

def generate_embedding(text: str, model: Optional[str] = None) -> List[float]:
    """Функция для обратной совместимости с существующим кодом"""
    return llm_client.generate_embedding(text=text, model=model)