#!/usr/bin/env python3
"""Очистка памяти Qdrant"""

import sys
sys.path.insert(0, '.')

from memory.qdrant_memory import ZoraMemory
import logging

logging.basicConfig(level=logging.INFO)

def clear_memory():
    print("Очистка памяти Qdrant...")
    
    try:
        # Создаем объект памяти
        memory = ZoraMemory()
        
        # Очищаем коллекцию
        print("Очищаем коллекцию 'zora_memory'...")
        memory.clear()
        
        print("✅ Память успешно очищена!")
        
        # Проверяем, что коллекция пуста
        print("Проверяем состояние коллекции...")
        count = memory.count()
        print(f"Количество записей в коллекции: {count}")
        
        if count == 0:
            print("✅ Коллекция пуста, все готово для новой индексации.")
        else:
            print(f"⚠️ В коллекции осталось {count} записей.")
            
    except Exception as e:
        print(f"❌ Ошибка при очистке памяти: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    clear_memory()
