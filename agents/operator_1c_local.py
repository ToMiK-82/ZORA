"""
Фоновый агент оператора 1С для автоматической проверки и обработки документов.
Наследует BaseBackgroundAgent и работает по расписанию в рабочее время.
"""

import asyncio
import logging
from datetime import datetime, time
from agents.base import BaseBackgroundAgent


class Operator1CLocal(BaseBackgroundAgent):
    """Фоновый агент оператора 1С для автоматической работы."""
    
    def __init__(self):
        super().__init__("operator_1c")
        self._last_check_time = None
        self._documents_processed = 0
        self._errors_count = 0
        self._initialize_connection()
    
    def _initialize_connection(self):
        """Инициализирует соединение с 1С (заглушка для тестирования)."""
        try:
            # Здесь будет реальная инициализация соединения с 1С
            # через COM, REST API или ODATA
            self.logger.info("✅ Соединение с 1С инициализировано (заглушка)")
            self._is_connected = True
        except Exception as e:
            self.logger.error(f"❌ Ошибка инициализации соединения с 1С: {e}")
            self._is_connected = False
    
    def _is_working_time(self) -> bool:
        """
        Проверяет, находится ли текущее время в рабочем интервале.
        Рабочее время: с 7:30 до 18:00 по будням.
        """
        now = datetime.now()
        
        # Выходные (суббота, воскресенье)
        if now.weekday() >= 5:
            return False
        
        # Рабочее время: с 7:30 до 18:00
        start = time(7, 30)
        end = time(18, 0)
        
        return start <= now.time() <= end
    
    async def execute(self):
        """Основная логика агента - проверка и обработка документов в 1С."""
        if not self._is_connected:
            self.logger.warning("⚠️ Соединение с 1С не установлено, пропускаем выполнение")
            return
        
        try:
            self.logger.info("🔍 Проверка документов в 1С...")
            
            # 1. Проверяем новые документы (заглушка)
            new_documents = await self._check_new_documents()
            
            if new_documents:
                self.logger.info(f"📄 Найдено {len(new_documents)} новых документов")
                
                # 2. Обрабатываем каждый документ
                for doc in new_documents:
                    await self._process_document(doc)
                    self._documents_processed += 1
                
                # 3. Сохраняем результаты
                await self._save_results(new_documents)
            else:
                self.logger.info("✅ Новых документов не найдено")
            
            # Обновляем время последней проверки
            self._last_check_time = datetime.now()
            
            # Логируем статистику
            current_time = datetime.now().strftime("%H:%M:%S")
            self.logger.info(f"✅ Проверка завершена в {current_time}. "
                           f"Обработано документов: {self._documents_processed}, "
                           f"Ошибок: {self._errors_count}")
            
            # Сохраняем результат в память
            await self._store_in_memory(new_documents)
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка выполнения задачи оператора 1С: {e}")
            self._errors_count += 1
            raise
    
    async def _check_new_documents(self):
        """Проверяет наличие новых документов в 1С (заглушка)."""
        # В реальной реализации здесь будет запрос к 1С
        # Например: проверка новых заказов, накладных, счетов
        
        # Заглушка для тестирования: возвращаем имитацию документов
        documents = []
        
        # С вероятностью 30% возвращаем "новые" документы
        import random
        if random.random() < 0.3:
            doc_types = ["Заказ покупателя", "Поступление товаров", "Счёт на оплату", "Накладная"]
            for i in range(random.randint(1, 3)):
                doc_type = random.choice(doc_types)
                documents.append({
                    "id": f"DOC-{datetime.now().strftime('%Y%m%d')}-{i+1}",
                    "type": doc_type,
                    "date": datetime.now().strftime("%d.%m.%Y"),
                    "number": f"{random.randint(1000, 9999)}",
                    "sum": random.randint(1000, 50000),
                    "status": "Новый"
                })
        
        return documents
    
    async def _process_document(self, document):
        """Обрабатывает один документ (заглушка)."""
        try:
            self.logger.info(f"🔄 Обработка документа {document['id']} ({document['type']})")
            
            # Имитация обработки
            await asyncio.sleep(1)
            
            # В реальной реализации здесь будет:
            # 1. Проверка документа на корректность
            # 2. Выполнение необходимых операций в 1С
            # 3. Обновление статуса документа
            
            document["processed"] = True
            document["processed_at"] = datetime.now().isoformat()
            
            self.logger.info(f"✅ Документ {document['id']} обработан")
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка обработки документа {document['id']}: {e}")
            document["error"] = str(e)
            self._errors_count += 1
    
    async def _save_results(self, documents):
        """Сохраняет результаты обработки (заглушка)."""
        # В реальной реализации здесь будет сохранение в БД или файл
        try:
            # Имитация сохранения
            await asyncio.sleep(0.5)
            
            summary = {
                "timestamp": datetime.now().isoformat(),
                "total_documents": len(documents),
                "successful": len([d for d in documents if d.get("processed", False)]),
                "failed": len([d for d in documents if "error" in d]),
                "documents": documents
            }
            
            self.logger.debug(f"📊 Результаты сохранены: {summary}")
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка сохранения результатов: {e}")
    
    async def _store_in_memory(self, documents):
        """Сохраняет информацию о работе в векторную память."""
        try:
            from memory import memory
            
            if documents:
                text = f"Обработано {len(documents)} документов в 1С:\n"
                for doc in documents:
                    text += f"- {doc['type']} №{doc['number']} на сумму {doc['sum']} руб.\n"
            else:
                text = "Проверка документов 1С выполнена, новых документов не найдено."
            
            memory.store(
                text=text,
                metadata={
                    "type": "background_task",
                    "agent": "operator_1c",
                    "timestamp": datetime.now().isoformat(),
                    "documents_count": len(documents),
                    "task": "check_documents"
                }
            )
            
        except Exception as e:
            self.logger.warning(f"Не удалось сохранить результат в память: {e}")
    
    def get_detailed_status(self) -> dict:
        """Возвращает расширенный статус агента."""
        base_status = self.get_status()
        
        # Добавляем информацию о рабочем времени и статистике
        now = datetime.now()
        is_working_time = self._is_working_time()
        
        base_status.update({
            "is_working_time": is_working_time,
            "is_connected": self._is_connected,
            "current_time": now.strftime("%H:%M:%S"),
            "weekday": now.strftime("%A"),
            "working_hours": "07:30-18:00 (пн-пт)",
            "last_check_time": self._last_check_time.isoformat() if self._last_check_time else None,
            "statistics": {
                "documents_processed": self._documents_processed,
                "errors_count": self._errors_count,
                "uptime_minutes": self._get_uptime_minutes()
            }
        })
        
        return base_status
    
    def _get_uptime_minutes(self):
        """Возвращает время работы агента в минутах."""
        if not self._running or not self._last_activity:
            return 0
        
        uptime = datetime.now() - self._last_activity
        return int(uptime.total_seconds() / 60)
    
    def stop(self):
        """Останавливает агента с сохранением состояния."""
        self.logger.info("🛑 Остановка агента оператора 1С...")
        super().stop()
        
        # Сохраняем статистику перед остановкой
        try:
            self.logger.info(f"📊 Итоговая статистика: "
                           f"обработано {self._documents_processed} документов, "
                           f"ошибок: {self._errors_count}")
        except Exception as e:
            self.logger.error(f"❌ Ошибка при сохранении статистики: {e}")


# Функция для тестирования агента
async def test_agent():
    """Тестирует работу агента оператора 1С."""
    print("🧪 Тестирование агента оператора 1С...")
    
    agent = Operator1CLocal()
    
    print(f"1. Имя агента: {agent.name}")
    print(f"2. Рабочее время сейчас: {agent._is_working_time()}")
    
    # Запускаем одну итерацию выполнения
    print("3. Запуск выполнения задачи...")
    try:
        await agent.execute()
        print("   ✅ Задача выполнена успешно")
    except Exception as e:
        print(f"   ❌ Ошибка выполнения: {e}")
    
    # Проверяем статус
    print("4. Статус агента:")
    status = agent.get_detailed_status()
    for key, value in status.items():
        if isinstance(value, dict):
            print(f"   {key}:")
            for k, v in value.items():
                print(f"     {k}: {v}")
        else:
            print(f"   {key}: {value}")
    
    print("\n✅ Тест завершён")


if __name__ == "__main__":
    # Настройка логирования для теста
    logging.basicConfig(level=logging.INFO)
    
    # Запуск теста
    asyncio.run(test_agent())