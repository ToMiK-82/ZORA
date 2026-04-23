"""
Пакет памяти для ZORA.
Экспортирует реализацию памяти на основе Qdrant.
"""

import logging
import sys
from typing import Dict, Any

# Импортируем Qdrant память с отложенной инициализацией
def _get_memory():
    """Отложенная загрузка памяти для избежания циклических импортов."""
    try:
        from .qdrant_memory import memory
        logging.info("✅ Память Qdrant загружена")
        return memory
    except Exception as e:
        logging.error(f"❌ Не удалось загрузить память Qdrant: {e}")
        
        # Создаём заглушку для памяти
        class DummyMemory:
            def __init__(self):
                self.logger = logging.getLogger("zora.memory.dummy")
                
            def store(self, text, metadata=None, agent=None, timestamp=None):
                self.logger.warning("Используется заглушка памяти. Данные не сохраняются.")
                return "dummy_id"
                
            def search(self, query, limit=5, agent=None, threshold=0.7):
                self.logger.warning("Используется заглушка памяти. Поиск не выполняется.")
                return []
                
            def clear(self):
                self.logger.warning("Используется заглушка памяти. Очистка не выполняется.")
            
            def delete_by_filter(self, filter_dict):
                self.logger.warning("Используется заглушка памяти. Удаление по фильтру не выполняется.")
        
        memory = DummyMemory()
        logging.warning("⚠️ Используется заглушка памяти. Функциональность памяти ограничена.")
        return memory

# Создаем ленивый объект памяти
class LazyMemory:
    """Ленивая загрузка памяти."""
    
    def __init__(self):
        self._memory = None
    
    def _ensure_loaded(self):
        if self._memory is None:
            self._memory = _get_memory()
    
    def store(self, text, metadata=None, agent=None, timestamp=None):
        self._ensure_loaded()
        return self._memory.store(text, metadata, agent, timestamp)
    
    def search(self, query, limit=5, agent=None, threshold=0.7):
        self._ensure_loaded()
        return self._memory.search(query, limit, agent, threshold)
    
    def clear(self):
        self._ensure_loaded()
        return self._memory.clear()
    
    def delete_by_filter(self, filter_dict: Dict[str, Any]):
        """
        Удаляет все точки, у которых в payload есть поля, совпадающие с filter_dict.
        Пример: memory.delete_by_filter({"path": "D:/file.py"})
        """
        self._ensure_loaded()
        return self._memory.delete_by_filter(filter_dict)

# Экспортируем память
memory = LazyMemory()
__all__ = ['memory']         